"""The guarded cycle is a *named* provider contract, not an inference.

:class:`~udv_echo_process.acquire.cycle.RoutineCycle` already refuses an unbound or unguarded
invocation, but until now nothing let a command select it.  These tests pin that seam: a host
module may export a ``guarded_cycle`` factory, the package calls it at most **once** per
construction, checks what it got, and refuses by name — on the ``ui`` route, without a module,
without that export, when the factory raises, when it returns something that is not a hardened
:class:`RoutineCycle`, when the cycle's own configuration check fails, and when its binding's
build digest disagrees with the table or the requested digest.

Two lines are drawn deliberately.  A programmatic caller may still inject any ``StoreCycle``;
only the **opt-in** path insists on ``RoutineCycle``, so a generic unguarded cycle can never be
mistaken for the hardened one.  And the flag selects the cycle, not an input-free run: the Store
dialog's ``Accept`` and the sweep's reset are still presses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from udv_echo_process.acquire import live
from udv_echo_process.acquire.actuator import ProcessMode, StripView
from udv_echo_process.acquire.bridge import (
    BRIDGE_TABLE_SCHEMA,
    BridgeTable,
    BridgeUnavailable,
    guarded_cycle_from,
    load_table,
)
from udv_echo_process.acquire.cycle import (
    CycleBinding,
    CycleReport,
    CycleRoutines,
    ObservedAddress,
    ProcessIdentity,
    RoutineCycle,
)

BUILD = "a" * 64
OTHER = "b" * 64
PID = 4242
CREATED_NS = 1_760_000_000_000_000_000

ROUTINES = CycleRoutines(record=0x71F034, store=0x71F060, form=0x6F2A10)


def binding(image_sha256: str = BUILD) -> CycleBinding:
    return CycleBinding(
        identity=ProcessIdentity(pid=PID, created_ns=CREATED_NS, image_sha256=image_sha256),
        owner=ObservedAddress(address=ROUTINES.form, source="primed census"),
        record=ObservedAddress(address=ROUTINES.record, source="table"),
        store=ObservedAddress(address=ROUTINES.store, source="table"),
    )


class Strip:
    """The three views a whole cycle reads: ready, then recording, then store."""

    def __init__(self) -> None:
        self.views = [StripView.READY, StripView.RECORDING, StripView.STORE]
        self.index = 0

    def __call__(self) -> StripView:
        view = self.views[min(self.index, len(self.views) - 1)]
        self.index += 1
        return view


class Dialog:
    """A store dialog that writes the block, which is what the cycle checks for."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def commit(self, name: str) -> bool:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{name}.BDD").write_bytes(b"block")
        return True


def cycle_arguments(directory: Path, **overrides: object) -> dict:
    """Everything a usable cycle needs, all of it fake — nothing here reads a process."""

    arguments: dict = {
        "caller": lambda address, form: {"ok": True},
        "routines": ROUTINES,
        "dialog": Dialog(directory),
        "binding": binding(),
        "identity": lambda: ProcessIdentity(
            pid=PID, created_ns=CREATED_NS, image_sha256=BUILD
        ),
        "owner_valid": lambda owner: owner == ROUTINES.form,
        "read_strip": Strip(),
        "decode": lambda path: 1,
        "measure_span": lambda path: 0.0,
        "poll_s": 0.0,
        "state_timeout_s": 0.0,
        "store_timeout_s": 0.0,
        "stop_settle_s": 0.0,
        "store_settle_s": 0.0,
        "sleep": lambda seconds: None,
    }
    arguments.update(overrides)
    return arguments


def good_cycle(directory: Path, **overrides: object) -> RoutineCycle:
    return RoutineCycle(**cycle_arguments(directory, **overrides))


def table_dict(image_sha256: str = BUILD) -> dict:
    return {
        "schema": BRIDGE_TABLE_SCHEMA,
        "image_sha256": image_sha256,
        "caption_prefix": "UDOP DOP3010",
        "abi": {"self": "eax", "sender": "edx", "stack_args": 0, "returns": "ret"},
        "dispatch": {"slot_pointer": 0x7812D0, "status_offset": 0x474},
        "operations": {
            "record": {"handler": 0x71F034, "code": 28, "signature": "558bec83c4f8"},
            "stop": {"handler": 0x71F034, "code": 28, "signature": "558bec83c4f8"},
            "store": {"handler": 0x71F060, "code": 29, "signature": "558bec83c4f8"},
        },
    }


