"""The **record-multiplexed** command: one ``Record``, the application's own completion, one store.

A multiplexed acquisition is finite by configuration: the operator enables the multiplexer, sets
each channel and its profiles, and presses ``Record`` **once**. The configured sequence then ends
by itself, the application returns the strip to the store row, and the block is stored under a
name. That is the whole sequence — and it is the one the single-channel cycle
(:func:`…actuator.Actuator.record_and_store`) cannot express, because that cycle ends a recording
with ``Stop`` after a requested duration.

**What it presses.** ``Record`` exactly once, and then ``Do store`` exactly once — the latter is
:func:`…store_completed.store_completed`, unchanged, on the **same** actuator and the **same**
bound window the recording was started from. Nothing else is pressed: no ``Stop``, no ``Pause``,
no ``Clear and restart``, no ``New acquisition``, no ``Remove current block``, no ``Disable
multiplexer``, no ``Channels`` menu, no parameter write. There is no retry, and nothing is
cleaned up on a failure — a recording left running is reported as running.

**What must be declared, and what is read.** The multiplexer's mode has no passive discriminator
in this repository (the menubar paints every entry; a single-channel screen and an enabled-MPX
one are the same surfaces), so the mode is the **operator's declaration** — required, named and
attributed — and never inferred from a strip that happens to read ``ready``. The channels and the
per-channel profile count are declared the same way, by the same rule the store-only command
judges (:func:`…store_completed.block_declaration_clauses`). The completion deadline is a caller
bound in seconds, not a value derived from any channel's dwell: this module invents no dwell and
converts no configured count into an observed one.

**The screen is read, and re-read.** Exactly one visible ``TMain_Scr`` window; its caption states
the instrument; no overlay is up; the strip is the measured three-button ``Pause`` / ``Record`` /
``Clear and restart`` row with no slider. Those four are re-read immediately before the press,
because the screen changes between a check and a gesture.

**The output is proved before the press, not after it.** The store name is one safe file-name
stem, the directory exists and can be listed, and nothing in it already bears that stem — all
checked by the store owner's own preflight
(:func:`…store_completed.store_preflight`) before ``Record`` is pressed, so a run whose block could
not be stored is never started.

**The completion is the strip's own classification, and an unsettled row is terminal.** The poll
is bounded by ``completion_timeout_s``; ``STORE`` with the slider and exactly two buttons is the
completion this command stores. A ``READY`` reading straight after the press is *provisional*
inside ``queue_grace_s`` — the press is queued, not synchronous — and becomes "the press never
turned into a recording" only once that grace has passed. Every outcome after the press is a
:class:`MultiplexedRecordingResult`, because what the instrument still owes is the fact the
operator needs; only a refusal **before** any press raises
:class:`~udv_echo_process.acquire.udop.AcquisitionError`, which is the boundary the CLI turns into
one line and exit 2.

**The stored artifact is verified, and the store stays stored.** After the one store returns a
path, that exact path — never a directory listing or a name guess — is decoded with the existing
:func:`…mpx_artifact.verify_mpx_artifact` against the **original validated declaration**
(:meth:`MultiplexedRecordingDeclaration.completed_block`, so the operator's own ``stated_by`` /
``stated_at`` / ``statement`` are the ones judged). The result is a separate typed
``artifact_verification`` report; the stored fact is unaffected by what it says. A contradiction,
an unverifiable or unreadable file, and even a verifier that raises or returns no typed report
are all reported as a stored run with the verification outcome (or an explicit verification
unknown), never as a re-record, a re-store, a retry or a cleanup.

Nothing here runs at import time: no window is read, no message posted, no file written.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationError, model_validator

from udv_echo_process.acquire.actuator import (
    STORE_TIMEOUT_S,
    STRIP_BUTTON_ORDER,
    StripControl,
    StripState,
    StripView,
    WindowTarget,
)
from udv_echo_process.acquire.driver import Win32Actuator
from udv_echo_process.acquire.mpx_artifact import (
    MpxArtifactReport,
    MpxVerdict,
    verify_mpx_artifact,
)
from udv_echo_process.acquire.store_completed import (
    CompletedBlockDeclaration,
    CompletedStoreResult,
    block_declaration_clauses,
    screen_clauses,
    store_completed,
    store_preflight,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "MPX_MODE_NOT_READ",
    "POLL_S",
    "QUEUE_GRACE_S",
    "MpxStage",
    "MultiplexedRecordingDeclaration",
    "MultiplexedRecordingResult",
    "ready_row_clauses",
    "record_multiplexed",
]

#: How often the strip is read while waiting for the application's own completion. A poll
#: interval, not a decision, and the same cadence the store-only path uses for its dialog.
POLL_S = 0.25

#: How long a ``ready`` reading straight after the ``Record`` press stays provisional. The press
#: is queued: the application starts the acquisition from its own message loop, so the row can
#: still read ``ready`` for a poll or two. This is a bounded grace, not a second wait, and it
#: never extends the completion deadline.
QUEUE_GRACE_S = 3.0

#: The measured ``ready`` row: ``Pause``, ``Record``, ``Clear and restart``, no slider
#: (:data:`…actuator.STRIP_BUTTON_ORDER`). Stated as data so the press binds a role, not a
#: position that happens to be second.
_READY_ROW = (
    StripControl.PAUSE,
    StripControl.RECORD,
    StripControl.CLEAR_AND_RESTART,
)

#: The measured MPX completion row, which is the only row this command stores from.
_COMPLETION_ROW = (StripControl.DO_STORE, StripControl.CLEAR_AND_RESTART)

#: The one sentence every non-stored report carries: the mode is never read, here or after.
MPX_MODE_NOT_READ = (
    "the multiplexer's mode was not read: this repository has no passive MPX discriminator, "
    "this command presses no Disable, and the operator's declaration is the only statement of it"
)


class MultiplexedRecordingDeclaration(ValueModel):
    """The operator's statement that the multiplexer is **on**, and of the block it will produce.

    Three facts, and none of them is a reading:

    - ``multiplexer_enabled`` — the operator configured the mode and left it enabled. Required to
      be true: this command starts a finite multiplexed recording, and a single-channel screen
      would produce a block the declared channel set does not describe. Nothing infers it from
      the strip's ``ready`` row, because that row is the *same* row in both modes.
    - ``channels`` / ``profiles_per_channel`` — the configured channel set and each channel's
      profile count, judged by :func:`…store_completed.block_declaration_clauses`, the rule the
      store-only path applies to the same statement. ``profiles_per_visit`` with
      ``sequence_repeats`` is the explicit repeated-sequence basis, mutually exclusive with the
      legacy total: their product is the expected stored total, computed once by the store-only
      declaration, and the repeat count itself is never compared with anything decoded.
    - ``stated_by`` — who said so. An unattributed 'yes' is not a declaration.
    """

    multiplexer_enabled: bool = Field(strict=True)
    channels: tuple[Annotated[int, Field(strict=True, gt=0)], ...]
    #: The operator's stated **total** per channel (the legacy basis); ``None`` when the count
    #: is stated per visit and repeated instead. Strict: a bool or a string is not a count.
    profiles_per_channel: int | None = Field(default=None, strict=True)
    #: The operator's stated count for one visit; only valid paired with ``sequence_repeats``.
    profiles_per_visit: int | None = Field(default=None, strict=True)
    #: The operator's stated repeat count. Never compared with a decoded count.
    sequence_repeats: int | None = Field(default=None, strict=True)
    stated_by: str
    stated_at: str = ""
    #: The operator's own words, kept raw for the report.
    statement: str = ""

    @model_validator(mode="after")
    def _require_stated(self) -> MultiplexedRecordingDeclaration:
        clauses = self.clauses()
        if clauses:
            raise ValueError("; ".join(clauses))
        return self

    def clauses(self) -> tuple[str, ...]:
        """Everything this declaration fails to state, as refused clauses (empty when valid)."""
        out: list[str] = []
        if not self.multiplexer_enabled:
            out.append(
                "the operator has not declared the multiplexer enabled: this command records a "
                "finite multiplexed acquisition, the mode has no passive read in this repository, "
                "and nothing is inferred from a 'ready' strip that looks the same in both modes"
            )
        out.extend(
            block_declaration_clauses(
                self.channels,
                self.profiles_per_channel,
                self.stated_by,
                profiles_per_visit=self.profiles_per_visit,
                sequence_repeats=self.sequence_repeats,
            )
        )
        return tuple(out)

    def completed_block(self) -> CompletedBlockDeclaration:
        """The same statement, as the store-only command's completed-block declaration.

        One operator, one statement, two stages: before the press it describes what the
        configured sequence will contain, and when the application has finished the block it is
        exactly the declaration the store path requires. Deriving it here rather than asking the
        operator twice keeps the two from disagreeing.
        """
        return CompletedBlockDeclaration(
            channels=self.channels,
            profiles_per_channel=self.profiles_per_channel,
            profiles_per_visit=self.profiles_per_visit,
            sequence_repeats=self.sequence_repeats,
            stated_by=self.stated_by,
            stated_at=self.stated_at,
            statement=self.statement,
        )

    @property
    def expected_total_profiles(self) -> int:
        """The expected stored total per channel, normalized by the completed-block owner."""
        return self.completed_block().expected_total_profiles

    @property
    def repeat_verification_unknown(self) -> str:
        """The visit-count unknown this declaration carries, or ``""`` on the legacy basis."""
        return self.completed_block().repeat_verification_unknown

    def count_summary(self) -> str:
        """One person-readable clause naming the count, its basis and its arithmetic."""
        return self.completed_block().count_summary()


class MpxStage(str, Enum):
    """How far the run got — each member says what was established, not what was tried."""

    #: The ``Record`` press was refused or failed; whether anything started is unknown.
    RECORD_REFUSED = "record_refused"
    #: The press returned and the strip stayed ``ready`` past the queue grace: no recording.
    RECORD_NOT_STARTED = "record_not_started"
    #: A recording was seen, and the strip is not a row this vocabulary settles.
    COMPLETION_UNKNOWN = "completion_unknown"
    #: The deadline passed with the strip still recording: the recording is left running.
    STILL_RUNNING = "still_running"
    #: Completion was seen and the store-only command refused or failed, once.
    STORE_FAILED = "store_failed"
    #: Completion was seen and the block was stored under the requested name.
    STORED = "stored"


class MultiplexedRecordingResult(ValueModel):
    """What one record-multiplexed run established, and what the instrument still owes.

    The stage is the outcome; every field beside it is evidence a reader on another machine can
    check. ``record_presses`` counts the presses that **returned** (one on every path but
    :attr:`MpxStage.RECORD_REFUSED`), and ``bound_target`` is the window the press was sent to —
    the same record the store's own result carries, so the two halves of the run are provably one
    binding. ``error`` preserves the original failure text (``Type: message``) rather than a
    paraphrase, because a driver's own words are the only account of what it saw.
    """

    stage: MpxStage
    declaration: MultiplexedRecordingDeclaration
    name: str
    directory: Path
    bound_target: WindowTarget
    record_presses: int = Field(ge=0)
    record_started: bool = False
    #: Every strip reading the wait took, as ``view/buttons/slider`` — the poll's own survey, so a
    #: reader can see the queued ``ready``, the ``recording`` and the ``store`` it settled on.
    observed: tuple[str, ...] = ()
    #: The row the wait accepted as the completion, read once and carried as evidence.
    completion_state: StripState | None = None
    #: The store-only command's result, when it returned one. ``None`` on every other path.
    store: CompletedStoreResult | None = None
    stored_path: Path | None = None
    #: The post-store check of ``stored_path`` against the **original** declaration. ``None``
    #: before a store, and after one only when the verifier itself failed
    #: (``artifact_verification_error`` then says so): a verification unknown, never a store
    #: failure and never a reason to act twice.
    artifact_verification: MpxArtifactReport | None = None
    #: ``Type: message`` from a verifier that raised. Empty when the check ran.
    artifact_verification_error: str = ""
    #: Whether :func:`…store_completed.store_completed` was invoked at all.
    store_invoked: bool = False
    #: The original failure text, ``Type: message`` — empty when nothing failed.
    error: str = ""
    reason: str = ""
    owed: tuple[str, ...] = ()
    driver_notes: tuple[str, ...] = ()
    #: What this run states about its own gestures — carried on a stored run so the record says
    #: which presses were made and which were never made, rather than leaving it implied.
    notes: tuple[str, ...] = ()

    @property
    def stored(self) -> bool:
        """Whether a new entry attributed to the requested name appeared."""
        return self.stage is MpxStage.STORED

    @property
    def artifact_consistent(self) -> bool:
        """Whether the stored artifact matched the original declaration (never a store test)."""
        return (
            self.artifact_verification is not None
            and self.artifact_verification.verdict is MpxVerdict.CONSISTENT
        )

    def summary(self) -> str:
        """One line for a log: what the run established, or why it stopped and what is owed."""
        head = (
            f"multiplexed recording on channels {list(self.declaration.channels)} "
            f"({self.declaration.count_summary()}, as stated by "
            f"{self.declaration.stated_by!r}): {self.stage.value}"
        )
        if self.stored and self.store is not None:
            head += f" {self.stored_path}; {self.store.summary()}"
            if self.artifact_verification is not None:
                head += (
                    f"; artifact verification {self.artifact_verification.verdict.value} "
                    f"(sha256 {self.artifact_verification.file_sha256 or 'unknown'})"
                )
            elif self.artifact_verification_error:
                head += (
                    "; artifact verification unknown: "
                    f"{self.artifact_verification_error}"
                )
        elif self.reason:
            head += f" — {self.reason}"
        if self.owed:
            head += f"; still owed: {'; '.join(self.owed)}"
        return head


def ready_row_clauses(state: StripState) -> tuple[str, ...]:
    """Why ``state`` is not the ``ready`` row a ``Record`` press starts from, or ``()``.

    The measured ready row is three buttons and **no** slider — ``Pause``, ``Record``, ``Clear
    and restart``. A sliderising row is a store view (a block that was never stored), one button
    is a recording already in progress, and four buttons without a slider is the row ledger B10
    leaves unresolved. Pressing ``Record`` from any of them would record over data the operator
    did not store or act on a row whose roles nothing states.
    """
    if state.has_slider:
        return (
            (
                f"the strip reads {state.view.value!r} with {state.button_count} button(s) and a "
                "slider, not the ready row: a block is already on screen, and this command "
                "records from the stopped row rather than over one it did not store"
            ),
        )
    if state.view is not StripView.READY:
        return (
            (
                f"the strip reads {state.view.value!r} with {state.button_count} button(s) and no "
                "slider where 'ready' is required: this command starts a recording only from the "
                "stopped three-button row"
            ),
        )
    if STRIP_BUTTON_ORDER.get((state.view, state.button_count)) != _READY_ROW:
        return (
            (
                "the ready row binds "
                f"{[c.value for c in STRIP_BUTTON_ORDER.get((state.view, state.button_count), ())]}"
                f" where this command requires exactly {[c.value for c in _READY_ROW]}: no "
                "'Record' role is bound in it, so nothing is pressed"
            ),
        )
    return ()


def _positive_seconds(label: str, value: float) -> float:
    """``value`` as a finite positive number of seconds, or a refusal naming ``label``."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise AcquisitionError(
            f"{label} must be finite positive seconds, got {value!r}"
        )
    return float(value)


