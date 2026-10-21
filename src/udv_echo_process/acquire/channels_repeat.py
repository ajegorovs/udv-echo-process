"""One guarded numeric write: the ``Channels`` popup's ``Repeat`` field, and nothing else.

This is the narrow writer a supervised trial needs — set the repeat count from a declared
baseline to a declared target, then back — without becoming a settings framework. It owns:

* **strict arguments.** ``expect`` is a positive integer (``True`` is not an integer here) and
  means only *the value this invocation requires the popup to state before it writes*;
  ``baseline`` is the separate, optional **original trial baseline** that a trial owes
  restoration to. Conflating the two made a restore run (``expect=2, value=1``) record and
  demand ``restore 2`` — the value the run had just left, never the trial's origin. The
  operator's multiplexer-off statement is an explicit argument, not an inference from a tick
  the tree cannot state.
* **one binding.** Exactly one instrument window is enumerated, bound once, and every read
  afterwards *verifies* that binding (:func:`…channels_read.read_channels` with ``target``) —
  nothing is rebound, so a window that changed identity refuses instead of moving the write.
* **preconditions before any action.** Full settings popup, readable, no overlay/dialog, the
  strip in its ready row, and the popup's own repeat value equal to ``expect``. Any mismatch is
  an :class:`~udv_echo_process.acquire.driver.AcquisitionError` with **zero writes**.
* **one commit.** A value equal to the current one is read and reported with no write at all;
  otherwise exactly one ``_set_text_commit`` on the freshly re-resolved edit, whose owning value
  button must still be the one the reading named.
* **a durable trial obligation.** The record is claimed (exclusively — never overwriting another
  trial's) and written with phase ``obligation`` **before** the commit, then rewritten with the
  outcome. A record that cannot be claimed refuses the write. The record names the declared
  trial baseline separately from this invocation's ``expect``, and a write that lands on the
  baseline owes no restoration. **One record per invocation:** each run claims its own file
  exclusively, so a trial's forward write and its restore write are two records — never one file
  rewritten, and never a new ledger. Every invocation of one trial declares the **same original**
  ``baseline``; reconciliation is reading the trial's records in order, the newest one naming the
  restoration that is still owed, not appending to a shared history inside this command.
  A record update that fails leaves the record at phase ``obligation`` on disk, and the result
  then reports ``trial_record_phase="obligation"`` too: the write may have landed, and the
  pre-write obligation is what the next run reads.
* **wall-clock stamps, not a monotonic counter.** ``written_at``/``completed_at`` are
  timezone-aware ISO 8601 wall-clock strings (:func:`_now_stamp`), because an operator reads
  them against a clock beside the instrument and the repository's other persisted manifests
  stamp local time from UTC. A monotonic value is an elapsed-time counter; persisted as a
  timestamp it is meaningless across processes and restarts.
* **no claims it cannot make.** A post-write read proves the *field* states the new value; it
  cannot prove the application kept it, because this repository's acceptance criterion for a
  committed value is a read taken from a **reopened** dialog, which this command does not do.
  That is a review requirement, not an established rule that a still-open dialog cannot retain
  an accepted value. Every post-write result therefore carries ``persisted="unknown"`` and
  whatever restoration is genuinely still owed.

Never pressed here: the menu, a hover, ``Enable``, ``Record``, ``Stop`` or ``Clear``. A popup
that closes after the write is reported as unknown and **not** retried.

**What is not established.** The operator opens the popup; this command never opens or closes
it, and it does not exit any hidden mode. Whether the strip's row can still be read *while* the
settings popup is up is a live-screen question this offline suite cannot answer: the row gate is
the shared preflight's, so a strip read that fails under the popup refuses with zero writes —
safe, but a trial that refuses there needs the live measurement, not a relaxed gate. And the
post-write reading is the still-open popup: it proves the field, never that the application kept
the value. A reopened dialog is the repository's acceptance step for that claim; one accepted
value proving retention across a reopen does not establish that no other path retains it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field

from udv_echo_process.acquire.actuator import (
    StripState,
    StripView,
    WindowTarget,
)
from udv_echo_process.acquire.channels_read import read_channels
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.store_completed import screen_clauses
from udv_echo_process.acquire.ui.channels import ChannelsRead, ChannelsSurface
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "MPX_DISABLED_STATEMENT",
    "PERSISTENCE_UNPROVEN",
    "TRIAL_FILE_NAME",
    "ChannelRepeatResult",
    "RepeatWriteStage",
    "acquire_repeat",
    "claim_trial_record",
    "trial_record_file",
    "update_trial_record",
]

#: The only declaration this command accepts as the operator's multiplexer-off statement.
MPX_DISABLED_STATEMENT = (
    "the operator declares the multiplexer disabled for this trial; the repository has no "
    "passive read of that mode, so it is never inferred from a tick or a strip row"
)

#: Why a successful post-write read is not persistence.
PERSISTENCE_UNPROVEN = (
    "a read of the still-open popup proves the field states the new value, not that the "
    "application kept it: this repository's acceptance criterion for a committed value is a "
    "read from a reopened dialog, which this command does not perform"
)

#: The record's file name when ``--trial-record`` names a directory.
TRIAL_FILE_NAME = "channels-repeat-trial.json"


def _now_stamp() -> str:
    """The record's wall-clock stamp: timezone-aware ISO 8601, local, per repository convention.

    The other persisted manifests in this package stamp ``datetime.now(tz=UTC).astimezone()``
    (:func:`udv_echo_process.acquire.campaign._local_now`), so the offset is explicit and an
    operator can read the value against the clock beside the instrument. Full ``isoformat()``
    precision is kept: two invocations of one trial can land inside the same second, and their
    stamps are the cheap way to order the records. Never a monotonic counter: that is elapsed
    time, not a timestamp, and it means nothing in a file read later.
    """
    return datetime.now(tz=UTC).astimezone().isoformat()


class RepeatWriteStage(str, Enum):
    """How far the run got — each member says what was established, not what was tried."""

    #: ``value`` already equalled the popup's reading: nothing was written.
    UNCHANGED = "unchanged"
    #: The commit returned and the fresh read states the new value; other facts unmoved.
    WRITTEN = "written"
    #: The commit returned, the field reads new, and another readable fact moved.
    WRITTEN_OTHER_FACTS_CHANGED = "written_other_facts_changed"
    #: The commit raised. Whether it landed is **unknown** — never reported as unchanged.
    COMMIT_RAISED = "commit_raised"
    #: The write was attempted and the popup could no longer be read; nothing was retried.
    WRITE_UNVERIFIED = "write_unverified"


class ChannelRepeatResult(ValueModel):
    """What one guarded repeat write established, and what the operator still owes."""

    stage: RepeatWriteStage
    bound_target: WindowTarget
    popup_hwnd: int | None = None
    slot: Literal["repeat"] = "repeat"
    #: The value **this invocation** required the popup to state before it wrote.
    expect: int
    value: int
    #: The trial's original baseline, when the caller declared one; never defaulted to ``expect``.
    baseline: int | None = None
    #: What this result says is owed back: the declared baseline, else this invocation's start.
    restore_to: int | None = None
    old_text: str = ""
    old_value: int | None = None
    #: The reading after the commit; ``None`` when no fresh reading could be taken.
    new_text: str | None = None
    new_value: int | None = None
    #: Every other readable fact at the moment of the pre-write read (texts, in popup order).
    other_facts: dict[str, str] = Field(default_factory=dict)
    other_facts_after: dict[str, str] = Field(default_factory=dict)
    #: Facts that differ after the write — evidence, never repaired here.
    other_changes: tuple[str, ...] = ()
    writes: int = 0
    #: ``True`` when this write landed exactly on the declared trial baseline.
    restored_baseline: bool = False
    #: ``not_written`` when nothing was committed; otherwise **unknown**, always.
    persisted: Literal["unknown", "not_written"] = "not_written"
    #: What the operator must do by hand, in their own words, before this trial is closed.
    restoration_owed: tuple[str, ...] = ()
    trial_record: Path | None = None
    #: ``after`` when the outcome reached disk; ``obligation`` when the update failed, because
    #: the file still carries the pre-write obligation and that is what the next run reads.
    trial_record_phase: Literal["", "obligation", "after"] = ""
    trial_record_error: str = ""
    observed: tuple[str, ...] = ()
    error: str = ""
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        """One log line: the stage, the two readings, the trial baseline, and what is owed."""
        baseline = "unstated" if self.baseline is None else str(self.baseline)
        head = (
            f"channels repeat {self.old_text or '?'} -> "
            f"{self.new_text if self.new_text is not None else '(unread)'} "
            f"(stage {self.stage.value}, writes {self.writes}, persisted {self.persisted}, "
            f"trial baseline {baseline})"
        )
        return (
            "; ".join((head, *self.restoration_owed)) if self.restoration_owed else head
        )


# ---------------------------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------------------------


def _positive_int(label: str, value: object) -> int:
    """``value`` as a strictly positive integer, or a refusal naming ``label``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise AcquisitionError(f"--{label} must be a positive integer, got {value!r}")
    if value <= 0:
        raise AcquisitionError(f"--{label} must be a positive integer, got {value!r}")
    return int(value)


