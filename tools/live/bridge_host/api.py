"""The host factory: what ``--route bridge --bridge-guarded-cycle`` calls, built from live reads.

`guarded_cycle_from` in the package resolves one optional export on the module named by
``--bridge-runner`` and checks what it gets back. This is that export's implementation for the
demonstrated producer: it loads the host config beside the table, starts **one** bounded session,
takes the binding from what the producer observed on the instance it is attached to, compares that
with the table, and hands the package a fully bound :class:`~udv_echo_process.acquire.cycle.RoutineCycle`.

Four decisions, each because the alternative is a silently wrong recording:

- **A disagreement is a refusal, never a substitution.** If the producer resolved a different build or
  a different handler than the table names, the run stops with ``host_build_mismatch`` /
  ``host_routine_conflict`` — before anything records. A table that no longer matches the application
  is exactly the case a binding exists to catch.
- **A binding must be observed.** ``owner: 0`` is refused as ``host_owner_not_observed``: an unowned
  pointer is the access violation the guarded cycle's identity checks exist to prevent.
- **The factory may observe, and does; it may not dispatch.** Starting the session attaches and
  reads. Nothing here starts, stops or stores a recording, so a command that later refuses has still
  mutated nothing.
- **One session, closed on the way out.** A refusal after the session started closes it; the budget
  bounds the process; :func:`close_host_sessions` runs at interpreter exit so nothing survives the
  command.

**What this does not prove.** No test here touches the application: the producer is a protocol, and a
producer that answers it is not the instrument. Live activation, the store dialog's press and the
stored block remain to be measured on the machine.
"""

from __future__ import annotations

import atexit
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from bridge_host.caller import SessionCaller
from bridge_host.config import (
    HostConfig,
    ProducerCommand,
    host_config_path,
    load_host_config,
)
from bridge_host.contract import HostRefusal, ProducerChannel, SessionDescriptor
from bridge_host.producer import FileProtocolChannel
from bridge_host.readers import SessionIdentityReader, SessionOwnerCheck
from bridge_host.session import BoundedSession
from udv_echo_process.acquire.bridge import BridgeTable, BridgeUnavailable
from udv_echo_process.acquire.cycle import (
    CycleBinding,
    CycleReport,
    CycleRoutines,
    CycleStage,
    ObservedAddress,
    RoutineCycle,
)
from udv_echo_process.acquire.udop.store import StoreDialogCommit
from udv_echo_process.models.base import ValueModel

__all__ = [
    "ActivationCheck",
    "ActivationReport",
    "BoundRoutineCycle",
    "BoundStoreCompletedCycle",
    "FileProtocolChannel",
    "HostConfig",
    "HostRefusal",
    "ProducerCommand",
    "activation_report",
    "bounds_from",
    "close_host_sessions",
    "guarded_cycle",
    "new_session",
    "store_completed_cycle",
]

#: Every session this process opened. Closed at exit; a command opens at most one.
_LIVE_SESSIONS: list[BoundedSession] = []


class ActivationCheck(ValueModel):
    """One preflight question and its answer — including the answer "could not ask"."""

    name: str = Field(min_length=1)
    ok: bool
    detail: str | None = None


class ActivationReport(ValueModel):
    """A passive preflight: what the host would do, and what it observed, before any recording."""

    ready: bool
    checks: tuple[ActivationCheck, ...] = ()
    config_path: str | None = None
    identity: object = None
    owner: int | None = Field(default=None, ge=0)
    strip_view: str | None = None
    session_closed: bool = True
    session_close_problem: str | None = None

    def failed(self) -> tuple[str, ...]:
        """The names of the checks that were not satisfied."""
        return tuple(check.name for check in self.checks if not check.ok)


def bounds_from(config: HostConfig) -> dict:
    """The session's bounds, taken from the host config — one vocabulary, not two."""
    return {
        "start_timeout_s": config.start_timeout_s,
        "dispatch_timeout_s": config.dispatch_timeout_s,
        "probe_timeout_s": config.probe_timeout_s,
        "close_timeout_s": config.close_timeout_s,
        "total_budget_s": config.total_budget_s,
    }


