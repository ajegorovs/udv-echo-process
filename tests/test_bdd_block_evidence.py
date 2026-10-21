"""Decoder container evidence: real repeat-2 capture, fail-closed crafted cases.

The reader reports, on request only, every profile container it walked: its 0-based
source ordinal, its stored vendor block/sequence word and how many profile rows of each
quantity the container holds. Nothing here claims that a container *is* a visit: the
manual documents the footer word only as a block/sequence number, so the evidence is a
stored container account, and a report-level "block" is only ever a run of contiguous
containers sharing one word.

Fixtures:

* ``outputs/live/store/mpx12-50profiles-repeat2-01.BDD`` — the live repeat-2 capture.
  It is under the git-ignored ``outputs/`` tree, so the test skips when it is absent and
  no binary is published. Its facts are asserted from the file itself.
* ``data/4-sensor-velocity/200RPM.BDD`` — the tracked authentic multiplexed capture. The
  crafted cases copy it into ``tmp_path`` and mutate footer/type/channel bytes only, so
  every calculated axis still matches the stored one and the case exercises the evidence
  path rather than a depth-arithmetic accident.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
from itertools import pairwise
from pathlib import Path

import pytest

from udv_echo_process.acquire.mpx_artifact import (
    MpxRepeatVerification,
    MpxVerdict,
    verify_mpx_artifact,
)
from udv_echo_process.acquire.store_completed import CompletedBlockDeclaration
from udv_echo_process.io.dop import bdd

REAL_REPEAT2 = Path("outputs/live/store/mpx12-50profiles-repeat2-01.BDD")
REPEAT2_SHA256 = "bc79760cdc9cd91e22334db713feea3ca95e4d8eb9a6d15ac8d3a274e00dfbc8"
AUTHENTIC = Path("data/4-sensor-velocity/200RPM.BDD")
AUTHENTIC_CHANNELS = (6, 7, 8, 9)

# Documented offsets (module docstring of io/dop/bdd.py).
MEAS_BASE = 31268
SEQUENCE_OFFSET = -8  # uint16 block/sequence word relative to a container's end
CHANNEL_OFFSET = -3  # uint8 relative to a container's end


def _containers(raw: bytes) -> list[tuple[int, int, int, int]]:
    """Own walk: ``(start, end, channel, first profile type offset)`` per container.

    Deliberately independent of the package: the test must not learn the container
    layout from the code it is checking.
    """
    found: list[tuple[int, int, int, int]] = []
    start = MEAS_BASE
    while start + 4 <= len(raw):
        length = struct.unpack_from("<H", raw, start)[0]
        end = start + length
        if length == 0 or end > len(raw):
            break
        channel = raw[end + CHANNEL_OFFSET]
        found.append((start, end, channel, start + 2))
        start = end
    return found


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "crafted.BDD"
    shutil.copyfile(AUTHENTIC, target)
    return target


def _signal_type_offset(raw: bytes, start: int) -> int | None:
    """Byte offset of the first signal profile's type byte inside one container."""
    pos = start + 2
    while True:
        plen = struct.unpack_from("<H", raw, pos)[0]
        if plen == 0:
            return None
        if raw[pos + 2] in (0, 1, 2):
            return pos + 2
        pos += plen + 3


def _signal_containers_by_channel(raw: bytes) -> dict[int, list[int]]:
    """Container end offsets that carry a signal profile, per channel, in source order."""
    by_channel: dict[int, list[int]] = {}
    for start, end, channel, _pos in _containers(raw):
        if _signal_type_offset(raw, start) is not None:
            by_channel.setdefault(channel, []).append(end)
    return by_channel


def repeated(per_visit: int, repeats: int) -> CompletedBlockDeclaration:
    return CompletedBlockDeclaration(
        channels=AUTHENTIC_CHANNELS,
        profiles_per_visit=per_visit,
        sequence_repeats=repeats,
        stated_by="pytest",
    )


# --------------------------------------------------------------------- real repeat-2 file


