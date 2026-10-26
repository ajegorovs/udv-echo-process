"""The cycle's own report rides *beside* the point's verdict, never inside it.

The runner's record answers "was this point's data good". The application's cycle report answers a
different question — where the record/stop/store cycle stopped, what it confirmed, how long the
stored block's own timestamps span — and the two are not the same verdict: a cycle can report a
perfect start and a refused stop while the point's own file never exists, and a stored file can be
sound while the cycle's report was never supplied at all.

So the log carries both, in two fields: ``status``/``failure`` are the point's, ``cycle_report`` is
the application's. The rules pinned here are the ones that keep the second honest:

- the report is **snapshotted once, immediately after the one cycle call** — including the call that
  returned ``False`` and the call that raised — because a property that is read later answers for
  whatever ran last;
- a point whose cycle was never attempted (a pre-flight refusal, the mode rung, a clamped
  read-back) carries **no** report, never the previous point's;
- an actuator without the capability (a legacy or UI double) leaves the field ``None`` and is not an
  error: absence of evidence is not a contradiction;
- a report that **is** offered but is not a :class:`CycleReport`, or names another cycle, is not
  credited to this point, and the point is not credited either — a record whose cycle evidence
  belongs to something else is worse than one with none;
- the captured object is the frozen report itself, so nothing later can move the evidence.

The fakes here extend the runner suite's own :class:`FakeActuator` (``tests.test_acquire_runner``),
which deliberately has no such property: that is the legacy double whose behaviour must not change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.test_acquire_cycle_safety import ROUTINES, Dialog, Harness
from tests.test_acquire_runner import (
    DURATION_S,
    FakeActuator,
    ScriptedVerifier,
    make_runner,
    patch_reader,
    patch_verifier,
    point_for,
)
from udv_echo_process.acquire.actuator import (
    STORE_TIMEOUT_S,
    ProcessMode,
    StripControl,
    StripView,
)
from udv_echo_process.acquire.bridge import BridgeActuator
from udv_echo_process.acquire.config import RecordSettings
from udv_echo_process.acquire.cycle import CycleReport, CycleStage
from udv_echo_process.acquire.log import (
    PointStatus,
    SizeSignature,
    SweepPointRecord,
    point_records,
    read_entries,
)
from udv_echo_process.acquire.runner import SweepRunner

#: The span the fake's cycle reports: the stored block's own elapsed time, which is not the window
#: (``cycle.SpanMeter``) and is the field a reader would lose if the report were flattened to a name.
CYCLE_SPAN_S = 4.56

#: "The case scripted no report" — distinct from ``None``, which is a property that answers nothing.
UNSET = object()


def cycle_report(
    name: str, stage: CycleStage = CycleStage.DONE, **overrides: object
) -> CycleReport:
    """A report of the shape a completed cycle builds, with ``name`` as the cycle it names."""
    fields: dict[str, object] = {
        "name": name,
        "stage": stage,
        "recorded": True,
        "stopped": True,
        "store_requested": True,
        "dialog_committed": True,
        "stored": True,
        "streams": 1,
        "recorded_span_s": CYCLE_SPAN_S,
        "last_view": StripView.READY,
    }
    fields.update(overrides)
    return CycleReport(**fields)  # type: ignore[arg-type]


class ReportingActuator(FakeActuator):
    """A fake that carries the cycle report the message-route actuator will carry.

    The agreed interface, exercised end to end: the property holds the report of the cycle that was
    actually supplied, it is reset before every invocation, and it is captured on every exit — the
    success, the ``(False, reason)`` return and the raise. :attr:`scripted_report` replaces what the
    property answers when a case needs to hand over something that is not that cycle's report, which
    is how a stale or foreign report is staged.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.report: object = None
        #: How often the runner read the property — one read per cycle, never more.
        self.report_reads = 0
        #: What the property answers instead of the cycle's own report; ``UNSET`` means "that report".
        self.scripted_report: object = UNSET
        #: Make the cycle raise after it has captured its report (the abort case).
        self.raise_from_cycle: str | None = None
        #: Answer the property once and then nothing, so a second read is visible as a lost report.
        self.answer_once = False

    @property
    def last_cycle_report(self) -> object:
        self.report_reads += 1
        if self.scripted_report is not UNSET:
            return self.scripted_report
        report, self.report = self.report, None if self.answer_once else self.report
        return report

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: object,
        timeout_s: float = STORE_TIMEOUT_S,
        verify_channel: bool = True,
        **extra: object,
    ) -> tuple[bool, object]:
        self.report = (
            None  # the reset the cycle's producer does before every invocation
        )
        if self.raise_from_cycle is not None:
            self.report = cycle_report(
                name,
                CycleStage.STORE,
                stored=False,
                store_requested=False,
                dialog_committed=False,
                reason=self.raise_from_cycle,
            )
            raise RuntimeError(self.raise_from_cycle)
        stored, result = super().try_record_and_store(
            name,
            duration_s,
            directory,
            expected_mode=expected_mode,  # type: ignore[arg-type]
            timeout_s=timeout_s,
            verify_channel=verify_channel,
            **extra,
        )
        if stored:
            self.report = cycle_report(name)
        else:
            # A cycle that stopped at the stop: recorded, never stopped, no store, no span.
            self.report = cycle_report(
                name,
                CycleStage.STOP,
                stopped=False,
                stored=False,
                store_requested=False,
                dialog_committed=False,
                streams=0,
                recorded_span_s=None,
                last_view=StripView.RECORDING,
                reason=str(result),
            )
        return stored, result


