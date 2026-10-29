"""The host integration that plugs the demonstrated producer into ``--route bridge --bridge-guarded-cycle``.

The package already composes the hardened cycle and already selects it from the CLI; what it had no
implementation of was the *host half*: a ``guarded_cycle`` factory that observes the running
application, refuses a stale or guessed binding, and dispatches the strip's routines through one
bounded session whose commands the application's own GUI loop consumes.

Two rules shape every test here. **Nothing is a guessed pointer**: the factory builds its binding
from what the producer states it observed, checks it against the machine-local table, and refuses by
name instead of inventing a value. And **a fake provider is not the live producer**: these tests
prove the protocol, the state machine, the refusals and the loading seam. They prove nothing about a
live application, and the module says so.

The last class drives the real file protocol against a real child process — a stand-in producer that
speaks the documented request/receipt contract — because a protocol that is only ever faked in
memory is not a protocol.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest

from udv_echo_process.acquire.actuator import StripView
from udv_echo_process.acquire.bridge import (
    BRIDGE_TABLE_SCHEMA,
    BridgeTable,
    guarded_cycle_from,
)
from udv_echo_process.acquire.cycle import (
    CycleBinding,
    CycleStage,
    ObservedAddress,
    ProcessIdentity,
    RoutineCycle,
)

REPO = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO / "tools" / "live" / "bridge_host" / "bootstrap.py"

BUILD = "a" * 64
PID = 4242
CREATED_NS = 1_760_000_000_000_000_000
RECORD = 0x71F034
STORE = 0x71F060
OWNER = 0x6F2A10


def table(**overrides) -> BridgeTable:
    payload = {
        "schema": BRIDGE_TABLE_SCHEMA,
        "image_sha256": BUILD,
        "dispatch": {"slot_pointer": 0x6F0000, "status_offset": 0x18},
        "operations": {
            "record": {"handler": RECORD, "code": 28},
            "stop": {"handler": RECORD, "code": 28},
            "store": {"handler": STORE, "code": 29},
        },
    }
    payload.update(overrides)
    return BridgeTable.model_validate(payload)


def descriptor(**overrides) -> object:
    from bridge_host.contract import SessionDescriptor

    payload = {
        "identity": ProcessIdentity(pid=PID, created_ns=CREATED_NS, image_sha256=BUILD),
        "owner": OWNER,
        "owner_source": "fresh discovery, class TMain_Scr",
        "record_handler": RECORD,
        "store_handler": STORE,
        "message_name": "HOST-Session-4242",
    }
    payload.update(overrides)
    return SessionDescriptor(**payload)


def host_dir(tmp_path: Path, *, name: str = "table.json", **config) -> Path:
    """A validated table with its host config beside it, as the parent will lay it out."""
    from bridge_host.config import HOST_CONFIG_SCHEMA

    table_path = tmp_path / name
    table_path.write_text(json.dumps({}), encoding="utf-8")
    payload = {
        "schema": HOST_CONFIG_SCHEMA,
        "store_directory": str(tmp_path / "store"),
        "producer": {"argv": [sys.executable, "producer.py"]},
    }
    payload.update(config)
    (tmp_path / "store").mkdir(exist_ok=True)
    (tmp_path / f"{table_path.stem}.host.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return table_path


@pytest.fixture(scope="session")
def host():
    """Load the bootstrap the way ``live.bridge_module`` does, and hand back its api module."""
    if not BOOTSTRAP.is_file():
        pytest.fail(f"the host integration is missing: {BOOTSTRAP}")
    spec = importlib.util.spec_from_file_location("udv_bridge_runner_test", BOOTSTRAP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["udv_bridge_runner_test"] = module
    spec.loader.exec_module(module)
    from bridge_host import api

    return module, api


class Channel:
    """A producer channel that answers from a script — never from a live application."""

    def __init__(self, *, state=None, receipts=None, probes=None) -> None:
        self._descriptor = state or descriptor()
        self._receipts = list(
            receipts
            or [
                {"ok": True, "operation": "record", "consumed_target": True},
                {"ok": True, "operation": "stop", "consumed_target": True},
                {"ok": True, "operation": "store", "consumed_target": True},
            ]
        )
        self._probes = list(
            probes or [{"identity": self._descriptor.identity, "owner_ok": True}]
        )
        self.calls: list[tuple] = []

    def start(self, *, session_dir, timeout_s):
        self.calls.append(("start", session_dir))
        return self._descriptor

    def dispatch(self, *, operation, address, form, sequence, timeout_s):
        from bridge_host.contract import DispatchReceipt

        self.calls.append(("dispatch", operation, address, form))
        return DispatchReceipt(**self._receipts.pop(0))

    def probe(self, *, sequence, timeout_s):
        from bridge_host.contract import ProbeReport

        self.calls.append(("probe", sequence))
        payload = self._probes.pop(0) if len(self._probes) > 1 else self._probes[0]
        return ProbeReport(**payload)

    def close(self, *, timeout_s):
        self.calls.append(("close",))

    @property
    def dispatched(self) -> list[str]:
        return [call[1] for call in self.calls if call[0] == "dispatch"]


class TestSessionBounds:
    def test_a_session_starts_once(self, host):
        _, api = host
        channel = Channel()
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        session.start()
        with pytest.raises(api.HostRefusal, match="host_session_started"):
            session.start()
        assert len([c for c in channel.calls if c[0] == "start"]) == 1

    def test_dispatch_before_start_is_refused_without_a_call(self, host):
        _, api = host
        channel = Channel()
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        with pytest.raises(api.HostRefusal, match="host_session_not_started"):
            session.dispatch("record", address=RECORD, form=OWNER)
        assert channel.dispatched == []

    def test_a_store_before_a_stop_is_out_of_order(self, host):
        _, api = host
        channel = Channel()
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        session.start()
        with pytest.raises(api.HostRefusal, match="host_operation_out_of_order:store"):
            session.dispatch("store", address=STORE, form=OWNER)
        assert channel.dispatched == []

    def test_a_store_only_session_dispatches_store_first(self, host):
        """The store-completed sequence: one operation, and it is the only one this session may name."""
        _, api = host
        channel = Channel(
            receipts=[{"ok": True, "operation": "store", "consumed_target": True}]
        )
        session = api.new_session(
            channel,
            sequence="store",
            **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp"))),
        )
        session.start()
        assert session.operations == ("store",)
        session.dispatch("store", address=STORE, form=OWNER)
        assert channel.dispatched == ["store"]

    def test_a_store_only_session_cannot_name_record_at_all(self, host):
        """Not out of order — never part of the sequence, so it is refused before it can be a step."""
        _, api = host
        channel = Channel()
        session = api.new_session(
            channel,
            sequence="store",
            **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp"))),
        )
        session.start()
        with pytest.raises(
            api.HostRefusal, match="host_operation_not_in_sequence:record"
        ):
            session.dispatch("record", address=RECORD, form=OWNER)
        assert channel.dispatched == []
        assert session.dispatched == ()

    def test_an_unknown_sequence_is_refused_rather_than_defaulted(self, host):
        _, api = host
        with pytest.raises(api.HostRefusal, match="host_sequence_unknown:record"):
            api.new_session(Channel(), sequence="record")

    def test_a_dispatch_the_loop_never_consumed_is_not_a_dispatch(self, host):
        """`ok` from the producer is not enough: the application's own loop must have taken it."""
        _, api = host
        channel = Channel(
            receipts=[{"ok": True, "operation": "record", "consumed_target": False}]
        )
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        session.start()
        with pytest.raises(api.HostRefusal, match="host_dispatch_not_consumed:record"):
            session.dispatch("record", address=RECORD, form=OWNER)

    def test_a_receipt_for_another_operation_is_unusable(self, host):
        _, api = host
        channel = Channel(
            receipts=[{"ok": True, "operation": "stop", "consumed_target": True}]
        )
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        session.start()
        with pytest.raises(
            api.HostRefusal, match="host_dispatch_receipt_invalid:operation"
        ):
            session.dispatch("record", address=RECORD, form=OWNER)

    def test_an_expired_session_refuses_and_still_closes_once(self, host):
        _, api = host
        channel = Channel()
        config = api.HostConfig.defaults_for(Path("/tmp")).model_copy(
            update={"total_budget_s": 0.0}
        )
        session = api.new_session(channel, **api.bounds_from(config))
        session.start()
        with pytest.raises(api.HostRefusal, match="host_session_expired"):
            session.dispatch("record", address=RECORD, form=OWNER)
        session.close()
        session.close()
        assert [c for c in channel.calls if c[0] == "close"] == [("close",)]

    def test_a_closed_session_refuses_every_further_read(self, host):
        _, api = host
        channel = Channel()
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        session.start()
        session.close()
        for call in (
            lambda: session.dispatch("record", address=RECORD, form=OWNER),
            session.probe,
        ):
            with pytest.raises(api.HostRefusal, match="host_session_closed"):
                call()


