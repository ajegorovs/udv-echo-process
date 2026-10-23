"""The composed cycle has to be reachable from the package's own commands, not only from a probe.

`live.sweep` is the composed path a campaign uses: rungs, plan validation, per-point log. For the message route to be
more than a demonstration, that function has to carry a caller-supplied cycle down to the wrapper, which is the same seam
`numeric_writes` uses. These tests pin the forwarding at each step a caller meets: the factory, the sweep, the single
point, and the wrapper itself.
"""

from __future__ import annotations

from pathlib import Path

from udv_echo_process.acquire import live
from udv_echo_process.acquire.actuator import ProcessMode


class Cycle:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
        self.calls.append((name, duration_s, Path(directory)))
        path = Path(directory) / f"{name}.BDD"
        path.write_bytes(b"block")
        return True, path


class Inner:
    def process_mode_note(self, mode):
        return None


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
