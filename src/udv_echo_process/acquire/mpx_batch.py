"""One finite batch of bounded multiplexed runs: ``run_mpx_once`` per item, nothing copied.

**This module is a composition, not a second acquisition path.** Every item is one
:func:`…mpx_run.run_mpx_once` call with the caller's shared declaration: the same inspect,
rollover, enable, record and post-save owners, the same pending record, the same one binding.
No gesture, no ledger, no resume and no retry lives here.

**One original target for the whole batch.** The batch enumerates the window once, binds it
once through :func:`…mpx_run.bind_once` and hands that record to every run, which may only
verify it. A changed handle is refused before the next run's setup, and each run must report
the *same* full :class:`WindowTarget` — a batch never re-binds between runs.

**Everything is proved before the first claim, press or open.** All names are checked with the
store owner's own rules (a safe stem, the directory lists, no entry already carried that stem
case-folded), every name is distinct case-folded, and every record path is judged as an
identity: a caller component Windows would silently rewrite (trailing dot/space, reserved device
stem, forbidden character) is refused with the exact input and never repaired; records must be
distinct by the parent directory's volume/file identity plus the case-folded file name (so
hard links, short names and ``..`` aliases cannot hide a shared record); no record may lie under
the capture root (it would collide with the root or a ``mpx-run-NNN`` claim); and a record placed
directly in the artifact store is refused when its exact stem is a batch store name (the store
attributes new entries by stem), while a distinct sidecar outside the store is the documented
contract. The capture root exists, is a directory and its remaining ``mpx-run-NNN`` slots (the
owner's own :data:`…mpx_run.CAPTURE_RUN_LIMIT`, read with a real ``stat`` so an unreadable root
is unknown rather than empty) are at least the item count. The shared declaration, the ``off``
baseline, the restore flag and every finite bound are validated in the same step. Nothing is
inspected, opened or claimed until all of it passes; there is **no arbitrary item cap** — the
finite bound is the explicit item sequence and the capture owner's own limit.

**Before each item, and after the last, there is a strict gate, never a stage-only success.**
A completed run is certified against facts re-read now: a final durable parent record read back
through the owner's :class:`…mpx_run.MpxFinalRecord` contract (phase ``after``, command,
declaration, original binding, capture root, stored path, artifact flag and baseline fields
compared field by field with the in-memory result), no owed clause, a restored ``off`` baseline,
``VISUAL_DISABLED`` from a fresh post-save capture (or the pre-restore capture the restore
child's own read bounds), rolling ``OFF_PROVEN``, a closed popup, the batch's exact bound target
on the run and on its rollover/enable/record/restore children, and a stored path that is a file
whose **freshly re-read** artifact still verifies consistent against the same declaration with
the digest the run reported. The same gate runs after the **final** item, so a batch is
``COMPLETE`` only when its last boundary was proved too. If any clause fails, no next item is
inspected or claimed.

**Interruption is an explicit result, never a retry.** A ``KeyboardInterrupt`` (a cancelled run)
stops the loop with the completed runs' facts preserved: raised inside a run it cannot promise
that run's cleanup or a durable partial, so the caller's parent-record path for that item is
reported as possibly pending/UNKNOWN and no second ``Record`` is ever pressed; raised between
runs (during any gate) no next item is started and no record is claimed. The batch returns
``INTERRUPTED`` rather than re-raising, because the earlier summaries are the operator's
evidence. ``SystemExit`` is not cancellation and is allowed to propagate. An ordinary exception
is a stop for that item with the earlier runs' facts kept — never a claim that nothing ran.

**Status.** Implemented, verified offline, and exercised once live: a supervised two-item batch
(2026-10-22) completed with both items stored, verified and gated. What that sitting did not
establish — and what this module's docs must keep saying — is unattended or back-to-back cycling,
batches beyond two items, live cancellation or live failure recovery, and the preconditions
`docs/dop3000/udop-automation.md` §12.13 named before any batch (disable during active acquisition,
popup/gesture timing, relay settling between blocks). This module composes the real GUI-driving
owners (it constructs :class:`…driver.Win32Actuator` when no actuator is injected); it does not add
an arm flag or a second command, and running the public ``acquire mpx-run --also`` path is the
operator's decision.

Nothing here runs at import time.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path

from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.channels_inspect import InspectionOutcome
from udv_echo_process.acquire.channels_repeat import trial_record_file
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.mpx_artifact import (
    MpxArtifactReport,
    MpxVerdict,
    verify_mpx_artifact,
)
from udv_echo_process.acquire.mpx_run import (
    CAPTURE_RUN_LIMIT,
    FINAL_RECORD_PHASE,
    MPX_RUN_RECORD_NAME,
    MpxFinalRecord,
    MpxRunResult,
    MpxRunStage,
    bind_once,
    capture_run_slots,
    read_parent_record,
    run_mpx_once,
    strict_flag,
    validate_bounds,
    validate_declaration,
)
from udv_echo_process.acquire.record_multiplexed import MultiplexedRecordingDeclaration
from udv_echo_process.acquire.set_rollover import Rolling
from udv_echo_process.acquire.store_completed import (
    RESERVED_FILE_STEMS,
    CompletedBlockDeclaration,
    store_directory,
    store_preflight,
)
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "MpxBatchItem",
    "MpxBatchResult",
    "MpxBatchRun",
    "MpxBatchStage",
    "parse_also",
    "run_mpx_batch",
]

#: Characters Windows refuses in a single path component (a drive separator is not a component).
_WINDOWS_FORBIDDEN = '\\/:*?"<>|'

#: Reserved device stems are the store owner's list; a record path is judged by the same names.
_RESERVED = RESERVED_FILE_STEMS

#: The capture-owner sources that may state a completed run's final disabled mode: the
#: post-save capture itself, or the pre-restore capture an accepted restore child's own fresh
#: read bounds. No other source is a final mode fact.
_POST_SAVE_MODE_SOURCES = ("post_save_capture", "pre_restore_capture")


class MpxBatchStage(str, Enum):
    """What the batch established — an outcome, never an attempt count."""

    #: Every item completed and passed the gate that stood before the next.
    COMPLETE = "complete"
    #: A run did not complete, or the gate refused the next item: later items did not start.
    STOPPED = "stopped"
    #: A KeyboardInterrupt (cancelled run) stopped this process: its outcome is UNKNOWN.
    INTERRUPTED = "interrupted"


class MpxBatchItem(ValueModel):
    """One explicitly ordered ``(name, record)`` pair, as the caller wrote it."""

    name: str
    #: The parent record path for this item (a file, or a directory resolved to
    #: ``mpx-run-record.json`` inside it by the owner at preflight).
    record: Path


class MpxBatchRun(ValueModel):
    """One item's compact evidence: references and key facts, never the nested full reports.

    The run's own parent record and its child records are on disk; this carries the small
    facts a reader needs to audit the boundary without a second copy of every stage report.
    """

    name: str
    record: Path
    capture_root: Path | None = None
    stage: MpxRunStage
    parent_record_phase: str = ""
    stored_path: Path | None = None
    #: The verdict and digest that licensed the next item: ``gate`` for the fresh re-read,
    #: ``run_report`` for the last item (no next item stands on it).
    artifact_verdict: str = ""
    artifact_sha256: str = ""
    artifact_source: str = ""
    post_save_mode: str = "UNKNOWN"
    #: The surface the Enable child's own post read stated (the clipped entry, or ``absent``).
    post_surface: str = "UNKNOWN"
    rolling_after: str = "UNKNOWN"
    post_saved_closed: bool = False
    baseline_restored: bool = False
    owed: tuple[str, ...] = ()
    reason: str = ""

    @property
    def complete(self) -> bool:
        return self.stage is MpxRunStage.COMPLETE

    def summary(self) -> str:
        head = f"{self.name}: {self.stage.value} on {self.record}"
        if self.stored_path is not None:
            head += f"; stored {self.stored_path}"
            if self.artifact_verdict:
                head += (
                    f"; artifact {self.artifact_verdict}"
                    + (
                        f" sha256 {self.artifact_sha256}"
                        if self.artifact_sha256
                        else ""
                    )
                    + f" ({self.artifact_source})"
                )
        if self.complete:
            head += (
                f"; post-save {self.post_save_mode}/{self.rolling_after}"
                f"; baseline {'restored' if self.baseline_restored else 'not restored'}"
            )
        elif self.reason:
            head += f" — {self.reason}"
        return head


class MpxBatchResult(ValueModel):
    """What the batch established: the explicit items, one compact entry per started run."""

    stage: MpxBatchStage
    items: tuple[MpxBatchItem, ...]
    declaration: MultiplexedRecordingDeclaration
    runs: tuple[MpxBatchRun, ...] = ()
    #: The item that did not complete (or did not start), when the batch stopped.
    stopped_item: MpxBatchItem | None = None
    #: Why it stopped: ``run_failed`` / ``run_refused`` / ``run_raised`` / ``gate`` /
    #: ``interrupted_inside_run`` / ``interrupted_between_runs``.
    stopped_kind: str = ""
    #: The parent record path that may be pending (or UNKNOWN) after an interruption.
    pending_record: Path | None = None
    bound_target: WindowTarget | None = None
    reason: str = ""
    error: str = ""
    owed: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.stage is MpxBatchStage.COMPLETE

    def summary(self) -> str:
        """One line for a log: how far the batch got, and what it still owes."""
        head = (
            f"mpx-batch {len(self.items)} item(s) on {list(self.declaration.channels)} "
            f"({self.declaration.count_summary()}): {self.stage.value}"
        )
        if self.bound_target is not None:
            head += f" one binding hwnd {self.bound_target.hwnd}"
        if self.stopped_item is not None:
            head += f"; stopped at {self.stopped_item.name!r} ({self.stopped_kind})"
        if self.pending_record is not None:
            head += f"; parent record possibly pending: {self.pending_record}"
        if self.reason:
            head += f" — {self.reason}"
        if self.owed:
            head += f"; still owed: {'; '.join(self.owed)}"
        return head


def _canonical_record(path: Path) -> str:
    """One identity for a record path under Windows' case-insensitive, link-resolved view."""
    return os.path.normcase(os.path.realpath(str(path)))