class TestTheCaller:
    def _session(self, api, channel):
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        session.start()
        return session

    def test_one_address_is_record_then_stop(self, host):
        _, api = host
        channel = Channel()
        caller = api.SessionCaller(self._session(api, channel), table())
        assert caller(RECORD, OWNER) == {"ok": True}
        assert caller(RECORD, OWNER) == {"ok": True}
        assert channel.dispatched == ["record", "stop"]

    def test_the_store_address_is_the_store_operation(self, host):
        _, api = host
        channel = Channel()
        caller = api.SessionCaller(self._session(api, channel), table())
        caller(RECORD, OWNER)
        caller(RECORD, OWNER)
        assert caller(STORE, OWNER) == {"ok": True}
        assert channel.dispatched == ["record", "stop", "store"]

    def test_an_unlisted_address_is_refused_without_a_dispatch(self, host):
        _, api = host
        channel = Channel()
        caller = api.SessionCaller(self._session(api, channel), table())
        answer = caller(0x31337, OWNER)
        assert answer["ok"] is False
        assert "host_address_not_allowlisted" in answer["errors"][0]
        assert channel.dispatched == []

    def test_a_third_record_dispatch_is_refused(self, host):
        _, api = host
        channel = Channel()
        caller = api.SessionCaller(self._session(api, channel), table())
        caller(RECORD, OWNER)
        caller(RECORD, OWNER)
        answer = caller(RECORD, OWNER)
        assert answer["ok"] is False
        assert "host_record_repeated" in answer["errors"][0]

    def test_a_producer_refusal_is_reported_not_raised(self, host):
        """The cycle turns `ok: False` into a named stage refusal; a raise would lose the stage."""
        _, api = host
        channel = Channel(
            receipts=[
                {"ok": False, "operation": "record", "errors": ["wrong GUI thread"]}
            ]
        )
        caller = api.SessionCaller(self._session(api, channel), table())
        answer = caller(RECORD, OWNER)
        assert answer["ok"] is False
        assert answer["errors"] == ["wrong GUI thread"]

    def test_a_store_only_caller_refuses_the_record_address_without_a_dispatch(
        self, host
    ):
        """The second lock: even an address this table carries is unreachable on this route."""
        _, api = host
        channel = Channel(
            receipts=[{"ok": True, "operation": "store", "consumed_target": True}]
        )
        session = api.new_session(
            channel,
            sequence="store",
            **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp"))),
        )
        session.start()
        caller = api.SessionCaller(session, table(), store_only=True)
        answer = caller(RECORD, OWNER)
        assert answer["ok"] is False
        assert "host_record_forbidden:store_only" in answer["errors"][0]
        assert channel.dispatched == []
        assert caller(STORE, OWNER) == {"ok": True}
        assert channel.dispatched == ["store"]

    def test_a_store_only_caller_over_a_recording_session_is_refused(self, host):
        _, api = host
        channel = Channel()
        with pytest.raises(api.HostRefusal, match="host_caller_sequence_mismatch"):
            api.SessionCaller(self._session(api, channel), table(), store_only=True)
        assert channel.dispatched == []


