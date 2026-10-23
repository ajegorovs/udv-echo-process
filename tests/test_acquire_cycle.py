"""The composed cycle: record → stop → store → name → commit, and the rules around it.

Every part of this has been measured on the live application; these tests pin the *discipline* the package adds, which is
what a sweep depends on when nobody is watching the screen: a taken name is refused before anything is recorded, a store
that produces nothing is a failure, and a stored file counts only when it decodes to a stream.
"""

from __future__ import annotations

from pathlib import Path

from udv_echo_process.acquire.bridge import BridgeActuator
from udv_echo_process.acquire.cycle import CycleRoutines, RoutineCycle

ROUTINES = CycleRoutines(record=0x1000, store=0x2000, form=0x3000)


class Caller:
    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self.fail_on = fail_on

    def __call__(self, address: int, form: int) -> dict:
        self.calls.append((address, form))
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            return {"ok": False, "errors": ["access violation"]}
        return {"ok": True, "errors": []}


class Dialog:
    def __init__(self, works: bool = True, write: bool = True) -> None:
        self.commits: list[str] = []
        self.works = works
        self.write = write

    def commit(self, name: str) -> bool:
        self.commits.append(name)
        if self.works and self.write and self.directory is not None:
            (self.directory / f"{name}.BDD").write_bytes(b"block")
        return self.works

    directory = None


class Factory:
    """Build a cycle whose stores land in a temporary directory, with no instrument involved."""

    def __init__(
        self,
        directory,
        *,
        fail_on: int | None = None,
        dialog: Dialog | None = None,
        decode=None,
        span=None,
        max_span_s: float | None = None,
    ):
        self.directory = directory
        self.caller = Caller(fail_on=fail_on)
        self.dialog = dialog or Dialog()
        self.dialog.directory = directory
        self.decode = decode or (lambda path: 1)
        self.span = span or (lambda path: 0.0)
        self.max_span_s = max_span_s
        self.sleeps: list[float] = []

    def __call__(self) -> RoutineCycle:
        return RoutineCycle(
            caller=self.caller,
            routines=ROUTINES,
            dialog=self.dialog,
            decode=self.decode,
            measure_span=self.span,
            max_span_s=self.max_span_s,
            sleep=self.sleeps.append,
            poll_s=0.0,
            store_timeout_s=0.0,
        )


class TestTheHappyPath:
    def test_one_cycle_records_stops_stores_and_names(self, tmp_path):
        factory = Factory(tmp_path)
        ok, outcome = factory().try_record_and_store("point-01", 4.0, tmp_path)
        assert ok is True
        assert outcome == tmp_path / "point-01.BDD"
        assert factory.caller.calls == [(ROUTINES.record, ROUTINES.form), (ROUTINES.record, ROUTINES.form), (ROUTINES.store, ROUTINES.form)]
        assert factory.dialog.commits == ["point-01"]
        assert factory.sleeps[0] == 4.0  # the recording window, before the stop


