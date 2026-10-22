"""One bounded multiplexed run: inspect, roll, enable, record, verify — once, offline-composed.

This is the **smallest** composition that turns the four existing owners into one supervised run.
It invents no gesture and no second implementation of any stage:

1. :func:`…channels_inspect.inspect_channels` — the disabled screen, closed, with capture evidence;
2. :func:`…set_rollover.acquire_set_rollover` — rolling ON, only when the fresh reading says it is
   not already on, and later the optional baseline restore;
3. :func:`…enable_multiplexed.acquire_enable_multiplexed` — the owned Enable press, from a popup
   this run opened on the original bound target;
4. :func:`…record_multiplexed.record_multiplexed` — one ``Record``, the application's own
   completion, one store, and the artifact check against the same operator declaration.

**One original target, and no second binding.** The parent enumerates the window once, binds it
once and verifies it; every child is handed that record through its ``bound_target`` seam and may
only call ``verify_bound_target``. A child that is handed the record never calls ``bind_target``,
and the enumerated handle must equal the bound handle before anything is verified.

**Everything is proved before the first gesture.** The store name, the store directory, the
capture root, the parent record path and every caller bound are checked first; an inspection
that presses nothing comes next. Only then is the parent record claimed, exclusively, in a
``pending`` phase that states the paths and explicitly does not report actions that have not
happened. It is rewritten once, at the end, and a failed rewrite means the run is **not**
reported as a success — the pending record stays on disk as the obligation it is.

**Each run owns its own records.** The parent record is the caller's path and must not exist.
The three child records are named *after* this run's capture root is claimed exclusively, and
they live inside it (``<run root>/records``), so two runs that share one parent directory — the
normal case, since ``--record`` sits beside the capture root — can never claim the same child
file, and the earlier run's obligations are left byte-identical rather than overwritten. A child
that is handed a path already claimed refuses, which is the children's own rule, not a check
duplicated here.

**The parent record's file name is a per-run identifier, not this composition's choice.** When
``--record`` names a directory, ``mpx-run-record.json`` inside it is the *caller's* declared
identifier for one run in that directory: it is deliberately one fixed name, so an existing file
is an exact refusal (two distinct file names are two runs, which is the supported live pattern).
A batch caller must therefore pass one distinct ``--record`` per run; this composition never
picks a second name on the caller's behalf, and it never reuses a claimed record.

**Positive enabled mode comes from the Enable stage's own fresh post-press capture.** A ``ready``
strip is the same row in both modes and is never used as a mode fact. The production-reachable
enabled pair is the **clipped one-entry popup** (``multiplexer_on_entry``) whose own fresh pair
states ``VISUAL_ENABLED``; an ``absent`` post surface can never state that mode, and this
composition never turns ``absent`` into ``enabled``.

**The clipped entry is dismissed once, through the existing owner.** After that positive mode
fact, the parent takes a fresh bound read, requires it to be the clipped surface, and calls the
library's own :meth:`…dismiss_channels_popup` (one guarded stepped path). Both an observed
``ABSENT`` from that dismissal **and** a fresh bound read of ``ABSENT`` immediately before
``Record`` are required; a dismissal that refuses, raises or does not observe ``ABSENT`` stops the
run with no ``Record`` and no second path. That integration point sits immediately before
``Record``. If the dismissal geometry cannot fit, the owner's refusal is reported and nothing is
recorded.

**Every parent-licensed capture is strict.** The baseline inspection, the clipped-entry pair that
licenses the one dismissal, and the post-save capture must each be this run's own
live-bracketed, digest-verified, agreed pair, with both guards binding the original window
and the same popup panel and its directory under this run's own capture root (a distinct
child directory per purpose, so no two owners write ``capture-NNN`` names into one folder). A
retained pair, a wrong handle or a torn frame can never complete the run, and a child's literals
never substitute for the parent's own pair.

**Each rolling/mode fact names its source.** ``rolling_before`` is the baseline capture's,
``rolling_at_enable`` is whichever earlier owner last *observed* it (the rollover child's fresh
post read, or — when that press was skipped — the baseline capture itself), and ``rolling_after``
is the post-save capture's or the restore child's fresh post read. An ``UNKNOWN`` later read never
becomes "rolling is ON now". When the restore child proves ``OFF_PROVEN``, that read is the
after-fact and the final mode stays the **pre-restore** strict capture, labelled as such: no third
inspection is taken, so nothing is reported as a post-restore observation.

**No loop, no retry, no second Record.** One call to each child, at most once. A record that did
not store, or stored an artifact that is not consistent, stops the run with the artifact preserved.

**Child obligations are history, not a growing ledger.** Each child result keeps its own
``restoration_owed`` nested, untouched. The parent's own obligation list is derived from what
*this* run's fresh proofs settled: a baseline restore that the parent verified with a fresh
``OFF_PROVEN`` reading resolves the historical clause, so it is not added again forever.

Nothing here runs at import time.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from udv_echo_process.acquire import mode_marks
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.binding import resolve_bound_target
from udv_echo_process.acquire.channels_inspect import (
    ChannelInspection,
    InspectionOutcome,
    inspect_channels,
)
from udv_echo_process.acquire.channels_read import read_channels
from udv_echo_process.acquire.channels_repeat import (
    claim_trial_record,
    trial_record_file,
    update_trial_record,
)
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.enable_multiplexed import (
    EnableMultiplexedResult,
    acquire_enable_multiplexed,
)
from udv_echo_process.acquire.record_multiplexed import (
    MpxStage,
    MultiplexedRecordingDeclaration,
    MultiplexedRecordingResult,
    record_multiplexed,
)
from udv_echo_process.acquire.set_rollover import (
    Rolling,
    SetRolloverResult,
    acquire_set_rollover,
)
from udv_echo_process.acquire.store_completed import store_preflight
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
)
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "CAPTURE_RUN_LIMIT",
    "MPX_RUN_RECORD_NAME",
    "ClippedEntryResult",
    "ClippedEntryStage",
    "MpxFinalRecord",
    "MpxPopupCloseRecord",
    "MpxRunResult",
    "MpxRunStage",
    "bind_once",
    "capture_run_slots",
    "read_parent_record",
    "run_mpx_once",
    "settle_clipped_entry",
    "strict_flag",
    "validate_bounds",
    "validate_declaration",
]

#: The parent record's file name inside a directory the caller passed.
MPX_RUN_RECORD_NAME = "mpx-run-record.json"

#: The owner's own bound on exclusive ``mpx-run-NNN`` roots under one capture root. A batch
#: preflight asks the owner for the free slots rather than inventing a second number.
CAPTURE_RUN_LIMIT = 1000

#: The pending record's own disclaimer: it lists what is planned, never what was done.
PENDING_SCOPE = (
    "pending: paths, declaration and bounds are established; no press count is stated here "
    "because a press may follow and this record is not an outcome"
)

#: What a run that stopped before its store still owes the operator.
_NO_RECORD_OWED = (
    (
        "the multiplexed block was not recorded or was not stored by this run; the "
        "instrument's screen is the authority, and nothing was retried, stopped or discarded"
    ),
)


class MpxRunStage(str, Enum):
    """How far the one run got — each member is an established state, not an attempt."""

    #: Refused before any gesture (declaration, bounds, paths, binding).
    REFUSED = "refused"
    #: The baseline inspection refused or could not prove a closed popup.
    INSPECTION_REFUSED = "inspection_refused"
    #: The baseline reading is not the caller's declared literal.
    BASELINE_DISAGREED = "baseline_disagreed"
    #: Rolling ON was not established by the rollover child's own fresh post read.
    ROLLOVER_FAILED = "rollover_failed"
    #: The Enable child refused, raised or could not state a positive enabled mode.
    ENABLE_FAILED = "enable_failed"
    #: The Enable press left a panel this composition does not dismiss.
    POPUP_LEFT_OPEN = "popup_left_open"
    #: The record child did not return a stored block.
    RECORD_FAILED = "record_failed"
    #: Stored, but the artifact check is not consistent (the file is preserved).
    ARTIFACT_INCONSISTENT = "artifact_inconsistent"
    #: Stored, but the post-save state could not be read.
    POST_SAVE_UNKNOWN = "post_save_unknown"
    #: Stored, and the baseline restore was requested but not proved.
    RESTORATION_FAILED = "restoration_failed"
    #: Stored, with the baseline still ON and no restore requested.
    RESTORATION_OWED = "restoration_owed"
    #: The run finished, but the final parent-record rewrite failed: not a success.
    RECORD_UNWRITTEN = "record_unwritten"
    #: Stored, artifact consistent, and the baseline observed OFF.
    COMPLETE = "complete"

    @property
    def recorded(self) -> bool:
        """Whether this stage preserved a stored block."""
        return self in (
            MpxRunStage.ARTIFACT_INCONSISTENT,
            MpxRunStage.POST_SAVE_UNKNOWN,
            MpxRunStage.RESTORATION_FAILED,
            MpxRunStage.RESTORATION_OWED,
            MpxRunStage.COMPLETE,
        )


class MpxRunResult(ValueModel):
    """One run's evidence, with each child's own result nested rather than flattened.

    The children are the owners of their facts: ``inspection`` / ``rollover`` / ``enable`` /
    ``record`` are their typed reports untouched, and ``post_save`` is the second inspection.
    ``owed`` is this run's **current** obligation list, derived from fresh proofs; the children's
    historical clauses stay nested in their own fields.
    """

    stage: MpxRunStage
    name: str
    directory: Path
    capture_root: Path
    declaration: MultiplexedRecordingDeclaration
    baseline: str
    restore_baseline: bool
    bound_target: WindowTarget | None = None
    parent_record: Path | None = None
    parent_record_phase: Literal["", "pending", "final", "unwritten"] = ""
    parent_record_error: str = ""
    inspection: ChannelInspection | None = None
    rollover: SetRolloverResult | None = None
    enable: EnableMultiplexedResult | None = None
    record: MultiplexedRecordingResult | None = None
    post_save: ChannelInspection | None = None
    restore: SetRolloverResult | None = None
    #: The mode stated by this run's own verified capture (never inferred from a press or a strip).
    post_mode: str = "UNKNOWN"
    post_surface: str = "UNKNOWN"
    #: The mode the post-save capture established, which is a later fact than ``post_mode``.
    post_save_mode: str = "UNKNOWN"
    #: The one dismissal this run walked to clear the clipped entry, when it did.
    popup_close: ChannelsDismissal | None = None
    rolling_before: str = "UNKNOWN"
    #: Which owner stated ``rolling_before`` (``baseline_capture``); never empty when it is known.
    rolling_before_source: str = ""
    #: The latest observed rolling fact at the moment the Enable press was licensed, with its
    #: source. It is **not** a claim about the post-Enable moment when no capture read it.
    rolling_at_enable: str = "UNKNOWN"
    rolling_at_enable_source: str = ""
    rolling_after: str = "UNKNOWN"
    #: Which owner stated ``rolling_after`` — a capture or a child's fresh post read.
    rolling_after_source: str = ""
    baseline_restored: bool = False
    #: The fresh proof the restore rests on (``post_save_capture`` / ``restore_child_post_read``).
    baseline_restored_source: str = ""
    post_mode_source: str = ""
    post_save_mode_source: str = ""
    stored_path: Path | None = None
    artifact_consistent: bool = False
    error: str = ""
    reason: str = ""
    owed: tuple[str, ...] = ()
    resolved_child_obligations: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether this run stored a consistent artifact and settled the baseline."""
        return self.stage is MpxRunStage.COMPLETE

    def summary(self) -> str:
        """One line for a log: what the run established, or why it stopped and what is owed."""
        head = (
            f"mpx-run {self.name} on channels {list(self.declaration.channels)} "
            f"({self.declaration.count_summary()}, as stated by "
            f"{self.declaration.stated_by!r}): {self.stage.value}"
        )
        if self.stored_path is not None:
            head += f" {self.stored_path}"
        elif self.reason:
            head += f" — {self.reason}"
        if self.owed:
            head += f"; still owed: {'; '.join(self.owed)}"
        return head