class TestTheReaders:
    def _session(self, api, channel):
        session = api.new_session(
            channel, **api.bounds_from(api.HostConfig.defaults_for(Path("/tmp")))
        )
        session.start()
        return session

    def test_the_identity_is_read_again_on_every_call(self, host):
        _, api = host
        second = ProcessIdentity(pid=PID + 1, created_ns=CREATED_NS, image_sha256=BUILD)
        channel = Channel(
            probes=[
                {"identity": descriptor().identity, "owner_ok": True},
                {"identity": second, "owner_ok": True},
            ]
        )
        reader = api.SessionIdentityReader(self._session(api, channel))
        assert reader() == descriptor().identity
        assert reader() == second
        assert len([c for c in channel.calls if c[0] == "probe"]) == 2

    def test_a_guard_that_did_not_answer_yes_or_no_is_passed_through(self, host):
        """A truthy string is malformed evidence; coercing it here would hide that from the cycle."""
        _, api = host
        channel = Channel(
            probes=[{"identity": descriptor().identity, "owner_ok": "yes"}]
        )
        check = api.SessionOwnerCheck(self._session(api, channel), OWNER)
        assert check(OWNER) == "yes"

    def test_another_pointer_is_never_validated_by_proxy(self, host):
        _, api = host
        channel = Channel(
            probes=[{"identity": descriptor().identity, "owner_ok": True}]
        )
        check = api.SessionOwnerCheck(self._session(api, channel), OWNER)
        assert check(OWNER + 4) is False
        # Nothing was asked about the foreign pointer: a proxy read would validate the wrong object.
        assert [call for call in channel.calls if call[0] == "probe"] == []


class TestTheFactory:
    def test_the_factory_builds_the_packages_own_cycle(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        channel = Channel()
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: _Surface())
        cycle = module.guarded_cycle(
            table=table(), table_path=host_dir(tmp_path), target_digest=None, channel=1
        )
        assert isinstance(cycle, RoutineCycle)
        assert cycle.configuration_problem() is None
        assert isinstance(cycle.binding, CycleBinding)
        assert cycle.binding.identity == descriptor().identity
        assert cycle.binding.owner == ObservedAddress(
            address=OWNER, source="fresh discovery, class TMain_Scr"
        )
        assert channel.calls[0][0] == "start"

    def test_a_build_that_is_not_the_tables_is_refused_before_any_dispatch(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        channel = Channel()
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: _Surface())
        other = ProcessIdentity(pid=PID, created_ns=CREATED_NS, image_sha256="b" * 64)
        channel._descriptor = descriptor(identity=other)
        with pytest.raises(api.BridgeUnavailable, match="host_build_mismatch"):
            module.guarded_cycle(
                table=table(),
                table_path=host_dir(tmp_path),
                target_digest=None,
                channel=1,
            )
        assert channel.dispatched == []

    def test_a_routine_the_producer_resolved_elsewhere_is_a_conflict(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        channel = Channel(state=descriptor(record_handler=RECORD + 8))
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: _Surface())
        with pytest.raises(api.BridgeUnavailable, match="host_routine_conflict:record"):
            module.guarded_cycle(
                table=table(),
                table_path=host_dir(tmp_path),
                target_digest=None,
                channel=1,
            )

    def test_an_owner_that_was_never_observed_is_refused(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        channel = Channel(state=descriptor(owner=0))
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: _Surface())
        with pytest.raises(api.BridgeUnavailable, match="host_owner_not_observed"):
            module.guarded_cycle(
                table=table(),
                table_path=host_dir(tmp_path),
                target_digest=None,
                channel=1,
            )

    def test_a_missing_host_config_is_named(self, host, tmp_path):
        module, _api = host
        bare = tmp_path / "table.json"
        bare.write_text("{}", encoding="utf-8")
        with pytest.raises(Exception, match="host_config_missing"):
            module.guarded_cycle(
                table=table(), table_path=bare, target_digest=None, channel=1
            )

    def test_the_packages_own_factory_check_accepts_it(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        channel = Channel()
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: _Surface())
        cycle = guarded_cycle_from(
            module.guarded_cycle,
            table=table(),
            table_path=host_dir(tmp_path),
            target_digest=BUILD,
            channel=1,
        )
        assert isinstance(cycle, RoutineCycle)