def _same_path(left: Path, right: Path) -> bool:
    """Whether two caller paths resolve to one path (case-folded, links followed)."""
    return _canonical_record(left) == _canonical_record(right)


def _is_within(child: Path, parent: Path) -> bool:
    """Whether ``child`` is ``parent`` or lies beneath it, under the same canonical view."""
    child_key = _canonical_record(child)
    parent_key = _canonical_record(parent)
    return child_key == parent_key or child_key.startswith(parent_key + os.sep)


def _literal_path_clause(path: Path) -> str | None:
    """Why a caller-written path is not the canonical Windows path it looks like, or ``None``.

    Nothing is trimmed, stripped or repaired: Windows silently drops a trailing dot or space and
    interprets a device stem as a device, so accepting such a component would let the durable
    record live at a different identity than the caller named. The refusal quotes the **exact**
    path the caller passed. ``..`` is a legal navigation component and is left to
    :func:`os.path.realpath` (the identity rule), not rewritten here.
    """
    text = str(path)
    parts = path.parts[1:] if path.anchor else path.parts
    for part in parts:
        if part in {"", ".", ".."}:
            continue
        if part != part.rstrip(" ."):
            return (
                f"the record path {text!r} has the component {part!r} ending in a dot or space: "
                "Windows drops that suffix, so the path the caller wrote is not the path that "
                "would exist, and no token is repaired"
            )
        if any(
            ch in _WINDOWS_FORBIDDEN or ord(ch) < 32 or ord(ch) == 127 for ch in part
        ):
            return (
                f"the record path {text!r} has the component {part!r} carrying a character "
                "Windows refuses in a file name, and no token is repaired"
            )
        stem = part.split(".", 1)[0]
        if stem.casefold() in _RESERVED:
            return (
                f"the record path {text!r} has the component {part!r} naming the reserved "
                f"Windows device {stem!r}: that is a device, not a durable record file, and no "
                "token is repaired"
            )
    return None