class MpxPopupCloseRecord(ValueModel):
    """The clipped-entry dismissal evidence exactly as the owner writes it into the record.

    ``point`` is written as ``list(close.point or ())``, so it is an empty tuple when the child
    stated no point. It is typed as a variable-length integer tuple for that reason — narrowing
    it back to ``(x, y)`` would make a valid record look malformed.
    """

    outcome: DismissalOutcome
    surface_before: str
    surface_after: str
    point: tuple[int, ...] | None = None
    reads: int = 0
    steps: int = 0


class MpxFinalRecord(ValueModel):
    """The parent record's **final** durable contract, exactly as :func:`run_mpx_once` writes it.

    One owner: this module writes the record (``stop``) and reads it back through this model, so
    a later composition compares against the owner's schema rather than guessing at keys. A
    pending record is a different shape and is refused before validation, because "still pending"
    is a meaningfully different fact from "malformed".
    """

    command: str
    name: str
    store_dir: str
    capture_root: str
    declaration: MultiplexedRecordingDeclaration
    baseline: str
    restore_baseline: bool
    bound_target: WindowTarget
    parent_record: str
    child_records: dict[str, str]
    child_capture_dirs: dict[str, str]
    completion_timeout_s: float
    settle_s: float
    boundary_seconds: float | None
    phase: Literal["after"]
    completed_at: str
    scope: str
    stage: MpxRunStage
    reason: str
    error: str
    owed: tuple[str, ...]
    child_stages: dict[str, str]
    post_surface: str
    post_mode: str
    post_mode_source: str
    post_save_mode: str
    post_save_mode_source: str
    popup_close: MpxPopupCloseRecord | None
    stored_path: str | None
    artifact_consistent: bool
    rolling_before: str
    rolling_before_source: str
    rolling_at_enable: str
    rolling_at_enable_source: str
    rolling_after: str
    rolling_after_source: str
    baseline_restored: bool
    baseline_restored_source: str


#: The one mapping from the durable record's ``after`` phase to the in-memory result's named
#: phase. ``stop`` writes ``after`` for the single final rewrite and reports
#: ``parent_record_phase="final"`` in memory; a reader must not treat those as different facts.
FINAL_RECORD_PHASE = "after"


