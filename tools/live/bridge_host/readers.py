"""The cycle's three guards, answered by fresh readings through the session.

`RoutineCycle` asks three questions before every dispatch and once more before it commits a store:
is this still the instance the binding was taken on, is the owning object still readable, and what
does the strip show. Each one here is a **live read**, never a memo:

- :class:`SessionIdentityReader` asks the producer for the identity every time it is called. A
  cached identity would pass the check that exists because a restart invalidates everything.
- :class:`SessionOwnerCheck` refuses a pointer other than the one it was built for, without asking
  the producer anything — validating a proxy for another object is how a stale pointer gets used.
  It returns the producer's raw answer, so a truthy non-boolean reaches the cycle as malformed
  evidence (`cycle_owner_evidence_invalid`) instead of being coerced into consent.
- the strip is read through the actuator the host already holds, because the strip is a window read
  and has nothing to do with the process being attached.

A guard that raises is not a crash path: `RoutineCycle` catches it and names the failure
(`cycle_identity_unavailable`, `cycle_owner_unreadable`), which is why nothing here swallows an error
into a ``False``.
"""

from __future__ import annotations

from bridge_host.session import BoundedSession
from udv_echo_process.acquire.cycle import ProcessIdentity

__all__ = ["SessionIdentityReader", "SessionOwnerCheck"]


class SessionIdentityReader:
    """`IdentityReader`: the live instance's pid, creation stamp and build digest, read now."""

    def __init__(self, session: BoundedSession) -> None:
        self._session = session

    def __call__(self) -> ProcessIdentity | None:
        """One reading. ``None`` when the producer could not state one — which the cycle refuses."""
        return self._session.probe().identity


class SessionOwnerCheck:
    """`OwnerCheck`: is *this* pointer still a readable object in the live application?"""

    def __init__(self, session: BoundedSession, owner: int) -> None:
        self._session = session
        self._owner = int(owner)

    def __call__(self, owner: int) -> object:
        """Answer for the bound pointer only, passing the producer's own answer through unchanged."""
        if int(owner) != self._owner:
            # A different pointer is not validated by proxy: nothing observed it, so nothing may pass
            # it. This is the stale-pointer hazard, refused rather than tested.
            return False
        report = self._session.probe()
        if report.owner is not None and int(report.owner) != self._owner:
            return False
        return report.owner_ok
