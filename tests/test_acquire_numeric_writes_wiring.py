"""The bridge's numeric-write policy, reachable from a command.

The policy itself is pinned in ``test_bridge_actuator.py``. What was missing — and is pinned here — is that
nothing could *ask* for it: the wrapper had a ``numeric_writes`` flag, and no factory, function or command line
ever set it, so a point's parameters always went through the GUI dialogs.

These tests are about the wiring, in the order a caller meets it: the route, the function, the command line.
"""

from __future__ import annotations

import pytest

from udv_echo_process.acquire import live
from udv_echo_process.acquire.actuator import ProcessMode
from udv_echo_process.cli import acquire_main


class Recorder:
    """Stands in for the bridge factory and remembers how it was called."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, channel=None, notes=None, **kwargs):
        self.calls.append({"channel": channel, "notes": notes, **kwargs})
        return "bridge-actuator"


class TestTheRoute:
    def test_the_flag_reaches_the_bridge(self, monkeypatch):
        recorder = Recorder()
        monkeypatch.setattr(live, "bridge_actuator", recorder)

        live.actuator_for("bridge", 1, numeric_writes=True)
        assert recorder.calls[0]["numeric_writes"] is True

    def test_it_stays_off_unless_asked(self, monkeypatch):
        recorder = Recorder()
        monkeypatch.setattr(live, "bridge_actuator", recorder)
        live.actuator_for("bridge", 1)
        assert recorder.calls[0]["numeric_writes"] is False

    def test_the_gui_route_never_sees_it(self, monkeypatch):
        seen: dict = {}

        def fake_live_actuator(channel=None, notes=None):
            seen["called"] = True
            return "ui-actuator"

        monkeypatch.setattr(live, "live_actuator", fake_live_actuator)
        assert live.actuator_for("ui", 1, numeric_writes=True) == "ui-actuator"
        assert seen["called"] is True


class TestTheFunctions:
    def test_point_forwards_it(self, monkeypatch):
        captured: dict = {}

        class Actuator:
            def try_record_and_store(self, name, seconds, store_dir, expected_mode=None):
                captured["called"] = name
                return True, store_dir

        def fake_actuator_for(route, channel, notes, **kwargs):
            captured.update({"route": route, **kwargs})
            return Actuator()

        monkeypatch.setattr(live, "actuator_for", fake_actuator_for)
        live.point(
            "point-1", 1.0, live.Path("outputs"), 1,
            expected_mode=ProcessMode.INSTRUMENT,
            route="bridge",
            numeric_writes=True,
        )
        assert captured["numeric_writes"] is True
        assert captured["route"] == "bridge"

    def test_sweep_forwards_it(self, monkeypatch):
        captured: dict = {}

        class Runner:
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)

            def run(self, *args, **kwargs):
                return ()

        monkeypatch.setattr(live, "actuator_for", lambda *a, **k: (captured.update(k), "actuator")[1])
        monkeypatch.setattr(live, "SweepRunner", Runner)
        # The wiring is what is under test, not the run: `SweepRunner` is stubbed above, so any failure here
        # is the harness, and swallowing it would hide exactly the mistake this test exists to catch.
        live.sweep(
            1.0, live.Path("outputs"), [1], 1,
            expected_mode=ProcessMode.INSTRUMENT,
            route="bridge",
            numeric_writes=True,
        )
        assert captured.get("numeric_writes") is True


class TestTheCommandLine:
    def test_point_accepts_the_flag_and_forwards_it(self, monkeypatch, capsys, tmp_path):
        seen: dict = {}

        def fake_point(name, seconds, store_dir, channel=None, notes=None, **kwargs):
            seen.update(kwargs)
            seen["name"] = name
            return True, "stored/path.BDD"

        monkeypatch.setattr(live, "point", fake_point)
        with pytest.raises(SystemExit) as exit_info:
            acquire_main([
                "point", "probe", "--seconds", "1", "--expect-mode", "instrument",
                "--route", "bridge", "--bridge-numeric-writes", "--store-dir", str(tmp_path), "--json",
            ])
        assert exit_info.value.code == 0
        assert seen["numeric_writes"] is True
        assert seen["route"] == "bridge"

    def test_point_without_the_flag_says_false(self, monkeypatch, tmp_path):
        seen: dict = {}

        def fake_point(name, seconds, store_dir, channel=None, notes=None, **kwargs):
            seen.update(kwargs)
            return True, "stored/path.BDD"

        monkeypatch.setattr(live, "point", fake_point)
        with pytest.raises(SystemExit):
            acquire_main([
                "point", "probe", "--seconds", "1", "--expect-mode", "instrument",
                "--store-dir", str(tmp_path), "--json",
            ])
        assert seen["numeric_writes"] is False

    def test_sweep_accepts_the_flag(self, monkeypatch, tmp_path):
        seen: dict = {}

        def fake_sweep(seconds, store_dir, rungs, channel=None, **kwargs):
            seen.update(kwargs)
            return ()

        monkeypatch.setattr(live, "sweep", fake_sweep)
        with pytest.raises(SystemExit):
            acquire_main([
                "sweep", "--seconds", "1", "--rungs", "1", "--expect-mode", "instrument",
                "--route", "bridge", "--bridge-numeric-writes",
                "--store-dir", str(tmp_path),
            ])
        assert seen["numeric_writes"] is True
