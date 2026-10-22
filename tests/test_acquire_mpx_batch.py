"""Tests for the finite multiplexed batch (``acquire mpx-run --also``).

The batch is exercised through the **production** parent: :func:`run_mpx_batch` calls the real
:func:`…mpx_run.run_mpx_once` with the existing owners' seams scripted, exactly as the single
run's tests do. The one fact that is not simulated is the boundary artifact check: it is the real
:func:`…mpx_artifact.verify_mpx_artifact` against a real `.BDD` fixture copied under each item's
own name, so the gate's fresh digest comparison is production code on real bytes.

Offline only: no window is enumerated, no GUI is driven and no real input is sent.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from udv_echo_process.acquire import mpx_artifact, mpx_batch, mpx_run
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.channels_capture import (
    CaptureEvidence,
    GuardComparison,
    NumericBracketing,
    WindowGuard,
)
from udv_echo_process.acquire.channels_inspect import (
    ChannelInspection,
    InspectionOutcome,
)
from udv_echo_process.acquire.channels_repeat import claim_trial_record
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.acquire.enable_multiplexed import (
    EnableMultiplexedResult,
    EnableStage,
)
from udv_echo_process.acquire.mode_marks import ModeMarkAttribution
from udv_echo_process.acquire.mpx_artifact import MpxArtifactReport, MpxVerdict
from udv_echo_process.acquire.mpx_batch import (
    MpxBatchItem,
    MpxBatchStage,
    parse_also,
    run_mpx_batch,
)
from udv_echo_process.acquire.record_multiplexed import (
    MpxStage,
    MultiplexedRecordingDeclaration,
    MultiplexedRecordingResult,
)
from udv_echo_process.acquire.set_rollover import (
    PopupClosure,
    Rolling,
    SetRolloverResult,
    SetRolloverStage,
)
from udv_echo_process.acquire.store_completed import CompletedBlockDeclaration
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    ChannelsOpen,
    DismissalOutcome,
    PopupOutcome,
)
from udv_echo_process.acquire.ui.channels import ChannelsRead, ChannelsSurface
from udv_echo_process.cli import acquire_main

#: A real four-channel block, and the declaration that matches it exactly. Using the fixture's
#: own channels and profile count means the boundary check is a real decode, not a stub.
FIXTURE = Path("data/4-sensor-velocity/200RPM.BDD")
CHANNELS = (6, 7, 8, 9)
PROFILES = 400


def target(hwnd: int = 4242) -> WindowTarget:
    return WindowTarget(hwnd=hwnd, thread_id=11, process_id=22, class_name="TMain_Scr")


def declaration() -> MultiplexedRecordingDeclaration:
    return MultiplexedRecordingDeclaration(
        multiplexer_enabled=True,
        channels=CHANNELS,
        profiles_per_channel=PROFILES,
        stated_by="operator",
    )


def capture(
    rolling: str,
    mode: str,
    *,
    directory: str | None = None,
    hwnd: int = 4242,
    popup_hwnd: int | None = 9001,
    surface: str = "SETTINGS_FULL",
) -> CaptureEvidence:
    guard = WindowGuard(label="UDOP", hwnd=hwnd, popup_hwnd=popup_hwnd)
    return CaptureEvidence(
        status="ok",
        captured=True,
        directory=directory,
        guards=GuardComparison(before=guard, after=guard.model_copy(), consistent=True),
        numeric=NumericBracketing(consistent=True),
        visual_mode_mark=ModeMarkAttribution(
            surface=surface,
            label="ENABLE_MULTIPLEXER",
            mode=mode,
            mark="GREEN_CHECK" if mode == "VISUAL_ENABLED" else "RED_CROSS",
            rolling=rolling,
            acquisition_context="live-bracketed",
            freshness="live_bracketed",
            integrity="capture-digest-verified",
            frames_agreed=True,
            recognition="EXACT_TEMPLATE_MATCH",
            frame_digests=("a" * 64, "b" * 64),
            enable_precondition=True,
        ),
    )


def inspection(
    rolling: str = "OFF_PROVEN", mode: str = "VISUAL_DISABLED"
) -> ChannelInspection:
    return ChannelInspection(
        outcome=InspectionOutcome.CLOSED,
        mode="ready",
        mode_source="strip_state",
        read=ChannelsRead(
            surface=ChannelsSurface.SETTINGS_POPUP,
            readable=True,
            capture=capture(rolling, mode),
        ),
        popup_left_open=False,
    )


def rollover(on: bool = True) -> SetRolloverResult:
    return SetRolloverResult(
        stage=SetRolloverStage.PRESSED,
        requested=Rolling.ON if on else Rolling.OFF,
        expect=Rolling.OFF if on else Rolling.ON,
        baseline=Rolling.OFF,
        bound_target=target(),
        post_rolling="ON_PROVEN" if on else "OFF_PROVEN",
        popup_closure=PopupClosure.OWNED_CLOSED,
        presses=1,
        press="attempted",
    )


def enable_result() -> EnableMultiplexedResult:
    return EnableMultiplexedResult(
        stage=EnableStage.PRESSED,
        bound_target=target(),
        post_surface="multiplexer_on_entry",
        post_mode="VISUAL_ENABLED",
        presses=1,
        press="attempted",
    )


class FakeActuator:
    """Records binding/verification only; the children are seams, not this object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def bind_target(self, hwnd: int) -> WindowTarget:
        self.calls.append(("bind_target", hwnd))
        return target(hwnd)

    def verify_bound_target(self, expected: WindowTarget) -> WindowTarget:
        self.calls.append(("verify_bound_target", expected.hwnd))
        return expected