def _parent_identity(record: Path) -> tuple[int, int] | None:
    """The existing parent directory's volume/file identity, or ``None`` when unknown."""
    try:
        info = os.stat(record.parent)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def parse_also(specs: Sequence[str]) -> tuple[MpxBatchItem, ...]:
    """Parse repeatable ``--also NAME=RECORD`` tokens, in order, with no repair.

    The grammar is exactly one separator: the **first** ``=`` splits the store name from the
    parent-record path, and both sides stay literal (a path may contain ``=``; a *name*
    containing ``=`` is therefore not expressible through this flag). A token without a
    separator, an empty name or an empty path is a usage refusal — nothing is trimmed,
    re-quoted, case-folded or otherwise repaired. The name's real validity is the store
    owner's, judged by the batch preflight before anything is claimed.
    """
    out: list[MpxBatchItem] = []
    for spec in specs:
        text = str(spec)
        name, separator, record = text.partition("=")
        if not separator:
            raise ValueError(
                f"--also value {text!r} is not NAME=RECORD: one '=' separates the literal "
                "store name from the literal parent-record path"
            )
        if not name:
            raise ValueError(
                f"--also value {text!r} names no store name before '=': nothing is stored under "
                "no name, and no token is repaired"
            )
        if not record:
            raise ValueError(
                f"--also value {text!r} names no parent-record path after '=': every item owns "
                "one durable record, and no token is repaired"
            )
        out.append(MpxBatchItem(name=name, record=Path(record)))
    return tuple(out)


