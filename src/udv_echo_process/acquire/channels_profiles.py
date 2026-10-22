"""One guarded numeric write: the ``Channels`` popup's per-channel ``Profiles`` field.

This is the second narrow writer a supervised trial needs, beside
:mod:`udv_echo_process.acquire.channels_repeat`. It owns exactly one commit on the group box's
``Acquire … Profiles`` edit, and it reuses the repeat writer's owning mechanisms instead of
re-implementing them — the exclusive trial-record claim/update, the stopped-row rule, the single
window binding, the shared screen preflight and the settings reader. Nothing here opens the popup,
presses a button, hovers a menu, records, stores, or changes a mode.

What this writer establishes, and what it deliberately does not
-----------------------------------------------------------------

* **The operator's channel is a declaration, not a reading.** The group box's caption is painted
  (``For the current channel (channel N)``) and the tree states nothing for it, so
  :class:`~udv_echo_process.acquire.ui.channels.PerChannelAmounts` carries
  ``channel="UNKNOWN"``. The caller must therefore state ``operator_channel`` explicitly. That
  declaration is recorded verbatim, is checked only against the channels the surface itself
  paints (a number the popup does not offer is refused), and **never** fills
  ``per_channel.channel``, never becomes ``channel_verified``, and never gains action authority.
  No visual attribution from a capture is consulted; this module never reads a picture.
* **``seconds`` is a coupled observable, not a preserved fact.** Changing the profile count makes
  the application recompute the neighbouring ``… during seconds`` amount, so requiring it
  unchanged would refuse the application's legitimate behaviour. It is reported before and after
  and the **fresh post-write** reading must state a valid positive amount; a value that is
  missing, zero, negative or unparseable after the commit is an unverified write. The facts that
  must stay put — ``repeat``, ``start_channel``, ``apply_from`` — are compared and any movement is
  reported (and is not exit-0 evidence).
* **Strict arguments, bounded by the actual control.** ``expect``/``value``/``baseline`` are
  strictly positive integers (``True`` is not an integer) because the profiles slot is parsed as a
  base-10 integer by the owning reader. No upper cap is invented: neither the control's stated
  text nor the manual reference states one, so the only shape enforced is the control's own
  integer format. The operator channel is checked against the channel numbers the popup paints.
* **One binding, one commit.** Exactly one visible instrument window is enumerated and bound; every
  later read verifies that binding. A popup that is absent, clipped (multiplexer on), behind a
  dialog, of another band order, unreadable, or stating another profile count refuses with **zero
  writes**. Immediately before the commit the profiles edit *and* the value button that owns it
  are re-resolved, and the caption/overlay/stopped-row/single-window clauses are asked **again on
  a fresh enumeration** — the mode is read from the caption at that moment, never inferred from
  the operator's declaration, and a recording or a modal that appeared in between refuses with
  zero writes.
* **A durable obligation before the commit.** The record is claimed exclusively and written with
  phase ``obligation`` before the commit, then rewritten with the outcome. ``baseline`` is the
  trial's **original** profile count and is never defaulted from ``expect``; a write that lands on
  the declared baseline owes no further restoration. A record that cannot be claimed refuses the
  write, and an outcome that cannot be written leaves the file (and the result) at ``obligation``.
* **No blind retry, no cleanup, no closed obligation.** The commit is attempted once. A raised
  commit, a popup that closed, a field that reads something else, invalid fresh seconds and another
  fact that moved are all reported as unknown/observed — never retried, never repaired, never
  dismissed. This command cannot close a trial: only a fresh read from a **reopened** dialog by
  the operator can, so every written outcome keeps ``obligation_open=True`` and says so.
* **Persistence is unproven.** A read of the still-open popup proves the field states the new
  value, not that the application kept it, so ``persisted="unknown"`` on every write.

**Supervised identity limitation.** The binding is one instrument window, verified around every
read, and the child handles are re-resolved immediately before the commit — but a popup the
operator closes and reopens between the reads cannot be distinguished from the popup that was
there, and a child handle is not an identity after the tree changes. The supervision is therefore
the operator's: nobody else may drive this application while the command runs, and the reopened
read is theirs. **No recording happens here** — no ``Record``, ``Stop``, ``Clear and restart``,
``Do store``, multiplexer press or menu entry is reachable from this module.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import Field

from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.channels_read import read_channels
from udv_echo_process.acquire.channels_repeat import (
    MPX_DISABLED_STATEMENT,
    PERSISTENCE_UNPROVEN,
    _fact_moves,
    _facts_unreadable,
    _now_stamp,
    _other_changes,
    _settings_read,
    _strip_not_recording,
    claim_trial_record,
    trial_record_file,
    update_trial_record,
)
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.store_completed import screen_clauses
from udv_echo_process.acquire.ui.channels import ChannelsRead, ChannelsSurface
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "OPERATOR_CHANNEL_DECLARATION",
    "PROFILES_TRIAL_FILE_NAME",
    "ChannelProfilesResult",
    "ProfilesWriteStage",
    "acquire_profiles",
]

#: The record's file name when ``--trial-record`` names a directory.
PROFILES_TRIAL_FILE_NAME = "channels-profiles-trial.json"

#: What the operator's channel argument means — carried on every report and record.
OPERATOR_CHANNEL_DECLARATION = (
    "the operator declares which channel the group box's per-channel amounts belong to; the "
    "popup paints that channel in its caption and the tree states nothing, so this is a "
    "declaration, not a reading: it never fills per_channel.channel, never becomes a verified "
    "channel and carries no action authority"
)


class ProfilesWriteStage(str, Enum):
    """How far the run got — each member says what was established, not what was tried."""

    #: ``value`` already equalled the profiles reading: nothing was written.
    UNCHANGED = "unchanged"
    #: The commit returned, the fresh read states the new count, and the preserved facts held.
    WRITTEN = "written"
    #: The commit returned and the field reads new, while the application recomputed ``seconds``.
    WRITTEN_SECONDS_RECOMPUTED = "written_seconds_recomputed"
    #: The field reads new, but a fact that must stay put (repeat/start/apply) moved.
    WRITTEN_OTHER_FACTS_CHANGED = "written_other_facts_changed"
    #: The commit raised. Whether it landed is **unknown** — never reported as unchanged.
    COMMIT_RAISED = "commit_raised"
    #: The write was attempted and its outcome could not be read back; nothing was retried.
    WRITE_UNVERIFIED = "write_unverified"


class ChannelProfilesResult(ValueModel):
    """What one guarded profiles write established, and what the operator still owes."""

    stage: ProfilesWriteStage
    bound_target: WindowTarget
    popup_hwnd: int | None = None
    slot: Literal["profiles"] = "profiles"
    #: The value **this invocation** required the popup to state before it wrote.
    expect: int
    value: int
    #: The operator's declaration; never a reading and never proof of the popup's channel.
    operator_channel: int
    operator_channel_declaration: str = OPERATOR_CHANNEL_DECLARATION
    #: ``False`` by construction: no read here can verify which channel the amounts belong to.
    channel_verified: Literal[False] = False
    #: The trial's original profile count, when declared; never defaulted to ``expect``.
    baseline: int | None = None
    #: What this result says is owed back: the declared baseline, else this invocation's start.
    restore_to: int | None = None
    old_text: str = ""
    old_value: int | None = None
    #: The neighbouring ``… during seconds`` amount, as an observation before and after.
    old_seconds_text: str = ""
    old_seconds: float | None = None
    new_text: str | None = None
    new_value: int | None = None
    new_seconds_text: str | None = None
    new_seconds: float | None = None
    #: ``True`` when the application's own recomputation moved ``seconds`` — legitimate, reported.
    seconds_recomputed: bool = False
    #: The facts that must be preserved (repeat, start_channel, apply_from), before and after.
    other_facts: dict[str, str] = Field(default_factory=dict)
    other_facts_after: dict[str, str] = Field(default_factory=dict)
    #: Preserved facts that differ after the write — evidence, never repaired here.
    other_changes: tuple[str, ...] = ()
    #: Preserved facts the earlier read stated and the post-write read did not: unknown, not gone.
    other_facts_unreadable: tuple[str, ...] = ()
    writes: int = 0
    #: ``True`` when this write landed exactly on the declared trial baseline.
    restored_baseline: bool = False
    #: ``True`` for every attempted write: only an operator's reopened read can close it.
    obligation_open: bool = False
    #: ``not_written`` when nothing was committed; otherwise **unknown**, always.
    persisted: Literal["unknown", "not_written"] = "not_written"
    #: What the operator must do by hand before this trial is closed.
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
        """One log line: the stage, both readings, the facts that moved and what is owed."""
        baseline = "unstated" if self.baseline is None else str(self.baseline)
        head = (
            f"channels profiles {self.old_text or '?'} -> "
            f"{self.new_text if self.new_text is not None else '(unread)'} "
            f"(channel {self.operator_channel} operator-declared, stage {self.stage.value}, "
            f"writes {self.writes}, persisted {self.persisted}, "
            f"seconds {self.old_seconds_text or '?'} -> "
            f"{self.new_seconds_text if self.new_seconds_text is not None else '(unread)'}, "
            f"trial baseline {baseline})"
        )
        moved = (
            f"other facts moved: {'; '.join(self.other_changes)}"
            if self.other_changes
            else ""
        )
        parts = [part for part in (head, moved, *self.restoration_owed) if part]
        return "; ".join(parts)


# ---------------------------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------------------------


def _positive_int(label: str, value: object) -> int:
    """``value`` as a strictly positive integer, or a refusal naming ``label``.

    No upper bound is applied: the profiles slot is parsed as a base-10 integer by the owning
    reader and neither the control's stated text nor the manual states a cap, so inventing one
    would refuse a value the application may legitimately accept.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise AcquisitionError(f"--{label} must be a positive integer, got {value!r}")
    if value <= 0:
        raise AcquisitionError(f"--{label} must be a positive integer, got {value!r}")
    return int(value)