@pytest.mark.skipif(
    not REAL_REPEAT2.exists(),
    reason="live repeat-2 capture is git-ignored and absent on this checkout",
)
def test_live_repeat2_capture_reports_two_runs_of_fifty_rows_per_channel() -> None:
    raw = REAL_REPEAT2.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REPEAT2_SHA256
    assert len(raw) == 43674

    bundle, evidence = bdd.read_with_containers(REAL_REPEAT2)

    # One row-id/timestamp model as before: 100 rows x 42 gates per channel.
    assert {
        stream.acquisition.channel.device_channel: stream.data.values.shape
        for stream in bundle.recording.streams
    } == {1: (100, 42), 2: (100, 42)}

    for channel in (1, 2):
        containers = [c for c in evidence.channel_containers(channel) if c.profiles]
        assert [c.stored_sequence for c in containers] == [1] * 50 + [2] * 50
        assert {p.quantity for c in containers for p in c.profiles} == {
            "axial_velocity"
        }
        assert {p.profiles for c in containers for p in c.profiles} == {1}
        setting = evidence.configured_for(channel)
        assert setting is not None
        assert (setting.containers_in_mode, setting.profiles_per_container) == (2, 50)

    declaration = CompletedBlockDeclaration(
        channels=(1, 2),
        profiles_per_visit=50,
        sequence_repeats=2,
        stated_by="pytest",
    )
    report = verify_mpx_artifact(REAL_REPEAT2, declaration)
    assert report.verdict is MpxVerdict.CONSISTENT
    assert report.repeat_verification is MpxRepeatVerification.PARTITION_CONSISTENT
    partition = {c.channel: c for c in report.block_partition}
    assert partition[1].stored_block_numbers == (1, 2)
    runs = [(g.block_number, g.profiles, g.containers) for g in partition[1].groups]
    assert runs == [(1, 50, 50), (2, 50, 50)]
    assert partition[1].configured_containers_in_mode == 2
    repeat_clause = next(c for c in report.clauses if c.subject == "repeats")
    assert "op 53 = 2" in repeat_clause.detail
    # The configured word is named as configuration, not as stored-container evidence.
    assert "not evidence that those profile containers" in repeat_clause.detail


# ------------------------------------------------------- authentic capture: run structure


def test_authentic_containers_are_reported_as_contiguous_runs() -> None:
    """100 runs of 4 rows per channel, from 1604 containers including depth-only ones."""
    _, evidence = bdd.read_with_containers(AUTHENTIC)

    assert evidence.containers_consumed == 1604
    assert evidence.trailing_bytes == 0
    for channel in AUTHENTIC_CHANNELS:
        containers = evidence.channel_containers(channel)
        assert len(containers) == 401
        # The first container of a channel carries only the depth pseudo-profile: it is
        # a stored container but not a measurement row, so it belongs to no run.
        assert containers[0].has_depth_axis is True
        assert containers[0].profiles == ()
        assert [c.source_ordinal for c in containers] == sorted(
            c.source_ordinal for c in containers
        )

    report = verify_mpx_artifact(AUTHENTIC, repeated(4, 100))
    assert report.verdict is MpxVerdict.CONSISTENT
    assert report.repeat_verification is MpxRepeatVerification.PARTITION_CONSISTENT
    for channel_report in report.block_partition:
        assert len(channel_report.groups) == 100
        assert len(channel_report.stored_block_numbers) == 100
        assert channel_report.blocks_with_unknown_number == 0
        assert {group.profiles for group in channel_report.groups} == {4}
        assert {group.containers for group in channel_report.groups} == {4}
        assert channel_report.configured_containers_in_mode == 100
        assert channel_report.configured_profiles_per_container == 4
        for group in channel_report.groups:
            ordinals = group.source_ordinals
            assert len(ordinals) == group.containers
            # Contiguity inside the run: the channel's own containers in one run are
            # adjacent in source order. Other channels' containers lie between runs, not
            # inside one.
            assert all(b - a == 1 for a, b in pairwise(ordinals))


# ------------------------------------------------------ causal: a reused word is not merged