def _preflight(
    items: Sequence[MpxBatchItem],
    *,
    store_dir: Path | str,
    capture_root: Path | str,
) -> tuple[Path, Path, tuple[MpxBatchItem, ...]]:
    """Every item's names and records, and the capture slots — all refused together, nothing run.

    Names are judged by the store owner's own :func:`store_preflight` (format, directory,
    case-folded collision). Distinctness is checked here because it is the *batch's* new fact:
    two items that would store or claim the same thing are refused before the first item, not
    discovered halfway through a finite sequence.

    Record paths are identities, not strings: a caller component Windows would silently rewrite
    (a trailing dot or space, a reserved device stem, a forbidden character) is refused with the
    exact input; the parent directory's volume/file identity groups hard links, short names and
    ``..`` aliases; a record under the capture root is refused because it would collide with the
    root or a ``mpx-run-NNN`` claim; and a record placed directly in the artifact store is
    refused when its **exact stem** is one of the batch's store names, because the store owner
    attributes a new entry by that stem. A distinct sidecar outside the store is the documented
    contract; no stem is reinterpreted.
    """
    if not items:
        raise AcquisitionError(
            "the batch names no items: a finite batch is an explicit (name, record) sequence, "
            "and an empty one is refused before anything is inspected, claimed or pressed"
        )
    clauses: list[str] = []
    target_dir = store_directory(store_dir)
    capture_base = Path(capture_root).expanduser()
    if not capture_base.is_absolute():
        capture_base = (Path.cwd() / capture_base).resolve()
    capture_known = False
    try:
        capture_info = os.stat(capture_base)
    except FileNotFoundError:
        clauses.append(
            f"the capture root {capture_base} does not exist: every item claims an exclusive "
            "run root under it, so nothing was inspected or pressed"
        )
    except OSError as exc:
        clauses.append(
            f"the capture root {capture_base} could not be read ({type(exc).__name__}: {exc}): "
            "an unreadable root is not an empty one, so nothing was inspected or pressed"
        )
    else:
        if not stat.S_ISDIR(capture_info.st_mode):
            clauses.append(
                f"the capture root {capture_base} is not a directory: every item claims an "
                "exclusive run root under it, so nothing was inspected or pressed"
            )
        else:
            capture_known = True
    names: dict[str, str] = {}
    records: dict[tuple[int, int, str], str] = {}
    normalized: list[MpxBatchItem] = []
    checked = [
        raw if isinstance(raw, MpxBatchItem) else MpxBatchItem.model_validate(raw)
        for raw in items
    ]
    store_names = {item.name.casefold() for item in checked}
    for item in checked:
        try:
            store_preflight(item.name, target_dir)
        except AcquisitionError as exc:
            clauses.append(str(exc))
        key = item.name.casefold()
        if key in names:
            clauses.append(
                f"the batch names {names[key]!r} and {item.name!r}, which are one name on a "
                "case-insensitive volume: each item stores its own block under its own name"
            )
        else:
            names[key] = item.name
        literal = _literal_path_clause(item.record)
        if literal is not None:
            clauses.append(literal)
        try:
            record = trial_record_file(item.record, name=MPX_RUN_RECORD_NAME)
        except AcquisitionError as exc:
            clauses.append(str(exc))
            record = Path(item.record)
        parent = _parent_identity(record)
        if parent is None:
            clauses.append(
                f"the record directory for {record} has no readable identity: whether it is the "
                "same directory as another item's is UNKNOWN, so no record is claimed"
            )
        else:
            identity = (parent[0], parent[1], record.name.casefold())
            if identity in records:
                clauses.append(
                    f"the batch records {records[identity]!r} and {item.name!r} at one path "
                    f"({record}): each item owns one parent record and none is shared or "
                    "rewritten"
                )
            else:
                records[identity] = item.name
        if capture_known and _is_within(record, capture_base):
            clauses.append(
                f"the record {record} lies under the capture root {capture_base}: the root and "
                "its mpx-run-NNN claims are the capture owner's names, so a record there could "
                "collide with a claim and is refused (name a record outside the capture root)"
            )
        if _same_path(record.parent, target_dir):
            stem = record.stem.casefold()
            if stem in store_names:
                clauses.append(
                    f"the record {record} sits in the artifact store {target_dir} with the stem "
                    f"{record.stem!r}, which is a store name for this batch: the store owner "
                    "attributes a new entry by that exact stem, so the store would refuse after "
                    "the item's press; records live outside the store directory"
                )
        if record.exists():
            clauses.append(
                f"a record already exists at {record}: refusing to overwrite another run's "
                f"obligation for item {item.name!r}"
            )
        normalized.append(MpxBatchItem(name=item.name, record=record))
    if capture_known:
        try:
            slots = capture_run_slots(capture_base)
        except AcquisitionError as exc:
            clauses.append(str(exc))
        else:
            if slots < len(items):
                clauses.append(
                    f"the capture root {capture_base} has {slots} of the capture owner's "
                    f"{CAPTURE_RUN_LIMIT} mpx-run-NNN root(s) free for {len(items)} item(s), "
                    "and this batch never reuses or mixes another run's evidence"
                )
    if clauses:
        raise AcquisitionError(
            "; ".join(clauses)
            + " (refused before any window was bound, any record claimed or any popup opened)"
        )
    return target_dir, capture_base, tuple(normalized)