def reports_of(log_path: Path) -> list[CycleReport | None]:
    """Every point record's cycle report, in log order."""
    return [record.cycle_report for record in point_records(read_entries(log_path))]


# ------------------------------------------------------- the report reaches the log


def test_a_stored_point_carries_its_cycle_report_into_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The successful path: serialized, round-tripped, and the span survives the trip."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    records = point_records(read_entries(log_path))
    assert len(records) == 1
    report = records[0].cycle_report
    assert isinstance(report, CycleReport)
    assert report.name == records[0].name
    assert report.stage is CycleStage.DONE
    assert report.stored is True
    assert report.streams == 1
    # The span is the reason the field is typed rather than a name: it is the block's own elapsed
    # time, and a reader that lost it would have to re-decode to get it back.
    assert report.recorded_span_s == pytest.approx(CYCLE_SPAN_S)
    assert report.last_view is StripView.READY
    # One serialized line, and the field is on it under its own name.
    line = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert line["cycle_report"]["stage"] == "done"
    assert line["cycle_report"]["recorded_span_s"] == pytest.approx(CYCLE_SPAN_S)
    assert fake.report_reads == 1


def test_a_partial_stop_failure_keeps_the_point_and_cycle_verdicts_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cycle that stopped at the stop: the point failed, and the report says where."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    fake.store_failure = "stop_not_dispatched: the strip never left recording"

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "the record/store cycle failed" in (outcome.reason or ""), outcome.reason
    record = point_records(read_entries(log_path))[0]
    assert record.status is PointStatus.FAILED
    # The point's verdict is its own: the cycle's stage and reason are not merged into it.
    assert record.failure is not None
    assert "the record/store cycle failed" in record.failure
    assert record.cycle_report is not None
    assert record.cycle_report.stage is CycleStage.STOP
    assert record.cycle_report.recorded is True
    assert record.cycle_report.stopped is False
    assert record.cycle_report.store_requested is False
    assert record.cycle_report.recorded_span_s is None
    assert (
        record.cycle_report.reason
        == "stop_not_dispatched: the strip never left recording"
    )


def test_a_cycle_that_raised_is_still_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The abort path: an exception is an exit, so the report captured on it is kept."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    fake.raise_from_cycle = "the store dialog never came back"

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "raised" in (outcome.reason or ""), outcome.reason
    record = point_records(read_entries(log_path))[0]
    assert record.status is PointStatus.FAILED
    assert record.cycle_report is not None
    assert record.cycle_report.stage is CycleStage.STORE
    assert record.cycle_report.reason == "the store dialog never came back"


def test_the_report_is_snapshotted_at_the_cycle_not_re_read_for_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One read, at the cycle: a property that forgets afterwards cannot empty the record."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    fake.answer_once = True

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    assert fake.report_reads == 1, (
        "the log was written from a snapshot, not from a second read"
    )
    assert reports_of(log_path)[0] is not None


# ----------------------------------------------------- where a report must not appear


