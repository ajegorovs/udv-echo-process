"""The **store-only** command: save a multiplexed block the application has already completed.

The operator records by hand — enables the multiplexer, presses ``Record``, lets the configured
channels run to the application's own completion — and stops there. What is left is one
``Do store`` and a name. This module does exactly that and nothing else.

**What it is not.** It presses neither ``Record``, ``Stop``, ``Pause``, ``Clear and restart``,
``New acquisition`` nor ``Remove current block``; it opens no ``Channels`` menu and writes no
parameter. :func:`store_completed` is the only press path, and the single ``press`` call in this
module is :attr:`~udv_echo_process.acquire.actuator.StripControl.DO_STORE` on a row that was
re-read and re-verified immediately before it.

**Why there is no plan and no dwell.** A completed recording has nothing left to time, so the
operator's statement is a :class:`CompletedBlockDeclaration` — the channels and the per-channel
profile count of the block **on screen**, attributed and dated — and not a recording plan. Nothing
here derives the profile count, and nothing converts a requested count into an observed one.

**What must be true before the one press** (all refused together, nothing pressed):

1. exactly one visible ``TMain_Scr`` window, and it is the handle bound with ``bind_target``;
2. the caption states the instrument (``UDOP DOP3010…``) — never the simulator, never nothing;
3. no overlay is already up;
4. the strip is the measured MPX completion row: store view, slider visible, exactly
   ``Do store`` and ``Clear and restart`` — so a ready, recording, ambiguous, three-button or
   four-button row is refused;
5. the operator's explicit declaration (more than one channel named, positive profile count,
   named operator) is valid;
6. the store name is one safe file-name **stem**, the directory exists and can be listed, and no
   entry in it already has that stem.

Clauses 1, 3 and 4 are re-read immediately before the press, because the screen can change
between the first check and the gesture.

**The new entry is *ours*, or the store failed.** One ``Do store`` on the strip, one bounded wait
for the Store dialog (at most one warning answered with its safe button), one name write, the
working directory asserted, one commit press, then a **new** directory entry whose stem must be
the requested name. A collision is refused before the press; a new entry that is not this block is
a refusal that says the store was committed once and the block's whereabouts are unknown. Nothing
is retried, nothing is overwritten, and no ``<name>b`` fallback name is ever used.

Nothing here runs at import time: no window is read, no message posted, no file written.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationError, model_validator

from udv_echo_process.acquire.actuator import (
    STORE_TIMEOUT_S,
    STRIP_BUTTON_ORDER,
    OverlayKind,
    ProcessMode,
    StripControl,
    StripState,
    StripView,
    WindowTarget,
)
from udv_echo_process.acquire.driver import Win32Actuator
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.ui.layout import MAIN_CLASS, process_mode_clause
from udv_echo_process.acquire.win32.tree import visible_main_windows
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DIALOG_POLL_S",
    "CompletedBlockDeclaration",
    "CompletedStoreResult",
    "StoreAttempt",
    "collision_clause",
    "completed_strip_clauses",
    "store_completed",
    "store_directory",
    "store_name_clause",
    "stored_file_clauses",
]

#: How often the Store dialog's arrival is polled. The application's own store cadence is the
#: recording surface's private ``_POLL_S`` (0.4 s); this module keeps its own copy rather than
#: importing a private, and the value is a poll interval, not a decision.
DIALOG_POLL_S = 0.4

#: Characters that cannot be part of a single Windows file name: a store name carrying one is a
#: path or an illegal name, never a stem the dialog can store under.
_NAME_FORBIDDEN = '\\/:*?"<>|'

#: Windows device names a file may not be called — ``NUL`` is a sink, not a file to wait for.
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)

#: The measured MPX completion row: store view, two buttons, ``Do store`` then
#: ``Clear and restart`` (:data:`STRIP_BUTTON_ORDER`).
_COMPLETED_ROW = (StripControl.DO_STORE, StripControl.CLEAR_AND_RESTART)


class CompletedBlockDeclaration(ValueModel):
    """The operator's statement about a multiplexed block that has **already completed**.

    Nothing here is read off the screen: the mode has no passive discriminator in this
    repository, so the channel set and the profile count are the operator's own declaration,
    attributed to a person and optionally dated. ``profiles_per_channel`` is retained exactly as
    stated — the count is a reading of the completed block, never a default and never derived from
    a requested value.
    """

    channels: tuple[Annotated[int, Field(strict=True, gt=0)], ...]
    #: Strict: a bool or a string is not a count the operator stated.
    profiles_per_channel: int = Field(strict=True)
    stated_by: str
    stated_at: str = ""
    #: The operator's own words, kept raw for the report.
    statement: str = ""

    @model_validator(mode="after")
    def _require_stated(self) -> CompletedBlockDeclaration:
        clauses = self.clauses()
        if clauses:
            raise ValueError("; ".join(clauses))
        return self

    def clauses(self) -> tuple[str, ...]:
        """Everything this declaration fails to state, as refused clauses (empty when valid)."""
        out: list[str] = []
        if not self.channels:
            out.append(
                "the declaration names no channels: a completed block is stored under the "
                "channel set the operator states, and an empty statement names nothing"
            )
        else:
            if len(set(self.channels)) != len(self.channels):
                out.append(
                    f"the declared channels {list(self.channels)} repeat one: a channel is "
                    "named once in a completed block"
                )
            if len(self.channels) < 2:
                out.append(
                    f"the declaration names {len(self.channels)} channel(s): this command "
                    "stores a multiplexed block, and a single-channel completion is not one"
                )
            if any(int(channel) < 1 for channel in self.channels):
                out.append(
                    f"the declared channels {list(self.channels)} include a non-positive "
                    "number: no channel is numbered zero or below"
                )
        profiles = self.profiles_per_channel
        if isinstance(profiles, bool) or not isinstance(profiles, int) or profiles < 1:
            out.append(
                "the declaration does not state a positive profile count per channel: the "
                "count is the operator's reading of the completed block, never a default"
            )
        if not self.stated_by.strip():
            out.append(
                "the declaration names no operator: an unattributed 'yes' is not one"
            )
        return tuple(out)


class StoreAttempt(ValueModel):
    """What the one store attempt did, with the path behaviour stated rather than implied.

    ``directory_rewritten`` says the driver wrote the caller's working directory because the
    dialog showed another one; ``working_directory`` is the value read back after that write.
    """

    name: str
    directory: Path
    working_directory: str
    directory_rewritten: bool
    dialog_warnings_answered: int = Field(ge=0)
    commit_presses: int = Field(default=1, ge=1)
    waited_s: float = Field(ge=0)
    stored_path: Path
    #: The **observed** new entry's name, which the stem check bound to ``name``. Kept because
    #: the extension is the application's choice, never this command's.
    stored_name: str
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        clause = (
            f"store: pressed 'Do store' on the strip once, wrote {self.name!r}, working "
            f"directory {self.working_directory!r}"
        )
        if self.directory_rewritten:
            clause += (
                " (rewritten to the caller's directory: the field decides where the point "
                "lands, so the app wrote it rather than refusing)"
            )
        return (
            f"{clause}; committed once, {self.dialog_warnings_answered} dialog warning(s) "
            f"answered, new file seen after {self.waited_s:.1f} s; the new entry "
            f"{self.stored_name!r} is the only one whose stem is the requested name"
        )


class CompletedStoreResult(ValueModel):
    """One store-only run's outcome: the path, the attempt, and the screen it verified."""

    stored_path: Path
    store: StoreAttempt
    strip_state: StripState
    declaration: CompletedBlockDeclaration
    bound_target: WindowTarget
    driver_notes: tuple[str, ...] = ()

    def summary(self) -> str:
        return (
            f"stored {self.stored_path.name!r} from the completed block on channels "
            f"{list(self.declaration.channels)} "
            f"({self.declaration.profiles_per_channel} profiles each, as stated): "
            f"{self.store.summary()}"
        )


