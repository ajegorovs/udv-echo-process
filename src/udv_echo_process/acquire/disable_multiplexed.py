"""One guarded press on the clipped popup's **Disable multiplexer** entry.

The clipped one-entry popup (158x43) only exists while the multiplexer is on, and its single
row is the operator's way back out. This command binds exactly one instrument window, reads the
popup the operator already opened, and presses **only** that measured entry once — never the
``Enable multiplexer`` toggle, never ``Record``, ``Stop`` or ``Clear``, and never a retry.

Ready-only
----------
The command starts from the strip's ``ready`` row: a recording in progress, an ambiguous row and
a block/view with a slider are refused before anything is read or written. **Ready means only
what the strip reports**: no recording in progress and no held or stored data in the row it
shows. Data the strip does not report — an invisible historical store, a block scrolled out of
the view, a recording started elsewhere — can still exist and is not inspected, so this is not a
claim that no data exists anywhere. The command takes no destructive action: it never presses
``Record``, ``Stop`` or ``Clear`` and reads or writes no data-store path.

Capture identity, not just freshness
------------------------------------
Both captures are pairs the reader itself claimed under this invocation's ``capture_dir`` (its
own exclusive ``capture-NNN`` run), never a path a caller passed and never the decision's run
reused as the licence. The licensing capture must additionally resolve the **same popup handle**
the decision capture bound, must be an ``entry_no_numeric`` pair (the settings and entry
contracts are never interchanged), and its two digests must be the pair's own frames. At the
press, the popup and entry rectangles are read **then**, from the same enumeration owner the
resolver uses, and the entry's live popup-relative rect must equal the licensed one — supplied or
stale geometry refuses with nothing posted.

What licenses the press
-----------------------
A **fresh capture taken in this same invocation** of the clipped shape, whose two frames agree
and whose digests were re-derived from the decoded pixels, must prove
``surface=MULTIPLEXER_ON_ENTRY``, the literal ``Desable multiplexer`` line
(``label=DESABLE_MULTIPLEXER``) and ``mode=VISUAL_ENABLED``. It must be ``live-bracketed`` /
``capture-digest-verified``, and its two digests must be the capture's **own** frames — a
retained ``mpx-mode-read`` directory, a bare attribution, or a mode mark copied from another
capture is never a licence to press.

Two captures, in this order, and they are distinct facts:

1. the **decision** capture, before anything is written: it establishes that this invocation may
   take on the obligation at all;
2. the **final licensing** capture, taken at the action boundary — *after* the obligation has
   been written durably (``O_EXCL`` + ``fsync``) and immediately before the one held press.

The target is bound by structure, never by handle reuse and never by the Enable toggle's
position: the popup must be the measured 158x43 panel, and exactly one **direct** ``TSp_Button``
child must own the measured entry label band :data:`…mode_marks.ENTRY_LABEL_BAND` inside it,
with the reader's own ``Disable multiplexer`` attribution. The action boundary re-asks the window
set, the strip row, the original bound root and that structural rule against the *fresh* capture,
verifies the child's live class and parent, and then posts one held press on the freshly
resolved handle. A stored handle from the decision capture is never pressed.

What stays unknown
------------------
``posted`` is ``"unknown"`` after a press: attempted is not delivered. ``post_mode`` is
``VISUAL_DISABLED`` **only** when a fresh settings-popup capture taken after the press proves the
``Enable multiplexer`` line on the full shape — the operator's popup must still be visible; this
command never opens it. Otherwise ``post_mode`` is ``UNKNOWN``, including when no settings
capture helper was supplied. A raised press leaves ``posted`` unknown; it is recorded, never
retried.

The live clipped-entry capture helper
-------------------------------------
A caller **must** supply ``capture_entry``. The production helper is the sibling-owned
``channels_read.read_channels(..., capture_dir=...)`` entry-shape support, and the parent wires
it once that owner's change lands. Until then no default exists here: this module never falls
back to a fabricated capture or to a settings-shaped one.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from udv_echo_process.acquire import mode_marks
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.channels_capture import (
    CAPTURE_ENTRY_NO_NUMERIC,
    CAPTURE_SETTINGS_NUMERIC,
)
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
    _PANEL_CLASSES,
    CAPTION_SOURCE,
    ChannelsRead,
    ChannelsSurface,
)
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.messages import _click_hold
from udv_echo_process.acquire.win32.tree import (
    _class_of,
    _parent_of,
    _visible_children,
    visible_main_windows,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DISABLE_CAPTION",
    "ENTRY_CLASS",
    "TRIAL_FILE_NAME",
    "DisableEntryTarget",
    "DisableMultiplexedResult",
    "DisableStage",
    "acquire_disable_multiplexed",
    "bind_disable_entry",
    "press_disable_entry",
]

#: The reader's caption attribution for the clipped entry (the painted string is ``Desable``).
DISABLE_CAPTION = "Disable multiplexer"
#: The only control class the entry row may be.
ENTRY_CLASS = "TSp_Button"
TRIAL_FILE_NAME = "disable-multiplexed-trial.json"

_FRESH_CONTEXT = "live-bracketed"
_FRESH_INTEGRITY = "capture-digest-verified"

PRESS_EVIDENCE = (
    "one press attempt with the strip's posted held-press recipe (WM_LBUTTONDOWN, hold, "
    "WM_LBUTTONUP) on the clipped entry's own handle, re-bound by structure — measured popup "
    "size, exactly one direct TSp_Button owning the entry label band, live class and parent — "
    "immediately before the press; never BM_CLICK, never a screen coordinate, never the Enable "
    "toggle's handle or position. Whether the message was delivered is unknown, so no field "
    "here claims a post"
)

HANDS_OFF = (
    "the operator must keep hands off the keyboard, mouse and instrument for the whole command: "
    "the popup must not move or be clicked, and no channel may change between the licensing "
    "capture and the posted press. The command states this requirement; it cannot enforce it"
)

OS_RACE = (
    "an operating-system race remains between the last read and the posted message: the "
    "application can move, repaint, or close that control in between, so the capture states the "
    "moment before the press and never a lock, and the post state stays unknown"
)

OPERATOR_WARNING = (
    "the operator must be present: a held press's delivery is unknown, this command never "
    "retries, and the mode after it is unknown until a fresh settings read proves it"
)

RELAY_WARNING = (
    "disabling stops relay cycling: with the multiplexer off the instrument no longer cycles "
    "channels. If a relay or recording was started elsewhere it may already have been "
    "interrupted; this command presses no Stop and performs no cleanup"
)

OBLIGATION_WARNING = (
    "the durable obligation is permanent: it records what was licensed, the press attempt and "
    "every fact that could not be established. It is never deleted or rewritten as a success, "
    "and a press that raises is recorded as an attempt of unknown delivery rather than retried"
)

NO_POST_CAPTURE = (
    "the mode after the press is unknown: no fresh settings-popup capture proved the disabled "
    "state, and this command never opens the Channels popup — read it from the operator's "
    "still-open popup or reopen Channels by hand"
)

BOUNDARY_DIAGNOSTIC = (
    "boundary_seconds is a monotonic measurement of the licensing capture and its checks taken "
    "immediately before the press: a diagnostic, not a security timeout and not an atomicity "
    "claim. No cap applies unless the caller passed max_boundary_seconds"
)

#: What ``press: not_attempted`` means *in this record*: as-of, never a claim about the future.
PRESS_STATE_AS_OF = (
    "as of this record's own write: no press had been attempted when it was written. This file "
    "is written once per phase and is never rewritten as a success; if a later phase cannot be "
    "recorded, this state is what remains on disk"
)

#: Scope of the strip's ``ready`` row — no held/store data *it reports*, not no data at all.
READY_ONLY_NOTE = (
    "the strip's ready row is the only store fact this command reads: it means the strip "
    "reports no held or stored data and no recording. Data the strip does not report — an "
    "invisible historical store, a block removed from the view, a recording started elsewhere — "
    "may still exist and is not inspected. This command takes no destructive action: it never "
    "presses Record, Stop or Clear and reads or writes no data-store path"
)


def _now_stamp() -> str:
    return datetime.now(tz=UTC).astimezone().isoformat()


def _reason(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__


def _relative(
    rect: Sequence[int], popup: Sequence[int]
) -> tuple[int, int, int, int]:
    left, top, right, bottom = (int(value) for value in rect)
    return (left - int(popup[0]), top - int(popup[1]), right - int(popup[0]), bottom - int(popup[1]))


def _contains(rect: Sequence[int], band: Sequence[int]) -> bool:
    return (
        rect[0] <= band[0]
        and rect[1] <= band[1]
        and band[2] <= rect[2]
        and band[3] <= rect[3]
    )


def _inside(rect: Sequence[int], size: tuple[int, int]) -> bool:
    return 0 <= rect[0] and 0 <= rect[1] and rect[2] <= size[0] and rect[3] <= size[1]


class DisableStage(str, Enum):
    """How far one invocation got — each member says what is established."""

    PRESSED = "pressed"
    PRESS_RAISED = "press_raised"
    #: The action boundary itself refused before posting: zero presses, nothing attempted.
    REFUSED = "refused"


class DisableEntryTarget(ValueModel):
    """The clipped popup's one measured entry row — structural identity, not a stored handle."""

    popup_hwnd: int
    popup_rect: tuple[int, int, int, int]
    hwnd: int
    #: Popup-relative rect of the button that owns the measured entry line.
    rect: tuple[int, int, int, int]
    attribution: str = DISABLE_CAPTION
    provenance: str = CAPTION_SOURCE
    #: The band the rect was held to, carried so a record says what licensed the binding.
    band: tuple[int, int, int, int] = mode_marks.ENTRY_LABEL_BAND
    kind: Literal["clipped_entry"] = "clipped_entry"