def test_reused_alternating_words_do_not_yield_a_consistent_partition(
    tmp_path: Path,
) -> None:
    """Alternating 1,2 over 200 runs of 2 rows must not be read as "2 blocks of 200".

    The authentic file is mutated so each channel's 400 signal containers alternate
    between the words ``1`` and ``2``. That is 200 contiguous runs of 2 rows per channel
    and **no** run holds 200 rows: a histogram over the raw words (summing every ``1``
    together and every ``2`` together) would wrongly report two groups of 200 rows and
    call a ``2 x 200`` declaration consistent. Each word reappears in 100 non-contiguous
    runs, so the partition must stay unknown rather than be merged.
    """
    target = _copy(tmp_path)
    raw = bytearray(target.read_bytes())
    for ends in _signal_containers_by_channel(raw).values():
        assert len(ends) == 400  # the authentic 4 x 100 containers, one row each
        for index, end in enumerate(ends):
            # Two containers per word: 200 runs of 2 rows, alternating 1,2.
            struct.pack_into("<H", raw, end + SEQUENCE_OFFSET, 1 + (index // 2) % 2)
    target.write_bytes(raw)

    _, evidence = bdd.read_with_containers(target)
    sequences = [
        c.stored_sequence for c in evidence.channel_containers(6) if c.profiles
    ]
    assert sequences[:8] == [1, 1, 2, 2, 1, 1, 2, 2]

    report = verify_mpx_artifact(target, repeated(200, 2))
    channel = next(c for c in report.block_partition if c.channel == 6)
    assert len(channel.groups) == 200
    assert {group.profiles for group in channel.groups} == {2}
    assert len(channel.stored_block_numbers) == 2
    assert report.repeat_verification is MpxRepeatVerification.UNKNOWN
    assert report.verdict is not MpxVerdict.CONSISTENT
    repeat_clause = next(c for c in report.clauses if c.subject == "repeats")
    assert "reappear in more than one non-contiguous run" in repeat_clause.detail
    assert "not merged" in repeat_clause.detail

    # The same file must not satisfy the histogram-shaped declaration either.
    histogram_shaped = verify_mpx_artifact(target, repeated(2, 200))
    assert (
        histogram_shaped.repeat_verification
        is not MpxRepeatVerification.PARTITION_CONSISTENT
    )
    assert histogram_shaped.verdict is not MpxVerdict.CONSISTENT


# ------------------------------------------------------------------ crafted, fail-closed


def test_unknown_sequence_word_fails_closed_and_keeps_decoded_counts(
    tmp_path: Path,
) -> None:
    target = _copy(tmp_path)
    raw = bytearray(target.read_bytes())
    containers = [c for c in _containers(raw) if c[2] == 6]
    victim_end = containers[5][1]
    struct.pack_into("<H", raw, victim_end + SEQUENCE_OFFSET, 0)
    target.write_bytes(raw)

    _, evidence = bdd.read_with_containers(target)
    channel_containers = [c for c in evidence.channel_containers(6) if c.profiles]
    unknown = [c for c in channel_containers if c.stored_sequence is None]
    assert len(unknown) == 1
    assert "block identity is unknown" in unknown[0].note
    # The partial facts survive: the unknown container still carries its decoded row
    # count and its source ordinal, and the numbered containers are still reported.
    assert [p.quantity for p in unknown[0].profiles] == ["axial_velocity"]
    assert unknown[0].profiles[0].profiles == 1
    assert unknown[0].source_ordinal >= 0
    assert (
        len({c.stored_sequence for c in channel_containers if c.stored_sequence}) == 100
    )

    report = verify_mpx_artifact(target, repeated(4, 100))
    channel = next(c for c in report.block_partition if c.channel == 6)
    assert channel.blocks_with_unknown_number == 1
    assert any(group.block_number is None for group in channel.groups)
    assert report.verdict is MpxVerdict.UNVERIFIABLE
    assert report.repeat_verification is MpxRepeatVerification.UNKNOWN
    repeat_clause = next(c for c in report.clauses if c.subject == "repeats")
    assert "unknown block/sequence number" in repeat_clause.detail
    assert "their decoded counts are preserved" in repeat_clause.detail


def test_container_carrying_two_quantities_keeps_counts_separate(
    tmp_path: Path,
) -> None:
    target = _copy(tmp_path)
    raw = bytearray(target.read_bytes())
    # Reuse one real velocity payload from channel 6, then append one new container to
    # the file that carries it as both a velocity and an echo profile. Appending
    # changes no existing offset, so the calculated axes stay valid.
    payload = None
    for start, _end, channel, _pos in _containers(raw):
        if channel != 6:
            continue
        type_at = _signal_type_offset(raw, start)
        if type_at is not None and raw[type_at] == 0:
            plen = struct.unpack_from("<H", raw, type_at - 2)[0]
            payload = bytes(raw[type_at + 1 : type_at + 1 + plen])
            break
    assert payload is not None
    subblocks = (
        struct.pack("<H", len(payload))
        + b"\x00"
        + payload  # velocity
        + struct.pack("<H", len(payload))
        + b"\x01"
        + payload  # echo
        + b"\x00\x00"
    )
    footer = (
        struct.pack("<I", 60000) + struct.pack("<H", 3) + b"\x00\x00\x01\x06\x00\x00"
    )
    block = struct.pack("<H", len(subblocks) + len(footer) + 2) + subblocks + footer
    raw.extend(block)
    target.write_bytes(raw)

    _, evidence = bdd.read_with_containers(target)
    mixed = [
        c
        for c in evidence.channel_containers(6)
        if {p.quantity for p in c.profiles} == {"axial_velocity", "echo_amplitude"}
    ]
    assert len(mixed) == 1
    assert sorted(p.quantity for p in mixed[0].profiles) == [
        "axial_velocity",
        "echo_amplitude",
    ]

    report = verify_mpx_artifact(target, repeated(4, 100))
    channel = next(c for c in report.block_partition if c.channel == 6)
    assert {g.quantity for g in channel.groups} == {"axial_velocity", "echo_amplitude"}
    assert report.repeat_verification is MpxRepeatVerification.UNKNOWN
    repeat_clause = next(c for c in report.clauses if c.subject == "repeats")
    assert "more than one quantity" in repeat_clause.detail


def test_single_stored_run_with_stated_repeats_stays_unverifiable(
    tmp_path: Path,
) -> None:
    """One run holding the whole total cannot show the per-visit split."""
    target = _copy(tmp_path)
    raw = bytearray(target.read_bytes())
    containers = [c for c in _containers(raw) if c[2] == 6]
    numbered = [
        c
        for c in containers
        if struct.unpack_from("<H", raw, c[1] + SEQUENCE_OFFSET)[0]
    ]
    for _start, end, _channel, _pos in numbered:
        struct.pack_into("<H", raw, end + SEQUENCE_OFFSET, 1)
    target.write_bytes(raw)

    _, evidence = bdd.read_with_containers(target)
    assert {
        c.stored_sequence for c in evidence.channel_containers(6) if c.profiles
    } == {1}

    report = verify_mpx_artifact(target, repeated(4, 100))
    assert report.repeat_verification is MpxRepeatVerification.UNKNOWN
    repeat_clause = next(c for c in report.clauses if c.subject == "repeats")
    assert "single stored run cannot show the per-visit split" in repeat_clause.detail


# ------------------------------------------------------- plain read: opt-in, no new failure


def test_plain_read_builds_no_container_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``read`` must not construct per-container models; ``read_with_containers`` must."""

    def _refuse(**_kwargs):
        raise AssertionError("plain read built a per-container evidence model")

    monkeypatch.setattr(bdd, "SourceProfileContainer", _refuse)
    bundle = bdd.read(AUTHENTIC)
    assert len(bundle.recording.streams) == len(AUTHENTIC_CHANNELS)

    with pytest.raises(AssertionError, match="per-container evidence model"):
        bdd.read_with_containers(AUTHENTIC)


def test_evidence_walk_preserves_artifact_ids_clock_and_rows() -> None:
    """The opt-in walk must not move any id, timestamp or decoded value."""
    plain = bdd.read(AUTHENTIC)
    with_evidence, evidence = bdd.read_with_containers(AUTHENTIC)

    assert evidence.file_sha256 == plain.recording.source_asset.content_sha256
    assert with_evidence.recording.recording_id == plain.recording.recording_id
    assert [s.artifact_id for s in with_evidence.recording.streams] == [
        s.artifact_id for s in plain.recording.streams
    ]
    for expected, actual in zip(
        plain.recording.streams, with_evidence.recording.streams
    ):
        assert (actual.data.values == expected.data.values).all()
        assert (
            actual.data.acquisition.acquisition_time_s
            == expected.data.acquisition.acquisition_time_s
        ).all()
        assert (
            actual.data.acquisition.sample_id == expected.data.acquisition.sample_id
        ).all()
    # 1604 containers, of which 4 are depth-only: evidence changes no row.
    row_containers = sum(1 for c in evidence.containers if c.profiles)
    assert row_containers == 1600
    assert sum(sum(p.profiles for p in c.profiles) for c in evidence.containers) == sum(
        s.data.values.shape[0] for s in with_evidence.recording.streams
    )


def test_malformed_channel_zero_does_not_break_a_plain_read(tmp_path: Path) -> None:
    """A 0 channel word on a depth-only container is described, not turned into a failure.

    The plain read already succeeded on this shape (a depth-only container looks up no
    op words). Evidence-model strictness must not add a plain-read failure.
    """
    target = _copy(tmp_path)
    raw = bytearray(target.read_bytes())
    depth_only = [c for c in _containers(raw) if _signal_type_offset(raw, c[0]) is None]
    assert depth_only, "expected depth-only containers in the authentic capture"
    for _start, end, _channel, _pos in depth_only:
        raw[end + CHANNEL_OFFSET] = 0
    target.write_bytes(raw)

    bundle = bdd.read(target)  # must not raise
    assert len(bundle.recording.streams) == len(AUTHENTIC_CHANNELS)

    _, evidence = bdd.read_with_containers(target)
    zeroed = [c for c in evidence.containers if c.channel == 0]
    assert len(zeroed) == len(depth_only)
    assert all("not a valid channel" in c.note for c in zeroed)
    assert all(c.has_depth_axis for c in zeroed)