def test_a_point_refused_before_its_cycle_logs_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-flight refusal never reads the property, so a stale report cannot be credited."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    # A report already sitting on the actuator, as it would after an earlier point or run.
    fake.scripted_report = cycle_report("sw100-k9-20260101T000000")
    fake.process_mode_note_value = "the caption states Simulation, not Instrument"

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert fake.report_reads == 0, "no cycle was attempted, so there is nothing to read"
    record = point_records(read_entries(log_path))[0]
    assert record.cycle_report is None


def test_consecutive_points_are_not_credited_with_the_previous_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second point's refusal must not inherit the first point's stored cycle."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )

    first = engine.run_point(point_for(1), DURATION_S)
    assert first.ok is True, first.reason
    # The actuator still holds the first cycle's report: no second cycle has reset it.
    fake.process_mode_note_value = "the caption states Simulation, not Instrument"
    second = engine.run_point(point_for(2), DURATION_S)

    assert second.ok is False
    records = point_records(read_entries(log_path))
    assert [record.key for record in records] == [1, 2]
    assert records[0].cycle_report is not None
    assert records[0].cycle_report.name == records[0].name
    assert records[1].cycle_report is None, (
        "the first point's report is not the second's"
    )
    assert fake.report_reads == 1


def test_an_actuator_without_the_capability_logs_no_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy or UI double has no such property, and that is not an error state."""
    assert not hasattr(FakeActuator, "last_cycle_report")
    _fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    record = point_records(read_entries(log_path))[0]
    assert record.cycle_report is None


# ------------------------------------------- a report that contradicts its own point


def test_a_report_that_is_not_a_cycle_report_is_not_credited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An untyped hand-over is evidence of nothing, and it does not pass the point."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    fake.scripted_report = {"name": "sw100-k1-20260101T000000", "stage": "done"}

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, (
        "a cycle whose own account of itself does not hold cannot establish where the "
        "application is, so the run stops here"
    )
    assert "cycle_report_unattributable" in (outcome.reason or ""), outcome.reason
    assert "the run stops here" in (outcome.reason or ""), outcome.reason
    assert "dict" in (outcome.reason or ""), outcome.reason
    record = point_records(read_entries(log_path))[0]
    assert record.status is PointStatus.INVALID
    assert record.cycle_report is None
    assert "cycle_report_unattributable" in (record.failure or "")
    # The artifact is named even though it was not credited, so the refusal points at something.
    assert (record.file_path or "").endswith(".BDD")


def test_a_report_naming_another_cycle_is_not_credited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report of some other cycle is recorded as the contradiction it is, not as this point's."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    fake.scripted_report = cycle_report(
        "sw100-k0-20260101T000000",
        CycleStage.STOP,
        stopped=False,
        stored=False,
        reason="stop_not_confirmed:recording",
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "cycle_report_unattributable" in (outcome.reason or ""), outcome.reason
    # The foreign report's own details survive: a reader sees what was offered and why it was
    # refused, instead of the attribution failing silently.
    assert "sw100-k0-20260101T000000" in (outcome.reason or "")
    assert "stop_not_confirmed:recording" in (outcome.reason or "")
    record = point_records(read_entries(log_path))[0]
    assert record.status is PointStatus.INVALID
    assert record.cycle_report is None


def test_a_contradicted_cycle_aborts_the_run_before_the_next_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cycle that claims a store its report does not corroborate ends the run.

    ``run_points`` is the public entry a campaign uses, so this is the rule seen from outside: one
    point is spent, and the next one is not reset, not configured and not recorded — because the
    contradiction is about *where the application is*, which is the one thing a later point cannot
    be planned around.
    """
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    fake.scripted_report = cycle_report("sw100-k0-20260101T000000")

    outcomes = engine.run_points((point_for(1), point_for(2)), DURATION_S)

    assert len(outcomes) == 1, "the second point must not be attempted"
    assert outcomes[0].ok is False
    assert outcomes[0].aborted is True, outcomes[0].reason
    reason = outcomes[0].reason or ""
    assert "cycle_report_unattributable" in reason, reason
    # Exactly one of each: one reset, one configuration, one cycle — nothing for a second point.
    presses = [call for call in fake.calls if call[0] == "press"]
    assert presses == [("press", StripControl.CLEAR_AND_RESTART.value)], presses
    assert [call for call in fake.calls if call[0] == "apply_point"] == [
        ("apply_point", point_for(1).parameters.gates)
    ]
    cycles = [call for call in fake.calls if call[0] == "try_record_and_store"]
    assert len(cycles) == 1, cycles
    assert cycles[0][2] == pytest.approx(DURATION_S)
    records = point_records(read_entries(log_path))
    assert [record.key for record in records] == [1]
    assert records[0].status is PointStatus.INVALID
    assert records[0].cycle_report is None
    # One finding, once. The abort note is appended to the *reason* after the attribution note was
    # put there, so a comparison against the whole reason never matched and the log carried the same
    # sentence twice — in the one field a reader has to be able to quote.
    failure = records[0].failure or ""
    assert failure.count("cycle_report_unattributable") == 1, failure


