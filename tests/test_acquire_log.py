"""Tests for the experiment log — ``acquire/log.py``.

The log is where "requested vs read back vs decoded" is preserved, so these
tests pin three things the recon session paid for:

- the **channel** is part of the record and there is no safe default for it
  (reading the wrong channel's block once "proved" a write had failed, docs/16
  §12/§12a);
- the **achieved resolution** comes from the stored block's word 10 — the rung
  index — not from anything we wrote (``4 -> 0.6083`` at c = 1460, ``1 -> 0.250``
  at c = 1500, docs/16 §12a);
- the **size signature** guard: a leftover recording was later stored under the
  next point's name as a 1,039,825 B file — 10x a normal point — so a size far
  off the signature invalidates the point (docs/16 §15b). The calibration is the
  two measured points, 805 gates over ~71 profiles at ~98 KB.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from udv_echo_process.acquire.actuator import (
    BurstState,
    BurstWriteResult,
    ColumnWriteResult,
    ComboReading,
    ParamRole,
    WriteState,
)
from udv_echo_process.acquire.config import (
    ParameterSet,
    ProfileTiming,
    RecordSettings,
)
from udv_echo_process.acquire.log import (
    KNOWN_RECORD_TYPES,
    LEGACY_BURST_HISTORY_KEY,
    DecodedBlock,
    PointStatus,
    SizeSignature,
    SweepLogHeader,
    SweepParameterMutation,
    SweepPointRecord,
    append_entry,
    migrate_legacy_burst_history,
    parameter_mutations,
    point_names,
    point_records,
    read_entries,
    sweep_id_for,
)
from udv_echo_process.acquire.plan import SweepDefinition
from udv_echo_process.io.dop.bdd import read

MEASURED_SIZE_BYTES = 97_993  # the first point's file at 805 gates, 1.5 s
MEASURED_SIZE_BYTES_ALT = 97_169
CONTAMINATED_SIZE_BYTES = 1_039_825  # a leftover recording stored as a point


def _parameters(gates: int = 805, resolution_mm: float = 0.121667) -> ParameterSet:
    return ParameterSet(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        resolution_mm=resolution_mm,
        gates=gates,
        prf_us=200.0,
    )


def _record(**overrides: object) -> SweepPointRecord:
    fields: dict[str, object] = {
        "sweep_id": "20260917T161738",
        "key": 1,
        "name": "sw100-k1-20260917T161738",
        "status": PointStatus.OK,
        "requested": _parameters(),
        "timing": ProfileTiming(target_s=0.0212, achieved_s=0.0212),
        "readback_gates": 805,
        "readback_resolution": "0.122",
        "file_path": "capture/sw100-k1-20260917T161738.BDD",
        "file_size_bytes": MEASURED_SIZE_BYTES,
        "expected_size_bytes": 97_164,
    }
    fields.update(overrides)
    return SweepPointRecord(**fields)  # type: ignore[arg-type]


def _header() -> SweepLogHeader:
    definition = SweepDefinition(
        sound_speed_ms=1460.0,
        first_gate_mm=2.0,
        target_depth_mm=100.0,
        duration_s=4.0,
        rungs=(1, 2),
        prf_us=200.0,
    )
    return SweepLogHeader.from_definition(
        "20260917T161738", definition, RecordSettings(name_prefix="sw100")
    )


# --------------------------------------------------------------- decoded block


def test_decoded_block_derives_the_achieved_resolution_from_the_rung_index() -> None:
    """Word 10 is the 0-based rung index: ``(index + 1) x c / 12000``."""
    rig = DecodedBlock(channel=1, n_gates=805, resolution_index=4, sound_speed_ms=1460)
    simulated = DecodedBlock(channel=1, n_gates=100, resolution_index=1, sound_speed_ms=1500)
    assert rig.achieved_resolution_mm == pytest.approx(0.6083333, abs=1e-6)
    assert simulated.achieved_resolution_mm == pytest.approx(0.25)


def test_decoded_block_without_the_words_cannot_derive_a_resolution() -> None:
    assert DecodedBlock(channel=1, n_gates=100).achieved_resolution_mm is None


def test_decoded_block_reports_prf_in_the_gui_unit_and_in_hz() -> None:
    """PRF is a period in us in this application (docs/07 §4 item 4)."""
    block = DecodedBlock(channel=1, n_gates=805, prf_us=200.0)
    assert block.prf_hz == pytest.approx(5000.0)
    assert DecodedBlock(channel=1, n_gates=805).prf_hz is None


def test_decoded_block_requires_a_channel_and_a_gate_count() -> None:
    with pytest.raises(ValueError):
        DecodedBlock(channel=0, n_gates=805)
    with pytest.raises(ValueError):
        DecodedBlock(channel=1, n_gates=0)


def test_decoded_block_can_be_built_from_a_word_mapping() -> None:
    """The reader may grow words freely without breaking a log write."""
    block = DecodedBlock.from_mapping(
        {
            "channel": 1,
            "n_gates": 805,
            "depth_mm": 100,
            "resolution_index": 0,
            "sound_speed_ms": 1460,
            "emissions_per_profile": 44,
            "some_future_word": 12,
        }
    )
    assert block.n_gates == 805
    assert block.depth_mm == 100
    assert block.emissions_per_profile == 44
    assert not hasattr(block, "some_future_word")


# -------------------------------------------------------------- size signature


def test_size_signature_matches_the_measured_points() -> None:
    """The old 805-gate points are 79 and 78 structural BDD blocks exactly."""
    signature = SizeSignature()
    assert signature.expected_bytes(805, 79) == MEASURED_SIZE_BYTES
    assert signature.expected_bytes(805, 78) == MEASURED_SIZE_BYTES_ALT
    # The pre-recording estimate used ~71 profiles; its deliberately gross factor accepts
    # the achieved 78-79 without learning the answer from the file under test.
    assert signature.matches(MEASURED_SIZE_BYTES, 805, 71) is True
    assert signature.matches(MEASURED_SIZE_BYTES_ALT, 805, 71) is True
    assert signature.ratio(MEASURED_SIZE_BYTES, 805, 71) == pytest.approx(1.0721, abs=1e-4)


def test_size_signature_includes_the_bdd_container_at_low_profile_counts() -> None:
    """The high-emissions files are small in profiles, not truncated or contaminated.

    A BDD is not payload alone. It starts with 31,268 fixed bytes, then one depth block
    (19 + 2 bytes per gate), then one signal block per profile (19 + 1 byte per gate).
    The four live emissions-128 files are therefore 41,323 B **exactly** at their 144
    measured profiles. The nominal period predicted 155 profiles; that expectation is
    42,082 B and must accept the real file. The old ``1.7 * gates * profiles`` model
    predicted only 13,175 B and falsely rejected every point at 3.14x.
    """
    signature = SizeSignature()

    assert signature.expected_bytes(50, 144) == 41_323
    assert signature.expected_bytes(50, 155) == 42_082
    assert signature.matches(41_323, 50, 155) is True


#: Every committed pass whose recordings the size law must reproduce exactly: the
#: zero-payload first pass (2026-09-20/21) and the live pass (2026-09-21).
COMMITTED_PASS_ROOTS = ("sparse-mixer-first-pass", "sparse-mixer-live-1")


@pytest.mark.parametrize("pass_dir", COMMITTED_PASS_ROOTS)
def test_size_signature_reproduces_every_committed_point(pass_dir: str) -> None:
    """The law is exact on all 26 recordings of each committed pass, not merely close."""
    signature = SizeSignature()
    pass_root = Path(__file__).resolve().parents[1] / "data" / pass_dir
    paths = sorted(pass_root.glob("*.BDD"))
    assert len(paths) == 26

    for path in paths:
        stream = read(path).recording.streams[0]
        gates = stream.data.values.shape[1]
        profiles = len(stream.data.time_s)
        size = path.stat().st_size
        assert signature.expected_bytes(gates, profiles) == size
        assert signature.matches(size, gates, profiles) is True


def test_size_signature_rejects_the_contaminated_point() -> None:
    """A leftover recording stored as a point was 10x the signature (docs/16 §15b)."""
    signature = SizeSignature()
    assert signature.matches(CONTAMINATED_SIZE_BYTES, 805, 71) is False
    assert signature.ratio(CONTAMINATED_SIZE_BYTES, 805, 71) == pytest.approx(
        11.3765, abs=1e-3
    )


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [(50_000, True), (91_401, True), (180_000, True), (200_000, False), (45_000, False)],
)
def test_size_signature_factor_is_a_band(size_bytes: int, expected: bool) -> None:
    assert SizeSignature(factor=2.0).matches(size_bytes, 805, 71) is expected


def test_size_signature_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        SizeSignature(bytes_per_gate_profile=0.0)
    with pytest.raises(ValueError):
        SizeSignature(factor=0.5)
    with pytest.raises(ValueError, match="n_gates"):
        SizeSignature().expected_bytes(0, 71)
    with pytest.raises(ValueError, match="profiles"):
        SizeSignature().expected_bytes(805, 0)


# ---------------------------------------------------------------- log records


def test_point_record_carries_requested_readback_and_decoded() -> None:
    record = _record(
        decoded=DecodedBlock(
            channel=1,
            n_gates=805,
            depth_mm=100,
            resolution_index=0,
            sound_speed_ms=1460,
            prf_us=169,
            size_bytes=MEASURED_SIZE_BYTES,
        )
    )
    assert record.status is PointStatus.OK
    assert record.requested.gates == 805
    assert record.decoded is not None
    assert record.decoded.channel == 1


def test_point_record_decodes_the_readback_into_a_clamp_check() -> None:
    """805 requested -> 474 read back is the wrong write order's signature."""
    clamped = _record(readback_gates=474, readback_resolution="0.122")
    accepted = _record(readback_gates=403)
    assert clamped.gate_drift == pytest.approx(0.4111801242236025)
    assert clamped.gates_clamped() is True
    assert accepted.gate_drift == pytest.approx(1.0 - 403 / 805)
    assert accepted.gates_clamped() is True  # 403 for an 805 request *is* a move
    assert _record(readback_gates=805).gates_clamped() is False
    assert _record(readback_gates=None).gate_drift is None