class DisableMultiplexedResult(ValueModel):
    """What the one guarded Disable press established, and everything it could not."""

    stage: DisableStage
    bound_target: WindowTarget
    popup_hwnd: int | None = None
    target_hwnd: int | None = None
    target_rect: tuple[int, int, int, int] | None = None
    target_attribution: str = DISABLE_CAPTION
    target_provenance: str = CAPTION_SOURCE
    capture_dir: str = ""
    old_label: str = ""
    old_mode: str = ""
    old_rolling: str = ""
    old_context: str = ""
    old_integrity: str = ""
    old_frame_digests: tuple[str, str] | None = None
    final_label: str = ""
    final_mode: str = ""
    final_rolling: str = ""
    final_context: str = ""
    final_integrity: str = ""
    final_frame_digests: tuple[str, str] | None = None
    final_capture_dir: str = ""
    boundary_seconds: float | None = None
    boundary_evidence: str = BOUNDARY_DIAGNOSTIC
    post_surface: str = "UNKNOWN"
    post_mode: Literal["VISUAL_DISABLED", "UNKNOWN"] = "UNKNOWN"
    post_capture_dir: str = ""
    post_capture_kind: str = ""
    #: The post-capture's **own** two frame digests, re-derived from the decoded pixels — the
    #: material association a caller checks before it may treat the disabled mode as verified.
    post_frame_digests: tuple[str, str] | None = None
    post_error: str = ""
    presses: int = 0
    press: Literal["not_attempted", "attempted"] = "not_attempted"
    posted: Literal["not_attempted", "unknown"] = "not_attempted"
    #: The obligation's own state on disk: ``pending`` means the pre-press record is the last
    #: durable statement (a later phase could not be written), so the press attempt is not in it.
    action: Literal["pending", "completed"] = "pending"
    obligation_open: bool = True
    press_state_as_of: str = PRESS_STATE_AS_OF
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
            f"disable multiplexed (stage {self.stage.value}, presses {self.presses}, "
            f"posted {self.posted}, post mode {self.post_mode}); "
            + "; ".join(self.restoration_owed)
        )


