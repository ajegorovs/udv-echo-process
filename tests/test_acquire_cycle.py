"""The composed cycle: record → stop → store → name → commit, and the rules around it.

Every part of this has been measured on the live application; these tests pin the *discipline* the package adds, which is
what a sweep depends on when nobody is watching the screen: a taken name is refused before anything is recorded, a store
that produces nothing is a failure, and a stored file counts only when it decodes to a stream.
"""

from __future__ import annotations

from pathlib import Path

from udv_echo_process.acquire.actuator import StripState, StripView
from udv_echo_process.acquire.bridge import BridgeActuator
from udv_echo_process.acquire.cycle import (
    CycleBinding,
    CycleRoutines,
    ObservedAddress,
    ProcessIdentity,
    RoutineCycle,
)

ROUTINES = CycleRoutines(record=0x1000, store=0x2000, form=0x3000)

#: The instance these routines were "observed on".  A fake, but the cycle treats it exactly as a measured identity, so the
#: scenarios below run through the same guards a live call would.
IDENTITY = ProcessIdentity(
    pid=4120, created_ns=133_700_000_000_000_000, image_sha256="a" * 64
)
BINDING = CycleBinding(
    identity=IDENTITY,
    owner=ObservedAddress(address=ROUTINES.form, source="observed:primed-strip-owner"),
    record=ObservedAddress(address=ROUTINES.record, source="table:routines.record"),
    store=ObservedAddress(address=ROUTINES.store, source="table:routines.store"),
)


class Strip:
    """The strip's own state machine: READY, then RECORDING, then STORE, as the dispatches land."""

    def __init__(self) -> None:
        self.view = StripView.READY

    def __call__(self) -> StripState:
        if self.view is StripView.RECORDING:
            return StripState(button_count=1)
        if self.view is StripView.STORE:
            return StripState(button_count=3, has_slider=True)
        return StripState(button_count=3)


class Caller:
    def __init__(self, fail_on: int | None = None, strip: Strip | None = None) -> None:
        self.calls: list[tuple[int, int]] = []
        self.fail_on = fail_on
        self.strip = strip

    def __call__(self, address: int, form: int) -> dict:
        self.calls.append((address, form))
        if self.strip is not None and address == ROUTINES.record:
            self.strip.view = (
                StripView.RECORDING
                if self.strip.view is not StripView.RECORDING
                else StripView.STORE
            )
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
        self.strip = Strip()
        self.caller = Caller(fail_on=fail_on, strip=self.strip)
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
            binding=BINDING,
            identity=lambda: IDENTITY,
            owner_valid=lambda owner: owner == ROUTINES.form,
            read_strip=self.strip,
            decode=self.decode,
            measure_span=self.span,
            max_span_s=self.max_span_s,
            sleep=self.sleeps.append,
            poll_s=0.0,
            store_timeout_s=0.0,
            state_timeout_s=0.0,
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
    def test_a_cycle_with_no_binding_refuses_before_any_call(self, tmp_path):
        """Fail-closed by default: the guard is not an option, so an unbound cycle cannot dispatch at all."""
        caller = Caller()
        cycle = RoutineCycle(caller=caller, routines=ROUTINES, dialog=Dialog())
        ok, reason = cycle.try_record_and_store("point-00", 1.0, tmp_path)
        assert ok is False
        assert str(reason).startswith("cycle_binding_missing")
        assert caller.calls == []
        assert cycle.last_report is not None
        assert cycle.last_report.stage.value == "preflight"

    def test_a_cycle_missing_one_guard_names_it(self, tmp_path):
        caller = Caller()
        cycle = RoutineCycle(
            caller=caller,
            routines=ROUTINES,
            dialog=Dialog(),
            binding=BINDING,
            identity=lambda: IDENTITY,
            owner_valid=lambda owner: True,
        )
        ok, reason = cycle.try_record_and_store("point-00b", 1.0, tmp_path)
        assert ok is False
        assert reason == "cycle_guard_missing:read_strip"
        assert caller.calls == []

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
