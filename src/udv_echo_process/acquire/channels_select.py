"""One guarded press on the ``Channels`` popup's **top radio row**: select one channel, once.

The row this command presses is the ten-cell ``TSp_Button`` strip that sits beside the
``Use only channel`` toggle — the reader's ``use_only_channel`` attribution. It is *not* the
standalone ``Use channels`` tick row below it: those cells are a different control with a
different meaning, and the two are separated here by attribution and by disjoint handle sets,
never by pixel order or by counting buttons. A tree that shows one strip, a duplicated ordinal,
a cell with no handle, or a shared handle set is a named refusal with **zero presses**.

The narrow authority, in the same shape as the sibling numeric writers:

* **strict arguments.** ``expect_channel`` is the channel the *operator declares* the popup is
  currently on. It is a **declaration, not a reading**: the ticked radio is painted glyph, the
  tree states no state (``ChannelCell.state`` is ``Literal["UNKNOWN"]``), so nothing downstream
  may quote it as measured. ``channel`` is the cell to press, restricted to
  :data:`SELECTABLE_CHANNELS` — the channels whose painted label an operator can corroborate by
  eye from the crops. ``expect_start_channel`` is a second declaration that *is* checkable,
  because the ``Start the sequence by using channel`` combo states text; a mismatch refuses. The
  declarations are channels ``1``..``10`` and must be integers (``True`` is not one);
  ``restore_channel`` is **required and explicit** — the trial's original is never defaulted from
  ``--expect-channel``, because that would record a restoration the operator never declared.
* **preconditions before the press.** Exactly one instrument window, bound once; the shared
  screen clauses (single binding, caption, no overlay/dialog, ready row); a full settings popup
  that resolved with no refusal; the declared start channel equal to the field's own text; and
  a complete, disjoint ten-cell top radio row whose ordinal ``channel`` resolves to exactly one
  handle. Then the whole preflight is asked **again on a fresh enumeration immediately before
  the press**, and a moved window, popup or field refuses with zero presses.
* **one press, held, through the narrow helper.** Exactly one
  ``live.press_channel_cell`` — ``RecordingSurface``'s target-bound entry point, which re-checks
  the binding, the popup, the row and the cell's ordinal live at the action boundary and then
  posts one held ``WM_LBUTTONDOWN`` / ``WM_LBUTTONUP``. There is no "press any handle" facade on
  that surface and this command adds none: never ``BM_CLICK``, never a coordinate, never a retry,
  and never a second press of any kind. **Attempted is not posted**: a press that raises leaves
  ``posted`` ``"UNKNOWN"``, the stage is ``press_raised`` (never ``pressed``), and the exit code
  is non-zero — an exception from the primitive proves neither that the message went out nor
  that it did not.
* **a durable obligation before acting, and only once the press is settled.** The record is
  claimed exclusively **after** the fresh preflight and the final bound-target check, and
  **before** the press. It carries the full bound target (handle, thread, process, class), the
  popup, row, cell handle and ordinal, and the popup's *readable* numeric state at that moment
  (repeat, start channel, apply-from, per-channel amounts). A record that cannot be claimed
  refuses the press, and nothing was pressed. Every pre-action refusal before the claim therefore
  leaves **no** record: there is no obligation to read, because no gesture was ever pending. One
  record per invocation; a forward select and its restore select are two records, each declaring
  the same original channel and the same declared source.
* **no claim of a selection.** The press is a gesture, not a read: ``selection`` is
  ``"UNKNOWN"`` on every outcome, ``native_proof`` is ``False`` by construction, and the
  post-press reading is a *bracketing* of the popup's numeric facts — it can show the popup
  still up and the amounts unchanged, never which radio is ticked. An operator's or a
  capture's visual corroboration is accepted only as a separate, explicitly labelled post-hoc
  observation (``visual_corroboration``), never as the command's own evidence, and it grants no
  action authority to the vision layer: the attribution type that carries a caption states
  ``action_authority: Literal[False]`` (``caption_band.CaptionAttribution``), so a visual reading
  can never become a press.
* **expected post-state changes are not errors.** The channel's own profile counts may change
  when the operator selects another channel; every readable fact that moved is reported as
  evidence, and nothing is repaired, re-pressed or "cleaned up".

Never pressed here: the ``Use channels`` tick row, the amount fields or their two action
buttons, a toggle, the menu, ``Enable``, ``Record``, ``Stop`` or ``Clear``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field

from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.channels_read import read_channels
from udv_echo_process.acquire.channels_repeat import (
    MPX_DISABLED_STATEMENT,
    _strip_not_recording,
    claim_trial_record,
    trial_record_file,
    update_trial_record,
)
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.store_completed import screen_clauses
from udv_echo_process.acquire.ui.channels import (
    STRIP_SIZE,
    USE_CHANNELS,
    USE_ONLY_CHANNEL,
    ChannelCell,
    ChannelsRead,
    ChannelsSurface,
)
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "LOWER_STRIP",
    "PRESS_EVIDENCE",
    "SELECTABLE_CHANNELS",
    "SELECTION_EVIDENCE",
    "TOP_STRIP",
    "TRIAL_FILE_NAME",
    "ChannelSelectResult",
    "SelectStage",
    "acquire_select_channel",
]

#: The radio row beside ``Use only channel`` — a channel *selection*, one of ten. The string is
#: the reader's own attribution (:data:`…ui.channels.USE_ONLY_CHANNEL`); this module names it, it
#: does not hold a second copy.
TOP_STRIP = USE_ONLY_CHANNEL

#: The tick row below it — a different control, and never this command's target.
LOWER_STRIP = USE_CHANNELS

#: Channels whose painted label an operator can corroborate from the committed crops. A wider
#: set needs a measured label mapping first; anything outside this tuple is refused.
SELECTABLE_CHANNELS: tuple[int, ...] = (1, 2, 10)

#: The record's file name when ``--trial-record`` names a directory.
TRIAL_FILE_NAME = "channels-select-trial.json"

#: Why the press is a gesture and not a proof of a selection.
SELECTION_EVIDENCE = (
    "the radio cells are custom buttons that paint their tick: the tree states no state for "
    "any of them (ChannelCell.state is UNKNOWN), so the selected channel after the press is "
    "unknown here until an operator states it or a retained capture is read"
)

#: What the one press is — the *attempt*, never a claimed delivery.
PRESS_EVIDENCE = (
    "one press attempt with the strip's posted held-press recipe (WM_LBUTTONDOWN, hold, "
    "WM_LBUTTONUP) on the cell's own handle, re-resolved immediately before the press; never "
    "BM_CLICK and never a screen coordinate. Whether the message was delivered is unknown, so "
    'no evidence field here claims a post: "posted" is the primitive\'s attempt state and '
    "nothing more"
)


def _now_stamp() -> str:
    """The record's wall-clock stamp: timezone-aware ISO 8601, local, per repository convention."""
    return datetime.now(tz=UTC).astimezone().isoformat()