class _Surface:
    """A store surface and strip reader for the factory's dialog adapter; no application behind it."""

    def __init__(
        self, views: list[StripView] | None = None, *, shows: str | None = None
    ) -> None:
        #: The strip's scripted views: the cycle reads it once per stage it confirms.
        self.views = list(views or [StripView.READY])
        #: What the Store dialog's ``Working directory`` states — text, as the application shows it.
        self.shows = shows
        self.notes: list[str] = []
        self.calls: list[tuple] = []

    def strip_state(self) -> StripView:
        if len(self.views) > 1:
            return self.views.pop(0)
        return self.views[0]

    def _require_store_dialog(self):
        return {"hwnd": 1}, []

    def read_working_directory(self):
        self.calls.append(("read_working_directory",))
        return self.shows

    def set_store_name(self, name):
        self.calls.append(("set_store_name", name))

    def commit_store(self):
        self.calls.append(("commit_store",))


class TestTheCycleThroughTheHost:
    def test_the_whole_chain_reaches_verify_through_the_real_cycle(
        self, host, tmp_path, monkeypatch
    ):
        """record → stop → store → commit, driven by the package's cycle over this host.

        The artifact is absent, so the cycle refuses at `verify` — which is the honest end of this
        test: what it proves is the dispatch chain, the guards and the dialog commit, not a stored
        block (that needs the instrument).
        """
        module, api = host
        channel = Channel()
        surface = _Surface(
            views=[StripView.READY, StripView.RECORDING, StripView.STORE],
            shows=str(tmp_path / "store"),
        )
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: surface)
        cycle = module.guarded_cycle(
            table=table(),
            table_path=host_dir(
                tmp_path, stop_settle_s=0.0, store_settle_s=0.0, store_timeout_s=0.0
            ),
            target_digest=None,
            channel=1,
        )
        ok, reason = cycle.try_record_and_store("host-01", 0.0, tmp_path / "store")
        assert ok is False
        assert str(reason).startswith("store_file_missing"), reason
        assert channel.dispatched == ["record", "stop", "store"]
        assert ("set_store_name", "host-01") in surface.calls
        assert ("commit_store",) in surface.calls
        report = cycle.last_report
        assert report is not None
        assert report.dialog_committed is True
        assert report.recorded is True and report.stopped is True

    def test_a_restart_during_the_recording_blocks_the_commit(
        self, host, tmp_path, monkeypatch
    ):
        """The interesting change happens *inside* a recording: the second identity must refuse."""
        module, api = host
        changed = ProcessIdentity(
            pid=PID, created_ns=CREATED_NS + 1, image_sha256=BUILD
        )
        channel = Channel(
            probes=[
                {"identity": descriptor().identity, "owner_ok": True},
                {"identity": changed, "owner_ok": True},
            ]
        )
        surface = _Surface(
            views=[StripView.READY, StripView.RECORDING, StripView.STORE],
            shows=str(tmp_path / "store"),
        )
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: surface)
        cycle = module.guarded_cycle(
            table=table(),
            table_path=host_dir(
                tmp_path, stop_settle_s=0.0, store_settle_s=0.0, store_timeout_s=0.0
            ),
            target_digest=None,
            channel=1,
        )
        ok, reason = cycle.try_record_and_store("host-02", 0.0, tmp_path / "store")
        assert ok is False
        assert "cycle_instance_changed" in str(reason), reason
        # The store was never requested and the dialog was never named: the restart stopped the cycle.
        assert "store" not in channel.dispatched


