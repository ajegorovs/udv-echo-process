"""Offline multiplexed-artifact verification: real fixtures and explicit boundaries."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from udv_echo_process.acquire import mpx_artifact
from udv_echo_process.acquire.store_completed import CompletedBlockDeclaration
from udv_echo_process.io import load

FIXTURE = Path("data/4-sensor-velocity/200RPM.BDD")
CHANNELS = (6, 7, 8, 9)
PROFILES = 400


def declaration(**overrides: object) -> CompletedBlockDeclaration:
    values: dict[str, object] = {
        "channels": CHANNELS,
        "profiles_per_channel": PROFILES,
        "stated_by": "pytest",
    }
    values.update(overrides)
    return CompletedBlockDeclaration(**values)


def stream(
    channel: int,
    values: np.ndarray,
    *,
    quantity: str = "axial_velocity",
    time_s: np.ndarray | None = None,
) -> SimpleNamespace:
    """A decoded-stream stand-in: only the attributes the summary owns."""
    rows = values.shape[0]
    times = np.arange(rows, dtype=float) if time_s is None else time_s
    return SimpleNamespace(
        acquisition=SimpleNamespace(channel=SimpleNamespace(device_channel=channel)),
        descriptor=SimpleNamespace(
            quantity=SimpleNamespace(value=quantity), unit="mm/s"
        ),
        data=SimpleNamespace(values=values, time_s=times),
    )


def report_for(streams: tuple[SimpleNamespace, ...]) -> mpx_artifact.MpxArtifactReport:
    """Build a report over synthetic streams, without touching a file."""
    channels = tuple(sorted({s.acquisition.channel.device_channel for s in streams}))
    profiles = int(streams[0].data.values.shape[0])
    synthetic_declaration = CompletedBlockDeclaration(
        channels=channels, profiles_per_channel=profiles, stated_by="pytest"
    )
    bundle = SimpleNamespace(
        recording=SimpleNamespace(
            streams=streams, acquisition_mode=SimpleNamespace(value="unknown")
        )
    )
    return mpx_artifact._report_from_bundle(
        Path("synthetic.BDD"),
        bundle,
        synthetic_declaration,
        sha256="0" * 64,
        byte_size=0,
        stat_note="synthetic streams, no file read",
    )


def test_real_fixture_is_consistent_and_keeps_provenance() -> None:
    result = mpx_artifact.verify_mpx_artifact(FIXTURE, declaration())

    raw = FIXTURE.read_bytes()
    assert result.verdict is mpx_artifact.MpxVerdict.CONSISTENT
    assert result.identity_verified is True
    assert result.file_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.byte_size == len(raw)
    assert result.decoded_channels == CHANNELS
    assert result.acquisition_mode == "sequential"
    assert "rolling" in result.mode_note
    assert [item.channel for item in result.streams] == list(CHANNELS)
    for item in result.streams:
        assert item.quantity == "axial_velocity"
        assert item.unit == "mm/s"
        assert item.profiles == PROFILES
        assert item.gates == 55
        assert item.finite_values == PROFILES * 55
        assert item.non_finite_values == 0
        assert item.nonzero_samples > 0
        assert item.abs_max is not None and item.abs_max > 0
        assert item.time_span_s is not None and item.time_span_s > 0
    assert {clause.status for clause in result.clauses} == {
        mpx_artifact.MpxVerdict.CONSISTENT
    }
    # The time figure is a span between decoded samples, and the report says so.
    assert "time_span_s" in result.streams[0].model_dump()
    assert "time_coverage_s" not in result.streams[0].model_dump()
    assert "span" in result.summary()


def test_wrong_profile_count_is_contradicted() -> None:
    result = mpx_artifact.verify_mpx_artifact(
        FIXTURE, declaration(profiles_per_channel=25)
    )

    assert result.verdict is mpx_artifact.MpxVerdict.CONTRADICTED
    profile_clauses = [
        clause for clause in result.clauses if clause.subject.startswith("profiles:")
    ]
    assert len(profile_clauses) == len(CHANNELS)
    for clause in profile_clauses:
        assert clause.status is mpx_artifact.MpxVerdict.CONTRADICTED
        assert clause.expected == 25
        assert clause.observed == PROFILES


def test_channel_set_mismatch_is_contradicted_and_extras_stay_unverifiable() -> None:
    result = mpx_artifact.verify_mpx_artifact(
        FIXTURE,
        CompletedBlockDeclaration(
            channels=(6, 7), profiles_per_channel=PROFILES, stated_by="pytest"
        ),
    )

    assert result.verdict is mpx_artifact.MpxVerdict.CONTRADICTED
    channels = next(c for c in result.clauses if c.subject == "channels")
    assert channels.status is mpx_artifact.MpxVerdict.CONTRADICTED
    assert "declared but not decoded" not in channels.detail
    assert "decoded but not declared: [8, 9]" in channels.detail
    extras = [
        clause
        for clause in result.clauses
        if clause.subject in {"profiles:channel 8", "profiles:channel 9"}
    ]
    assert {clause.status for clause in extras} == {
        mpx_artifact.MpxVerdict.UNVERIFIABLE
    }
    assert {clause.observed for clause in extras} == {PROFILES}


def test_declared_channel_absent_is_unverifiable_and_contradicted_set() -> None:
    result = mpx_artifact.verify_mpx_artifact(
        FIXTURE,
        CompletedBlockDeclaration(
            channels=(6, 7, 10), profiles_per_channel=PROFILES, stated_by="pytest"
        ),
    )

    assert result.verdict is mpx_artifact.MpxVerdict.CONTRADICTED
    absent = next(c for c in result.clauses if c.subject == "profiles:channel 10")
    assert absent.status is mpx_artifact.MpxVerdict.UNVERIFIABLE
    assert absent.observed is None


def test_garbage_is_unreadable_not_contradicted(tmp_path: Path) -> None:
    path = tmp_path / "garbage.BDD"
    path.write_bytes(b"not a bdd file" * 10)

    result = mpx_artifact.verify_mpx_artifact(path, declaration())

    assert result.verdict is mpx_artifact.MpxVerdict.UNREADABLE
    assert result.identity_verified is False
    assert result.streams == ()
    assert result.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.clauses[0].status is mpx_artifact.MpxVerdict.UNREADABLE


def test_truncated_file_reports_the_shorter_decode_honestly(tmp_path: Path) -> None:
    path = tmp_path / "truncated.BDD"
    path.write_bytes(FIXTURE.read_bytes()[:40000])

    result = mpx_artifact.verify_mpx_artifact(path, declaration())

    assert result.verdict is mpx_artifact.MpxVerdict.CONTRADICTED
    assert result.decoded_channels == CHANNELS
    assert [item.profiles for item in result.streams] != [PROFILES] * len(CHANNELS)
    assert all(item.profiles < PROFILES for item in result.streams)
    assert result.identity_verified is True
    for clause in result.clauses:
        if clause.subject.startswith("profiles:"):
            assert clause.status is mpx_artifact.MpxVerdict.CONTRADICTED


def test_invalid_declaration_is_refused_before_any_decode(monkeypatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("decode must not run for an invalid declaration")

    monkeypatch.setattr(mpx_artifact, "_decode", explode)
    # model_construct bypasses the model's own validation, so this exercises the
    # workflow's own before-decode guard rather than the constructor's.
    unvalidated = CompletedBlockDeclaration.model_construct(
        channels=(6,),
        profiles_per_channel=PROFILES,
        stated_by="pytest",
        stated_at="",
        statement="",
    )

    with pytest.raises(ValueError, match="single-channel completion"):
        mpx_artifact.verify_mpx_artifact(FIXTURE, unvalidated)


def test_cli_invalid_declaration_exits_2_concise_without_decode(
    monkeypatch, capsys
) -> None:
    from udv_echo_process import cli

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("decode must not run for an invalid declaration")

    monkeypatch.setattr(mpx_artifact, "_decode", explode)

    with pytest.raises(SystemExit) as raised:
        cli.acquire_main(
            [
                "mpx-check",
                str(FIXTURE),
                "--channel",
                "6",
                "--profiles",
                str(PROFILES),
            ]
        )
    assert raised.value.code == 2
    stderr = capsys.readouterr().err
    lines = [line for line in stderr.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "single-channel completion" in lines[0]
    # One refusal line, not pydantic's multi-line validation dump.
    assert "validation error" not in stderr.lower()
    assert "input_value" not in stderr


def test_cli_unreadable_file_exits_4(tmp_path: Path) -> None:
    from udv_echo_process import cli

    path = tmp_path / "garbage.BDD"
    path.write_bytes(b"not a bdd file" * 10)

    with pytest.raises(SystemExit) as raised:
        cli.acquire_main(
            [
                "mpx-check",
                str(path),
                "--channel",
                "6",
                "7",
                "--profiles",
                str(PROFILES),
            ]
        )
    assert raised.value.code == 4


def test_cli_unverifiable_decode_exits_3(monkeypatch) -> None:
    """A real decode with two streams for one channel maps to exit 3, not 0 or 1."""
    from udv_echo_process import cli

    real = load(FIXTURE)
    duplicated = real.recording.streams[0]
    decoded = SimpleNamespace(
        recording=SimpleNamespace(
            streams=(duplicated, duplicated, *real.recording.streams[1:]),
            acquisition_mode=real.recording.acquisition_mode,
            source_asset=real.recording.source_asset,
        )
    )
    monkeypatch.setattr(mpx_artifact, "_decode", lambda _path: (decoded, None))

    with pytest.raises(SystemExit) as raised:
        cli.acquire_main(
            [
                "mpx-check",
                str(FIXTURE),
                "--channel",
                *[str(channel) for channel in CHANNELS],
                "--profiles",
                str(PROFILES),
            ]
        )
    assert raised.value.code == 3


def test_non_finite_cells_are_explicit_and_never_graded() -> None:
    ok = np.zeros((2, 3), dtype=float)
    bad = np.array([[0.0, 0.0, 0.0], [1.0, np.nan, 0.0]])

    result = report_for((stream(6, ok), stream(7, bad, time_s=np.array([0.0, 1.0]))))

    assert result.verdict is mpx_artifact.MpxVerdict.UNVERIFIABLE
    summary = {item.channel: item for item in result.streams}
    assert summary[6].abs_max == 0.0  # zeros are signal, not failure
    assert summary[6].nonzero_samples == 0
    assert summary[7].non_finite_values == 1
    assert summary[7].finite_values == 5
    assert summary[7].nonzero_values == 1
    assert summary[7].nonzero_samples == 1
    assert summary[7].abs_max == 1.0
    data_clause = next(c for c in result.clauses if c.subject == "data:channel 7")
    assert data_clause.status is mpx_artifact.MpxVerdict.UNVERIFIABLE


def test_multiple_quantities_per_channel_are_not_conflated() -> None:
    values = np.zeros((3, 2), dtype=float)

    result = report_for(
        (
            stream(6, values, quantity="axial_velocity"),
            stream(6, values, quantity="echo_amplitude"),
            stream(7, values),
        )
    )

    clause = next(c for c in result.clauses if c.subject == "profiles:channel 6")
    assert clause.status is mpx_artifact.MpxVerdict.UNVERIFIABLE
    assert "more than one quantity" in clause.detail
    assert [item.quantity for item in result.streams if item.channel == 6] == [
        "axial_velocity",
        "echo_amplitude",
    ]
    duplicate = [item for item in result.streams if item.channel == 6]
    assert [item.profiles for item in duplicate] == [3, 3]
    assert result.verdict is mpx_artifact.MpxVerdict.UNVERIFIABLE


def test_file_replaced_during_verification_claims_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "replaced.BDD"
    shutil.copyfile(FIXTURE, path)
    decoded = load(path)

    def replace_then_decode(_path: Path):
        path.write_bytes(path.read_bytes() + b"replacement")
        return decoded, None

    monkeypatch.setattr(mpx_artifact, "_decode", replace_then_decode)

    result = mpx_artifact.verify_mpx_artifact(path, declaration())

    assert result.verdict is mpx_artifact.MpxVerdict.UNREADABLE
    assert result.identity_verified is False
    assert "streamed content digest changed while it was being verified" in (
        result.identity_note
    )
    assert result.streams == ()
    assert result.clauses[0].status is mpx_artifact.MpxVerdict.UNREADABLE


def test_decoder_digest_disagreement_is_unreadable_with_both_digests(
    monkeypatch,
) -> None:
    """The decoder's own content identity is compared, and both actual digests are shown."""
    real = load(FIXTURE)
    wrong_digest = "0" * 64
    wrong_asset = real.recording.source_asset.model_copy(
        update={
            "content_sha256": wrong_digest,
            "asset_id": f"sha256:{wrong_digest}",
        }
    )
    decoded = SimpleNamespace(
        recording=SimpleNamespace(
            streams=real.recording.streams,
            acquisition_mode=real.recording.acquisition_mode,
            source_asset=wrong_asset,
        )
    )
    monkeypatch.setattr(mpx_artifact, "_decode", lambda _path: (decoded, None))

    result = mpx_artifact.verify_mpx_artifact(FIXTURE, declaration())

    assert result.verdict is mpx_artifact.MpxVerdict.UNREADABLE
    assert result.identity_verified is False
    assert result.decoded_channels == ()
    actual = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert actual in result.identity_note
    assert wrong_digest in result.identity_note
    assert "decoder" in result.identity_note