def _compact(
    item: MpxBatchItem,
    result: MpxRunResult,
    *,
    verdict: str,
    sha256: str,
    source: str,
) -> MpxBatchRun:
    post = result.post_save
    return MpxBatchRun(
        name=item.name,
        record=item.record,
        capture_root=result.capture_root,
        stage=result.stage,
        parent_record_phase=result.parent_record_phase,
        stored_path=result.stored_path,
        artifact_verdict=verdict,
        artifact_sha256=sha256,
        artifact_source=source,
        post_save_mode=result.post_save_mode,
        post_surface=result.post_surface,
        rolling_after=result.rolling_after,
        post_saved_closed=(
            post is not None
            and post.outcome is InspectionOutcome.CLOSED
            and post.popup_left_open is False
        ),
        baseline_restored=result.baseline_restored,
        owed=result.owed,
        reason=result.reason,
    )


def _gate(
    item: MpxBatchItem,
    result: MpxRunResult,
    *,
    bound: WindowTarget,
    declaration: MultiplexedRecordingDeclaration,
    store_dir: Path,
    restore_baseline: bool,
    verify: Callable[[Path, CompletedBlockDeclaration], MpxArtifactReport],
) -> tuple[tuple[str, ...], MpxArtifactReport | None]:
    """Why the completed run does not license the next item (or the batch's COMPLETE).

    Every clause is a fact the run itself reported, a fact re-read **from the durable parent
    record** through the owner's :class:`MpxFinalRecord` contract, or a fact this gate observed
    now. ``complete`` alone is never enough, and the stored artifact is verified **now** against
    the same declaration rather than trusted from the run's earlier verdict. The returned report
    is the one fresh check, so a caller reports it instead of decoding the file a second time.
    """
    out: list[str] = []
    fresh: MpxArtifactReport | None = None
    if result.stage is not MpxRunStage.COMPLETE:
        out.append(f"the run ended {result.stage.value}, not complete")
    if result.parent_record_phase != "final":
        out.append(
            "the parent record is not final "
            f"(phase {result.parent_record_phase or 'unclaimed'!r})"
        )
    if result.parent_record_error:
        out.append(f"the parent record was not rewritten: {result.parent_record_error}")
    if result.owed:
        out.append(f"the run still owes {len(result.owed)} clause(s)")
    if not result.baseline_restored:
        out.append("the declared baseline is not restored")
    if result.post_save_mode != "VISUAL_DISABLED":
        out.append(
            f"the post-save mode is {result.post_save_mode}, not VISUAL_DISABLED"
        )
    if result.post_save_mode_source not in _POST_SAVE_MODE_SOURCES:
        out.append(
            "the post-save mode is not sourced from a fresh capture "
            f"({result.post_save_mode_source or 'no source'!r})"
        )
    if result.rolling_after != "OFF_PROVEN":
        out.append(f"rolling after the run is {result.rolling_after}, not OFF_PROVEN")
    post = result.post_save
    if (
        post is None
        or post.outcome is not InspectionOutcome.CLOSED
        or post.popup_left_open is not False
    ):
        out.append("the post-save Channels popup is not observed closed")
    if result.bound_target != bound:
        out.append(
            "the run's bound target "
            f"{None if result.bound_target is None else result.bound_target.hwnd} is not the "
            f"batch's one binding {bound.hwnd} (full identity)"
        )
    for label, child in (
        ("rollover", result.rollover),
        ("enable", result.enable),
        ("record", result.record),
        ("restore", result.restore),
    ):
        if child is not None and child.bound_target != bound:
            stated = getattr(child, "bound_target", None)
            out.append(
                f"the {label} child is bound to "
                f"{None if stated is None else stated.hwnd}, not the batch's binding "
                f"{bound.hwnd} (full identity)"
            )
    record = result.record
    if record is None:
        out.append("the run reports no record child result")

    durable: MpxFinalRecord | None = None
    if result.parent_record is None:
        out.append("the run states no parent record path")
    else:
        if not _same_path(result.parent_record, item.record):
            out.append(
                f"the run's parent record {result.parent_record} is not this item's record "
                f"{item.record} (one path)"
            )
        try:
            durable = read_parent_record(result.parent_record)
        except AcquisitionError as exc:
            out.append(
                f"the durable parent record is not the owner's final record: {exc}"
            )
    if durable is not None:
        if durable.phase != FINAL_RECORD_PHASE:
            out.append(
                f"the durable record phase is {durable.phase!r}, not the final "
                f"{FINAL_RECORD_PHASE!r} record"
            )
        if durable.command != "mpx-run":
            out.append(
                f"the durable record command is {durable.command!r}, not 'mpx-run'"
            )
        if durable.name != item.name:
            out.append(
                f"the durable record names {durable.name!r}, not this item {item.name!r}"
            )
        if not _same_path(Path(durable.store_dir), store_dir):
            out.append(
                f"the durable record stores in {durable.store_dir}, not {store_dir}"
            )
        if not _same_path(Path(durable.capture_root), result.capture_root):
            out.append(
                f"the durable record's capture root {durable.capture_root} is not the run's "
                f"{result.capture_root}"
            )
        if durable.declaration != declaration:
            out.append(
                "the durable record's declaration is not the batch's one declaration"
            )
        if durable.baseline != "off":
            out.append(
                f"the durable record's baseline is {durable.baseline!r}, not the literal 'off'"
            )
        if durable.restore_baseline is not restore_baseline:
            out.append(
                "the durable record's restore flag is "
                f"{durable.restore_baseline}, not the batch's {restore_baseline}"
            )
        if durable.bound_target != bound:
            out.append(
                "the durable record's bound target "
                f"{durable.bound_target.hwnd} is not the batch's one binding {bound.hwnd} "
                "(full identity)"
            )
        if not _same_path(Path(durable.parent_record), item.record):
            out.append(
                f"the durable record names itself {durable.parent_record}, not {item.record}"
            )
        if durable.stage is not MpxRunStage.COMPLETE:
            out.append(
                f"the durable record states stage {durable.stage.value}, not complete"
            )
        if durable.owed:
            out.append(f"the durable record still owes {len(durable.owed)} clause(s)")
        if not durable.baseline_restored:
            out.append("the durable record states the baseline is not restored")
        if durable.rolling_after != "OFF_PROVEN":
            out.append(
                f"the durable record's rolling after is {durable.rolling_after!r}, not "
                "OFF_PROVEN"
            )
        if durable.post_save_mode != "VISUAL_DISABLED":
            out.append(
                f"the durable record's post-save mode is {durable.post_save_mode!r}, not "
                "VISUAL_DISABLED"
            )
        if durable.post_save_mode_source not in _POST_SAVE_MODE_SOURCES:
            out.append(
                "the durable record's post-save mode is not sourced from a fresh capture "
                f"({durable.post_save_mode_source or 'no source'!r})"
            )
        if not durable.artifact_consistent:
            out.append("the durable record states the artifact is not consistent")
        if durable.stored_path is None:
            out.append("the durable record states no stored path")
        elif result.stored_path is None:
            out.append("the run states no stored path")
        elif not _same_path(Path(durable.stored_path), result.stored_path):
            out.append(
                f"the durable record's stored path {durable.stored_path} is not the run's "
                f"{result.stored_path}"
            )

    stored = result.stored_path
    if stored is None:
        out.append("the run states no stored path")
    elif not stored.is_file():
        out.append(f"the stored path {stored} is not a file on disk now")
    elif not result.artifact_consistent:
        out.append("the run's own artifact verdict is not consistent")
    else:
        reported = record.artifact_verification if record is not None else None
        reported_sha = "" if reported is None else (reported.file_sha256 or "")
        if not reported_sha:
            out.append("the run's artifact report carries no digest to re-check")
        else:
            try:
                fresh = verify(stored, declaration.completed_block())
            except Exception as exc:  # noqa: BLE001 - a verifier failure is a gate refusal
                out.append(
                    f"the fresh artifact re-check raised ({type(exc).__name__}: {exc})"
                )
            else:
                if fresh.verdict is not MpxVerdict.CONSISTENT:
                    out.append(
                        f"the fresh artifact re-check is {fresh.verdict.value}, not consistent"
                    )
                if fresh.file_sha256 != reported_sha:
                    out.append(
                        "the file on disk no longer carries the digest the run verified "
                        f"({fresh.file_sha256} against {reported_sha})"
                    )
    return tuple(out), fresh