def test_point_record_size_check_is_none_when_unchecked() -> None:
    """``None`` means unchecked, never "fine"."""
    unchecked = _record(file_size_bytes=None, expected_size_bytes=None)
    assert unchecked.size_ratio is None
    assert unchecked.size_is_plausible() is None
    assert _record().size_is_plausible() is True
    assert _record(file_size_bytes=CONTAMINATED_SIZE_BYTES).size_is_plausible() is False
    assert (
        _record(file_size_bytes=CONTAMINATED_SIZE_BYTES).size_is_plausible(
            SizeSignature(factor=20.0)
        )
        is True
    )


def test_point_record_round_trips_through_json() -> None:
    record = _record()
    assert SweepPointRecord.model_validate_json(record.model_dump_json()) == record


def test_point_record_rejects_an_unknown_field() -> None:
    with pytest.raises(ValueError):
        _record(profile_period_s=0.0212)


def test_point_status_values_are_the_logged_strings() -> None:
    assert [status.value for status in PointStatus] == ["ok", "failed", "invalid"]


def test_log_header_describes_the_sweep_from_its_definition() -> None:
    header = _header()
    assert header.sound_speed_ms == 1460.0
    assert header.first_gate_mm == 2.0
    assert header.target_depth_mm == 100.0
    assert header.rungs == (1, 2)
    assert header.name_prefix == "sw100"
    assert header.capture_dir == "capture"
    assert header.model_validate_json(header.model_dump_json()) == header