def _optional_baseline(value: object) -> int | None:
    """The declared trial baseline, or ``None`` — **never** a silent alias for ``expect``.

    ``expect`` is what this invocation requires the popup to state; a trial's baseline is where
    the trial started. Defaulting the second to the first is only truthful for a trial's first
    write, and the command cannot tell a first write from a restore, so it does not guess.
    """
    if value is None:
        return None
    return _positive_int("baseline", value)


def _require_mpx_disabled(declared: object) -> None:
    """The operator's multiplexer-off statement is required, not defaulted."""
    if declared is not True:
        raise AcquisitionError(
            "refused: this command writes one field only in the multiplexer-disabled "
            f"configuration and needs the operator's explicit declaration (--mpx-disabled); "
            f"{MPX_DISABLED_STATEMENT}"
        )


# ---------------------------------------------------------------------------------------------
# the trial record: a narrow obligation, not a ledger
# ---------------------------------------------------------------------------------------------


def trial_record_file(path: Path | str) -> Path:
    """The record file to claim: ``path`` itself, or ``TRIAL_FILE_NAME`` inside it if a dir."""
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / TRIAL_FILE_NAME
    parent = candidate.parent
    if not parent.is_dir():
        raise AcquisitionError(
            f"the trial record's directory {parent} does not exist: the obligation has to be "
            "durable before anything is written, so nothing was attempted"
        )
    return candidate