def new_session(
    channel: ProducerChannel, *, sequence: str = "record_stop_store", **bounds: object
) -> BoundedSession:
    """A bounded session over ``channel`` — the one constructor the factory and the preflight share.

    ``sequence`` is the closed operation sequence the session may run; it defaults to the cycle the
    package has always driven, so every existing caller is unchanged.
    """
    return BoundedSession(channel, sequence=sequence, **bounds)  # type: ignore[arg-type]


def _channel_for(config: HostConfig, session_dir: Path) -> ProducerChannel:
    """The machine-local producer, described by the config and located by its own argv."""
    command = config.producer
    if command is None:
        raise HostRefusal("host_producer_missing")
    return FileProtocolChannel(command, session_dir=session_dir)


def _new_actuator(channel_number: int | None) -> object:
    """The GUI surface the store dialog is committed through — imported only when it is needed."""
    try:
        from udv_echo_process.acquire.driver import Win32Actuator
    except Exception as exc:  # noqa: BLE001 - a host without the platform surface is a refusal
        raise HostRefusal(f"host_actuator_unavailable:{type(exc).__name__}") from None
    return Win32Actuator(channel=channel_number)


def _new_session_dir() -> Path:
    """A fresh directory for one session's protocol files; kept afterwards as evidence."""
    return Path(tempfile.mkdtemp(prefix="udv-bridge-host-"))


def close_host_sessions() -> None:
    """Close every session this process opened. Idempotent, and never raises."""
    for session in _LIVE_SESSIONS:
        session.close()


atexit.register(close_host_sessions)


def _table_operations(table: BridgeTable) -> tuple[tuple[str, int], ...]:
    """The three operations' handler addresses, refusing a table that cannot carry the cycle."""
    found: list[tuple[str, int]] = []
    for name in ("record", "stop", "store"):
        operation = table.operation(name)
        if operation.handler == 0:
            raise HostRefusal(f"host_table_operation_null:{name}")
        found.append((name, operation.handler))
    return tuple(found)


def _descriptor_problem(
    table: BridgeTable, descriptor: SessionDescriptor
) -> str | None:
    """Compare what the producer observed with what the table declares — the binding's whole point."""
    if descriptor.identity.image_sha256 != table.image_sha256:
        return (
            "host_build_mismatch:binding:"
            f"{descriptor.identity.image_sha256[:12]}!={table.image_sha256[:12]}"
        )
    if descriptor.owner == 0:
        return "host_owner_not_observed"
    if descriptor.record_handler != table.operation("record").handler:
        return (
            f"host_routine_conflict:record:0x{descriptor.record_handler:x}"
            f"!=0x{table.operation('record').handler:x}"
        )
    if descriptor.store_handler != table.operation("store").handler:
        return (
            f"host_routine_conflict:store:0x{descriptor.store_handler:x}"
            f"!=0x{table.operation('store').handler:x}"
        )
    return None


def _binding(
    table: BridgeTable, descriptor: SessionDescriptor
) -> tuple[CycleRoutines, CycleBinding]:
    """The cycle's routines and the binding every dispatch is conditional on."""
    record = table.operation("record").handler
    store = table.operation("store").handler
    routines = CycleRoutines(record=record, store=store, form=descriptor.owner)
    binding = CycleBinding(
        identity=descriptor.identity,
        owner=ObservedAddress(address=descriptor.owner, source=descriptor.owner_source),
        record=ObservedAddress(
            address=record,
            source=f"table operation record, resolved 0x{descriptor.record_handler:x} in-process",
        ),
        store=ObservedAddress(
            address=store,
            source=f"table operation store, resolved 0x{descriptor.store_handler:x} in-process",
        ),
    )
    return routines, binding