def test_sweep_id_is_timestamp_shaped() -> None:
    """Local wall-clock of the moment it is given; no offset is encoded."""
    moment = datetime(2026, 9, 17, 16, 17, 38, tzinfo=UTC)
    earlier = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert sweep_id_for(moment) == "20260917T161738"
    assert sweep_id_for(earlier) == "20260102T030405"


# ------------------------------------------------------------ JSONL round trip


def test_entries_append_and_read_back_in_order(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "sweep.jsonl"
    append_entry(path, _header())
    append_entry(path, _record(key=1))
    append_entry(
        path,
        _record(key=2, status=PointStatus.INVALID, failure="size off signature"),
    )
    entries = read_entries(path)
    assert isinstance(entries[0], SweepLogHeader)
    assert [entry.key for entry in entries[1:]] == [1, 2]
    assert entries[2].status is PointStatus.INVALID
    assert entries[2].failure == "size off signature"


def test_log_is_one_json_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "sweep.jsonl"
    append_entry(path, _header())
    append_entry(path, _record())
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["record_type"] for line in lines] == ["sweep", "point"]


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "sweep.jsonl"
    append_entry(path, _header())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n   \n")
    append_entry(path, _record())
    assert len(read_entries(path)) == 2


def test_a_malformed_line_raises_rather_than_being_guessed_at(tmp_path: Path) -> None:
    path = tmp_path / "sweep.jsonl"
    append_entry(path, _header())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"record_type": "point", "key": 1}\n')
    with pytest.raises(ValueError):
        read_entries(path)