class TestTheStoreCompletedFactory:
    """``store_completed_cycle``: the same construction, over a sequence that cannot record.

    The producer is a double, so what is proven here is the wiring — one observed binding, the table
    compared with what the producer stated, one bounded session — and what is *not*: no application is
    behind any of it.
    """

    def _cycle(self, host, tmp_path, monkeypatch, *, config=None):
        _, api = host
        channel = Channel(
            receipts=[{"ok": True, "operation": "store", "consumed_target": True}]
        )
        surface = _Surface(views=[StripView.STORE], shows=str(tmp_path / "store"))
        monkeypatch.setattr(api, "_channel_for", lambda _config, _dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda _channel: surface)
        cycle = api.store_completed_cycle(
            table=table(),
            table_path=host_dir(
                tmp_path, sequence="store", store_settle_s=0.0, store_timeout_s=0.0
            ),
            target_digest=None,
            channel=1,
        )
        return api, cycle, channel, surface

    def test_it_dispatches_only_the_store_routine(self, host, tmp_path, monkeypatch):
        _api, cycle, channel, surface = self._cycle(host, tmp_path, monkeypatch)
        # The artifact is absent, so the tail refuses at `verify` — which is the honest end of an
        # offline test: the dispatch chain, the guards and the commit are what it proves.
        ok, reason = cycle.store_completed_block("held-01", tmp_path / "store")
        assert ok is False
        assert str(reason).startswith("store_file_missing"), reason
        assert channel.dispatched == ["store"]
        assert ("set_store_name", "held-01") in surface.calls
        assert ("commit_store",) in surface.calls
        report = cycle.last_report
        assert report is not None
        assert report.recorded is False and report.stopped is False
        assert report.store_requested is True and report.dialog_committed is True
        assert report.stored is False

    def test_the_recording_entry_point_is_closed_and_says_so(
        self, host, tmp_path, monkeypatch
    ):
        _api, cycle, channel, _surface = self._cycle(host, tmp_path, monkeypatch)
        ok, reason = cycle.try_record_and_store("held-02", 0.0, tmp_path / "store")
        assert (ok, reason) == (
            False,
            "cycle_store_only:record_and_store_not_permitted",
        )
        assert channel.dispatched == []

    def test_a_recording_config_is_refused_before_anything_attaches(
        self, host, tmp_path, monkeypatch
    ):
        _, api = host
        channel = Channel()
        monkeypatch.setattr(api, "_channel_for", lambda _config, _dir: channel)
        with pytest.raises(api.HostRefusal, match="host_sequence_mismatch"):
            api.store_completed_cycle(
                table=table(),
                table_path=host_dir(
                    tmp_path
                ),  # the default: a record/stop/store config
                target_digest=None,
                channel=1,
            )
        assert channel.calls == []

    def test_the_recording_factory_refuses_a_store_only_config(
        self, host, tmp_path, monkeypatch
    ):
        from udv_echo_process.acquire.bridge import BridgeUnavailable

        module, api = host
        channel = Channel()
        monkeypatch.setattr(api, "_channel_for", lambda _config, _dir: channel)
        with pytest.raises(BridgeUnavailable, match="host_sequence_mismatch"):
            module.guarded_cycle(
                table=table(),
                table_path=host_dir(tmp_path, sequence="store"),
                target_digest=None,
                channel=1,
            )
        assert channel.calls == []

    def test_the_package_still_sees_a_routine_cycle(self, host, tmp_path, monkeypatch):
        _api, cycle, _channel, _surface = self._cycle(host, tmp_path, monkeypatch)
        assert isinstance(cycle, RoutineCycle)

    def test_a_refused_recording_leaves_no_stale_success_behind(
        self, host, tmp_path, monkeypatch
    ):
        """`last_report` is read *after* the call: a success left standing beside a refusal is the bug."""
        import shutil

        _, api = host
        channel = Channel(
            receipts=[{"ok": True, "operation": "store", "consumed_target": True}]
        )

        class Writing(_Surface):
            """The Store dialog that really writes the block, so the first invocation succeeds."""

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.named: str | None = None

            def set_store_name(self, name):
                super().set_store_name(name)
                self.named = name

            def commit_store(self):
                super().commit_store()
                shutil.copyfile(
                    REPO / "data" / "4-sensor-velocity" / "200RPM.BDD",
                    tmp_path / "store" / f"{self.named}.BDD",
                )

        surface = Writing(views=[StripView.STORE], shows=str(tmp_path / "store"))
        monkeypatch.setattr(api, "_channel_for", lambda _config, _dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda _channel: surface)
        cycle = api.store_completed_cycle(
            table=table(),
            table_path=host_dir(
                tmp_path, sequence="store", store_settle_s=0.0, store_timeout_s=0.0
            ),
            target_digest=None,
            channel=1,
        )
        stored, outcome = cycle.store_completed_block("held-03", tmp_path / "store")
        assert stored is True, outcome
        assert cycle.last_report.stored is True
        assert cycle.last_report.recorded_span_s is not None

        refused, reason = cycle.try_record_and_store("held-04", 0.0, tmp_path / "store")
        assert refused is False
        assert reason == "cycle_store_only:record_and_store_not_permitted"
        report = cycle.last_report
        assert report is not None
        assert report.reason == "cycle_store_only:record_and_store_not_permitted"
        assert report.name == "held-04"
        assert report.stage is CycleStage.PREFLIGHT
        # No fact of the earlier store survives into this refusal.
        assert report.stored is False
        assert report.store_requested is False
        assert report.dialog_committed is False
        assert report.recorded is False and report.stopped is False
        assert report.streams == 0
        assert report.recorded_span_s is None
        assert channel.dispatched == ["store"]  # the refusal dispatched nothing