def _post_store_verification(
    verify: Callable[[Path, CompletedBlockDeclaration], MpxArtifactReport],
    path: Path,
    declaration: CompletedBlockDeclaration,
) -> tuple[MpxArtifactReport | None, str]:
    """Check the stored file, turning any verifier failure into an explicit unknown.

    The store has already happened, so nothing here may undo it: a verifier that raises is
    reported as ``(None, "Type: message")`` rather than escaping to the caller's refusal
    boundary, and no retry, re-store or cleanup follows.

    The report is also checked at this boundary. A verifier is a caller-supplied seam, so a
    ``None`` or a wrongly typed return (a ``dict``, a bare verdict) is a *report-less* check,
    not a consistent one: it becomes the same explicit verification unknown with a reason
    naming what arrived. Reading ``.verdict`` — or ``.clauses`` downstream — off such a value
    must never be the way the caller finds out, so the stored facts and path are returned
    untouched beside ``(None, reason)``.
    """
    try:
        report = verify(path, declaration)
    except Exception as exc:  # noqa: BLE001 - a post-store verification failure is a report
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(report, MpxArtifactReport):
        arrived = "None" if report is None else type(report).__name__
        return None, (
            f"the artifact verifier returned {arrived} where an MpxArtifactReport was "
            "required, so the stored file's content was not verified"
        )
    return report, ""