def _optional_baseline(value: object) -> int | None:
    """The declared trial baseline, or ``None`` — **never** a silent alias for ``expect``."""
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
# preconditions and readings
# ---------------------------------------------------------------------------------------------


def _require_readable_profiles(
    report: ChannelsRead, *, what: str, operator_channel: int
) -> None:
    """Refuse anything that is not the full, readable settings popup with a profiles amount."""
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
    if report.per_channel is None or report.per_channel.profiles.value is None:
        raise AcquisitionError(
            f"{what}: the popup states no readable per-channel profiles amount; nothing was "
            "written"
        )
    profiles = report.per_channel.profiles
    if isinstance(profiles.value, float) or not isinstance(profiles.value, int):
        raise AcquisitionError(
            f"{what}: the profiles amount reads {profiles.text!r} ({profiles.value!r}), which is "
            "not an integer count; nothing was written"
        )
    if profiles.hwnd is None or profiles.owner_hwnd is None:
        raise AcquisitionError(
            "the profiles amount resolved without an owning value button and its own edit: this "
            "command writes only an exact field, so nothing was written"
        )
    painted = sorted({cell.index for cell in report.channel_ticks})
    if operator_channel not in painted:
        raise AcquisitionError(
            f"--operator-channel {operator_channel} is not one of the channels this popup paints "
            f"({painted}): the group box's channel is caption-only and the surface itself offers "
            "only those numbers, so nothing was written"
        )