class TestTheActivationGate:
    """Static admission is a gate: a failed check must not be followed by an attach.

    The store-completed sequence exists because the recording sequence's producer primes a parameter
    before it observes anything. An activation that reports the mismatch and then starts that producer
    anyway has done the thing the refusal was supposed to prevent, so these tests intercept the three
    steps that would touch the application and require none of them to run.
    """

    def test_a_store_activation_of_a_recording_config_never_starts_the_producer(
        self, host, tmp_path, monkeypatch
    ):
        _, api = host
        touched: list[str] = []

        def forbidden_channel(_config, _session_dir):
            touched.append("channel")
            raise AssertionError("the parameter-priming producer was started")

        def forbidden_dir():
            touched.append("session_dir")
            raise AssertionError("a session directory was created")

        def forbidden_strip():
            touched.append("strip")
            raise AssertionError("the strip was read")

        monkeypatch.setattr(api, "_channel_for", forbidden_channel)
        monkeypatch.setattr(api, "_new_session_dir", forbidden_dir)
        report = api.activation_report(
            table=table(),
            table_path=host_dir(tmp_path),  # the default: record_stop_store
            sequence="store",
            probe=True,
            strip_reader=forbidden_strip,
        )
        assert report.ready is False
        assert "sequence" in report.failed()
        assert touched == []
        assert (
            report.identity is None
            and report.owner is None
            and report.strip_view is None
        )
        assert report.session_closed is True

    def test_a_recording_activation_of_a_store_config_never_starts_the_producer(
        self, host, tmp_path, monkeypatch
    ):
        _, api = host
        touched: list[str] = []

        def forbidden_channel(_config, _session_dir):
            touched.append("channel")
            raise AssertionError("a producer was started for a refused activation")

        monkeypatch.setattr(
            api,
            "_channel_for",
            forbidden_channel,
        )
        monkeypatch.setattr(
            api, "_new_session_dir", lambda: touched.append("session_dir") or tmp_path
        )
        report = api.activation_report(
            table=table(),
            table_path=host_dir(tmp_path, sequence="store"),
            sequence="record_stop_store",
            probe=True,
        )
        assert report.ready is False
        assert "sequence" in report.failed()
        assert touched == []

    def test_an_unknown_sequence_cannot_be_activated_at_all(
        self, host, tmp_path, monkeypatch
    ):
        _, api = host
        touched: list[str] = []

        def forbidden_channel(_config, _session_dir):
            touched.append("channel")
            raise AssertionError("a producer was started for an unnameable sequence")

        monkeypatch.setattr(api, "_channel_for", forbidden_channel)
        monkeypatch.setattr(
            api, "_new_session_dir", lambda: touched.append("session_dir") or tmp_path
        )
        report = api.activation_report(
            table=table(),
            table_path=host_dir(tmp_path),
            sequence="record",  # not one of the closed sequences
            probe=True,
        )
        assert report.ready is False
        assert "sequence" in report.failed()
        assert touched == []

    def test_the_valid_recording_activation_still_probes(
        self, host, tmp_path, monkeypatch
    ):
        """The gate must not close the path that works: every static check passing still attaches."""
        _, api = host
        channel = Channel()
        monkeypatch.setattr(api, "_channel_for", lambda _config, _dir: channel)
        menu = tmp_path / "menu_dispatch.py"
        menu.write_text(
            'def dispatch(call):\n    return {"ok": True}\n', encoding="utf-8"
        )
        from bridge_host.menu import legacy_dispatch

        report = api.activation_report(
            table=table(),
            table_path=host_dir(tmp_path),
            probe=True,
            menu_dispatch=legacy_dispatch(str(menu)),
        )
        assert report.ready is True, report.failed()
        assert [call[0] for call in channel.calls] == ["start", "close"]


class TestTheFileProtocol:
    """The channel against a real child process: requests out, receipts in, bounded, cleaned up."""

    def test_a_child_that_speaks_the_protocol_is_driven_and_closed(
        self, host, tmp_path
    ):
        _, api = host
        producer = tmp_path / "producer.py"
        producer.write_text(
            textwrap.dedent(
                f"""
                import json, os, sys, time
                from pathlib import Path

                session = Path(sys.argv[1])
                session.mkdir(parents=True, exist_ok=True)
                identity = {{"pid": {PID}, "created_ns": {CREATED_NS}, "image_sha256": "{BUILD}"}}
                ready = {{
                    "identity": identity,
                    "owner": {OWNER},
                    "owner_source": "stand-in producer",
                    "record_handler": {RECORD},
                    "store_handler": {STORE},
                    "message_name": "HOST-Session-{PID}",
                }}
                (session / "session-ready.json").write_text(json.dumps(ready), encoding="utf-8")
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    request = session / "request.json"
                    if request.is_file():
                        payload = json.loads(request.read_text(encoding="utf-8"))
                        request.unlink()
                        operation = payload["operation"]
                        receipt = {{"ok": True, "operation": operation, "consumed_target": True}}
                        if operation == "probe":
                            receipt = {{"identity": identity, "owner_ok": True, "owner": {OWNER}}}
                        target = session / ("receipt-%d.json" % payload["sequence"])
                        target.write_text(json.dumps(receipt), encoding="utf-8")
                    if (session / "close.json").is_file():
                        raise SystemExit(0)
                    time.sleep(0.01)
                raise SystemExit(3)
                """
            ),
            encoding="utf-8",
        )
        session_dir = tmp_path / "session"
        channel = api.FileProtocolChannel(
            api.ProducerCommand(argv=(sys.executable, str(producer))),
            session_dir=session_dir,
        )
        descriptor = channel.start(session_dir=session_dir, timeout_s=20.0)
        assert descriptor.owner == OWNER
        first = channel.dispatch(
            operation="record", address=RECORD, form=OWNER, sequence=1, timeout_s=20.0
        )
        assert first.ok is True and first.consumed_target is True
        probe = channel.probe(sequence=2, timeout_s=20.0)
        assert probe.identity == descriptor.identity and probe.owner_ok is True
        channel.close(timeout_s=20.0)
        assert channel.process is None or channel.process.poll() is not None

    def test_a_child_that_dies_is_named_rather_than_waited_on(self, host, tmp_path):
        _, api = host
        producer = tmp_path / "dead.py"
        producer.write_text("raise SystemExit(9)\n", encoding="utf-8")
        session_dir = tmp_path / "gone"
        channel = api.FileProtocolChannel(
            api.ProducerCommand(argv=(sys.executable, str(producer))),
            session_dir=session_dir,
        )
        with pytest.raises(api.HostRefusal, match="host_producer_exited:9"):
            channel.start(session_dir=session_dir, timeout_s=20.0)