def read_parent_record(path: Path | str) -> MpxFinalRecord:
    """Read and validate a parent record through the owner's own schema.

    Every failure is a typed :class:`AcquisitionError` naming the exact file and the reason: a
    missing file, an unreadable file, text that is not one JSON object, a record that is still
    ``pending``, a phase that is not the final ``after``, or a payload that does not satisfy
    :class:`MpxFinalRecord`. No key is guessed and no value is repaired.
    """
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AcquisitionError(
            f"the parent record {target} is missing: the final record is the durable obligation, "
            "so nothing is inferred from memory"
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise AcquisitionError(
            f"the parent record {target} could not be read ({type(exc).__name__}: {exc}): the "
            "final record is the durable obligation, so nothing is inferred from memory"
        ) from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AcquisitionError(
            f"the parent record {target} is not readable JSON ({exc}): the durable record is "
            "the authority and no key is guessed"
        ) from exc
    if not isinstance(raw, dict):
        raise AcquisitionError(
            f"the parent record {target} is not one JSON object: the durable record is the "
            "authority and no key is guessed"
        )
    phase = raw.get("phase")
    if phase == "pending":
        raise AcquisitionError(
            f"the parent record {target} is still pending, not the final "
            f"{FINAL_RECORD_PHASE!r} record: a pending obligation is not an outcome"
        )
    if phase != FINAL_RECORD_PHASE:
        raise AcquisitionError(
            f"the parent record {target} states phase {phase!r}, not the final "
            f"{FINAL_RECORD_PHASE!r} record"
        )
    try:
        return MpxFinalRecord.model_validate(raw)
    except ValidationError as exc:
        raise AcquisitionError(
            f"the parent record {target} is malformed against the owner's final-record "
            f"contract: {exc}"
        ) from exc


def _now_stamp() -> str:
    return datetime.now(tz=UTC).astimezone().isoformat()


def _reason(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__


def _seconds(label: str, value: float, *, positive: bool) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or (value <= 0 if positive else value < 0)
    ):
        relation = "finite positive" if positive else "finite and >= 0"
        raise AcquisitionError(f"{label} must be {relation} seconds, got {value!r}")
    return float(value)


def validate_bounds(
    *,
    completion_timeout_s: float,
    settle_s: float,
    boundary_seconds: float | None,
) -> None:
    """Every caller bound this composition uses, refused before anything is inspected.

    One rule for the single run and the batch: the completion wait is finite positive, the
    settle bound finite and non-negative, and an optional boundary finite positive. Nothing
    here derives a bound from a declaration.
    """
    _seconds("completion_timeout_s", completion_timeout_s, positive=True)
    _seconds("settle_s", settle_s, positive=False)
    if boundary_seconds is not None:
        _seconds("boundary_seconds", boundary_seconds, positive=True)


def strict_flag(label: str, value: object) -> bool:
    """A caller's flag as an actual ``bool``, or a refusal — never a truthiness reading.

    Pydantic's lax bool parsing accepts ``"no"``/``"off"``/``"0"`` as ``False``, so a truthy
    non-bool could press the restore while the durable report validated to ``False``: the
    behaviour and the record would then disagree about a press this composition did make.
    """
    if not isinstance(value, bool):
        raise AcquisitionError(
            f"{label} must be a bool (true or false), got {value!r} of type "
            f"{type(value).__name__}: a flag is never read by truthiness, and the durable "
            "record would otherwise disagree with what this run pressed; nothing was "
            "inspected or pressed"
        )
    return value


def _rolling_literal(mark: object | None) -> str:
    """The capture's own rolling verdict, or ``"UNKNOWN"`` — never a guess from a strip."""
    if mark is None:
        return "UNKNOWN"
    value = getattr(mark, "rolling", "UNKNOWN")
    return value if value in ("ON_PROVEN", "OFF_PROVEN") else "UNKNOWN"


def _inspection_rolling(inspection: ChannelInspection | None) -> str:
    if inspection is None or inspection.read is None or inspection.read.capture is None:
        return "UNKNOWN"
    return _rolling_literal(inspection.read.capture.visual_mode_mark)


#: The only capture contexts a **parent** decision may rest on, stated by the producing owner.
_FRESH_CONTEXT = "live-bracketed"
_FRESH_INTEGRITY = "capture-digest-verified"


def _strict_capture(
    capture: object | None,
    *,
    target: WindowTarget,
    directory: Path,
) -> tuple[object | None, str]:
    """This run's own fresh, bracketed, digest-verified capture — or the clause that failed.

    The facts are the producing owner's (:mod:`…channels_capture` / :mod:`…mode_marks`); this
    helper only refuses a pair that is not live-bracketed, not digest-verified, not agreed, or
    not attributable to the original binding and the same popup panel. A retained pair, a
    wrong handle or a torn frame therefore never becomes this run's mode fact.
    """
    if capture is None:
        return None, "no fresh capture was taken in this invocation"
    if getattr(capture, "status", "UNKNOWN") != "ok":
        reasons = (
            "; ".join(getattr(capture, "unknown_reasons", ())) or "status is not ok"
        )
        return None, f"the capture is not ok ({reasons})"
    guards = getattr(capture, "guards", None)
    after_guard = None if guards is None else getattr(guards, "after", None)
    if (
        guards is None
        or not getattr(guards, "consistent", False)
        or after_guard is None
    ):
        failures = () if guards is None else getattr(guards, "failures", ())
        return None, "the window guards do not agree across the pair: " + (
            "; ".join(failures) or "no closing guard"
        )
    for guard in (guards.before, after_guard):
        if getattr(guard, "hwnd", None) != target.hwnd:
            return None, (
                f"the {getattr(guard, 'label', '')} guard resolved hwnd "
                f"{getattr(guard, 'hwnd', None)} where the run's binding is {target.hwnd}: "
                "identity drift, so no mode is stated"
            )
    popup_before = getattr(guards.before, "popup_hwnd", None)
    popup_after = getattr(after_guard, "popup_hwnd", None)
    if popup_before is None or popup_before != popup_after:
        return None, (
            f"the popup frame metadata disagrees across the pair "
            f"({popup_before!r} -> {popup_after!r}): a different panel's pixels state nothing"
        )
    mark = getattr(capture, "visual_mode_mark", None)
    if mark is None:
        return None, "the capture carries no mode attribution for its measured shape"
    if (
        getattr(mark, "acquisition_context", "") != _FRESH_CONTEXT
        or getattr(mark, "freshness", "") != "live_bracketed"
        or getattr(mark, "integrity", "") != _FRESH_INTEGRITY
        or getattr(mark, "frames_agreed", None) is not True
        or getattr(mark, "recognition", "") != "EXACT_TEMPLATE_MATCH"
    ):
        return None, (
            "the capture is not a fresh live-bracketed digest-verified pair "
            f"(context={getattr(mark, 'acquisition_context', None)!r}, "
            f"freshness={getattr(mark, 'freshness', None)!r}, "
            f"integrity={getattr(mark, 'integrity', None)!r}, "
            f"agreed={getattr(mark, 'frames_agreed', None)!r}, "
            f"recognition={getattr(mark, 'recognition', None)!r})"
        )
    digests = getattr(mark, "frame_digests", None)
    if digests is None or len(digests) != 2 or any(len(item) != 64 for item in digests):
        return None, "the capture carries no two genuine 64-character frame digests"
    claimed = getattr(capture, "directory", None)
    if claimed and Path(claimed).parent.resolve() != directory.resolve():
        return None, (
            f"the capture directory {claimed!r} is outside this run's child directory "
            f"{str(directory)!r}"
        )
    return mark, ""


def _claim_capture_run(base: Path) -> Path:
    """Claim one exclusive, empty run root under the caller's capture root.

    Evidence is never mixed across runs: an earlier ``mpx-run-NNN`` is left untouched and the
    next name is claimed with ``mkdir(exist_ok=False)`` before any hover or press.
    """
    for index in range(1, CAPTURE_RUN_LIMIT + 1):
        candidate = base / f"mpx-run-{index:03d}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise AcquisitionError(
        f"{CAPTURE_RUN_LIMIT} capture run roots already exist under the caller's capture root: "
        "refusing to reuse or mix another run's evidence, so nothing was inspected or pressed"
    )


def capture_run_slots(base: Path) -> int:
    """How many of the owner's own ``mpx-run-NNN`` names are still free under ``base``.

    This asks the **owner's** rule (:func:`_claim_capture_run`) rather than counting a glob:
    only the exact names that loop will try are counted, so a stray file, a name outside the
    ``001``–``1000`` range or a nested directory can never inflate or deflate the answer.
    """
    taken = 0
    for index in range(1, CAPTURE_RUN_LIMIT + 1):
        candidate = base / f"mpx-run-{index:03d}"
        try:
            os.stat(candidate)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise AcquisitionError(
                f"the capture root {base} could not be read at {candidate.name} "
                f"({type(exc).__name__}: {exc}): an unreadable root is not an empty one, so its "
                "free run roots are UNKNOWN and nothing was inspected or pressed"
            ) from exc
        taken += 1
    return CAPTURE_RUN_LIMIT - taken


def bind_once(
    *,
    actuator,
    enumerate_windows: Callable[[], Sequence[int]],
    class_name: str = MAIN_CLASS,
    bound_target: WindowTarget | None = None,
) -> WindowTarget:
    """Enumerate the instrument once and return the run's one verified target.

    With no ``bound_target`` this is the standalone rule: one ``bind_target`` on the single
    enumerated window, then its verification. With a handed record it **verifies only** that
    record — the enumerated handle must match it first — and never binds again, so a batch can
    bind once and hand the same record to every run.
    """
    windows = tuple(enumerate_windows())
    if len(windows) != 1:
        raise AcquisitionError(
            f"{len(windows)} visible {class_name} window(s) are up {list(windows)}: exactly one "
            "instrument must be running, and this composition does not choose between copies"
        )
    if bound_target is not None:
        return resolve_bound_target(
            actuator, windows, bound_target=bound_target, class_name=class_name
        )
    bound = actuator.bind_target(int(windows[0]))  # the one binding of this run
    return resolve_bound_target(
        actuator, windows, bound_target=bound, class_name=class_name
    )


def validate_declaration(
    declaration: MultiplexedRecordingDeclaration,
) -> MultiplexedRecordingDeclaration:
    """The operator's shared declaration, or the pre-gesture refusal that stops the run.

    One implementation for the single run and the batch: an invalid statement and a
    not-enabled multiplexer are both refused before anything is inspected, claimed or pressed.
    """
    try:
        validated = MultiplexedRecordingDeclaration.model_validate(declaration)
    except Exception as exc:
        raise AcquisitionError(
            f"invalid multiplexed recording declaration: {exc}"
        ) from exc
    if not validated.multiplexer_enabled:
        raise AcquisitionError(
            "the operator has not declared the multiplexer enabled: this run enables it and "
            "records a finite multiplexed block, and nothing is inferred from a 'ready' strip"
        )
    return validated


def _stage_value(child: object | None) -> str:
    """The child's own stage/outcome value, for a compact durable fact — never its full report."""
    if child is None:
        return ""
    for attribute in ("stage", "outcome"):
        value = getattr(child, attribute, None)
        if value is not None:
            return str(getattr(value, "value", value))
    return ""


def _settled(result: SetRolloverResult) -> bool:
    """Whether the child's own typed closure proves its popup settled — never assume it did.

    ``popup_closure is None`` means the child stated no closure at all, which is unknown; the
    earlier ``None`` reading treated that as settled and let a run continue on an unproved
    popup. Only a member whose own ``settled`` property says so counts.
    """
    closure = result.popup_closure
    return closure is not None and closure.settled