class BoundRoutineCycle(RoutineCycle):
    """The hardened cycle with one addition: each invocation's directory reaches the dialog adapter.

    ``RoutineCycle`` is built once per command and asked to record several points, and
    ``commit(name)`` receives only a name — so a factory-time directory would be right for the first
    point and silently wrong for the next. This subclass binds the **actual** ``directory`` argument
    into the store adapter immediately before every invocation and then defers to the package's own
    implementation, which is why the cycle protocol itself needs no change and
    ``isinstance(cycle, RoutineCycle)`` still holds for the factory's check.
    """

    def __init__(self, *, store_dialog: StoreDialogCommit, **kwargs: object) -> None:
        super().__init__(dialog=store_dialog, **kwargs)  # type: ignore[arg-type]
        self._store_dialog = store_dialog

    @property
    def store_dialog(self) -> StoreDialogCommit:
        """The adapter a point's directory is bound to — read-only, for a caller's own report."""
        return self._store_dialog

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: object = None,
    ) -> tuple[bool, Path | str]:
        """Bind this point's directory, then run the package's own cycle unchanged."""
        self._store_dialog.bind_directory(Path(directory))
        return super().try_record_and_store(
            name, duration_s, Path(directory), expected_mode=expected_mode
        )


class BoundStoreCompletedCycle(BoundRoutineCycle):
    """The hardened cycle with one addition: the store-completed entry point, and no recording one.

    ``store_completed_block`` binds this invocation's directory for the same reason
    ``try_record_and_store`` does — ``commit(name)`` receives only a name, so a factory-time directory
    would be right for the first block and silently wrong for the next.

    ``try_record_and_store`` is **closed** here, and closed by returning a refusal rather than by
    raising: the cycle's own vocabulary is its output, and this object was built over a session whose
    sequence cannot name ``record`` at all. The refusal exists so a caller that reached for the wrong
    entry point is told which one this is, instead of reading an out-of-order error from the session.
    """

    def store_completed_block(
        self, name: str, directory: Path
    ) -> tuple[bool, Path | str]:
        """Bind this block's directory, then run the package's own store-completed tail unchanged."""
        self._store_dialog.bind_directory(Path(directory))
        return super().store_completed_block(name, Path(directory))

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: object = None,
    ) -> tuple[bool, Path | str]:
        """Refuse: this cycle was built to store a block nothing here recorded.

        The refusal becomes **this invocation's** report. ``last_report`` is read after the call, so a
        success left standing from the previous store would be read as this call's evidence — a stored
        path and a decoded stream count beside a refusal, which is the worst shape a report can take.
        """
        reason = "cycle_store_only:record_and_store_not_permitted"
        self._last_report = CycleReport(
            name=str(name), stage=CycleStage.PREFLIGHT, reason=reason
        )
        return False, reason


def guarded_cycle(
    *,
    table: BridgeTable,
    table_path: str | Path | None,
    target_digest: str | None,
    channel: int | None,
) -> RoutineCycle:
    """The host's ``guarded_cycle`` export, in the factory signature the contract fixes."""
    try:
        return _build_cycle(
            table=table,
            table_path=table_path,
            target_digest=target_digest,
            channel=channel,
        )
    except HostRefusal as refusal:
        # The package passes this vocabulary through unchanged, so the reason a run refused is the
        # host's own words rather than `bridge_guarded_cycle_factory_raised:<Type>`.
        raise BridgeUnavailable(str(refusal)) from None


def store_completed_cycle(
    *,
    table: BridgeTable,
    table_path: str | Path | None,
    target_digest: str | None,
    channel: int | None,
) -> RoutineCycle:
    """The host's store-only entry point: a guarded cycle that can store a held block, and nothing else.

    The same construction as :func:`guarded_cycle` — one observed binding, the table compared against
    what the producer resolved, one bounded session — with the session's closed sequence set to
    ``store`` (:data:`bridge_host.session.STORE_ONLY`). What differs is only what the cycle may do: it
    dispatches the store routine and commits the Store dialog, and every path that could start, stop,
    reset or reconfigure an acquisition is unreachable from it, in the session and in the caller.

    It is deliberately **not** exported under the package's factory name: that name builds a record
    cycle, and a store-only cycle answering it would be a cycle a recording command could run. Refusals
    are raised as :class:`HostRefusal`, unwrapped, because a caller invokes this directly and wants the
    host's own words.
    """
    return _build_cycle(
        table=table,
        table_path=table_path,
        target_digest=target_digest,
        channel=channel,
        sequence="store",
    )


