"""The cycle's binding and guards: a call is only allowed on the instance the addresses were observed on.

`RoutineCycle` used to hold bare integers and credit a caller's `ok` as proof. These tests pin the opposite: a routine
pointer is only usable against the process, instance and build it was observed on, and every refusal that can be made
before the first call is made before it — with the call list asserted empty, because that is the whole point of a check.
Nothing here touches an instrument: the identity reader, the owner check and the strip reader are injected fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.acquire.actuator import StripState, StripView
from udv_echo_process.acquire.cycle import (
    CycleBinding,
    CycleReport,
    CycleRoutines,
    CycleStage,
    ObservedAddress,
    ProcessIdentity,
    RoutineCycle,
)

ROUTINES = CycleRoutines(record=0x1000, store=0x2000, form=0x3000)
IDENTITY = ProcessIdentity(
    pid=4120, created_ns=133_700_000_000_000_000, image_sha256="a" * 64
)
BINDING = CycleBinding(
    identity=IDENTITY,
    owner=ObservedAddress(address=ROUTINES.form, source="observed:primed-strip-owner"),
    record=ObservedAddress(address=ROUTINES.record, source="table:routines.record"),
    store=ObservedAddress(address=ROUTINES.store, source="table:routines.store"),
)

_BUTTONS: dict[StripView, tuple[int, bool]] = {
    StripView.READY: (3, False),
    StripView.RECORDING: (1, False),
    StripView.STORE: (3, True),
    StripView.AMBIGUOUS: (4, False),
    StripView.UNKNOWN: (0, False),
}


def _state(view: StripView) -> StripState:
    count, slider = _BUTTONS[view]
    return StripState(button_count=count, has_slider=slider)


class Strip:
    """A strip whose view follows the routine calls, one view per dispatch."""

    def __init__(self, view: StripView = StripView.READY) -> None:
        self.view = view
        self.reads = 0
        self.states: list[StripView] = []

    def __call__(self) -> StripState:
        self.reads += 1
        self.states.append(self.view)
        return _state(self.view)


class Caller:
    """Dispatch a routine, record it, and — optionally — walk the strip's own state machine.

    ``follow`` is what makes a dispatched `ok` testable: ``both`` moves READY → RECORDING → STORE the way the
    application does, ``start`` stops after the first move, and ``none`` answers ok without changing anything — which is
    the case a dispatched `ok` cannot be trusted for.
    """

    def __init__(self, strip: Strip | None = None, *, follow: str = "both") -> None:
        self.calls: list[tuple[int, int]] = []
        self.strip = strip
        self.follow = follow
        #: Per-call answers, the last one repeating; ``None`` means "ok, no errors" every time.
        self.results: list[object] | None = None

    def __call__(self, address: int, form: int) -> dict:
        self.calls.append((address, form))
        index = len(self.calls) - 1
        if self.strip is not None and address == ROUTINES.record:
            if self.follow == "both":
                self.strip.view = (
                    StripView.RECORDING
                    if self.strip.view is not StripView.RECORDING
                    else StripView.STORE
                )
            elif self.follow == "start" and self.strip.view is not StripView.RECORDING:
                self.strip.view = StripView.RECORDING
        if self.results is None:
            return {"ok": True, "errors": []}
        result = self.results[min(index, len(self.results) - 1)]
        if isinstance(result, BaseException):
            raise result
        return result  # type: ignore[return-value]


class Dialog:
    def __init__(self, works: object = True, write: bool = True) -> None:
        self.commits: list[str] = []
        self.works = works
        self.write = write
        self.directory: Path | None = None

    def commit(self, name: str) -> bool:
        self.commits.append(name)
        if self.works is True and self.write and self.directory is not None:
            (self.directory / f"{name}.BDD").write_bytes(b"block")
        if isinstance(self.works, BaseException):
            raise self.works
        return self.works  # type: ignore[return-value]


class Sleeps(list):
    """Record the cycle's waits, and raise on the one a test names — a clock is an injected dependency too."""

    def __init__(self, fail=None) -> None:
        super().__init__()
        self.fail = fail

    def __call__(self, seconds: float) -> None:
        index = len(self)
        if self.fail is not None and self.fail(seconds, index):
            raise TimeoutError(f"clock refused the {seconds}s wait")
        self.append(seconds)