def store_name_clause(name: str) -> str | None:
    """Why ``name`` is not one safe file-name *stem* for the Store dialog, or ``None``.

    The dialog takes a bare name and the application supplies the extension — the documented
    chain stores ``auto-cycle-1`` as ``auto-cycle-1.BDD`` (``docs/dop3000/udop-automation.md``
    §1, §4) — so a **stem** is what is validated. Everything whose product could not be
    attributed back to the requested name is refused: a separator or traversal segment (which
    would store outside the watched directory), a name that already carries a suffix, a dotfile,
    a control character, a trailing dot/space and a reserved device name.
    """
    if not name or not name.strip():
        return "the store name is empty: nothing may be stored under no name"
    if name != name.strip():
        return (
            f"the store name {name!r} has leading or trailing whitespace: the dialog would take "
            "it literally and the entry it produced could not be matched to it"
        )
    bad = sorted(
        {ch for ch in name if ch in _NAME_FORBIDDEN or ord(ch) < 32 or ord(ch) == 127}
    )
    if bad:
        return (
            f"the store name {name!r} contains {bad!r}: a store name is one file-name stem, "
            "never a path, and a separator would store outside the directory this command "
            "watches"
        )
    if Path(name).name != name:
        return f"the store name {name!r} is not a single path component"
    if name in {".", ".."}:
        return f"the store name {name!r} is a traversal segment, not a file name"
    if name.startswith("."):
        return (
            f"the store name {name!r} starts with a dot: that is a hidden/dotfile name, not the "
            "bare stem the dialog stores"
        )
    if name.endswith("."):
        return (
            f"the store name {name!r} ends with a dot: Windows drops a trailing dot, so the "
            "entry it produced would not carry the requested name"
        )
    suffix = Path(name).suffix
    if suffix:
        return (
            f"the store name {name!r} already carries the suffix {suffix!r}: the dialog takes a "
            "bare name and the application supplies the extension (documented: 'auto-cycle-1' "
            "stores as 'auto-cycle-1.BDD'), so a suffixed name cannot be attributed to the file "
            "it produces"
        )
    if name.casefold() in _RESERVED_NAMES:
        return (
            f"the store name {name!r} is a reserved Windows device name, not a file this "
            "command could wait for"
        )
    return None