class TestWhatItRefuses:
    def test_a_taken_name_is_refused_before_anything_is_recorded(self, tmp_path):
        (tmp_path / "point-01.BDD").write_bytes(b"existing")
        factory = Factory(tmp_path)
        ok, reason = factory().try_record_and_store("point-01", 4.0, tmp_path)
        assert ok is False
        assert "store_name_taken" in reason
        # nothing was recorded: the overwrite warning is what wedges a run
        assert factory.caller.calls == []
        assert factory.dialog.commits == []

    def test_a_record_that_does_not_dispatch_stops_the_cycle(self, tmp_path):
        factory = Factory(tmp_path, fail_on=1)
        ok, reason = factory().try_record_and_store("point-02", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("record_not_dispatched")
        assert factory.dialog.commits == []

    def test_a_stop_that_does_not_dispatch_does_not_reach_store(self, tmp_path):
        factory = Factory(tmp_path, fail_on=2)
        ok, reason = factory().try_record_and_store("point-03", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("stop_not_dispatched")
        assert factory.dialog.commits == []

    def test_a_dialog_that_does_not_commit_is_a_failure(self, tmp_path):
        dialog = Dialog(works=False)
        factory = Factory(tmp_path, dialog=dialog)
        ok, reason = factory().try_record_and_store("point-04", 1.0, tmp_path)
        assert ok is False
        assert reason == "store_dialog_not_committed"

    def test_a_commit_that_writes_no_file_is_a_failure(self, tmp_path):
        dialog = Dialog(write=False)
        factory = Factory(tmp_path, dialog=dialog)
        ok, reason = factory().try_record_and_store("point-05", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("store_file_missing")

    def test_a_block_that_decodes_to_nothing_is_a_failure(self, tmp_path):
        factory = Factory(tmp_path, decode=lambda path: 0)
        ok, reason = factory().try_record_and_store("point-06", 1.0, tmp_path)
        assert ok is False
        assert reason == "store_decoded_no_streams"

    def test_an_undecodable_block_is_a_failure_not_a_crash(self, tmp_path):
        def explode(path):
            raise ValueError("not a block")

        factory = Factory(tmp_path, decode=explode)
        ok, reason = factory().try_record_and_store("point-07", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("store_undecodable")


class TestTheBridgePrefersTheCycle:
    def test_a_supplied_cycle_replaces_the_host_dispatch(self, tmp_path):
        class Inner:
            def process_mode_note(self, mode):
                return None

        class Table:
            image_sha256 = "0" * 64

        called: list[tuple] = []

        class Cycle:
            def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
                called.append((name, duration_s, Path(directory)))
                path = Path(directory) / f"{name}.BDD"
                path.write_bytes(b"block")
                return True, path

        actuator = BridgeActuator(
            Inner(), table=Table(), dispatch=None, cycle=Cycle()
        )
        ok, outcome = actuator.try_record_and_store(
            "point-08", 2.0, tmp_path, expected_mode=type("M", (), {"value": "instrument"})()
        )
        assert ok is True
        assert called and called[0][0] == "point-08"
        assert Path(outcome).is_file()

    def test_without_a_cycle_or_a_dispatch_the_route_still_refuses(self, tmp_path):
        class Inner:
            def process_mode_note(self, mode):
                return None

        class Table:
            image_sha256 = "0" * 64

        actuator = BridgeActuator(Inner(), table=Table(), dispatch=None)
        ok, reason = actuator.try_record_and_store(
            "point-09", 1.0, tmp_path, expected_mode=type("M", (), {"value": "instrument"})()
        )
        assert ok is False
        assert "unavailable" in str(reason) or "bridge" in str(reason)


class TestTheRecordingWindow:
    """A block that recorded far longer than asked is refused, and the span is reported.

    Measured cause: record and stop are two separate attachments, so a requested 4 s window produced a 20.7 s block. The
    span is read from the block's own timestamps, which is the only source that knows.
    """

    def test_the_span_is_reported(self, tmp_path):
        factory = Factory(tmp_path, span=lambda path: 4.2)
        ok, _ = factory().try_record_and_store("point-10", 4.0, tmp_path)
        assert ok is True

    def test_the_span_is_reported_without_judging_the_point(self, tmp_path):
        # measured: a 4 s recording stored 397 s of buffer, so a span says nothing about the window and must not refuse
        factory = Factory(tmp_path, span=lambda path: 397.17)
        ok, _ = factory().try_record_and_store("point-11", 4.0, tmp_path)
        assert ok is True

    def test_a_caller_can_still_ask_for_a_ceiling(self, tmp_path):
        factory = Factory(tmp_path, span=lambda path: 397.17, max_span_s=60.0)
        ok, reason = factory().try_record_and_store("point-12", 4.0, tmp_path)
        assert ok is False
        assert reason.startswith("recorded_span_over_limit")
        assert "397.17s>60.00s" in reason

    def test_an_unmeasurable_span_is_a_refusal_not_a_pass(self, tmp_path):
        def explode(path):
            raise ValueError("no timestamps")

        factory = Factory(tmp_path, span=explode)
        ok, reason = factory().try_record_and_store("point-13", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("store_span_unmeasurable")
