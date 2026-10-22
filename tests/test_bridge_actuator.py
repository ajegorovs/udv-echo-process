"""The bridge actuator: the proven record/store half behind the ``SweepActuator`` port.

Every vendor fact this route needs (handler addresses, command codes, ABI, the dispatch slot) lives in
a **machine-local** table, never in this repository, and the execution that patches another process
lives behind a callable the operator supplies.  What this module owns is the interface, the evidence
contract and the refusals — so the tests here use a fake table and a fake dispatch, and no vendor
process, device or screen is involved.

The refusals are the point of the suite.  A route that can only be trusted when it succeeds is not a
route: each precondition below must refuse *by name*, before anything is dispatched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire.actuator import ProcessMode
from udv_echo_process.acquire.bridge import (
    BRIDGE_OPERATIONS_REQUIRED,
    BRIDGE_TABLE_SCHEMA,
    BridgeActuator,
    BridgeRefused,
    BridgeSetter,
    BridgeUnavailable,
    load_table,
)

BUILD = "a" * 64


def table_dict(**overrides) -> dict:
    table = {
        "schema": BRIDGE_TABLE_SCHEMA,
        "image_sha256": BUILD,
        "caption_prefix": "UDOP DOP3010",
        "abi": {"self": "eax", "sender": "edx", "stack_args": 0, "returns": "ret"},
        "dispatch": {"slot_pointer": 0x7812D0, "status_offset": 0x474},
        "operations": {
            "record": {"handler": 0x71F034, "code": 28, "signature": "558bec83c4f8"},
            "stop": {"handler": 0x71F034, "code": 28, "signature": "558bec83c4f8"},
            "store": {"handler": 0x71F060, "code": 29, "signature": "558bec83c4f8"},
        },
    }
    table.update(overrides)
    return table


class Inner:
    """The UI half, delegated to.  Records what it was asked for and presses nothing."""

    def __init__(
        self, mode_note: str | None = None, values: dict | None = None
    ) -> None:
        self.mode_note = mode_note
        self.calls: list[tuple[str, tuple, dict]] = []
        #: Scripted parameter texts, consumed read by read, last entry repeating.
        self.script = {role: list(texts) for role, texts in (values or {}).items()}
        self.current = {role: texts[0] for role, texts in (values or {}).items()}

    def process_mode_note(self, expected: ProcessMode) -> str | None:
        self.calls.append(("process_mode_note", (expected,), {}))
        return self.mode_note

    def read_parameter(self, role):
        self.calls.append(("read_parameter", (role,), {}))
        sequence = self.script.get(role)
        if sequence:
            value = sequence.pop(0) if len(sequence) > 1 else sequence[0]
            self.current[role] = value
            return value
        return self.current.get(role, "50")

    def write_parameter(self, role, value):
        self.calls.append(("write_parameter", (role, value), {}))

    def apply_point(self, parameters):
        self.calls.append(("apply_point", (parameters,), {}))
        return {}

    def press(self, control):
        self.calls.append(("press", (control,), {}))

    def wait_for_view(self, views, *, timeout_s):
        self.calls.append(("wait_for_view", (views,), {"timeout_s": timeout_s}))
        return "ready"

    def layout_note(self):
        return None


class Dispatch:
    """The machine-local execution, faked: it returns the report the route produces.

    A report may be produced at call time: a real dispatch stores the file it reports, so a fixture
    that created the artifact before the call would trip the name precondition instead of testing
    what the test names.
    """

    def __init__(self, report: dict | None = None, factory=None) -> None:
        self.requests = []
        self.report = report
        self.factory = factory

    def __call__(self, request):
        self.requests.append(request)
        if self.factory is not None:
            self.report = self.factory()
        return self.report


def stored_report(
    directory: Path,
    name: str,
    *,
    content: bytes = b"\x01\x02\x03",
    config_matches: bool = True,
    identity_unchanged: bool = True,
    tamper: bytes | None = None,
) -> dict:
    path = directory / f"{name}.BDD"
    path.write_bytes(content)
    report = {
        "ok": True,
        "outcome": "record_verified",
        "blockers": [],
        "decoded": {
            "profiles": 302,
            "gates": 42,
            "emissions_per_profile": 50,
            "config_matches": config_matches,
        },
        "stored": {
            "stored": True,
            "stored_path": str(path),
            "stored_sha256": hashlib.sha256(content).hexdigest(),
            "stored_bytes": len(content),
        },
        "identity_unchanged": identity_unchanged,
    }
    if tamper is not None:
        # The report is honest about what was stored; the file then changes underneath it.
        path.write_bytes(tamper)
    return report


def actuator(
    tmp_path: Path, *, report=None, inner=None, dispatch=None, digest=BUILD, table=None
) -> tuple[BridgeActuator, Dispatch, Inner]:
    path = tmp_path / "operations.json"
    path.write_text(
        json.dumps(table if table is not None else table_dict()), encoding="utf-8"
    )
    fake_dispatch = dispatch if dispatch is not None else Dispatch(report)
    inner = inner or Inner()
    return (
        BridgeActuator(
            inner, dispatch=fake_dispatch, table_path=path, target_digest=digest
        ),
        fake_dispatch,
        inner,
    )


class TestTheTable:
    def test_the_table_loads_and_names_its_operations(self, tmp_path):
        path = tmp_path / "operations.json"
        path.write_text(json.dumps(table_dict()), encoding="utf-8")
        table = load_table(path)
        assert table.image_sha256 == BUILD
        assert set(table.operations) >= set(BRIDGE_OPERATIONS_REQUIRED)
        assert table.operations["record"].code == 28

    def test_a_missing_table_refuses_by_name(self, tmp_path):
        with pytest.raises(BridgeUnavailable) as caught:
            load_table(tmp_path / "absent.json")
        assert caught.value.reason.startswith("bridge_table_missing:")

    def test_an_unset_table_location_refuses_rather_than_searching(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("UDV_BRIDGE_TABLE", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing-here"))
        with pytest.raises(BridgeUnavailable) as caught:
            load_table()
        assert caught.value.reason == "bridge_table_not_configured"

    def test_the_default_location_is_used_when_it_exists(self, monkeypatch, tmp_path):
        """The branch a real host takes: nothing configured, the table where the default says."""
        local = tmp_path / "localappdata"
        (local / "udv-bridge").mkdir(parents=True)
        (local / "udv-bridge" / "operations.json").write_text(
            json.dumps(table_dict()), encoding="utf-8"
        )
        monkeypatch.delenv("UDV_BRIDGE_TABLE", raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(local))

        table = load_table()

        assert table.image_sha256 == BUILD

    def test_the_variable_beats_the_default_location(self, monkeypatch, tmp_path):
        local = tmp_path / "localappdata"
        (local / "udv-bridge").mkdir(parents=True)
        (local / "udv-bridge" / "operations.json").write_text(
            json.dumps(table_dict(image_sha256="f" * 64)), encoding="utf-8"
        )
        chosen = tmp_path / "chosen.json"
        chosen.write_text(json.dumps(table_dict()), encoding="utf-8")
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("UDV_BRIDGE_TABLE", str(chosen))

        assert load_table().image_sha256 == BUILD

    def test_a_foreign_schema_is_refused_not_migrated(self, tmp_path):
        path = tmp_path / "operations.json"
        path.write_text(
            json.dumps(table_dict(schema="udv-bridge-operations-v0")), encoding="utf-8"
        )
        with pytest.raises(BridgeUnavailable) as caught:
            load_table(path)
        assert caught.value.reason == "bridge_table_schema:udv-bridge-operations-v0"

    def test_a_table_missing_a_required_operation_is_refused(self, tmp_path):
        incomplete = table_dict()
        del incomplete["operations"]["store"]
        path = tmp_path / "operations.json"
        path.write_text(json.dumps(incomplete), encoding="utf-8")
        with pytest.raises(BridgeUnavailable) as caught:
            load_table(path)
        assert caught.value.reason == "bridge_table_operation:store"

    def test_a_table_with_a_stray_field_is_refused(self, tmp_path):
        path = tmp_path / "operations.json"
        path.write_text(json.dumps(table_dict(extra_field=True)), encoding="utf-8")
        with pytest.raises(BridgeUnavailable) as caught:
            load_table(path)
        assert caught.value.reason.startswith("bridge_table_invalid:")


class TestThePoint:
    def test_a_point_is_dispatched_and_returns_the_stored_path(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, inner = actuator(tmp_path)
        dispatch.factory = lambda: stored_report(directory, "point-01")

        ok, evidence = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is True
        assert evidence == directory / "point-01.BDD"
        (request,) = dispatch.requests
        assert request.name == "point-01"
        assert request.duration_s == 12.0
        assert request.expected_mode == ProcessMode.INSTRUMENT.value
        assert request.table_digest == BUILD
        assert "record" in request.operations and "store" in request.operations
        # The mode expectation is checked in-process, before the dispatch, so a wrong screen never
        # reaches the route that would record on it.
        assert inner.calls and inner.calls[0][0] == "process_mode_note"

    def test_a_caption_the_expectation_contradicts_refuses_before_the_dispatch(
        self, tmp_path
    ):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, _ = actuator(
            tmp_path, inner=Inner(mode_note="caption says 'UDOP Simul'")
        )

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason.startswith("bridge_mode_mismatch:")
        assert dispatch.requests == []

    def test_an_existing_name_refuses_before_the_dispatch(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        (directory / "point-01.BDD").write_bytes(b"older")
        bridge, dispatch, _ = actuator(tmp_path)

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason.startswith("store_name_taken:")
        assert dispatch.requests == []

    def test_no_dispatch_configured_refuses_rather_than_recording(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        path = tmp_path / "operations.json"
        path.write_text(json.dumps(table_dict()), encoding="utf-8")
        bridge = BridgeActuator(
            Inner(), dispatch=None, table_path=path, target_digest=BUILD
        )

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason == "bridge_runner_not_configured"

    def test_a_table_from_another_build_refuses_by_digest(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, _ = actuator(tmp_path, digest="b" * 64)

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason == "bridge_digest_unknown:" + "b" * 64
        assert dispatch.requests == []

    def test_a_runner_that_did_not_store_returns_its_reason(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, _ = actuator(
            tmp_path,
            report={
                "ok": False,
                "stored": {"stored": False, "reason": "overlay refused"},
            },
        )
        dispatch.report = {
            "ok": False,
            "stored": {"stored": False, "reason": "overlay refused"},
        }

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason == "overlay refused"

    def test_a_decode_that_does_not_match_the_request_is_a_failure(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, _ = actuator(tmp_path)
        dispatch.factory = lambda: stored_report(
            directory, "point-01", config_matches=False
        )

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason == "bridge_decode_mismatch"

    def test_a_changed_target_identity_is_a_failure(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, _ = actuator(tmp_path)
        dispatch.factory = lambda: stored_report(
            directory, "point-01", identity_unchanged=False
        )

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason == "bridge_identity_changed"

    def test_evidence_missing_a_key_is_named(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()

        def report_without_a_path():
            report = stored_report(directory, "point-01")
            del report["stored"]["stored_path"]
            return report

        bridge, dispatch, _ = actuator(tmp_path)
        dispatch.factory = report_without_a_path

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason == "bridge_evidence_incomplete:stored_path"

    def test_an_artifact_whose_digest_disagrees_is_refused(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, _ = actuator(tmp_path)
        dispatch.factory = lambda: stored_report(
            directory, "point-01", tamper=b"rewritten after the store"
        )

        ok, reason = bridge.try_record_and_store(
            "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason.startswith("bridge_artifact_mismatch:")

    def test_the_composed_call_raises_the_same_reason(self, tmp_path):
        directory = tmp_path / "store"
        directory.mkdir()
        bridge, dispatch, _ = actuator(tmp_path)
        dispatch.factory = lambda: stored_report(
            directory, "point-01", config_matches=False
        )

        with pytest.raises(BridgeRefused) as caught:
            bridge.record_and_store(
                "point-01", 12.0, directory, expected_mode=ProcessMode.INSTRUMENT
            )

        assert caught.value.reason == "bridge_decode_mismatch"


class TestDelegation:
    def test_primitives_go_to_the_inner_actuator_unchanged(self, tmp_path):
        bridge, _, inner = actuator(tmp_path)

        assert bridge.read_parameter("emissions") == "50"
        bridge.apply_point({"gates": 42})
        bridge.press("stop")
        bridge.wait_for_view(("ready",), timeout_s=5)

        assert [call[0] for call in inner.calls] == [
            "read_parameter",
            "apply_point",
            "press",
            "wait_for_view",
        ]

    def test_the_route_is_not_reimplemented_here(self, tmp_path):
        """Only the cycle is overridden; a missing primitive must be the inner's absence too."""
        bridge, _, _ = actuator(tmp_path)
        with pytest.raises(AttributeError):
            bridge.something_the_inner_does_not_have()