# ---------------------------------------------------------------------------------------------
# structural binding: measured popup, one direct TSp_Button, the entry label band
# ---------------------------------------------------------------------------------------------


def bind_disable_entry(
    report: ChannelsRead, children: Sequence[Mapping]
) -> DisableEntryTarget:
    """The clipped popup's one entry row, or a refusal naming the clause that failed.

    Identity is structural and local to the measured clipped shape:

    * the report resolved ``MULTIPLEXER_ON_ENTRY`` and its panel rectangle is exactly
      :data:`…mode_marks.ENTRY_SIZE`, with a handle;
    * the report is readable, carries the reader's ``Disable multiplexer`` attribution with the
      reader's provenance, and its entry row is explicitly bound to no action;
    * among the popup's **published direct children**, exactly one visible ``TSp_Button`` has a
      popup-relative rect that contains :data:`…mode_marks.ENTRY_LABEL_BAND` and stays inside the
      popup, and that button is the reader's entry handle.

    Caption order, an ordinal, the Enable toggle's coordinates and any stored handle are not
    identity. A tree that states no parent links is refused rather than read by containment,
    because "direct descendant" is exactly the clause being established.
    """
    if report.surface is not ChannelsSurface.MULTIPLEXER_ON_ENTRY:
        raise AcquisitionError(
            f"the popup reads {report.surface.value!r}, not the measured clipped one-entry "
            "shape: the Disable entry is bound only inside that popup — nothing was pressed"
        )
    popup = report.popup
    if popup is None or popup.hwnd is None or popup.rect is None:
        raise AcquisitionError(
            "the clipped popup's handle or rectangle did not resolve, so no entry can be held "
            "to the measured label band: nothing was pressed"
        )
    if popup.cls not in _PANEL_CLASSES:
        raise AcquisitionError(
            f"the resolved popup is class {popup.cls!r}, not a panel: nothing was pressed"
        )
    popup_rect = popup.rect.as_tuple()
    size = (popup_rect[2] - popup_rect[0], popup_rect[3] - popup_rect[1])
    if size != mode_marks.ENTRY_SIZE:
        raise AcquisitionError(
            f"the popup measures {size[0]}x{size[1]} where the clipped entry shape is "
            f"{mode_marks.ENTRY_SIZE[0]}x{mode_marks.ENTRY_SIZE[1]}: the measured band belongs "
            "to a different popup shape, so nothing was pressed"
        )
    if not report.readable or report.refusals:
        raise AcquisitionError(
            "the clipped popup did not read cleanly "
            f"({'; '.join(report.refusals) or 'readable is False'}): nothing was pressed"
        )
    entry = report.entry
    if entry is None or entry.hwnd is None:
        raise AcquisitionError(
            "the clipped popup states no single entry row with a handle: nothing was pressed"
        )
    if entry.action_bound is not False:
        raise AcquisitionError(
            "the reader's entry row is not marked as bound to no action: the report's contract "
            "changed, so nothing was pressed"
        )
    if entry.attribution.caption != DISABLE_CAPTION:
        raise AcquisitionError(
            f"the entry row reads {entry.attribution.caption!r} where the measured Disable "
            "attribution is required: nothing was pressed"
        )
    if not entry.attribution.provenance.strip():
        raise AcquisitionError(
            "the entry row states no caption provenance, so its attribution cannot be told "
            "apart from a caller's declaration: nothing was pressed"
        )

    popup_hwnd = int(popup.hwnd)
    band = mode_marks.ENTRY_LABEL_BAND
    rows = list(children)
    if not rows:
        raise AcquisitionError(
            "the popup's published direct children were not supplied, so 'exactly one direct "
            "TSp_Button owns the entry band' cannot be established: nothing was pressed"
        )
    direct: list[Mapping] = []
    for row in rows:
        parent = row.get("parent")
        if parent is None:
            raise AcquisitionError(
                "a published row states no parent, so direct descent cannot be established; "
                "nothing was pressed"
            )
        if int(parent) == popup_hwnd:
            direct.append(row)
    if not direct:
        raise AcquisitionError(
            f"no published row hangs directly off the popup {popup_hwnd}: nothing was pressed"
        )
    visible = [row for row in direct if bool(row.get("visible", True))]
    if not visible:
        raise AcquisitionError(
            "the popup publishes no visible direct child: nothing was pressed"
        )
    owning: list[tuple[Mapping, tuple[int, int, int, int]]] = []
    for row in visible:
        if row.get("cls") != ENTRY_CLASS:
            continue
        rect = row.get("rect")
        if rect is None or len(tuple(rect)) != 4:
            continue
        relative = _relative(rect, popup_rect)
        if _inside(relative, mode_marks.ENTRY_SIZE) and _contains(relative, band):
            owning.append((row, relative))
    if len(owning) != 1:
        rects = [
            _relative(row["rect"], popup_rect)
            for row in visible
            if row.get("cls") == ENTRY_CLASS and row.get("rect") is not None
        ]
        raise AcquisitionError(
            f"{len(owning)} direct {ENTRY_CLASS} child(ren) own the measured entry band "
            f"{band!r} inside the {mode_marks.ENTRY_SIZE[0]}x{mode_marks.ENTRY_SIZE[1]} popup "
            f"(rects {rects!r}) where exactly one may: nothing was pressed"
        )
    row, rect = owning[0]
    if int(row["hwnd"]) != int(entry.hwnd):
        raise AcquisitionError(
            f"the row that owns the measured entry band is hwnd {row['hwnd']} where the reader's "
            f"entry is {entry.hwnd}: the reading and the tree disagree, so nothing was pressed"
        )
    # The Enable toggle is a different control on a different popup shape. Refuse a row whose
    # geometry is the measured Enable line rather than the entry line, so a settings row can
    # never be pressed through the clipped contract.
    if rect == mode_marks.ENABLE_LABEL_BAND:
        raise AcquisitionError(
            "the bound rect is the measured Enable toggle line, not the clipped entry: nothing "
            "was pressed"
        )
    return DisableEntryTarget(
        popup_hwnd=popup_hwnd,
        popup_rect=popup_rect,
        hwnd=int(row["hwnd"]),
        rect=rect,
        band=band,
    )


