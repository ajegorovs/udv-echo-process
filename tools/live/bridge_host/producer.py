"""The tracked half of the producer protocol: a session directory, requests out, receipts in.

The demonstrated producer owns the attachment; this channel owns the conversation with it. The
protocol is deliberately small and file-based, because that is what the measured design already is —
the 2026-10-23 sitting drove the application through a registered window message and read its own
progress from JSON files (`session-ready`, `record-dispatched`, `record-stopped`,
`store-dispatched`) written by the process that did the work. Nothing here replaces that
instrumentation: it names the same events as a request/receipt pair so a tracked, address-free
adapter can drive it.

The conventions, in full — a producer that implements these is complete:

1. It is started as ``argv + [<session directory>]``; that path is its only positional argument.
2. On attach it writes ``session-ready.json`` with ``identity`` (pid, created stamp, build digest),
   ``owner``, ``owner_source``, ``record_handler``, ``store_handler`` and ``message_name``.
3. Each ``request.json`` it finds carries ``sequence``, ``operation`` and, for a dispatch,
   ``address`` and ``form``. It answers in ``receipt-<sequence>.json`` and **removes the request**.
4. A dispatch receipt states ``ok``, ``operation``, ``consumed_target`` and any ``errors``; a probe
   receipt states ``identity``, ``owner_ok`` and ``owner``.
5. ``close.json`` asks it to exit; it must exit on its own, and this channel only terminates it if it
   does not. It may also carry its own deadline — the session's budget is the outer bound either way.

**What a timeout means.** Every wait here is bounded and every bound names the file it waited for.
A producer that stops answering costs a refused point with a reason, never a hung run.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from bridge_host.config import ProducerCommand
from bridge_host.contract import (
    CLOSE_FILE,
    REQUEST_FILE,
    SESSION_READY_FILE,
    DispatchReceipt,
    HostRefusal,
    ProbeReport,
    SessionDescriptor,
    receipt_name,
)

__all__ = ["FileProtocolChannel"]


class FileProtocolChannel:
    """One producer process, one session directory, bounded waits, cleaned up on close."""

    def __init__(
        self,
        command: ProducerCommand,
        *,
        session_dir: Path | str,
        poll_s: float = 0.02,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        spawn: Callable[..., object] = subprocess.Popen,
    ) -> None:
        self._command = command
        self.session_dir = Path(session_dir)
        self._poll_s = float(poll_s)
        self._sleep = sleep
        self._clock = clock
        self._spawn = spawn
        self._process: object | None = None
        #: Why the last close could not complete cleanly, or ``None``.
        self.close_problem: str | None = None

    # -- reads ------------------------------------------------------------
    @property
    def process(self) -> object | None:
        """The producer child, or ``None`` before :meth:`start`."""
        return self._process

    # -- lifecycle --------------------------------------------------------
    def start(
        self, *, session_dir: object = None, timeout_s: float
    ) -> SessionDescriptor:
        """Spawn the producer and read what it observed, or refuse by name."""
        if session_dir is not None:
            self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        stderr = (self.session_dir / "producer-stderr.log").open("w", encoding="utf-8")
        stdout = (self.session_dir / "producer-stdout.log").open("w", encoding="utf-8")
        argv = [*self._command.argv, str(self.session_dir)]
        cwd = None if self._command.cwd is None else str(self._command.cwd)
        try:
            self._process = self._spawn(
                argv, cwd=cwd, stdout=stdout, stderr=stderr, close_fds=True
            )
        except Exception as exc:  # noqa: BLE001 - a producer that cannot start is a refusal
            stdout.close()
            stderr.close()
            raise HostRefusal(
                f"host_producer_unstartable:{type(exc).__name__}"
            ) from None
        payload = self._await_file(
            self.session_dir / SESSION_READY_FILE,
            timeout_s=timeout_s,
            on_timeout="host_session_start_timeout",
        )
        try:
            return SessionDescriptor.model_validate(payload)
        except ValidationError as exc:
            raise HostRefusal(
                f"host_session_ready_invalid:{_first_error(exc)}"
            ) from None

    def close(self, *, timeout_s: float) -> None:
        """Ask the producer to leave, and make sure it did.

        Both failures here are recorded rather than raised: this runs on the way out of a refused
        point, and an exception from the exit path would replace the reason the caller was leaving.
        """
        process = self._process
        if process is None:
            return
        try:
            self._write(self.session_dir / CLOSE_FILE, {"close": True})
        except OSError as exc:
            self.close_problem = f"host_close_request_unwritable:{type(exc).__name__}"
        try:
            code = process.wait(timeout=max(0.0, float(timeout_s)))  # type: ignore[attr-defined]
            if code != 0 and self.close_problem is None:
                self.close_problem = f"host_producer_close_exit:{code}"
            return
        except Exception:  # noqa: BLE001 - a child that ignored the request is terminated
            self.close_problem = "host_producer_did_not_exit"
        try:
            process.terminate()  # type: ignore[attr-defined]
            process.wait(timeout=max(1.0, float(timeout_s)))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - the caller's own bound reports it
            self.close_problem = f"host_producer_unreaped:{type(exc).__name__}"

    # -- work -------------------------------------------------------------
    def dispatch(
        self,
        *,
        operation: str,
        address: int,
        form: int,
        sequence: int,
        timeout_s: float,
    ) -> DispatchReceipt:
        """Ask for one command and wait for the receipt that says the loop consumed it."""
        self._write(
            self.session_dir / REQUEST_FILE,
            {
                "sequence": int(sequence),
                "operation": operation,
                "address": int(address),
                "form": int(form),
            },
        )
        payload = self._await_file(
            self.session_dir / receipt_name(sequence),
            timeout_s=timeout_s,
            on_timeout=f"host_dispatch_timeout:{operation}",
        )
        try:
            return DispatchReceipt.model_validate(payload)
        except ValidationError as exc:
            raise HostRefusal(
                f"host_dispatch_receipt_invalid:{_first_error(exc)}"
            ) from None

    def probe(self, *, sequence: int, timeout_s: float) -> ProbeReport:
        """Ask for one live reading — identity, owner validity, the pointer that answered."""
        self._write(
            self.session_dir / REQUEST_FILE,
            {"sequence": int(sequence), "operation": "probe"},
        )
        payload = self._await_file(
            self.session_dir / receipt_name(sequence),
            timeout_s=timeout_s,
            on_timeout="host_probe_timeout",
        )
        try:
            return ProbeReport.model_validate(payload)
        except ValidationError as exc:
            raise HostRefusal(
                f"host_probe_receipt_invalid:{_first_error(exc)}"
            ) from None

    # -- internals --------------------------------------------------------
    def _write(self, path: Path, payload: dict) -> None:
        """Write one request atomically, so a reader never sees half a message."""
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, path)

    def _await_file(self, path: Path, *, timeout_s: float, on_timeout: str) -> dict:
        """Wait for one answer, bounded, and name what was waited for when it never arrives."""
        deadline = self._clock() + max(0.0, float(timeout_s))
        while True:
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise HostRefusal(
                        f"host_receipt_unreadable:{path.name}:{type(exc).__name__}"
                    ) from None
            process = self._process
            if process is not None:
                code = process.poll()  # type: ignore[attr-defined]
                if code is not None:
                    raise HostRefusal(f"host_producer_exited:{code}")
            if self._clock() >= deadline:
                raise HostRefusal(f"{on_timeout}:{path.name}")
            self._sleep(self._poll_s)


def _first_error(exc: ValidationError) -> str:
    """The first field a malformed payload got wrong — enough to name, short enough to log."""
    errors = exc.errors()
    if not errors:
        return "invalid"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ())) or "payload"
    return f"{location}:{first.get('type', 'invalid')}"