class Harness:
    """Build a guarded cycle whose stores land in a temporary directory."""

    def __init__(
        self,
        directory: Path,
        *,
        view: StripView = StripView.READY,
        identity: ProcessIdentity | None = IDENTITY,
        binding: CycleBinding | None = BINDING,
        owner_ok: object = True,
        routines: CycleRoutines = ROUTINES,
        dialog: Dialog | None = None,
        span: float = 0.0,
        max_span_s: float | None = None,
        decode=1,
        follow: str = "both",
        results: list[object] | None = None,
        identity_reader=None,
        owner_check=None,
        strip=None,
        state_timeout_s: float = 0.0,
        sleep=None,
        **overrides,
    ) -> None:
        self.directory = directory
        self.strip = strip if strip is not None else Strip(view)
        self.caller = Caller(self.strip, follow=follow)
        self.caller.results = results
        self.dialog = dialog if dialog is not None else Dialog()
        self.dialog.directory = directory
        self.identity = identity
        self.binding = binding
        self.owner_ok = owner_ok
        self.routines = routines
        self.span = span
        self.decode = decode if callable(decode) else (lambda path: decode)
        self.max_span_s = max_span_s
        self.state_timeout_s = state_timeout_s
        self.overrides = overrides
        self._identity_reader = identity_reader
        self._owner_check = owner_check
        self.sleeps = sleep if sleep is not None else Sleeps()

    def read_identity(self) -> ProcessIdentity | None:
        if self._identity_reader is not None:
            return self._identity_reader()
        return self.identity

    def owner_check(self, owner: int) -> bool:
        if self._owner_check is not None:
            return self._owner_check(owner)
        if isinstance(self.owner_ok, BaseException):
            raise self.owner_ok
        return self.owner_ok  # type: ignore[return-value]

    def kwargs(self) -> dict:
        """The cycle's keyword arguments, so a test can replace one guard without reaching for a private field."""
        # A guard that was asked for as ``None`` is a cycle with that guard *missing*, which is a refusal on its own.
        identity = None if self.identity is None else self.read_identity
        kwargs: dict = {
            "caller": self.caller,
            "routines": self.routines,
            "dialog": self.dialog,
            "binding": self.binding,
            "identity": identity,
            "owner_valid": self.owner_check,
            "read_strip": self.strip,
            "decode": self.decode,
            "measure_span": lambda path: self.span,
            "max_span_s": self.max_span_s,
            "sleep": self.sleeps,
            "poll_s": 0.0,
            "store_timeout_s": 0.0,
            "state_timeout_s": self.state_timeout_s,
        }
        kwargs.update(self.overrides)
        return kwargs

    def __call__(self) -> RoutineCycle:
        return RoutineCycle(**self.kwargs())


def cycle_with(harness: Harness, **overrides) -> RoutineCycle:
    """A cycle built from ``harness`` with one or more keyword arguments replaced."""
    kwargs = harness.kwargs()
    kwargs.update(overrides)
    return RoutineCycle(**kwargs)


def refused(harness: Harness, tmp_path: Path, name: str = "safety-01"):
    """Run one cycle and return the refusal, asserting nothing was called or committed."""
    ok, reason = harness().try_record_and_store(name, 1.0, tmp_path)
    assert ok is False
    assert harness.caller.calls == []
    assert harness.dialog.commits == []
    return str(reason)


class TestTheOwnedBindingRuns:
    def test_a_cycle_on_its_own_instance_records_stops_and_stores(self, tmp_path):
        harness = Harness(tmp_path)
        cycle = harness()
        ok, outcome = cycle.try_record_and_store("owned-01", 1.0, tmp_path)
        assert ok is True
        assert outcome == tmp_path / "owned-01.BDD"
        assert harness.caller.calls == [
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.store, ROUTINES.form),
        ]
        assert harness.dialog.commits == ["owned-01"]
        report = cycle.last_report
        assert isinstance(report, CycleReport)
        assert report.stored is True
        assert report.stage is CycleStage.DONE
        assert report.last_view is StripView.STORE