def _build_cycle(
    *,
    table: BridgeTable,
    table_path: str | Path | None,
    target_digest: str | None,
    channel: int | None,
    sequence: str = "record_stop_store",
) -> RoutineCycle:
    """One bound cycle over one session, for the closed ``sequence`` the caller asked for.

    The config beside the table declares the sequence it describes, and the two must agree: a
    store-only entry point pointed at a recording config would open a session against a producer that
    primes a parameter and demands a ready row, which is precisely the work this entry point exists to
    not do. The disagreement is refused before anything attaches.
    """
    if table_path is None:
        # The config is the table's sibling, so a run that did not name its table cannot find one.
        raise HostRefusal("host_config_missing:table-path-not-given")
    config = load_host_config(table_path)
    if config.sequence != sequence:
        raise HostRefusal(f"host_sequence_mismatch:{config.sequence}!={sequence}")
    if target_digest is not None and table.image_sha256 != target_digest:
        raise HostRefusal(
            f"host_build_mismatch:table:{table.image_sha256[:12]}!={target_digest[:12]}"
        )
    if config.producer is None:
        raise HostRefusal("host_producer_missing")
    _table_operations(table)
    store_directory = Path(config.store_directory)
    if not store_directory.is_dir():
        raise HostRefusal(f"host_store_directory_missing:{store_directory}")
    actuator = _new_actuator(channel)
    session = new_session(
        _channel_for(config, _new_session_dir()),
        sequence=sequence,
        **bounds_from(config),
    )
    try:
        descriptor = session.start()
        problem = _descriptor_problem(table, descriptor)
        if problem is not None:
            raise HostRefusal(problem)
        routines, binding = _binding(table, descriptor)
        dialog = StoreDialogCommit(
            actuator,
            # Deliberately unbound: `BoundRoutineCycle` binds each invocation's own directory, so a
            # factory-time path can never be silently reused for the next point.
            directory=None,
            dialog_timeout_s=config.dialog_timeout_s,
            poll_s=config.poll_s or 0.2,
        )
        cycle_class = (
            BoundStoreCompletedCycle if sequence == "store" else BoundRoutineCycle
        )
        cycle = cycle_class(
            caller=SessionCaller(session, table, store_only=(sequence == "store")),
            routines=routines,
            store_dialog=dialog,
            binding=binding,
            identity=SessionIdentityReader(session),
            owner_valid=SessionOwnerCheck(session, descriptor.owner),
            read_strip=actuator.strip_state,  # type: ignore[attr-defined]
            stop_settle_s=config.stop_settle_s,
            store_settle_s=config.store_settle_s,
            store_timeout_s=config.store_timeout_s,
            state_timeout_s=config.state_timeout_s,
            poll_s=config.poll_s,
        )
    except BaseException:
        # Whatever the reason, nothing of this session survives it: an attachment left open is the
        # next point's stale pointer.
        session.close()
        raise
    _LIVE_SESSIONS.append(session)
    return cycle