def _seconds(report: ChannelsRead) -> tuple[str, float | None]:
    """The neighbouring ``… during seconds`` amount as (exact text, parsed value)."""
    if report.per_channel is None:
        return "", None
    slot = report.per_channel.seconds
    value = slot.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        return slot.text, None
    number = float(value)
    return slot.text, number if math.isfinite(number) else None


def _seconds_valid(seconds: float | None) -> bool:
    """A fresh seconds amount is valid only when it is a finite, strictly positive number."""
    return seconds is not None and math.isfinite(seconds) and seconds > 0


def _preserved_facts(report: ChannelsRead) -> dict[str, str]:
    """The facts that must not move, as exact text: repeat, start channel and apply-from."""
    facts: dict[str, str] = {}
    for label, slot in (
        ("repeat", report.repeat),
        ("start_channel", report.start_channel),
        ("apply_from", report.apply_from),
    ):
        if slot is not None:
            facts[label] = slot.text
    return facts


def _facts_after(report: ChannelsRead) -> dict[str, str] | None:
    """The preserved facts a post-write reading states, or ``None`` when it states none.

    Only a full settings-popup reading can be compared with the pre-write facts: a clipped
    multiplexer-on surface, a dialog in front, an absent or reshaped popup states none of these
    amounts, so passing an empty mapping would read as every one of them having vanished.
    ``None`` says *unknown* instead, and :meth:`ChannelProfilesResult.other_changes` stays empty
    rather than claiming a movement this command never saw.
    """
    if report.surface is not ChannelsSurface.SETTINGS_POPUP:
        return None
    return _preserved_facts(report)


# ---------------------------------------------------------------------------------------------
# the workflow
# ---------------------------------------------------------------------------------------------