# ---------------------------------------------------------------------------------------------
# capture contract
# ---------------------------------------------------------------------------------------------


def _capture_association(
    capture,
    what: str,
    *,
    root: Path,
    decision_run: str | None = None,
) -> None:
    """The capture's **own** claimed run under this invocation's root, with its own frames.

    The reader claims each pair in a fresh ``capture-NNN`` directory under the caller's path
    (``mkdir(exist_ok=False)``), so requiring the claimed run's parent to be this invocation's
    root binds the pixels to this run rather than to any path a caller passed. ``decision_run``
    names the decision capture's run: the licensing capture must be a *different* claim, because
    a pair taken before the obligation was written cannot also be the pair taken after it.
    """
    claim = "" if capture.directory is None else str(capture.directory).strip()
    if not claim:
        raise AcquisitionError(
            f"the capture {what} states no claimed run directory, so its frames have no "
            "association to this invocation: nothing was pressed"
        )
    claimed = Path(claim)
    if claimed.resolve().parent != root.resolve():
        raise AcquisitionError(
            f"the capture {what} was claimed at {claim!r}, outside this invocation's capture "
            f"root {str(root)!r}: a pair from elsewhere is never this run's evidence — nothing "
            "was pressed"
        )
    if decision_run is not None and claimed.resolve() == Path(decision_run).resolve():
        raise AcquisitionError(
            f"the capture {what} reuses the decision capture's run {claim!r}: the licensing pair "
            "must be its own capture taken after the obligation was written — nothing was pressed"
        )
    frames = tuple(capture.frames)[:2]
    if len(frames) != 2 or any(len(str(frame.digest)) != 64 for frame in frames):
        raise AcquisitionError(
            f"the capture {what} does not carry two genuine 64-character frame digests: "
            "nothing was pressed"
        )
    missing = [Path(str(frame.path)).name for frame in frames if not Path(str(frame.path)).is_file()]
    if missing:
        raise AcquisitionError(
            f"the capture {what} names frames that are not on disk {missing!r}, so its digests "
            "have no material association: nothing was pressed"
        )


def _verified_entry_capture(
    report: ChannelsRead,
    *,
    what: str,
    root: Path,
    decision_run: str | None = None,
) -> mode_marks.ModeMarkAttribution:
    """The fresh clipped capture's enabled evidence, or a refusal naming the clause."""
    capture = report.capture
    if capture is None:
        raise AcquisitionError(
            f"no capture was taken {what}: a disable press needs a fresh same-invocation "
            "clipped capture, never a retained directory and never an attribution alone — "
            "nothing was pressed"
        )
    if capture.capture_kind != CAPTURE_ENTRY_NO_NUMERIC:
        raise AcquisitionError(
            f"the capture {what} is {capture.capture_kind!r} where the clipped entry's "
            f"{CAPTURE_ENTRY_NO_NUMERIC!r} contract is mandatory: the settings and entry "
            "contracts are never interchanged — nothing was pressed"
        )
    if capture.status != "ok" or capture.stable is not True:
        reasons = "; ".join(capture.unknown_reasons) or "status is not ok or frames are unstable"
        raise AcquisitionError(
            f"the capture {what} is not a stable ok capture ({reasons}): nothing was pressed"
        )
    _capture_association(
        capture, what, root=root, decision_run=decision_run
    )
    mark = capture.visual_mode_mark
    if mark is None:
        raise AcquisitionError(
            f"the capture {what} carries no mode attribution (the live clipped capture helper "
            "must attribute the entry shape): nothing was pressed"
        )
    if (
        mark.surface != mode_marks.MULTIPLEXER_ON_ENTRY
        or mark.label != "DESABLE_MULTIPLEXER"
        or mark.mode != "VISUAL_ENABLED"
    ):
        raise AcquisitionError(
            f"the capture {what} reads surface={mark.surface!r} label={mark.label!r} "
            f"mode={mark.mode!r} where the clipped entry's enabled line is required: nothing was "
            "pressed"
        )
    if mark.rolling != "ABSENT":
        raise AcquisitionError(
            f"the capture {what} states rolling={mark.rolling!r}; the clipped popup structurally "
            "contains no rollover row, so an invented rolling state is not a measured one: "
            "nothing was pressed"
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
            f"recognition={mark.recognition!r}): retained or unverified evidence is not a "
            "precondition — nothing was pressed"
        )
    if mark.frame_digests is None or tuple(mark.frame_digests) != tuple(
        str(frame.digest) for frame in tuple(capture.frames)[:2]
    ):
        raise AcquisitionError(
            f"the capture {what} attributes digests that are not its own two frames: nothing "
            "was pressed"
        )
    return mark