class SelectStage(str, Enum):
    """How far one invocation got — each member says what is *established*, not what was tried."""

    #: The declaration already names the target: read, reported, and deliberately not pressed.
    NO_OP = "no_op"
    #: The one press returned without raising. That it *posted* is still unknown; the selection
    #: is unknown on every path.
    PRESSED = "pressed"
    #: The press primitive raised. Whether a message reached the control is **unknown**, so this
    #: is never reported as ``pressed`` and never retried.
    PRESS_RAISED = "press_raised"


class ChannelSelectResult(ValueModel):
    """What one guarded selection established, what it could not, and what the operator owes."""

    stage: SelectStage
    bound_target: WindowTarget
    popup_hwnd: int | None = None
    #: The operator's declaration of the channel the popup was on before this invocation.
    expect_channel: int
    #: The channel this invocation pressed.
    channel: int
    #: The trial's original, as the operator **declared** it; never defaulted from ``expect``.
    restore_to: int
    #: Where ``restore_to`` came from: an explicit declaration, always.
    restore_source: Literal["declared"] = "declared"
    #: The declared ``Start the sequence by using channel`` value, checked against the field.
    expect_start_channel: int
    #: The cell's own handle, the strip panel that owns it, and its position on that row.
    target_hwnd: int | None = None
    row_hwnd: int | None = None
    target_strip: str = TOP_STRIP
    target_ordinal: int | None = None
    #: The cell's **owner provenance**: the attribution the reader gave it, quoted verbatim.
    target_attribution: str = ""
    #: Every readable numeric fact before the press (popup order), and after it.
    old_facts: dict[str, str] = Field(default_factory=dict)
    new_facts: dict[str, str] = Field(default_factory=dict)
    #: Facts that differ after the press — expected for a channel switch; evidence, never an error.
    facts_moved: tuple[str, ...] = ()
    #: Facts the earlier read stated and the post-press read did not: unknown, never "gone".
    facts_unreadable: tuple[str, ...] = ()
    #: Always ``UNKNOWN``: the press proves a gesture, never a tick.
    selection: Literal["UNKNOWN"] = "UNKNOWN"
    selection_evidence: str = SELECTION_EVIDENCE
    #: Always ``False``: no native text ever states which radio is set.
    native_proof: Literal[False] = False
    #: A post-hoc operator/capture observation, reported separately and never as this command's.
    visual_corroboration: str = ""
    #: How many times the press primitive was **called** — an attempt, never a post.
    presses: int = 0
    #: ``attempted`` once the primitive was called; it says nothing about delivery.
    press: Literal["not_attempted", "attempted"] = "not_attempted"
    #: Never ``"posted"``: no return value of a posted message proves it was delivered.
    posted: Literal["not_attempted", "unknown"] = "not_attempted"
    press_error: str = ""
    post_error: str = ""
    press_evidence: str = PRESS_EVIDENCE
    #: ``not_pressed`` when nothing was posted; otherwise **unknown**, always.
    persisted: Literal["unknown", "not_pressed"] = "not_pressed"
    #: The owed gesture before this trial is closed, in words: it never names an executor.
    restoration_owed: tuple[str, ...] = ()
    trial_record: Path | None = None
    trial_record_phase: Literal["", "obligation", "after"] = ""
    trial_record_error: str = ""
    observed: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        """One log line: the press, the facts that moved, and what is still owed."""
        head = (
            f"channels select {self.expect_channel} -> {self.channel} "
            f"(stage {self.stage.value}, presses {self.presses}, posted {self.posted}, "
            "selection unknown)"
        )
        moved = (
            f"facts moved: {'; '.join(self.facts_moved)}" if self.facts_moved else ""
        )
        parts = [part for part in (head, moved, *self.restoration_owed) if part]
        return "; ".join(parts)