def store_directory(directory: Path) -> Path:
    """The caller's store directory, absolute — one normalization for every caller."""
    target = Path(directory).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    return target


def _directory_names(directory: Path) -> frozenset[str]:
    """The directory's current entry names, or a refusal naming why it cannot be listed."""
    try:
        return frozenset(p.name for p in directory.glob("*"))
    except OSError as exc:
        raise AcquisitionError(
            f"the store directory {directory} could not be listed ({exc}): a folder this "
            "command cannot list is a folder whose new file it could not attribute, so nothing "
            "is pressed"
        ) from exc


def collision_clause(
    name: str, directory: Path, known: Iterable[str] = ()
) -> str | None:
    """Refuse a name already taken, comparing stems case-folded (``x.BDD`` vs ``x``)."""
    taken = _directory_names(directory) | {str(entry) for entry in known}
    collision = sorted(
        entry for entry in taken if Path(entry).stem.casefold() == name.casefold()
    )
    if not collision:
        return None
    return (
        f"the name {name!r} is already taken in {directory} ({collision[0]!r}): the store is "
        "refused before the press rather than raising an overwrite warning, and this command "
        "never replaces an existing file"
    )


def stored_file_clauses(
    name: str, directory: Path, path: Path, *, known: Iterable[str] = ()
) -> tuple[str, ...]:
    """Why ``path`` is not the file that storing ``name`` in ``directory`` produced, or ``()``.

    The driver's wait returns the first **new** directory entry it sees, whatever it is: another
    process's file, a subdirectory, or a name this point was not stored under
    (``acquire/udop/store.py::_poll_new_file``). Every fact that makes the entry this block's is
    therefore checked: it is inside the watched directory, it was not there before, it is a
    regular file, and its stem is the requested name case-folded (a case-insensitive volume may
    restate the case). The extension is **not** checked — what the application appends is
    observed, never assumed.
    """
    returned = Path(path)
    out: list[str] = []
    if not returned.is_absolute():
        out.append(f"the returned entry {str(returned)!r} is not an absolute path")
    elif returned.parent.resolve() != directory.resolve():
        out.append(
            f"the returned entry {returned} is not in the watched directory {directory}"
        )
    if returned.name in {str(entry) for entry in known}:
        out.append(
            f"the returned entry {returned.name!r} was already in {directory} before the "
            "commit: it is not the file this store produced"
        )
    if not returned.exists():
        out.append(f"the returned entry {returned} does not exist on disk")
    elif not returned.is_file():
        out.append(
            f"the returned entry {returned} is not a regular file (a directory or device): the "
            "driver's new-entry wait reports any new name, not the stored point"
        )
    if returned.stem.casefold() != name.casefold():
        out.append(
            f"the returned entry {returned.name!r} has the stem {returned.stem!r} where the "
            f"requested store name is {name!r}: the block this command stored cannot be "
            "attributed to it"
        )
    return tuple(out)


