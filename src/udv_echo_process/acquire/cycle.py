"""The record → stop → store cycle, composed from routine calls and one dialog commit.

This is the message route's own cycle, as an object rather than a script. Every part of it has been measured on the live
application: the strip routines take the form object this instance was primed with and write the application's own command
codes (so no input starts or stops a recording), the store raises a dialog whose name field is a plain edit, and that
dialog's `Accept` takes a posted press because a modal is the active window.

What the class adds over a sequence of calls is the discipline the rest of this package already applies: a name already
used is refused before anything is recorded, a store that produces no file is a failure rather than a hope, and a stored
file is only accepted when it decodes to a stream. The caller and the dialog are injected, so all of that is testable
without an instrument.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CycleRoutines:
    """The three routine addresses and the object this instance's primed form is at.

    The addresses come from the machine-local table; ``form`` comes from observing the application — a recorded value is
    stale for a different instance by construction, so it is carried explicitly rather than remembered anywhere.
    """

    record: int
    store: int
    form: int


class RoutineCaller(Protocol):
    """Execute one routine call inside the application and report whether it ran."""

    def __call__(self, address: int, form: int) -> dict: ...


class StoreDialog(Protocol):
    """Name the block a store just raised a dialog for, and commit it."""

    def commit(self, name: str) -> bool: ...


class Decoder(Protocol):
    """What counts as a stored recording: a file that decodes to at least one stream."""

    def __call__(self, path: Path) -> int: ...


@dataclass
class CycleReport:
    """What the cycle did, so a caller can report evidence rather than an inference."""

    name: str
    recorded: bool = False
    stopped: bool = False
    store_requested: bool = False
    dialog_committed: bool = False
    stored: bool = False
    streams: int = 0
    reason: str | None = None


def _default_decoder(path: Path) -> int:
    """Count the streams a stored block decodes to, using the repository's own reader."""
    from udv_echo_process.io.dop import bdd

    bundle = bdd.read(path)
    return len(getattr(bundle.recording, "streams", []) or [])


class RoutineCycle:
    """Record, stop and store through the application's own routines, then commit its dialog.

    ``duration_s`` is the recording window: the stop call is issued after it, because the application has no "record for
    N seconds" command. A failed routine call does not raise — it stops the cycle and returns the reason, because a caller
    that has to unwind mid-cycle needs the state, not an exception it cannot see.
    """

    def __init__(
        self,
        *,
        caller: RoutineCaller,
        routines: CycleRoutines,
        dialog: StoreDialog,
        decode: Decoder | None = None,
        stop_settle_s: float = 1.5,
        store_settle_s: float = 1.5,
        store_timeout_s: float = 30.0,
        poll_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._caller = caller
        self._routines = routines
        self._dialog = dialog
        self._decode = decode or _default_decoder
        self._stop_settle_s = stop_settle_s
        self._store_settle_s = store_settle_s
        self._store_timeout_s = store_timeout_s
        self._poll_s = poll_s
        self._sleep = sleep

    def _call(self, address: int) -> dict:
        return self._caller(address, self._routines.form)

    def try_record_and_store(
        self, name: str, duration_s: float, directory: Path, *, expected_mode: object = None
    ) -> tuple[bool, Path | str]:
        """Run one cycle. Returns the stored path, or a reason prefixed so a caller can tell the stages apart."""
        directory = Path(directory)
        target = directory / f"{name}.BDD"
        if target.exists():
            # A taken name raises the application's overwrite warning, and an unanswered warning wedges the run.
            return False, f"store_name_taken:{target.name}"
        report = CycleReport(name=name)

        result = self._call(self._routines.record)
        if not result.get("ok"):
            report.reason = f"record_not_dispatched:{_reason(result)}"
            return False, report.reason
        report.recorded = True

        self._sleep(float(duration_s))

        result = self._call(self._routines.record)  # record and stop are the same handler
        if not result.get("ok"):
            report.reason = f"stop_not_dispatched:{_reason(result)}"
            return False, report.reason
        report.stopped = True
        self._sleep(self._stop_settle_s)

        result = self._call(self._routines.store)
        if not result.get("ok"):
            report.reason = f"store_not_dispatched:{_reason(result)}"
            return False, report.reason
        report.store_requested = True
        self._sleep(self._store_settle_s)

        if not self._dialog.commit(name):
            report.reason = "store_dialog_not_committed"
            return False, report.reason
        report.dialog_committed = True

        # The file is the application's own evidence; wait for it rather than assuming the commit wrote it.
        waited = 0.0
        while waited < self._store_timeout_s:
            if target.is_file() and target.stat().st_size > 0:
                break
            self._sleep(self._poll_s)
            waited += self._poll_s
        if not target.is_file():
            report.reason = f"store_file_missing:{target.name}"
            return False, report.reason

        try:
            streams = int(self._decode(target))
        except Exception as exc:  # noqa: BLE001 - an undecodable block is a failed store, not a crash
            report.reason = f"store_undecodable:{type(exc).__name__}"
            return False, report.reason
        report.streams = streams
        if streams < 1:
            report.reason = "store_decoded_no_streams"
            return False, report.reason

        report.stored = True
        return True, target


def _reason(result: dict) -> str:
    errors = result.get("errors") or []
    if errors:
        return str(errors[0])
    return str(result.get("status") or "unknown")