class TestSelection:
    """The route is opt-in: a host without the table or the dispatch refuses, it does not guess."""

    def test_no_runner_configured_is_none_not_a_fallback(self, monkeypatch):
        from udv_echo_process.acquire.live import bridge_dispatch

        monkeypatch.delenv("UDV_BRIDGE_RUNNER", raising=False)
        assert bridge_dispatch() is None

    def test_a_named_runner_module_is_loaded(self, tmp_path):
        from udv_echo_process.acquire.live import bridge_dispatch

        module = tmp_path / "runner_mod.py"
        module.write_text(
            "def dispatch(request):\n    return {'stored': {'stored': False}}\n",
            encoding="utf-8",
        )
        loaded = bridge_dispatch(module)
        assert callable(loaded)
        assert loaded({})["stored"]["stored"] is False

    def test_a_module_without_dispatch_is_not_a_runner(self, tmp_path):
        from udv_echo_process.acquire.live import bridge_dispatch

        module = tmp_path / "not_a_runner.py"
        module.write_text("X = 1\n", encoding="utf-8")
        assert bridge_dispatch(module) is None

    def test_a_missing_runner_path_is_none(self, tmp_path):
        from udv_echo_process.acquire.live import bridge_dispatch

        assert bridge_dispatch(tmp_path / "absent.py") is None

    def test_the_wrapper_answers_every_method_the_sweep_port_names(self, tmp_path):
        """A delegated method is still the port's method: nothing may be missing because it is not
        reimplemented here."""
        from udv_echo_process.acquire.actuator import Actuator
        from udv_echo_process.acquire.runner import SweepActuator

        bridge, _, inner = actuator(tmp_path)
        port = {
            name: member
            for base in (Actuator, SweepActuator)
            for name, member in vars(base).items()
            if callable(member) and not name.startswith("_")
        }
        # Stub whatever this fake does not implement, so the check is about the wrapper's exposure
        # rather than about how complete the fake is.
        for name in port:
            if not hasattr(inner, name):
                setattr(inner, name, lambda *args, **kwargs: None)

        missing = [name for name in port if not hasattr(bridge, name)]
        assert missing == []
        # Deliberately *not* asserted: ``isinstance(bridge, Actuator)``.  CPython resolves a
        # runtime-checkable protocol's members statically, so a proxy that delegates through
        # ``__getattr__`` answers every call and still fails the check.  Nothing in ``acquire``
        # isinstance-checks the port (verified), and the runner calls the methods directly — but a
        # future reader must not "fix" this by trusting the isinstance result either way.

    def test_the_bridge_is_a_separate_entry_point(self):
        import inspect

        live_module = pytest.importorskip("udv_echo_process.acquire.live")
        # The default construction path is unchanged; the bridge has its own function, so no caller
        # gains the route by accident.
        assert "route" not in inspect.signature(live_module.live_actuator).parameters
        parameters = inspect.signature(live_module.bridge_actuator).parameters
        assert {"table_path", "runner_path", "target_digest"} <= set(parameters)