class BatchHarness:
    """Scripted owners for a batch, with per-item behaviour keyed by the item's index."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = root / "store"
        self.store.mkdir()
        self.captures = root / "captures"
        self.captures.mkdir()
        self.calls: list[str] = []
        self.actuator = FakeActuator()
        self.seen_bound: list[object] = []
        #: One run is one baseline inspection followed by one post-save inspection; the popup
        #: reads of each run start again at the pre-open surface.
        self.inspect_calls = 0
        self.popup_reads = 0
        self.run_index = 0
        self.post_save = inspection()
        self.rollover_interrupt_at: int | None = None
        self.rollover_closure_unsettled_at: int | None = None
        self.record_bound = target()
        self.record_digest: str | None = None
        self.record_stored_path: Path | None = None
        self.record_verdict = MpxVerdict.CONSISTENT
        self.rollover_bound: WindowTarget | None = None
        self.system_exit_at_attempt: int | None = None
        self.gate_verify_calls = 0
        self.gate_interrupt_at: int | None = None
        self.gate_bad_digest_at: int | None = None
        #: Files another process leaves behind mid-batch, by name, so a later item's own
        #: preflight refuses after the earlier items completed.
        self.write_ahead: set[str] = set()

    @property
    def attempt(self) -> int:
        """1-based index of the run that is currently asking."""
        return max(1, self.run_index)

    # -- the child owners ---------------------------------------------------------------
    def inspect(self, **kwargs: object) -> ChannelInspection:
        self.inspect_calls += 1
        baseline = self.inspect_calls % 2 == 1
        if baseline:
            self.run_index += 1
            self.popup_reads = 0
        label = "inspect:baseline" if baseline else "inspect:post"
        self.calls.append(label)
        base = inspection() if label == "inspect:baseline" else self.post_save
        directory = kwargs.get("capture_dir")
        assert directory is not None and base.read is not None
        assert base.read.capture is not None
        read = base.read.model_copy(
            update={
                "capture": base.read.capture.model_copy(
                    update={"directory": str(Path(str(directory)) / "capture-001")}
                )
            }
        )
        return base.model_copy(update={"read": read})

    def read_popup(self, *args: object, **kwargs: object) -> SimpleNamespace:
        pattern = ("absent", "multiplexer_on_entry", "absent")
        surface = pattern[min(self.popup_reads, len(pattern) - 1)]
        self.popup_reads += 1
        read = SimpleNamespace(
            surface=ChannelsSurface(surface), readable=surface != "absent"
        )
        directory = kwargs.get("capture_dir")
        if directory is not None:
            read.capture = capture(
                "ON_PROVEN",
                "VISUAL_ENABLED",
                directory=str(Path(str(directory)) / "capture-001"),
                surface="MULTIPLEXER_ON_ENTRY",
            )
        return read

    def close_popup(self, **kwargs: object) -> ChannelsDismissal:
        self.calls.append("dismiss")
        return ChannelsDismissal(
            outcome=DismissalOutcome.ABSENT,
            point=(500, 500),
            surface_before="multiplexer_on_entry",
            surface_after="absent",
            reads=2,
            steps=4,
        )

    def set_rollover(self, **kwargs: object) -> SetRolloverResult:
        self.calls.append("rollover")
        self.seen_bound.append(kwargs.get("bound_target"))
        record = kwargs.get("trial_record")
        if record is not None:
            claim_trial_record(Path(str(record)), {"command": "fake-rollover"})
        if self.rollover_interrupt_at == self.attempt:
            raise KeyboardInterrupt("operator cancelled this run")
        if self.system_exit_at_attempt == self.attempt:
            raise SystemExit("the process was asked to exit")
        result = rollover(str(kwargs["requested"]) == "on")
        if self.rollover_bound is not None:
            result = result.model_copy(update={"bound_target": self.rollover_bound})
        if self.rollover_closure_unsettled_at == self.attempt:
            result = result.model_copy(
                update={"popup_closure": PopupClosure.OWNED_LEFT_OPEN}
            )
        return result

    def enable(self, **kwargs: object) -> EnableMultiplexedResult:
        self.calls.append("enable")
        self.seen_bound.append(kwargs.get("bound_target"))
        record = kwargs.get("trial_record")
        if record is not None:
            claim_trial_record(Path(str(record)), {"command": "fake-enable"})
        result = enable_result()
        return result.model_copy(update={"bound_target": kwargs.get("bound_target")})

    def record_block(self, **kwargs: object) -> MultiplexedRecordingResult:
        self.calls.append("record")
        self.seen_bound.append(kwargs.get("bound_target"))
        name = str(kwargs["name"])
        directory = Path(str(kwargs["directory"]))
        shared = kwargs["declaration"]
        assert isinstance(shared, MultiplexedRecordingDeclaration)
        stored = directory / f"{name}.ADD"
        shutil.copyfile(FIXTURE, stored)
        for ahead in self.write_ahead:
            shutil.copyfile(FIXTURE, directory / ahead)
        report = mpx_artifact.verify_mpx_artifact(stored, shared.completed_block())
        if self.record_digest is not None:
            report = report.model_copy(update={"file_sha256": self.record_digest})
        if self.record_verdict is not MpxVerdict.CONSISTENT:
            report = report.model_copy(update={"verdict": self.record_verdict})
        return MultiplexedRecordingResult(
            stage=MpxStage.STORED,
            declaration=shared,
            name=name,
            directory=directory,
            bound_target=self.record_bound,
            record_presses=1,
            record_started=True,
            stored_path=self.record_stored_path or stored,
            artifact_verification=report,
            store_invoked=True,
        )

    def verify(
        self, path: Path, completed: CompletedBlockDeclaration
    ) -> MpxArtifactReport:
        self.gate_verify_calls += 1
        if self.gate_interrupt_at == self.gate_verify_calls:
            raise KeyboardInterrupt("operator cancelled between runs")
        report = mpx_artifact.verify_mpx_artifact(path, completed)
        if self.gate_bad_digest_at == self.gate_verify_calls:
            report = report.model_copy(update={"file_sha256": "0" * 64})
        return report

    # -- the composed call --------------------------------------------------------------
    def items(self, *records: str) -> tuple[MpxBatchItem, ...]:
        return tuple(
            MpxBatchItem(name=f"item-{index:02d}", record=self.root / record)
            for index, record in enumerate(records, start=1)
        )

    def run(self, *records: str, **overrides: object) -> mpx_batch.MpxBatchResult:
        kwargs: dict[str, object] = {
            "items": self.items(*records),
            "declaration": declaration(),
            "store_dir": self.store,
            "capture_root": self.captures,
            "completion_timeout_s": 30.0,
            "actuator": self.actuator,
            "enumerate_windows": lambda: (4242,),
            "verify_artifact": self.verify,
            "seams": {
                "inspect": self.inspect,
                "set_rollover": self.set_rollover,
                "enable": self.enable,
                "record_block": self.record_block,
                "open_popup": lambda **_: ChannelsOpen(
                    outcome=PopupOutcome.OPEN,
                    surface=ChannelsSurface.SETTINGS_POPUP.value,
                    readable=True,
                    point=(10, 20),
                    reads=1,
                ),
                "read_popup": self.read_popup,
                "close_popup": self.close_popup,
            },
        }
        kwargs.update(overrides)
        return run_mpx_batch(**kwargs)


def all_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }


# ---------------------------------------------------------------------------------------------
# a complete batch: one binding, a gate on the boundary, no extra files
# ---------------------------------------------------------------------------------------------


def test_a_finite_batch_runs_each_item_on_one_binding_and_gates_the_boundary(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.COMPLETE
    assert result.complete
    assert [entry.name for entry in result.runs] == ["item-01", "item-02"]
    assert [entry.stage for entry in result.runs] == [mpx_run.MpxRunStage.COMPLETE] * 2
    assert [entry.artifact_source for entry in result.runs] == ["gate", "gate"]
    assert h.gate_verify_calls == 2

    # One binding for the whole batch; each run verifies the handled record, none binds.
    assert [call[0] for call in h.actuator.calls] == [
        "bind_target",
        "verify_bound_target",
        "verify_bound_target",
        "verify_bound_target",
    ]
    assert h.actuator.calls[0] == ("bind_target", 4242)

    # Every child was handed the same record with its full identity, not just the hwnd.
    assert len(h.seen_bound) == 6
    assert all(item == result.bound_target for item in h.seen_bound)
    assert all(item == target() for item in h.seen_bound)

    # The boundary check is the real verifier on the real stored bytes, and it carries the
    # digest that run's own report stated.
    first = result.runs[0]
    assert first.stored_path is not None
    real = mpx_artifact.verify_mpx_artifact(
        first.stored_path, declaration().completed_block()
    )
    assert first.artifact_verdict == "consistent"
    assert first.artifact_sha256 == real.file_sha256
    assert first.post_save_mode == "VISUAL_DISABLED"
    assert first.rolling_after == "OFF_PROVEN"
    assert first.post_saved_closed and first.baseline_restored
    assert first.owed == ()

    # Two records, two capture roots, two store files — and no ledger, journal or batch report
    # file invented beside them.
    assert all(
        (tmp_path / record).is_file() for record in ("first.json", "second.json")
    )
    assert sorted(p.name for p in h.captures.iterdir()) == [
        "mpx-run-001",
        "mpx-run-002",
    ]
    assert all_files(tmp_path) == {
        "first.json",
        "second.json",
        "store/item-01.ADD",
        "store/item-02.ADD",
        "captures/mpx-run-001/records/rollover-trial.json",
        "captures/mpx-run-001/records/enable-trial.json",
        "captures/mpx-run-002/records/rollover-trial.json",
        "captures/mpx-run-002/records/enable-trial.json",
    }


def test_the_batch_summary_carries_references_and_key_facts_not_nested_reports(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    result = h.run("first.json", "second.json")
    dumped = json.dumps(result.model_dump(mode="json"), default=str)

    assert set(mpx_batch.MpxBatchRun.model_fields) == {
        "name",
        "record",
        "capture_root",
        "stage",
        "parent_record_phase",
        "stored_path",
        "artifact_verdict",
        "artifact_sha256",
        "artifact_source",
        "post_save_mode",
        "post_surface",
        "rolling_after",
        "post_saved_closed",
        "baseline_restored",
        "owed",
        "reason",
    }
    assert "inspection" not in dumped and "artifact_verification" not in dumped
    assert "one binding hwnd 4242" in result.summary()
    # Each run's line names its own record and stored artifact rather than repeating a report.
    assert "first.json" in result.runs[0].summary()
    assert "item-01.ADD" in result.runs[0].summary()
    assert "second.json" in result.runs[1].summary()


# ---------------------------------------------------------------------------------------------
# preflight: every name and path before the first bind, claim or open
# ---------------------------------------------------------------------------------------------


def test_preflight_refuses_two_names_that_are_one_on_windows_before_any_bind(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    items = (
        MpxBatchItem(name="Block", record=tmp_path / "a.json"),
        MpxBatchItem(name="block", record=tmp_path / "b.json"),
    )
    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=items,
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    message = str(caught.value)
    assert "case-insensitive volume" in message
    assert "refused before any window was bound" in message
    assert h.calls == []
    assert h.actuator.calls == []
    assert list(h.captures.iterdir()) == []
    assert not (tmp_path / "a.json").exists()


def test_preflight_refuses_one_parent_record_for_two_items_before_any_bind(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    items = (
        MpxBatchItem(name="one", record=tmp_path / "shared.json"),
        MpxBatchItem(name="two", record=tmp_path / "SHARED.json"),
    )
    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=items,
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    assert "one path" in str(caught.value)
    assert h.actuator.calls == []
    assert list(h.captures.iterdir()) == []


def test_preflight_refuses_an_existing_store_entry_and_an_existing_record(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    (h.store / "Taken.BDD").write_bytes(b"someone else's block")
    (tmp_path / "claimed.json").write_text("{}", encoding="utf-8")
    items = (
        MpxBatchItem(name="taken", record=tmp_path / "fresh.json"),
        MpxBatchItem(name="other", record=tmp_path / "claimed.json"),
    )
    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=items,
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    message = str(caught.value)
    assert "already taken" in message
    assert "a record already exists" in message
    assert "claimed.json" in message
    assert h.actuator.calls == []


def test_preflight_counts_the_capture_owners_own_root_names_not_a_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = BatchHarness(tmp_path)
    (h.captures / "mpx-run-001").mkdir()
    # Neither of these is a name the owner's loop will try, so neither occupies a slot.
    (h.captures / "mpx-run-777").mkdir()
    (h.captures / "mpx-run-9").mkdir()
    (h.captures / "mpx-run-abc").mkdir()
    monkeypatch.setattr(mpx_run, "CAPTURE_RUN_LIMIT", 2)
    monkeypatch.setattr(mpx_batch, "CAPTURE_RUN_LIMIT", 2)

    assert mpx_run.capture_run_slots(h.captures) == 1

    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=h.items("a.json", "b.json"),
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    message = str(caught.value)
    assert "1 of the capture owner's 2" in message
    assert "mpx-run-NNN" in message
    assert h.actuator.calls == []


def test_bounds_and_the_off_baseline_are_refused_before_any_bind(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    for overrides, phrase in (
        ({"completion_timeout_s": float("inf")}, "finite positive"),
        ({"settle_s": -1.0}, "finite and >= 0"),
        ({"boundary_seconds": float("nan")}, "finite positive"),
        ({"baseline": "on"}, "only the literal 'off'"),
        ({"baseline": "maybe"}, "literal 'on' or 'off'"),
        ({"restore_baseline": "no"}, "must be a bool"),
    ):
        with pytest.raises(AcquisitionError) as caught:
            h.run("a.json", "b.json", **overrides)
        assert phrase in str(caught.value), overrides
    assert h.actuator.calls == []
    assert list(h.captures.iterdir()) == []


# ---------------------------------------------------------------------------------------------
# the gate before each next item: no stage-only success, no second run
# ---------------------------------------------------------------------------------------------


def test_no_second_item_after_a_run_that_did_not_complete(tmp_path: Path) -> None:
    h = BatchHarness(tmp_path)
    h.post_save = inspection(rolling="ON_PROVEN", mode="VISUAL_DISABLED")
    result = h.run("first.json", "second.json", restore_baseline=False)

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "run_failed"
    assert result.stopped_item is not None and result.stopped_item.name == "item-01"
    assert len(result.runs) == 1
    assert result.runs[0].stage is mpx_run.MpxRunStage.RESTORATION_OWED
    assert result.runs[0].baseline_restored is False
    assert result.owed
    assert not (tmp_path / "second.json").exists()
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001"]


def test_no_second_item_when_the_record_child_reports_another_binding(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.record_bound = target(7777)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "gate"
    assert result.stopped_item is not None and result.stopped_item.name == "item-02"
    assert any("full identity" in clause for clause in result.owed)
    assert result.runs[0].stage is mpx_run.MpxRunStage.COMPLETE
    assert not (tmp_path / "second.json").exists()
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001"]


def test_no_second_item_when_the_stored_digest_is_not_the_one_verified(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.record_digest = "0" * 64
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "gate"
    assert any("digest" in clause for clause in result.owed)
    assert not (tmp_path / "second.json").exists()
    assert h.gate_verify_calls == 1


def test_no_second_item_when_the_stored_file_is_gone(tmp_path: Path) -> None:
    h = BatchHarness(tmp_path)
    h.record_stored_path = tmp_path / "store" / "missing.ADD"
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert any("not a file on disk now" in clause for clause in result.owed)
    assert h.gate_verify_calls == 0
    assert not (tmp_path / "second.json").exists()


def test_an_inconsistent_artifact_stops_the_batch_without_a_second_item(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.record_verdict = MpxVerdict.CONTRADICTED
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "run_failed"
    assert result.runs[0].stage is mpx_run.MpxRunStage.ARTIFACT_INCONSISTENT
    assert result.runs[0].stored_path is not None
    assert result.runs[0].stored_path.is_file()  # preserved, never re-recorded
    assert not (tmp_path / "second.json").exists()


def test_a_failed_final_rewrite_is_not_a_success_and_stops_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = BatchHarness(tmp_path)
    monkeypatch.setattr(
        mpx_run, "update_trial_record", lambda *args, **kwargs: "record is read-only"
    )
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.runs[0].stage is mpx_run.MpxRunStage.RECORD_UNWRITTEN
    assert result.runs[0].parent_record_phase == "unwritten"
    assert not (tmp_path / "second.json").exists()
    # The pending record stays on disk as the obligation it is.
    assert (tmp_path / "first.json").is_file()


# ---------------------------------------------------------------------------------------------
# interruption: reported with the completed facts, never retried, never a fake result
# ---------------------------------------------------------------------------------------------


def test_a_cancelled_second_run_keeps_the_first_facts_and_names_the_pending_record(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.rollover_interrupt_at = 2
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.INTERRUPTED
    assert result.stopped_kind == "interrupted_inside_run"
    assert len(result.runs) == 1
    assert result.runs[0].name == "item-01"
    assert result.runs[0].stage is mpx_run.MpxRunStage.COMPLETE
    assert result.runs[0].artifact_source == "gate"
    assert result.pending_record == tmp_path / "second.json"
    assert result.stopped_item is not None and result.stopped_item.name == "item-02"
    # No fabricated result for the cancelled item, and no second capture root claimed by it.
    assert [entry.name for entry in result.runs] == ["item-01"]
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001", "mpx-run-002"]
    assert "UNKNOWN" in result.reason and "no second Record" in result.reason


def test_a_cancelled_gate_reports_the_next_item_not_started_and_unclaimed(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.gate_interrupt_at = 1
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.INTERRUPTED
    assert result.stopped_kind == "interrupted_between_runs"
    assert result.pending_record is None
    assert result.stopped_item is not None and result.stopped_item.name == "item-02"
    assert len(result.runs) == 1
    assert result.runs[0].stage is mpx_run.MpxRunStage.COMPLETE
    assert not (tmp_path / "second.json").exists()
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001"]


# ---------------------------------------------------------------------------------------------
# the --also grammar, and the unchanged standalone branch
# ---------------------------------------------------------------------------------------------


def test_parse_also_keeps_literal_paths_and_refuses_repair() -> None:
    parsed = parse_also(["second=records/second=01.json", "third=C:/tmp/third.json"])
    assert [item.name for item in parsed] == ["second", "third"]
    assert parsed[0].record == Path("records/second=01.json")
    assert parsed[1].record == Path("C:/tmp/third.json")

    for broken in ("no-separator", "=record.json", "name="):
        with pytest.raises(ValueError):
            parse_also([broken])


def test_the_cli_refuses_a_malformed_also_token_before_any_binding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    captures = tmp_path / "captures"
    captures.mkdir()
    with pytest.raises(SystemExit) as caught:
        acquire_main(
            [
                "mpx-run",
                "first",
                "--channel",
                "6",
                "7",
                "8",
                "9",
                "--profiles",
                str(PROFILES),
                "--stated-by",
                "operator",
                "--completion-timeout",
                "30",
                "--capture-root",
                str(captures),
                "--record",
                str(tmp_path / "first.json"),
                "--store-dir",
                str(store),
                "--also",
                "no-separator",
            ]
        )

    assert caught.value.code == 2
    assert "NAME=RECORD" in capsys.readouterr().err
    assert list(captures.iterdir()) == []
    assert not (tmp_path / "first.json").exists()


def test_the_cli_refuses_two_items_sharing_one_record_before_any_binding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    captures = tmp_path / "captures"
    captures.mkdir()
    with pytest.raises(SystemExit) as caught:
        acquire_main(
            [
                "mpx-run",
                "first",
                "--channel",
                "6",
                "7",
                "8",
                "9",
                "--profiles",
                str(PROFILES),
                "--stated-by",
                "operator",
                "--completion-timeout",
                "30",
                "--capture-root",
                str(captures),
                "--record",
                str(tmp_path / "shared.json"),
                "--store-dir",
                str(store),
                "--also",
                f"second={tmp_path / 'SHARED.json'}",
            ]
        )

    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "one path" in err
    assert "refused before any window was bound" in err
    assert list(captures.iterdir()) == []


def test_an_item_whose_own_setup_refuses_after_the_first_completed_keeps_its_facts(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    # The first run's store leaves an entry that the second item's own preflight will refuse:
    # the collision did not exist when the batch preflighted, so it is the run's own refusal.
    h.write_ahead = {"item-02.BDD"}
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "run_refused"
    assert result.stopped_item is not None and result.stopped_item.name == "item-02"
    assert len(result.runs) == 1
    assert result.runs[0].name == "item-01"
    assert result.runs[0].stage is mpx_run.MpxRunStage.COMPLETE
    assert result.runs[0].artifact_source == "gate"
    assert "earlier item(s) above stand as reported" in result.reason
    assert "nothing ran" not in result.reason.lower()
    assert not (tmp_path / "second.json").exists()
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001"]


def test_no_second_item_when_a_child_states_no_settled_popup_closure(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.rollover_closure_unsettled_at = 1
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "run_failed"
    assert result.runs[0].stage is mpx_run.MpxRunStage.ROLLOVER_FAILED
    assert not (tmp_path / "second.json").exists()
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001"]


# ---------------------------------------------------------------------------------------------
# the final item is gated too: a fresh digest after the last run, or no COMPLETE
# ---------------------------------------------------------------------------------------------


def test_the_final_item_is_gated_with_its_own_fresh_digest(tmp_path: Path) -> None:
    h = BatchHarness(tmp_path)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.COMPLETE
    assert h.gate_verify_calls == 2
    final = result.runs[-1]
    assert final.artifact_source == "gate"
    assert final.stored_path is not None
    fresh = mpx_artifact.verify_mpx_artifact(
        final.stored_path, declaration().completed_block()
    )
    assert final.artifact_sha256 == fresh.file_sha256

    # The final item's durable record is a real owner-contract record, not just memory.
    durable = mpx_run.read_parent_record(tmp_path / "second.json")
    assert durable.phase == "after"
    assert durable.stage is mpx_run.MpxRunStage.COMPLETE
    assert durable.bound_target == target()
    assert durable.stored_path == str(final.stored_path)


def test_the_last_items_gate_stops_the_batch_when_its_fresh_digest_disagrees(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.gate_bad_digest_at = 2
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "gate"
    assert result.stopped_item is not None and result.stopped_item.name == "item-02"
    assert any("digest" in clause for clause in result.owed)
    assert len(result.runs) == 2
    assert result.runs[0].artifact_source == "gate"
    assert result.runs[-1].artifact_source == "run_report"
    assert "not COMPLETE" in result.reason


def _rewrite_final(monkeypatch: pytest.MonkeyPatch, transform) -> None:
    """Mutate the owner's durable final payload between its write and the batch's readback."""
    original = mpx_run.update_trial_record

    def writer(path, payload):
        if payload.get("phase") == "after":
            payload = transform(dict(payload))
        return original(path, payload)

    monkeypatch.setattr(mpx_run, "update_trial_record", writer)


def _wrong_name(payload):
    payload["name"] = "someone-else"
    return payload


def _wrong_declaration(payload):
    payload["declaration"]["profiles_per_channel"] = PROFILES + 1
    return payload


def _wrong_target(payload):
    payload["bound_target"]["hwnd"] = 7777
    return payload


def _wrong_stored_path(payload):
    payload["stored_path"] = str(Path(payload["stored_path"]).with_name("other.ADD"))
    return payload


def _not_consistent(payload):
    payload["artifact_consistent"] = False
    return payload


def _not_restored(payload):
    payload["baseline_restored"] = False
    return payload


@pytest.mark.parametrize(
    ("transform", "phrase"),
    [
        (_wrong_name, "durable record names"),
        (_wrong_declaration, "declaration is not the batch's"),
        (_wrong_target, "full identity"),
        (_wrong_stored_path, "stored path"),
        (_not_consistent, "artifact is not consistent"),
        (_not_restored, "baseline is not restored"),
    ],
)
def test_the_gate_reads_the_durable_record_not_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transform, phrase: str
) -> None:
    h = BatchHarness(tmp_path)
    _rewrite_final(monkeypatch, transform)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "gate"
    assert any(phrase in clause for clause in result.owed), result.owed
    assert not (tmp_path / "second.json").exists()
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001"]


def test_a_pending_durable_record_is_refused_before_the_next_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = BatchHarness(tmp_path)

    def _pending(payload):
        payload["phase"] = "pending"
        return payload

    _rewrite_final(monkeypatch, _pending)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert any("still pending" in clause for clause in result.owed)
    assert not (tmp_path / "second.json").exists()


def test_a_malformed_durable_record_is_refused_before_the_next_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = BatchHarness(tmp_path)
    original = mpx_run.update_trial_record

    def writer(path, payload):
        written = original(path, payload)
        if payload.get("phase") == "after":
            Path(path).write_text("{not json", encoding="utf-8")
        return written

    monkeypatch.setattr(mpx_run, "update_trial_record", writer)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert any("not readable JSON" in clause for clause in result.owed)
    assert not (tmp_path / "second.json").exists()


def test_a_missing_durable_record_is_refused_before_the_next_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = BatchHarness(tmp_path)
    original = mpx_run.update_trial_record

    def writer(path, payload):
        written = original(path, payload)
        if payload.get("phase") == "after":
            Path(path).unlink()
        return written

    monkeypatch.setattr(mpx_run, "update_trial_record", writer)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert any("is missing" in clause for clause in result.owed)


def test_an_unreadable_durable_record_is_refused_before_the_next_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = BatchHarness(tmp_path)
    original = Path.read_text

    def guarded(self, *args, **kwargs):
        if self.name == "first.json":
            raise PermissionError("access is denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert any("could not be read" in clause for clause in result.owed)


# ---------------------------------------------------------------------------------------------
# record paths are identities: aliases, Windows noncanonical components, capture/store claims
# ---------------------------------------------------------------------------------------------


def test_preflight_refuses_a_record_under_the_capture_root_before_any_bind(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    items = (
        MpxBatchItem(name="one", record=h.captures / "one.json"),
        MpxBatchItem(name="two", record=tmp_path / "two.json"),
    )
    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=items,
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    assert "lies under the capture root" in str(caught.value)
    assert h.actuator.calls == []
    assert list(h.captures.iterdir()) == []


def test_preflight_refuses_a_record_in_the_store_whose_stem_is_a_store_name(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    items = (
        MpxBatchItem(name="block", record=h.store / "block.json"),
        MpxBatchItem(name="other", record=tmp_path / "other.json"),
    )
    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=items,
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    message = str(caught.value)
    assert "sits in the artifact store" in message
    assert "exact stem" in message
    assert h.actuator.calls == []


def test_preflight_refuses_a_record_with_an_alias_component_before_any_bind(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    (tmp_path / "sub").mkdir()
    items = (
        MpxBatchItem(name="one", record=tmp_path / "sub" / ".." / "shared.json"),
        MpxBatchItem(name="two", record=tmp_path / "shared.json"),
    )
    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=items,
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    assert "one path" in str(caught.value)
    assert "ending in a dot" not in str(caught.value)
    assert h.actuator.calls == []


@pytest.mark.parametrize(
    ("record", "phrase"),
    [
        ("first.json.", "ending in a dot or space"),
        ("first.json ", "ending in a dot or space"),
        ("CON.json", "reserved Windows device"),
        ("bad:name.json", "character Windows refuses"),
    ],
)
def test_preflight_refuses_a_noncanonical_record_component_with_the_exact_input(
    tmp_path: Path, record: str, phrase: str
) -> None:
    h = BatchHarness(tmp_path)
    items = (
        MpxBatchItem(name="one", record=tmp_path / record),
        MpxBatchItem(name="two", record=tmp_path / "two.json"),
    )
    with pytest.raises(AcquisitionError) as caught:
        run_mpx_batch(
            items=items,
            declaration=declaration(),
            store_dir=h.store,
            capture_root=h.captures,
            completion_timeout_s=30.0,
            actuator=h.actuator,
            enumerate_windows=lambda: (4242,),
        )

    message = str(caught.value)
    assert phrase in message
    assert repr(str(tmp_path / record)) in message
    assert h.actuator.calls == []


def test_an_unreadable_capture_root_is_unknown_not_empty_and_is_refused_before_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = BatchHarness(tmp_path)

    def unreadable(base: Path) -> int:
        raise AcquisitionError(
            f"the capture root {base} could not be read: permission denied"
        )

    monkeypatch.setattr(mpx_batch, "capture_run_slots", unreadable)
    with pytest.raises(AcquisitionError) as caught:
        h.run("first.json", "second.json")

    assert "could not be read" in str(caught.value)
    assert h.actuator.calls == []
    assert list(h.captures.iterdir()) == []


# ---------------------------------------------------------------------------------------------
# child identity, and cancellation versus process exit
# ---------------------------------------------------------------------------------------------


def test_no_second_item_when_the_rollover_child_reports_another_binding(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.rollover_bound = target(9999)
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.STOPPED
    assert result.stopped_kind == "gate"
    assert any("rollover child is bound" in clause for clause in result.owed)
    assert not (tmp_path / "second.json").exists()


def test_a_final_record_with_no_dismissal_point_is_not_malformed(
    tmp_path: Path,
) -> None:
    h = BatchHarness(tmp_path)
    h.close_popup = lambda **_: ChannelsDismissal(
        outcome=DismissalOutcome.ABSENT,
        point=None,
        surface_before="multiplexer_on_entry",
        surface_after="absent",
        reads=2,
        steps=4,
    )
    result = h.run("first.json", "second.json")

    assert result.stage is MpxBatchStage.COMPLETE
    durable = mpx_run.read_parent_record(tmp_path / "first.json")
    assert durable.popup_close is not None
    assert durable.popup_close.point == ()


def test_a_process_exit_is_not_treated_as_a_cancelled_batch(tmp_path: Path) -> None:
    h = BatchHarness(tmp_path)
    h.system_exit_at_attempt = 1
    with pytest.raises(SystemExit):
        h.run("first.json", "second.json")

    # The pending obligation was claimed before the press, so it stays on disk as pending; it
    # is not rewritten as an outcome and no second item started.
    with pytest.raises(AcquisitionError, match="still pending"):
        mpx_run.read_parent_record(tmp_path / "first.json")
    assert not (tmp_path / "second.json").exists()
    assert [p.name for p in h.captures.iterdir()] == ["mpx-run-001"]
