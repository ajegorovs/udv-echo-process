"""The store-completed entry point: one store dispatch, and nothing that could start, end or clear one.

The block under test is one the **application** finished — a finite multiplexed sequence closes itself
(manual §11), so the cycle is asked to store what is already on screen. Everything asserted here is
offline: a scripted strip, a scripted caller and a Store dialog double that writes a real artifact when
it commits. The artifact used is the repository's own tracked multiplexed recording, so the decode and
the span are the real reader's answers for a real four-channel file.

Three claims, and the third is the one worth the file:

- the entry point dispatches **only** the store routine, exactly once, and never the record address that
  is the start *and* the stop;
- a state, an instance, an owner or a name that is not what this path requires is refused **before** any
  dispatch, so a refusal cannot leave a half-stored block behind;
- the ordinary record/stop/store cycle is unchanged — including its refusal to start from a held block.

No test here touches the application, and none of them lets a fake stand for a live reading.
"""

from __future__ import annotations

import shutil
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

MULTIPLEXED = (
    Path(__file__).resolve().parents[1] / "data" / "4-sensor-velocity" / "200RPM.BDD"
)
BUILD = "a" * 64
PID = 4242
CREATED_NS = 1_760_000_000_000_000_000
RECORD = 0x71F034
STORE = 0x71F060
OWNER = 0x6F2A10


def binding(**overrides) -> CycleBinding:
    payload = {
        "identity": ProcessIdentity(pid=PID, created_ns=CREATED_NS, image_sha256=BUILD),
        "owner": ObservedAddress(address=OWNER, source="observed on the main form"),
        "record": ObservedAddress(address=RECORD, source="table operation record"),
        "store": ObservedAddress(address=STORE, source="table operation store"),
    }
    payload.update(overrides)
    return CycleBinding(**payload)


def routines() -> CycleRoutines:
    return CycleRoutines(record=RECORD, store=STORE, form=OWNER)


class Strip:
    """The strip as a script: one view per read, then the last one repeats."""

    def __init__(self, *views: StripView | StripState) -> None:
        self.views = list(views)
        self.reads = 0

    def __call__(self):
        self.reads += 1
        return self.views.pop(0) if len(self.views) > 1 else self.views[0]


class Caller:
    """A routine caller that answers ``ok`` and remembers which addresses were reached."""

    def __init__(self, answer: dict | None = None) -> None:
        self.addresses: list[int] = []
        self._answer = answer or {"ok": True}

    def __call__(self, address: int, form: int) -> dict:
        self.addresses.append(int(address))
        return dict(self._answer)

    @property
    def record_calls(self) -> list[int]:
        return [address for address in self.addresses if address == RECORD]

    @property
    def store_calls(self) -> list[int]:
        return [address for address in self.addresses if address == STORE]


class Dialog:
    """A Store dialog that writes what it is told to — a copy of a real recording by default."""

    def __init__(
        self,
        directory: Path,
        *,
        source: Path | None = MULTIPLEXED,
        answer: object = True,
    ) -> None:
        self.directory = Path(directory)
        self.commits: list[str] = []
        self._source = source
        self._answer = answer

    def commit(self, name: str) -> object:
        self.commits.append(name)
        if self._answer is True and self._source is not None:
            shutil.copyfile(self._source, self.directory / f"{name}.BDD")
        return self._answer


def cycle(
    tmp_path: Path,
    *,
    views: tuple = (StripView.STORE,),
    caller: Caller | None = None,
    dialog: Dialog | None = None,
    created_ns: int = CREATED_NS,
    owner_valid: object = True,
    **kwargs,
) -> tuple[RoutineCycle, Caller, Dialog, Strip]:
    """A guarded cycle over scripted collaborators — fully bound, so no guard is missing."""
    strip = Strip(*views)
    reached = caller or Caller()
    store_dialog = dialog or Dialog(tmp_path)
    store_timeout_s = kwargs.pop("store_timeout_s", 0.0)
    poll_s = kwargs.pop("poll_s", 0.0)
    seen = ProcessIdentity(pid=PID, created_ns=created_ns, image_sha256=BUILD)
    built = RoutineCycle(
        caller=reached,
        routines=routines(),
        dialog=store_dialog,
        binding=binding(),
        identity=lambda: seen,
        owner_valid=lambda _owner: owner_valid,
        read_strip=strip,
        stop_settle_s=0.0,
        store_settle_s=0.0,
        store_timeout_s=store_timeout_s,
        state_timeout_s=0.0,
        poll_s=poll_s,
        sleep=lambda _seconds: None,
        **kwargs,
    )
    return built, reached, store_dialog, strip