def _verified_settings_disabled(
    report: ChannelsRead, *, what: str, target: WindowTarget, root: Path
) -> mode_marks.ModeMarkAttribution:
    """A fresh settings-popup capture that proves the disabled mode, or a refusal."""
    capture = report.capture
    if capture is None:
        raise AcquisitionError(
            f"no capture was taken {what}, so the mode is unknown rather than disabled"
        )
    if capture.capture_kind != CAPTURE_SETTINGS_NUMERIC:
        raise AcquisitionError(
            f"the capture {what} is {capture.capture_kind!r} where the full settings popup's "
            "contract is required: the entry and settings contracts are never interchanged"
        )
    if capture.status != "ok" or capture.stable is not True:
        reasons = "; ".join(capture.unknown_reasons) or "status is not ok or frames are unstable"
        raise AcquisitionError(f"the capture {what} is not a stable ok capture ({reasons})")
    _capture_association(capture, what, root=root)
    guards = capture.guards
    if not guards.consistent or guards.after is None:
        raise AcquisitionError(
            f"the capture {what} has window guards that do not agree across the pair: "
            + ("; ".join(guards.failures) or "no closing guard")
        )
    for guard in (guards.before, guards.after):
        if guard.hwnd != target.hwnd:
            raise AcquisitionError(
                f"the capture {what} has a {guard.label} guard on hwnd {guard.hwnd} where the "
                f"original binding is {target.hwnd}: a different window's settings popup proves "
                "nothing about this one"
            )
    mark = capture.visual_mode_mark
    if mark is None:
        raise AcquisitionError(f"the capture {what} carries no mode attribution")
    if (
        mark.surface != mode_marks.SETTINGS_FULL
        or mark.label != "ENABLE_MULTIPLEXER"
        or mark.mode != "VISUAL_DISABLED"
    ):
        raise AcquisitionError(
            f"the capture {what} reads surface={mark.surface!r} label={mark.label!r} "
            f"mode={mark.mode!r} where the full settings popup's disabled line is required"
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
            f"recognition={mark.recognition!r})"
        )
    if mark.frame_digests is None or tuple(mark.frame_digests) != tuple(
        str(frame.digest) for frame in tuple(capture.frames)[:2]
    ):
        raise AcquisitionError(
            f"the capture {what} attributes digests that are not its own two frames"
        )
    return mark


# ---------------------------------------------------------------------------------------------
# the narrow action boundary
# ---------------------------------------------------------------------------------------------


def press_disable_entry(
    *,
    target: WindowTarget,
    popup_hwnd: int,
    entry_hwnd: int,
    entry_rect: tuple[int, int, int, int],
) -> None:
    """Post one held press on the freshly bound clipped entry, and nothing else.

    A narrow target-bound entry point rather than a generic ``press(handle)``: the popup must be
    a panel hanging directly off the bound root, the entry must be a direct ``TSp_Button`` of
    that popup, the popup must still be the measured clipped size, and the entry's rect must
    contain the measured entry band and stay inside the popup. **Both rectangles are read
    here, now**, from the same enumeration owner the resolver uses — never taken from the
    licensing read as an assertion — so a popup that moved, resized or repainted an entry
    between the read and the press refuses with nothing posted. The licensed relative entry
    rect is the comparison, so stale geometry is a refusal rather than a press at an old place.
    """
    rows = _visible_children(int(target.hwnd))
    current = {
        int(row["hwnd"]): tuple(int(value) for value in row["rect"])
        for row in rows
        if row.get("hwnd") is not None and row.get("rect") is not None
    }
    popup_rect = current.get(int(popup_hwnd))
    if popup_rect is None:
        raise AcquisitionError(
            f"the popup {popup_hwnd} publishes no current rectangle at the press, so it is gone "
            "or hidden: nothing was posted"
        )
    size = (popup_rect[2] - popup_rect[0], popup_rect[3] - popup_rect[1])
    if size != mode_marks.ENTRY_SIZE:
        raise AcquisitionError(
            f"the popup measures {size[0]}x{size[1]} at the press where the clipped entry shape "
            f"is {mode_marks.ENTRY_SIZE[0]}x{mode_marks.ENTRY_SIZE[1]}: nothing was posted"
        )
    if _class_of(int(popup_hwnd)) not in _PANEL_CLASSES:
        raise AcquisitionError(
            f"hwnd {popup_hwnd} is not a panel, so it cannot be the clipped Channels popup: "
            "nothing was posted"
        )
    if _parent_of(int(popup_hwnd)) != int(target.hwnd):
        raise AcquisitionError(
            f"hwnd {popup_hwnd} does not hang off the bound root {target.hwnd}: nothing was "
            "posted"
        )
    if _class_of(int(entry_hwnd)) != ENTRY_CLASS:
        raise AcquisitionError(
            f"hwnd {entry_hwnd} is class {_class_of(int(entry_hwnd))!r}, not a {ENTRY_CLASS} "
            "entry: nothing was posted"
        )
    if _parent_of(int(entry_hwnd)) != int(popup_hwnd):
        raise AcquisitionError(
            f"hwnd {entry_hwnd} does not hang directly off the popup {popup_hwnd}, so it is not "
            "its entry row: nothing was posted"
        )
    current_entry = current.get(int(entry_hwnd))
    if current_entry is None:
        raise AcquisitionError(
            f"the entry {entry_hwnd} publishes no current rectangle at the press, so it is gone "
            "or hidden: nothing was posted"
        )
    relative = _relative(current_entry, popup_rect)
    if relative != entry_rect:
        raise AcquisitionError(
            f"the entry's current rectangle {relative!r} is not the licensed one {entry_rect!r} "
            "at the press: the popup moved, resized or repainted its row since the licensing "
            "read — nothing was posted"
        )
    if not _contains(relative, mode_marks.ENTRY_LABEL_BAND):
        raise AcquisitionError(
            f"the entry rect {relative!r} does not own the measured entry band "
            f"{mode_marks.ENTRY_LABEL_BAND!r}: nothing was posted"
        )
    if not _inside(relative, mode_marks.ENTRY_SIZE):
        raise AcquisitionError(
            f"the entry rect {relative!r} is outside the clipped popup: nothing was posted"
        )
    _click_hold(int(entry_hwnd))