class TestNumericWritesAreDeclaredNotWired:
    """P3's boundary, pinned: the refusal surface exists, and nothing writes a parameter yet.

    The live numeric write waits on a decision about how a half-applied value is undone, so the safest
    possible state is one where a caller cannot accidentally get a partial write: every path here either
    refuses by name or delegates the GUI's own write.
    """

    def test_the_switch_is_required_before_anything_else_is_considered(self, tmp_path):
        bridge, _, _ = actuator(tmp_path)
        assert bridge.value_write_blocker("emissions_per_profile", 49) == (
            "bridge_numeric_writes_not_enabled"
        )

    def test_a_parameter_without_a_setter_is_named(self, tmp_path):
        bridge, _, _ = actuator(tmp_path)
        bridge._numeric_writes = True
        assert bridge.value_write_blocker("emissions_per_profile", 49) == (
            "bridge_setter_missing:emissions_per_profile"
        )

    def test_a_configured_setter_still_has_bounds(self, tmp_path):
        table = table_dict()
        table["setters"] = {
            "emissions_per_profile": {
                "setter": 0x61A000,
                "notify": 0x61A100,
                "minimum": 8,
                "maximum": 128,
            }
        }
        bridge, _, _ = actuator(tmp_path, table=table)
        bridge._numeric_writes = True
        assert bridge.value_write_blocker("emissions_per_profile", 49) is None
        assert bridge.value_write_blocker("emissions_per_profile", 7).startswith(
            "bridge_value_out_of_range:"
        )
        assert bridge.value_write_blocker("emissions_per_profile", 129).startswith(
            "bridge_value_out_of_range:"
        )

    def test_the_setter_model_is_strict_about_unknown_fields(self):
        with pytest.raises(ValidationError):
            BridgeSetter(setter=1, notify=2, not_a_field=True)

    def test_without_a_value_dispatch_the_write_is_refused_not_attempted(
        self, tmp_path
    ):
        table = table_dict()
        table["setters"] = {"emissions_per_profile": {"setter": 1, "notify": 2}}
        bridge, _, _ = actuator(tmp_path, table=table)
        bridge._numeric_writes = True
        with pytest.raises(BridgeRefused) as caught:
            bridge.write_parameter("emissions_per_profile", "49")
        assert caught.value.reason == "bridge_value_runner_not_configured"

    def test_a_non_numeric_value_is_refused_rather_than_typed(self, tmp_path):
        bridge, _, _ = actuator(tmp_path)
        bridge._numeric_writes = True
        with pytest.raises(BridgeRefused) as caught:
            bridge.write_parameter("emissions_per_profile", "auto")
        assert caught.value.reason.startswith("bridge_value_not_numeric:")

    def test_the_default_path_is_still_the_gui_write(self, tmp_path):
        """P1's behaviour: without the switch, every write is the inner actuator's, unchanged."""
        bridge, _, inner = actuator(tmp_path)
        bridge.write_parameter("emissions_per_profile", "49")
        assert inner.calls[-1][0] == "write_parameter"