class TestWhatIsRefusedBeforeAnyCall:
    def test_a_cycle_with_no_binding_does_not_call_anything(self, tmp_path):
        assert refused(Harness(tmp_path, binding=None), tmp_path).startswith(
            "cycle_binding_missing"
        )

    @pytest.mark.parametrize("guard", ["identity", "owner_valid", "read_strip"])
    def test_a_missing_guard_is_named_and_calls_nothing(self, tmp_path, guard):
        harness = Harness(tmp_path, **{guard: None})
        reason = refused(harness, tmp_path)
        assert reason.startswith(f"cycle_guard_missing:{guard}")

    def test_an_unreadable_identity_is_a_refusal(self, tmp_path):
        reason = refused(Harness(tmp_path, identity_reader=lambda: None), tmp_path)
        assert reason == "cycle_identity_unavailable:null"

    def test_an_identity_reader_that_raises_is_a_refusal_not_a_crash(self, tmp_path):
        def explode():
            raise OSError("process gone")

        reason = refused(Harness(tmp_path, identity_reader=explode), tmp_path)
        assert reason == "cycle_identity_unavailable:OSError"

    def test_an_identity_of_the_wrong_type_is_a_refusal(self, tmp_path):
        reason = refused(
            Harness(tmp_path, identity_reader=lambda: {"pid": 4120}), tmp_path
        )
        assert reason.startswith("cycle_identity_invalid")

    def test_a_different_pid_is_a_refusal(self, tmp_path):
        other = IDENTITY.model_copy(update={"pid": 5121})
        reason = refused(Harness(tmp_path, identity=other), tmp_path)
        assert reason.startswith("cycle_pid_changed")

    def test_the_same_pid_with_another_creation_time_is_a_pid_reuse_refusal(self, tmp_path):
        reused = IDENTITY.model_copy(update={"created_ns": IDENTITY.created_ns + 1})
        reason = refused(Harness(tmp_path, identity=reused), tmp_path)
        assert reason.startswith("cycle_instance_changed")

    def test_a_changed_build_is_a_refusal(self, tmp_path):
        other = IDENTITY.model_copy(update={"image_sha256": "b" * 64})
        reason = refused(Harness(tmp_path, identity=other), tmp_path)
        assert reason.startswith("cycle_build_changed")

    def test_a_null_owner_is_a_refusal(self, tmp_path):
        binding = BINDING.model_copy(
            update={"owner": ObservedAddress(address=0, source="observed:no-owner")}
        )
        reason = refused(Harness(tmp_path, binding=binding), tmp_path)
        assert reason.startswith("cycle_owner_null")

    @pytest.mark.parametrize("field", ["record", "store"])
    def test_a_null_routine_is_a_refusal(self, tmp_path, field):
        binding = BINDING.model_copy(
            update={field: ObservedAddress(address=0, source="table:missing")}
        )
        reason = refused(Harness(tmp_path, binding=binding), tmp_path)
        assert reason.startswith(f"cycle_routine_null:{field}")

    @pytest.mark.parametrize(
        ("field", "address"),
        [("record", 0x9999), ("store", 0x9999), ("owner", 0x9999)],
    )
    def test_a_binding_that_contradicts_the_routines_is_a_refusal(
        self, tmp_path, field, address
    ):
        binding = BINDING.model_copy(
            update={field: ObservedAddress(address=address, source="table:other")}
        )
        reason = refused(Harness(tmp_path, binding=binding), tmp_path)
        assert reason.startswith(f"cycle_binding_conflict:{field}")

    def test_a_pointer_the_owner_check_cannot_read_is_a_refusal(self, tmp_path):
        reason = refused(Harness(tmp_path, owner_ok=False), tmp_path)
        assert reason.startswith("cycle_owner_unreadable")

    def test_an_owner_check_that_raises_is_a_refusal_not_a_crash(self, tmp_path):
        def explode(owner):
            raise ValueError("unmapped")

        reason = refused(Harness(tmp_path, owner_check=explode), tmp_path)
        assert reason == "cycle_owner_unreadable:ValueError"

    def test_a_strip_the_reader_cannot_see_is_a_refusal(self, tmp_path):
        reason = refused(Harness(tmp_path, strip=lambda: None), tmp_path)
        assert reason.startswith("strip_state_unreadable")

    def test_an_already_recording_strip_is_refused(self, tmp_path):
        harness = Harness(tmp_path, view=StripView.RECORDING)
        reason = refused(harness, tmp_path)
        assert reason == "cycle_strip_not_ready:recording"

    def test_a_strip_holding_a_stored_block_is_refused(self, tmp_path):
        harness = Harness(tmp_path, view=StripView.STORE)
        reason = refused(harness, tmp_path)
        assert reason == "cycle_strip_not_ready:store"

    def test_a_taken_name_is_still_refused_first(self, tmp_path):
        (tmp_path / "safety-02.BDD").write_bytes(b"existing")
        harness = Harness(tmp_path)
        ok, reason = harness().try_record_and_store("safety-02", 1.0, tmp_path)
        assert ok is False
        assert str(reason).startswith("store_name_taken")
        assert harness.caller.calls == []

    @pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
    def test_a_duration_that_cannot_bound_the_window_is_refused(self, tmp_path, value):
        harness = Harness(tmp_path)
        ok, reason = harness().try_record_and_store("safety-03", value, tmp_path)
        assert ok is False
        assert str(reason).startswith("cycle_parameter_invalid:duration_s")
        assert harness.caller.calls == []

    @pytest.mark.parametrize(
        "field", ["state_timeout_s", "poll_s", "stop_settle_s", "store_settle_s"]
    )
    @pytest.mark.parametrize("value", [-1.0, float("nan")])
    def test_a_polling_parameter_that_cannot_be_bounded_is_refused(
        self, tmp_path, field, value
    ):
        harness = Harness(tmp_path, **{field: value})
        ok, reason = harness().try_record_and_store("safety-04", 1.0, tmp_path)
        assert ok is False
        assert str(reason).startswith(f"cycle_parameter_invalid:{field}")
        assert harness.caller.calls == []

    @pytest.mark.parametrize("wait", ["state_timeout_s", "store_timeout_s"])
    def test_a_zero_poll_cannot_be_paired_with_a_wait(self, tmp_path, wait):
        """A wait with no interval is a hot spin, not a bound — refused, rather than trusted to exit."""
        harness = Harness(tmp_path, **{wait: 5.0})
        ok, reason = harness().try_record_and_store("safety-05", 1.0, tmp_path)
        assert ok is False
        assert reason == "cycle_parameter_invalid:poll_s"
        assert harness.caller.calls == []