def record_multiplexed(
    name: str,
    directory: Path,
    *,
    declaration: MultiplexedRecordingDeclaration,
    completion_timeout_s: float,
    channel: int | None = None,
    store_timeout_s: float = STORE_TIMEOUT_S,
    dialog_timeout_s: float = 10.0,
    poll_s: float = POLL_S,
    queue_grace_s: float = QUEUE_GRACE_S,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    verify_artifact: Callable[
        [Path, CompletedBlockDeclaration], MpxArtifactReport
    ] = verify_mpx_artifact,
    notes: list[str] | None = None,
) -> MultiplexedRecordingResult:
    """One ``Record``, the application's own completion, one store — or a report saying why not.

    ``completion_timeout_s`` is the caller's bound on the *whole* wait for the application's
    completion, never a dwell and never derived from the declared profile count. Everything the
    run needs is settled before the press: the declaration, every bound, the store's own output
    preflight (name, directory, collision), the single-window binding, the caption, the overlay
    and the ready row. A refusal on any of those raises
    :class:`~udv_echo_process.acquire.udop.AcquisitionError` with nothing pressed.

    After the press every outcome is returned, never raised: a completion that could not be read,
    a row the vocabulary does not settle, a deadline that expired with the recording still
    running, and a store that failed are all facts the operator has to act on, and none of them
    triggers a second attempt or a cleanup press.

    Once the store returns a path, that exact path is checked against the original validated
    declaration and the typed report is carried beside the stored facts. The check cannot change
    the stored stage, cannot fail the run, and never causes a second Record, store or cleanup;
    a verifier that raises or returns no typed report leaves an explicit verification unknown
    instead.
    """
    try:
        declaration = MultiplexedRecordingDeclaration.model_validate(declaration)
    except ValidationError as exc:
        raise AcquisitionError(
            f"invalid multiplexed recording declaration: {exc}"
        ) from exc
    _positive_seconds("completion_timeout_s", completion_timeout_s)
    _positive_seconds("store_timeout_s", store_timeout_s)
    _positive_seconds("dialog_timeout_s", dialog_timeout_s)
    _positive_seconds("poll_s", poll_s)
    if (
        isinstance(queue_grace_s, bool)
        or not isinstance(queue_grace_s, (int, float))
        or not math.isfinite(queue_grace_s)
        or queue_grace_s < 0
    ):
        raise AcquisitionError(
            f"queue_grace_s must be finite and >= 0, got {queue_grace_s!r}"
        )

    # The output is proved before the press: a block this run could not store is one it must not
    # record. The store-only command repeats these checks at its own press, which is why the
    # early call is the *same* rule and not a copy.
    target_dir = store_preflight(name, directory)

    sink = notes if notes is not None else []
    live = (
        actuator
        if actuator is not None
        else Win32Actuator(channel=channel, note_sink=sink.append)
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
        live, target, windows, class_name=class_name, strip=ready_row_clauses
    )
    if clauses:
        raise AcquisitionError("; ".join(clauses))

    # The screen changes between a check and a gesture: the window count, the caption, the
    # overlay and the row are read again here, immediately before the one press.
    clauses, state = screen_clauses(
        live,
        target,
        tuple(enumerate_windows_fn()),
        class_name=class_name,
        strip=ready_row_clauses,
    )
    if clauses:
        raise AcquisitionError("; ".join(clauses))
    assert state is not None  # no clause was produced, so the row was read and accepted

    def result(stage: MpxStage, **fields) -> MultiplexedRecordingResult:
        """Every post-press outcome, in one shape, with the binding and the survey carried."""
        fields.setdefault(
            "owed",
            (
                MPX_MODE_NOT_READ,
                "the completed block's whereabouts are unestablished; nothing was retried",
            ),
        )
        return MultiplexedRecordingResult(
            stage=stage,
            declaration=declaration,
            name=name,
            directory=target_dir,
            bound_target=target,
            observed=fields.pop("observed", ()),
            driver_notes=tuple(getattr(live, "warnings", ())),
            **fields,
        )

    observed: list[str] = [
        f"entry:{state.view.value}/{state.button_count}/{int(state.has_slider)}"
    ]
    try:
        live.press(StripControl.RECORD)  # once
    except Exception as exc:  # noqa: BLE001 - the press's own refusal is a report
        return result(
            MpxStage.RECORD_REFUSED,
            record_presses=0,
            error=f"{type(exc).__name__}: {exc}",
            reason=(
                "the Record press was refused or failed: "
                f"{type(exc).__name__}: {exc}; whether a recording started is unknown and "
                "nothing was retried"
            ),
            observed=tuple(observed),
            owed=(
                MPX_MODE_NOT_READ,
                (
                    "whether a recording is running is unknown; no Stop was sent and nothing "
                    "was retried"
                ),
            ),
        )
    pressed_at = clock()
    deadline = pressed_at + completion_timeout_s
    grace_until = pressed_at + queue_grace_s
    recording_seen = False

    # --- the application's own completion; never Stop, never extend the wait ---------------
    while True:
        try:
            state = live.strip_state()
        except Exception as exc:  # noqa: BLE001 - an unreadable strip is a terminal report
            return result(
                MpxStage.COMPLETION_UNKNOWN,
                record_presses=1,
                record_started=recording_seen,
                error=f"{type(exc).__name__}: {exc}",
                reason=(
                    "the completion could not be read: "
                    f"{type(exc).__name__}: {exc}; it is unknown, nothing was retried, and the "
                    "block was not discarded"
                ),
                observed=tuple(observed),
                owed=(
                    MPX_MODE_NOT_READ,
                    "a recording may still be running; no Stop was sent and nothing was stored",
                ),
            )
        observed.append(
            f"wait:{state.view.value}/{state.button_count}/{int(state.has_slider)}"
        )
        if state.view is StripView.RECORDING:
            recording_seen = True
        elif state.view is StripView.STORE:
            if (
                state.has_slider
                and state.button_count == 2
                and STRIP_BUTTON_ORDER.get((StripView.STORE, 2)) == _COMPLETION_ROW
            ):
                break
            return result(
                MpxStage.COMPLETION_UNKNOWN,
                record_presses=1,
                record_started=recording_seen,
                reason=(
                    f"the strip reads {state.view.value!r} with {state.button_count} button(s) "
                    f"and {'a' if state.has_slider else 'no'} slider where the measured "
                    "two-button multiplexed completion row is required: this row binds roles "
                    "this command does not store from, and an unsettled completion is terminal"
                ),
                observed=tuple(observed),
                owed=(
                    MPX_MODE_NOT_READ,
                    "the block remains unstored on the strip; nothing was retried or discarded",
                ),
            )
        elif state.view is StripView.READY:
            # A queued press leaves the row reading 'ready' for a moment. Inside the grace that
            # is provisional: poll again, press nothing, fail nothing.
            if not recording_seen and clock() < grace_until and clock() < deadline:
                sleep(poll_s)
                continue
            return result(
                MpxStage.RECORD_NOT_STARTED,
                record_presses=1,
                record_started=recording_seen,
                reason=(
                    "the strip still reads 'ready' "
                    + (
                        "after the recording ended without a block"
                        if recording_seen
                        else f"past the {queue_grace_s:g} s queue grace after the Record press, "
                        "without ever reading 'recording'"
                    )
                    + "; the press was made once and is not repeated"
                ),
                observed=tuple(observed),
                owed=(
                    MPX_MODE_NOT_READ,
                    (
                        "whether the application started and finished a block is unestablished; "
                        "nothing was pressed again and nothing was stored"
                    ),
                ),
            )
        else:
            return result(
                MpxStage.COMPLETION_UNKNOWN,
                record_presses=1,
                record_started=recording_seen,
                reason=(
                    f"the completion is unknown: the strip reads {state.view.value!r} with "
                    f"{state.button_count} button(s), a row this vocabulary does not settle — "
                    "nothing is pressed and the store is not attempted"
                ),
                observed=tuple(observed),
                owed=(
                    MPX_MODE_NOT_READ,
                    "the block's state is unestablished; nothing was retried or discarded",
                ),
            )
        if clock() >= deadline:
            return result(
                MpxStage.STILL_RUNNING,
                record_presses=1,
                record_started=recording_seen,
                reason=(
                    f"the recording had not completed within the caller's {completion_timeout_s:g} s "
                    "bound and is left running: this command never presses Stop and never extends "
                    "its own wait"
                ),
                observed=tuple(observed),
                owed=(
                    MPX_MODE_NOT_READ,
                    "a recording is still in progress; nothing was stopped, stored or discarded",
                ),
            )
        sleep(poll_s)

    completion_state = state
    completion_facts = (
        f"wait:{state.view.value}/{state.button_count}/{int(state.has_slider)}"
    )

    # --- one store, through the store-only command, on the same binding --------------------
    try:
        stored = store_completed(
            name,
            target_dir,
            declaration=declaration.completed_block(),
            channel=channel,
            store_timeout_s=store_timeout_s,
            dialog_timeout_s=dialog_timeout_s,
            actuator=live,
            enumerate_windows=enumerate_windows_fn,
            class_name=class_name,
            target=target,
            notes=sink,
        )
    except Exception as exc:  # noqa: BLE001 - preserve every post-Record store failure
        return result(
            MpxStage.STORE_FAILED,
            record_presses=1,
            record_started=recording_seen,
            completion_state=completion_state,
            store_invoked=True,
            error=f"{type(exc).__name__}: {exc}",
            reason=(
                "the store was attempted once through the store-only command and did not "
                f"complete: {exc}. That command refuses a taken name, an unlistable directory "
                "and a screen that is not the completed row *before* it presses 'Do store', so "
                "its own words state whether anything was committed; nothing was retried"
            ),
            observed=tuple(observed) + (completion_facts,),
            owed=(
                MPX_MODE_NOT_READ,
                (
                    "the completed block remains unstored, or was stored under a name this run "
                    "could not attribute; the store was not retried"
                ),
            ),
        )

    # --- the stored artifact, against the original declaration (never a second action) ------
    # The store already succeeded, so this cannot change the stage: a contradiction, an
    # unverifiable/unreadable file or a raising verifier are all reported beside a stored run.
    artifact_verification, verification_error = _post_store_verification(
        verify_artifact, stored.stored_path, declaration.completed_block()
    )
    verification_owed: tuple[str, ...] = ()
    if artifact_verification is None:
        verification_owed = (
            (
                "the stored file's content was not verified against the declaration "
                f"({verification_error or 'no reason reported'}); the file remains stored at "
                "the reported path and is neither re-recorded nor rewritten"
            ),
        )
    elif artifact_verification.verdict is not MpxVerdict.CONSISTENT:
        verification_owed = (
            (
                "the stored file's artifact verification is "
                f"{artifact_verification.verdict.value}, not consistent: the file remains "
                "stored at the reported path and is neither re-recorded nor re-stored"
            ),
        )
    # A repeated declaration's per-visit/repeat pair is the operator's arithmetic, never a
    # decoded partition: the stored bytes carry an unpartitioned total, so the repeat count
    # stays owed even when that total matches the expectation.
    repeat_owed: tuple[str, ...] = (
        ()
        if declaration.sequence_repeats is None
        else (declaration.repeat_verification_unknown,)
    )

    return MultiplexedRecordingResult(
        stage=MpxStage.STORED,
        declaration=declaration,
        name=name,
        directory=target_dir,
        bound_target=target,
        record_presses=1,
        record_started=recording_seen,
        observed=tuple(observed) + (completion_facts,),
        completion_state=completion_state,
        store=stored,
        stored_path=stored.stored_path,
        artifact_verification=artifact_verification,
        artifact_verification_error=verification_error,
        store_invoked=True,
        driver_notes=tuple(getattr(live, "warnings", ())),
        notes=(
            (
                f"one 'Record' press on {target.hwnd} and one 'Do store' on the same binding; "
                "no Stop, Pause, Clear and restart, New acquisition, Remove current block, "
                "Disable multiplexer, Channels menu or parameter write"
            ),
        ),
        owed=(MPX_MODE_NOT_READ,) + repeat_owed + verification_owed,
    )
