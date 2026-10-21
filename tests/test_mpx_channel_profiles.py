"""Per-channel (asymmetric) count declarations: one owner, no uniform fallback.

``--channel-profiles CHANNEL=COUNT`` paired with ``--repeats`` is the third count basis:
each declared channel states **its own** profiles-per-visit, and its expected stored total
is that channel's own count times the one repeat count. The uniform bases are unchanged:
``--profiles`` (a stated total) and ``--profiles-per-visit`` (one count for every channel)
still mean what they meant.

What is and is not claimed here
-------------------------------

* The asymmetric *declaration* arithmetic is checked on a hand-written statement labelled
  SYNTHETIC. It reads no file and is not an acceptance claim about any recording.
* The committed 4-channel fixture (``data/4-sensor-velocity/200RPM.BDD``) is used twice:
  with the legacy uniform total ``400`` (unchanged behaviour) and with an explicit
  per-channel mapping whose counts happen to agree (``4`` per visit on all four channels,
  ``100`` repeats). Both are real decodes of a tracked file.
* The real repeat-2 capture (``outputs/live/store/mpx12-50profiles-repeat2-01.BDD``) is
  git-ignored, so its case skips when the file is absent. Declaring ``ch 1 = 50 and
  ch 2 = 75`` per visit against it is a **correct negative**: channel 1's 100 rows agree
  with ``2 x 50`` and channel 2's 100 rows contradict its own ``2 x 75 = 150``. It is not
  a new asymmetric acceptance claim — no real asymmetric acquisition exists on this host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.acquire import mpx_artifact
from udv_echo_process.acquire import record_multiplexed as workflow
from udv_echo_process.acquire.actuator import (
    OverlayKind,
    StripControl,
    StripState,
    WindowTarget,
)
from udv_echo_process.acquire.store_completed import (
    CompletedBlockDeclaration,
    ProfileCountBasis,
    block_declaration_clauses,
    parse_channel_profiles,
)
from udv_echo_process.cli import acquire_main

FIXTURE = Path("data/4-sensor-velocity/200RPM.BDD")
CHANNELS = (6, 7, 8, 9)
TOTAL = 400
REAL_REPEAT2 = Path("outputs/live/store/mpx12-50profiles-repeat2-01.BDD")
HWND = 4711


def asymmetric(
    *,
    channels: tuple[int, ...] = (1, 2),
    counts: tuple[int, ...] = (50, 75),
    repeats: int = 2,
) -> CompletedBlockDeclaration:
    return CompletedBlockDeclaration(
        channels=channels,
        channel_profiles=tuple(zip(channels, counts, strict=True)),
        sequence_repeats=repeats,
        stated_by="pytest",
        statement="SYNTHETIC per-channel declaration (no recording behind it)",
    )


# ---------------------------------------------------- SYNTHETIC declaration arithmetic only


def test_synthetic_asymmetric_declaration_normalizes_each_channel_once() -> None:
    """SYNTHETIC: no file is read, and this is not an acceptance claim about a recording."""

    declaration = asymmetric()

    assert declaration.count_basis is (
        ProfileCountBasis.PER_CHANNEL_PER_VISIT_TIMES_REPEATS
    )
    # There is no uniform total to report: reporting 100 or 150 as "the" total would turn an
    # asymmetric statement into a uniform one.
    assert declaration.expected_total_profiles is None
    assert declaration.expected_profiles_by_channel == ((1, 100), (2, 150))
    assert declaration.count_for_channel(1) == 100
    assert declaration.count_for_channel(2) == 150
    assert declaration.per_visit_for_channel(1) == 50
    assert declaration.per_visit_for_channel(2) == 75
    # The mapping is normalized to the caller's channel order, never to the stated order.
    reordered = CompletedBlockDeclaration(
        channels=(2, 1),
        channel_profiles=((1, 50), (2, 75)),
        sequence_repeats=2,
        stated_by="pytest",
    )
    assert reordered.expected_profiles_by_channel == ((2, 150), (1, 100))
    # Both channels are named in words; neither is rendered as ``None``.
    summary = declaration.count_summary()
    assert "channel 1: 100 expected = 2 repeat(s) x 50 per visit" in summary
    assert "channel 2: 150 expected = 2 repeat(s) x 75 per visit" in summary
    assert "None" not in summary
    assert "not proof that 2 visit(s) were stored" in (
        declaration.repeat_verification_unknown
    )
    assert "channel 2: 75 profile(s) per visit" in (
        declaration.repeat_verification_unknown
    )


def test_parse_channel_profiles_is_strict_and_never_repairs() -> None:
    assert parse_channel_profiles(["1=50", "2=75"]) == ((1, 50), (2, 75))
    for bad, needle in [
        (["1=50", "1=75"], "more than once"),
        (["1=050"], "leading zero"),
        (["+1=50"], "not CHANNEL=COUNT"),
        (["1 =50"], "not CHANNEL=COUNT"),
        (["1=50", "2"], "one '='"),
        (["1=0"], "positive decimal integers"),
        (["0=50"], "positive decimal integers"),
        (["1=-5"], "positive decimal integers"),
    ]:
        with pytest.raises(ValueError, match=needle):
            parse_channel_profiles(bad)


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"channel_profiles": ((1, 50),)}, r"no count for declared channel\(s\) \[2\]"),
        (
            {"channel_profiles": ((1, 50), (2, 75), (3, 9))},
            "which the declared channels",
        ),
        (
            {"channel_profiles": ((1, 50), (1, 75), (2, 75))},
            "more than once",
        ),
        (
            {"channel_profiles": ((1, 50), (2, 75)), "sequence_repeats": None},
            "without a repeat count",
        ),
        (
            {
                "channel_profiles": ((1, 50), (2, 75)),
                "profiles_per_channel": 100,
                "sequence_repeats": 2,
            },
            "one basis",
        ),
        (
            {
                "channel_profiles": ((1, 50), (2, 75)),
                "profiles_per_visit": 50,
                "sequence_repeats": 2,
            },
            "one basis",
        ),
    ],
)
def test_mapping_is_refused_when_it_does_not_describe_the_declared_block(
    kwargs: dict, needle: str
) -> None:
    values: dict[str, object] = {
        "channels": (1, 2),
        "sequence_repeats": 2,
        "stated_by": "pytest",
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=needle):
        CompletedBlockDeclaration(**values)


# --------------------------------------- the tracked fixture: uniform counts are unchanged


def test_tracked_fixture_still_reports_the_legacy_total_as_consistent() -> None:
    declaration = CompletedBlockDeclaration(
        channels=CHANNELS, profiles_per_channel=TOTAL, stated_by="pytest"
    )

    report = mpx_artifact.verify_mpx_artifact(FIXTURE, declaration)

    assert report.verdict is mpx_artifact.MpxVerdict.CONSISTENT
    assert report.expected_total_profiles == TOTAL
    assert report.expected_profiles_by_channel == tuple(
        (channel, TOTAL) for channel in CHANNELS
    )
    for channel_report in report.block_partition:
        assert channel_report.configured_containers_in_mode == 100


def test_tracked_fixture_with_explicit_uniform_mapping_is_consistent() -> None:
    """A per-channel statement whose counts agree is still a real decode of the tracked file."""

    declaration = CompletedBlockDeclaration(
        channels=CHANNELS,
        channel_profiles=tuple((channel, 4) for channel in CHANNELS),
        sequence_repeats=100,
        stated_by="pytest",
    )

    report = mpx_artifact.verify_mpx_artifact(FIXTURE, declaration)

    assert report.verdict is mpx_artifact.MpxVerdict.CONSISTENT
    assert report.count_basis is (ProfileCountBasis.PER_CHANNEL_PER_VISIT_TIMES_REPEATS)
    assert report.expected_total_profiles is None
    assert report.expected_profiles_by_channel == tuple(
        (channel, TOTAL) for channel in CHANNELS
    )
    assert report.repeat_verification is (
        mpx_artifact.MpxRepeatVerification.PARTITION_CONSISTENT
    )
    profiles = [c for c in report.clauses if c.subject.startswith("profiles:")]
    for clause in profiles:
        assert clause.expected == TOTAL and clause.observed == TOTAL
        assert "for that channel" in clause.detail


# -------------------------------- the real repeat-2 capture: a correct asymmetric negative


@pytest.mark.skipif(
    not REAL_REPEAT2.exists(),
    reason="the repeat-2 capture lives under the git-ignored outputs/ tree",
)
def test_real_repeat2_file_contradicts_the_stated_channel_2_count_only() -> None:
    """Not an acceptance claim: the asymmetric declaration is used to check the *negative*.

    Channels 1 and 2 both stored 100 rows in two runs of 50. Stating ``1=50, 2=75`` per
    visit with 2 repeats must accept channel 1 (100 = 2 x 50) and contradict channel 2
    (150 expected, 100 stored), from that channel's own expectation — never a uniform count
    taken from channel 1.
    """

    report = mpx_artifact.verify_mpx_artifact(REAL_REPEAT2, asymmetric())

    assert report.verdict is mpx_artifact.MpxVerdict.CONTRADICTED
    assert report.expected_total_profiles is None
    assert report.expected_profiles_by_channel == ((1, 100), (2, 150))
    clauses = {clause.subject: clause for clause in report.clauses}
    assert clauses["profiles:channel 1"].status is mpx_artifact.MpxVerdict.CONSISTENT
    assert clauses["profiles:channel 1"].expected == 100
    assert clauses["profiles:channel 1"].observed == 100
    assert clauses["profiles:channel 2"].status is mpx_artifact.MpxVerdict.CONTRADICTED
    assert clauses["profiles:channel 2"].expected == 150
    assert clauses["profiles:channel 2"].observed == 100
    assert "for channel 2" in clauses["profiles:channel 2"].detail
    repeats = clauses["repeats"]
    assert repeats.status is mpx_artifact.MpxVerdict.CONTRADICTED
    assert "ch 1: 50, ch 2: 75" in repeats.detail
    assert "expected totals ch 1: 100, ch 2: 150" in repeats.detail
    assert "2 x 50" in repeats.detail
    assert "does not match the stated 2 run(s) x 75 profile(s)" in repeats.detail


# ---------------------------------------------------------------- CLI: refusals first


def run_cli(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as raised:
        acquire_main(argv)
    return int(raised.value.code)


@pytest.mark.parametrize(
    "declaration_args",
    [
        ["--channel-profiles", "1=50", "1=75", "--repeats", "2"],
        ["--channel-profiles", "1=50", "--repeats", "2"],
        ["--channel-profiles", "1=50", "2=75", "3=100", "--repeats", "2"],
        ["--channel-profiles", "1=050", "2=75", "--repeats", "2"],
        ["--channel-profiles", "1=0", "2=75", "--repeats", "2"],
        ["--channel-profiles", "1=50", "2=75"],
        ["--channel-profiles", "1=50", "2=75", "--repeats", "0"],
        ["--channel-profiles", "1=50", "2=75", "--repeats", "2", "--profiles", "100"],
        [
            "--channel-profiles",
            "1=50",
            "2=75",
            "--repeats",
            "2",
            "--profiles-per-visit",
            "50",
        ],
    ],
)
def test_cli_mpx_check_refuses_an_invalid_mapping_before_any_decode(
    tmp_path: Path, capsys, declaration_args: list[str]
) -> None:
    absent = tmp_path / "absent.BDD"
    code = run_cli(
        [
            "mpx-check",
            str(absent),
            "--channel",
            "1",
            "2",
            "--stated-by",
            "pytest",
            *declaration_args,
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("udv-acquire: refused: ")
    assert not absent.exists()


@pytest.mark.parametrize(
    "declaration_args",
    [
        ["--channel-profiles", "1=50", "1=75", "--repeats", "2"],
        ["--channel-profiles", "1=50", "2=75"],
        ["--channel-profiles", "1=50", "2=75", "3=9", "--repeats", "2"],
    ],
)
def test_cli_record_multiplexed_refuses_an_invalid_mapping_before_any_device_action(
    tmp_path: Path, capsys, declaration_args: list[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    code = run_cli(
        [
            "record-multiplexed",
            "asym-01",
            "--channel",
            "1",
            "2",
            "--mpx-enabled",
            "--completion-timeout",
            "30",
            "--stated-by",
            "operator",
            "--store-dir",
            str(store),
            *declaration_args,
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("udv-acquire: refused: ")
    assert list(store.iterdir()) == []


@pytest.mark.parametrize(
    "declaration_args",
    [
        ["--channel-profiles", "1=50", "1=75", "--repeats", "2"],
        [],
        ["--channel-profiles", "1=50", "2=75"],
    ],
)
def test_cli_store_completed_refuses_an_invalid_mapping_before_any_device_action(
    tmp_path: Path, capsys, declaration_args: list[str]
) -> None:
    store = tmp_path / "store"
    store.mkdir()
    code = run_cli(
        [
            "store-completed",
            "asym-01",
            "--channel",
            "1",
            "2",
            "--stated-by",
            "operator",
            "--store-dir",
            str(store),
            *declaration_args,
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("udv-acquire: refused: ")
    assert list(store.iterdir()) == []


# ---------------------------------------------- a full record/store with a fake verifier


class StoredScreen:
    """The narrow screen double: ready row, completion row, one stored file of bytes."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.target: WindowTarget | None = None
        self.presses: list[StripControl] = []
        self.store_names: list[str] = []
        self.commits = 0
        self.recorded = False
        self.store_pressed = False
        self.warnings: list[str] = []

    def bind_target(self, hwnd: int) -> WindowTarget:
        self.target = WindowTarget(
            hwnd=hwnd, thread_id=11, process_id=22, class_name="TMain_Scr"
        )
        return self.target

    def verify_bound_target(self, expected: WindowTarget) -> WindowTarget:
        return expected

    def window_caption(self) -> str:
        return "UDOP DOP3010.43"

    def peek_overlay(self) -> OverlayKind | None:
        return OverlayKind.STORE_DIALOG if self.store_pressed else None

    def strip_state(self) -> StripState:
        if not self.recorded:
            return StripState(button_count=3, has_slider=False)
        return StripState(button_count=2, has_slider=True, slider_max=50)

    def press(self, control: StripControl) -> None:
        self.presses.append(control)
        if control is StripControl.RECORD:
            self.recorded = True
        elif control is StripControl.DO_STORE:
            self.store_pressed = True

    def set_store_name(self, name: str) -> None:
        self.store_names.append(name)

    def verify_working_directory(self, directory: Path):
        from udv_echo_process.acquire.udop.store import StoreDirectoryVerification

        return StoreDirectoryVerification(
            before=str(directory), after=str(directory), changed=False
        )

    def commit_store(self) -> None:
        self.commits += 1

    def wait_for_stored_file(self, directory: Path, *, known, timeout_s: float) -> Path:
        path = Path(directory) / f"{self.store_names[-1]}.BDD"
        path.write_bytes(self.payload)
        return path