@dataclass
class _Boundary:
    """What the boundary immediately before the press found — clauses, or a licence."""

    clauses: tuple[str, ...] = ()
    capture_dir: str = ""
    mark: mode_marks.ModeMarkAttribution | None = None
    entry: DisableEntryTarget | None = None
    seconds: float | None = None


def _published_children(roles: object, popup_hwnd: int) -> tuple[Mapping, ...]:
    """The resolver's published direct children of ``popup_hwnd``, with parent links.

    Only already-parsed rows are consumed: a row's own ``parent`` (published by the resolver) is
    the statement, with the role map's ``parent_of`` as the fallback. Nothing is re-enumerated.
    """
    if not isinstance(roles, dict):
        raise AcquisitionError(
            "the screen read published no role map, so the popup's direct children are unknown"
        )
    raw = roles.get("raw")
    if not isinstance(raw, (list, tuple)):
        raise AcquisitionError(
            "the screen read published no control rows, so the popup's direct children are "
            "unknown"
        )
    links = roles.get("parent_of") or {}
    out: list[Mapping] = []
    for row in raw:
        if not isinstance(row, Mapping) or row.get("hwnd") is None:
            continue
        parent = row.get("parent")
        if parent is None and isinstance(links, Mapping):
            parent = links.get(row.get("hwnd"))
        if parent is None:
            raise AcquisitionError(
                f"published row {row.get('hwnd')} states no parent: direct descent cannot be "
                "established"
            )
        # Normalise once, here: the resolver publishes the link in ``parent_of`` and the driver
        # copies it onto each row. A map read back from a capture may carry only the link, so the
        # row is completed from the same owner's statement — never re-derived downstream.
        if row.get("parent") is None:
            row = {**row, "parent": parent}
        out.append(row)
    return tuple(out)


def _final_boundary(
    live,
    target: WindowTarget,
    *,
    capture_fn: Callable[..., ChannelsRead],
    children_fn: Callable[[int], Sequence[Mapping]],
    directory: Path,
    decision_popup_hwnd: int,
    decision_run: str,
    enumerate_fn: Callable[[], Sequence[int]],
    class_name: str,
    windows: Sequence[int],
    clock: Callable[[], float],
    max_seconds: float | None,
) -> _Boundary:
    """Same root, ready strip, the **same popup**, a **new** capture and a structural re-bind."""
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
    except Exception as exc:  # noqa: BLE001 - a failed final capture refuses, never retries
        out.clauses = (f"the final capture could not be taken: {_reason(exc)}",)
        out.seconds = clock() - started
        return out
    capture = report.capture
    if capture is not None:
        out.capture_dir = capture.directory or str(directory)
        out.mark = capture.visual_mode_mark
    try:
        if report.popup is None or report.popup.hwnd is None:
            raise AcquisitionError(
                "the final read resolved no popup handle: nothing was pressed"
            )
        if int(report.popup.hwnd) != int(decision_popup_hwnd):
            raise AcquisitionError(
                f"the final read resolved popup {report.popup.hwnd} where the decision capture "
                f"bound {decision_popup_hwnd}: a different panel is not the popup this "
                "invocation licensed, so nothing was pressed"
            )
        entry = bind_disable_entry(report, children_fn(int(report.popup.hwnd)))
        out.entry = entry
        out.mark = _verified_entry_capture(
            report,
            what="at the action boundary",
            root=directory,
            decision_run=decision_run,
        )
    except AcquisitionError as exc:
        out.clauses = (str(exc),)
        out.seconds = clock() - started
        return out
    out.seconds = clock() - started
    if max_seconds is not None and out.seconds > max_seconds:
        allowed = f"{max_seconds:.3f}"
        clause = (
            f"the boundary took {out.seconds:.3f} s where the caller allowed {allowed} s "
            "between the licensing capture and the press"
        )
        out.clauses = (clause,)
    return out


