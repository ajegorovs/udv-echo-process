"""Address → operation: the one place the table's handlers become the cycle's three commands.

`RoutineCycle` calls its `RoutineCaller` with an address and the owning object, and expects a report
whose ``ok`` is exactly true or false. This adapter answers that shape from the table and the session:

- the store handler is the `store` operation;
- **the record handler is both `record` and `stop`** — the application has one handler seen in two
  states — so the first call to that address is the start and the second is the stop. A third is
  refused: a cycle that asked for a third recording has lost track of the strip, and guessing would
  start one nobody asked for;
- anything else is refused without a dispatch. An address nobody put in the table is not an address
  this route may call.

Refusals travel as ``{"ok": False, "errors": [...]}`` rather than exceptions: the cycle turns that
into a *named stage* refusal including the reason, while a raised exception is reported as the stage
plus an exception type and loses the producer's own words.
"""

from __future__ import annotations

from bridge_host.contract import HostRefusal
from bridge_host.session import BoundedSession
from udv_echo_process.acquire.bridge import BridgeTable

__all__ = ["SessionCaller"]


def _refused(reason: str) -> dict:
    return {"ok": False, "errors": [reason]}


class SessionCaller:
    """The cycle's `RoutineCaller` over one bounded session and the run's own table."""

    def __init__(self, session: BoundedSession, table: BridgeTable) -> None:
        self._session = session
        # Read once at construction: the table is frozen and validated, so a missing operation raises
        # here rather than three stages into a recording.
        self._record_address = table.operation("record").handler
        self._store_address = table.operation("store").handler
        #: How many times this caller has issued the record/stop address — the cycle's own order.
        self._record_calls = 0

    def __call__(self, address: int, form: int) -> dict:
        """Dispatch the operation ``address`` names, or refuse it with a reason."""
        address = int(address)
        if address == self._store_address:
            return self._dispatch("store", address, form)
        if address == self._record_address:
            if self._record_calls >= 2:
                return _refused("host_record_repeated")
            operation = "record" if self._record_calls == 0 else "stop"
            # Counted before the attempt: a failed dispatch is spent, and the cycle never retries, so
            # a second start must not become possible because the first one failed.
            self._record_calls += 1
            return self._dispatch(operation, address, form)
        return _refused(f"host_address_not_allowlisted:0x{address:x}")

    def _dispatch(self, operation: str, address: int, form: int) -> dict:
        try:
            receipt = self._session.dispatch(operation, address=address, form=form)
        except HostRefusal as refusal:
            return _refused(str(refusal))
        if receipt.ok is True:
            return {"ok": True}
        return {
            "ok": False,
            "errors": list(receipt.errors) or [f"host_dispatch_refused:{operation}"],
        }