def _popup_clause(inspection: ChannelInspection | None) -> tuple[str, ...]:
    if inspection is None or inspection.popup_left_open is not True:
        return ()
    return (
        (
            "a Channels popup may still be open (the close was not observed ABSENT): the "
            "operator owns it, and no second path, message or restart is attempted"
        ),
    )


class ClippedEntryStage(str, Enum):
    """How far the one clipped-entry lifecycle got — each member is an observed state."""

    #: The clipped entry was read, dismissed through the owned path, and ABSENT was re-read.
    ABSENT = "absent"
    #: The fresh bound read before the dismissal raised.
    READ_RAISED = "read_raised"
    #: The fresh read is not the clipped one-entry popup.
    NOT_CLIPPED = "not_clipped"
    #: The fresh clipped capture does not state an enabled mode (only when required).
    NOT_ENABLED = "not_enabled"
    #: The owned dismissal refused or raised.
    DISMISS_RAISED = "dismiss_raised"
    #: The dismissal did not observe ABSENT.
    NOT_ABSENT = "not_absent"
    #: The fresh bound read after the dismissal raised.
    REREAD_RAISED = "reread_raised"
    #: The fresh bound read after the dismissal is not ABSENT.
    STILL_PRESENT = "still_present"


class ClippedEntryResult(ValueModel):
    """One clipped-entry lifecycle's evidence: what was read, closed, and re-read.

    The :class:`ChannelsDismissal` is the producing owner's record untouched. ``owed`` is the
    obligation this lifecycle leaves the operator when it could not observe ABSENT.
    """

    stage: ClippedEntryStage
    surface_before: str = "UNKNOWN"
    enabled_mode: str = "UNKNOWN"
    close: ChannelsDismissal | None = None
    surface_after: str = "UNKNOWN"
    reason: str = ""
    error: str = ""
    owed: tuple[str, ...] = ()

    @property
    def absent(self) -> bool:
        """Whether this lifecycle observed the clipped entry away, on the original binding."""
        return self.stage is ClippedEntryStage.ABSENT


def settle_clipped_entry(
    *,
    target: WindowTarget,
    read: Callable[[], ChannelsRead],
    close: Callable[[], ChannelsDismissal],
    capture: Callable[[], ChannelsRead] | None = None,
    capture_dir: Path | None = None,
    require_enabled: bool = False,
) -> ClippedEntryResult:
    """Read the clipped entry once, dismiss it once, then require a fresh ABSENT read.

    This is the **one** implementation of the parent's clipped-entry lifecycle, shared by
    :func:`run_mpx_once` and the live acceptance probe: one fresh read, the library's own
    :meth:`…dismiss_channels_popup` through ``close``, and a second fresh read of the same
    binding. Nothing is retried and no second path is walked.

    ``require_enabled`` adds the probe's stronger precondition: a **fresh** capture pair taken by
    ``capture`` under ``capture_dir`` must be this run's own live-bracketed, digest-verified,
    agreed pair on the original binding and state ``VISUAL_ENABLED``. A retained pair, a wrong
    handle or a torn frame therefore never licenses the dismissal.
    """
    try:
        clipped = read()
    except Exception as exc:  # noqa: BLE001 - an unreadable fresh read is a stop
        error = f"{type(exc).__name__}: {_reason(exc)}"
        return ClippedEntryResult(
            stage=ClippedEntryStage.READ_RAISED,
            error=error,
            reason=(
                "the clipped entry's mode was stated, but the fresh bound read before its "
                f"dismissal raised: {error} — no Record was pressed"
            ),
            owed=_NO_RECORD_OWED,
        )
    surface_before = clipped.surface.value
    if clipped.surface is not ChannelsSurface.MULTIPLEXER_ON_ENTRY:
        return ClippedEntryResult(
            stage=ClippedEntryStage.NOT_CLIPPED,
            surface_before=surface_before,
            reason=(
                f"the fresh read before the dismissal is {surface_before!r}, not the clipped "
                "one-entry popup: the screen changed, so no dismissal was walked and no Record "
                "was pressed"
            ),
            owed=_NO_RECORD_OWED,
        )

    enabled_mode = "UNKNOWN"
    if require_enabled:
        if capture is None or capture_dir is None:
            return ClippedEntryResult(
                stage=ClippedEntryStage.NOT_ENABLED,
                surface_before=surface_before,
                reason=(
                    "an enabled mode is required from a fresh clipped capture, but no capture "
                    "seam was supplied: no dismissal was walked and no Record was pressed"
                ),
                owed=_NO_RECORD_OWED,
            )
        try:
            fresh = capture()
        except Exception as exc:  # noqa: BLE001 - a failed fresh capture is a stop
            error = f"{type(exc).__name__}: {_reason(exc)}"
            return ClippedEntryResult(
                stage=ClippedEntryStage.NOT_ENABLED,
                surface_before=surface_before,
                error=error,
                reason=(
                    "the clipped entry is visible, but this invocation's fresh capture could "
                    f"not be taken: {error} — no dismissal was walked and no Record was pressed"
                ),
                owed=_NO_RECORD_OWED,
            )
        mark, refusal = _strict_capture(
            getattr(fresh, "capture", None),
            target=target,
            directory=capture_dir,
        )
        if mark is None:
            return ClippedEntryResult(
                stage=ClippedEntryStage.NOT_ENABLED,
                surface_before=surface_before,
                reason=(
                    "the clipped entry is visible, but its fresh capture is not this "
                    f"invocation's licensed pair ({refusal}): no dismissal was walked and no "
                    "Record was pressed"
                ),
                owed=_NO_RECORD_OWED,
            )
        enabled_mode = getattr(mark, "mode", "UNKNOWN")
        if (
            getattr(mark, "surface", "") != mode_marks.MULTIPLEXER_ON_ENTRY
            or enabled_mode != "VISUAL_ENABLED"
        ):
            return ClippedEntryResult(
                stage=ClippedEntryStage.NOT_ENABLED,
                surface_before=surface_before,
                enabled_mode=enabled_mode,
                reason=(
                    "the fresh clipped capture does not state an enabled mode "
                    f"(surface={getattr(mark, 'surface', None)!r}, mode={enabled_mode!r}, "
                    "label="
                    f"{getattr(mark, 'label', None)!r}): no dismissal was walked and no Record "
                    "was pressed"
                ),
                owed=_NO_RECORD_OWED,
            )

    try:
        closed = close()
    except Exception as exc:  # noqa: BLE001 - the close is its own fact
        error = f"{type(exc).__name__}: {_reason(exc)}"
        return ClippedEntryResult(
            stage=ClippedEntryStage.DISMISS_RAISED,
            surface_before=surface_before,
            enabled_mode=enabled_mode,
            error=error,
            reason=(
                "the clipped entry's owned dismissal refused or raised, so the popup was not "
                f"observed away and no Record was pressed: {error}"
            ),
            owed=(
                (
                    "the Channels popup may still be open: settle it by hand; no second path "
                    "is walked and no Disable is pressed"
                ),
            ),
        )
    surface_after = closed.surface_after
    if closed.outcome is not DismissalOutcome.ABSENT:
        return ClippedEntryResult(
            stage=ClippedEntryStage.NOT_ABSENT,
            surface_before=surface_before,
            enabled_mode=enabled_mode,
            close=closed,
            surface_after=surface_after,
            reason=(
                "the clipped entry's dismissal did not observe ABSENT "
                f"(outcome {closed.outcome.value!r}, last surface {surface_after!r}): no "
                "Record was pressed and no second path is walked"
            ),
            owed=(
                (
                    "the popup's absence was not observed: settle the screen by hand; this "
                    "run pressed no Disable and no Record"
                ),
            ),
        )
    try:
        gone = read()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {_reason(exc)}"
        return ClippedEntryResult(
            stage=ClippedEntryStage.REREAD_RAISED,
            surface_before=surface_before,
            enabled_mode=enabled_mode,
            close=closed,
            surface_after=surface_after,
            error=error,
            reason=(
                "the dismissal observed ABSENT, but the fresh bound read immediately before "
                f"Record raised: {error} — no Record was pressed"
            ),
            owed=_NO_RECORD_OWED,
        )
    if gone.surface is not ChannelsSurface.ABSENT:
        return ClippedEntryResult(
            stage=ClippedEntryStage.STILL_PRESENT,
            surface_before=surface_before,
            enabled_mode=enabled_mode,
            close=closed,
            surface_after=gone.surface.value,
            reason=(
                "the fresh bound read immediately before Record is "
                f"{gone.surface.value!r}, not 'absent': the popup is not observed away, so no "
                "Record was pressed"
            ),
            owed=_NO_RECORD_OWED,
        )
    return ClippedEntryResult(
        stage=ClippedEntryStage.ABSENT,
        surface_before=surface_before,
        enabled_mode=enabled_mode,
        close=closed,
        surface_after=gone.surface.value,
    )