class TestProducerCloseReporting:
    """An exited producer and a clean attachment shutdown are not synonyms."""

    @pytest.mark.parametrize("exit_code", [0, 7])
    def test_actual_child_exit_status_is_preserved(self, host, tmp_path, exit_code):
        _, api = host
        producer = tmp_path / "closing_child.py"
        ready = {
            "identity": {"pid": PID, "created_ns": CREATED_NS, "image_sha256": BUILD},
            "owner": OWNER,
            "owner_source": "owned offline lifecycle fixture",
            "record_handler": RECORD,
            "store_handler": STORE,
            "message_name": "HOST-Close-Fixture",
        }
        producer.write_text(
            textwrap.dedent(
                f"""
                import json, sys, time
                from pathlib import Path
                session = Path(sys.argv[1])
                (session / "session-ready.json").write_text(
                    json.dumps({ready!r}), encoding="utf-8"
                )
                deadline = time.monotonic() + 10
                while not (session / "close.json").exists():
                    if time.monotonic() >= deadline:
                        raise SystemExit(99)
                    time.sleep(0.01)
                raise SystemExit({exit_code})
                """
            ),
            encoding="utf-8",
        )
        channel = api.FileProtocolChannel(
            api.ProducerCommand(argv=(sys.executable, str(producer))),
            session_dir=tmp_path / "session",
        )
        session = api.new_session(channel, sequence="store", close_timeout_s=10)
        try:
            session.start()
        finally:
            session.close()
        assert channel.process.poll() == exit_code
        expected = None if exit_code == 0 else f"host_producer_close_exit:{exit_code}"
        assert channel.close_problem == expected
        assert session.close_problem == expected
        assert session.closed is True  # this flag means called, not clean
        assert session.dispatched == ()

    @pytest.mark.parametrize(
        "problem", ["host_producer_did_not_exit", "host_producer_unreaped:OSError"]
    )
    def test_nonraising_channel_problem_reaches_session_once(self, host, problem):
        _, api = host

        class FailedClose(Channel):
            def close(self, *, timeout_s):
                super().close(timeout_s=timeout_s)
                self.close_problem = problem

        channel = FailedClose()
        session = api.new_session(channel, sequence="store")
        session.start()
        session.close()
        session.close()
        assert session.close_problem == problem
        assert [call for call in channel.calls if call[0] == "close"] == [("close",)]
        assert session.dispatched == ()


class TestActivationCleanupReporting:
    @pytest.mark.parametrize("problem", [None, "host_producer_close_exit:7"])
    def test_probe_exposes_close_problem_and_refuses_dirty_close(
        self, host, tmp_path, monkeypatch, problem
    ):
        _, api = host

        class ClosingChannel(Channel):
            def close(self, *, timeout_s):
                super().close(timeout_s=timeout_s)
                self.close_problem = problem

        channel = ClosingChannel()
        monkeypatch.setattr(api, "_channel_for", lambda _config, _dir: channel)
        report = api.activation_report(
            table=table(),
            table_path=host_dir(tmp_path, sequence="store"),
            sequence="store",
            probe=True,
        )
        assert report.ready is (problem is None)
        assert getattr(report, "session_close_problem", None) == problem
        assert report.session_closed is True
        if problem:
            assert "session_close" in report.failed()
        assert [call for call in channel.calls if call[0] == "close"] == [("close",)]


class TestThePreflightScript:
    """The same preflight from a shell: one command, one exit code, nothing recorded."""

    def _real_table(self, tmp_path) -> Path:
        table_path = host_dir(tmp_path)
        table_path.write_text(
            json.dumps(table().model_dump(by_alias=True)), encoding="utf-8"
        )
        return table_path

    def test_a_bound_host_exits_zero(self, host, tmp_path, monkeypatch, capsys):
        _, api = host
        from bridge_host import activate

        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: Channel())
        menu = tmp_path / "menu_dispatch.py"
        menu.write_text(
            'def dispatch(call):\n    return {"ok": True}\n', encoding="utf-8"
        )
        assert (
            activate.main(
                [
                    "--table",
                    str(self._real_table(tmp_path)),
                    "--menu-dispatch-module",
                    str(menu),
                ]
            )
            == 0
        )
        assert '"ready": true' in capsys.readouterr().out

    def test_without_a_menu_dispatch_background_readiness_is_refused(
        self, host, tmp_path, monkeypatch, capsys
    ):
        """A cycle alone would hover at channel verification: that is not background readiness."""
        _, api = host
        from bridge_host import activate

        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: Channel())
        assert activate.main(["--table", str(self._real_table(tmp_path))]) == 2
        output = capsys.readouterr().out
        assert "menu_dispatch" in output and '"ready": false' in output

    def test_the_sequence_flag_is_forwarded_and_a_mismatch_never_probes(
        self, host, tmp_path, monkeypatch, capsys
    ):
        """``--sequence store`` against a recording config: refused, and nothing is started."""
        _, api = host
        from bridge_host import activate

        monkeypatch.setattr(
            api,
            "_channel_for",
            lambda *_args: pytest.fail(
                "a producer was started for a mismatched sequence"
            ),
        )
        assert (
            activate.main(
                ["--table", str(self._real_table(tmp_path)), "--sequence", "store"]
            )
            == 2
        )
        output = capsys.readouterr().out
        assert "sequence" in output and '"ready": false' in output

    def test_a_store_only_config_activates_as_the_store_sequence(
        self, host, tmp_path, capsys
    ):
        from bridge_host import activate

        table_path = host_dir(tmp_path, sequence="store")
        table_path.write_text(
            json.dumps(table().model_dump(by_alias=True)), encoding="utf-8"
        )
        assert (
            activate.main(
                ["--table", str(table_path), "--sequence", "store", "--no-probe"]
            )
            == 0
        )
        assert '"ready": true' in capsys.readouterr().out

    def test_an_unconfigured_host_exits_two_and_names_the_reason(
        self, host, tmp_path, capsys
    ):
        from bridge_host import activate

        bare = tmp_path / "solo.json"
        bare.write_text(json.dumps(table().model_dump(by_alias=True)), encoding="utf-8")
        assert activate.main(["--table", str(bare)]) == 2
        output = capsys.readouterr().out
        assert "host_config" in output and '"ready": false' in output