def write_table(tmp_path: Path, image_sha256: str = BUILD) -> Path:
    path = tmp_path / "operations.json"
    path.write_text(json.dumps(table_dict(image_sha256)), encoding="utf-8")
    return path


def load_fixture_table(tmp_path: Path, image_sha256: str = BUILD) -> BridgeTable:
    return load_table(write_table(tmp_path, image_sha256))


class FakeInner:
    """The UI half, faked: it answers the one question the wrapper asks before a cycle."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.options = kwargs

    def process_mode_note(self, expected: ProcessMode) -> str | None:
        return None


#: A fake machine-local host module, generated into ``tmp_path`` with the paths it needs baked in.
#: Its ``dispatch`` raises: a guarded run that fell back to host press dispatch would fail loudly
#: instead of quietly recording through the legacy route.
HOST_SOURCE = '''
"""A fake machine-local host: the guarded-cycle contract, and a dispatch that must never run."""

from pathlib import Path

from udv_echo_process.acquire.actuator import StripView
from udv_echo_process.acquire.cycle import (
    CycleBinding,
    CycleRoutines,
    ObservedAddress,
    ProcessIdentity,
    RoutineCycle,
)

BUILD = "{build}"
STORE_DIR = Path({store_dir})
COUNT = Path({count})

ROUTINES = CycleRoutines(record=0x71F034, store=0x71F060, form=0x6F2A10)
IDENTITY = ProcessIdentity(
    pid=4242, created_ns=1760000000000000000, image_sha256=BUILD
)
BINDING = CycleBinding(
    identity=IDENTITY,
    owner=ObservedAddress(address=ROUTINES.form, source="primed census"),
    record=ObservedAddress(address=ROUTINES.record, source="table"),
    store=ObservedAddress(address=ROUTINES.store, source="table"),
)

FACTORY_CALLS = []


class Strip:
    def __init__(self):
        self.views = [StripView.READY, StripView.RECORDING, StripView.STORE]
        self.index = 0

    def __call__(self):
        view = self.views[min(self.index, len(self.views) - 1)]
        self.index += 1
        return view


class Dialog:
    def commit(self, name):
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        (STORE_DIR / (name + ".BDD")).write_bytes(b"block")
        return True


def guarded_cycle(*, table, table_path, target_digest, channel):
    FACTORY_CALLS.append(
        dict(
            table_digest=table.image_sha256,
            table_path=table_path,
            target_digest=target_digest,
            channel=channel,
        )
    )
    COUNT.write_text(str(len(FACTORY_CALLS)), encoding="utf-8")
    return RoutineCycle(
        caller=lambda address, form: dict(ok=True),
        routines=ROUTINES,
        dialog=Dialog(),
        binding=BINDING,
        identity=lambda: IDENTITY,
        owner_valid=lambda owner: owner == ROUTINES.form,
        read_strip=Strip(),
        decode=lambda path: 1,
        measure_span=lambda path: 0.0,
        poll_s=0.0,
        state_timeout_s=0.0,
        store_timeout_s=0.0,
        stop_settle_s=0.0,
        store_settle_s=0.0,
        sleep=lambda seconds: None,
    )


def dispatch(request):
    raise AssertionError(
        "the legacy dispatch must not run when the guarded cycle is selected"
    )
'''


def write_host(tmp_path: Path, store_dir: Path, *, with_dispatch: bool = True) -> tuple[Path, Path]:
    """Write the fake host module and return it with the file its factory counts into."""

    module = tmp_path / ("host.py" if with_dispatch else "factory-only.py")
    count = tmp_path / "factory-calls.txt"
    source = HOST_SOURCE.format(
        build=BUILD, store_dir=repr(str(store_dir)), count=repr(str(count))
    )
    if not with_dispatch:
        source = source.replace("def dispatch(request):", "def _dispatch(request):")
    module.write_text(source, encoding="utf-8")
    return module, count


class TestTheFactoryContract:
    """What the export may be, and every way it can be refused by name."""

    def test_an_absent_factory_is_named(self, tmp_path):
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(None, table=load_fixture_table(tmp_path))
        assert caught.value.reason == "bridge_guarded_cycle_factory_missing:guarded_cycle"

    def test_a_non_callable_export_is_named(self, tmp_path):
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from("not a factory", table=load_fixture_table(tmp_path))
        assert caught.value.reason == "bridge_guarded_cycle_factory_invalid:guarded_cycle"

    def test_a_raising_factory_is_named_and_not_propagated(self, tmp_path):
        def factory(**kwargs):
            raise RuntimeError("the instrument is not running")

        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(factory, table=load_fixture_table(tmp_path))
        assert caught.value.reason == "bridge_guarded_cycle_factory_raised:RuntimeError"

    def test_a_generic_unguarded_store_cycle_is_not_accepted(self, tmp_path):
        """The opt-in path cannot silently take a cycle that never hardened itself."""

        class GenericStoreCycle:
            def try_record_and_store(
                self, name, duration_s, directory, *, expected_mode=None
            ):
                return True, Path("somewhere.BDD")

        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(
                lambda **kwargs: GenericStoreCycle(), table=load_fixture_table(tmp_path)
            )
        assert caught.value.reason == "bridge_guarded_cycle_invalid:GenericStoreCycle"

    def test_a_return_that_is_not_an_object_at_all_is_named(self, tmp_path):
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(lambda **kwargs: "cycle", table=load_fixture_table(tmp_path))
        assert caught.value.reason == "bridge_guarded_cycle_invalid:str"

    def test_a_cycle_without_a_binding_is_unusable(self, tmp_path):
        cycle = good_cycle(tmp_path, binding=None)
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(lambda **kwargs: cycle, table=load_fixture_table(tmp_path))
        assert caught.value.reason == "bridge_guarded_cycle_unusable:cycle_binding_missing"

    @pytest.mark.parametrize("missing", ["identity", "owner_valid", "read_strip"])
    def test_a_missing_guard_is_named(self, tmp_path, missing):
        cycle = good_cycle(tmp_path, **{missing: None})
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(lambda **kwargs: cycle, table=load_fixture_table(tmp_path))
        assert (
            caught.value.reason
            == f"bridge_guarded_cycle_unusable:cycle_guard_missing:{missing}"
        )

    def test_a_cycle_whose_own_check_raises_is_named(self, tmp_path):
        class Breaking(RoutineCycle):
            def configuration_problem(self):
                raise RuntimeError("boom")

        cycle = Breaking(**cycle_arguments(tmp_path))
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(lambda **kwargs: cycle, table=load_fixture_table(tmp_path))
        assert caught.value.reason == (
            "bridge_guarded_cycle_unusable:configuration_problem_raised:RuntimeError"
        )

    def test_a_binding_measured_on_another_build_is_a_conflict(self, tmp_path):
        cycle = good_cycle(tmp_path, binding=binding(OTHER))
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(lambda **kwargs: cycle, table=load_fixture_table(tmp_path))
        assert caught.value.reason == (
            f"bridge_guarded_cycle_digest_conflict:binding:{OTHER[:12]}!={BUILD[:12]}"
        )

    def test_a_requested_digest_that_contradicts_the_table_is_a_conflict(self, tmp_path):
        cycle = good_cycle(tmp_path)
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(
                lambda **kwargs: cycle,
                table=load_fixture_table(tmp_path),
                target_digest=OTHER,
            )
        assert caught.value.reason == (
            f"bridge_guarded_cycle_digest_conflict:table:{BUILD[:12]}!={OTHER[:12]}"
        )

    def test_a_table_digest_conflict_is_refused_before_the_host_is_called(self, tmp_path):
        """A comparison between two values the package already holds needs no host.

        The host factory is the one thing that *may* touch the running application (it is how a
        binding is observed), so a request whose declared digest already contradicts the table must
        be refused without calling it at all: nothing about the refusal depends on the host, and an
        unwarranted construction is application access a caller never asked for.
        """
        calls: list[dict] = []

        def spy(**kwargs):
            calls.append(kwargs)
            return good_cycle(tmp_path)

        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(
                spy, table=load_fixture_table(tmp_path), target_digest=OTHER
            )

        assert caught.value.reason == (
            f"bridge_guarded_cycle_digest_conflict:table:{BUILD[:12]}!={OTHER[:12]}"
        )
        assert calls == [], "the host factory must not be invoked for a static refusal"

    def test_the_binding_digest_check_still_needs_the_factory(self, tmp_path):
        """The other half of the digest rule is about the *returned* cycle, so it runs after.

        The split is deliberate: only the table half is static. The binding half compares against a
        cycle that does not exist until the host has built it, so the factory is called exactly once
        and the refusal is still named.
        """
        calls: list[dict] = []

        def factory(**kwargs):
            calls.append(kwargs)
            return good_cycle(tmp_path, binding=binding(OTHER))

        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(factory, table=load_fixture_table(tmp_path))

        assert caught.value.reason == (
            f"bridge_guarded_cycle_digest_conflict:binding:{OTHER[:12]}!={BUILD[:12]}"
        )
        assert len(calls) == 1, "the binding check cannot run before there is a binding"

    def test_a_requested_digest_that_the_binding_does_not_carry_is_a_conflict(self, tmp_path):
        cycle = good_cycle(tmp_path, binding=binding(OTHER))
        with pytest.raises(BridgeUnavailable) as caught:
            guarded_cycle_from(
                lambda **kwargs: cycle,
                table=load_fixture_table(tmp_path),
                target_digest=BUILD,
            )
        assert caught.value.reason == (
            f"bridge_guarded_cycle_digest_conflict:binding:{OTHER[:12]}!={BUILD[:12]}"
        )

    def test_a_usable_cycle_is_returned_unchanged(self, tmp_path):
        cycle = good_cycle(tmp_path)
        assert (
            guarded_cycle_from(lambda **kwargs: cycle, table=load_fixture_table(tmp_path))
            is cycle
        )

    def test_the_factory_is_called_once_with_the_documented_keywords(self, tmp_path):
        seen: list[dict] = []

        def factory(**kwargs):
            seen.append(kwargs)
            return good_cycle(tmp_path)

        guarded_cycle_from(
            factory,
            table=load_fixture_table(tmp_path),
            table_path="operations.json",
            target_digest=BUILD,
            channel=3,
        )
        assert len(seen) == 1
        assert set(seen[0]) == {"table", "table_path", "target_digest", "channel"}
        assert seen[0]["table_path"] == "operations.json"
        assert seen[0]["target_digest"] == BUILD
        assert seen[0]["channel"] == 3


class TestTheRoute:
    """The flag is a route decision, refused before anything touches the application."""

    def test_the_ui_route_refuses_the_guarded_flag(self):
        with pytest.raises(BridgeUnavailable) as caught:
            live.actuator_for("ui", guarded_cycle=True)
        assert caught.value.reason == "bridge_guarded_cycle_route:ui"

    def test_an_unknown_route_is_still_an_error(self):
        with pytest.raises(ValueError) as caught:
            live.actuator_for("auto", guarded_cycle=True)
        assert "ui" in str(caught.value) and "bridge" in str(caught.value)

    def test_a_host_without_the_module_is_named(self, tmp_path):
        with pytest.raises(BridgeUnavailable) as caught:
            live.bridge_actuator(
                runner_path=tmp_path / "absent.py",
                table_path=write_table(tmp_path),
                guarded_cycle=True,
            )
        assert caught.value.reason == "bridge_guarded_cycle_factory_missing:module"

    def test_a_module_without_the_export_is_named(self, tmp_path):
        module = tmp_path / "legacy-host.py"
        module.write_text(
            "def dispatch(request):\n    return {}\n", encoding="utf-8"
        )
        with pytest.raises(BridgeUnavailable) as caught:
            live.bridge_actuator(
                runner_path=module,
                table_path=write_table(tmp_path),
                guarded_cycle=True,
            )
        assert caught.value.reason == "bridge_guarded_cycle_factory_missing:guarded_cycle"

    def test_an_injected_cycle_and_the_flag_are_a_conflict(self, tmp_path):
        """Two selections for one route is ambiguous, and neither may win silently."""

        class Injected:
            def try_record_and_store(
                self, name, duration_s, directory, *, expected_mode=None
            ):
                return False, "never called"

        with pytest.raises(BridgeUnavailable) as caught:
            live.bridge_actuator(
                table_path=write_table(tmp_path),
                guarded_cycle=True,
                cycle=Injected(),
            )
        assert caught.value.reason == "bridge_guarded_cycle_conflict:cycle"


class TestTheEndToEndPath:
    """The flag and the factory reached through the public commands, not a MagicMock."""

    def test_a_point_through_a_fake_host_module_stores(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        store.mkdir()
        host, count = write_host(tmp_path, store)
        monkeypatch.setattr(live, "Win32Actuator", FakeInner)

        ok, outcome = live.point(
            "guarded-01",
            1.0,
            store,
            None,
            expected_mode=ProcessMode.INSTRUMENT,
            route="bridge",
            table_path=write_table(tmp_path),
            runner_path=host,
            target_digest=BUILD,
            guarded_cycle=True,
        )

        assert ok is True, outcome
        assert Path(outcome) == store / "guarded-01.BDD"
        assert Path(outcome).read_bytes() == b"block"
        assert count.read_text(encoding="utf-8") == "1", "the factory ran exactly once"

    def test_the_guarded_cycle_report_is_exposed_on_the_actuator(
        self, tmp_path, monkeypatch
    ):
        store = tmp_path / "store"
        store.mkdir()
        host, _count = write_host(tmp_path, store)
        monkeypatch.setattr(live, "Win32Actuator", FakeInner)
        actuator = live.bridge_actuator(
            table_path=write_table(tmp_path),
            runner_path=host,
            target_digest=BUILD,
            guarded_cycle=True,
        )
        assert actuator.last_cycle_report is None

        ok, outcome = actuator.try_record_and_store(
            "guarded-02", 1.0, store, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is True, outcome
        assert isinstance(actuator.last_cycle_report, CycleReport)
        assert actuator.last_cycle_report.name == "guarded-02"
        assert actuator.last_cycle_report.stored is True

    def test_a_sweep_through_a_fake_host_module_stores(self, tmp_path, monkeypatch):
        store = tmp_path / "store"
        store.mkdir()
        host, count = write_host(tmp_path, store)
        seen: dict = {}

        class Runner:
            def __init__(self, actuator, settings, store_dir, **kwargs):
                seen["actuator"] = actuator
                seen["store_dir"] = Path(store_dir)

            def run(self, definition, seconds):
                ok, outcome = seen["actuator"].try_record_and_store(
                    "guarded-sweep-k1",
                    1.0,
                    seen["store_dir"],
                    expected_mode=ProcessMode.INSTRUMENT,
                )
                seen["result"] = (ok, outcome)
                return ()

        monkeypatch.setattr(live, "SweepRunner", Runner)
        monkeypatch.setattr(live, "Win32Actuator", FakeInner)

        live.sweep(
            1.0,
            store,
            [1],
            None,
            expected_mode=ProcessMode.INSTRUMENT,
            route="bridge",
            table_path=write_table(tmp_path),
            runner_path=host,
            target_digest=BUILD,
            guarded_cycle=True,
        )

        ok, outcome = seen["result"]
        assert ok is True, outcome
        assert Path(outcome) == store / "guarded-sweep-k1.BDD"
        assert count.read_text(encoding="utf-8") == "1"

    def test_without_the_flag_the_factory_is_never_consulted(self, tmp_path, monkeypatch):
        """The legacy bridge path keeps its own refusal; the new export is not a substitute."""

        store = tmp_path / "store"
        store.mkdir()
        host, count = write_host(tmp_path, store, with_dispatch=False)
        monkeypatch.setattr(live, "Win32Actuator", FakeInner)

        ok, reason = live.point(
            "legacy-01",
            1.0,
            store,
            None,
            expected_mode=ProcessMode.INSTRUMENT,
            route="bridge",
            table_path=write_table(tmp_path),
            runner_path=host,
            target_digest=BUILD,
        )

        assert ok is False
        assert reason == "bridge_runner_not_configured"
        assert not count.exists(), "the guarded factory must not be called without the flag"