class TestTheHeldBlock:
    def test_one_store_dispatch_and_never_the_record_address(self, tmp_path):
        built, caller, dialog, _ = cycle(tmp_path)
        ok, outcome = built.store_completed_block("mpx-01", tmp_path)
        assert ok is True, outcome
        assert caller.addresses == [STORE]
        assert caller.record_calls == []
        assert dialog.commits == ["mpx-01"]
        assert (tmp_path / "mpx-01.BDD").is_file()

    def test_the_report_claims_only_what_the_invocation_did(self, tmp_path):
        built, _caller, _dialog, _ = cycle(tmp_path)
        ok, outcome = built.store_completed_block("mpx-02", tmp_path)
        assert ok is True, outcome
        report = built.last_report
        assert isinstance(report, CycleReport)
        assert report.stage is CycleStage.DONE
        assert report.recorded is False and report.stopped is False
        assert report.store_requested is True and report.dialog_committed is True
        assert report.stored is True

    def test_a_tracked_multiplexed_artifact_decodes_every_stream(self, tmp_path):
        """The real reader on the repository's own four-channel recording: four streams, a real span."""
        built, _caller, _dialog, _ = cycle(tmp_path)
        ok, outcome = built.store_completed_block("mpx-200rpm", tmp_path)
        assert ok is True, outcome
        report = built.last_report
        assert report.streams == 4
        assert report.recorded_span_s is not None and report.recorded_span_s > 0.0

    def test_the_measured_two_button_row_is_what_this_path_admits(self, tmp_path):
        """The row the 2026-10-21 run ended in: two buttons, slider present (``store/2/1``)."""
        built, caller, _dialog, _ = cycle(
            tmp_path, views=(StripState(button_count=2, has_slider=True),)
        )
        built.store_completed_block("mpx-03", tmp_path)
        assert caller.addresses == [STORE]

    def test_an_empty_artifact_is_refused_rather_than_credited(self, tmp_path):
        empty = tmp_path / "empty-source.BDD"
        empty.write_bytes(b"")
        built, _caller, _dialog, _ = cycle(
            tmp_path, dialog=Dialog(tmp_path, source=empty)
        )
        ok, outcome = built.store_completed_block("empty", tmp_path)
        assert ok is False
        assert str(outcome).startswith("store_file_empty"), outcome

    def test_a_missing_artifact_is_refused(self, tmp_path):
        built, _caller, _dialog, _ = cycle(
            tmp_path, dialog=Dialog(tmp_path, source=None)
        )
        ok, outcome = built.store_completed_block("absent", tmp_path)
        assert ok is False
        assert str(outcome).startswith("store_file_missing"), outcome


