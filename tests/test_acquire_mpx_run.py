"""Tests for the bounded one-shot MPX composition (``acquire mpx-run``).

The instrument is replaced by the children themselves: each test scripts the four owners'
reports and asserts the **sequence and the ownership rules** the composition exists to enforce —
one binding handed to every child, a pending parent record before the first rolling child, no
second Record, no Stop/Clear/Disable, and a final rewrite failure that is not a success.

What these tests do **not** establish: any real-provider behaviour. They are offline only.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from udv_echo_process.acquire import mpx_run
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.binding import resolve_bound_target
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
from udv_echo_process.acquire.mpx_run import MpxRunStage, run_mpx_once
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
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    ChannelsOpen,
    DismissalOutcome,
    PopupOutcome,
)
from udv_echo_process.acquire.ui.channels import ChannelsRead, ChannelsSurface
from udv_echo_process.cli import acquire_main

# ---------------------------------------------------------------------------------------------
# fixtures the composition can be handed like the real owners
# ---------------------------------------------------------------------------------------------


def target(hwnd: int = 4242) -> WindowTarget:
    return WindowTarget(hwnd=hwnd, thread_id=11, process_id=22, class_name="TMain_Scr")


def capture(
    rolling: str,
    mode: str,
    *,
    directory: str | None = None,
    hwnd: int = 4242,
    popup_hwnd: int | None = 9001,
    context: str = "live-bracketed",
    freshness: str = "live_bracketed",
    integrity: str = "capture-digest-verified",
    agreed: bool = True,
    recognition: str = "EXACT_TEMPLATE_MATCH",
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
            acquisition_context=context,
            freshness=freshness,
            integrity=integrity,
            frames_agreed=agreed,
            recognition=recognition,
            frame_digests=("a" * 64, "b" * 64),
            enable_precondition=True,
        ),
    )


def inspection(
    rolling: str = "OFF_PROVEN",
    mode: str = "VISUAL_DISABLED",
    *,
    outcome: InspectionOutcome = InspectionOutcome.CLOSED,
    popup_left_open: bool | None = False,
    refused_stage: str | None = None,
    directory: str | None = None,
    **capture_overrides: object,
) -> ChannelInspection:
    return ChannelInspection(
        outcome=outcome,
        mode="ready",
        mode_source="strip_state",
        refused=None if outcome is InspectionOutcome.CLOSED else "refused",
        refused_stage=refused_stage,
        read=ChannelsRead(
            surface=ChannelsSurface.SETTINGS_POPUP,
            readable=True,
            capture=capture(rolling, mode, directory=directory, **capture_overrides),
        ),
        popup_left_open=popup_left_open,
    )


def rollover_result(
    *,
    post_rolling: str = "ON_PROVEN",
    settled: bool = True,
    popup_closure: PopupClosure | None = None,
) -> SetRolloverResult:
    """A child report; ``popup_closure=None`` states *no* closure, which is not "settled"."""
    closure = (
        popup_closure
        if popup_closure is not None
        else (PopupClosure.OWNED_CLOSED if settled else PopupClosure.OWNED_LEFT_OPEN)
    )
    return SetRolloverResult(
        stage=SetRolloverStage.PRESSED,
        requested=Rolling.ON,
        expect=Rolling.OFF,
        baseline=Rolling.OFF,
        bound_target=target(),
        post_rolling=post_rolling,
        popup_closure=closure,
        presses=1,
        press="attempted",
    )


def enable_result(
    *, surface: str = "multiplexer_on_entry", mode: str = "VISUAL_ENABLED"
) -> EnableMultiplexedResult:
    return EnableMultiplexedResult(
        stage=EnableStage.PRESSED,
        bound_target=target(),
        post_surface=surface,
        post_mode=mode,
        presses=1,
        press="attempted",
        restoration_owed=(
            (
                "read the mode back from a freshly reopened Channels popup: this command "
                "cannot infer that the application is enabled"
            ),
        ),
    )


def artifact_report(verdict: MpxVerdict = MpxVerdict.CONSISTENT) -> MpxArtifactReport:
    return MpxArtifactReport(
        file_name="run.ADD",
        file_sha256="0" * 64,
        byte_size=1234,
        identity_verified=True,
        identity_note="fixture",
        acquisition_mode="mpx",
        mode_note="fixture",
        declared_channels=(1, 2),
        declared_profiles_per_channel=10,
        expected_total_profiles=10,
        decoded_channels=(1, 2),
        verdict=verdict,
    )


def record_result(
    declaration: MultiplexedRecordingDeclaration,
    directory: Path,
    *,
    stage: MpxStage = MpxStage.STORED,
    verdict: MpxVerdict = MpxVerdict.CONSISTENT,
    reason: str = "",
) -> MultiplexedRecordingResult:
    stored = directory / "run.ADD"
    return MultiplexedRecordingResult(
        stage=stage,
        declaration=declaration,
        name="run",
        directory=directory,
        bound_target=target(),
        record_presses=1 if stage is not MpxStage.RECORD_REFUSED else 0,
        record_started=stage is MpxStage.STORED,
        stored_path=stored if stage is MpxStage.STORED else None,
        artifact_verification=(
            artifact_report(verdict) if stage is MpxStage.STORED else None
        ),
        store_invoked=stage is MpxStage.STORED,
        reason=reason,
        owed=("the multiplexer's mode was not read",) if reason else (),
    )


class FakeActuator:
    """A doubling actuator that records bind/verify and nothing else."""

    def __init__(self, hwnd: int = 4242, bound_hwnd: int | None = None) -> None:
        self.hwnd = hwnd
        self.bound_hwnd = bound_hwnd if bound_hwnd is not None else hwnd
        self.calls: list[tuple[str, object]] = []
        self.warnings: tuple[str, ...] = ()

    def bind_target(self, hwnd: int) -> WindowTarget:
        self.calls.append(("bind_target", hwnd))
        return target(self.bound_hwnd)

    def verify_bound_target(self, expected: WindowTarget) -> WindowTarget:
        self.calls.append(("verify_bound_target", expected.hwnd))
        return expected

    def read(self, *args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            surface=ChannelsSurface.ABSENT, readable=False, capture=None
        )

    def open_channels_popup(self, **kwargs: object) -> ChannelsOpen:
        return ChannelsOpen(
            outcome=PopupOutcome.OPEN,
            surface=ChannelsSurface.SETTINGS_POPUP.value,
            readable=True,
            point=(10, 20),
            reads=1,
        )

    def dismiss_channels_popup(self, **kwargs: object) -> ChannelsDismissal:
        return ChannelsDismissal(
            outcome=DismissalOutcome.ABSENT,
            point=(500, 500),
            surface_before="multiplexer_on_entry",
            surface_after="absent",
            reads=2,
            steps=4,
        )


class Harness:
    """Scripted owners, one call log, and the parent-record path the test can read."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = root / "store"
        self.store.mkdir()
        self.captures = root / "captures"
        self.captures.mkdir()
        self.record = root / "parent.json"
        self.calls: list[str] = []
        self.actuator = FakeActuator()
        self.baseline = inspection()
        self.post_save = inspection()
        self.rollovers: list[SetRolloverResult] = [
            rollover_result(),
            rollover_result(post_rolling="OFF_PROVEN"),
        ]
        self.rollover_error: BaseException | None = None
        self.enable_result = enable_result()
        self.enable_error: BaseException | None = None
        self.record_stage = MpxStage.STORED
        self.record_verdict = MpxVerdict.CONSISTENT
        self.record_error: BaseException | None = None
        self.record_calls = 0
        self.record_kwargs: dict[str, object] = {}
        self.seen_bound: list[object] = []
        self.pending_at_rollover: dict | None = None
        #: The ordered surfaces the composed reads see: pre-open, pre-dismiss, post-dismiss.
        self.reads = ["absent", "multiplexer_on_entry", "absent"]
        self.close_outcome = DismissalOutcome.ABSENT
        self.close_error: BaseException | None = None
        self.close_calls = 0
        #: Overrides for the parent's own clipped-entry pair (retained/torn/wrong-hwnd cases).
        self.clipped_capture: dict[str, object] = {}
        self.inspect_error: BaseException | None = None
        self.child_record_paths: dict[str, Path] = {}
        self.current_record = self.record
        self.declaration = MultiplexedRecordingDeclaration(
            multiplexer_enabled=True,
            channels=(1, 2),
            profiles_per_channel=10,
            stated_by="operator",
        )

    # -- the four injected owners ----------------------------------------------------------
    def inspect(self, **kwargs: object) -> ChannelInspection:
        label = (
            "inspect:post" if "inspect:baseline" in self.calls else "inspect:baseline"
        )
        self.calls.append(label)
        if label == "inspect:post" and self.inspect_error is not None:
            raise self.inspect_error
        base = self.baseline if label == "inspect:baseline" else self.post_save
        directory = kwargs.get("capture_dir")
        if directory is None or base.read is None or base.read.capture is None:
            return base
        listed = str(Path(str(directory)) / "capture-001")
        read = base.read.model_copy(
            update={
                "capture": base.read.capture.model_copy(update={"directory": listed})
            }
        )
        return base.model_copy(update={"read": read})

    def read_popup(self, *args: object, **kwargs: object) -> SimpleNamespace:
        surface = self.reads.pop(0) if self.reads else "absent"
        read = SimpleNamespace(
            surface=ChannelsSurface(surface), readable=surface != "absent"
        )
        directory = kwargs.get("capture_dir")
        if directory is not None:
            # The parent's own clipped pair: a fresh live-bracketed pair on the original
            # binding, in the directory the parent named for it.
            read.capture = capture(
                "ON_PROVEN",
                "VISUAL_ENABLED",
                directory=str(Path(str(directory)) / "capture-001"),
                surface="MULTIPLEXER_ON_ENTRY",
                **self.clipped_capture,
            )
        return read

    def close_popup(self, **kwargs: object) -> ChannelsDismissal:
        self.calls.append("dismiss")
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error
        after = (
            "absent"
            if self.close_outcome is DismissalOutcome.ABSENT
            else ("multiplexer_on_entry")
        )
        return ChannelsDismissal(
            outcome=self.close_outcome,
            point=(500, 500),
            surface_before="multiplexer_on_entry",
            surface_after=after,
            reads=2,
            steps=4,
        )

    def set_rollover(self, **kwargs: object) -> SetRolloverResult:
        self.seen_bound.append(kwargs.get("bound_target"))
        wanted = str(kwargs["requested"])
        # The real child claims its record exclusively; a shared path is a refusal, not a
        # silent overwrite, so the harness claims it the same way.
        record = kwargs.get("trial_record")
        if record is not None:
            claim_trial_record(Path(str(record)), {"command": "fake-rollover"})
            self.child_record_paths[f"rollover:{wanted}"] = Path(str(record))
        if wanted == "on":
            self.calls.append("rollover:on")
            self.pending_at_rollover = json.loads(
                self.current_record.read_text("utf-8")
            )
        else:
            self.calls.append("rollover:off")
        if self.rollover_error is not None:
            raise self.rollover_error
        if self.rollovers:
            return self.rollovers.pop(0)
        return rollover_result(
            post_rolling="ON_PROVEN" if wanted == "on" else "OFF_PROVEN"
        )

    def enable(self, **kwargs: object) -> EnableMultiplexedResult:
        self.calls.append("enable")
        self.seen_bound.append(kwargs.get("bound_target"))
        record = kwargs.get("trial_record")
        if record is not None:
            claim_trial_record(Path(str(record)), {"command": "fake-enable"})
            self.child_record_paths["enable"] = Path(str(record))
        if self.enable_error is not None:
            raise self.enable_error
        return self.enable_result

    def record_block(self, **kwargs: object) -> MultiplexedRecordingResult:
        self.calls.append("record")
        self.record_calls += 1
        self.seen_bound.append(kwargs.get("bound_target"))
        self.record_kwargs = kwargs
        if self.record_error is not None:
            raise self.record_error
        return record_result(
            kwargs["declaration"],
            Path(kwargs["directory"]),
            stage=self.record_stage,
            verdict=self.record_verdict,
            reason="" if self.record_stage is MpxStage.STORED else "stopped",
        )

    # -- the composed call ------------------------------------------------------------------
    def run(self, **overrides: object):
        kwargs: dict[str, object] = {
            "name": "run",
            "store_dir": self.store,
            "capture_root": self.captures,
            "record": self.record,
            "declaration": self.declaration,
            "completion_timeout_s": 30.0,
            "actuator": self.actuator,
            "enumerate_windows": lambda: (4242,),
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
        }
        kwargs.update(overrides)
        self.current_record = Path(str(kwargs["record"]))
        return run_mpx_once(**kwargs)