class ValueDispatch:
    """The machine-local numeric commit, faked: it moves the field the way the application would."""

    def __init__(
        self, inner: Inner, *, apply: bool = True, restore_changes: bool = True
    ) -> None:
        self.inner = inner
        self.apply = apply
        self.restore_changes = restore_changes
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        role = request.role
        if not self.apply:
            return {
                "committed": True,
                "setter_calls": 1,
                "readback": self.inner.current.get(role),
            }
        first = len([r for r in self.requests if r.role == role]) == 1
        if first or self.restore_changes:
            self.inner.script[role] = [f"{request.value:g}"]
            self.inner.current[role] = f"{request.value:g}"
        return {
            "committed": True,
            "setter_calls": 1,
            "readback": self.inner.current.get(role),
        }


def value_bridge(tmp_path, *, values, **dispatch_options):
    table = table_dict()
    table["setters"] = {
        "emissions_per_profile": {
            "setter": 0x61A000,
            "notify": 0x61A100,
            "minimum": 8,
            "maximum": 128,
        }
    }
    inner = Inner(values=values)
    dispatch = ValueDispatch(inner, **dispatch_options)
    path = tmp_path / "operations.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    bridge = BridgeActuator(
        inner,
        dispatch=Dispatch(),
        value_dispatch=dispatch,
        table_path=path,
        target_digest=BUILD,
        numeric_writes=True,
    )
    return bridge, dispatch, inner