def test_a_failed_cycle_keeps_its_own_cause_beside_the_attribution_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The original failure is never swallowed in order to report the attribution problem."""
    fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    fake.raise_from_cycle = "the store dialog never came back"
    fake.scripted_report = cycle_report("sw100-k0-20260101T000000")

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    # The outcome still says what actually went wrong with the cycle...
    assert "raised" in (outcome.reason or ""), outcome.reason
    assert "the store dialog never came back" in (outcome.reason or ""), outcome.reason
    record = point_records(read_entries(log_path))[0]
    # ...and the log keeps both findings: the cause first, the attribution note beside it.
    failure = record.failure or ""
    assert "the store dialog never came back" in failure
    assert "cycle_report_unattributable" in failure
    assert failure.index("the store dialog never came back") < failure.index(
        "cycle_report_unattributable"
    )
    assert record.cycle_report is None


def test_the_captured_report_cannot_be_changed_afterwards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The log holds the frozen report itself, so the evidence cannot be rewritten."""
    _fake, engine, log_path, _ = make_runner(
        tmp_path, monkeypatch, fake_class=ReportingActuator
    )
    engine.run_point(point_for(1), DURATION_S)

    report = point_records(read_entries(log_path))[0].cycle_report
    assert report is not None
    with pytest.raises(ValidationError):
        report.stage = CycleStage.PREFLIGHT  # type: ignore[misc]
    with pytest.raises(ValidationError):
        report.stored = False  # type: ignore[misc]


# --------------------------------------------------------------- the log's own side


def test_a_point_record_written_before_the_field_existed_reads_back(
    tmp_path: Path,
) -> None:
    """An older log has no ``cycle_report`` key; the field's default is how it stays readable."""
    legacy = SweepPointRecord(
        sweep_id="20260917T161738",
        key=1,
        name="sw100-k1-20260917T161738",
        status=PointStatus.OK,
        requested=point_for(1).parameters,
    )
    payload = legacy.model_dump(mode="json")
    assert payload.pop("cycle_report", None) is None
    path = tmp_path / "sweep.jsonl"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    entries = read_entries(path)

    assert len(entries) == 1
    assert isinstance(entries[0], SweepPointRecord)
    assert entries[0].cycle_report is None
    assert entries[0].status is PointStatus.OK


def test_a_report_round_trips_through_the_log_unchanged(tmp_path: Path) -> None:
    """Serialization is lossless for every field the cycle reports, enum values included."""
    report = cycle_report("sw100-k1-20260917T161738")
    record = SweepPointRecord(
        sweep_id="20260917T161738",
        key=1,
        name="sw100-k1-20260917T161738",
        status=PointStatus.OK,
        requested=point_for(1).parameters,
        cycle_report=report,
    )

    restored = SweepPointRecord.model_validate_json(record.model_dump_json())

    assert restored.cycle_report == report


# ------------------------------------------- the real wrapper, over a real cycle, under the runner
#
# Everything above hands the runner a *double* that already carries the property. The seam the
# runner actually meets in a run is `BridgeActuator`, and its `last_cycle_report` has to answer for
# the invocation that just happened: a legacy cycle gives it nothing (absence), and a cycle that
# offers evidence the wrapper cannot use must not end up looking like absence. `None` is the
# runner's "no such capability", so an evidence value dropped inside the wrapper is
# indistinguishable, at the log, from an actuator that never had one — which is how a contradicted
# cycle could be logged as a clean success.