def completed_strip_clauses(state: StripState) -> tuple[str, ...]:
    """Why ``state`` is not the completed multiplexed row this command stores from, or ``()``.

    The measured MPX completion is the two-button, slider-bearing row (``269x123``, 2026-10-20
    capture): ``STRIP_BUTTON_ORDER[(STORE, 2)]`` binds exactly ``Do store`` and
    ``Clear and restart``. The three- and four-button store rows bind ``New acquisition`` /
    ``Remove current block`` as well, so a press from them would have to choose a role this
    command does not own; every such row, and every recording/ready/ambiguous row, is refused by
    name with nothing pressed.
    """
    view = state.view
    if view is not StripView.STORE:
        return (
            (
                f"the strip reads {view.value!r} with {state.button_count} button(s) and "
                f"{'a' if state.has_slider else 'no'} slider, not a completed block's store row: "
                "this command only stores a recording the application has already finished — it "
                "never starts, stops, pauses or clears one"
            ),
        )
    if not state.has_slider:
        return (
            (
                f"the strip reads {view.value!r} with {state.button_count} button(s) but no "
                "slider: the store view is marked by its slider, and without one the row is not "
                "the row this command stores from"
            ),
        )
    if (view, state.button_count) not in STRIP_BUTTON_ORDER:
        return (
            (
                f"the completed row holds {state.button_count} button(s), which is no row in "
                "STRIP_BUTTON_ORDER: no press is bound in it"
            ),
        )
    if STRIP_BUTTON_ORDER[(view, state.button_count)] != _COMPLETED_ROW:
        return (
            (
                "the completed row binds "
                f"{[c.value for c in STRIP_BUTTON_ORDER[(view, state.button_count)]]} where this "
                "command requires exactly 'Do store' and 'Clear and restart' (the measured "
                "two-button MPX completion row): a row carrying any other role makes a press "
                "here a choice this command does not make, and nothing is pressed"
            ),
        )
    return ()


def _screen_check(
    actuator,
    target: WindowTarget,
    windows: Sequence[int],
    *,
    class_name: str,
) -> tuple[tuple[str, ...], StripState | None]:
    """The window/caption/overlay/row preconditions, as refused clauses and the strip read."""
    out: list[str] = []
    if len(windows) != 1:
        out.append(
            f"{len(windows)} visible {class_name} window(s) are up {list(windows)}: this "
            "command drives exactly one application, and it will not choose between copies"
        )
    elif int(windows[0]) != target.hwnd:
        out.append(
            f"the only visible window is {windows[0]} where the binding is {target.hwnd}: "
            "refusing to act on a window the binding does not name"
        )
    try:
        caption = actuator.window_caption()
    except Exception as exc:  # noqa: BLE001 - an unreadable caption is a refusal
        out.append(f"the bound window's caption could not be read: {exc}")
    else:
        clause = process_mode_clause(caption, ProcessMode.INSTRUMENT)
        if clause is not None:
            out.append(clause)
    overlay = actuator.peek_overlay()
    if overlay is not None:
        out.append(
            f"an overlay is already up ({overlay.value}): this command refuses to start behind "
            "a modal and never dismisses one to make room"
        )
    state: StripState | None = None
    try:
        state = actuator.strip_state()
    except Exception as exc:  # noqa: BLE001
        out.append(
            f"the recording strip could not be read: {type(exc).__name__}: {exc}"
        )
    else:
        out.extend(completed_strip_clauses(state))
    return tuple(out), state