# ---------------------------------------------------------------------------------------------
# the workflow
# ---------------------------------------------------------------------------------------------


def acquire_disable_multiplexed(
    *,
    capture_dir: Path | str,
    trial_record: Path | str,
    capture_entry: Callable[..., ChannelsRead],
    capture_settings: Callable[..., ChannelsRead] | None = None,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    popup_children: Callable[[int], Sequence[Mapping]] | None = None,
    class_name: str = MAIN_CLASS,
    stamp: Callable[[], str] = _now_stamp,
    clock: Callable[[], float] = time.monotonic,
    max_boundary_seconds: float | None = None,
    read_popup: Callable[..., ChannelsRead] | None = None,
    notes: list[str] | None = None,
) -> DisableMultiplexedResult:
    """Press the clipped Disable entry once from a fresh verified capture.

    ``capture_entry`` is **mandatory**: it is the production live clipped-entry capture helper
    (the sibling-owned ``read_channels`` entry-shape support, wired by the caller). There is no
    default and no fabricated fallback. ``capture_settings`` is optional and is used only for the
    post-press mode read; without it the post mode stays ``UNKNOWN``.
    """
    directory = Path(capture_dir)
    record_file = trial_record_file(trial_record, name=TRIAL_FILE_NAME)
    sink = notes if notes is not None else []
    live = (
        actuator
        if actuator is not None
        else Win32Actuator(note_sink=sink.append, allow_real_input=False)
    )
    read_fn = read_popup if read_popup is not None else read_channels
    children_fn: Callable[[int], Sequence[Mapping]] = (
        popup_children
        if popup_children is not None
        else (lambda hwnd: _published_children(getattr(live, "last_roles", None), hwnd))
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
    target = live.bind_target(int(windows[0]))
    clauses, _state = screen_clauses(
        live, target, windows, class_name=class_name, strip=_strip_not_recording
    )
    if clauses:
        raise AcquisitionError("; ".join(clauses))

    # (1) the decision capture: what licenses taking on the obligation at all.
    initial = capture_entry(live, target=target, capture_dir=directory)
    if initial.popup is None or initial.popup.hwnd is None:
        raise AcquisitionError(
            "the clipped popup resolved no handle: nothing was pressed"
        )
    decision = bind_disable_entry(initial, children_fn(int(initial.popup.hwnd)))
    old = _verified_entry_capture(initial, what="before the press", root=directory)
    decision_run = "" if initial.capture is None else str(initial.capture.directory or "")

    restoration = (
        (
            "read the mode back from a freshly reopened Channels popup: this command cannot "
            "infer that the application is disabled, and the pressed state is unverified"
        ),
        (
            "a raised or undelivered press is recorded, never retried: if the entry still reads "
            "Disable multiplexer, the operator decides whether to press it again"
        ),
        (
            "no Stop, Clear, Record or store action is taken by this command; any recording or "
            "relay already running elsewhere is the operator's to settle"
        ),
    )
    obligation = {
        "phase": "obligation",
        "command": "disable-multiplexed",
        "written_at": stamp(),
        "bound_target": target.model_dump(),
        "capture_dir": str(directory),
        "popup_hwnd": decision.popup_hwnd,
        "entry_hwnd": decision.hwnd,
        "entry_rect": list(decision.rect),
        "entry_band": list(decision.band),
        "popup_rect": list(decision.popup_rect),
        "target_attribution": decision.attribution,
        "target_provenance": decision.provenance,
        "old_label": old.label,
        "old_mode": old.mode,
        "old_rolling": old.rolling,
        "old_context": old.acquisition_context,
        "old_freshness": old.freshness,
        "old_integrity": old.integrity,
        "old_frame_digests": list(old.frame_digests or ()),
        "old_capture_dir": str(initial.capture.directory if initial.capture else directory),
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
        "operator_warning": OPERATOR_WARNING,
        "os_race": OS_RACE,
        "relay_warning": RELAY_WARNING,
        "obligation_warning": OBLIGATION_WARNING,
        "scope": "one held press on the clipped Disable entry; nothing else",
        "ready_only": READY_ONLY_NOTE,
        "presses": 0,
        "press": "not_attempted",
        "posted": "not_attempted",
        "action": "pending",
        "obligation_open": True,
        "press_state_as_of": PRESS_STATE_AS_OF,
        "restoration_owed": list(restoration),
    }
    # (2) the durable claim, and only then the narrow action boundary.
    claim_trial_record(record_file, obligation)

    boundary = _final_boundary(
        live,
        target,
        capture_fn=capture_entry,
        children_fn=children_fn,
        directory=directory,
        decision_popup_hwnd=decision.popup_hwnd,
        decision_run=decision_run,
        enumerate_fn=enumerate_fn,
        class_name=class_name,
        windows=windows,
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
                "action": "completed",
                "press_state_as_of": PRESS_STATE_AS_OF,
                "final_label": "" if final is None else final.label,
                "final_mode": "" if final is None else final.mode,
                "final_rolling": "" if final is None else final.rolling,
                "final_context": "" if final is None else final.acquisition_context,
                "final_integrity": "" if final is None else final.integrity,
                "final_frame_digests": list(
                    () if final is None or final.frame_digests is None else final.frame_digests
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

    entry = boundary.entry
    if entry is None:
        raise AcquisitionError(
            "the boundary licensed a press without a bound entry — internal refusal; nothing "
            "was pressed"
        )
    press_error = ""
    refusal = ""
    try:
        live.verify_bound_target(target)
        press_disable_entry(
            target=target,
            popup_hwnd=entry.popup_hwnd,
            entry_hwnd=entry.hwnd,
            entry_rect=entry.rect,
        )
    except AcquisitionError as exc:
        # A refusal from the press boundary happens *before* the message is posted: the live
        # geometry, class or parent no longer licenses it. That is zero presses, not an attempt.
        refusal = (
            f"the action boundary refused immediately before the press: {_reason(exc)}. "
            "No message was posted and nothing was retried"
        )
    except Exception as exc:  # noqa: BLE001 - a raised press is a fact, not a retry
        press_error = (
            f"the press raised {type(exc).__name__}: {_reason(exc)}; whether any message reached "
            "the control is unknown — this is not a report that nothing was pressed"
        )
    if refusal:
        presses, press_state, posted = 0, "not_attempted", "not_attempted"
        stage = DisableStage.REFUSED
    else:
        presses, press_state, posted = 1, "attempted", "unknown"
        stage = DisableStage.PRESS_RAISED if press_error else DisableStage.PRESSED

    # The post state is a read, never a claim. VISUAL_DISABLED needs a fresh full settings
    # capture; anything else — including an absent popup — is UNKNOWN, and nothing is opened.
    post_error = ""
    post_surface = "UNKNOWN"
    post_mode: Literal["VISUAL_DISABLED", "UNKNOWN"] = "UNKNOWN"
    post_capture_dir = ""
    post_capture_kind = ""
    post_frame_digests: tuple[str, str] | None = None
    try:
        post = read_fn(live, target=target)
        post_surface = post.surface.value
    except Exception as exc:  # noqa: BLE001 - an unreadable screen is a fact
        post_error = f"the screen could not be read after the press: {_reason(exc)}"
    else:
        if post.surface is not ChannelsSurface.SETTINGS_POPUP:
            post_error = (
                f"the popup reads {post.surface.value!r} after the press, so no settings surface "
                "is visible to prove the disabled mode. " + NO_POST_CAPTURE
            )
        elif capture_settings is None:
            post_error = (
                "no settings capture helper was supplied, so the visible settings popup was not "
                "photographed and its mode is not proved. " + NO_POST_CAPTURE
            )
        else:
            try:
                evidence = capture_settings(live, target=target, capture_dir=directory)
                _verified_settings_disabled(
                    evidence, what="after the press", target=target, root=directory
                )
                post_capture_dir = str(
                    evidence.capture.directory
                    if evidence.capture is not None and evidence.capture.directory
                    else ""
                )
                if evidence.capture is not None:
                    post_capture_kind = evidence.capture.capture_kind
                    frames = tuple(evidence.capture.frames)[:2]
                    if len(frames) == 2:
                        post_frame_digests = (
                            str(frames[0].digest),
                            str(frames[1].digest),
                        )
                post_mode = "VISUAL_DISABLED"
                post_error = ""
            except Exception as exc:  # noqa: BLE001 - an unproved mode stays unknown
                post_error = (
                    "the visible settings popup did not prove the disabled mode: "
                    f"{_reason(exc)}. " + NO_POST_CAPTURE
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
            "post_capture_dir": post_capture_dir,
            "post_capture_kind": post_capture_kind,
            "post_frame_digests": list(post_frame_digests or ()),
            "press_error": press_error,
            "post_error": post_error,
            "boundary_error": refusal,
            "final_label": final.label if final is not None else "",
            "final_mode": final.mode if final is not None else "",
            "final_rolling": final.rolling if final is not None else "",
            "final_context": final.acquisition_context if final is not None else "",
            "final_integrity": final.integrity if final is not None else "",
            "final_frame_digests": list(
                () if final is None or final.frame_digests is None else final.frame_digests
            ),
            "final_capture_dir": boundary.capture_dir,
            "boundary_seconds": boundary.seconds,
            "restoration_owed": list(restoration),
            "obligation_open": True,
            "action": "completed",
            "press_state_as_of": PRESS_STATE_AS_OF,
        }
    )
    record_error = update_trial_record(record_file, payload)
    observed = [
        f"read:popup={entry.popup_hwnd}",
        f"read:entry={entry.hwnd}",
        f"read:entry_rect={entry.rect!r}",
        f"read:mode={old.mode}",
        f"read:context={old.acquisition_context}/{old.integrity}",
        f"boundary:final={None if final is None else final.mode}",
        f"boundary:seconds={boundary.seconds!r}",
        f"post:surface={post_surface}/mode={post_mode}",
    ]
    return DisableMultiplexedResult(
        stage=stage,
        bound_target=target,
        popup_hwnd=entry.popup_hwnd,
        target_hwnd=entry.hwnd,
        target_rect=entry.rect,
        target_attribution=entry.attribution,
        target_provenance=entry.provenance,
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
        post_capture_dir=post_capture_dir,
        post_capture_kind=post_capture_kind,
        post_frame_digests=post_frame_digests,
        post_error=post_error,
        presses=presses,
        press=press_state,
        posted=posted,
        action="pending" if record_error else "completed",
        obligation_open=True,
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
                OPERATOR_WARNING,
                OBLIGATION_WARNING,
                RELAY_WARNING,
                press_error,
                post_error,
                refusal,
            )
            if item
        ),
    )
