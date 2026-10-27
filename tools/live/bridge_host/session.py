"""One session, bounded, with the order of a recording written down where it cannot drift.

The cycle dispatches `record`, then `stop`, then `store` — and the first two are the **same**
handler address seen in two states, so an address alone cannot say which one is meant. The session
is where that becomes unambiguous: it counts the operations, refuses one out of order, and gives
every request a sequence number so a receipt can only answer the request that produced it. The one
other sequence it can be opened for is `store` alone (:data:`STORE_ONLY`), which is the
store-completed path: a session that cannot name `record` cannot start an acquisition, whatever its
caller asks for.

Three rules it enforces, each of which is a way a live run goes wrong:

- **A refused or un-consumed command is still spent.** The cycle never retries, and a session that
  let a second `record` follow a failed one would start a recording nobody asked for.
- **A dispatch the application's loop never consumed is not a dispatch.** `ok` says the producer
  ran its stub; `consumed_target` says the application's own `DispatchMessage` reached it.
- **A session is bounded in time, not only in steps.** A producer that stops answering must cost a
  refused point, not a hung run, so every call is deadline-checked against the session's budget.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Self

from bridge_host.contract import (
    DispatchReceipt,
    HostRefusal,
    ProbeReport,
    ProducerChannel,
    SessionDescriptor,
)

__all__ = ["OPERATIONS", "OPERATION_SEQUENCES", "STORE_ONLY", "BoundedSession"]

#: The cycle's whole repertoire, in the only order it may happen in.
OPERATIONS = ("record", "stop", "store")

#: The closed set of sequences a session may be opened for — two entries, not a parameter.
#:
#: A session that could run an arbitrary subsequence could store a block nothing had completed, or
#: record after a store.  ``store`` alone is the store-completed path: the application finished that
#: block itself, so the session that carries it must be unable to start, end or reset an acquisition,
#: and that inability is a property of the session rather than a promise made by its caller.
OPERATION_SEQUENCES: dict[str, tuple[str, ...]] = {
    "record_stop_store": OPERATIONS,
    "store": ("store",),
}

#: The store-completed sequence, named once so a caller cannot spell it differently.
STORE_ONLY = OPERATION_SEQUENCES["store"]


class BoundedSession:
    """One producer attachment, used once, in the cycle's order, inside its budget."""

    def __init__(
        self,
        channel: ProducerChannel,
        *,
        start_timeout_s: float = 90.0,
        dispatch_timeout_s: float = 60.0,
        probe_timeout_s: float = 20.0,
        close_timeout_s: float = 5.0,
        total_budget_s: float = 600.0,
        sequence: str = "record_stop_store",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._channel = channel
        self._start_timeout_s = float(start_timeout_s)
        self._dispatch_timeout_s = float(dispatch_timeout_s)
        self._probe_timeout_s = float(probe_timeout_s)
        self._close_timeout_s = float(close_timeout_s)
        self._total_budget_s = float(total_budget_s)
        #: The closed sequence this session may run, resolved here so a typo cannot become a mode.
        operations = OPERATION_SEQUENCES.get(str(sequence))
        if operations is None:
            raise HostRefusal(f"host_sequence_unknown:{sequence}")
        self._operations = operations
        self._clock = clock
        self._descriptor: SessionDescriptor | None = None
        self._deadline: float | None = None
        self._closed = False
        self._sequence = 0
        self._dispatched: list[str] = []
        #: Why the last close could not be completed, if it could not. Never raised: an exit path
        #: that throws hides the reason the caller was leaving in the first place.
        self.close_problem: str | None = None

    # -- reads ------------------------------------------------------------
    @property
    def descriptor(self) -> SessionDescriptor | None:
        """What the producer stated when it started, or ``None`` before that."""
        return self._descriptor

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has run — the session is never reopened."""
        return self._closed

    @property
    def dispatched(self) -> tuple[str, ...]:
        """The operations this session dispatched, in order, refused or not."""
        return tuple(self._dispatched)

    @property
    def operations(self) -> tuple[str, ...]:
        """The sequence this session was opened for — a dispatch outside it is refused, not coerced."""
        return self._operations

    # -- lifecycle --------------------------------------------------------
    def start(self) -> SessionDescriptor:
        """Attach once and keep what the producer observed; a second call is a refusal."""
        if self._closed:
            raise HostRefusal("host_session_closed")
        if self._descriptor is not None:
            raise HostRefusal("host_session_started")
        try:
            descriptor = self._channel.start(
                session_dir=getattr(self._channel, "session_dir", None),
                timeout_s=self._start_timeout_s,
            )
        except HostRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 - a producer that cannot start is a refusal
            raise HostRefusal(
                f"host_session_start_failed:{type(exc).__name__}"
            ) from None
        if not isinstance(descriptor, SessionDescriptor):
            raise HostRefusal(f"host_session_start_failed:{type(descriptor).__name__}")
        self._descriptor = descriptor
        self._deadline = self._clock() + self._total_budget_s
        return descriptor

    def close(self) -> None:
        """End the attachment, once, whatever state the cycle got to."""
        if self._closed:
            return
        self._closed = True
        try:
            self._channel.close(timeout_s=self._close_timeout_s)
        except Exception as exc:  # noqa: BLE001 - reported beside the exit, never raised from it
            self.close_problem = type(exc).__name__

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- work -------------------------------------------------------------
    def dispatch(self, operation: str, *, address: int, form: int) -> DispatchReceipt:
        """Dispatch one operation, reading the producer's answer strictly.

        A refusal the producer *stated* (`ok: False`) is returned rather than raised: the cycle turns
        it into a named stage refusal, and raising would erase which stage it happened at. Everything
        that makes the answer unusable — a missing receipt, another operation's receipt, a command the
        loop never consumed — raises, because none of those is a possibility the cycle can report.
        """
        self._usable()
        if operation not in OPERATIONS:
            raise HostRefusal(f"host_operation_not_allowlisted:{operation}")
        if operation not in self._operations:
            # Named apart from "out of order": this operation is never part of this session's sequence,
            # so it is refused before it could be counted as a step.
            raise HostRefusal(f"host_operation_not_in_sequence:{operation}")
        if len(self._dispatched) >= len(self._operations):
            raise HostRefusal(f"host_operation_out_of_order:{operation}")
        expected = self._operations[len(self._dispatched)]
        if operation != expected:
            raise HostRefusal(f"host_operation_out_of_order:{operation}")
        sequence = self._next_sequence()
        try:
            receipt = self._channel.dispatch(
                operation=operation,
                address=int(address),
                form=int(form),
                sequence=sequence,
                timeout_s=self._dispatch_timeout_s,
            )
        except HostRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 - a channel that raised did not dispatch
            raise HostRefusal(
                f"host_dispatch_failed:{operation}:{type(exc).__name__}"
            ) from None
        if not isinstance(receipt, DispatchReceipt):
            raise HostRefusal(f"host_dispatch_receipt_invalid:{type(receipt).__name__}")
        if receipt.operation != operation:
            raise HostRefusal(
                f"host_dispatch_receipt_invalid:operation:{receipt.operation}!={operation}"
            )
        if receipt.ok is True and receipt.consumed_target is not True:
            raise HostRefusal(f"host_dispatch_not_consumed:{operation}")
        self._dispatched.append(operation)
        return receipt

    def probe(self) -> ProbeReport:
        """Take one live reading for a guard — never cached, because a cached pass is not a check."""
        self._usable()
        sequence = self._next_sequence()
        try:
            report = self._channel.probe(
                sequence=sequence, timeout_s=self._probe_timeout_s
            )
        except HostRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 - a reading that failed refused nothing
            raise HostRefusal(f"host_probe_failed:{type(exc).__name__}") from None
        if not isinstance(report, ProbeReport):
            raise HostRefusal(f"host_probe_invalid:{type(report).__name__}")
        return report

    # -- internals --------------------------------------------------------
    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _usable(self) -> None:
        """Refuse a closed, unstarted or expired session — in that order, because the reasons differ."""
        if self._closed:
            raise HostRefusal("host_session_closed")
        if self._descriptor is None or self._deadline is None:
            raise HostRefusal("host_session_not_started")
        if self._clock() >= self._deadline:
            raise HostRefusal("host_session_expired")