class TestTheCycleObservesItsTransitions:
    """A dispatched `ok` is not a state change: the strip has to show it, within a bounded wait."""

    def test_a_start_that_never_shows_recording_is_refused(self, tmp_path):
        harness = Harness(tmp_path, follow="none")
        cycle = harness()
        ok, reason = cycle.try_record_and_store("state-01", 1.0, tmp_path)
        assert ok is False
        assert reason == "record_not_confirmed:ready"
        # the call happened — this is the other kind of test, so the call list is asserted, never empty
        assert harness.caller.calls == [(ROUTINES.record, ROUTINES.form)]
        assert harness.dialog.commits == []
        assert cycle.last_report is not None
        assert cycle.last_report.stage is CycleStage.RECORD
        # no transition was confirmed, so nothing may claim a successful start
        assert cycle.last_report.recorded is False
        assert cycle.last_report.stopped is False
        assert cycle.last_report.last_view is StripView.READY

    def test_a_stop_that_never_shows_the_store_view_is_refused(self, tmp_path):
        harness = Harness(tmp_path, follow="start")
        cycle = harness()
        ok, reason = cycle.try_record_and_store("state-02", 1.0, tmp_path)
        assert ok is False
        assert reason == "stop_not_confirmed:recording"
        assert harness.caller.calls == [
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.record, ROUTINES.form),
        ]
        assert harness.dialog.commits == []
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.STOP
        assert report.recorded is True
        assert report.stopped is False
        assert report.last_view is StripView.RECORDING

    def test_the_confirmation_wait_polls_until_the_view_arrives(self, tmp_path):
        """With a real polling interval the cycle waits for the transition instead of reading once."""

        class Late(Strip):
            def __init__(self) -> None:
                super().__init__(StripView.READY)
                self.delay = 2

            def __call__(self) -> StripState:
                if self.view is StripView.RECORDING and self.delay:
                    self.delay -= 1
                    # the application has accepted the command but has not repainted yet
                    self.states.append(StripView.READY)
                    self.reads += 1
                    return _state(StripView.READY)
                return super().__call__()

        strip = Late()
        harness = Harness(tmp_path, strip=strip, state_timeout_s=1.0, poll_s=0.25)
        ok, outcome = harness().try_record_and_store("state-03", 1.0, tmp_path)
        assert ok is True, outcome
        assert harness.sleeps.count(0.25) >= 1