def activation_report(
    *,
    table: BridgeTable,
    table_path: str | Path | None,
    target_digest: str | None = None,
    channel: int | None = None,
    sequence: str = "record_stop_store",
    probe: bool = True,
    strip_reader: Callable[[], object] | None = None,
    menu_dispatch: Callable[[object], object] | None = None,
) -> ActivationReport:
    """Everything the host can settle **before** a recording, as a report rather than an exception.

    This is the mode a parent exercises first: it reads the config, checks the store directory and the
    table, and — when ``probe`` is true — starts one bounded session to read the identity, the owner
    and the routines, then closes it. It dispatches no cycle commands, but starting a producer may
    attach or prime a binding; callers need permission for that producer's actual behavior. Set
    ``probe=False`` for static checks with no producer start.

    ``sequence`` names which closed sequence is being activated. It is checked against the config
    before anything attaches, and it changes one requirement: a store-completed run routes no channel,
    so the composed menu dispatch that the recording path needs to avoid hovering is not asked for.
    """
    checks: list[ActivationCheck] = []

    def check(name: str, ok: bool, detail: str | None = None) -> None:
        checks.append(ActivationCheck(name=name, ok=bool(ok), detail=detail))

    def report(**kwargs: object) -> ActivationReport:
        payload = {
            "ready": all(item.ok for item in checks),
            "checks": tuple(checks),
            "config_path": (
                None if table_path is None else str(host_config_path(table_path))
            ),
            **kwargs,
        }
        return ActivationReport(**payload)

    if table_path is None:
        check(
            "host_config",
            False,
            "the table path was not given, so no config can be found",
        )
        return report()
    try:
        config = load_host_config(table_path)
    except HostRefusal as refusal:
        check("host_config", False, str(refusal))
        return report()
    check("host_config", True, str(host_config_path(table_path)))
    check(
        "sequence",
        config.sequence == sequence,
        f"config says {config.sequence}, this activation asked for {sequence}",
    )
    check(
        "store_directory", Path(config.store_directory).is_dir(), config.store_directory
    )
    command = config.producer
    if command is None:
        check("producer", False, "host_producer_missing")
    else:
        executable = Path(command.argv[0])
        if executable.is_absolute() or executable.parent != Path("."):
            check("producer", executable.is_file(), str(executable))
        else:
            check(
                "producer",
                True,
                f"{command.argv[0]!r} resolved by the operating system",
            )
    try:
        _table_operations(table)
        check("table_operations", True)
    except HostRefusal as refusal:
        check("table_operations", False, str(refusal))
    if target_digest is not None:
        check(
            "declared_digest",
            table.image_sha256 == target_digest,
            f"{table.image_sha256[:12]} vs {target_digest[:12]}",
        )
    # A guarded cycle without a composed menu dispatch is not background-usable: `ensure_channel`
    # would hover, which is a foreground gesture. Refused explicitly rather than blessed silently.
    # The store-completed sequence routes no channel at all, so it asks for none.
    if sequence == "record_stop_store" and not callable(menu_dispatch):
        check(
            "menu_dispatch",
            False,
            "no menu dispatch is composed: the channel verification would hover, so background "
            "readiness is refused",
        )
    elif callable(menu_dispatch):
        check("menu_dispatch", True, "composed from an existing dispatch module")
    else:
        check(
            "menu_dispatch",
            True,
            f"not required: the {sequence!r} sequence starts no acquisition and routes no channel",
        )
    # Static admission is a gate, not a note. A check that failed says this host must not be attached
    # to at all, and the probe is not a read-only curiosity: starting the producer runs *its* own
    # start-up, which on the recording sequence includes a parameter prime. So a refused activation
    # never creates a directory, a producer channel or a session — it reports and returns, and the
    # caller learns why from the same checks it would have read before.
    if any(not item.ok for item in checks):
        return report()
    if not probe:
        return report()
    if command is None:
        return report()
    session = new_session(
        _channel_for(config, _new_session_dir()),
        sequence=sequence,
        **bounds_from(config),
    )
    identity = None
    owner = None
    strip_view = None
    try:
        descriptor = session.start()
        identity, owner = descriptor.identity, descriptor.owner
        problem = _descriptor_problem(table, descriptor)
        check("binding", problem is None, problem)
        if strip_reader is not None:
            try:
                reading = strip_reader()
                strip_view = getattr(reading, "value", reading)
                check("strip_view", strip_view is not None, str(strip_view))
            except Exception as exc:  # noqa: BLE001 - an unreadable strip is a failed check
                check("strip_view", False, f"{type(exc).__name__}: {exc}")
    except HostRefusal as refusal:
        check("session", False, str(refusal))
    except Exception as exc:  # noqa: BLE001 - a preflight reports, it does not crash
        check("session", False, f"{type(exc).__name__}: {exc}")
    finally:
        session.close()
    check("session_close", session.close_problem is None, session.close_problem)
    return report(
        identity=identity,
        owner=owner if owner else None,
        strip_view=None if strip_view is None else str(strip_view),
        session_closed=session.closed,
        session_close_problem=session.close_problem,
    )