class TestAGuardedNumericWrite:
    """The agreed policy: verify against the application's own text, restore through the same setter."""

    def test_a_write_the_field_confirms_is_accepted(self, tmp_path):
        bridge, dispatch, inner = value_bridge(
            tmp_path, values={"emissions_per_profile": ["50"]}
        )

        bridge.write_parameter("emissions_per_profile", "49")

        assert len(dispatch.requests) == 1
        request = dispatch.requests[0]
        assert (request.role, request.value, request.previous) == (
            "emissions_per_profile",
            49.0,
            "50",
        )
        assert request.table_digest == BUILD
        assert request.setter == 0x61A000 and request.notify == 0x61A100
        assert bridge.value_writes[-1]["verified"] is True
        reads = [call for call in inner.calls if call[0] == "read_parameter"]
        assert len(reads) == 2  # one before the write, one after it

    def test_a_mismatch_is_repaired_through_the_gui_write_not_a_second_dispatch(self, tmp_path):
        """One attach can commit twice; a fresh one cannot commit again, with identical addresses and
        state (measured 2026-10-22). So the repair uses the reliable mechanism, not the failing one.
        """
        bridge, dispatch, inner = value_bridge(
            tmp_path, values={"emissions_per_profile": ["50"]}, apply=False
        )

        with pytest.raises(BridgeRefused) as caught:
            bridge.write_parameter("emissions_per_profile", "49")

        assert caught.value.reason == "bridge_write_rolled_back:emissions_per_profile:49.0->50"
        # Exactly one dispatch — the write. The repair is the GUI's, and the record says so.
        assert [request.value for request in dispatch.requests] == [49.0]
        assert ("write_parameter", ("emissions_per_profile", "50"), {}) in inner.calls
        assert bridge.value_writes[-1]["restored"] is True
        assert bridge._poisoned is None

    def test_an_unverified_restore_poisons_the_actuator(self, tmp_path):
        # The field says 50 before the write, 51 afterwards, and 51 again after the restore: the
        # dispatch moved it somewhere nobody asked for and the restore did not bring it back.
        bridge, dispatch, inner = value_bridge(
            tmp_path,
            values={"emissions_per_profile": ["50", "51"]},
            apply=False,
            restore_changes=False,
        )

        with pytest.raises(BridgeRefused) as caught:
            bridge.write_parameter("emissions_per_profile", "49")
        repairs = [call for call in inner.calls if call[0] == "write_parameter"]

        assert caught.value.reason.startswith(
            "bridge_write_unverified:emissions_per_profile:"
        )
        assert bridge._poisoned is not None
        with pytest.raises(BridgeRefused) as again:
            bridge.write_parameter("emissions_per_profile", "49")
        assert again.value.reason.startswith("bridge_writes_poisoned:")
        # One dispatch (the write) and one GUI repair attempt, then nothing: the actuator is poisoned.
        assert len(dispatch.requests) == 1
        assert len(repairs) == 1

    def test_a_poisoned_actuator_does_not_dispatch_at_all(self, tmp_path):
        bridge, dispatch, _ = value_bridge(
            tmp_path, values={"emissions_per_profile": ["50"]}
        )
        bridge._poisoned = "emissions_per_profile:51"
        with pytest.raises(BridgeRefused):
            bridge.write_parameter("emissions_per_profile", "49")
        assert dispatch.requests == []


    def test_a_write_of_the_value_already_present_is_a_no_op_not_a_transition(self, tmp_path):
        """A read-back cannot distinguish "it worked" from "it was already so" — so it is not claimed."""
        bridge, dispatch, _inner = value_bridge(tmp_path, values={"emissions_per_profile": ["50"]})

        bridge.write_parameter("emissions_per_profile", "50")

        assert dispatch.requests == []  # nothing was dispatched
        entry = bridge.value_writes[-1]
        assert entry["unchanged"] is True and entry["verified"] is False