def acquire_profiles(
    *,
    expect: int,
    value: int,
    operator_channel: int,
    baseline: int | None = None,
    mpx_disabled: bool,
    trial_record: Path | str,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    stamp: Callable[[], str] = _now_stamp,
    notes: list[str] | None = None,
) -> ChannelProfilesResult:
    """Set the popup's per-channel ``Profiles`` from ``expect`` to ``value``, once.

    ``operator_channel`` is the operator's declaration of which channel the group box's amounts
    belong to. The caption that states it is painted, so it is checked only against the channel
    numbers the popup paints and is never promoted to a verified channel.

    ``expect`` is this invocation's precondition. ``baseline`` is the trial's **original** count:
    declare it on every invocation of one trial, so a restore run (``expect=8, value=7,
    baseline=7``) records that it returned to the baseline instead of owing a restore to ``8``.

    ``seconds`` is **not** a preserved fact. The application recomputes it when the profile count
    changes, so a movement is reported (``seconds_recomputed``) and the fresh amount must be valid
    and positive; requiring it unchanged would refuse the application's legitimate behaviour.
    ``repeat``, ``start_channel`` and ``apply_from`` must stay put, and a movement is reported as
    ``WRITTEN_OTHER_FACTS_CHANGED`` — never exit-0 evidence.

    ``trial_record`` is claimed exclusively for this invocation, with
    ``PROFILES_TRIAL_FILE_NAME`` when the path is a directory. A forward write and its restore
    write are two records, and the trial is reconciled by reading them in order while every one
    of them declares the same original ``baseline``.

    Everything is settled before the commit: the arguments, the operator's mode declaration, the
    record path, the single window binding, the caption/overlay/ready-row preflight, the full
    settings popup, the current count against ``expect``, the declared channel against the painted
    channels, and a **fresh** re-resolution of the same edit and owner. The caption/overlay/row/
    window clauses are then re-asked on a fresh enumeration immediately before the commit, so a
    recording or a modal that appeared while the readings were taken refuses with zero writes
    rather than being written through. A refusal on any of them raises
    :class:`~udv_echo_process.acquire.driver.AcquisitionError` having written nothing.

    After the commit every outcome is returned, never raised and never retried.
    """
    expect = _positive_int("expect", expect)
    value = _positive_int("value", value)
    operator_channel = _positive_int("operator-channel", operator_channel)
    baseline = _optional_baseline(baseline)
    _require_mpx_disabled(mpx_disabled)
    record_file = trial_record_file(trial_record, name=PROFILES_TRIAL_FILE_NAME)
    restore_to = baseline if baseline is not None else expect
    restores_baseline = baseline is not None and value == baseline

    sink = notes if notes is not None else []
    # The write is the posted numeric recipe; the cursor-driven menubar step is refused by
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
    _require_readable_profiles(
        report, what="before the write", operator_channel=operator_channel
    )
    assert report.per_channel is not None  # _require_readable_profiles established it
    profiles = report.per_channel.profiles
    if profiles.value != expect:
        raise AcquisitionError(
            f"the popup reads profiles {profiles.text!r} ({profiles.value!r}) where --expect "
            f"{expect} was declared; nothing was written (0 writes) and the screen was not "
            "touched — re-read it and declare the count it actually states"
        )
    if profiles.hwnd is None or profiles.owner_hwnd is None:
        raise AcquisitionError(
            "the profiles amount resolved without an owning value button and its own edit: this "
            "command writes only an exact field, so nothing was written"
        )
    old_seconds_text, old_seconds = _seconds(report)
    if not _seconds_valid(old_seconds):
        raise AcquisitionError(
            f"the popup's coupled seconds amount reads {old_seconds_text!r}, which is not a "
            "valid positive amount; the write is refused because the recomputation it triggers "
            "could not be checked, and nothing was written"
        )
    before = _preserved_facts(report)
    observed = [
        (
            f"read:profiles={profiles.text}/{profiles.value}/edit={profiles.hwnd}/"
            f"owner={profiles.owner_hwnd}"
        ),
        f"read:seconds={old_seconds_text}/{old_seconds}",
        (
            f"declared:operator_channel={operator_channel} "
            f"(painted channels {sorted({cell.index for cell in report.channel_ticks})})"
        ),
    ]

    if int(profiles.value) == value:
        # Read, and deliberately not written: proving the no-write path is part of the trial.
        return ChannelProfilesResult(
            stage=ProfilesWriteStage.UNCHANGED,
            bound_target=target,
            popup_hwnd=None if report.popup is None else report.popup.hwnd,
            expect=expect,
            value=value,
            operator_channel=operator_channel,
            baseline=baseline,
            restore_to=restore_to,
            old_text=profiles.text,
            old_value=int(profiles.value),
            old_seconds_text=old_seconds_text,
            old_seconds=old_seconds,
            new_text=profiles.text,
            new_value=int(profiles.value),
            new_seconds_text=old_seconds_text,
            new_seconds=old_seconds,
            other_facts=before,
            other_facts_after=dict(before),
            writes=0,
            persisted="not_written",
            observed=tuple(observed),
            notes=tuple(getattr(live, "warnings", ())),
        )

    # Fresh re-resolution immediately before the commit: the field's own edit and owner must be
    # the pair this write was decided on, and nothing readable may have moved under the reads.
    fresh = _settings_read(live, target, what="immediately before the commit")
    _require_readable_profiles(
        fresh, what="immediately before the commit", operator_channel=operator_channel
    )
    assert fresh.per_channel is not None  # established above
    if fresh.per_channel.profiles.value != expect:
        raise AcquisitionError(
            f"the profiles field changed under the read: {fresh.per_channel.profiles.text!r} "
            f"where --expect {expect} was declared; nothing was written"
        )
    if (fresh.per_channel.profiles.hwnd, fresh.per_channel.profiles.owner_hwnd) != (
        profiles.hwnd,
        profiles.owner_hwnd,
    ):
        raise AcquisitionError(
            f"the profiles field's edit/owner resolved as "
            f"({fresh.per_channel.profiles.hwnd}, {fresh.per_channel.profiles.owner_hwnd}) where "
            f"the reading named ({profiles.hwnd}, {profiles.owner_hwnd}): the tree changed, so "
            "nothing was written"
        )
    if _fact_moves(before, _preserved_facts(fresh)):
        raise AcquisitionError(
            "another readable fact moved between the two reads "
            f"({list(_fact_moves(before, _preserved_facts(fresh)))!r}): this command writes "
            "one field, so nothing was written"
        )
    if _seconds(fresh) != (old_seconds_text, old_seconds):
        raise AcquisitionError(
            "the coupled seconds amount moved between the two reads with no write in between "
            f"({_seconds(fresh)!r} where the reading named "
            f"{(old_seconds_text, old_seconds)!r}): nothing was written"
        )
    edit_hwnd, owner_hwnd = int(profiles.hwnd), int(profiles.owner_hwnd)

    # The whole screen is asked again immediately before the commit, not only at the binding:
    # the caption (the only surface that states which process is on the screen), the overlay,
    # the stopped row and the single visible window are preconditions of *writing*, and the two
    # readings above take time. A recording that started, a modal that appeared or a second copy
    # launched in that window refuses here with zero writes. The mode is never inferred from the
    # operator's multiplexer declaration: the caption is read again, or the run refuses.
    clauses, _state = screen_clauses(
        live,
        target,
        tuple(enumerate_windows_fn()),
        class_name=class_name,
        strip=_strip_not_recording,
    )
    if clauses:
        raise AcquisitionError("immediately before the commit: " + "; ".join(clauses))

    if restores_baseline:
        owed_after = (
            f"reopen Channels by hand and read profiles == {value} and the seconds the "
            "application now states; this write returns the field to the trial baseline "
            f"({baseline}), so no further restoration is owed once that read is taken — this "
            "command does not close the obligation itself"
        )
    elif baseline is not None:
        owed_after = (
            f"reopen Channels by hand and read profiles == {value} and its seconds; the recorded "
            f"obligation is to restore the trial baseline profiles == {baseline} before the "
            "trial is closed"
        )
    else:
        owed_after = (
            f"reopen Channels by hand and read profiles == {value} and its seconds; no trial "
            "baseline was declared, so the only restoration recorded is this invocation's own "
            f"starting count (profiles == {expect})"
        )
    obligation = {
        "command": "acquire channels-profiles",
        "phase": "obligation",
        "written_at": stamp(),
        "slot": "profiles",
        # ``expect`` is this invocation's precondition; ``baseline`` is the trial's origin.
        "expect": expect,
        "value": value,
        "baseline": baseline,
        "restore_to": restore_to,
        "restore_to_source": (
            "declared-trial-baseline" if baseline is not None else "this-invocation"
        ),
        "restores_baseline": restores_baseline,
        "operator_channel": operator_channel,
        "operator_channel_declaration": OPERATOR_CHANNEL_DECLARATION,
        "channel_verified": False,
        "old_text": profiles.text,
        "old_seconds_text": old_seconds_text,
        "old_seconds": old_seconds,
        "other_facts": before,
        "mpx_disabled_declaration": MPX_DISABLED_STATEMENT,
        "bound_target": target.model_dump(mode="json"),
        "popup_hwnd": None if report.popup is None else report.popup.hwnd,
        "edit_hwnd": edit_hwnd,
        "owner_hwnd": owner_hwnd,
        "owed_after": owed_after,
        "persistence": "unknown until the operator reopens the dialog",
        "identity_limitation": (
            "one supervised binding; a popup closed and reopened between reads cannot be told "
            "from the one that was read, and no recording is performed by this command"
        ),
    }
    claim_trial_record(record_file, obligation)

    def after(
        stage: ProfilesWriteStage,
        *,
        writes: int,
        post: ChannelsRead | None = None,
        error: str = "",
        other_after: dict[str, str] | None = None,
    ) -> ChannelProfilesResult:
        """Every post-commit outcome, in one shape, with the record read back and updated."""
        persisted: Literal["unknown", "not_written"] = (
            "unknown" if writes else "not_written"
        )
        owed: list[str] = []
        new_text = (
            None
            if post is None or post.per_channel is None
            else post.per_channel.profiles.text
        )
        new_value = (
            None
            if post is None or post.per_channel is None
            else post.per_channel.profiles.value
        )
        new_seconds_text, new_seconds = ("", None) if post is None else _seconds(post)
        if post is None:
            new_seconds_text = None
        # Only a post-read that states the committed count is evidence the write landed; a raised
        # commit, a closed popup and a field that reads something else are not.
        landed = new_value is not None and int(new_value) == value
        recomputed = bool(
            landed
            and new_seconds_text is not None
            and (new_seconds_text, new_seconds) != (old_seconds_text, old_seconds)
        )
        # The one post-write instruction this outcome carries; it is also the record's
        # ``owed_after``, so a failed restore cannot leave the pre-write intent standing.
        confirm = ""
        if writes:
            owed.append(PERSISTENCE_UNPROVEN)
            if not landed:
                # The reading contradicts the committed count, so never tell the operator to
                # "confirm" it: ask for the count the field actually states, then name the
                # restore target the trial owes.
                target_note = (
                    f"the trial baseline profiles == {baseline}"
                    if baseline is not None
                    else (
                        "this invocation's own starting count profiles == "
                        f"{expect} (no trial baseline was declared)"
                    )
                )
                confirm = (
                    "a write attempt may have landed and the field does not read "
                    f"{value}: reopen the Channels popup by hand and read the profiles as it "
                    "actually states before concluding anything, then restore "
                    f"{target_note} (the obligation is recorded at {record_file})"
                )
            elif restores_baseline:
                confirm = (
                    "reopen the Channels popup by hand and read profiles == "
                    f"{value} and its seconds: this write returned the field to the trial "
                    "baseline, so no further restoration is owed once that read is taken, and "
                    f"only that read closes the obligation (recorded at {record_file})"
                )
            elif baseline is not None:
                confirm = (
                    "reopen the Channels popup by hand and read profiles == "
                    f"{value} and its seconds; before the trial is closed, restore the trial "
                    f"baseline profiles == {baseline} (the obligation is recorded at "
                    f"{record_file})"
                )
            else:
                confirm = (
                    "reopen the Channels popup by hand and read profiles == "
                    f"{value} and its seconds; no trial baseline was declared, so the only "
                    f"restoration this invocation can name is the count it found, profiles == "
                    f"{expect}, if the write is not wanted (the obligation is recorded at "
                    f"{record_file})"
                )
            owed.append(confirm)
        changes = () if other_after is None else _other_changes(before, other_after)
        # A preserved fact the post-write read did not state is unknown, not gone: it is carried
        # as its own observation, so an empty ``other_changes`` never reads as "they all held".
        unreadable = (
            () if other_after is None else _facts_unreadable(before, other_after)
        )
        record = {
            **obligation,
            "phase": "after",
            "completed_at": stamp(),
            "stage": stage.value,
            "writes": writes,
            "persisted": persisted,
            "new_text": new_text,
            "new_value": new_value,
            "new_seconds_text": new_seconds_text,
            "new_seconds": new_seconds,
            "seconds_recomputed": recomputed,
            "other_facts_after": other_after if other_after is not None else {},
            "other_changes": list(changes),
            "other_facts_unreadable": list(unreadable),
            "error": error,
            "owed_after": confirm or obligation["owed_after"],
            # ``restores_baseline`` above is the pre-write intent; this is the observation.
            "restored_baseline": bool(restores_baseline and landed),
            # The command can never close the trial: a reopened read is the operator's.
            "obligation_open": bool(writes),
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
        return ChannelProfilesResult(
            stage=stage,
            bound_target=target,
            popup_hwnd=None if post is None or post.popup is None else post.popup.hwnd,
            expect=expect,
            value=value,
            operator_channel=operator_channel,
            baseline=baseline,
            restore_to=restore_to,
            old_text=profiles.text,
            old_value=int(profiles.value),
            old_seconds_text=old_seconds_text,
            old_seconds=old_seconds,
            new_text=new_text,
            new_value=None if new_value is None else int(new_value),
            new_seconds_text=new_seconds_text,
            new_seconds=new_seconds,
            seconds_recomputed=recomputed,
            other_facts=before,
            other_facts_after=dict(other_after or {}),
            other_changes=changes,
            other_facts_unreadable=unreadable,
            writes=writes,
            # Claimed only from the post-write reading: a commit that raised, a closed popup
            # and a count that did not take are all unknown, never "restored".
            restored_baseline=bool(restores_baseline and landed),
            obligation_open=bool(writes),
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
            ProfilesWriteStage.COMMIT_RAISED,
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
            ProfilesWriteStage.WRITE_UNVERIFIED,
            writes=1,
            error=(
                f"the post-write read failed ({type(exc).__name__}: {exc}); the commit returned "
                "but the field's new value could not be seen, and nothing was re-read or retried"
            ),
        )
    if (
        post.surface is not ChannelsSurface.SETTINGS_POPUP
        or post.per_channel is None
        or post.per_channel.profiles.value is None
    ):
        # The reading is carried even though the profiles amount is not there: reporting it as
        # ``post=None`` threw away everything the same read *did* state — the raw text the widget
        # shows and every preserved fact — as if no read had been taken. ``_facts_after`` is the
        # surface gate's answer, so a surface that states none of those facts stays unknown
        # instead of reading as every one of them having vanished.
        stated = (
            "no per-channel profiles amount could be read from the popup"
            if post.per_channel is None
            else f"its profiles widget states {post.per_channel.profiles.text!r}"
        )
        return after(
            ProfilesWriteStage.WRITE_UNVERIFIED,
            writes=1,
            post=post,
            other_after=_facts_after(post),
            error=(
                f"the popup reads {post.surface.value!r} after the write and {stated}; the "
                "field's new value could not be seen, so whether the write landed is unknown "
                "and nothing was retried"
            ),
        )
    if post.per_channel.profiles.value != value:
        return after(
            ProfilesWriteStage.WRITE_UNVERIFIED,
            writes=1,
            post=post,
            other_after=_preserved_facts(post),
            error=(
                f"the field reads {post.per_channel.profiles.text!r} where {value} was committed; "
                "the field did not take the value and nothing was retried"
            ),
        )
    _post_seconds_text, post_seconds = _seconds(post)
    if not _seconds_valid(post_seconds):
        return after(
            ProfilesWriteStage.WRITE_UNVERIFIED,
            writes=1,
            post=post,
            other_after=_preserved_facts(post),
            error=(
                "the profiles field reads the committed count but the coupled seconds amount "
                f"reads {_post_seconds_text!r}, which is not a valid positive amount: the "
                "recomputation cannot be accepted and nothing was retried"
            ),
        )
    other_after = _preserved_facts(post)
    changes = _other_changes(before, other_after)
    if changes:
        return after(
            ProfilesWriteStage.WRITTEN_OTHER_FACTS_CHANGED,
            writes=1,
            post=post,
            other_after=other_after,
        )
    recomputed = (_post_seconds_text, post_seconds) != (old_seconds_text, old_seconds)
    return after(
        ProfilesWriteStage.WRITTEN_SECONDS_RECOMPUTED
        if recomputed
        else ProfilesWriteStage.WRITTEN,
        writes=1,
        post=post,
        other_after=other_after,
    )