class _Table:
    """The table stub the wrapper needs; the cycle path reads no routine from it."""

    image_sha256 = "0" * 64


class _SizedDialog(Dialog):
    """The store dialog, writing a block the runner's own size signature will accept.

    The size guard is part of the point's verdict, so the file this dialog writes is the size the
    point's own plan predicts rather than a number chosen here.
    """

    def __init__(self, fake: FakeActuator) -> None:
        super().__init__()
        self.fake = fake

    def commit(self, name: str) -> bool:
        self.commits.append(name)
        size = self.fake.expected_size(DURATION_S) or 1
        (self.directory / f"{name}.BDD").write_bytes(b"\x00" * size)
        return True


class Offering:
    """A real cycle whose *offered* report is replaced after the invocation ran.

    The producer of the report is the cycle, and the states that matter are the ones a cycle can
    reach by being wrong about its own evidence: another cycle's report, a value that is not a
    report at all, or a report that contradicts what the cycle returned. The invocation itself
    stays real — it records, stops, stores and commits — so the wrapper is answering about a
    genuine store rather than a scripted one.
    """

    def __init__(self, cycle: object, mutate) -> None:
        self._cycle = cycle
        self._mutate = mutate
        self.last_report: object = getattr(cycle, "last_report", None)

    def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
        try:
            return self._cycle.try_record_and_store(  # type: ignore[attr-defined]
                name, duration_s, directory, expected_mode=expected_mode
            )
        finally:
            self.last_report = self._mutate(
                self._cycle.last_report  # type: ignore[attr-defined]
            )


class Unreadable:
    """A cycle whose report *property* refuses to answer — unreadable evidence, not absence."""

    def __init__(self, cycle: object) -> None:
        self._cycle = cycle

    def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
        return self._cycle.try_record_and_store(  # type: ignore[attr-defined]
            name, duration_s, directory, expected_mode=expected_mode
        )

    @property
    def last_report(self) -> object:
        raise RuntimeError("the report was dropped by the producer")


class Raising(Offering):
    """A cycle that stores, then loses its own exit: the exception is the point's cause."""

    def __init__(self, cycle: object, mutate, error: BaseException) -> None:
        super().__init__(cycle, mutate)
        self.error = error

    def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
        super().try_record_and_store(
            name, duration_s, directory, expected_mode=expected_mode
        )
        raise self.error


class Legacy:
    """A generic ``StoreCycle``: the pre-report shape a caller may still inject directly."""

    def __init__(self, size_of) -> None:
        self.size_of = size_of
        self.calls: list[str] = []

    def try_record_and_store(self, name, duration_s, directory, *, expected_mode=None):
        self.calls.append(name)
        target = Path(directory) / f"{name}.BDD"
        target.write_bytes(b"\x00" * (self.size_of() or 1))
        return True, target


def _second_name(first: str) -> str:
    """The name the next point of the same sweep will ask for, derived from the last one.

    The runner names points ``<prefix>-k<key>-<sweep-id>``; the sweep id is generated per run, so the
    next point's name is this one with the key moved on by one rather than a name guessed here.
    """
    prefix, _, rest = first.partition("-k")
    key, _, sweep = rest.partition("-")
    return f"{prefix}-k{int(key) + 1}-{sweep}"


def composed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    wrap=None,
    **harness_kwargs: object,
):
    """A real wrapper over a real cycle, driven by a real ``SweepRunner`` and its own JSONL.

    The cycle is the hardened :class:`RoutineCycle` built by the safety suite's ``Harness`` — real
    binding, real guards, real transition confirmation — with the application-facing edges injected
    the way that suite injects them, and the store dialog writing a block of the size the runner's
    own signature expects. ``wrap`` receives the cycle and the fake and replaces what the cycle
    *offers*, never what it does.
    """
    capture = Path(tmp_path) / "capture"
    capture.mkdir(parents=True, exist_ok=True)
    log_path = Path(tmp_path) / "logs" / "sweep.jsonl"
    signature = SizeSignature()
    fake = FakeActuator(capture, signature=signature)
    dialog = _SizedDialog(fake)
    harness = Harness(capture, dialog=dialog, **harness_kwargs)  # type: ignore[arg-type]
    cycle = harness()
    offered = cycle if wrap is None else wrap(cycle, fake)
    actuator = BridgeActuator(fake, table=_Table(), dispatch=None, cycle=offered)
    engine = SweepRunner(
        actuator,
        RecordSettings(name_prefix="sw100"),
        capture,
        signature=signature,
        log_path=log_path,
        expected_mode=ProcessMode.INSTRUMENT,
    )
    patch_reader(monkeypatch, fake=fake)
    patch_verifier(monkeypatch, ScriptedVerifier())
    return fake, engine, log_path, actuator, cycle, harness