# ---------------------------------------------------------------------------------------------
# arguments and structure
# ---------------------------------------------------------------------------------------------


def _declared_channel(label: str, value: object) -> int:
    """A channel the operator **declares**: a strict integer in ``1..STRIP_SIZE``, else refuse.

    A declaration is checked against the row the popup paints and nothing more: any channel on
    the ten-cell row can be declared, because declaring a state is not pressing it. ``True`` is
    not an integer here — it would otherwise pass as channel 1.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise AcquisitionError(
            f"{label} must be an integer channel, not {value!r}: nothing was pressed"
        )
    if not 1 <= value <= STRIP_SIZE:
        raise AcquisitionError(
            f"{label} {value} is outside the channels this row paints (1..{STRIP_SIZE}): "
            "nothing was pressed"
        )
    return value


def _press_target(label: str, value: object) -> int:
    """The cell this invocation may **press**: a declared channel, and one of the measured set.

    The narrow set is the press authority's, not the declaration's: a wider target needs a
    measured label mapping first, so an ordinal outside :data:`SELECTABLE_CHANNELS` refuses.
    """
    channel = _declared_channel(label, value)
    if channel not in SELECTABLE_CHANNELS:
        raise AcquisitionError(
            f"{label} {channel} is outside the channels this command presses "
            f"{list(SELECTABLE_CHANNELS)}: a wider set needs a measured label mapping first, so "
            "nothing was pressed"
        )
    return channel


def _require_mpx_disabled(declared: object) -> None:
    """The operator's multiplexer-off statement is an argument, not an inference."""
    if declared is not True:
        raise AcquisitionError(
            f"--mpx-disabled was not declared ({declared!r}): {MPX_DISABLED_STATEMENT}"
        )