def test_record_then_store_carries_the_asymmetric_declaration_into_the_verifier(
    tmp_path: Path,
) -> None:
    """The verifier receives the operator's own asymmetric statement, and the store is one."""

    seen: list[CompletedBlockDeclaration] = []

    def fake_verifier(path: Path, declaration: CompletedBlockDeclaration):
        seen.append(declaration)  # a report-less (None) check: an explicit unknown

    screen = StoredScreen(b"stored bytes")
    result = workflow.record_multiplexed(
        "asym-run",
        tmp_path,
        declaration=workflow.MultiplexedRecordingDeclaration(
            multiplexer_enabled=True,
            channels=(1, 2),
            channel_profiles=((1, 50), (2, 75)),
            sequence_repeats=2,
            stated_by="operator",
            stated_at="2026-10-21T21:30:00+03:00",
            statement="MPX on, ch 1 = 50, ch 2 = 75 per visit, repeat 2",
        ),
        completion_timeout_s=30.0,
        actuator=screen,
        enumerate_windows=lambda: (HWND,),
        sleep=lambda _s: None,
        verify_artifact=fake_verifier,
    )

    assert result.stage is workflow.MpxStage.STORED
    assert screen.presses == [StripControl.RECORD, StripControl.DO_STORE]
    assert screen.commits == 1
    assert result.stored_path == tmp_path / "asym-run.BDD"
    assert result.artifact_verification is None
    assert result.artifact_verification_error
    # The original declaration, not a derived uniform one, is what the verifier judged.
    assert len(seen) == 1
    judged = seen[0]
    assert judged.channel_profiles == ((1, 50), (2, 75))
    assert judged.sequence_repeats == 2
    assert judged.expected_total_profiles is None
    assert judged.expected_profiles_by_channel == ((1, 100), (2, 150))
    assert judged.stated_by == "operator"
    assert judged.stated_at == "2026-10-21T21:30:00+03:00"
    # Both the result and the store's own record carry the mapping, rendered in words.
    assert result.declaration.channel_profiles == ((1, 50), (2, 75))
    assert result.store is not None
    assert result.store.declaration.channel_profiles == ((1, 50), (2, 75))
    assert result.store.declaration.expected_total_profiles is None
    assert "channel 2: 150 expected" in result.store.declaration.count_summary()
    assert "asym-run" in result.store.summary()


def test_block_declaration_clauses_accepts_a_complete_mapping() -> None:
    clauses = block_declaration_clauses(
        (1, 2),
        None,
        "pytest",
        sequence_repeats=2,
        channel_profiles=((1, 50), (2, 75)),
    )
    assert clauses == ()
