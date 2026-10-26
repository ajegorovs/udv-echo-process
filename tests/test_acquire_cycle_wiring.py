"""The composed cycle has to be reachable from the package's own commands, not only from a probe.

`live.sweep` is the composed path a campaign uses: rungs, plan validation, per-point log. For the message route to be
more than a demonstration, that function has to carry a caller-supplied cycle down to the wrapper, which is the same seam
`numeric_writes` uses. These tests pin the forwarding at each step a caller meets: the factory, the sweep, the single
point, and the wrapper itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.acquire import live
from udv_echo_process.acquire.actuator import ProcessMode
from udv_echo_process.acquire.bridge import BridgeActuator, BridgeUnavailable
from udv_echo_process.acquire.cycle import CycleReport, CycleStage


class Cycle:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
        self.calls.append((name, duration_s, Path(directory)))
        path = Path(directory) / f"{name}.BDD"
        path.write_bytes(b"block")
        return True, path


class ReportingCycle(Cycle):
    """A cycle that carries the report of the invocation, like the hardened one does."""

    def __init__(self, report: CycleReport, *, raises: BaseException | None = None):
        super().__init__()
        self.last_report = report
        self.raises = raises

    def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
        if self.raises is not None:
            raise self.raises
        return super().try_record_and_store(
            name, duration_s, directory, expected_mode=expected_mode
        )


class Inner:
    def __init__(self) -> None:
        self.mode_note: str | None = None

    def process_mode_note(self, mode):
        return self.mode_note


class Table:
    image_sha256 = "0" * 64


class TestTheWrapper:
    def test_a_supplied_cycle_replaces_the_host_dispatch(self, tmp_path):
        from udv_echo_process.acquire.bridge import BridgeActuator

        cycle = Cycle()
        actuator = BridgeActuator(Inner(), table=Table(), dispatch=None, cycle=cycle)
        ok, outcome = actuator.try_record_and_store(
            "wired-01", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )
        assert ok is True
        assert cycle.calls == [("wired-01", 1.0, tmp_path)]
        assert Path(outcome).is_file()

    def test_a_supplied_cycle_still_needs_the_requested_build(self, tmp_path):
        """The cycle replaces execution, not the build check: a rung may not record on a table that
        was measured against another application build."""
        from udv_echo_process.acquire.bridge import BridgeActuator

        cycle = Cycle()
        actuator = BridgeActuator(
            Inner(), table=Table(), dispatch=None, cycle=cycle, target_digest="f" * 64
        )
        ok, outcome = actuator.try_record_and_store(
            "wired-03", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )
        assert ok is False
        assert outcome == "bridge_digest_unknown:" + "f" * 64
        assert cycle.calls == []

    def test_a_supplied_cycle_on_the_requested_build_still_runs(self, tmp_path):
        """And the digest check does not make the cycle path unrunnable: an equal digest passes."""
        from udv_echo_process.acquire.bridge import BridgeActuator

        cycle = Cycle()
        actuator = BridgeActuator(
            Inner(), table=Table(), dispatch=None, cycle=cycle, target_digest="0" * 64
        )
        ok, outcome = actuator.try_record_and_store(
            "wired-04", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )
        assert ok is True
        assert Path(outcome) == tmp_path / "wired-04.BDD"
        assert cycle.calls == [("wired-04", 1.0, tmp_path)]


class TestTheFactory:
    def test_actuator_for_hands_the_cycle_to_the_bridge(self, monkeypatch):
        seen: dict = {}

        def fake_bridge(channel=None, notes=None, **kwargs):
            seen.update(kwargs)
            return "bridge-actuator"

        monkeypatch.setattr(live, "bridge_actuator", fake_bridge)
        cycle = Cycle()
        assert live.actuator_for("bridge", 1, cycle=cycle) == "bridge-actuator"
        assert seen["cycle"] is cycle

    def test_the_gui_route_never_sees_it(self, monkeypatch):
        seen: dict = {}

        def fake_ui(channel=None, notes=None, **kwargs):
            seen.update(kwargs)
            return "ui-actuator"

        monkeypatch.setattr(live, "live_actuator", fake_ui)
        live.actuator_for("ui", 1, cycle=Cycle())
        assert "cycle" not in seen


class TestTheCommands:
    def test_sweep_forwards_the_cycle(self, monkeypatch):
        captured: dict = {}

        class Runner:
            def __init__(self, *args, **kwargs):
                pass

            def run(self, *args, **kwargs):
                return ()

        monkeypatch.setattr(live, "actuator_for", lambda *a, **k: captured.update(k) or "actuator")
        monkeypatch.setattr(live, "SweepRunner", Runner)
        cycle = Cycle()
        live.sweep(1.0, Path("outputs"), [5], 1, expected_mode=ProcessMode.INSTRUMENT, route="bridge", cycle=cycle)
        assert captured.get("cycle") is cycle

    def test_point_forwards_the_cycle(self, monkeypatch):
        captured: dict = {}

        class Actuator:
            def try_record_and_store(self, name, seconds, store_dir, expected_mode=None):
                return True, store_dir

        monkeypatch.setattr(live, "actuator_for", lambda *a, **k: captured.update(k) or Actuator())
        cycle = Cycle()
        ok, _ = live.point(
            "wired-02", 1.0, Path("outputs"), 1,
            expected_mode=ProcessMode.INSTRUMENT, route="bridge", cycle=cycle,
        )
        assert ok is True
        assert captured.get("cycle") is cycle


class TestTheGuardedFlag:
    """The opt-in is a route decision: it is named, and the UI route cannot carry it."""

    def test_actuator_for_hands_the_flag_to_the_bridge(self, monkeypatch):
        seen: dict = {}

        def fake_bridge(channel=None, notes=None, **kwargs):
            seen.update(kwargs)
            return "bridge-actuator"

        monkeypatch.setattr(live, "bridge_actuator", fake_bridge)
        assert live.actuator_for("bridge", 1, guarded_cycle=True) == "bridge-actuator"
        assert seen["guarded_cycle"] is True

    def test_the_ui_route_refuses_it_by_name(self):
        with pytest.raises(BridgeUnavailable) as caught:
            live.actuator_for("ui", guarded_cycle=True)
        assert caught.value.reason == "bridge_guarded_cycle_route:ui"

    def test_the_ui_route_never_hears_about_it_by_default(self, monkeypatch):
        seen: dict = {}

        def fake_ui(channel=None, notes=None, **kwargs):
            seen.update(kwargs)
            return "ui-actuator"

        monkeypatch.setattr(live, "live_actuator", fake_ui)
        assert live.actuator_for("ui") == "ui-actuator"
        assert "guarded_cycle" not in seen

    def test_point_and_sweep_take_the_flag(self):
        """The library surface the CLI flag has to reach — asserted without a screen."""
        import inspect

        for function in (live.point, live.sweep):
            parameters = inspect.signature(function).parameters
            assert "guarded_cycle" in parameters, function.__name__


class TestTheCycleReport:
    """The report belongs to one invocation: cleared before it, captured after every exit."""

    @staticmethod
    def report(name: str = "wired-05") -> CycleReport:
        return CycleReport(
            name=name,
            stage=CycleStage.DONE,
            recorded=True,
            stopped=True,
            store_requested=True,
            dialog_committed=True,
            stored=True,
            streams=1,
        )

    def test_the_report_of_the_cycle_that_ran_is_exposed(self, tmp_path):
        cycle = ReportingCycle(self.report())
        actuator = BridgeActuator(Inner(), table=Table(), dispatch=None, cycle=cycle)

        ok, outcome = actuator.try_record_and_store(
            "wired-05", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is True, outcome
        assert actuator.last_cycle_report is cycle.last_report
        assert actuator.last_cycle_report.name == "wired-05"

    def test_a_legacy_cycle_without_a_report_leaves_none(self, tmp_path):
        """A generic StoreCycle has no report, and none may be invented for it."""

        actuator = BridgeActuator(Inner(), table=Table(), dispatch=None, cycle=Cycle())

        ok, outcome = actuator.try_record_and_store(
            "wired-06", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is True, outcome
        assert actuator.last_cycle_report is None

    def test_the_previous_report_is_cleared_before_each_invocation(self, tmp_path):
        """A point refused before its cycle must not hand over the earlier point's evidence.

        The pair of properties both answer for one invocation: the report and the diagnostic beside it are
        reset together, so a refusal that never reached a cycle leaves neither the previous point's evidence
        nor the previous point's reason for having none.
        """

        cycle = ReportingCycle(self.report("wired-07"))
        inner = Inner()
        actuator = BridgeActuator(inner, table=Table(), dispatch=None, cycle=cycle)
        assert actuator.try_record_and_store(
            "wired-07", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )[0] is True
        assert actuator.last_cycle_report is not None
        assert actuator.cycle_report_problem is None

        inner.mode_note = "the caption states Simulation, not Instrument"
        ok, reason = actuator.try_record_and_store(
            "wired-08", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
        )

        assert ok is False
        assert reason == "bridge_mode_mismatch:the caption states Simulation, not Instrument"
        assert actuator.last_cycle_report is None
        assert actuator.cycle_report_problem is None
        assert cycle.calls == [("wired-07", 1.0, tmp_path)], "the second cycle never ran"

    def test_the_report_is_captured_when_the_cycle_raises(self, tmp_path):
        original = self.report()
        cycle = ReportingCycle(original, raises=RuntimeError("the stop was never dispatched"))
        actuator = BridgeActuator(Inner(), table=Table(), dispatch=None, cycle=cycle)

        with pytest.raises(RuntimeError):
            actuator.try_record_and_store(
                "wired-09", 1.0, tmp_path, expected_mode=ProcessMode.INSTRUMENT
            )

        assert actuator.last_cycle_report is original