def run_mpx_batch(
    *,
    items: Sequence[MpxBatchItem],
    declaration: MultiplexedRecordingDeclaration,
    store_dir: Path | str,
    capture_root: Path | str,
    completion_timeout_s: float,
    baseline: str = "off",
    restore_baseline: bool = True,
    settle_s: float = 3.0,
    boundary_seconds: float | None = None,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    verify_artifact: Callable[
        [Path, CompletedBlockDeclaration], MpxArtifactReport
    ] = verify_mpx_artifact,
    seams: dict[str, object] | None = None,
    notes: list[str] | None = None,
) -> MpxBatchResult:
    """Run the explicit items in order, gating each boundary, and stop at the first failure.

    ``seams`` is handed to every :func:`run_mpx_once` unchanged (the child owners' injection
    points, used by tests and probes); this function adds no acquisition logic of its own.
    Every refusal **before the batch's one binding** raises :class:`AcquisitionError`; every
    outcome after it is a returned report, because the earlier runs' evidence is the operator's.
    """
    sink = notes if notes is not None else []
    declaration = validate_declaration(declaration)
    validate_bounds(
        completion_timeout_s=completion_timeout_s,
        settle_s=settle_s,
        boundary_seconds=boundary_seconds,
    )
    restore_baseline = strict_flag("restore_baseline", restore_baseline)
    try:
        baseline_mark = Rolling(baseline)
    except (ValueError, TypeError) as exc:
        raise AcquisitionError(
            f"baseline must be the literal 'on' or 'off', got {baseline!r}: every batch item "
            "starts from the stopped, multiplexer-disabled screen with rolling off"
        ) from exc
    if baseline_mark is not Rolling.OFF:
        raise AcquisitionError(
            f"baseline {baseline!r}: every batch item starts from the stopped, "
            "multiplexer-disabled screen with rolling off, so only the literal 'off' is "
            "accepted and nothing was inspected or pressed"
        )
    target_dir, capture_base, ordered = _preflight(
        items, store_dir=store_dir, capture_root=capture_root
    )

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
    bound = bind_once(
        actuator=live, enumerate_windows=enumerate_fn, class_name=class_name
    )
    sink.append(
        f"mpx-batch binds hwnd {bound.hwnd} once and hands that record to every item; no item "
        "may bind a second time"
    )
    run_kwargs: dict[str, object] = dict(seams or {})

    runs: list[MpxBatchRun] = []

    def result(
        stage: MpxBatchStage,
        *,
        stopped: MpxBatchItem | None = None,
        kind: str = "",
        reason: str = "",
        error: str = "",
        owed: tuple[str, ...] = (),
        pending: Path | None = None,
    ) -> MpxBatchResult:
        return MpxBatchResult(
            stage=stage,
            items=ordered,
            declaration=declaration,
            runs=tuple(runs),
            stopped_item=stopped,
            stopped_kind=kind,
            pending_record=pending,
            bound_target=bound,
            reason=reason,
            error=error,
            owed=owed,
            notes=tuple(sink),
        )

    for index, item in enumerate(ordered):
        next_item = ordered[index + 1] if index + 1 < len(ordered) else None
        try:
            outcome = run_mpx_once(
                name=item.name,
                store_dir=target_dir,
                capture_root=capture_base,
                record=item.record,
                declaration=declaration,
                completion_timeout_s=completion_timeout_s,
                baseline=baseline,
                restore_baseline=restore_baseline,
                settle_s=settle_s,
                boundary_seconds=boundary_seconds,
                actuator=live,
                bound_target=bound,
                enumerate_windows=enumerate_fn,
                class_name=class_name,
                notes=sink,
                **run_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - a raised setup is a stated stop
            error = f"{type(exc).__name__}: {exc}"
            return result(
                MpxBatchStage.STOPPED,
                stopped=item,
                kind=(
                    "run_refused" if isinstance(exc, AcquisitionError) else "run_raised"
                ),
                reason=(
                    f"item {item.name!r} raised before its own outcome, so no result is "
                    f"reported for it: {error}. The {len(runs)} earlier item(s) above stand as "
                    "reported; nothing for this item was retried and no further item was started"
                ),
                error=error,
            )
        except KeyboardInterrupt as exc:
            # The deliberate cancellation boundary: an explicit INTERRUPTED result, not a
            # re-raise, so the completed runs' summaries survive. SystemExit is **not**
            # cancellation and is allowed to propagate (a process-exit request is not ours).
            error = f"{type(exc).__name__}: {exc}"
            return result(
                MpxBatchStage.INTERRUPTED,
                stopped=item,
                kind="interrupted_inside_run",
                reason=(
                    f"item {item.name!r} was cancelled inside the run ({error}): this batch "
                    "cannot promise that run's cleanup or a durable partial, so its outcome is "
                    f"UNKNOWN; the {len(runs)} completed item(s) above stand as reported, its "
                    f"parent record {item.record} may be pending, and no second Record was or "
                    "will be pressed"
                ),
                error=error,
                pending=item.record,
            )

        reported = outcome.record.artifact_verification if outcome.record else None
        verdict = "" if reported is None else reported.verdict.value
        digest = "" if reported is None else (reported.file_sha256 or "")
        source = "run_report" if reported is not None else ""
        if not outcome.complete:
            runs.append(
                _compact(item, outcome, verdict=verdict, sha256=digest, source=source)
            )
            return result(
                MpxBatchStage.STOPPED,
                stopped=item,
                kind="run_failed",
                reason=(
                    f"item {item.name!r} ended {outcome.stage.value}: {outcome.reason}. No "
                    "further item was started and no run was retried"
                ),
                owed=outcome.owed,
            )

        try:
            clauses, fresh = _gate(
                item,
                outcome,
                bound=bound,
                declaration=declaration,
                store_dir=target_dir,
                restore_baseline=restore_baseline,
                verify=verify_artifact,
            )
        except KeyboardInterrupt as exc:
            error = f"{type(exc).__name__}: {exc}"
            runs.append(
                _compact(item, outcome, verdict=verdict, sha256=digest, source=source)
            )
            if next_item is None:
                return result(
                    MpxBatchStage.INTERRUPTED,
                    stopped=item,
                    kind="interrupted_between_runs",
                    reason=(
                        f"the final gate after item {item.name!r} was cancelled ({error}): "
                        f"item {item.name!r} stands as reported, no item was started, and no "
                        "record was claimed"
                    ),
                    error=error,
                )
            return result(
                MpxBatchStage.INTERRUPTED,
                stopped=next_item,
                kind="interrupted_between_runs",
                reason=(
                    f"the gate before item {next_item.name!r} was cancelled ({error}): item "
                    f"{item.name!r} stands as reported, item {next_item.name!r} was not "
                    "started, and no record was claimed for it"
                ),
                error=error,
            )
        if clauses:
            runs.append(
                _compact(item, outcome, verdict=verdict, sha256=digest, source=source)
            )
            if next_item is None:
                return result(
                    MpxBatchStage.STOPPED,
                    stopped=item,
                    kind="gate",
                    reason=(
                        f"item {item.name!r} completed but its final boundary is not proved, "
                        "so this batch is not COMPLETE and no further item exists: "
                        + "; ".join(clauses)
                    ),
                    owed=clauses,
                )
            return result(
                MpxBatchStage.STOPPED,
                stopped=next_item,
                kind="gate",
                reason=(
                    f"item {item.name!r} completed but its boundary is not proved, so item "
                    f"{next_item.name!r} was not inspected, claimed or pressed: "
                    + "; ".join(clauses)
                ),
                owed=clauses,
            )
        runs.append(
            _compact(
                item,
                outcome,
                verdict="" if fresh is None else fresh.verdict.value,
                sha256="" if fresh is None else (fresh.file_sha256 or ""),
                source="gate",
            )
        )

    return result(MpxBatchStage.COMPLETE)