class TestTheInvocationDirectory:
    """The factory is built once; the directory that matters is the one each point passes in."""

    def test_a_later_point_binds_its_own_directory_rather_than_the_factories(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        channel = Channel()
        first, second = tmp_path / "store", tmp_path / "second"
        first.mkdir()
        second.mkdir()
        # The dialog still states the *first* point's directory when the second point is asked for.
        surface = _Surface(
            views=[StripView.READY, StripView.RECORDING, StripView.STORE],
            shows=str(first),
        )
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        monkeypatch.setattr(api, "_new_actuator", lambda channel_number: surface)
        cycle = module.guarded_cycle(
            table=table(),
            table_path=host_dir(
                tmp_path, stop_settle_s=0.0, store_settle_s=0.0, store_timeout_s=0.0
            ),
            target_digest=None,
            channel=1,
        )
        assert cycle.store_dialog.directory is None  # nothing bound at construction
        ok, reason = cycle.try_record_and_store("point-02", 0.0, second)
        assert ok is False
        # The *invocation's* directory was bound, and the dialog's answer was judged against it.
        assert cycle.store_dialog.directory == second
        assert cycle.store_dialog.original_directory == str(first)
        assert "store_dialog_raised" in str(reason), reason
        assert ("set_store_name", "point-02") not in surface.calls
        assert ("commit_store",) not in surface.calls


class TestTheMenuComposition:
    """A cycle alone is not background-usable: the menu dispatch must be composed, not rebuilt."""

    def _module(self, tmp_path, body: str) -> Path:
        path = tmp_path / "menu_module.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_an_existing_dispatch_is_returned_unchanged(self, host, tmp_path):
        from bridge_host.menu import legacy_dispatch

        path = self._module(
            tmp_path,
            'def dispatch(call):\n    return {"ok": True, "overlay_painted": True}\n',
        )
        composed = legacy_dispatch(path)
        assert composed({"action": "enter"}) == {"ok": True, "overlay_painted": True}

    def test_a_missing_module_is_named(self, host, tmp_path):
        from bridge_host.menu import legacy_dispatch

        with pytest.raises(Exception, match="host_menu_dispatch_missing"):
            legacy_dispatch(tmp_path / "absent.py")

    def test_a_module_without_a_dispatch_is_named(self, host, tmp_path):
        from bridge_host.menu import legacy_dispatch

        with pytest.raises(Exception, match="host_menu_dispatch_invalid"):
            legacy_dispatch(self._module(tmp_path, "VALUE = 1\n"))


class TestActivation:
    """The passive mode a parent runs before a grant: it observes, reports, closes — never dispatches."""

    def test_a_ready_host_reports_what_it_observed_and_dispatches_nothing(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        channel = Channel()
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        report = module.activation_report(
            table=table(),
            table_path=host_dir(tmp_path),
            strip_reader=lambda: StripView.READY,
            menu_dispatch=lambda call: {"ok": True},
        )
        assert report.ready is True, report.failed()
        assert report.identity == descriptor().identity
        assert report.owner == OWNER
        assert report.strip_view == "ready"
        assert report.session_closed is True
        assert [call for call in channel.calls if call[0] == "dispatch"] == []
        assert ("close",) in channel.calls

    def test_a_missing_config_is_the_only_finding_and_nothing_is_attached(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        monkeypatch.setattr(
            api,
            "_channel_for",
            lambda *_a: pytest.fail("a session was built without a config"),
        )
        bare = tmp_path / "table.json"
        bare.write_text("{}", encoding="utf-8")
        report = module.activation_report(table=table(), table_path=bare)
        assert report.ready is False
        assert "host_config" in report.failed()

    def test_a_build_disagreement_is_reported_not_raised(
        self, host, tmp_path, monkeypatch
    ):
        module, api = host
        other = ProcessIdentity(pid=PID, created_ns=CREATED_NS, image_sha256="c" * 64)
        channel = Channel(state=descriptor(identity=other))
        monkeypatch.setattr(api, "_channel_for", lambda config, session_dir: channel)
        # Static admission is a gate, so the binding check — the subject here — is only reachable with
        # every static check passing. The menu dispatch is the one a recording activation must compose.
        report = module.activation_report(
            table=table(),
            table_path=host_dir(tmp_path),
            menu_dispatch=lambda call: {"ok": True},
        )
        assert report.ready is False
        assert "binding" in report.failed()
        assert report.session_closed is True