class TestWhatIsRefusedBeforeAnyDispatch:
    def test_a_ready_row_has_no_block_to_store(self, tmp_path):
        built, caller, dialog, _ = cycle(tmp_path, views=(StripView.READY,))
        ok, outcome = built.store_completed_block("mpx-04", tmp_path)
        assert ok is False
        assert outcome == "store_completed_strip_not_store:ready", outcome
        assert caller.addresses == [] and dialog.commits == []

    def test_a_recording_row_is_somebody_elses_unfinished_block(self, tmp_path):
        built, caller, dialog, _ = cycle(tmp_path, views=(StripView.RECORDING,))
        ok, outcome = built.store_completed_block("mpx-05", tmp_path)
        assert ok is False
        assert outcome == "store_completed_strip_not_store:recording", outcome
        assert caller.addresses == [] and dialog.commits == []

    def test_a_pid_reused_for_another_instance_is_refused(self, tmp_path):
        built, caller, dialog, _ = cycle(tmp_path, created_ns=CREATED_NS + 1)
        ok, outcome = built.store_completed_block("mpx-06", tmp_path)
        assert ok is False
        assert str(outcome).startswith("cycle_instance_changed"), outcome
        assert caller.addresses == [] and dialog.commits == []

    def test_an_owner_that_does_not_answer_yes_is_refused(self, tmp_path):
        built, caller, dialog, _ = cycle(tmp_path, owner_valid=False)
        ok, outcome = built.store_completed_block("mpx-07", tmp_path)
        assert ok is False
        assert str(outcome).startswith("cycle_owner_unreadable"), outcome
        assert caller.addresses == [] and dialog.commits == []

    def test_a_taken_name_is_refused_before_the_store_routine_is_named(self, tmp_path):
        (tmp_path / "mpx-08.BDD").write_bytes(b"previous block")
        built, caller, dialog, _ = cycle(tmp_path)
        ok, outcome = built.store_completed_block("mpx-08", tmp_path)
        assert ok is False
        assert str(outcome).startswith("store_name_taken"), outcome
        assert caller.addresses == [] and dialog.commits == []

    def test_an_unbounded_store_wait_is_refused(self, tmp_path):
        built, caller, _dialog, _ = cycle(tmp_path, store_timeout_s=10.0, poll_s=0.0)
        ok, outcome = built.store_completed_block("mpx-09", tmp_path)
        assert ok is False
        assert outcome == "cycle_parameter_invalid:poll_s", outcome
        assert caller.addresses == []

    def test_a_missing_guard_is_a_refusal_not_an_unguarded_run(self, tmp_path):
        built = RoutineCycle(
            caller=Caller(),
            routines=routines(),
            dialog=Dialog(tmp_path),
            binding=None,
            identity=lambda: None,
            owner_valid=lambda _owner: True,
            read_strip=Strip(StripView.STORE),
            store_settle_s=0.0,
            store_timeout_s=0.0,
            poll_s=0.0,
            sleep=lambda _seconds: None,
        )
        ok, outcome = built.store_completed_block("mpx-10", tmp_path)
        assert ok is False
        assert outcome == "cycle_binding_missing", outcome


class TestTheDispatchItself:
    def test_a_refused_store_is_a_named_stage_with_its_reason(self, tmp_path):
        refused = Caller({"ok": False, "errors": ["host_record_forbidden:store_only"]})
        built, _caller, dialog, _ = cycle(tmp_path, caller=refused)
        ok, outcome = built.store_completed_block("mpx-11", tmp_path)
        assert ok is False
        assert str(outcome).startswith("store_not_dispatched:"), outcome
        assert built.last_report is not None
        assert built.last_report.store_requested is False
        assert dialog.commits == []

    def test_a_dialog_that_did_not_commit_is_not_a_store(self, tmp_path):
        built, _caller, dialog, _ = cycle(
            tmp_path, dialog=Dialog(tmp_path, answer=False)
        )
        ok, outcome = built.store_completed_block("mpx-12", tmp_path)
        assert ok is False
        assert outcome == "store_dialog_not_committed", outcome
        assert dialog.commits == ["mpx-12"]

    def test_a_decoder_that_finds_no_stream_is_a_failed_store(self, tmp_path):
        built, _caller, _dialog, _ = cycle(tmp_path, decode=lambda _path: 0)
        ok, outcome = built.store_completed_block("mpx-13", tmp_path)
        assert ok is False
        assert outcome == "store_decoded_no_streams", outcome


class TestTheRecordingPathIsUnchanged:
    def test_a_held_block_is_still_not_a_place_to_start_recording(self, tmp_path):
        built, caller, dialog, _ = cycle(tmp_path)
        ok, outcome = built.try_record_and_store("mpx-14", 0.0, tmp_path)
        assert ok is False
        assert str(outcome).startswith("cycle_strip_not_ready:store"), outcome
        assert caller.addresses == [] and dialog.commits == []


