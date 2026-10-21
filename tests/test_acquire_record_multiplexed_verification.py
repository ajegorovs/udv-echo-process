"""The post-store artifact verification: stored stays stored, verification is its own report.

These cases drive the **production** workflow and the **production** verifier on the committed
4-channel fixture: the store double writes that fixture's bytes to the exact path the store
returns, so the report is a real decode rather than a stand-in. The verifier boundary is
injected only for the case where the verifier itself raises, which no fixture can express.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from udv_echo_process.acquire import record_multiplexed as workflow
from udv_echo_process.acquire.actuator import (
    OverlayKind,
    StripControl,
    StripState,
    WindowTarget,
)
from udv_echo_process.acquire.mpx_artifact import MpxRepeatVerification, MpxVerdict
from udv_echo_process.acquire.record_multiplexed import (
    MPX_MODE_NOT_READ,
    MpxStage,
    MultiplexedRecordingDeclaration,
    record_multiplexed,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.store import StoreDirectoryVerification
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.cli import acquire_main

HWND = 4711
FIXTURE = Path("data/4-sensor-velocity/200RPM.BDD")
CHANNELS = (6, 7, 8, 9)
PROFILES = 400

READY = StripState(button_count=3, has_slider=False)
COMPLETED = StripState(button_count=2, has_slider=True, slider_max=50)


class StoredScreen:
    """One bound window, a ready row, the completion row, and a stored file of ``payload``."""

    def __init__(self, payload: bytes, *, on_stored=None) -> None:
        self.payload = payload
        self.on_stored = on_stored
        self.target: WindowTarget | None = None
        self.presses: list[tuple[StripControl, int]] = []
        self.store_names: list[str] = []
        self.commits = 0
        self.recorded = False
        self.store_pressed = False
        self.warnings: list[str] = []

    def bind_target(self, hwnd: int) -> WindowTarget:
        self.target = WindowTarget(
            hwnd=hwnd, thread_id=11, process_id=22, class_name=MAIN_CLASS
        )
        return self.target

    def verify_bound_target(self, expected: WindowTarget) -> WindowTarget:
        if self.target != expected:
            raise AcquisitionError("the original target identity changed")
        return expected

    def window_caption(self) -> str:
        return "UDOP DOP3010.43"

    def peek_overlay(self) -> OverlayKind | None:
        return OverlayKind.STORE_DIALOG if self.store_pressed else None

    def strip_state(self) -> StripState:
        return COMPLETED if self.recorded else READY

    def press(self, control: StripControl) -> None:
        self.presses.append((control, self.target.hwnd if self.target else 0))
        if control is StripControl.RECORD:
            self.recorded = True
        elif control is StripControl.DO_STORE:
            self.store_pressed = True

    def set_store_name(self, name: str) -> None:
        self.store_names.append(name)

    def verify_working_directory(self, directory: Path) -> StoreDirectoryVerification:
        return StoreDirectoryVerification(
            before=str(directory), after=str(directory), changed=False
        )

    def commit_store(self) -> None:
        self.commits += 1

    def wait_for_stored_file(self, directory: Path, *, known, timeout_s: float) -> Path:
        path = Path(directory) / f"{self.store_names[-1]}.BDD"
        path.write_bytes(self.payload)
        if self.on_stored is not None:
            self.on_stored(path)
        return path

    def controls(self) -> list[StripControl]:
        return [control for control, _hwnd in self.presses]


def declaration(**overrides) -> MultiplexedRecordingDeclaration:
    fields = {
        "multiplexer_enabled": True,
        "channels": CHANNELS,
        "profiles_per_channel": PROFILES,
        "stated_by": "operator",
        "stated_at": "2026-10-21T20:00:00+03:00",
        "statement": "MPX on, four channels, 400 profiles each",
    }
    fields.update(overrides)
    return MultiplexedRecordingDeclaration(**fields)


def run(
    tmp_path: Path,
    *,
    screen: StoredScreen,
    declar: MultiplexedRecordingDeclaration | None = None,
    **kwargs,
):
    return record_multiplexed(
        "mpx-run",
        tmp_path,
        declaration=declar or declaration(),
        completion_timeout_s=30.0,
        actuator=screen,
        enumerate_windows=lambda: (HWND,),
        sleep=lambda _s: None,
        **kwargs,
    )


def cli_args(tmp_path: Path, *, profiles: int = PROFILES, json_output: bool = False):
    args = [
        "record-multiplexed",
        "mpx-run",
        "--channel",
        *[str(channel) for channel in CHANNELS],
        "--profiles",
        str(profiles),
        "--stated-by",
        "operator",
        "--mpx-enabled",
        "--completion-timeout",
        "30",
        "--store-dir",
        str(tmp_path),
    ]
    if json_output:
        args.append("--json")
    return args


# ------------------------------------------------------------------- stored and consistent


def test_stored_artifact_is_verified_against_the_original_declaration(tmp_path: Path):
    payload = FIXTURE.read_bytes()
    screen = StoredScreen(payload)
    result = run(tmp_path, screen=screen)

    assert result.stage is MpxStage.STORED
    assert result.stored and result.stored_path == tmp_path / "mpx-run.BDD"
    assert result.stored_path.read_bytes() == payload
    assert result.artifact_consistent is True
    report = result.artifact_verification
    assert report is not None
    assert report.verdict is MpxVerdict.CONSISTENT
    assert report.file_name == "mpx-run.BDD"
    assert report.file_sha256 == hashlib.sha256(payload).hexdigest()
    assert report.declared_channels == CHANNELS
    assert report.declared_profiles_per_channel == PROFILES
    # The declaration is the operator's original one: attribution, date and words survive.
    assert result.declaration.stated_by == "operator"
    assert result.declaration.stated_at == "2026-10-21T20:00:00+03:00"
    assert result.declaration.statement.startswith("MPX on")
    assert result.store is not None and result.store.declaration.stated_by == "operator"
    assert result.store.declaration.stated_at == "2026-10-21T20:00:00+03:00"
    # The store evidence is unchanged, and exactly one Record and one Do store were made.
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1
    assert result.store.stored_path == result.stored_path
    assert result.store.store.commit_presses == 1
    assert result.owed == (MPX_MODE_NOT_READ,)


def test_filename_is_not_used_to_infer_the_declared_channels(tmp_path: Path):
    """The stored name is 'mpx-run'; the check compares the declared channel set, not the name."""
    screen = StoredScreen(FIXTURE.read_bytes())
    result = run(tmp_path, screen=screen, declar=declaration(channels=(6, 7)))

    report = result.artifact_verification
    assert report is not None and report.verdict is MpxVerdict.CONTRADICTED
    channels = next(c for c in report.clauses if c.subject == "channels")
    assert "decoded but not declared: [8, 9]" in channels.detail
    assert report.declared_channels == (6, 7)


def test_repeated_declaration_compares_the_stored_block_partition_not_visits(
    tmp_path: Path,
):
    """4 per visit x 100 repeats matches 100 stored blocks of 4 rows; visits stay unclaimed.

    The furnished file is authentic (a 100-block multiplexed acquisition) and the reader
    reports each stored block's own block/sequence word, so the stated split is compared with
    a **stored block partition** and the run reports it consistent. The footer word is a
    block/sequence number, not a visit identity, so the run must not claim 100 visits ran:
    the declaration's own unknown is still owed in words.
    """
    screen = StoredScreen(FIXTURE.read_bytes())
    declar = declaration(
        profiles_per_channel=None, profiles_per_visit=4, sequence_repeats=100
    )
    result = run(tmp_path, screen=screen, declar=declar)

    assert result.stage is MpxStage.STORED
    report = result.artifact_verification
    assert report is not None
    assert report.verdict is MpxVerdict.CONSISTENT
    assert result.artifact_consistent is True
    assert report.expected_total_profiles == PROFILES
    assert report.declared_profiles_per_channel is None
    assert report.declared_profiles_per_visit == 4
    assert report.declared_sequence_repeats == 100
    profiles = [c for c in report.clauses if c.subject.startswith("profiles:")]
    assert {c.status for c in profiles} == {MpxVerdict.CONSISTENT}
    # The stored partition is what was compared: 100 block numbers x 4 rows per channel.
    assert {c.channel for c in report.block_partition} == set(CHANNELS)
    for channel_report in report.block_partition:
        assert len(channel_report.stored_block_numbers) == 100
        assert channel_report.blocks_with_unknown_number == 0
        assert {group.profiles for group in channel_report.groups} == {4}
    assert report.repeat_verification is MpxRepeatVerification.PARTITION_CONSISTENT
    repeats = [c for c in report.clauses if c.subject == "repeats"]
    assert len(repeats) == 1 and repeats[0].status is MpxVerdict.CONSISTENT
    assert repeats[0].expected == 100 and repeats[0].observed == 100
    assert "footer word is documented as a block/sequence number" in repeats[0].detail
    assert "not a visit identity" in repeats[0].detail
    # A consistent partition is still not a decoded visit count.
    assert "not a decoded visit or round count" in report.repeat_note
    # The operator's own per-visit/repeat numbers survive into the stored declaration and
    # the visit unknown is still owed in words beside the partition result.
    assert result.declaration.profiles_per_visit == 4
    assert result.declaration.sequence_repeats == 100
    assert result.store is not None
    assert result.store.declaration.expected_total_profiles == PROFILES
    assert result.owed[0] == MPX_MODE_NOT_READ
    assert any(
        "actual number of stored visits is unknown" in item for item in result.owed
    )
    assert "not proof that 100 visit(s)" in result.owed[1]
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1


# ------------------------------------------------------------- stored but not consistent


def test_contradicted_artifact_keeps_the_stored_fact_and_acts_once(tmp_path: Path):
    screen = StoredScreen(FIXTURE.read_bytes())
    result = run(tmp_path, screen=screen, declar=declaration(profiles_per_channel=25))

    assert result.stage is MpxStage.STORED
    assert result.stored and result.stored_path.exists()
    assert result.artifact_verification is not None
    assert result.artifact_verification.verdict is MpxVerdict.CONTRADICTED
    assert result.artifact_consistent is False
    assert result.artifact_verification_error == ""
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1
    # The existing mode-unknown obligation is kept, and the mismatch is added to what is owed.
    assert result.owed[0] == MPX_MODE_NOT_READ
    assert "contradicted" in result.owed[-1]
    assert "neither re-recorded nor re-stored" in result.owed[-1]


def test_missing_file_after_store_is_unreadable_and_still_stored(tmp_path: Path):
    from udv_echo_process.acquire.mpx_artifact import verify_mpx_artifact

    def delete_then_verify(path: Path, declar):
        path.unlink()
        return verify_mpx_artifact(path, declar)

    screen = StoredScreen(FIXTURE.read_bytes())
    result = run(tmp_path, screen=screen, verify_artifact=delete_then_verify)

    assert result.stage is MpxStage.STORED
    assert result.stored_path == tmp_path / "mpx-run.BDD"
    assert not result.stored_path.exists()
    assert result.artifact_verification is not None
    assert result.artifact_verification.verdict is MpxVerdict.UNREADABLE
    assert result.artifact_verification.file_sha256 is None
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1


def test_an_unverifiable_report_still_leaves_the_file_stored(tmp_path: Path):
    from udv_echo_process.acquire.mpx_artifact import MpxArtifactReport, MpxClause

    def unverifiable(path: Path, declar):
        return MpxArtifactReport(
            file_name=path.name,
            file_sha256="0" * 64,
            byte_size=path.stat().st_size,
            identity_verified=True,
            identity_note="injected boundary: a decoded stream could not be compared",
            acquisition_mode="unknown",
            mode_note="injected boundary",
            declared_channels=CHANNELS,
            declared_profiles_per_channel=PROFILES,
            expected_total_profiles=PROFILES,
            decoded_channels=CHANNELS,
            clauses=(
                MpxClause(
                    subject="profiles:channel 6",
                    status=MpxVerdict.UNVERIFIABLE,
                    detail="injected boundary",
                ),
            ),
            verdict=MpxVerdict.UNVERIFIABLE,
        )

    screen = StoredScreen(FIXTURE.read_bytes())
    result = run(tmp_path, screen=screen, verify_artifact=unverifiable)

    assert result.stage is MpxStage.STORED
    assert result.stored_path is not None and result.stored_path.exists()
    assert result.artifact_verification is not None
    assert result.artifact_verification.verdict is MpxVerdict.UNVERIFIABLE
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1
    assert "unverifiable" in result.owed[-1]


def test_a_raising_verifier_is_an_explicit_unknown_not_a_store_failure(tmp_path: Path):
    calls: list[tuple[Path, object]] = []

    def explode(path: Path, declar):
        calls.append((path, declar))
        raise RuntimeError("decoder state unavailable")

    screen = StoredScreen(FIXTURE.read_bytes())
    result = run(tmp_path, screen=screen, verify_artifact=explode)

    assert result.stage is MpxStage.STORED
    assert result.stored and result.stored_path.exists()
    assert result.artifact_verification is None
    assert (
        result.artifact_verification_error == "RuntimeError: decoder state unavailable"
    )
    # The check ran once on the exact returned path, with the original declaration.
    assert len(calls) == 1 and calls[0][0] == result.stored_path
    assert calls[0][1].stated_by == "operator"
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1
    assert "not verified" in result.owed[-1]
    assert "neither re-recorded nor rewritten" in result.owed[-1]


# ------------------------------------------------ the verifier boundary's own return value


def test_a_verifier_returning_none_is_an_explicit_unknown_not_a_crash(tmp_path: Path):
    """``None`` from an injected verifier is a report-less check, never a stored claim."""

    def none(path: Path, declar):
        return None

    screen = StoredScreen(FIXTURE.read_bytes())
    result = run(tmp_path, screen=screen, verify_artifact=none)

    assert result.stage is MpxStage.STORED
    assert result.stored and result.stored_path == tmp_path / "mpx-run.BDD"
    assert result.stored_path.exists()
    assert result.artifact_verification is None
    assert result.artifact_verification_error
    assert "not verified" in result.owed[-1]
    assert "neither re-recorded nor rewritten" in result.owed[-1]
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1


def test_a_verifier_returning_a_wrong_type_is_an_explicit_unknown_not_a_crash(
    tmp_path: Path,
):
    """A dict where a report belongs is an unverified file, not an ``AttributeError``."""

    def wrong_type(path: Path, declar):
        return {"verdict": "consistent"}

    screen = StoredScreen(FIXTURE.read_bytes())
    result = run(tmp_path, screen=screen, verify_artifact=wrong_type)

    assert result.stage is MpxStage.STORED
    assert result.stored and result.stored_path.exists()
    assert result.artifact_verification is None
    assert result.artifact_verification_error
    assert "dict" in result.artifact_verification_error
    assert result.artifact_consistent is False
    assert "not verified" in result.owed[-1]
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1


# ------------------------------------------------------------------- no store, no verification


def test_a_failed_store_is_never_verified(tmp_path: Path):
    calls: list[Path] = []
    screen = StoredScreen(FIXTURE.read_bytes())

    def fail(directory):
        raise OSError("readback unavailable")

    screen.verify_working_directory = fail
    result = run(
        tmp_path, screen=screen, verify_artifact=lambda path, d: calls.append(path)
    )

    assert result.stage is MpxStage.STORE_FAILED
    assert result.stored is False
    assert result.artifact_verification is None
    assert result.artifact_verification_error == ""
    assert calls == []
    assert screen.commits == 0


def test_a_failed_record_press_is_never_verified(tmp_path: Path):
    calls: list[Path] = []
    screen = StoredScreen(FIXTURE.read_bytes())

    def refuse(control):
        raise RuntimeError("message queue refused")

    screen.press = refuse
    result = run(
        tmp_path, screen=screen, verify_artifact=lambda path, d: calls.append(path)
    )

    assert result.stage is MpxStage.RECORD_REFUSED
    assert result.artifact_verification is None
    assert result.artifact_verification_error == ""
    assert calls == []


# ---------------------------------------------------------------------------------------- CLI


def test_cli_prints_json_and_exits_0_only_for_stored_and_consistent(
    tmp_path: Path, monkeypatch, capsys
):
    screen = StoredScreen(FIXTURE.read_bytes())
    monkeypatch.setattr(workflow, "Win32Actuator", lambda **kwargs: screen)
    monkeypatch.setattr(workflow, "visible_main_windows", lambda *args: (HWND,))

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(cli_args(tmp_path, json_output=True))

    assert exit_info.value.code == 0
    dumped = json.loads(capsys.readouterr().out)
    assert dumped["stage"] == "stored"
    assert dumped["artifact_verification"]["verdict"] == "consistent"
    assert dumped["stored_path"].endswith("mpx-run.BDD")
    assert dumped["declaration"]["stated_by"] == "operator"


def test_cli_exits_nonzero_on_a_stored_mismatch_and_names_the_saved_path(
    tmp_path: Path, monkeypatch, capsys
):
    screen = StoredScreen(FIXTURE.read_bytes())
    monkeypatch.setattr(workflow, "Win32Actuator", lambda **kwargs: screen)
    monkeypatch.setattr(workflow, "visible_main_windows", lambda *args: (HWND,))

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(cli_args(tmp_path, profiles=25))

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert "contradicted" in captured.out
    assert "stored" in captured.err and str(tmp_path / "mpx-run.BDD") in captured.err
    assert "neither rewritten nor re-stored" in captured.err
    assert screen.commits == 1
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]


def test_cli_exits_4_on_a_stored_unreadable_file_and_keeps_the_path(
    tmp_path: Path, monkeypatch, capsys
):
    screen = StoredScreen(b"not a bdd file")
    monkeypatch.setattr(workflow, "Win32Actuator", lambda **kwargs: screen)
    monkeypatch.setattr(workflow, "visible_main_windows", lambda *args: (HWND,))

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(cli_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_info.value.code == 4
    assert str(tmp_path / "mpx-run.BDD") in captured.err
    assert "unreadable" in captured.err
    assert screen.commits == 1


def _cli_with_verifier(tmp_path: Path, monkeypatch, verifier):
    """Drive the real CLI with ``verifier`` bound where the workflow's default sits.

    ``record_multiplexed`` binds ``verify_mpx_artifact`` as a keyword default at import, so the
    CLI's own call can only be reached by replacing that default — the seam the boundary is.
    """
    screen = StoredScreen(FIXTURE.read_bytes())
    monkeypatch.setattr(workflow, "Win32Actuator", lambda **kwargs: screen)
    monkeypatch.setattr(workflow, "visible_main_windows", lambda *args: (HWND,))
    monkeypatch.setitem(
        workflow.record_multiplexed.__kwdefaults__, "verify_artifact", verifier
    )
    return screen


def test_cli_exits_3_when_the_verifier_raises_and_names_the_stored_path(
    tmp_path: Path, monkeypatch, capsys
):
    def explode(path: Path, declar):
        raise RuntimeError("decoder state unavailable")

    screen = _cli_with_verifier(tmp_path, monkeypatch, explode)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(cli_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_info.value.code == 3
    assert "RuntimeError: decoder state unavailable" in captured.err
    assert str(tmp_path / "mpx-run.BDD") in captured.err
    assert "neither rewritten nor re-stored" in captured.err
    assert screen.commits == 1
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]


def test_cli_exits_3_on_an_unverifiable_report_and_names_the_stored_path(
    tmp_path: Path, monkeypatch, capsys
):
    from udv_echo_process.acquire.mpx_artifact import MpxArtifactReport, MpxClause

    def unverifiable(path: Path, declar):
        return MpxArtifactReport(
            file_name=path.name,
            file_sha256="0" * 64,
            byte_size=path.stat().st_size,
            identity_verified=True,
            identity_note="injected boundary: a decoded stream could not be compared",
            acquisition_mode="unknown",
            mode_note="injected boundary",
            declared_channels=CHANNELS,
            declared_profiles_per_channel=PROFILES,
            expected_total_profiles=PROFILES,
            decoded_channels=CHANNELS,
            clauses=(
                MpxClause(
                    subject="profiles:channel 6",
                    status=MpxVerdict.UNVERIFIABLE,
                    detail="injected boundary",
                ),
            ),
            verdict=MpxVerdict.UNVERIFIABLE,
        )

    screen = _cli_with_verifier(tmp_path, monkeypatch, unverifiable)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(cli_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_info.value.code == 3
    assert "unverifiable" in captured.err
    assert str(tmp_path / "mpx-run.BDD") in captured.err
    assert "neither rewritten nor re-stored" in captured.err
    assert screen.commits == 1
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]


def test_cli_exits_3_when_the_verifier_returns_no_report(
    tmp_path: Path, monkeypatch, capsys
):
    screen = _cli_with_verifier(tmp_path, monkeypatch, lambda path, declar: None)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(cli_args(tmp_path))

    captured = capsys.readouterr()
    assert exit_info.value.code == 3
    assert "artifact verification failed" in captured.err
    assert str(tmp_path / "mpx-run.BDD") in captured.err
    assert screen.commits == 1
    assert screen.controls() == [StripControl.RECORD, StripControl.DO_STORE]