# ---------------------------------------------------------------------------------------------
# the sequence, and the one binding
# ---------------------------------------------------------------------------------------------


def test_happy_path_runs_the_four_owners_once_in_order(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    assert result.complete
    assert h.calls == [
        "inspect:baseline",
        "rollover:on",
        "enable",
        "dismiss",
        "record",
        "inspect:post",
    ]
    assert result.stored_path == h.store / "run.ADD"
    assert result.artifact_consistent
    assert result.owed == ()


def test_one_binding_is_verified_and_never_rebound(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    assert [c[0] for c in h.actuator.calls] == ["bind_target", "verify_bound_target"]
    assert len(h.seen_bound) == 3
    assert all(item == h.actuator.bound_hwnd for item in [b.hwnd for b in h.seen_bound])
    assert all(b is result.bound_target for b in h.seen_bound)


def test_a_handed_bound_target_is_verified_and_never_bound(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    handed = target(4242)
    result = h.run(bound_target=handed)

    assert result.stage is MpxRunStage.COMPLETE
    assert [c[0] for c in h.actuator.calls] == ["verify_bound_target"]
    assert result.bound_target == handed
    assert all(item == handed for item in h.seen_bound)


def test_a_handed_bound_target_that_is_not_the_enumerated_window_is_refused(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    with pytest.raises(AcquisitionError) as caught:
        h.run(bound_target=target(7777))

    assert "target changed" in str(caught.value)
    assert h.actuator.calls == []
    assert h.calls == []


def test_children_still_bind_when_no_record_is_handed_over() -> None:
    fake = FakeActuator()
    bound = resolve_bound_target(
        fake, (4242,), bound_target=None, class_name="TMain_Scr"
    )
    assert bound.hwnd == 4242
    assert fake.calls == [("bind_target", 4242)]


def test_a_handed_over_record_is_verified_never_rebound() -> None:
    fake = FakeActuator()
    expected = target()
    got = resolve_bound_target(
        fake, (4242,), bound_target=expected, class_name="TMain_Scr"
    )
    assert got is expected
    assert fake.calls == [("verify_bound_target", 4242)]


def test_a_changed_enumerated_target_refuses_before_verifying() -> None:
    fake = FakeActuator()
    with pytest.raises(AcquisitionError) as caught:
        resolve_bound_target(
            fake, (9999,), bound_target=target(), class_name="TMain_Scr"
        )
    assert "target changed" in str(caught.value)
    assert fake.calls == []  # nothing bound, nothing verified


def test_a_parent_binding_that_changed_is_refused_before_any_child(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.actuator = FakeActuator(hwnd=4242, bound_hwnd=7777)
    with pytest.raises(AcquisitionError):
        h.run()
    assert h.calls == []


# ---------------------------------------------------------------------------------------------
# the pending parent record
# ---------------------------------------------------------------------------------------------


def test_pending_record_is_on_disk_before_the_first_rolling_child(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    result = h.run()

    assert h.pending_at_rollover is not None
    assert h.pending_at_rollover["phase"] == "pending"
    assert "a press may follow" in h.pending_at_rollover["actions"]
    final = json.loads(h.record.read_text("utf-8"))
    assert final["phase"] == "after"
    assert final["stage"] == "complete"
    assert result.parent_record_phase == "final"


def test_an_existing_parent_record_refuses_before_any_gesture(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.record.write_text("{}", encoding="utf-8")
    with pytest.raises(AcquisitionError) as caught:
        h.run()
    assert "refusing to overwrite" in str(caught.value)
    assert h.calls == []


def test_a_failed_final_rewrite_is_not_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness(tmp_path)
    monkeypatch.setattr(
        mpx_run, "update_trial_record", lambda *a, **k: "disk is read-only"
    )
    result = h.run()

    assert result.stage is MpxRunStage.RECORD_UNWRITTEN
    assert not result.complete
    assert result.parent_record_phase == "unwritten"
    assert any("still reads pending" in clause for clause in result.owed)
    # The pending record is preserved as the obligation it states.
    assert json.loads(h.record.read_text("utf-8"))["phase"] == "pending"


# ---------------------------------------------------------------------------------------------
# refusals that must happen before anything is pressed
# ---------------------------------------------------------------------------------------------


def test_missing_capture_root_refuses_before_inspection(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    with pytest.raises(AcquisitionError) as caught:
        h.run(capture_root=tmp_path / "absent")
    assert "capture root" in str(caught.value)
    assert h.calls == []
    assert not h.record.exists()


def test_a_preexisting_popup_is_refused_and_never_adopted(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.baseline = inspection(
        outcome=InspectionOutcome.REFUSED,
        popup_left_open=True,
        refused_stage="adopt",
    )
    h.baseline = h.baseline.model_copy(
        update={"refused": "a readable Channels popup is already open"}
    )
    result = h.run()

    assert result.stage is MpxRunStage.INSPECTION_REFUSED
    assert h.calls == ["inspect:baseline"]
    assert not h.record.exists()
    assert any("operator-opened" in clause for clause in result.owed)


def test_a_baseline_mode_that_disagrees_is_refused_before_pressing(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.baseline = inspection(mode="VISUAL_ENABLED")
    result = h.run()

    assert result.stage is MpxRunStage.BASELINE_DISAGREED
    assert h.calls == ["inspect:baseline"]
    assert not h.record.exists()


def test_rolling_already_on_skips_the_rollover_press(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.baseline = inspection(rolling="ON_PROVEN")
    h.rollovers = [rollover_result(post_rolling="OFF_PROVEN")]
    h.post_save = inspection(rolling="OFF_PROVEN")
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    assert "rollover:on" not in h.calls
    assert h.calls == [
        "inspect:baseline",
        "enable",
        "dismiss",
        "record",
        "inspect:post",
    ]


def test_rollover_that_does_not_prove_on_stops_before_enable(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.rollovers = [rollover_result(post_rolling="UNKNOWN")]
    result = h.run()

    assert result.stage is MpxRunStage.ROLLOVER_FAILED
    assert h.calls == ["inspect:baseline", "rollover:on"]
    assert h.record_calls == 0


# ---------------------------------------------------------------------------------------------
# the enable stage owns the popup, and a panel is never guessed away
# ---------------------------------------------------------------------------------------------


def test_enable_leaving_a_panel_stops_without_record_or_disable(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.enable_result = enable_result(surface="settings_popup")
    result = h.run()

    assert result.stage is MpxRunStage.POPUP_LEFT_OPEN
    assert h.calls == ["inspect:baseline", "rollover:on", "enable"]
    assert h.record_calls == 0
    assert any("presses no Disable" in clause for clause in result.owed)


def test_enable_without_a_positive_mode_stops_before_record(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.enable_result = enable_result(mode="UNKNOWN")
    result = h.run()

    assert result.stage is MpxRunStage.ENABLE_FAILED
    assert h.record_calls == 0
    assert "Record zero times" in " ".join(result.owed)


def test_the_real_clipped_pair_is_dismissed_and_then_recorded(tmp_path: Path) -> None:
    """The only production-reachable enabled pair: clipped surface + VISUAL_ENABLED."""
    h = Harness(tmp_path)
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    assert result.enable.post_surface == "multiplexer_on_entry"
    assert result.enable.post_mode == "VISUAL_ENABLED"
    assert result.post_mode == "VISUAL_ENABLED"
    assert result.post_save_mode == "VISUAL_DISABLED"
    assert result.popup_close is not None
    assert result.popup_close.outcome is DismissalOutcome.ABSENT
    assert h.close_calls == 1
    assert h.record_calls == 1
    assert h.calls.index("dismiss") < h.calls.index("record")
    durable = json.loads(h.record.read_text("utf-8"))
    assert durable["popup_close"]["outcome"] == "absent"
    assert durable["post_mode"] == "VISUAL_ENABLED"
    assert durable["child_stages"]["record"] == "stored"
    assert durable["child_stages"]["enable"] == "pressed"


def test_a_dismissal_not_observed_absent_sends_no_record(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.close_outcome = DismissalOutcome.UNKNOWN
    result = h.run()

    assert result.stage is MpxRunStage.POPUP_LEFT_OPEN
    assert h.close_calls == 1
    assert h.record_calls == 0
    assert "inspect:post" not in h.calls


def test_a_dismissal_that_raises_sends_no_record(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.close_error = AcquisitionError("the dismissal geometry cannot fit")
    result = h.run()

    assert result.stage is MpxRunStage.POPUP_LEFT_OPEN
    assert h.record_calls == 0
    assert "cannot fit" in result.error


def test_an_absent_post_surface_stops_without_dismiss_or_record(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.enable_result = enable_result(surface="absent", mode="UNKNOWN")
    result = h.run()

    assert result.stage is MpxRunStage.ENABLE_FAILED
    assert h.close_calls == 0
    assert h.record_calls == 0
    assert any("never turned into 'enabled'" in clause for clause in [result.reason])


def test_a_fresh_read_that_is_not_clipped_walks_no_dismissal(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.reads = ["absent", "absent"]
    result = h.run()

    assert result.stage is MpxRunStage.POPUP_LEFT_OPEN
    assert h.close_calls == 0
    assert h.record_calls == 0


# ---------------------------------------------------------------------------------------------
# the record stage: one press, no cleanup, the artifact preserved
# ---------------------------------------------------------------------------------------------


def test_record_that_is_still_running_sends_no_stop_and_no_second_record(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.record_stage = MpxStage.STILL_RUNNING
    result = h.run()

    assert result.stage is MpxRunStage.RECORD_FAILED
    assert h.record_calls == 1
    assert "inspect:post" not in h.calls
    assert "rollover:off" not in h.calls
    assert "no Stop, Clear" in result.reason


def test_an_inconsistent_artifact_is_reported_with_the_file_preserved(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.record_verdict = MpxVerdict.CONTRADICTED
    result = h.run()

    assert result.stage is MpxRunStage.ARTIFACT_INCONSISTENT
    assert result.stored_path == h.store / "run.ADD"
    assert h.record_calls == 1
    assert "inspect:post" not in h.calls


# ---------------------------------------------------------------------------------------------
# the post-save inspection, and the baseline obligation
# ---------------------------------------------------------------------------------------------


def test_post_save_unknown_state_is_owed_and_not_a_success(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(mode="UNKNOWN", rolling="UNKNOWN")
    result = h.run()

    assert result.stage is MpxRunStage.POST_SAVE_UNKNOWN
    assert result.stored_path == h.store / "run.ADD"
    assert result.artifact_consistent
    assert "rollover:off" not in h.calls


def test_a_retained_post_save_capture_never_completes(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(
        mode="VISUAL_DISABLED",
        rolling="OFF_PROVEN",
        context="retained",
        freshness="not_established",
        integrity="decoded-pair-only",
    )
    result = h.run()

    assert result.stage is MpxRunStage.POST_SAVE_UNKNOWN
    assert not result.complete
    assert result.artifact_consistent
    assert "rollover:off" not in h.calls


def test_a_post_save_capture_on_another_handle_never_completes(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(hwnd=7777)
    result = h.run()

    assert result.stage is MpxRunStage.POST_SAVE_UNKNOWN
    assert not result.complete
    assert result.artifact_consistent


def test_post_save_rolling_unknown_is_owed_without_a_restore_press(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(mode="VISUAL_DISABLED", rolling="UNKNOWN")
    result = h.run()

    assert result.stage is MpxRunStage.POST_SAVE_UNKNOWN
    assert result.artifact_consistent
    assert "rollover:off" not in h.calls
    assert "no restore child is called" in result.reason


def test_a_post_save_inspection_that_raises_keeps_the_artifact(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.inspect_error = RuntimeError("capture backend down")
    result = h.run()

    assert result.stage is MpxRunStage.POST_SAVE_UNKNOWN
    assert result.artifact_consistent
    assert result.stored_path == h.store / "run.ADD"


def test_a_capture_root_claims_a_fresh_run_root_and_never_mixes_evidence(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    earlier = h.captures / "mpx-run-001"
    earlier.mkdir()
    marker = earlier / "frame.png"
    marker.write_bytes(b"old run")

    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    assert result.capture_root.name == "mpx-run-002"
    assert marker.read_bytes() == b"old run"


def test_post_save_enabled_owes_the_baseline_and_presses_no_disable(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(mode="VISUAL_ENABLED", rolling="ON_PROVEN")
    result = h.run()

    assert result.stage is MpxRunStage.RESTORATION_OWED
    assert h.calls == [
        "inspect:baseline",
        "rollover:on",
        "enable",
        "dismiss",
        "record",
        "inspect:post",
    ]
    assert result.artifact_consistent
    assert any("presses no Disable" in clause for clause in result.owed)


def test_the_baseline_restore_uses_the_existing_child_and_resolves_the_obligation(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(mode="VISUAL_DISABLED", rolling="ON_PROVEN")
    h.rollovers = [rollover_result(), rollover_result(post_rolling="OFF_PROVEN")]
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    assert h.calls[-1] == "rollover:off"
    assert result.baseline_restored
    assert result.owed == ()
    # The child's historical clause stays nested; the parent's fresh proof resolves it.
    assert result.enable.restoration_owed
    per_run = result.resolved_child_obligations
    assert any("resolved by this run" in clause for clause in per_run)


def test_a_restore_that_is_not_proved_stays_owed(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(mode="VISUAL_DISABLED", rolling="ON_PROVEN")
    h.rollovers = [rollover_result(), rollover_result(post_rolling="UNKNOWN")]
    result = h.run()

    assert result.stage is MpxRunStage.RESTORATION_FAILED
    assert result.stored_path == h.store / "run.ADD"
    assert any("restore rolling" in clause for clause in result.owed)


# ---------------------------------------------------------------------------------------------
# record ownership: the child records belong to the run root, never to the parent directory
# ---------------------------------------------------------------------------------------------


def test_child_records_live_inside_the_runs_own_capture_root(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    durable = json.loads(h.record.read_text("utf-8"))
    assert set(durable["child_records"]) == {"rollover", "enable", "restore"}
    for key, path in durable["child_records"].items():
        named = Path(path)
        assert named.name == f"{key}-trial.json"
        assert named.parent.parent == result.capture_root
    # The children claimed exactly the paths the parent named for them.
    assert (
        Path(durable["child_records"]["rollover"])
        == h.child_record_paths["rollover:on"]
    )
    assert Path(durable["child_records"]["enable"]) == h.child_record_paths["enable"]


def test_two_runs_sharing_one_parent_dir_never_collide_on_child_records(
    tmp_path: Path,
) -> None:
    """A second run in the same directory must not reuse the first run's child records."""
    h = Harness(tmp_path)
    first = h.run()
    assert first.stage is MpxRunStage.COMPLETE
    first_payload = json.loads(h.record.read_text("utf-8"))
    first_children = {
        key: Path(path) for key, path in first_payload["child_records"].items()
    }
    # ``restore`` is not invoked when the post-save capture already reads OFF.
    first_written = {key: path for key, path in first_children.items() if path.exists()}
    assert set(first_written) == {"rollover", "enable"}
    first_bytes = {key: path.read_bytes() for key, path in first_written.items()}

    h.rollovers = [rollover_result(), rollover_result(post_rolling="OFF_PROVEN")]
    h.reads = ["absent", "multiplexer_on_entry", "absent"]
    second = h.run(record=tmp_path / "parent-2.json")

    assert second.stage is MpxRunStage.COMPLETE
    second_payload = json.loads((tmp_path / "parent-2.json").read_text("utf-8"))
    second_children = {
        key: Path(path) for key, path in second_payload["child_records"].items()
    }
    assert second.capture_root != first.capture_root
    assert set(map(str, first_children.values())).isdisjoint(
        map(str, second_children.values())
    )
    # The first run's obligations are untouched by the second run.
    for key, path in first_written.items():
        assert path.read_bytes() == first_bytes[key]
    for key in ("rollover", "enable"):
        assert second_children[key].exists()
        assert first.capture_root not in second_children[key].parents


def test_an_existing_parent_record_refuses_before_a_run_root_is_claimed(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.record.write_text("{}\n", encoding="utf-8")

    with pytest.raises(AcquisitionError) as caught:
        h.run()

    assert "refusing to overwrite" in str(caught.value)
    assert list(h.captures.iterdir()) == []
    assert h.calls == []


def test_a_shared_child_record_path_is_a_refusal_and_never_an_overwrite(
    tmp_path: Path,
) -> None:
    """The ownership rule the parent relies on: a claimed record is never written twice."""
    shared = tmp_path / "rollover-trial.json"
    claim_trial_record(shared, {"command": "first-run"})
    before = shared.read_bytes()

    with pytest.raises(AcquisitionError) as caught:
        claim_trial_record(shared, {"command": "second-run"})

    assert "refusing to overwrite" in str(caught.value)
    assert shared.read_bytes() == before


# ---------------------------------------------------------------------------------------------
# the caller's flag is a bool, and the parent's own pairs license its own decisions
# ---------------------------------------------------------------------------------------------


def test_a_non_bool_restore_flag_is_refused_before_any_gesture(tmp_path: Path) -> None:
    """``"no"`` is truthy; Pydantic would report it as ``False`` while the run restored."""
    h = Harness(tmp_path)
    with pytest.raises(AcquisitionError) as caught:
        h.run(restore_baseline="no")
    assert "restore_baseline must be a bool" in str(caught.value)
    assert "nothing was inspected or pressed" in str(caught.value)
    assert h.calls == []
    assert not h.record.exists()
    assert list(h.captures.iterdir()) == []


@pytest.mark.parametrize(
    "capture_overrides",
    [
        {
            "context": "retained",
            "freshness": "not_established",
            "integrity": "decoded-pair-only",
        },
        {"agreed": False},
        {"hwnd": 7777},
    ],
    ids=["retained", "torn", "wrong-hwnd"],
)
def test_the_baseline_mode_never_rests_on_a_pair_this_run_does_not_own(
    tmp_path: Path, capture_overrides: dict[str, object]
) -> None:
    h = Harness(tmp_path)
    h.baseline = inspection(**capture_overrides)
    result = h.run()

    assert result.stage is MpxRunStage.INSPECTION_REFUSED
    assert h.calls == ["inspect:baseline"]
    assert not h.record.exists()
    assert "licensed pair" in result.reason


@pytest.mark.parametrize(
    "capture_overrides",
    [
        {
            "context": "retained",
            "freshness": "not_established",
            "integrity": "decoded-pair-only",
        },
        {"agreed": False},
        {"hwnd": 7777},
    ],
    ids=["retained", "torn", "wrong-hwnd"],
)
def test_the_parent_never_dismisses_the_clipped_entry_on_another_pairs_word(
    tmp_path: Path, capture_overrides: dict[str, object]
) -> None:
    """The Enable child's literals are its own; the parent's fresh pair must license the press."""
    h = Harness(tmp_path)
    h.clipped_capture = dict(capture_overrides)
    result = h.run()

    assert result.stage is MpxRunStage.POPUP_LEFT_OPEN
    assert h.close_calls == 0
    assert h.record_calls == 0
    assert "licensed pair" in result.reason


def test_a_child_that_states_no_popup_closure_prevents_enable_and_record(
    tmp_path: Path,
) -> None:
    """``None`` is *unknown*, not settled: the run must not continue on it."""
    h = Harness(tmp_path)
    h.rollovers = [
        rollover_result(post_rolling="ON_PROVEN").model_copy(
            update={"popup_closure": None}
        )
    ]
    result = h.run()

    assert result.stage is MpxRunStage.ROLLOVER_FAILED
    assert h.calls == ["inspect:baseline", "rollover:on"]
    assert h.record_calls == 0
    assert "closure None" in result.reason


def test_the_durable_record_states_each_rolling_fact_with_its_source(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    durable = json.loads(h.record.read_text("utf-8"))
    assert durable["rolling_before"] == "OFF_PROVEN"
    assert durable["rolling_before_source"] == "baseline_capture"
    assert durable["rolling_at_enable"] == "ON_PROVEN"
    assert durable["rolling_at_enable_source"] == "rollover_child_post_read"
    assert durable["rolling_after"] == "OFF_PROVEN"
    assert durable["rolling_after_source"] == "post_save_capture"
    assert durable["baseline_restored"] is True
    assert durable["baseline_restored_source"] == "post_save_capture"
    assert durable["post_mode"] == "VISUAL_ENABLED"
    assert durable["post_mode_source"] == "parent_clipped_capture"


def test_a_post_save_that_could_not_be_read_preserves_the_prior_facts(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.inspect_error = RuntimeError("capture backend down")
    result = h.run()

    assert result.stage is MpxRunStage.POST_SAVE_UNKNOWN
    durable = json.loads(h.record.read_text("utf-8"))
    # The prior observed fact is preserved with its own source, and nothing is restored.
    assert durable["rolling_after"] == "ON_PROVEN"
    assert durable["rolling_after_source"] == "rollover_child_post_read"
    assert durable["baseline_restored"] is False
    assert durable["baseline_restored_source"] == ""
    assert durable["rolling_at_enable_source"] == "rollover_child_post_read"


def test_the_restore_childs_own_read_is_the_stated_after_fact(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(mode="VISUAL_DISABLED", rolling="ON_PROVEN")
    h.rollovers = [rollover_result(), rollover_result(post_rolling="OFF_PROVEN")]
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    durable = json.loads(h.record.read_text("utf-8"))
    assert durable["rolling_after"] == "OFF_PROVEN"
    assert durable["rolling_after_source"] == "restore_child_post_read"
    assert durable["baseline_restored"] is True
    assert durable["baseline_restored_source"] == "restore_child_post_read"
    # No third inspection is taken, and the record says so rather than implying a fresh mode.
    assert durable["post_save_mode_source"] == "pre_restore_capture"
    assert "inspect:post" in h.calls and h.calls.count("inspect:post") == 1


def test_a_restore_that_is_not_proved_never_claims_the_baseline_was_restored(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.post_save = inspection(mode="VISUAL_DISABLED", rolling="ON_PROVEN")
    h.rollovers = [rollover_result(), rollover_result(post_rolling="UNKNOWN")]
    result = h.run()

    assert result.stage is MpxRunStage.RESTORATION_FAILED
    durable = json.loads(h.record.read_text("utf-8"))
    assert durable["baseline_restored"] is False
    assert durable["rolling_after"] == "UNKNOWN"
    assert durable["rolling_after_source"] == "restore_child_post_read"


def test_an_unknown_enable_read_never_invents_a_current_rolling_state(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path)
    h.baseline = inspection(rolling="ON_PROVEN")
    h.enable_result = enable_result().model_copy(
        update={"post_rolling": "UNKNOWN", "post_capture_kind": "clipped_entry"}
    )
    h.post_save = inspection(mode="VISUAL_DISABLED", rolling="OFF_PROVEN")
    result = h.run()

    assert result.stage is MpxRunStage.COMPLETE
    # The known fact is the *baseline capture's*, not a fresh claim about the Enable moment.
    assert result.rolling_at_enable == "ON_PROVEN"
    assert result.rolling_at_enable_source == "baseline_capture"
    assert any("states no rollover mark" in note for note in result.notes)


def test_a_capture_root_that_cannot_be_created_is_a_pre_gesture_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness(tmp_path)

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(AcquisitionError) as caught:
        h.run()

    message = str(caught.value)
    assert "PermissionError" in message
    assert "nothing was inspected or pressed" in message
    assert h.calls == []
    assert not h.record.exists()


def test_the_cli_reports_a_denied_capture_directory_as_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    captures = tmp_path / "captures"
    captures.mkdir()

    def deny(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(SystemExit) as caught:
        acquire_main(
            [
                "mpx-run",
                "run",
                "--channel",
                "1",
                "2",
                "--profiles",
                "10",
                "--stated-by",
                "operator",
                "--completion-timeout",
                "30",
                "--capture-root",
                str(captures),
                "--record",
                str(tmp_path / "parent.json"),
                "--store-dir",
                str(store),
            ]
        )

    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "could not be claimed" in err
    assert "nothing was inspected or pressed" in err
    assert "after its baseline inspection" not in err