#: Tokens a caller must not be able to turn into a target: a path component, a relative step, an empty
#: name, a name that already carries the suffix the cycle appends, a control character (NUL included, the
#: one that makes ``Path.exists`` raise instead of answer) and a Windows device name. Every one of them is
#: paired with the clause the refusal has to name, so a clause cannot be silently reclassified.
ESCAPES = (
    ("", "empty"),
    (".", "relative"),
    ("..", "relative"),
    ("block.BDD", "suffix"),
    ("block.bdd", "suffix"),
    ("..\\escape", "path"),
    ("../escape", "path"),
    ("/absolute", "path"),
    ("C:name", "path"),
    ("\\\\server\\share\\x", "path"),
    ("a\x00b", "control"),
    ("nul", "reserved"),
    ("CON.txt", "reserved"),
    ("com3", "reserved"),
    (" bad", "padded"),
    ("bad ", "padded"),
    ("a*b", "forbidden"),
    ("a?b", "forbidden"),
)

#: Names that are one ordinary file stem and must keep working — the guard may not be an ASCII-only rule.
STEMS = ("mpx-01", "mpx.01.run", "måling-01", "a b", "block_name-2")


class TestTheNameIsOneStem:
    """A supplied token is used exactly as given, or refused — never trimmed, retargeted or repaired.

    The cycle appends ``.BDD`` to whatever it is handed and then watches that path, so a token carrying a
    separator chooses a file outside the directory the run was told to watch, and an embedded NUL makes
    the path probe raise instead of answer. Both are refused before any dispatch, and the refusal quotes
    the token character for character so an operator can see what was refused.
    """

    @pytest.mark.parametrize(("name", "clause"), ESCAPES)
    def test_the_store_completed_path_refuses_it_before_any_dispatch(
        self, tmp_path, name, clause
    ):
        built, caller, dialog, _ = cycle(tmp_path)
        ok, reason = built.store_completed_block(name, tmp_path)
        assert ok is False, reason
        assert reason == f"store_name_invalid:{name}:{clause}", reason
        assert caller.addresses == [] and dialog.commits == []
        assert list(tmp_path.iterdir()) == []
        assert not (tmp_path.parent / "escape.BDD").exists()
        report = built.last_report
        assert report is not None and report.stage is CycleStage.PREFLIGHT
        assert name in report.reason

    @pytest.mark.parametrize(("name", "clause"), ESCAPES)
    def test_the_recording_path_refuses_it_before_any_dispatch(
        self, tmp_path, name, clause
    ):
        built, caller, dialog, _ = cycle(tmp_path, views=(StripView.READY,))
        ok, reason = built.try_record_and_store(name, 0.0, tmp_path)
        assert ok is False, reason
        assert reason == f"store_name_invalid:{name}:{clause}", reason
        assert caller.addresses == [] and dialog.commits == []
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("name", STEMS)
    def test_a_valid_stem_is_used_exactly_as_given(self, tmp_path, name):
        built, caller, dialog, _ = cycle(tmp_path)
        ok, outcome = built.store_completed_block(name, tmp_path)
        assert ok is True, outcome
        assert dialog.commits == [name]
        assert (tmp_path / f"{name}.BDD").is_file()
        assert caller.addresses == [STORE]

    def test_a_valid_stem_still_starts_a_recording(self, tmp_path):
        """The invariant belongs to both entries, so the recording path keeps its default names too."""
        built, caller, dialog, _ = cycle(
            tmp_path, views=(StripView.READY, StripView.RECORDING, StripView.STORE)
        )
        ok, outcome = built.try_record_and_store("måling.01", 0.0, tmp_path)
        assert ok is True, outcome
        assert caller.addresses == [RECORD, RECORD, STORE]
        assert dialog.commits == ["måling.01"]