def test_reading_a_missing_log_says_so(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_entries(tmp_path / "absent.jsonl")


def test_point_records_and_names_are_the_resume_inputs(tmp_path: Path) -> None:
    path = tmp_path / "sweep.jsonl"
    append_entry(path, _header())
    append_entry(path, _record(key=1, name="sw100-k1-161738"))
    append_entry(path, _record(key=2, name="sw100-k2-161738"))
    entries = read_entries(path)
    assert [record.key for record in point_records(entries)] == [1, 2]
    assert point_names(entries) == frozenset({"sw100-k1-161738", "sw100-k2-161738"})
    settings = RecordSettings(name_prefix="sw100")
    assert (
        settings.next_name(1, "161738", point_names(entries)) == "sw100-k1-161738b"
    )


# ------------- the window a record has to be read against (findings 4 and 5)
#
# `timing` was carried by every record ever written and populated by none of them
# (`outputs/live/*.jsonl` holds nine records, all `target_s: null, achieved_s: null`),
# and no field said how much observation a point had bought. These synthetic cases preserve
# the model's ability to describe a short retained window without claiming that this was the
# instrument's production behavior. The completed sparse pass later retained 12.4651-12.5713 s
# for 12 s requests; the runner side is asserted against real files in `test_acquire_runner.py`.


def _windowed(**overrides: object) -> SweepPointRecord:
    """A record in the 12 s-requested / 257-profile shape the bring-up measured."""
    fields: dict[str, object] = {
        "requested_duration_s": 12.0,
        "block_cap_profiles": 257,
        "decoded": DecodedBlock(
            channel=1,
            n_gates=805,
            n_profiles=257,
            span_s=8.4,
            achieved_period_s=8.4 / 256,
            median_interval_s=0.0327,
            interval_deviation=0.02,
        ),
    }
    fields.update(overrides)
    return _record(**fields)


def test_a_wrapped_block_is_recorded_as_the_window_it_really_covers() -> None:
    """Model a synthetic case with 12 s requested and 8.4 s retained.

    This pins the model semantics, not a production-instrument claim. The synthetic block
    has 257 profiles at the cap, while the request implies ~566 of them (12 s at the
    0.0212 s law) — 2.2x what could be kept, so profiles were certainly discarded.
    """
    record = _windowed()
    assert record.requested_duration_s == 12.0
    assert record.stored_profiles == 257
    assert record.stored_span_s == 8.4
    assert record.retained_fraction == pytest.approx(0.7)
    assert record.block_at_cap is True
    assert record.expected_profiles == pytest.approx(566, abs=1)
    assert record.block_wrapped is True


def test_reaching_the_cap_without_over_production_is_not_a_wrap() -> None:
    """The boundary the earlier inference got wrong: exactly the cap, nothing beyond.

    The request is set so the plan implies exactly the cap: the block may have produced
    just that many profiles, or more and lost its earliest ones, and the stored file
    cannot tell the two apart. So the answer is `None` — "not established" — while
    `block_at_cap` still reports the fact.
    """
    record = _windowed(
        requested_duration_s=257 * 0.0212,
        decoded=DecodedBlock(channel=1, n_gates=805, n_profiles=257),
    )
    assert record.block_at_cap is True
    assert record.expected_profiles == pytest.approx(257)
    assert record.block_wrapped is None


def test_a_block_below_its_cap_did_not_wrap() -> None:
    """Below the cap nothing was discarded, whatever the request implied."""
    record = _windowed(decoded=DecodedBlock(channel=1, n_gates=805, n_profiles=256))
    assert record.block_at_cap is False
    assert record.block_wrapped is False


@pytest.mark.parametrize(
    "overrides",
    (
        {"block_cap_profiles": None},  # the cap is not in the record
        {"decoded": DecodedBlock(channel=1, n_gates=805)},  # nothing says how many
    ),
)
def test_an_unknown_cap_or_count_leaves_the_wrap_unknown(
    overrides: dict[str, object],
) -> None:
    """Unknown is `None`, never `False`: absence cannot support "it did not wrap"."""
    record = _windowed(**overrides)
    assert record.block_at_cap is None
    assert record.block_wrapped is None


@pytest.mark.parametrize(
    "overrides",
    (
        {"requested_duration_s": None},
        {"decoded": DecodedBlock(channel=1, n_gates=805, n_profiles=257)},
    ),
)
def test_the_retained_fraction_needs_both_the_request_and_the_file(
    overrides: dict[str, object],
) -> None:
    assert _windowed(**overrides).retained_fraction is None


def test_a_decode_without_profile_timestamps_reports_no_window() -> None:
    """The window fields are optional evidence: a block that lacks them has none."""
    block = DecodedBlock(channel=1, n_gates=805)
    assert block.n_profiles is None
    assert block.span_s is None
    assert block.achieved_period_s is None


def test_a_single_profile_is_a_zero_length_window() -> None:
    """One stored profile is a 0.0 s window, and offers no interval to measure."""
    block = DecodedBlock(channel=1, n_gates=805, n_profiles=1, span_s=0.0)
    assert block.span_s == 0.0
    assert block.achieved_period_s is None


def test_the_window_and_the_interval_are_two_views_of_one_measurement() -> None:
    """``span == (profiles - 1) x period`` — the invariant the full-span interval buys.

    It holds exactly, because the period *is* the span over the profile count minus one.
    A median adjacent interval would leave the two fields describing slightly different
    observations of the same recording, which is the reason `analysis/rpm.py` calibrates
    on the full span and keeps the median only as a diagnostic.
    """
    decoded = _windowed().decoded
    assert decoded is not None
    assert decoded.n_profiles is not None
    assert decoded.span_s is not None
    assert decoded.achieved_period_s is not None
    assert decoded.achieved_period_s == pytest.approx(
        decoded.span_s / (decoded.n_profiles - 1)
    )
    assert decoded.span_s == pytest.approx(
        (decoded.n_profiles - 1) * decoded.achieved_period_s
    )
    # The diagnostic is not the period: this record's median differs from its interval.
    assert decoded.median_interval_s != decoded.achieved_period_s
    assert decoded.interval_deviation is not None and decoded.interval_deviation > 0


# ------------------------------- the job boundary's own record (a verified burst mutation)
#
# The boundary's write (`campaign._transit_burst_length`) is real the moment the application
# accepts it, while the manifest that used to be its only record is written at the *end* of the
# invocation — so an invocation refused in between (a compile refusal, a resume-identity refusal)
# lost the record of a mutation that happened. The log is append-only and already per-job, so the
# verified transition is appended there at the boundary (docs/dop3000/failed-invocation-provenance.md
# §O4/§5.1). These cases pin the record itself: what it carries, that it is an *occurrence* and
# never a content key, that every existing reader of the union ignores it, and that a type this
# build does not know refuses the whole log instead of being read past.


def _transition(*, before: str = "10", requested: int = 18) -> BurstWriteResult:
    """One verified transition's evidence, as the driver returns it."""
    return BurstWriteResult(
        requested_burst=requested,
        state=BurstState.VERIFIED,
        channel="1",
        before_burst=ComboReading(text=before),
        after_burst=ComboReading(text=str(requested)),
        after_sampling_volume=ComboReading(text="1.460"),
    )


def _column_result(**overrides: object) -> ColumnWriteResult:
    """One column transition's evidence: read 20, asked for 64, read back 64."""
    fields: dict[str, object] = {
        "role": ParamRole.EMISSIONS_PER_PROFILE,
        "requested": "64",
        "state": WriteState.VERIFIED,
        "before": "20",
        "write_readback": "64",
        "after": "64",
    }
    fields.update(overrides)
    return ColumnWriteResult(**fields)  # type: ignore[arg-type]


def _mutation(**overrides: object) -> SweepParameterMutation:
    """One burst-backed parameter mutation, written the way the job boundary appends it."""
    fields: dict[str, object] = {
        "parameter": "burst_length",
        "mutation_id": "9f2c1a4e5b6d708192a3b4c5d6e7f809",
        "occurred_at": datetime(2026, 9, 25, 11, 59, 30, tzinfo=UTC),
        "job": "test-single-channel",
        "fingerprint": "a" * 64,
        "routed_channel": 1,
        "evidence": _transition(),
    }
    fields.update(overrides)
    return SweepParameterMutation(**fields)  # type: ignore[arg-type]


def _column_mutation(**overrides: object) -> SweepParameterMutation:
    """The same record for the **column** surface: a second parameter, one entry type."""
    fields: dict[str, object] = {
        "parameter": ParamRole.EMISSIONS_PER_PROFILE.value,
        "mutation_id": "2b3c4d5e6f708192a3b4c5d6e7f80910",
        "occurred_at": datetime(2026, 9, 25, 12, 1, tzinfo=UTC),
        "job": "test-single-channel",
        "fingerprint": "a" * 64,
        "routed_channel": 1,
        "evidence": _column_result(),
    }
    fields.update(overrides)
    return SweepParameterMutation(**fields)  # type: ignore[arg-type]


def test_a_parameter_mutation_round_trips_through_the_log(tmp_path: Path) -> None:
    """The write's evidence survives the file — request, state and both rows on both sides.

    The record is the durable half of the mutation, so it carries the driver's own
    :class:`BurstWriteResult` rather than a boolean: a later reader has to be able to say *what*
    the boundary wrote and what the application answered, with no instrument in front of them.
    """
    path = tmp_path / "job.jsonl"
    entry = _mutation()
    append_entry(path, _header())
    append_entry(path, entry)

    entries = read_entries(path)
    assert len(entries) == 2
    assert isinstance(entries[1], SweepParameterMutation)
    read_back = entries[1]
    assert read_back == entry
    assert read_back.parameter == "burst_length"
    assert read_back.mutation_id == "9f2c1a4e5b6d708192a3b4c5d6e7f809"
    assert read_back.occurred_at == datetime(2026, 9, 25, 11, 59, 30, tzinfo=UTC)
    assert read_back.job == "test-single-channel"
    assert read_back.fingerprint == "a" * 64
    assert read_back.routed_channel == 1
    assert read_back.evidence == entry.evidence
    assert read_back.state is WriteState.VERIFIED
    # The generic answer is derived from the evidence, so the record stores one copy of each value
    # and a reader that does not know what a burst is can still ask what moved.
    assert read_back.before == "10"
    assert read_back.requested == "18"
    assert read_back.verified == "18"
    assert read_back.dependent is not None
    assert read_back.dependent.name == "sampling_volume"
    assert read_back.dependent.after == "1.460"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[1])["record_type"] == "parameter_mutation"