def test_a_real_cycle_with_a_typed_report_is_credited_and_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The happy path through every real layer: the point is ok and its report is the cycle's own."""
    _fake, engine, log_path, actuator, cycle, harness = composed_run(tmp_path, monkeypatch)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    record = point_records(read_entries(log_path))[0]
    assert record.status is PointStatus.OK
    report = record.cycle_report
    assert isinstance(report, CycleReport)
    assert report == cycle.last_report
    assert report.name == record.name
    assert report.stage is CycleStage.DONE
    assert report.stored is True
    assert report.streams == 1
    assert actuator.last_cycle_report == report
    assert actuator.cycle_report_problem is None
    # The cycle really ran: record, stop, store and the dialog's own commit all happened.
    assert [address for address, _form in harness.caller.calls] == [
        ROUTINES.record,
        ROUTINES.record,
        ROUTINES.store,
    ]
    assert harness.dialog.commits == [record.name]


def test_a_generic_cycle_without_a_report_is_not_a_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cycle that has no report is absence: the point keeps its verdict, the field stays ``None``.

    This is the state ``None`` is reserved for. A generic ``StoreCycle`` may be injected directly,
    it has no ``last_report`` at all, and refusing such a point would retire every legacy cycle.
    """
    generic: list[Legacy] = []

    def wrap(cycle: object, fake: FakeActuator) -> object:
        generic.append(Legacy(lambda: fake.expected_size(DURATION_S)))
        return generic[-1]

    _fake, engine, log_path, actuator, _cycle, _harness = composed_run(
        tmp_path, monkeypatch, wrap=wrap
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
    record = point_records(read_entries(log_path))[0]
    assert record.status is PointStatus.OK
    assert record.cycle_report is None
    assert actuator.cycle_report_problem is None
    assert record.failure is None
    assert generic[0].calls == [record.name]


@pytest.mark.parametrize(
    ("mutate", "token"),
    [
        (lambda report: "stored, trust me", "bridge_cycle_report_invalid:str"),
        (
            lambda report: RuntimeError("the producer lost it"),
            "bridge_cycle_report_invalid:RuntimeError",
        ),
        (
            lambda report: report.model_copy(update={"name": "sw100-k9-20260101T000000"}),
            "bridge_cycle_report_unattributable:sw100-k9-20260101T000000",
        ),
        (
            lambda report: report.model_copy(
                update={
                    "stage": CycleStage.VERIFY,
                    "stored": False,
                    "streams": 0,
                    "recorded_span_s": None,
                    "reason": "store_undecodable:OSError",
                }
            ),
            "bridge_cycle_report_contradicts_store",
        ),
    ],
    ids=["string", "exception", "another-name", "contradicted-store"],
)
def test_an_offered_report_the_wrapper_cannot_use_fails_the_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    token: str,
) -> None:
    """A stored file whose own account of itself does not hold is not a success.

    The cycle stored — the file is on disk — but what it offered as its report is unusable,
    belongs to another cycle, or contradicts the store it just claimed. The point is refused, the
    run stops, and the reason names *which* of those it was exactly once: the wrapper's diagnostic
    and the runner's note are the same finding, so it may not be serialised twice.
    """
    _fake, engine, log_path, actuator, _cycle, _harness = composed_run(
        tmp_path, monkeypatch, wrap=lambda cycle, fake: Offering(cycle, mutate)
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    reason = outcome.reason or ""
    assert token in reason, reason
    record = point_records(read_entries(log_path))[0]
    assert record.status is not PointStatus.OK
    assert record.cycle_report is None
    assert record.failure is not None
    assert record.failure.count(token) == 1, record.failure
    # The store did happen: this is a refusal of the evidence, not of the file's existence.
    assert [path.suffix for path in (Path(tmp_path) / "capture").glob("*")] == [".BDD"]
    assert actuator.cycle_report_problem is not None
    assert token in actuator.cycle_report_problem


def test_an_unreadable_report_fails_the_point_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A property that raises is evidence that could not be read — not an actuator without one."""
    _fake, engine, log_path, actuator, _cycle, _harness = composed_run(
        tmp_path, monkeypatch, wrap=lambda cycle, fake: Unreadable(cycle)
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    token = "bridge_cycle_report_unreadable:RuntimeError"
    reason = outcome.reason or ""
    assert token in reason, reason
    record = point_records(read_entries(log_path))[0]
    assert record.status is not PointStatus.OK
    assert record.cycle_report is None
    assert record.failure is not None
    assert record.failure.count(token) == 1, record.failure
    assert "cycle_report_unattributable" not in record.failure
    assert actuator.cycle_report_problem is not None
    assert token in actuator.cycle_report_problem


def test_a_failed_cycle_keeps_its_own_reason_before_the_attribution_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the cycle itself failed *and* offered junk, the failure stays the point's cause."""
    _fake, engine, log_path, _actuator, _cycle, harness = composed_run(
        tmp_path,
        monkeypatch,
        results=[{"ok": False, "errors": ["the record routine refused"]}],
        wrap=lambda cycle, fake: Offering(cycle, lambda report: "not a report"),
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    reason = outcome.reason or ""
    assert "the record/store cycle failed" in reason, reason
    assert "record_not_dispatched" in reason, reason
    assert "the record routine refused" in reason, reason
    assert "bridge_cycle_report_invalid:str" in reason, reason
    assert reason.index("record_not_dispatched") < reason.index(
        "bridge_cycle_report_invalid"
    )
    record = point_records(read_entries(log_path))[0]
    assert record.cycle_report is None
    failure = record.failure or ""
    assert "record_not_dispatched" in failure
    assert failure.count("bridge_cycle_report_invalid:str") == 1, failure
    assert failure.index("record_not_dispatched") < failure.index(
        "bridge_cycle_report_invalid"
    )
    assert harness.dialog.commits == []


def test_a_raising_cycle_keeps_its_exception_as_the_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exception is never exchanged for the note: both are reported, the cause first."""
    error = RuntimeError("the store dialog never came back")
    _fake, engine, log_path, _actuator, _cycle, _harness = composed_run(
        tmp_path,
        monkeypatch,
        wrap=lambda cycle, fake: Raising(cycle, lambda report: 17, error),
    )

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    reason = outcome.reason or ""
    assert "raised" in reason, reason
    assert "the store dialog never came back" in reason, reason
    record = point_records(read_entries(log_path))[0]
    assert record.cycle_report is None
    failure = record.failure or ""
    assert "the store dialog never came back" in failure
    assert failure.count("bridge_cycle_report_invalid:int") == 1, failure


def test_the_diagnostic_is_reset_by_a_point_whose_cycle_never_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wrapper's diagnostic answers for one invocation, like the report it describes.

    A point refused before its cycle must hand over neither the earlier report nor its problem: an
    actuator's property is read once, right after that point's call, and a stale diagnostic would
    attribute the previous point's failure to this one.
    """
    _fake, engine, log_path, actuator, _cycle, harness = composed_run(
        tmp_path,
        monkeypatch,
        wrap=lambda cycle, fake: Offering(cycle, lambda report: "junk"),
    )
    assert engine.run_point(point_for(1), DURATION_S).ok is False
    assert actuator.cycle_report_problem is not None
    first = point_records(read_entries(log_path))[0]

    # The next attempt is refused inside the wrapper, before its cycle: the name is already taken.
    taken = _second_name(first.name)
    (Path(tmp_path) / "capture" / f"{taken}.BDD").write_bytes(b"held")
    outcome = engine.run_point(point_for(2), DURATION_S)

    assert outcome.ok is False
    assert f"store_name_taken:{taken}.BDD" in (outcome.reason or ""), outcome.reason
    assert actuator.cycle_report_problem is None, "a pre-cycle refusal leaves no diagnostic"
    assert actuator.last_cycle_report is None
    assert len(harness.caller.calls) == 3, "the second point never reached a dispatch"