def _strip_cells(report: ChannelsRead) -> dict[str, dict[int, ChannelCell]]:
    """The popup's strips by attribution, **both present** — the one thing this command adds.

    Completeness, geometry, ordinal ordering and the refusal of a handle shared between the two
    rows are the *reader's*
    (:func:`~udv_echo_process.acquire.ui.channels.strip_cells` and the alias clause in
    ``resolve_channels``), so they are not re-derived here: a report that states them is trusted,
    and a tree that fails them never reaches this function as a readable settings popup. What is
    local is the selection question only: the top radio row cannot be told from the tick row
    when its sibling is missing, so a single-strip surface refuses here. Nothing reads a rect or
    a tick.
    """
    strips: dict[str, dict[int, ChannelCell]] = {}
    for cell in report.channel_ticks:
        if cell.strip not in {TOP_STRIP, LOWER_STRIP}:
            raise AcquisitionError(
                f"a channel cell is attributed to the unknown strip {cell.strip!r}: the two "
                "strips this command can tell apart are "
                f"{[TOP_STRIP, LOWER_STRIP]}; nothing was pressed"
            )
        strips.setdefault(cell.strip, {})[cell.index] = cell
    if set(strips) != {TOP_STRIP, LOWER_STRIP}:
        raise AcquisitionError(
            f"the popup resolved strips {sorted(strips)} where both {TOP_STRIP!r} (the radio "
            f"row) and {LOWER_STRIP!r} (the tick row) are required: the top row cannot be "
            "identified against a missing sibling, so nothing was pressed"
        )
    return strips


def _facts(report: ChannelsRead) -> dict[str, str]:
    """The popup's readable numeric facts, in popup order: evidence, never a selection state."""
    out: dict[str, str] = {}
    for name in ("repeat", "start_channel", "apply_from"):
        slot = getattr(report, name)
        if slot is not None:
            out[name] = slot.text
    if report.per_channel is not None:
        out["profiles"] = report.per_channel.profiles.text
        out["seconds"] = report.per_channel.seconds.text
    return out


def _moved(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        f"{key}: {before[key]!r} -> {after[key]!r}"
        for key in before
        if key in after and after[key] != before[key]
    )