def test_a_column_mutation_is_the_same_record_with_its_own_evidence(tmp_path: Path) -> None:
    """The second surface uses the same entry, tag and accessor — only the payload differs.

    This is the generalisation the record exists for (review decisions 1 and 2): a reader that
    knows how to fold a burst mutation folds an emissions one without learning anything new, and
    the parameter-specific half stays typed rather than becoming text.
    """
    path = tmp_path / "job.jsonl"
    entry = _column_mutation()
    append_entry(path, _header())
    append_entry(path, entry)

    read_back = parameter_mutations(read_entries(path))[0]
    assert read_back.parameter == "emissions_per_profile"
    assert read_back.evidence == _column_result()
    assert read_back.before == "20"
    assert read_back.requested == "64"
    assert read_back.verified == "64"
    assert read_back.state is WriteState.VERIFIED
    # No dependent row moved, and ``None`` says exactly that rather than "read as empty".
    assert read_back.dependent is None


def test_the_parameter_tag_cannot_disagree_with_the_evidence() -> None:
    """The tag and the payload are one answer to "what moved", so a mismatch is refused.

    The check is against each evidence's own parameter: a column role's value *is* its fact name,
    and the burst evidence names no parameter of its own (its row is the burst row by binding).
    """
    with pytest.raises(ValueError) as excinfo:
        _mutation(parameter="emissions_per_profile")
    assert "burst_length" in str(excinfo.value), excinfo.value

    with pytest.raises(ValueError) as excinfo:
        _column_mutation(parameter="burst_length")
    assert "emissions_per_profile" in str(excinfo.value), excinfo.value