def claim_trial_record(file: Path, obligation: dict) -> None:
    """Create ``file`` exclusively with the obligation — never overwrite another trial."""
    try:
        with open(file, "x", encoding="utf-8") as handle:
            json.dump(obligation, handle, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise AcquisitionError(
            f"a trial record already exists at {file}: refusing to overwrite another trial's "
            "obligation (move or name a different --trial-record)"
        ) from exc
    except OSError as exc:
        raise AcquisitionError(
            f"the trial record {file} could not be created: {exc}"
        ) from exc


def update_trial_record(file: Path, payload: dict) -> str:
    """Rewrite the claimed record atomically; return the failure text, empty on success."""
    temporary = file.with_name(file.name + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, file)
    except OSError as exc:
        return f"the trial record {file} could not be updated: {exc}"
    return ""


# ---------------------------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------------------------


def _strip_not_recording(state: StripState) -> tuple[str, ...]:
    """Why ``state`` is not the stopped row this command writes from, or ``()``.

    Narrow on purpose: a recording (one button), an ambiguous row and a sliderising store view
    are all refused, and the ``Record`` role is never needed because nothing is pressed.
    """
    if state.has_slider:
        return (
            (
                f"the strip reads {state.view.value!r} with {state.button_count} button(s) and "
                "a slider: a block is on screen, and this command writes no setting over one "
                "it did not store"
            ),
        )
    if state.view is not StripView.READY:
        return (
            (
                f"the strip reads {state.view.value!r} with {state.button_count} button(s) "
                "where 'ready' is required: the popup is only written from the stopped row, so "
                "a recording in progress is refused rather than raced"
            ),
        )
    return ()


def _settings_read(live, target: WindowTarget, *, what: str) -> ChannelsRead:
    """One fresh popup reading through the shared reader, its binding verified not replaced."""
    try:
        report = read_channels(live, target=target)
    except Exception as exc:
        raise AcquisitionError(
            f"{what}: the Channels popup could not be read ({type(exc).__name__}: {exc}); "
            "nothing was written and nothing was retried"
        ) from exc
    return report


def _require_readable_settings(report: ChannelsRead, *, what: str) -> None:
    """Refuse anything that is not the full, readable settings popup with a repeat amount."""
    if report.surface is not ChannelsSurface.SETTINGS_POPUP:
        raise AcquisitionError(
            f"{what}: the surface reads {report.surface.value!r}, not the full settings popup "
            f"(refusals: {list(report.refusals)!r}); nothing was written"
        )
    if not report.readable:
        raise AcquisitionError(
            f"{what}: the settings popup is not readable (refusals: {list(report.refusals)!r}); "
            "nothing was written"
        )
    if report.repeat is None or report.repeat.value is None:
        raise AcquisitionError(
            f"{what}: the popup states no readable repeat amount; nothing was written"
        )


def _facts(report: ChannelsRead) -> dict[str, str]:
    """Every other readable amount this command carries, as exact text, in popup order."""
    facts: dict[str, str] = {}
    for label, slot in (
        ("start_channel", report.start_channel),
        ("apply_from", report.apply_from),
    ):
        if slot is not None:
            facts[label] = slot.text
    if report.per_channel is not None:
        facts["profiles"] = report.per_channel.profiles.text
        facts["seconds"] = report.per_channel.seconds.text
    return facts


def _other_changes(before: dict[str, str], after: dict[str, str]) -> tuple[str, ...]:
    """The facts that moved, named — an observation, never a repair."""
    out: list[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            out.append(f"{key}: {before.get(key)!r} -> {after.get(key)!r}")
    return tuple(out)


# ---------------------------------------------------------------------------------------------
# the workflow
# ---------------------------------------------------------------------------------------------


def acquire_repeat(
    *,
    expect: int,
    value: int,
    baseline: int | None = None,
    mpx_disabled: bool,
    trial_record: Path | str,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    stamp: Callable[[], str] = _now_stamp,
    notes: list[str] | None = None,
) -> ChannelRepeatResult:
    """Set the popup's ``Repeat`` from ``expect`` to ``value``, once, and say what is unknown.

    ``expect`` is this invocation's precondition and nothing more. ``baseline`` is the trial's
    **original** value: declare it on every invocation of one trial, so a restore run
    (``expect=2, value=1, baseline=1``) records that it returned to the baseline instead of
    owing a restore to ``2``. With no ``baseline`` the command refuses to invent one — the
    record carries ``baseline: null`` and the only restoration it can name is this invocation's
    own starting value, ``expect``.

    ``trial_record`` is claimed **exclusively for this invocation**: a forward write and its
    restore write are two records, and the trial is reconciled by reading them in order while
    every one of them declares the same original ``baseline``. There is no ledger file and no
    append path; a record that already exists refuses the write.

    Everything is settled before the commit: the arguments, the operator's mode declaration,
    the record path, the single window binding, the caption/overlay/ready-row preconditions, the
    full settings popup, the current value against ``expect``, and a **fresh** re-resolution of
    the same edit and owner. A refusal on any of them raises
    :class:`~udv_echo_process.acquire.driver.AcquisitionError` having written nothing.

    After the commit every outcome is returned, never raised: a commit that failed, a popup that
    closed, a field that reads something else, and another fact that moved are all facts for the
    operator, and none of them triggers a retry or a second press.
    """
    expect = _positive_int("expect", expect)
    value = _positive_int("value", value)
    baseline = _optional_baseline(baseline)
    _require_mpx_disabled(mpx_disabled)
    record_file = trial_record_file(trial_record)
    # The restoration target is the declared trial baseline when there is one. Without one the
    # command can only name its own undo, so the record says so rather than calling ``expect``
    # the baseline — which is what made a restore run owe a restore back to the value it left.
    restore_to = baseline if baseline is not None else expect
    restores_baseline = baseline is not None and value == baseline

    sink = notes if notes is not None else []
    # ``allow_real_input=False``: this command never hovers the menubar — the commit below is the
    # posted numeric-write recipe (``_set_text_commit``), which takes no cursor at all — so the
    # one real-input step is refused by construction rather than merely not called.
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
    # The one and only binding. Every read below verifies it instead of replacing it.
    target = live.bind_target(int(windows[0]))
    clauses, _state = screen_clauses(
        live,
        target,
        windows,
        class_name=class_name,
        strip=_strip_not_recording,
    )
    if clauses:
        raise AcquisitionError("; ".join(clauses))

    report = _settings_read(live, target, what="before the write")
    _require_readable_settings(report, what="before the write")
    assert report.repeat is not None  # _require_readable_settings established it
    repeat = report.repeat
    if repeat.value != expect:
        raise AcquisitionError(
            f"the popup reads repeat {repeat.text!r} ({repeat.value!r}) where --expect "
            f"{expect} was declared; nothing was written (0 writes) and the screen was not "
            "touched — re-read it and declare the value it actually states"
        )
    if repeat.hwnd is None or repeat.owner_hwnd is None:
        raise AcquisitionError(
            "the repeat amount resolved without an owning value button and its own edit: this "
            "command writes only an exact field, so nothing was written"
        )
    before = _facts(report)
    observed = [
        f"read:repeat={repeat.text}/{repeat.value}/edit={repeat.hwnd}/owner={repeat.owner_hwnd}",
    ]

    if int(repeat.value) == value:
        # Read, and deliberately not written: proving the no-write path is part of the trial.
        return ChannelRepeatResult(
            stage=RepeatWriteStage.UNCHANGED,
            bound_target=target,
            popup_hwnd=None if report.popup is None else report.popup.hwnd,
            expect=expect,
            value=value,
            baseline=baseline,
            restore_to=restore_to,
            old_text=repeat.text,
            old_value=int(repeat.value),
            new_text=repeat.text,
            new_value=int(repeat.value),
            other_facts=before,
            other_facts_after=dict(before),
            writes=0,
            persisted="not_written",
            observed=tuple(observed),
            notes=tuple(getattr(live, "warnings", ())),
        )

    # Fresh re-resolution immediately before the commit: the tree is re-enumerated and the
    # field's own edit and owner must be the pair this write was decided on.
    fresh = _settings_read(live, target, what="immediately before the commit")
    _require_readable_settings(fresh, what="immediately before the commit")
    assert fresh.repeat is not None  # established above
    if fresh.repeat.value != expect:
        raise AcquisitionError(
            f"the repeat field changed under the read: {fresh.repeat.text!r} where --expect "
            f"{expect} was declared; nothing was written"
        )
    if (fresh.repeat.hwnd, fresh.repeat.owner_hwnd) != (repeat.hwnd, repeat.owner_hwnd):
        raise AcquisitionError(
            f"the repeat field's edit/owner resolved as "
            f"({fresh.repeat.hwnd}, {fresh.repeat.owner_hwnd}) where the reading named "
            f"({repeat.hwnd}, {repeat.owner_hwnd}): the tree changed, so nothing was written"
        )
    if _facts(fresh) != before:
        raise AcquisitionError(
            "another readable fact moved between the two reads "
            f"({list(_other_changes(before, _facts(fresh)))!r}): this command writes one field, "
            "so nothing was written"
        )
    edit_hwnd, owner_hwnd = int(repeat.hwnd), int(repeat.owner_hwnd)

    if restores_baseline:
        owed_after = (
            f"reopen Channels and confirm repeat == {value}; this write returns the field to "
            f"the trial baseline ({baseline}), so no further restoration is owed"
        )
    elif baseline is not None:
        owed_after = (
            f"reopen Channels and confirm repeat == {value}; the recorded obligation is to "
            f"restore the trial baseline repeat == {baseline} before the trial is closed"
        )
    else:
        owed_after = (
            f"reopen Channels and confirm repeat == {value}; no trial baseline was declared, "
            f"so the only restoration recorded is this invocation's own starting value "
            f"(repeat == {expect})"
        )
    obligation = {
        "command": "acquire channels-repeat",
        "phase": "obligation",
        "written_at": stamp(),
        "slot": "repeat",
        # ``expect`` is this invocation's precondition; ``baseline`` is the trial's origin.
        "expect": expect,
        "value": value,
        "baseline": baseline,
        "restore_to": restore_to,
        "restore_to_source": (
            "declared-trial-baseline" if baseline is not None else "this-invocation"
        ),
        "restores_baseline": restores_baseline,
        "old_text": repeat.text,
        "other_facts": before,
        "mpx_disabled_declaration": MPX_DISABLED_STATEMENT,
        "bound_target": target.model_dump(mode="json"),
        "popup_hwnd": None if report.popup is None else report.popup.hwnd,
        "edit_hwnd": edit_hwnd,
        "owner_hwnd": owner_hwnd,
        "owed_after": owed_after,
        "persistence": "unknown until the operator reopens the dialog",
    }
    claim_trial_record(record_file, obligation)

    def after(
        stage: RepeatWriteStage,
        *,
        writes: int,
        post: ChannelsRead | None = None,
        error: str = "",
        other_after: dict[str, str] | None = None,
    ) -> ChannelRepeatResult:
        """Every post-commit outcome, in one shape, with the record read back and updated."""
        persisted: Literal["unknown", "not_written"] = (
            "unknown" if writes else "not_written"
        )
        owed: list[str] = []
        new_text = None if post is None or post.repeat is None else post.repeat.text
        new_value = None if post is None or post.repeat is None else post.repeat.value
        # Only a post-read that states the committed value is evidence the write landed; a
        # raised commit, a closed popup and a field that reads something else are not.
        landed = new_value is not None and int(new_value) == value
        # The one post-write instruction this outcome carries; it is also the record's
        # ``owed_after``, so a failed restore cannot leave the pre-write intent standing.
        confirm = ""
        if writes:
            owed.append(PERSISTENCE_UNPROVEN)
            if not landed:
                # The reading contradicts the committed value, so never tell the operator to
                # "confirm" it: ask for the value the field actually states, then name the
                # restore target the trial owes.
                target_note = (
                    f"the trial baseline repeat == {baseline}"
                    if baseline is not None
                    else (
                        "this invocation's own starting value repeat == "
                        f"{expect} (no trial baseline was declared)"
                    )
                )
                confirm = (
                    "a write attempt may have landed and the field does not read "
                    f"{value}: reopen the Channels popup by hand and read the repeat as it "
                    "actually states before concluding anything, then restore "
                    f"{target_note} (the obligation is recorded at {record_file})"
                )
            elif restores_baseline:
                confirm = (
                    "reopen the Channels popup by hand and confirm repeat == "
                    f"{value}: this write returned the field to the trial baseline, so no "
                    f"further restoration is owed (the obligation is recorded at {record_file})"
                )
            elif baseline is not None:
                confirm = (
                    "reopen the Channels popup by hand and confirm repeat == "
                    f"{value}; before the trial is closed, restore the trial baseline "
                    f"repeat == {baseline} (the obligation is recorded at {record_file})"
                )
            else:
                confirm = (
                    "reopen the Channels popup by hand and confirm repeat == "
                    f"{value}; no trial baseline was declared, so the only restoration this "
                    f"invocation can name is the value it found, repeat == {expect}, if the "
                    f"write is not wanted (the obligation is recorded at {record_file})"
                )
            owed.append(confirm)
        changes = () if other_after is None else _other_changes(before, other_after)
        record = {
            **obligation,
            "phase": "after",
            "completed_at": stamp(),
            "stage": stage.value,
            "writes": writes,
            "persisted": persisted,
            "new_text": new_text,
            "new_value": new_value,
            "other_facts_after": other_after if other_after is not None else {},
            "other_changes": list(changes),
            "error": error,
            "owed_after": confirm or obligation["owed_after"],
            # ``restores_baseline`` above is the pre-write intent; this is the observation.
            "restored_baseline": bool(restores_baseline and landed),
            "owed": owed,
        }
        record_error = update_trial_record(record_file, record)
        if record_error:
            owed.append(record_error + " — the obligation on disk is the pre-write one")
        # The file is still at ``obligation`` when the update failed, and the result must report
        # that same phase: claiming ``after`` here would say the outcome reached disk when it did
        # not, and the write may have landed.
        record_phase: Literal["obligation", "after"] = (
            "obligation" if record_error else "after"
        )
        return ChannelRepeatResult(
            stage=stage,
            bound_target=target,
            popup_hwnd=None if post is None or post.popup is None else post.popup.hwnd,
            expect=expect,
            value=value,
            baseline=baseline,
            restore_to=restore_to,
            old_text=repeat.text,
            old_value=int(repeat.value),
            new_text=new_text,
            new_value=None if new_value is None else int(new_value),
            other_facts=before,
            other_facts_after=dict(other_after or {}),
            other_changes=changes,
            writes=writes,
            # Claimed only from the post-write reading: a commit that raised, a closed popup
            # and a value that did not take are all unknown, never "restored".
            restored_baseline=bool(restores_baseline and landed),
            persisted=persisted,
            restoration_owed=tuple(owed),
            trial_record=record_file,
            trial_record_phase=record_phase,
            trial_record_error=record_error,
            observed=tuple(observed),
            error=error,
            notes=tuple(getattr(live, "warnings", ())),
        )

    try:
        live._set_text_commit(edit_hwnd, str(value), owner_hwnd)  # once
    except Exception as exc:  # noqa: BLE001 - the commit's own failure is a report
        return after(
            RepeatWriteStage.COMMIT_RAISED,
            writes=1,
            error=(
                f"the commit raised {type(exc).__name__}: {exc}; whether it landed is unknown — "
                "this is not a report that nothing changed"
            ),
        )

    # One fresh read; a popup that closed is reported, never reopened and never retried.
    try:
        post = read_channels(live, target=target)
    except Exception as exc:  # noqa: BLE001 - an unreadable post-write screen is terminal
        return after(
            RepeatWriteStage.WRITE_UNVERIFIED,
            writes=1,
            error=(
                f"the post-write read failed ({type(exc).__name__}: {exc}); the commit returned "
                "but the field's new value could not be seen, and nothing was re-read or retried"
            ),
        )
    if post.surface is not ChannelsSurface.SETTINGS_POPUP or post.repeat is None:
        return after(
            RepeatWriteStage.WRITE_UNVERIFIED,
            writes=1,
            error=(
                f"the popup reads {post.surface.value!r} after the write, so the field's new "
                "value could not be seen; whether the write landed is unknown and nothing was "
                "retried"
            ),
        )
    other_after = _facts(post)
    changes = _other_changes(before, other_after)
    if post.repeat.value != value:
        return after(
            RepeatWriteStage.WRITE_UNVERIFIED,
            writes=1,
            post=post,
            other_after=other_after,
            error=(
                f"the field reads {post.repeat.text!r} where {value} was committed; the field "
                "did not take the value and nothing was retried"
            ),
        )
    return after(
        RepeatWriteStage.WRITTEN_OTHER_FACTS_CHANGED
        if changes
        else RepeatWriteStage.WRITTEN,
        writes=1,
        post=post,
        other_after=other_after,
    )
