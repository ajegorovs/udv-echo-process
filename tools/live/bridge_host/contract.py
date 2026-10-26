"""What a producer must state, and what the host may therefore believe.

This module is the whole interface between the tracked integration and the machine-local half that
actually attaches to the application. It exists because the two facts that made the 2026-10-23
sitting work are *observations* — which object the strip's routines belong to, and which build the
addresses were resolved in — and an observation is only usable if the thing that took it says so.

Three consequences are built into the types below rather than left to prose.

**A dispatch is not a dispatch until the application's own loop consumed it.** The producer posts a
registered window message and the application's message loop reaches its own `DispatchMessage`; a
receipt that says ``ok`` but not ``consumed_target`` describes a message we handed to a loop, not a
command that ran. :attr:`DispatchReceipt.consumed_target` is what the session checks.

**An identity is three values, not one.** A pid is reused by the operating system, so ``pid`` plus
``created_ns`` plus the build digest is the smallest set that can say "the same process instance,
still that build". Anything weaker is a guess with a receipt attached.

**A guard that did not answer yes-or-no is not a pass.** :class:`ProbeReport` carries the raw
answer, and the owner check passes it through unchanged so the cycle can call it what it is —
malformed evidence — instead of a truthy string silently becoming consent.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from udv_echo_process.acquire.cycle import ProcessIdentity
from udv_echo_process.models.base import ValueModel

__all__ = [
    "CLOSE_FILE",
    "HOST_CONFIG_SCHEMA",
    "REQUEST_FILE",
    "SESSION_READY_FILE",
    "DispatchReceipt",
    "HostRefusal",
    "ProbeReport",
    "ProducerChannel",
    "SessionDescriptor",
    "receipt_name",
]

#: The host config's schema id. A table and its host config travel together; the id is what stops a
#: config written for another layout from being read as if it were this one.
HOST_CONFIG_SCHEMA = "bridge-host/1"

#: The three files of the producer protocol, all inside the session directory.
SESSION_READY_FILE = "session-ready.json"
REQUEST_FILE = "request.json"
CLOSE_FILE = "close.json"


def receipt_name(sequence: int) -> str:
    """The receipt file one request is answered in — numbered, so two requests cannot share one."""
    return f"receipt-{int(sequence)}.json"


class HostRefusal(RuntimeError):
    """A refusal from the host half, with a reason from a fixed vocabulary.

    The reasons are the interface: ``host_config_missing``, ``host_session_expired``,
    ``host_dispatch_not_consumed`` and the rest each name a *different* next step, and a caller that
    logs them can tell an unconfigured machine from a stale binding without reading a traceback.
    """


class SessionDescriptor(ValueModel):
    """What the producer states once it is attached and has observed the application.

    Every field is an observation the producer took on the instance it is attached to **now**: the
    identity of that instance, the owning object it resolved, and the two handler addresses it will
    call. The host compares them with the machine-local table and refuses a disagreement rather
    than substituting either value.
    """

    identity: ProcessIdentity
    #: The owning object the strip's routines are called with, as the producer observed it.
    owner: int = Field(ge=0)
    #: How that object was obtained. Required: an observation without a stated source is a guess.
    owner_source: str = Field(min_length=1)
    #: The handler the producer resolved for record/stop, and the one for store.
    record_handler: int = Field(ge=0)
    store_handler: int = Field(ge=0)
    #: The registered window message the producer consumes its commands on.
    message_name: str = Field(min_length=1)


class DispatchReceipt(ValueModel):
    """One command's answer, from the producer that consumed it.

    ``ok`` is a real boolean: a truthy stand-in says nothing about what happened. ``consumed_target``
    is the loop-consumption proof — a command posted to a window that never dispatched it is a
    message, not a recording.
    """

    ok: bool
    operation: str
    consumed_target: bool = False
    errors: tuple[str, ...] = ()
    detail: str | None = None


class ProbeReport(ValueModel):
    """One live reading of the things a guard asks about, taken now and not remembered.

    ``owner_ok`` keeps its raw answer on purpose: ``None`` (no answer), a string, or a number is
    *malformed evidence* and reaches the cycle as such. Only ``True`` is a pass.
    """

    identity: ProcessIdentity | None = None
    owner_ok: object = None
    #: The pointer the producer actually re-validated, so a check of another pointer is refused.
    owner: int | None = Field(default=None, ge=0)
    reason: str | None = None


class ProducerChannel(Protocol):
    """The machine-local half: one attachment, commands consumed by the application's own loop.

    Implementations own the process they talk to and may not widen this interface: the session above
    them is what enforces ordering, bounds and cleanup, and a channel that also decided *whether* to
    dispatch would put a second policy beside it.
    """

    def start(self, *, session_dir: object, timeout_s: float) -> SessionDescriptor: ...

    def dispatch(
        self,
        *,
        operation: str,
        address: int,
        form: int,
        sequence: int,
        timeout_s: float,
    ) -> DispatchReceipt: ...

    def probe(self, *, sequence: int, timeout_s: float) -> ProbeReport: ...

    def close(self, *, timeout_s: float) -> None: ...