def test_two_identical_mutations_are_two_records_and_are_not_collapsed() -> None:
    """The occurrence is the record's own ``mutation_id``, minted per append — never its content.

    ``10 -> 18`` twice is one content and **two** events, and the identity in the log has to
    survive that: a reader keyed on the transition's content would fold the second write into the
    first and lose a real mutation.
    """
    first = _mutation(mutation_id="0" * 32)
    second = _mutation(
        mutation_id="1" * 32, occurred_at=datetime(2026, 9, 25, 12, 5, tzinfo=UTC)
    )

    assert first.evidence == second.evidence, "the premise: the two writes are identical"
    assert first.mutation_id != second.mutation_id
    assert first.occurred_at is not None and second.occurred_at is not None
    assert first.occurred_at < second.occurred_at, "elapsed time is what orders them"
    assert first != second


def test_a_parameter_mutation_needs_an_occurrence_identity() -> None:
    """``mutation_id`` is the identity, so an empty one is not a record of an event.

    ``None`` is the one other accepted value, and it means something specific: an entry migrated
    from a manifest written before this record existed, where no identity was ever minted.
    """
    with pytest.raises(ValueError):
        _mutation(mutation_id="")


def test_point_records_and_names_ignore_a_parameter_mutation(tmp_path: Path) -> None:
    """Every existing reader of the union has to ignore the new member, untouched.

    ``point_records`` and ``point_names`` are the resume's own inputs
    (``campaign.recorded_points`` reads them), and a mutation record is neither a point nor a
    name — the log's readers gain a type, not a behaviour.
    """
    path = tmp_path / "job.jsonl"
    record = _record(key=1, name="sw100-k1-161738")
    append_entry(path, _header())
    append_entry(path, _mutation())
    append_entry(path, record)

    entries = read_entries(path)
    assert len(entries) == 3
    assert point_records(entries) == (record,)
    assert point_names(entries) == frozenset({"sw100-k1-161738"})
    assert parameter_mutations(entries) == (_mutation(),)
    assert point_records(parameter_mutations(entries)) == ()