def test_missing_file_is_unreadable_and_claims_no_identity(tmp_path: Path) -> None:
    missing = tmp_path / "absent.BDD"

    result = mpx_artifact.verify_mpx_artifact(missing, declaration())

    assert result.verdict is mpx_artifact.MpxVerdict.UNREADABLE
    assert result.file_sha256 is None
    assert result.byte_size is None
    assert result.identity_verified is False
    assert result.streams == ()
    assert "cannot read the file" in result.identity_note
    assert "corrupt" not in result.identity_note


def test_duplicate_same_quantity_streams_are_not_called_multiple_quantities() -> None:
    """A repeated quantity is a repeated quantity, not a second quantity."""
    values = np.zeros((3, 2), dtype=float)

    result = report_for(
        (
            stream(6, values, quantity="axial_velocity"),
            stream(6, values, quantity="axial_velocity"),
            stream(7, values),
        )
    )

    clause = next(c for c in result.clauses if c.subject == "profiles:channel 6")
    assert clause.status is mpx_artifact.MpxVerdict.UNVERIFIABLE
    assert "same quantity" in clause.detail
    assert "more than one quantity" not in clause.detail
    assert "[3, 3]" in clause.detail
    assert result.verdict is mpx_artifact.MpxVerdict.UNVERIFIABLE
