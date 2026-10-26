"""The host half of the guarded cycle: a producer contract, one bounded session, and the factory.

Import-safe everywhere and address-free by construction: this package knows what a producer must
state and how a session is bounded, and nothing about a process, a pointer or a build. The machine
local half implements :class:`~bridge_host.contract.ProducerChannel`; the config beside the
machine-local table says where it lives.

Public surface, and nothing else is promised:

- :func:`~bridge_host.api.guarded_cycle` — the ``guarded_cycle`` export the run's host module must
  provide (signature fixed by ``docs/dop3000/guarded-cycle-contract.md``);
- :func:`~bridge_host.api.activation_report` — the passive preflight;
- the contract types, the session and the caller, for a host module that composes its own command.
"""

from __future__ import annotations

from bridge_host.api import (
    ActivationCheck,
    ActivationReport,
    HostConfig,
    HostRefusal,
    activation_report,
    bounds_from,
    close_host_sessions,
    guarded_cycle,
    new_session,
)
from bridge_host.caller import SessionCaller
from bridge_host.config import ProducerCommand, host_config_path, load_host_config
from bridge_host.contract import (
    DispatchReceipt,
    ProbeReport,
    ProducerChannel,
    SessionDescriptor,
)
from bridge_host.producer import FileProtocolChannel
from bridge_host.readers import SessionIdentityReader, SessionOwnerCheck
from bridge_host.session import OPERATIONS, BoundedSession

__all__ = [
    "OPERATIONS",
    "ActivationCheck",
    "ActivationReport",
    "BoundedSession",
    "DispatchReceipt",
    "FileProtocolChannel",
    "HostConfig",
    "HostRefusal",
    "ProbeReport",
    "ProducerChannel",
    "ProducerCommand",
    "SessionCaller",
    "SessionDescriptor",
    "SessionIdentityReader",
    "SessionOwnerCheck",
    "activation_report",
    "bounds_from",
    "close_host_sessions",
    "guarded_cycle",
    "host_config_path",
    "load_host_config",
    "new_session",
]