def test_a_record_type_the_build_does_not_know_refuses_the_log(tmp_path: Path) -> None:
    """An unknown entry type is a refusal, not a line to read past — the chosen policy.

    Acquisition logs are forward-schema: a newer build may write an entry this one cannot
    understand, and an older checkout that *skipped* it while resuming would answer questions
    about a history it had silently shortened (a mutation above all). So the whole log is
    refused, and the refusal names the file, the line and the type it declared.

    The burst slice's own tag is one of the types this build no longer knows: the record
    generalised **before** that branch merged, so no released build ever wrote one and there is
    no migration to write for it — while a log line whose meaning this build cannot state is
    exactly what must not be read past.
    """
    path = tmp_path / "job.jsonl"
    append_entry(path, _header())
    append_entry(path, _mutation())
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"record_type": "burst_mutation_v2", "mutation_id": "x"}\n')
    append_entry(path, _record())

    with pytest.raises(ValueError) as excinfo:
        read_entries(path)

    message = str(excinfo.value)
    assert "burst_mutation_v2" in message, message
    assert "line 3" in message, message
    assert path.name in message, message
    # ... and the refusal says which types *are* known, so an operator can tell an unknown record
    # from a damaged one.
    assert all(record_type in message for record_type in KNOWN_RECORD_TYPES), message


