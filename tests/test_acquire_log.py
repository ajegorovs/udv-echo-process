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

from udv_echo_process.acquire.config import (
    ParameterSet,
    ProfileTiming,
    RecordSettings,
)
from udv_echo_process.acquire.log import (
    DecodedBlock,
    PointStatus,
    SizeSignature,
    SweepLogHeader,
    SweepPointRecord,
    append_entry,
    point_names,
    point_records,
    read_entries,
    sweep_id_for,
)
from udv_echo_process.acquire.plan import SweepDefinition

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
    """805 gates over ~71 profiles: 97,993 B and 97,169 B were both real points."""
    signature = SizeSignature()
    assert signature.expected_bytes(805, 71) == 97_164
    assert signature.matches(MEASURED_SIZE_BYTES, 805, 71) is True
    assert signature.matches(MEASURED_SIZE_BYTES_ALT, 805, 71) is True
    assert signature.ratio(MEASURED_SIZE_BYTES, 805, 71) == pytest.approx(1.0085, abs=1e-4)


def test_size_signature_rejects_the_contaminated_point() -> None:
    """A leftover recording stored as a point was 10x the signature (docs/16 §15b)."""
    signature = SizeSignature()
    assert signature.matches(CONTAMINATED_SIZE_BYTES, 805, 71) is False
    assert signature.ratio(CONTAMINATED_SIZE_BYTES, 805, 71) == pytest.approx(
        10.7018, abs=1e-3
    )


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [(50_000, True), (97_164, True), (180_000, True), (200_000, False), (48_000, False)],
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
# and no field said how much observation a point had bought. The app's block is a ring:
# a 12 s request stores the last ~257 profiles (~8.4 s) and still decodes as a good
# point, so without the retained window "12 s requested" and "8.4 s stored" are the same
# record. These cases pin the model's side of it; the runner's side is asserted against
# real files in `test_acquire_runner.py`.


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
    """12 s asked for, 8.4 s retained: 0.7 of the window, at the cap, not a 12 s point."""
    record = _windowed()
    assert record.requested_duration_s == 12.0
    assert record.stored_profiles == 257
    assert record.stored_span_s == 8.4
    assert record.retained_fraction == pytest.approx(0.7)
    assert record.block_wrapped is True


def test_a_block_below_its_cap_did_not_wrap() -> None:
    record = _windowed(decoded=DecodedBlock(channel=1, n_gates=805, n_profiles=256))
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
    assert _windowed(**overrides).block_wrapped is None


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