def run_mpx_once(
    *,
    name: str,
    store_dir: Path | str,
    capture_root: Path | str,
    record: Path | str,
    declaration: MultiplexedRecordingDeclaration,
    completion_timeout_s: float,
    baseline: str = "off",
    restore_baseline: bool = True,
    settle_s: float = 3.0,
    boundary_seconds: float | None = None,
    actuator=None,
    bound_target: WindowTarget | None = None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    inspect: Callable[..., ChannelInspection] = inspect_channels,
    set_rollover: Callable[..., SetRolloverResult] = acquire_set_rollover,
    enable: Callable[..., EnableMultiplexedResult] = acquire_enable_multiplexed,
    record_block: Callable[..., MultiplexedRecordingResult] = record_multiplexed,
    open_popup: Callable[..., ChannelsOpen] | None = None,
    read_popup: Callable[..., object] | None = None,
    close_popup: Callable[..., object] | None = None,
    stamp: Callable[[], str] = _now_stamp,
    notes: list[str] | None = None,
) -> MpxRunResult:
    """Inspect the disabled screen, roll ON, enable, record once, verify, then settle the baseline.

    Every refusal **before a gesture** raises :class:`AcquisitionError`; every outcome after the
    first rolling press is a returned :class:`MpxRunResult`, because what the instrument still
    owes is the fact the operator needs. ``baseline`` is the caller's own literal, retained
    verbatim and compared with the fresh capture; this composition runs only from ``off``.

    ``bound_target`` is the batch's one binding: handed a record, this run verifies it against
    its own enumeration and never calls ``bind_target``. Without it the standalone rule is
    unchanged — one bind on the single enumerated window, then its verification.
    """
    sink = notes if notes is not None else []
    declaration = validate_declaration(declaration)
    validate_bounds(
        completion_timeout_s=completion_timeout_s,
        settle_s=settle_s,
        boundary_seconds=boundary_seconds,
    )
    # A caller flag is a bool or a refusal: ``"no"`` is truthy, and Pydantic would report it as
    # ``False`` while this run went on to press the restore it was told not to press.
    restore_baseline = strict_flag("restore_baseline", restore_baseline)

    requested_baseline = baseline
    try:
        original = Rolling(baseline)
    except ValueError as exc:
        raise AcquisitionError(
            f"baseline must be the literal 'on' or 'off', got {baseline!r}"
        ) from exc
    if original is not Rolling.OFF:
        raise AcquisitionError(
            f"baseline {requested_baseline!r}: this composition starts from the stopped, "
            "multiplexer-disabled screen with rolling off, so only the literal 'off' is "
            "accepted and nothing was inspected or pressed"
        )

    # --- everything is proved before the first gesture -------------------------------------
    # Paths are claimed here, before the inspection and therefore before any press. A filesystem
    # refusal (a denied ``mkdir``, a read-only capture root) is a **pre-gesture** refusal, so it
    # is raised as the one class the CLI reports as exit 2 — never as an OSError that the CLI's
    # post-inspection handler would report as "raised after its baseline inspection".
    try:
        target_dir = store_preflight(name, store_dir)
        capture_base = Path(capture_root)
        if not capture_base.is_dir():
            raise AcquisitionError(
                f"the capture root {capture_base} does not exist: every child capture directory "
                "is claimed under it, so nothing was inspected or pressed"
            )
        # One exclusive, empty run root per invocation: an earlier run's frames are never reused.
        parent_record = trial_record_file(record, name=MPX_RUN_RECORD_NAME)
        if parent_record.exists():
            raise AcquisitionError(
                f"a record already exists at {parent_record}: refusing to overwrite another "
                "run's obligation (move it or name a different --record), so nothing was "
                "inspected or pressed"
            )
        # The child records are named **after** the run root is claimed, and inside it: each one
        # is a file of this run's own exclusive directory, so two runs sharing one parent
        # directory can never claim the same child record, and the first run's obligations are
        # left byte-identical.
        capture = _claim_capture_run(capture_base)
        record_dir = capture / "records"
        record_dir.mkdir(parents=True, exist_ok=True)
        child_records = {
            key: record_dir / f"{key}-trial.json"
            for key in ("rollover", "enable", "restore")
        }
        # Every capture purpose gets its own directory under this run's root, so two owners'
        # ``capture-NNN`` names can never collide inside one run either.
        child_dirs = {
            "baseline": capture / "inspection-baseline",
            "rollover": capture / "rollover",
            "enable": capture / "enable",
            "clipped": capture / "clipped-entry",
            "post_save": capture / "inspection-post-save",
            "restore": capture / "restore",
        }
        for directory in child_dirs.values():
            directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AcquisitionError(
            f"the run's paths could not be claimed ({type(exc).__name__}: {_reason(exc)}): "
            "nothing was inspected or pressed, and no press of this run was made"
        ) from exc

    live = (
        actuator
        if actuator is not None
        else Win32Actuator(note_sink=sink.append, allow_real_input=True)
    )
    enumerate_fn: Callable[[], Sequence[int]] = (
        enumerate_windows
        if enumerate_windows is not None
        else (lambda: tuple(visible_main_windows(class_name)))
    )
    read_fn = read_popup if read_popup is not None else read_channels
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

    windows = tuple(enumerate_fn())
    bound = bind_once(
        actuator=live,
        enumerate_windows=lambda: windows,
        class_name=class_name,
        bound_target=bound_target,
    )

    fields: dict[str, object] = {
        "name": name,
        "directory": target_dir,
        "capture_root": capture,
        "declaration": declaration,
        "baseline": requested_baseline,
        "restore_baseline": restore_baseline,
        "bound_target": bound,
        "parent_record": parent_record,
    }
    sink.append(
        "mpx-run binds the instrument once and hands that verified record to every child; no "
        "child may bind a second time"
        if bound_target is None
        else "mpx-run verifies the caller's bound record without binding a second time and "
        "hands that record to every child"
    )

    def stop(
        stage: MpxRunStage,
        *,
        reason: str,
        owed: tuple[str, ...],
        error: str = "",
        **extra: object,
    ) -> MpxRunResult:
        """One terminal report, with the parent record rewritten once (and never claimed as done)."""
        merged: dict[str, object] = {**fields, **extra}
        close = merged.get("popup_close")
        payload = {
            **base_payload(),
            "phase": "after",
            "completed_at": stamp(),
            "scope": "final: what this run established, and what it still owes",
            "stage": stage.value,
            "reason": reason,
            "error": error,
            "owed": list(owed),
            # Small facts and references only: each child's full report stays on the result.
            "child_stages": {
                key: _stage_value(merged.get(key))
                for key in (
                    "inspection",
                    "rollover",
                    "enable",
                    "record",
                    "post_save",
                    "restore",
                )
            },
            "post_surface": str(merged.get("post_surface", "UNKNOWN")),
            "post_mode": str(merged.get("post_mode", "UNKNOWN")),
            "post_mode_source": str(merged.get("post_mode_source", "")),
            "post_save_mode": str(merged.get("post_save_mode", "UNKNOWN")),
            "post_save_mode_source": str(merged.get("post_save_mode_source", "")),
            "popup_close": (
                None
                if close is None
                else {
                    "outcome": close.outcome.value,
                    "surface_before": close.surface_before,
                    "surface_after": close.surface_after,
                    "point": list(close.point or ()),
                    "reads": close.reads,
                    "steps": close.steps,
                }
            ),
            "stored_path": (
                None
                if merged.get("stored_path") is None
                else str(merged["stored_path"])
            ),
            "artifact_consistent": bool(merged.get("artifact_consistent", False)),
            "rolling_before": str(merged.get("rolling_before", "UNKNOWN")),
            "rolling_before_source": str(merged.get("rolling_before_source", "")),
            "rolling_at_enable": str(merged.get("rolling_at_enable", "UNKNOWN")),
            "rolling_at_enable_source": str(merged.get("rolling_at_enable_source", "")),
            "rolling_after": str(merged.get("rolling_after", "UNKNOWN")),
            "rolling_after_source": str(merged.get("rolling_after_source", "")),
            "baseline_restored": bool(merged.get("baseline_restored", False)),
            "baseline_restored_source": str(merged.get("baseline_restored_source", "")),
        }
        record_error = update_trial_record(parent_record, payload)
        return MpxRunResult(
            stage=MpxRunStage.RECORD_UNWRITTEN
            if record_error and stage is MpxRunStage.COMPLETE
            else stage,
            parent_record_phase="unwritten" if record_error else "final",
            parent_record_error=record_error,
            reason=reason,
            error=error,
            notes=tuple(sink),
            owed=owed
            + (
                ()
                if not record_error
                else (
                    f"the parent record {parent_record} was not rewritten and still reads "
                    "pending: " + record_error,
                )
            ),
            **merged,
        )

    def base_payload() -> dict:
        """Everything this run knows before its first press — paths, declaration, bounds."""
        return {
            "command": "mpx-run",
            "name": name,
            "store_dir": str(target_dir),
            "capture_root": str(capture),
            "declaration": declaration.model_dump(),
            "baseline": requested_baseline,
            "restore_baseline": restore_baseline,
            "bound_target": bound.model_dump(),
            "parent_record": str(parent_record),
            "child_records": {key: str(path) for key, path in child_records.items()},
            "child_capture_dirs": {key: str(path) for key, path in child_dirs.items()},
            "completion_timeout_s": completion_timeout_s,
            "settle_s": settle_s,
            "boundary_seconds": boundary_seconds,
        }

    def pending_payload() -> dict:
        return {
            **base_payload(),
            "phase": "pending",
            "written_at": stamp(),
            "scope": PENDING_SCOPE,
            "actions": "none are stated as taken by this pending record; a press may follow",
        }

    # --- (1) the disabled screen, read and closed, before anything is written -------------
    try:
        before = inspect(
            actuator=live,
            target=bound,
            capture_dir=str(child_dirs["baseline"]),
            allow_real_input=True,
            adopt_open=False,
            close_adopted=False,
            settle_s=settle_s,
            read=lambda **kwargs: read_fn(live, target=bound, **kwargs),
        )
    except Exception as exc:  # noqa: BLE001 - an inspection failure is a stated stop
        return MpxRunResult(
            stage=MpxRunStage.INSPECTION_REFUSED,
            reason=(
                "the baseline inspection raised, so no popup state is known and nothing was "
                f"pressed: {type(exc).__name__}: {_reason(exc)}"
            ),
            error=f"{type(exc).__name__}: {_reason(exc)}",
            owed=_NO_RECORD_OWED + _popup_clause(None),
            notes=tuple(sink),
            **fields,
        )
    if before.outcome is not InspectionOutcome.CLOSED:
        popup_clause = _popup_clause(before)
        return MpxRunResult(
            stage=MpxRunStage.INSPECTION_REFUSED,
            inspection=before,
            reason=(
                "the baseline inspection did not close a readable popup "
                f"({before.outcome.value}"
                + (f": {before.refused}" if before.refused else "")
                + "): nothing was rolled, enabled or recorded"
            ),
            owed=(
                (
                    (
                        "an operator-opened Channels popup is never adopted or taken over "
                        "by this composition: close it by hand and re-run with the screen "
                        "stopped"
                    ),
                )
                if before.refused_stage in ("adopt", "surface")
                else ()
            )
            + popup_clause
            + _NO_RECORD_OWED,
            notes=tuple(sink),
            **fields,
        )

    # The baseline decisions rest on this run's own licensed pair, exactly like the post-save
    # one: a retained pair, a wrong handle or a torn frame states neither the declared mode nor
    # whether rolling is already on, so it is refused before the parent record is claimed.
    baseline_mark, baseline_refusal = _strict_capture(
        None if before.read is None else before.read.capture,
        target=bound,
        directory=child_dirs["baseline"],
    )
    if baseline_mark is None:
        return MpxRunResult(
            stage=MpxRunStage.INSPECTION_REFUSED,
            inspection=before,
            reason=(
                "the baseline inspection closed the popup, but its capture is not this run's "
                f"own licensed pair ({baseline_refusal}): the declared mode and the rollover "
                "state would rest on evidence this run does not own, so nothing was pressed"
            ),
            owed=(
                (
                    "re-inspect the stopped screen with this run's own live capture before "
                    + "re-running; this run pressed nothing"
                ),
            )
            + _NO_RECORD_OWED,
            notes=tuple(sink),
            **fields,
        )
    mode_before = baseline_mark.mode
    # ``original`` is checked to be ``Rolling.OFF`` above, so this composition starts disabled.
    declared_mode = "VISUAL_DISABLED"
    if mode_before != declared_mode:
        return MpxRunResult(
            stage=MpxRunStage.BASELINE_DISAGREED,
            inspection=before,
            rolling_before=_rolling_literal(baseline_mark),
            reason=(
                f"the operator declared the multiplexer baseline {requested_baseline!r} but the "
                f"fresh baseline capture reads mode {mode_before}: the declaration is the input, "
                "and a disagreement is refused before any press"
            ),
            owed=(
                (
                    f"settle the multiplexer to {requested_baseline!r} and re-run: nothing "
                    "was pressed"
                ),
            )
            + _NO_RECORD_OWED,
            notes=tuple(sink),
            **fields,
        )
    rolling_before = _rolling_literal(baseline_mark)
    if rolling_before == "UNKNOWN":
        return MpxRunResult(
            stage=MpxRunStage.INSPECTION_REFUSED,
            inspection=before,
            reason=(
                "the baseline capture does not state the rollover mark, so whether rolling ON is "
                "needed at all is unknown: nothing was pressed"
            ),
            owed=(
                (
                    "read the rollover state from a fresh capture before re-running; this "
                    "run pressed nothing"
                ),
            )
            + _NO_RECORD_OWED,
            notes=tuple(sink),
            **fields,
        )

    fields["inspection"] = before

    # --- (2) the durable parent record, exclusively claimed, before the first rolling child
    claim_trial_record(parent_record, pending_payload())

    # The rolling facts live in the run context as soon as their owner states them, so every
    # later report states the same value with the same source instead of re-stating (or
    # upgrading) it at each stop. ``baseline_capture`` is honestly a pre-Enable observation.
    fields.update(
        rolling_before=rolling_before,
        rolling_before_source="baseline_capture",
        rolling_at_enable=rolling_before,
        rolling_at_enable_source="baseline_capture",
    )

    # --- (3) rolling ON, only when the fresh reading says it is not already on -------------
    rollover: SetRolloverResult | None = None
    if rolling_before == "OFF_PROVEN":
        try:
            rollover = set_rollover(
                requested="on",
                expect="off",
                baseline="off",
                capture_dir=child_dirs["rollover"],
                trial_record=child_records["rollover"],
                actuator=live,
                enumerate_windows=enumerate_fn,
                class_name=class_name,
                settle_s=settle_s,
                max_boundary_seconds=boundary_seconds,
                bound_target=bound,
                notes=sink,
            )
        except Exception as exc:  # noqa: BLE001 - a raised child is a stated stop
            return stop(
                MpxRunStage.ROLLOVER_FAILED,
                reason=(
                    "the rollover child refused or raised, so rolling ON is not established "
                    f"and nothing was enabled or recorded: {type(exc).__name__}: "
                    f"{_reason(exc)}"
                ),
                error=f"{type(exc).__name__}: {_reason(exc)}",
                owed=_NO_RECORD_OWED,
            )
        fields["rollover"] = rollover
        if rollover.post_rolling != "ON_PROVEN" or not _settled(rollover):
            return stop(
                MpxRunStage.ROLLOVER_FAILED,
                reason=(
                    "the rollover child did not prove rolling ON from its own fresh post "
                    f"read (post rolling {rollover.post_rolling}, closure "
                    f"{None if rollover.popup_closure is None else rollover.popup_closure.value})"
                    ": nothing was enabled or recorded"
                ),
                owed=_NO_RECORD_OWED,
            )
        fields.update(
            rolling_at_enable=rollover.post_rolling,
            rolling_at_enable_source="rollover_child_post_read",
        )

    # --- (4) one managed open, on the original target, then the owned Enable press --------
    try:
        pre = read_fn(live, target=bound)
    except Exception as exc:  # noqa: BLE001
        return stop(
            MpxRunStage.ENABLE_FAILED,
            reason=(
                "the screen could not be read before opening Channels, so nothing was pressed: "
                f"{type(exc).__name__}: {_reason(exc)}"
            ),
            error=f"{type(exc).__name__}: {_reason(exc)}",
            owed=_NO_RECORD_OWED,
        )
    if pre.surface in READABLE_SURFACES and pre.readable:
        return stop(
            MpxRunStage.POPUP_LEFT_OPEN,
            reason=(
                "a readable Channels popup is already open and this composition never adopts or "
                "takes over one it did not open: nothing was enabled or recorded"
            ),
            owed=(
                "close the operator's popup by hand and re-run: this run took no gesture on it",
            )
            + _NO_RECORD_OWED,
        )
    if pre.surface is not ChannelsSurface.ABSENT:
        return stop(
            MpxRunStage.POPUP_LEFT_OPEN,
            reason=(
                f"the pre-open reading is {pre.surface.value!r}, neither 'absent' nor a readable "
                "Channels popup: nothing was hovered, enabled or recorded"
            ),
            owed=(
                "identify and clear the surface on screen, then re-run: nothing was pressed",
            )
            + _NO_RECORD_OWED,
        )
    try:
        opened = open_fn(
            target=bound,
            read=lambda **kwargs: read_fn(live, target=bound, **kwargs),
            timeout_s=settle_s,
            adopt_open=False,
        )
    except Exception as exc:  # noqa: BLE001
        return stop(
            MpxRunStage.ENABLE_FAILED,
            reason=(
                "the managed Channels open refused or raised, so nothing was enabled or "
                f"recorded: {type(exc).__name__}: {_reason(exc)}"
            ),
            error=f"{type(exc).__name__}: {_reason(exc)}",
            owed=_NO_RECORD_OWED,
        )
    if opened.outcome is not PopupOutcome.OPEN:
        return stop(
            MpxRunStage.ENABLE_FAILED,
            reason=(
                "the measured Channels stepped entry produced no readable popup, so the Enable press was "
                f"not made: {opened.clause or opened.surface}"
            ),
            owed=_NO_RECORD_OWED,
        )

    try:
        enabled = enable(
            capture_dir=child_dirs["enable"],
            trial_record=child_records["enable"],
            actuator=live,
            enumerate_windows=enumerate_fn,
            class_name=class_name,
            max_boundary_seconds=boundary_seconds,
            bound_target=bound,
            stamp=stamp,
            notes=sink,
        )
    except Exception as exc:  # noqa: BLE001 - enabled's pre-press refusal
        # The child raises only before it presses, so the popup this run opened is untouched
        # and is closed through the library's own owned dismissal — once, never retried.
        closure = ""
        try:
            closed = close_fn(
                target=bound,
                read=lambda **kwargs: read_fn(live, target=bound, **kwargs),
                timeout_s=settle_s,
            )
            closure = f"; the popup this run opened was closed ({closed.outcome.value})"
        except Exception as close_exc:  # noqa: BLE001 - the close is its own fact
            closure = (
                "; the popup this run opened could not be closed ("
                f"{type(close_exc).__name__}: {_reason(close_exc)}) and is left for the operator"
            )
        return stop(
            MpxRunStage.ENABLE_FAILED,
            reason=(
                "the Enable child refused before pressing, so no mode is established and nothing "
                f"was recorded: {type(exc).__name__}: {_reason(exc)}{closure}"
            ),
            error=f"{type(exc).__name__}: {_reason(exc)}",
            owed=_NO_RECORD_OWED,
        )
    fields["enable"] = enabled

    if enabled.bound_target.hwnd != bound.hwnd:
        return stop(
            MpxRunStage.ENABLE_FAILED,
            reason=(
                "the Enable child's report is bound to "
                f"{enabled.bound_target.hwnd} where this run bound {bound.hwnd}: identity "
                "drift, so its mode fact is not this run's and no Record was pressed"
            ),
            owed=_NO_RECORD_OWED,
        )

    # The only production-reachable enabled pair: the clipped one-entry popup, whose own fresh
    # capture states VISUAL_ENABLED. An ``ABSENT`` post surface cannot state that mode, and a
    # clipped surface without the positive mode states nothing either.
    post_surface = enabled.post_surface
    post_mode = enabled.post_mode
    fields.update(
        post_surface=post_surface,
        post_mode=post_mode,
        post_mode_source="enable_child_post_capture",
    )
    # A later observation replaces the earlier one only when it states one: an Enable post read
    # of ``UNKNOWN`` never turns into "rolling is ON now".
    if enabled.post_rolling in ("ON_PROVEN", "OFF_PROVEN"):
        fields.update(
            rolling_at_enable=enabled.post_rolling,
            rolling_at_enable_source="enable_child_post_capture",
        )
    elif enabled.post_capture_kind:
        sink.append(
            "the Enable child's post capture states no rollover mark, so rolling is known only "
            "from the earlier capture and no current state is inferred"
        )
    if post_surface == ChannelsSurface.ABSENT.value:
        return stop(
            MpxRunStage.ENABLE_FAILED,
            reason=(
                "the post-Enable read is 'absent' and the Enable child states a positive mode "
                "only from the clipped 'multiplexer_on_entry' pair, so an absent surface "
                "establishes no enabled mode: no Record was pressed, and 'absent' is never "
                "turned into 'enabled'"
            ),
            owed=(
                (
                    "reopen Channels and read the mode from a fresh capture before recording; "
                    "this run pressed Record zero times"
                ),
            )
            + _NO_RECORD_OWED,
        )
    if post_surface != ChannelsSurface.MULTIPLEXER_ON_ENTRY.value:
        return stop(
            MpxRunStage.POPUP_LEFT_OPEN,
            reason=(
                f"the post-Enable read is {post_surface!r}, neither the clipped one-entry "
                "popup nor 'absent': this run does not guess at another surface, so no Record "
                "was pressed and nothing was cleaned up"
            ),
            owed=(
                (
                    "the screen must be identified and settled by the operator; this run "
                    "presses no Disable, Record or second gesture"
                ),
            )
            + _NO_RECORD_OWED,
        )
    if post_mode != "VISUAL_ENABLED":
        return stop(
            MpxRunStage.ENABLE_FAILED,
            reason=(
                "the post-Enable read is the clipped one-entry popup, but its own fresh pair "
                f"does not state an enabled mode ({post_mode}), and a 'ready' strip is the "
                "same row in both modes: no Record was pressed"
            ),
            owed=(
                (
                    "establish the enabled mode from a fresh clipped capture before recording; "
                    "this run pressed Record zero times"
                ),
            )
            + _NO_RECORD_OWED,
        )

    # --- the clipped entry: the parent's own fresh pair licenses its one dismissal ---------
    # The child's literals above are what *it* read; this composition never dismisses a popup on
    # another owner's word. ``require_enabled`` makes the parent take its own live-bracketed,
    # digest-verified pair under this run's own ``clipped-entry`` directory (no other owner
    # writes there, so two owners' ``capture-NNN`` names cannot collide) and holds it to the
    # original binding and the same popup panel.
    def read_clipped() -> ChannelsRead:
        return read_fn(live, target=bound, capture_dir=str(child_dirs["clipped"]))

    held = settle_clipped_entry(
        target=bound,
        read=lambda: read_fn(live, target=bound),
        close=lambda: close_fn(
            target=bound,
            read=lambda **kwargs: read_fn(live, target=bound, **kwargs),
            timeout_s=settle_s,
        ),
        capture=read_clipped,
        capture_dir=child_dirs["clipped"],
        require_enabled=True,
    )
    if not held.absent:
        return stop(
            MpxRunStage.POPUP_LEFT_OPEN,
            reason=held.reason,
            error=held.error,
            owed=held.owed + _NO_RECORD_OWED,
        )
    fields["popup_close"] = held.close
    # The mode this run proceeds on is now the parent's own fresh pair, not a child's literal.
    fields.update(
        post_mode=held.enabled_mode, post_mode_source="parent_clipped_capture"
    )
    # Until a later capture states otherwise, this is the latest *observed* rolling fact — with
    # the owner that stated it. Nothing here pretends it was re-read at the Record moment.
    fields.update(
        rolling_after=fields["rolling_at_enable"],
        rolling_after_source=fields["rolling_at_enable_source"],
    )
    sink.append(
        "the clipped one-entry popup was dismissed through the existing stepped owner and its "
        "absence was re-read on the original binding; no second path is walked and the next "
        "gesture is the one Record"
    )

    # --- (5) one Record, the application's own completion, one store ----------------------
    try:
        recorded = record_block(
            name=name,
            directory=target_dir,
            declaration=declaration,
            completion_timeout_s=completion_timeout_s,
            actuator=live,
            enumerate_windows=enumerate_fn,
            class_name=class_name,
            bound_target=bound,
            notes=sink,
        )
    except Exception as exc:  # noqa: BLE001 - a refused Record is a report
        return stop(
            MpxRunStage.RECORD_FAILED,
            reason=(
                "the record child refused or raised before its press; what the instrument holds "
                f"is unknown and nothing was retried: {type(exc).__name__}: {_reason(exc)}"
            ),
            error=f"{type(exc).__name__}: {_reason(exc)}",
            owed=_NO_RECORD_OWED,
        )
    fields["record"] = recorded
    if recorded.stage is not MpxStage.STORED:
        return stop(
            MpxRunStage.RECORD_FAILED,
            reason=(
                f"the record child returned {recorded.stage.value}: {recorded.reason} — nothing "
                "further is pressed, and no Stop, Clear, store retry or second Record is made"
            ),
            owed=recorded.owed
            + (
                (
                    "the parent record stays pending until the operator states the "
                    "instrument's state; this run performs no cleanup"
                ),
            ),
        )
    if not recorded.artifact_consistent:
        return stop(
            MpxRunStage.ARTIFACT_INCONSISTENT,
            reason=(
                "the block was stored once and its artifact verification is not consistent "
                f"({recorded.artifact_verification_error or 'verdict not consistent'}); the file "
                f"at {recorded.stored_path} is preserved and is neither re-recorded nor re-stored"
            ),
            owed=recorded.owed,
            stored_path=recorded.stored_path,
        )

    # --- (6) the post-save inspection, and the baseline the panel states ------------------
    try:
        after = inspect(
            actuator=live,
            target=bound,
            capture_dir=str(child_dirs["post_save"]),
            allow_real_input=True,
            adopt_open=False,
            close_adopted=False,
            settle_s=settle_s,
            read=lambda **kwargs: read_fn(live, target=bound, **kwargs),
        )
    except Exception as exc:  # noqa: BLE001
        return stop(
            MpxRunStage.POST_SAVE_UNKNOWN,
            reason=(
                "the block is stored and consistent, but the post-save inspection raised, so the "
                f"final state and the baseline obligation are unknown: {type(exc).__name__}: "
                f"{_reason(exc)}"
            ),
            error=f"{type(exc).__name__}: {_reason(exc)}",
            owed=(
                (
                    "read the rollover state from a fresh capture and settle the baseline by "
                    "hand; the stored artifact is preserved"
                ),
            ),
            stored_path=recorded.stored_path,
            artifact_consistent=True,
        )
    fields["post_save"] = after
    strict_mark, strict_reason = _strict_capture(
        None if after.read is None else after.read.capture,
        target=bound,
        directory=child_dirs["post_save"],
    )
    rolling_after = (
        _rolling_literal(strict_mark)
        if strict_mark is not None
        else _inspection_rolling(after)
    )
    mode_after = "UNKNOWN" if strict_mark is None else strict_mark.mode
    fields.update(
        rolling_after=rolling_after,
        rolling_after_source="post_save_capture",
        post_save_mode=mode_after,
        post_save_mode_source="post_save_capture",
    )
    if after.outcome is not InspectionOutcome.CLOSED or strict_reason:
        return stop(
            MpxRunStage.POST_SAVE_UNKNOWN,
            reason=(
                "the block is stored and consistent, but the post-save inspection is "
                f"{after.outcome.value} and its capture is not this run's licensed pair "
                f"({strict_reason or 'no reason reported'}): the final state is unknown and "
                "nothing further is pressed"
            ),
            owed=(
                (
                    "close/read the Channels popup and settle the baseline by hand; the "
                    "stored artifact is preserved"
                ),
            )
            + _popup_clause(after),
            stored_path=recorded.stored_path,
            artifact_consistent=True,
        )
    if rolling_after == "UNKNOWN":
        return stop(
            MpxRunStage.POST_SAVE_UNKNOWN,
            reason=(
                "the block is stored and consistent, but the post-save capture does not state "
                "the rollover mark: whether rolling ON is still in force is unknown, so no "
                "restore child is called and no rolling state is claimed"
            ),
            owed=(
                (
                    "read the rollover state from a fresh capture and settle the declared "
                    "baseline by hand; the stored artifact is preserved and the rollover "
                    "toggle was not pressed again"
                ),
            ),
            stored_path=recorded.stored_path,
            artifact_consistent=True,
        )

    resolved: list[str] = [
        (
            "the Enable child's 'read the mode back from a freshly reopened Channels popup' "
            f"obligation is resolved by this run's fresh post-save capture, which reads "
            f"{mode_after}"
        )
    ]
    fields["resolved_child_obligations"] = tuple(resolved)

    if mode_after != "VISUAL_DISABLED":
        # The multiplexer is still enabled: this composition never presses Disable, so the
        # baseline is owed to the operator rather than restored by a guessed gesture.
        return stop(
            MpxRunStage.RESTORATION_OWED,
            reason=(
                "the block is stored and consistent, but the post-save capture reads the "
                f"multiplexer {mode_after}: this composition presses no Disable, so the "
                "declared baseline is owed rather than restored"
            ),
            owed=(
                (
                    "the multiplexer is still enabled: returning it to the declared baseline "
                    "off is a separate operator gesture; this run presses no Disable and "
                    f"records no second block (stored artifact {recorded.stored_path})"
                ),
            ),
            stored_path=recorded.stored_path,
            artifact_consistent=True,
        )

    if rolling_after == "OFF_PROVEN":
        # The post-save capture *is* the fresh proof: the baseline is restored by the run itself
        # because rolling is already off, and the source names that capture.
        fields.update(
            stored_path=recorded.stored_path,
            artifact_consistent=True,
            baseline_restored=True,
            baseline_restored_source="post_save_capture",
        )
        return stop(
            MpxRunStage.COMPLETE,
            reason="",
            owed=(),
            stored_path=recorded.stored_path,
        )

    if not restore_baseline:
        return stop(
            MpxRunStage.RESTORATION_OWED,
            reason=(
                "the block is stored and consistent; the post-save capture reads rolling ON and "
                "--no-restore-baseline was given, so the baseline is owed rather than restored"
            ),
            owed=(
                (
                    f"rolling is {rolling_after} where the declared baseline is "
                    f"{requested_baseline!r}: restoring the rollover toggle is a separate "
                    "decision this run was told not to take"
                ),
            ),
            stored_path=recorded.stored_path,
            artifact_consistent=True,
        )

    # --- (7) the baseline restore, through the existing child, proved by its fresh read ---
    restored: SetRolloverResult | None = None
    try:
        restored = set_rollover(
            requested="off",
            expect="on",
            baseline="off",
            capture_dir=child_dirs["restore"],
            trial_record=child_records["restore"],
            actuator=live,
            enumerate_windows=enumerate_fn,
            class_name=class_name,
            settle_s=settle_s,
            max_boundary_seconds=boundary_seconds,
            bound_target=bound,
            notes=sink,
        )
    except Exception as exc:  # noqa: BLE001
        return stop(
            MpxRunStage.RESTORATION_FAILED,
            reason=(
                "the block is stored and consistent, but the baseline restore refused or raised: "
                f"rolling stays ON: {type(exc).__name__}: {_reason(exc)}"
            ),
            error=f"{type(exc).__name__}: {_reason(exc)}",
            owed=(
                f"restore rolling {requested_baseline!r} by hand; the stored artifact is preserved",
            ),
            stored_path=recorded.stored_path,
            restore=None,
            artifact_consistent=True,
        )
    fields["restore"] = restored
    # The restore child's own fresh post read is a later observation than the post-save capture,
    # so it becomes the stated after-fact with its own source — whether or not it proved OFF.
    fields.update(
        rolling_after=restored.post_rolling,
        rolling_after_source="restore_child_post_read",
    )
    if restored.post_rolling != "OFF_PROVEN" or not _settled(restored):
        return stop(
            MpxRunStage.RESTORATION_FAILED,
            reason=(
                "the baseline restore did not prove rolling OFF from its own fresh post read "
                f"(post rolling {restored.post_rolling})"
            ),
            owed=(
                f"restore rolling {requested_baseline!r} by hand and prove it with a fresh "
                + "capture; the stored artifact is preserved",
            ),
            stored_path=recorded.stored_path,
            artifact_consistent=True,
        )
    # No third inspection is taken: the final mode is the pre-restore strict capture (the
    # rollover press cannot change the multiplexer mode and this run presses no Disable), and
    # the restore's own fresh post read proves rolling OFF. Both sources are stated so a reader
    # never mistakes the mode for a post-restore observation.
    fields.update(
        stored_path=recorded.stored_path,
        artifact_consistent=True,
        baseline_restored=True,
        baseline_restored_source="restore_child_post_read",
        post_save_mode_source="pre_restore_capture",
    )
    return stop(
        MpxRunStage.COMPLETE,
        reason="",
        owed=(),
        stored_path=recorded.stored_path,
    )