class TestAChangedInstanceMidCycle:
    def test_a_restart_after_the_start_does_not_reach_for_the_stop(self, tmp_path):
        """The stop must not be dispatched through the old instance's object — that is how an access violation is made."""
        harness = Harness(tmp_path)
        later = IDENTITY.model_copy(update={"created_ns": IDENTITY.created_ns + 1})
        harness._identity_reader = lambda: IDENTITY if not harness.caller.calls else later
        cycle = harness()
        ok, reason = cycle.try_record_and_store("mid-01", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("cycle_instance_changed")
        assert harness.caller.calls == [(ROUTINES.record, ROUTINES.form)]
        assert harness.dialog.commits == []
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.STOP
        assert report.recorded is True
        assert report.stopped is False

    def test_an_owner_that_stops_being_readable_is_not_committed_through(self, tmp_path):
        harness = Harness(tmp_path)
        harness._owner_check = lambda owner: len(harness.caller.calls) < 3
        cycle = harness()
        ok, reason = cycle.try_record_and_store("mid-02", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("cycle_owner_unreadable")
        assert harness.dialog.commits == []
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.COMMIT
        assert report.dialog_committed is False


class TestStrictCallerEvidence:
    """Only an actual ``True`` means dispatched, and a raise is reported at its own stage."""

    def test_a_truthy_answer_is_not_a_dispatch(self, tmp_path):
        harness = Harness(tmp_path, results=[{"ok": 1}])
        ok, reason = harness().try_record_and_store("ev-01", 1.0, tmp_path)
        assert ok is False
        assert reason == "record_evidence_invalid:ok"
        assert len(harness.caller.calls) == 1

    def test_a_missing_ok_is_not_a_dispatch(self, tmp_path):
        harness = Harness(tmp_path, results=[{"errors": []}])
        ok, reason = harness().try_record_and_store("ev-02", 1.0, tmp_path)
        assert ok is False
        assert reason == "record_evidence_invalid:ok"

    def test_a_non_mapping_answer_is_not_evidence(self, tmp_path):
        harness = Harness(tmp_path, results=[None])
        ok, reason = harness().try_record_and_store("ev-03", 1.0, tmp_path)
        assert ok is False
        assert reason == "record_evidence_invalid:result"

    def test_a_raising_caller_is_named_at_its_stage(self, tmp_path):
        harness = Harness(tmp_path, results=[TimeoutError("no boundary")])
        ok, reason = harness().try_record_and_store("ev-04", 1.0, tmp_path)
        assert ok is False
        assert reason == "record_call_raised:TimeoutError"

    def test_a_stop_that_raises_is_named_at_the_stop_stage(self, tmp_path):
        harness = Harness(tmp_path, results=[{"ok": True}, ValueError("bad form")])
        ok, reason = harness().try_record_and_store("ev-05", 1.0, tmp_path)
        assert ok is False
        assert reason == "stop_call_raised:ValueError"
        assert harness.dialog.commits == []

    def test_a_dialog_that_raises_is_evidence_not_a_crash(self, tmp_path):
        harness = Harness(tmp_path, dialog=Dialog(works=RuntimeError("modal gone")))
        ok, reason = harness().try_record_and_store("ev-06", 1.0, tmp_path)
        assert ok is False
        assert reason == "store_dialog_raised:RuntimeError"

    def test_a_truthy_commit_is_not_a_commit(self, tmp_path):
        harness = Harness(tmp_path, dialog=Dialog(works=1))
        ok, reason = harness().try_record_and_store("ev-07", 1.0, tmp_path)
        assert ok is False
        assert reason == "store_dialog_evidence_invalid:int"


class TestPartialProgressIsReportedNotRetried:
    def test_a_failed_store_names_the_progress_and_does_not_retry(self, tmp_path):
        harness = Harness(
            tmp_path, results=[{"ok": True}, {"ok": True}, {"ok": False, "errors": ["denied"]}]
        )
        cycle = harness()
        ok, reason = cycle.try_record_and_store("partial-01", 1.0, tmp_path)
        assert ok is False
        assert reason == "store_not_dispatched:denied"
        # exactly one call per stage: a mutation that did not dispatch is never retried
        assert harness.caller.calls == [
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.store, ROUTINES.form),
        ]
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.STORE
        assert report.recorded is True
        assert report.stopped is True
        assert report.store_requested is False
        assert report.stored is False
        assert report.last_view is StripView.STORE

    def test_the_report_survives_the_span_check(self, tmp_path):
        harness = Harness(tmp_path, span=397.17, max_span_s=60.0)
        cycle = harness()
        ok, _reason = cycle.try_record_and_store("partial-02", 1.0, tmp_path)
        assert ok is False
        report = cycle.last_report
        assert report is not None
        assert report.recorded_span_s == 397.17
        assert report.stage is CycleStage.VERIFY


class TestTheReportIsAlwaysThere:
    def test_a_refusal_before_the_first_call_still_reports(self, tmp_path):
        cycle = Harness(tmp_path, binding=None)()
        ok, reason = cycle.try_record_and_store("report-01", 1.0, tmp_path)
        assert ok is False
        assert str(reason).startswith("cycle_binding_missing")
        report = cycle.last_report
        assert report is not None
        assert report.name == "report-01"
        assert report.stage is CycleStage.PREFLIGHT
        assert report.recorded is False
        assert report.reason == reason

    def test_the_report_is_immutable(self, tmp_path):
        from pydantic import ValidationError

        cycle = Harness(tmp_path)()
        cycle.try_record_and_store("report-02", 1.0, tmp_path)
        report = cycle.last_report
        assert report is not None
        with pytest.raises(ValidationError):
            report.stored = False  # type: ignore[misc]

    def test_the_report_is_reset_across_successive_invocations(self, tmp_path):
        harness = Harness(tmp_path)
        cycle = harness()
        ok, _outcome = cycle.try_record_and_store("report-03", 1.0, tmp_path)
        assert ok is True
        assert cycle.last_report is not None
        assert cycle.last_report.stored is True

        # the second point is refused at pre-flight: its report must not be the first point's
        harness._identity_reader = lambda: IDENTITY.model_copy(update={"pid": 4321})
        ok, _reason = cycle.try_record_and_store("report-04", 1.0, tmp_path)
        assert ok is False
        report = cycle.last_report
        assert report is not None
        assert report.name == "report-04"
        assert report.stored is False
        assert report.recorded is False
        assert report.stage is CycleStage.PREFLIGHT

    def test_the_report_serializes_the_evidence_a_caller_needs(self, tmp_path):
        harness = Harness(tmp_path, span=4.56)
        cycle = harness()
        ok, _outcome = cycle.try_record_and_store("report-05", 4.0, tmp_path)
        assert ok is True
        payload = cycle.last_report.model_dump(mode="json")
        assert payload["stage"] == "done"
        assert payload["recorded_span_s"] == 4.56
        assert payload["last_view"] == "store"
        assert payload["stored"] is True


class TestAClockThatFailsStillReports:
    """A wait is an injected dependency: when it raises, the cycle reports where it was and calls nothing later."""

    def test_the_window_wait_failing_reports_the_confirmed_start(self, tmp_path):
        harness = Harness(tmp_path, sleep=Sleeps(lambda seconds, index: seconds == 4.0))
        cycle = harness()
        ok, reason = cycle.try_record_and_store("clock-01", 4.0, tmp_path)
        assert ok is False
        assert reason.startswith("cycle_sleep_failed:window:")
        assert reason.endswith("TimeoutError")
        # the start was dispatched and confirmed; the stop was never reached
        assert harness.caller.calls == [(ROUTINES.record, ROUTINES.form)]
        assert harness.dialog.commits == []
        report = cycle.last_report
        assert report is not None, "a sleep failure must still leave a report"
        assert report.stage is CycleStage.RECORD
        assert report.recorded is True
        assert report.stopped is False
        assert report.last_view is StripView.RECORDING
        assert report.reason == reason

    def test_the_stop_settle_failing_reports_before_the_store_call(self, tmp_path):
        harness = Harness(
            tmp_path,
            stop_settle_s=1.5,
            store_settle_s=2.5,
            sleep=Sleeps(lambda seconds, index: seconds == 1.5),
        )
        cycle = harness()
        ok, reason = cycle.try_record_and_store("clock-02", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("cycle_sleep_failed:stop_settle:")
        assert harness.caller.calls == [
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.record, ROUTINES.form),
        ]
        assert harness.dialog.commits == []
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.STOP
        assert report.recorded is True
        assert report.stopped is True

    def test_the_store_settle_failing_reports_before_the_commit(self, tmp_path):
        harness = Harness(
            tmp_path,
            stop_settle_s=2.5,
            store_settle_s=1.5,
            sleep=Sleeps(lambda seconds, index: seconds == 1.5),
        )
        cycle = harness()
        ok, reason = cycle.try_record_and_store("clock-03", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("cycle_sleep_failed:store_settle:")
        assert harness.dialog.commits == []
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.STORE
        assert report.store_requested is True
        assert report.dialog_committed is False

    def test_a_state_wait_whose_clock_fails_reports_the_stage_it_was_waiting_at(self, tmp_path):
        harness = Harness(
            tmp_path,
            follow="none",
            state_timeout_s=1.0,
            poll_s=0.25,
            sleep=Sleeps(lambda seconds, index: seconds == 0.25),
        )
        cycle = harness()
        ok, reason = cycle.try_record_and_store("clock-04", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("cycle_sleep_failed:state:")
        assert harness.caller.calls == [(ROUTINES.record, ROUTINES.form)]
        assert harness.dialog.commits == []
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.RECORD
        assert report.recorded is False

    def test_a_store_poll_whose_clock_fails_reports_the_verification_stage(self, tmp_path):
        # the commit happens but writes nothing, so the file wait is the step that polls — and its clock fails
        harness = Harness(
            tmp_path,
            dialog=Dialog(write=False),
            state_timeout_s=0.0,
            store_timeout_s=5.0,
            poll_s=0.25,
            sleep=Sleeps(lambda seconds, index: seconds == 0.25),
        )
        cycle = harness()
        ok, reason = cycle.try_record_and_store("clock-05", 1.0, tmp_path)
        assert ok is False
        assert reason.startswith("cycle_sleep_failed:store_poll:")
        assert len(harness.dialog.commits) == 1
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.VERIFY
        assert report.stored is False


class EmptyDialog(Dialog):
    """A store dialog that commits the name and leaves the file empty.

    The application creates the file when the commit is accepted, so a file of zero bytes is a state it
    can really leave behind — a store that did not finish, not a store that never happened.
    """

    def commit(self, name: str) -> bool:
        self.commits.append(name)
        (self.directory / f"{name}.BDD").write_bytes(b"")
        return True


class TestAZeroByteStoreIsNotAStore:
    """A file the application created and wrote nothing into is not this point's block.

    The wait for the store ends on a non-empty file, but the check after it used to be existence only, so
    a zero-byte file reached the decoder — and a decoder can answer a stream count for it (the injected
    one here says ``1`` unconditionally, which is exactly what a permissive double does). The store's own
    evidence is the file's *content*, so the empty file is refused by name before anything is asked to
    read it: the decoder is not called, and the report says where it stopped.
    """

    def test_a_zero_byte_file_is_refused_before_the_decoder_is_called(self, tmp_path):
        decoded: list[Path] = []
        harness = Harness(
            tmp_path,
            dialog=EmptyDialog(),
            decode=lambda path: decoded.append(path) or 1,
            store_timeout_s=1.0,
            poll_s=0.5,
        )
        cycle = harness()

        ok, reason = cycle.try_record_and_store("empty-01", 1.0, tmp_path)

        assert ok is False
        assert reason == "store_file_empty:empty-01.BDD"
        # The caller and the dialog committed: this is a refusal about what arrived, not about a
        # store that never happened, and the difference is what the report has to preserve.
        assert harness.caller.calls == [
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.record, ROUTINES.form),
            (ROUTINES.store, ROUTINES.form),
        ]
        assert harness.dialog.commits == ["empty-01"]
        # The window and the two settles are waited out too; the tail is the store poll, bounded twice.
        assert harness.sleeps[-2:] == [0.5, 0.5], harness.sleeps
        assert decoded == [], "a decoder is never asked about a file with nothing in it"
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.VERIFY
        assert report.stored is False
        assert report.reason == "store_file_empty:empty-01.BDD"
        assert report.streams == 0

    def test_an_empty_file_is_refused_even_with_no_wait(self, tmp_path):
        """The same refusal without a polling bound: the size check is not a symptom of the wait."""
        decoded: list[Path] = []
        harness = Harness(
            tmp_path,
            dialog=EmptyDialog(),
            decode=lambda path: decoded.append(path) or 1,
        )

        ok, reason = harness().try_record_and_store("empty-02", 1.0, tmp_path)

        assert ok is False
        assert reason == "store_file_empty:empty-02.BDD"
        assert decoded == []


class TestMalformedStoreEvidenceIsNamed:
    """A count or a span that cannot be one is a refusal, and it never enters the report as a value."""

    @pytest.mark.parametrize(("decoded", "detail"), [(-1, "-1"), (1.5, "float"), (True, "bool")])
    def test_a_malformed_decoded_count_is_refused(self, tmp_path, decoded, detail):
        harness = Harness(tmp_path, decode=decoded)
        cycle = harness()
        ok, reason = cycle.try_record_and_store("evidence-01", 1.0, tmp_path)
        assert ok is False
        assert reason == f"store_decoded_streams_invalid:{detail}"
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.VERIFY
        assert report.streams == 0
        assert report.stored is False

    @pytest.mark.parametrize(
        ("span", "detail"),
        [
            (float("nan"), "nan"),
            (float("inf"), "inf"),
            (-1.5, "-1.5"),
        ],
    )
    def test_a_span_that_cannot_be_one_is_refused(self, tmp_path, span, detail):
        harness = Harness(tmp_path, span=span)
        cycle = harness()
        ok, reason = cycle.try_record_and_store("evidence-02", 1.0, tmp_path)
        assert ok is False
        assert reason == f"store_span_invalid:{detail}"
        report = cycle.last_report
        assert report is not None
        assert report.stage is CycleStage.VERIFY
        assert report.recorded_span_s is None
        assert report.stored is False

    def test_a_zero_span_is_legal(self, tmp_path):
        # the default meter answers 0.0 for a one-profile block, which is a real reading rather than a malformed one
        harness = Harness(tmp_path, span=0.0)
        ok, outcome = harness().try_record_and_store("evidence-03", 1.0, tmp_path)
        assert ok is True, outcome


class TestThePublicReadinessContract:
    """What a factory has to be able to ask before it touches the application."""

    def test_the_binding_is_public_and_read_only(self, tmp_path):
        cycle = Harness(tmp_path)()
        assert cycle.binding is BINDING
        with pytest.raises(AttributeError):
            cycle.binding = None  # type: ignore[misc]

    def test_an_unbound_cycle_says_so(self, tmp_path):
        cycle = Harness(tmp_path, binding=None)()
        assert cycle.binding is None
        assert cycle.configuration_problem() == "cycle_binding_missing"

    def test_a_guarded_cycle_has_no_configuration_problem(self, tmp_path):
        assert Harness(tmp_path)().configuration_problem() is None

    @pytest.mark.parametrize("guard", ["identity", "owner_valid", "read_strip"])
    def test_a_missing_guard_is_named(self, tmp_path, guard):
        cycle = cycle_with(Harness(tmp_path), **{guard: None})
        assert cycle.configuration_problem() == f"cycle_guard_missing:{guard}"

    @pytest.mark.parametrize("guard", ["identity", "owner_valid", "read_strip"])
    def test_a_guard_that_is_not_callable_is_named(self, tmp_path, guard):
        cycle = cycle_with(Harness(tmp_path), **{guard: 0})
        assert cycle.configuration_problem() == f"cycle_guard_invalid:{guard}"

    def test_a_binding_that_contradicts_the_routines_is_named(self, tmp_path):
        binding = BINDING.model_copy(
            update={"store": ObservedAddress(address=0x9999, source="table:other")}
        )
        cycle = Harness(tmp_path, binding=binding)()
        assert cycle.configuration_problem() == "cycle_binding_conflict:store"

    def test_the_check_is_pure_and_calls_no_reader(self, tmp_path):
        def never(*args):
            raise AssertionError("configuration_problem must not read the live application")

        cycle = cycle_with(
            Harness(tmp_path), identity=never, owner_valid=never, read_strip=never
        )
        assert cycle.configuration_problem() is None

    def test_the_preflight_refuses_with_the_same_pure_reason(self, tmp_path):
        harness = Harness(tmp_path)
        cycle = cycle_with(harness, read_strip=0)
        assert cycle.configuration_problem() == "cycle_guard_invalid:read_strip"
        ok, reason = cycle.try_record_and_store("ready-01", 1.0, tmp_path)
        assert ok is False
        assert reason == "cycle_guard_invalid:read_strip"
        assert harness.caller.calls == []