def _unreadable(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    return tuple(f"{key} (was {before[key]!r})" for key in before if key not in after)


def _settings_read(live, target: WindowTarget, *, what: str) -> ChannelsRead:
    """One reading of the operator-opened popup against the *existing* binding."""
    report = read_channels(live, target=target)
    if report.surface is not ChannelsSurface.SETTINGS_POPUP or report.popup is None:
        raise AcquisitionError(
            f"the Channels popup is not the full settings surface {what} (surface "
            f"{report.surface.value!r}, popup {None if report.popup is None else report.popup.hwnd}): "
            "this command presses the top radio row only inside that popup — nothing was pressed"
        )
    if not report.readable or report.refusals:
        raise AcquisitionError(
            f"the settings popup did not read cleanly {what} "
            f"({'; '.join(report.refusals) or 'readable is False'}): nothing was pressed"
        )
    return report


# ---------------------------------------------------------------------------------------------
# the workflow
# ---------------------------------------------------------------------------------------------


def acquire_select_channel(
    *,
    expect_channel: int,
    channel: int,
    expect_start_channel: int,
    restore_channel: int,
    mpx_disabled: bool,
    trial_record: Path | str,
    visual_corroboration: str = "",
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    stamp: Callable[[], str] = _now_stamp,
    notes: list[str] | None = None,
) -> ChannelSelectResult:
    """Press the popup's top radio row once at ``channel`` and say what stays unknown.

    Everything is settled before the press: the arguments, the operator's mode declaration, the
    record path, the single window binding, the shared screen clauses, the full settings popup,
    the declared start channel against the field's text, and the complete top row the reader
    resolved. Those clauses are asked **again on a fresh enumeration immediately before the
    press**; the target is then verified once more against the binding, and only then is the
    obligation claimed. Any refusal on them raises
    :class:`~udv_echo_process.acquire.driver.AcquisitionError` having pressed nothing and having
    written no record.

    After the press every outcome is returned, never raised: a raised press primitive, a closed
    popup, an unreadable field and a moved amount are facts for the operator, and none of them
    triggers a retry or a second press. ``selection`` stays ``"UNKNOWN"`` on every path, and
    ``posted`` is never claimed: a call that returned is an attempt, a call that raised is an
    attempt whose delivery is unknown.
    """
    expect_channel = _declared_channel("expect_channel", expect_channel)
    channel = _press_target("channel", channel)
    expect_start_channel = _declared_channel(
        "expect_start_channel", expect_start_channel
    )
    # No default: the trial's original is a declaration of its own. Defaulting it from
    # ``expect_channel`` would silently record a restoration nobody declared, and a restore run
    # would then owe an undo of itself.
    restore_to = _declared_channel("restore_channel", restore_channel)
    _require_mpx_disabled(mpx_disabled)
    no_op = expect_channel == channel
    record_file = trial_record_file(trial_record, name=TRIAL_FILE_NAME)

    sink = notes if notes is not None else []
    # Posted messages only, and no cursor is touched: the one real-input step is refused by
    # construction rather than merely not called.
    live = (
        actuator
        if actuator is not None
        else Win32Actuator(note_sink=sink.append, allow_real_input=False)
    )
    if enumerate_windows is None:
        enumerate_windows_fn: Callable[[], Sequence[int]] = lambda: tuple(
            visible_main_windows(class_name)
        )
    else:
        enumerate_windows_fn = enumerate_windows
    windows = tuple(enumerate_windows_fn())
    if len(windows) != 1:
        raise AcquisitionError(
            f"{len(windows)} visible {class_name} window(s) are up {list(windows)}: exactly one "
            "application must be running, and this command does not choose between copies"
        )
    target = live.bind_target(int(windows[0]))
    clauses, _state = screen_clauses(
        live, target, windows, class_name=class_name, strip=_strip_not_recording
    )
    if clauses:
        raise AcquisitionError("; ".join(clauses))

    report = _settings_read(live, target, what="before the press")
    start = report.start_channel
    if start is None or start.value is None:
        raise AcquisitionError(
            "the popup's start-channel field did not resolve to a number, so the declared "
            "start channel cannot be checked: nothing was pressed"
        )
    start_value = start.value
    if isinstance(start_value, bool) or not isinstance(start_value, int):
        raise AcquisitionError(
            f"the popup's start-channel field reads {start.text!r}, which is not an integer "
            "channel: nothing was pressed"
        )
    if not 1 <= start_value <= STRIP_SIZE or start_value != expect_start_channel:
        raise AcquisitionError(
            f"the popup reads start channel {start.text!r} ({start.value!r}) where "
            f"--expect-start-channel {expect_start_channel} was declared (the row states "
            f"1..{STRIP_SIZE}); nothing was pressed — re-read the field and declare what it states"
        )
    cell = _strip_cells(report)[TOP_STRIP][channel]
    if (
        cell.hwnd is None or cell.owner_hwnd is None
    ):  # the reader refuses both; keep it honest
        raise AcquisitionError(
            "the target cell or its owning strip panel resolved no handle: nothing was pressed"
        )
    popup_hwnd = report.popup.hwnd if report.popup is not None else None
    if popup_hwnd is None:
        raise AcquisitionError(
            "the settings popup resolved no handle, so the cell's descent cannot be stated: "
            "nothing was pressed"
        )
    cell_hwnd, row_hwnd = int(cell.hwnd), int(cell.owner_hwnd)
    before = _facts(report)
    observed = [
        f"read:popup={popup_hwnd}",
        f"read:row={row_hwnd}",
        f"read:{TOP_STRIP}[{cell.index}]={cell_hwnd}",
        f"read:start_channel={start.text}/{start.value}",
    ]
    restoration: tuple[str, ...] = ()
    if channel != restore_to:
        # The obligation is the *gesture*, so it names no executor: the operator can take it, and
        # so can a further supervised invocation of this same command (that is what the accepted
        # 1 -> 2 -> 1 trial did). Saying "by hand" recorded a method nobody had established and
        # misdescribed a restoration the automation itself performed.
        restoration = (
            (
                f"select channel {restore_to} again on the top radio row: the declaration before "
                "this trial named it as the original, and no reading can confirm either the old "
                "or the new tick (this is the owed gesture, not a finger: the operator or a "
                "further supervised invocation of this command takes it)"
            ),
        )

    def result(**kwargs) -> ChannelSelectResult:
        """One result assembled from what this invocation established, with the fixed limits."""
        base = {
            "bound_target": target,
            "popup_hwnd": popup_hwnd,
            "expect_channel": expect_channel,
            "channel": channel,
            "restore_to": restore_to,
            "expect_start_channel": expect_start_channel,
            "target_hwnd": cell_hwnd,
            "row_hwnd": row_hwnd,
            "target_ordinal": cell.index,
            "target_attribution": cell.attribution.caption,
            "old_facts": before,
            "visual_corroboration": visual_corroboration,
            "observed": tuple(observed),
        }
        base.update(kwargs)
        return ChannelSelectResult(**base)

    if no_op:
        return result(
            stage=SelectStage.NO_OP,
            new_facts=dict(before),
            presses=0,
            persisted="not_pressed",
            notes=tuple(getattr(live, "warnings", ())),
        )

    # Fresh preflight immediately before the press: the tree is re-enumerated and the cell, its
    # row, its popup and the facts must be the ones this press was decided on.
    fresh_windows = tuple(enumerate_windows_fn())
    if fresh_windows != windows:
        raise AcquisitionError(
            f"the window set changed between the reading and the press ({list(windows)} -> "
            f"{list(fresh_windows)}): nothing was pressed"
        )
    fresh_clauses, _fresh_state = screen_clauses(
        live,
        target,
        fresh_windows,
        class_name=class_name,
        strip=_strip_not_recording,
    )
    if fresh_clauses:
        raise AcquisitionError(f"{'; '.join(fresh_clauses)} — nothing was pressed")
    fresh = _settings_read(live, target, what="immediately before the press")
    fresh_cell = _strip_cells(fresh)[TOP_STRIP][channel]
    if (fresh_cell.hwnd, fresh_cell.owner_hwnd, fresh.popup and fresh.popup.hwnd) != (
        cell_hwnd,
        row_hwnd,
        popup_hwnd,
    ):
        raise AcquisitionError(
            f"the top-row cell, its row or its popup changed under the read ({cell_hwnd}/"
            f"{row_hwnd}/{popup_hwnd} -> {fresh_cell.hwnd}/{fresh_cell.owner_hwnd}/"
            f"{fresh.popup and fresh.popup.hwnd}): nothing was pressed"
        )
    if _facts(fresh) != before:
        raise AcquisitionError(
            f"the popup's readable state changed under the read ({_facts(fresh)!r} where "
            f"{before!r}): nothing was pressed"
        )
    # The binding's own live identity, asked last and before the record: a window that moved
    # since the read is a refusal with no press and no obligation on disk.
    live.verify_bound_target(target)

    # The durable obligation, claimed only now — the press is settled and imminent, so a record
    # cannot exist for a gesture that this invocation then refused to take.
    obligation = {
        "phase": "obligation",
        "command": "channels-select",
        "written_at": stamp(),
        "bound_target": target.model_dump(),
        "popup_hwnd": popup_hwnd,
        "row_hwnd": row_hwnd,
        "cell_hwnd": cell_hwnd,
        "target_strip": TOP_STRIP,
        "target_ordinal": cell.index,
        "target_attribution": cell.attribution.caption,
        "expect_channel": expect_channel,
        "channel": channel,
        "restore_to": restore_to,
        "restore_source": "declared",
        "expect_start_channel": expect_start_channel,
        "mpx_disabled_statement": MPX_DISABLED_STATEMENT,
        "facts_before": before,
        "facts_unreadable": [],
        "selection": "UNKNOWN",
        "selection_evidence": SELECTION_EVIDENCE,
        "visual_corroboration": visual_corroboration,
        "presses": 0,
        "press": "not_attempted",
        "posted": "not_attempted",
        "obligation_open": False,
        "restoration_owed": list(restoration),
    }
    claim_trial_record(record_file, obligation)

    press_error = ""
    try:
        live.press_channel_cell(
            target=target,
            popup_hwnd=popup_hwnd,
            row_hwnd=row_hwnd,
            cell_hwnd=cell_hwnd,
            ordinal=cell.index,
        )
    except Exception as exc:  # noqa: BLE001 - a raised press is a fact, not a retry
        press_error = (
            f"the press raised {type(exc).__name__}: {exc}; whether any message reached the "
            "control is unknown — this is not a report that nothing was pressed"
        )
    # An attempt, not a post: the primitive's return proves neither delivery nor a tick.
    presses, press_state, posted = 1, "attempted", "unknown"
    stage = SelectStage.PRESS_RAISED if press_error else SelectStage.PRESSED

    # After the press nothing is raised, repaired or retried. A popped-down popup, an unreadable
    # field and a moved profile count are all reported; the selection stays unknown.
    after: dict[str, str] = {}
    post_error = ""
    try:
        post = read_channels(live, target=target)
    except Exception as exc:  # noqa: BLE001 - an unreadable popup is a fact
        post_error = f"the popup could not be read after the press: {exc}"
    else:
        if post.surface is ChannelsSurface.SETTINGS_POPUP and post.popup is not None:
            after = _facts(post)
        else:
            post_error = (
                f"the popup no longer reads as the settings surface (surface "
                f"{post.surface.value!r}): what the radio row now selects is unknown"
            )
    moved = _moved(before, after)
    unreadable = _unreadable(before, after)
    owed = list(restoration)
    if press_error:
        owed.insert(
            0,
            "confirm on the screen whether the radio row moved at all: the press raised, so "
            "neither an old nor a new tick is established here",
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
            "facts_after": after,
            "facts_unreadable": list(unreadable),
            "facts_moved": list(moved),
            "press_error": press_error,
            "post_error": post_error,
            "restoration_owed": owed,
            "obligation_open": True,
        }
    )
    record_error = update_trial_record(record_file, payload)
    return result(
        stage=stage,
        new_facts=after,
        facts_moved=moved,
        facts_unreadable=unreadable,
        presses=presses,
        press=press_state,
        posted=posted,
        press_error=press_error,
        post_error=post_error,
        persisted="unknown",
        restoration_owed=tuple(owed),
        trial_record=record_file,
        trial_record_phase="obligation" if record_error else "after",
        trial_record_error=record_error,
        notes=tuple(
            item
            for item in (*getattr(live, "warnings", ()), press_error, post_error)
            if item
        ),
    )