def store_completed(
    name: str,
    directory: Path,
    *,
    declaration: CompletedBlockDeclaration,
    channel: int | None = None,
    store_timeout_s: float = STORE_TIMEOUT_S,
    dialog_timeout_s: float = 10.0,
    actuator=None,
    enumerate_windows: Callable[[], Sequence[int]] | None = None,
    class_name: str = MAIN_CLASS,
    notes: list[str] | None = None,
) -> CompletedStoreResult:
    """Store the block that is already on screen, once, under ``name``.

    The store's own preconditions are checked **before** a driver is built or a window is bound:
    a name that is not one safe file-name stem, a directory that does not exist or cannot be
    listed, and a name already taken in the watched directory (stems compared case-folded,
    because the application appends its own extension). A run that would have to be thrown away
    is never started.

    The default wiring is the real one: a ``Win32Actuator`` (no target, so nothing is selected
    before the count is known) bound with ``bind_target`` to the single visible ``TMain_Scr``
    window. ``actuator`` and ``enumerate_windows`` exist so an offline test can hand in
    driver-shaped objects; passing them changes nothing about the composition under test.

    Raises :class:`~udv_echo_process.acquire.udop.AcquisitionError` for every refusal: the name,
    the directory, a collision, an unreadable screen, a window count other than one, a simulator
    or unknown caption, an overlay, a strip that is not the completed row, a Store dialog that
    does not open, a working directory that did not verify, no new file within
    ``store_timeout_s``, or a new entry that cannot be attributed to ``name``. Nothing is retried
    and nothing is overwritten.
    """
    try:
        declaration = CompletedBlockDeclaration.model_validate(declaration)
    except ValidationError as exc:
        raise AcquisitionError(f"invalid completed-block declaration: {exc}") from exc
    for label, value in (
        ("store_timeout_s", store_timeout_s),
        ("dialog_timeout_s", dialog_timeout_s),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise AcquisitionError(
                f"{label} must be finite positive seconds, got {value!r}"
            )
    target_dir = store_directory(directory)
    clause = store_name_clause(name)
    if clause is not None:
        raise AcquisitionError(f"{clause} (refused before anything is pressed)")
    if not target_dir.is_dir():
        raise AcquisitionError(
            f"the store directory {target_dir} does not exist (or is not a directory): the "
            "Store dialog's working directory is set by this command, and nothing is pressed "
            "for a folder that is not there"
        )
    taken = collision_clause(name, target_dir)
    if taken is not None:
        raise AcquisitionError(f"{taken} (refused before anything is pressed)")

    sink = notes if notes is not None else []
    live = (
        actuator
        if actuator is not None
        else Win32Actuator(channel=channel, note_sink=sink.append)
    )
    if enumerate_windows is None:
        enumerate_windows_fn: Callable[[], Sequence[int]] = lambda: (
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
    clauses, state = _screen_check(live, target, windows, class_name=class_name)
    if clauses:
        raise AcquisitionError("; ".join(clauses))
    assert (
        state is not None
    )  # no clause was produced, so the strip was read and accepted

    # The screen can change between the check above and the gesture, so the row, the overlay and
    # the name are re-read here; ``before`` is the snapshot the new-entry wait is given.
    before = _directory_names(target_dir)
    clauses, current_state = _screen_check(
        live, target, tuple(enumerate_windows_fn()), class_name=class_name
    )
    taken = collision_clause(name, target_dir, before)
    if taken is not None:
        clauses += (taken,)
    if clauses:
        raise AcquisitionError("; ".join(clauses))
    assert current_state is not None
    state = current_state

    started = time.monotonic()
    live.press(StripControl.DO_STORE)  # once

    answered = 0
    deadline = time.monotonic() + dialog_timeout_s
    while True:
        overlay = live.peek_overlay()
        if overlay is OverlayKind.STORE_DIALOG:
            break
        if overlay is OverlayKind.WARNING:
            if answered:
                raise AcquisitionError(
                    "a second warning came up before the Store dialog: the first one was "
                    "answered with its safe button and this command does not keep answering"
                )
            live.answer_overlay()
            answered += 1
        if time.monotonic() >= deadline:
            raise AcquisitionError(
                "the Store dialog did not open within "
                f"{dialog_timeout_s:g} s of the strip's 'Do store' press"
            )
        time.sleep(DIALOG_POLL_S)

    live.set_store_name(name)
    notes_before = len(getattr(live, "warnings", ()))
    verified_directory = live.assert_working_directory(target_dir)
    new_notes = tuple(getattr(live, "warnings", ())[notes_before:])
    rewritten = any(
        note.startswith("the Store dialog's Working directory was")
        for note in new_notes
    )
    live.commit_store()  # once

    path = Path(
        live.wait_for_stored_file(target_dir, known=before, timeout_s=store_timeout_s)
    )
    clauses = stored_file_clauses(name, target_dir, path, known=before)
    if clauses:
        raise AcquisitionError(
            f"the store committed once and the new entry {path.name!r} is not the file "
            f"{name!r} was stored as: {'; '.join(clauses)} — nothing was overwritten and nothing "
            f"retried, so whether a block exists under {name!r} is unknown"
        )

    attempt = StoreAttempt(
        name=name,
        directory=target_dir,
        working_directory=str(verified_directory),
        directory_rewritten=rewritten,
        dialog_warnings_answered=answered,
        commit_presses=1,
        waited_s=time.monotonic() - started,
        stored_path=path,
        stored_name=path.name,
        notes=new_notes,
    )
    return CompletedStoreResult(
        stored_path=path,
        store=attempt,
        strip_state=state,
        declaration=declaration,
        bound_target=target,
        driver_notes=tuple(getattr(live, "warnings", ())),
    )