def test_a_damaged_record_of_a_known_type_refuses_the_log_too(tmp_path: Path) -> None:
    """A known type is not read *partially* either: a body that cannot be parsed refuses the log."""
    path = tmp_path / "job.jsonl"
    path.write_text(
        '{"record_type": "parameter_mutation", "mutation_id": "x"}\n', encoding="utf-8"
    )

    with pytest.raises(ValueError) as excinfo:
        read_entries(path)

    message = str(excinfo.value)
    assert "parameter_mutation" in message, message
    assert "line 1" in message, message


def test_a_line_that_is_not_a_record_at_all_refuses_the_log(tmp_path: Path) -> None:
    """Neither a non-object JSON line nor a non-JSON line is read past — both refuse the log."""
    path = tmp_path / "job.jsonl"
    path.write_text('"just a string"\n', encoding="utf-8")
    with pytest.raises(TypeError) as excinfo:
        read_entries(path)
    assert "line 1" in str(excinfo.value), excinfo.value

    path.write_text("not json at all\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        read_entries(path)
    assert "line 1" in str(excinfo.value), excinfo.value


def test_the_known_types_are_the_ones_the_models_declare() -> None:
    """The known list is the union's own, so a member added without it would refuse a valid log."""
    declared = {
        SweepLogHeader.model_fields["record_type"].default,
        SweepPointRecord.model_fields["record_type"].default,
        SweepParameterMutation.model_fields["record_type"].default,
    }
    assert declared == set(KNOWN_RECORD_TYPES)


def test_a_manifest_written_before_the_record_existed_migrates(tmp_path: Path) -> None:
    """An older manifest's ``burst_transitions`` reads as what it always was: parameter mutations.

    The record generalized before the burst branch merged, so the *log* has no legacy shape to
    read. A job manifest does: ``burst_transitions`` shipped in the B5 slice and is what a resume
    of an already-run job on this machine will find. Reading forwards costs these few lines once,
    and refusing it would strand every pass recorded before the rename.
    """
    legacy_manifest = {
        "job": "burst-20",
        "fingerprint": "b" * 64,
        "burst_transitions": [
            _transition().model_dump(mode="json"),
            _transition(requested=20, before="18").model_dump(mode="json"),
        ],
        "planned": {"points": 1},
    }

    migrated = migrate_legacy_burst_history(legacy_manifest)

    assert isinstance(migrated, dict)
    assert LEGACY_BURST_HISTORY_KEY not in migrated, "the key is read, never carried forwards"
    assert migrated["planned"] == {"points": 1}, "everything else rides through untouched"
    history = migrated["parameter_mutations"]
    assert [entry["parameter"] for entry in history] == ["burst_length", "burst_length"]
    assert history[0]["job"] == "burst-20", "the job and fingerprint come from the record itself"
    assert history[0]["fingerprint"] == "b" * 64
    assert history[0]["evidence"] == _transition().model_dump(mode="json")
    # Nothing that was never recorded is invented for these entries: no identity, no timestamp, no
    # routing answer — the reader's own defaults are the whole statement about them.
    read_entries_back = [
        SweepParameterMutation.model_validate(entry) for entry in history
    ]
    assert [entry.mutation_id for entry in read_entries_back] == [None, None]
    assert [entry.occurred_at for entry in read_entries_back] == [None, None]
    assert [entry.routed_channel for entry in read_entries_back] == [None, None]
    # The payload stays typed, so the sampling-volume evidence survives the migration.
    first = read_entries_back[0]
    assert first.requested == "18"
    assert first.verified == "18"
    assert first.state is WriteState.VERIFIED
    assert first.dependent is not None and first.dependent.after == "1.460"
    assert read_entries_back[1].before == "18", "the second entry's own sides survive too"


def test_migration_leaves_everything_it_does_not_own_alone() -> None:
    """A payload with no legacy key — and one that is not a payload at all — is returned as given."""
    payload = {"job": "burst-20", "parameter_mutations": [{"parameter": "burst_length"}]}
    assert migrate_legacy_burst_history(payload) is payload

    modern = {"job": "burst-20", "burst_transitions": [], "parameter_mutations": []}
    migrated = migrate_legacy_burst_history(modern)
    assert isinstance(migrated, dict)
    assert "burst_transitions" not in migrated, "the legacy key is dropped either way"
    assert migrated["parameter_mutations"] == [], "and the new field is the authority"

    assert migrate_legacy_burst_history("not a payload") == "not a payload"
