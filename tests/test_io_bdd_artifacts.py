"""Phase 6 BDD-reader artifact tests: the migrated reader returns a bundle.

Plan §6.5–§6.7, §7.1, §8.1, §10.7 (the binary footer), §11, §12.2, §13.
Every numeric decode assertion that lived in ``tests/test_io_bdd.py`` is
re-expressed here against the migrated ``ArtifactBundle`` return value before
that legacy file is touched.

Decoded format facts (measured on the committed fixtures, cross-checked against
the DOP3000-3010 manual reference):

* ``data/echo/*.BDD`` — single-sensor echo, one channel ``device_channel=4``.
  ``200.BDD``: ``T=4180``, ``G=26``, canonical (calculated) gate 0 at
  ``42.972 mm`` with pitch ``0.4567 mm`` — the matching ``200.ADD`` depth row
  reads ``42.97 … 54.39`` (rounded to 0.01 mm) and the stored pseudo-profile
  reads ``43.0 … 54.4`` (rounded to 0.1 mm) — ``module_scale=2048``,
  ``sound_speed_ms=2740``, ``trigger_delay_ms=0``, every value finite and in
  ``[0, 2048]``, per-interval ``dt`` in ``{3.1, 3.2} ms``.
  The op-parameter multiplexer-enable bit (word 52, bit index 0 = value ``1``;
  the manual numbers row 52's bits 1-based, so this is its "bit 1"; manual
  ``10-storing-and-reading-measures.md`` §"DOP3000 parameters table", row 52) is
  **clear**, so non-multiplexed operation; the file proves no cross-channel
  acquisition topology.
* ``data/4-sensor-velocity/*.BDD`` — 4-channel velocity, channels
  ``6,7,8,9``. Each ``T=400``, ``G=55``, canonical gate 0 at ``20.002 mm``
  (pitch ``1.095 mm``; ``.ADD`` row ``20.00 … 79.13``, stored profile
  ``20.0 … 79.1``), ``sound_speed_ms=1460``, all finite. The multiplexer-enable
  bit (index 0) is **set** (word 52 = ``0x261e03``, which sets both index 0 and
  index 1 — the manual's "bit 2: UDV MD mode"), word 51 ("Nb profiles in block
  in multiplexer mode", row 51) = ``4``, word 53 ("Nb blocks in multiplexer
  mode", row 53) = ``100``.
* The per-profile footer (manual ``10-storing-and-reading-measures.md`` §10.7,
  points E–K) carries the timestamp (E, 4 bytes at ``meas_end-12``) and the
  block number (F, 2 bytes at ``meas_end-8``) and the multiplexer channel (J,
  1 byte at ``meas_end-3``). Measured: the block number spans ``1..100`` exactly
  matching word 53, and each channel appears once per block with four contiguous
  profiles matching word 51.

Those decoded facts are why ``200RPM.BDD`` is ``AcquisitionMode.SEQUENTIAL``
(the documented multiplexer-enable parameter proves channels were switched one
after another; ``ROLLING`` is *not* provable because roll-over is a runtime
option, not a stored field) and ``200.BDD`` is ``AcquisitionMode.UNKNOWN``.

The footer block number and the word-51/word-53 counts are recorded here as
*measured evidence only*: the format documents them as a "block"/"sequence"
number and a profile count, not as a round/visit identity, and the plan forbids
deriving ``round_id``/``visit_id``/``profile_in_visit`` from block order or from
the footer word. So no fixture fabricates them; the reader emits no index
topology and ``acquisition_order`` stays ``None``. The exact missing format fact
is asserted by ``test_block_number_pattern_is_measured_but_not_fabricated`` so a
later phase can revisit it without re-deriving it.
"""

from __future__ import annotations

import hashlib
import struct
from collections import Counter
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.io import load
from udv_echo_process.io.dop.bdd import read
from udv_echo_process.models import (
    AcquisitionMode,
    ChannelKey,
    SignalQuantity,
    SupportKind,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.provenance import ArtifactBundle, ChannelBundle, select_channel

DATA = Path("data")
ECHO = DATA / "echo"
VEL = DATA / "4-sensor-velocity"

ECHO_200 = ECHO / "200.BDD"
ECHO_650 = ECHO / "650.BDD"
FOUR_SENSOR = VEL / "200RPM.BDD"
FOUR_SENSOR_V2 = VEL / "200RPM_v2.BDD"

_OBSERVED = int(SupportKind.OBSERVED)

#: Start of the measurement-block chain (manual §10.7 "A block that contains
#: the values of the data profiles", offset 31268).
_MEAS_BASE_OFFSET = 31268


def _channel(bundle: ArtifactBundle, device_channel: int) -> ChannelBundle:
    return select_channel(bundle, ChannelKey(device_channel=device_channel))


def _footer_rows(path: Path) -> list[tuple[int, int, int]]:
    """Walk the block chain and return the documented footer fields.

    ``(multiplexer channel, block number, timestamp)`` read at the manual's
    per-profile footer offsets (point F = block word at ``meas_end-8``, point J
    = channel byte at ``meas_end-3``, point E = timestamp at ``meas_end-12``;
    ``10-storing-and-reading-measures.md`` §10.7). Deliberately independent of
    the reader under test.
    """
    raw = path.read_bytes()
    start = _MEAS_BASE_OFFSET
    eof = len(raw)
    rows: list[tuple[int, int, int]] = []
    while start + 4 <= eof:
        length = struct.unpack_from("<H", raw, start)[0]
        end = start + length
        if length == 0 or end > eof:
            break
        timestamp = struct.unpack_from("<I", raw, end - 12)[0]
        block = struct.unpack_from("<H", raw, end - 8)[0]
        channel = raw[end - 3]
        rows.append((channel, block, timestamp))
        start = end
    return rows


def _synthetic_single_channel_bdd(mux_flags: int, gates: int = 2) -> bytes:
    """Build a minimal single-channel echo ``.BDD`` carrying only what the reader
    needs: the magic, op-param word 52 for channel 1, and one measurement block
    holding an echo profile, a depth pseudo-profile and a footer.

    Deliberately independent of the reader under test — the op-param block is
    otherwise zero (so the gate-depth calculation is undecodable and the file's
    depth pseudo-profile is the canonical axis), which isolates the mux word.
    """
    raw = bytearray(_MEAS_BASE_OFFSET)
    raw[0:8] = b"BINUDOPV"
    struct.pack_into("<i", raw, 548 + 4 * 52, mux_flags)  # channel 1 op word 52

    echo = bytes(range(1, gates + 1))  # uint8 echo counts
    depth = struct.pack(f"<{gates}h", *(430 + 10 * i for i in range(gates)))

    def profile(ptype: int, payload: bytes) -> bytes:
        return struct.pack("<H", len(payload)) + bytes([ptype]) + payload

    body = profile(1, echo) + profile(25, depth) + b"\x00\x00"
    footer = bytearray(16)
    struct.pack_into("<I", footer, 4, 0)  # timestamp at meas_end-12
    footer[13] = 1  # channel byte at meas_end-3
    block = body + bytes(footer)
    raw += struct.pack("<H", 2 + len(block)) + block
    return bytes(raw)


# ── content identity ───────────────────────────────────────────────────


@pytest.mark.parametrize("path", [ECHO_200, ECHO_650, FOUR_SENSOR, FOUR_SENSOR_V2])
def test_source_asset_identity_is_the_content_sha256(path):
    bundle = read(path)
    asset = bundle.recording.source_asset
    expected_hex = hashlib.sha256(path.read_bytes()).hexdigest()
    assert asset.content_sha256 == expected_hex
    assert asset.asset_id == f"sha256:{expected_hex}"
    assert asset.byte_size == path.stat().st_size
    assert asset.file_name == path.name
    assert asset.content_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("path", [ECHO_200, FOUR_SENSOR])
def test_recording_and_artifact_ids_are_deterministic(path):
    first = read(path)
    second = read(path)
    assert first.recording.recording_id == second.recording.recording_id
    assert first.recording.recording_id == recording_id_for(
        first.recording.source_asset.asset_id
    )
    assert [s.artifact_id for s in first.recording.streams] == [
        s.artifact_id for s in second.recording.streams
    ]
    assert first.graph.root_artifacts == second.graph.root_artifacts


# ── single-channel echo ────────────────────────────────────────────────


class TestSingleChannelEcho:
    def test_channel_descriptor_shape_and_gates(self):
        bundle = read(ECHO_200)
        assert isinstance(bundle, ArtifactBundle)
        assert len(bundle.recording.streams) == 1
        stream = bundle.recording.streams[0]
        assert stream.acquisition.channel == ChannelKey(device_channel=4)
        assert stream.descriptor.quantity is SignalQuantity.ECHO_AMPLITUDE
        assert stream.descriptor.unit == "module"
        data = stream.data
        assert data.values.shape == (4180, 26)
        assert data.time_s.shape == (4180,)
        assert data.gate_depths_mm.shape == (26,)
        assert data.gate_depths_mm[0] == pytest.approx(43.0, abs=0.1)
        assert data.gate_depths_mm[-1] == pytest.approx(54.4, abs=0.1)

    def test_config_matches_the_op_parameter_block(self):
        bundle = read(ECHO_200)
        config = bundle.recording.streams[0].config
        assert config.module_scale == 2048
        assert config.sound_speed_ms == pytest.approx(2740, abs=1)
        assert config.trigger_delay_ms == pytest.approx(0.0)
        assert config.n_gates == 26
        assert config.gate1_mm == pytest.approx(43.0, abs=0.1)

    def test_time_is_strictly_increasing_with_the_measured_cadence(self):
        data = read(ECHO_650).recording.streams[0].data
        assert np.all(np.diff(data.time_s) > 0)

    def test_decoded_cadence_is_the_measured_3_1_3_2_ms(self):
        data = read(ECHO_200).recording.streams[0].data
        steps_ms = np.round(np.diff(data.time_s) * 1e3, 4)
        assert set(np.unique(steps_ms).tolist()) == {3.1, 3.2}

    def test_every_decoded_value_is_observed_and_quality_none(self):
        data = read(ECHO_200).recording.streams[0].data
        assert np.isfinite(data.values).all()
        assert np.array_equal(
            data.support.kind, np.full(data.values.shape, _OBSERVED, np.uint8)
        )
        assert data.support.valid.all()
        assert not data.support.quality.any()

    def test_topology_is_unknown_and_no_index_is_fabricated(self):
        """The non-multiplexed file proves no round/visit: no fabricated ids.

        Measured (independent footer walk): all 4181 blocks of ``200.BDD`` carry
        the constant footer block word ``1`` (manual point F, ``meas_end-8``)
        and channel ``4``, and the op-param multiplexer-enable bit (word 52,
        bit index 0, the manual's 1-based "bit 1") is clear. Neither a constant
        block word nor the one-channel count proves an acquisition mode or a
        visit order, so the reader emits ``UNKNOWN`` and leaves round/visit as
        ``None``.
        """
        rows = _footer_rows(ECHO_200)
        assert len(rows) == 4181
        assert {channel for channel, _, _ in rows} == {4}
        assert {block for _, block, _ in rows} == {1}

        bundle = read(ECHO_200)
        assert bundle.recording.acquisition_mode is AcquisitionMode.UNKNOWN
        assert bundle.recording.acquisition_order is None
        index = bundle.recording.streams[0].data.acquisition
        assert index is not None
        assert index.round_id is None
        assert index.visit_id is None
        assert index.profile_in_visit is None

    def test_acquisition_index_links_every_row(self):
        data = read(ECHO_200).recording.streams[0].data
        index = data.acquisition
        assert index is not None
        assert index.sample_id.tolist() == list(range(4180))
        assert np.array_equal(index.acquisition_time_s, data.time_s)


# ── four-channel multiplexed velocity ──────────────────────────────────


class TestFourChannelVelocity:
    def test_channels_descriptor_and_gates(self):
        bundle = read(FOUR_SENSOR)
        assert len(bundle.recording.streams) == 4
        assert {
            s.acquisition.channel.device_channel for s in bundle.recording.streams
        } == {
            6,
            7,
            8,
            9,
        }
        for stream in bundle.recording.streams:
            assert stream.descriptor.quantity is SignalQuantity.AXIAL_VELOCITY
            assert stream.descriptor.unit == "mm/s"
            data = stream.data
            assert data.values.shape == (400, 55)
            assert data.gate_depths_mm[0] == pytest.approx(20.0, abs=0.1)
            assert data.gate_depths_mm[-1] == pytest.approx(79.1, abs=0.1)
            pitch = np.diff(data.gate_depths_mm).mean()
            assert pitch == pytest.approx(1.0944, abs=0.01)
            assert np.isfinite(data.values).all()
            assert np.all(np.diff(data.time_s) > 0)

    def test_config_and_nyquist_velocity(self):
        bundle = read(FOUR_SENSOR_V2)
        for stream in bundle.recording.streams:
            assert stream.config.sound_speed_ms == pytest.approx(1460, abs=1)
            assert stream.config.velo_max_ms is not None

    def test_staggered_start_times(self):
        bundle = read(FOUR_SENSOR)
        starts = [s.data.time_s[0] for s in bundle.recording.streams]
        assert starts[0] == pytest.approx(0.0, abs=1e-3)
        for earlier, later in pairwise(starts):
            assert (later - earlier) > 0.05

    def test_every_decoded_value_is_observed_and_quality_none(self):
        for stream in read(FOUR_SENSOR).recording.streams:
            assert np.array_equal(
                stream.data.support.kind,
                np.full(stream.data.values.shape, _OBSERVED, np.uint8),
            )
            assert stream.data.support.valid.all()
            assert not stream.data.support.quality.any()

    def test_mode_is_sequential_from_the_decoded_multiplexer_bit(self):
        """Mode comes from the documented multiplexer parameter, not stream count.

        The multiplexer-enable bit is word 52 bit index 0 (the manual's 1-based
        "bit 1", "if set multiplexer enables", §10.7 parameters table row 52)
        and is set for every channel (``0x261e03``), and §11 documents that
        multiplexed acquisition selects each channel's profiles one after
        another, so the channels were acquired sequentially.
        """
        bundle = read(FOUR_SENSOR)
        assert bundle.recording.acquisition_mode is AcquisitionMode.SEQUENTIAL
        # no acquisition order is fabricated: the format declares no such field
        assert bundle.recording.acquisition_order is None

    def test_block_number_pattern_is_measured_but_not_fabricated(self):
        """Decode the footer block number, then prove the reader invents none.

        Measured (independent footer walk): ``200RPM.BDD`` has 1604 blocks, four
        depth pseudo-profiles (channels 6–9) then 1600 signal profiles; the
        footer block word (manual point F, ``meas_end-8``) spans ``1..100``
        exactly matching word 53 ("Nb blocks in multiplexer mode"), and each
        channel acquires four contiguous profiles per block matching word 51
        ("Nb profiles in block in multiplexer mode"). This is *evidence*, not a
        proven round/visit identity — the format stores no such field — so the
        reader records none.
        """
        rows = _footer_rows(FOUR_SENSOR)
        assert len(rows) == 1604
        # the first four blocks are the per-channel depth pseudo-profiles
        assert [channel for channel, _, _ in rows[:4]] == [6, 7, 8, 9]
        signal = rows[4:]
        assert {channel for channel, _, _ in signal} == {6, 7, 8, 9}
        blocks = sorted({block for _, block, _ in signal})
        assert blocks == list(range(1, 101))
        per_block = Counter((block, channel) for channel, block, _ in signal)
        assert set(per_block.values()) == {4}
        # channel order is stable within every block: 6,7,8,9 four times each
        for block in (1, 50, 100):
            order = [channel for channel, b, _ in signal if b == block]
            assert order == [6, 6, 6, 6, 7, 7, 7, 7, 8, 8, 8, 8, 9, 9, 9, 9]

        for stream in read(FOUR_SENSOR).recording.streams:
            index = stream.data.acquisition
            assert index is not None
            assert index.round_id is None
            assert index.visit_id is None
            assert index.profile_in_visit is None
        assert read(FOUR_SENSOR).recording.acquisition_order is None

    def test_acquisition_index_links_every_row(self):
        for stream in read(FOUR_SENSOR).recording.streams:
            index = stream.data.acquisition
            assert index is not None
            assert index.sample_id.tolist() == list(range(400))
            assert np.array_equal(index.acquisition_time_s, stream.data.time_s)


# ── the multiplexer-enable bit is index 0, not the UDV MD flag ─────────


@pytest.mark.parametrize(
    ("mux_flags", "expected"),
    [
        (0x0, AcquisitionMode.UNKNOWN),  # no flag: nothing proves a mode
        (0x1, AcquisitionMode.SEQUENTIAL),  # manual "bit 1" = bit index 0
        (0x2, AcquisitionMode.UNKNOWN),  # manual "bit 2" = UDV MD mode, NOT mux
        (0x3, AcquisitionMode.SEQUENTIAL),  # both set (the committed mux shape)
    ],
)
def test_mux_enable_is_bit_index_zero_not_the_udv_md_flag(
    tmp_path: Path, mux_flags: int, expected: AcquisitionMode
) -> None:
    """Flag ``0x1`` (manual "bit 1") means multiplexed; ``0x2`` is UDV MD mode.

    Row 52 of the manual's parameter table numbers bits 1-based, so its "bit 1:
    if set multiplexer enables" is bit index 0 and its "bit 2: if set UDV MD
    mode" is bit index 1. DOPpy agrees (``'4m0'`` = ``multi``, ``'4m1'`` =
    ``udvmd``). A file with only ``0x2`` set is therefore *not* multiplexed and
    must stay ``UNKNOWN``; only a synthetic fixture can separate the two flags,
    because every committed multiplexer file sets both (word 52 = ``0x261e03``).
    Exercised through the public ``read`` and ``load`` entry points.
    """
    path = tmp_path / f"mux_{mux_flags:x}.BDD"
    path.write_bytes(_synthetic_single_channel_bdd(mux_flags))
    assert read(path).recording.acquisition_mode is expected
    assert load(path).recording.acquisition_mode is expected


# ── calculated canonical depths vs the matching .ADD grid ─────────────


def _add_depth_row(path: Path, channel: int) -> np.ndarray:
    """Read one ``Gate Depth [mm]`` row from a matching ``.ADD`` export.

    Sections are keyed by the channel number in the last column of their data
    rows, so the four-sensor rolling export's repeated sections map to the
    requested channel. Deliberately independent of the reader under test.
    """
    lines = path.read_text(encoding="latin-1").splitlines()
    for i, line in enumerate(lines):
        if line.strip() != "Gate Depth [mm]":
            continue
        if i + 3 >= len(lines):
            continue
        cols = lines[i + 3].split("\t")
        if cols and cols[-1].strip() == str(channel):
            row = [float(x.replace(",", ".")) for x in lines[i + 1].split("\t") if x]
            return np.array(row)
    raise AssertionError(f"no .ADD depth row for channel {channel} in {path}")


def _file_depth_profile(path: Path, channel: int) -> np.ndarray:
    """Decode the stored ``depth`` pseudo-profile (int16 / 10) for one channel.

    An independent walk of the block chain, used to re-derive the validation
    residual the reader checks internally.
    """
    raw = path.read_bytes()
    start = _MEAS_BASE_OFFSET
    eof = len(raw)
    while start + 4 <= eof:
        length = struct.unpack_from("<H", raw, start)[0]
        end = start + length
        if length == 0 or end > eof:
            break
        if raw[end - 3] == channel:
            prof = start + 2
            while True:
                plen = struct.unpack_from("<H", raw, prof)[0]
                if plen == 0:
                    break
                if raw[prof + 2] == 25:  # Data_Type_Depth_mm_10
                    return (
                        np.frombuffer(
                            raw[prof + 3 : prof + 3 + plen], dtype=np.int16
                        ).astype(float)
                        / 10.0
                    )
                prof += plen + 3
        start = end
    raise AssertionError(f"no stored depth profile for channel {channel} in {path}")


CALC_ADD_CASES = [
    (ECHO_200, 4),
    (ECHO_650, 4),
    (FOUR_SENSOR, 6),
    (FOUR_SENSOR, 7),
    (FOUR_SENSOR, 8),
    (FOUR_SENSOR, 9),
    (FOUR_SENSOR_V2, 6),
]


@pytest.mark.parametrize(("path", "channel"), CALC_ADD_CASES)
def test_calculated_depths_match_the_matching_add_depth_row(path, channel):
    """PLAN §Phase 1: calculated depths reproduce the ``.ADD`` grid ``<= 0.005``.

    The ``.ADD`` depth row is the calculated vector rounded to 0.01 mm, so the
    residual is one rounding step — far below the old 0.1 mm ``approx`` bound.
    """
    data = _channel(read(path), channel).artifact.data
    add = _add_depth_row(path.with_suffix(".ADD"), channel)
    assert data.gate_depths_mm.shape == add.shape
    residual = float(np.max(np.abs(data.gate_depths_mm - add)))
    assert residual <= 0.005, residual


def test_canonical_depths_are_calculated_not_the_file_vector():
    """The canonical axis is the calculation (42.9723...), not the file's 43.0."""
    data = read(ECHO_200).recording.streams[0].data
    # sound * (gate1/(2*rate) - hw/2e6) = 2740 * (199/12000 - 1800/2e6)
    assert data.gate_depths_mm[0] == pytest.approx(42.9723333, abs=1e-6)
    # the stored pseudo-profile would have said a flat 43.0
    assert abs(data.gate_depths_mm[0] - 43.0) > 0.02


@pytest.mark.parametrize(("path", "channel"), [(ECHO_200, 4), (FOUR_SENSOR, 6)])
def test_stored_depth_profile_validates_the_calculation(path, channel):
    """The file pseudo-profile agrees with the canonical vector to <= 0.05 mm.

    That residual is the file's 0.1 mm quantisation (a half step), which is why
    the reader keeps it as a validation input rather than the canonical axis.
    """
    calc = _channel(read(path), channel).artifact.data.gate_depths_mm
    file_depth = _file_depth_profile(path, channel)
    assert file_depth.shape == calc.shape
    assert float(np.max(np.abs(calc - file_depth))) <= 0.05


def test_canonical_depth_rule_calc_fallback_and_disagreement():
    """The documented rule's three branches, exercised directly.

    The tolerance is fixture-backed (<= 0.0497 mm on every committed file); the
    synthetic inputs below only make the fallback/dissent branches reachable
    without mutating a real recording.
    """
    from udv_echo_process.io.dop.bdd import _canonical_depth_mm

    op: dict[str, object] = {
        "gate_n": 3,
        "gate1": 199,
        "resolution": 1,
        "hardware_delay_ns": 1800,
        "sound_speed_ms": 2740,
        "aquisition_rate": (0, 6, 12, 40),
    }
    calc = _canonical_depth_mm(None, op, "x.BDD", 4)
    assert calc.shape == (3,)
    assert calc[0] == pytest.approx(42.9723333, abs=1e-6)

    # out-of-range packed index -> calculation not decodable -> file fallback
    undecodable: dict[str, object] = dict(op, aquisition_rate=(9, 6, 12, 40))
    file_depth = np.array([1.0, 2.0, 3.0])
    assert np.array_equal(
        _canonical_depth_mm(file_depth, undecodable, "x.BDD", 4), file_depth
    )
    # neither source available -> error
    with pytest.raises(ValueError, match="no decoded depth pseudo-profile"):
        _canonical_depth_mm(None, undecodable, "x.BDD", 4)
    # both present but disagreeing -> error, never a silent pick
    with pytest.raises(ValueError, match="differ from the stored depth"):
        _canonical_depth_mm(np.zeros(3), op, "x.BDD", 4)


def test_resolution_is_reconciled_with_the_calculated_gate_step():
    """One interpretation of word 10 + word 29, matching the ``.ADD`` pitch."""
    echo = read(ECHO_200).recording.streams[0]
    # word 19=2740 m/s, word 10=1, word 29=(0, 6, 12, 40) -> rate byte 6 * 1e3
    assert echo.config.resolution_mm == pytest.approx(2740 * 2 / (2 * 6000))
    assert echo.config.resolution_mm == pytest.approx(0.4566667, abs=1e-6)
    vel = _channel(read(FOUR_SENSOR), 6).artifact
    assert vel.config.resolution_mm == pytest.approx(1460 * 9 / (2 * 6000))
    assert vel.config.resolution_mm == pytest.approx(1.095, abs=1e-6)


def test_prf_word_is_a_microsecond_period_converted_to_hz():
    """Word 5 is documented as a period in µs; the field name demands Hz."""
    echo = read(ECHO_200).recording.streams[0]
    assert echo.config.pulse_repetition_freq_hz == pytest.approx(1e6 / 125)
    vel = _channel(read(FOUR_SENSOR), 6).artifact
    assert vel.config.pulse_repetition_freq_hz == pytest.approx(1e6 / 600)


def test_max_depth_is_the_last_canonical_gate():
    echo = read(ECHO_200).recording.streams[0]
    assert echo.config.gate1_mm == pytest.approx(float(echo.data.gate_depths_mm[0]))
    assert echo.config.max_depth_mm == pytest.approx(
        float(echo.data.gate_depths_mm[-1])
    )
    assert echo.config.max_depth_mm == pytest.approx(54.389, abs=1e-3)


def test_ungrounded_metadata_fields_stay_deferred():
    """``sampling_volume_mm``/``trigger_state`` have no byte-grounded formula.

    DOPpy's sampling-volume formula is flagged reverse-engineered with a
    unit-inconsistent ``max()`` (metres vs mm); the footer trigger byte's coding
    is undocumented. Neither is populated until that changes, so both stay None.
    """
    for stream in read(FOUR_SENSOR).recording.streams:
        assert stream.config.sampling_volume_mm is None
        assert stream.config.trigger_state is None


def test_canonical_depth_ids_round_trip_through_storage(tmp_path):
    """PLAN §Phase 1 step 5: stored bundles stay readable and self-consistent."""
    from udv_echo_process.storage import load_bundle, store_bundle

    bundle = read(ECHO_200)
    destination = tmp_path / "store"
    store_bundle(bundle, destination)
    loaded = load_bundle(destination)
    assert loaded.recording.recording_id == bundle.recording.recording_id
    assert [s.artifact_id for s in loaded.recording.streams] == [
        s.artifact_id for s in bundle.recording.streams
    ]
    assert np.allclose(
        loaded.recording.streams[0].data.gate_depths_mm,
        bundle.recording.streams[0].data.gate_depths_mm,
    )


# ── every fixture round-trips to a closed bundle ───────────────────────


@pytest.mark.parametrize("path", [ECHO_200, ECHO_650, FOUR_SENSOR, FOUR_SENSOR_V2])
def test_graph_holds_every_channel_artifact_as_a_root(path):
    bundle = read(path)
    roots = set(bundle.graph.root_artifacts)
    assert roots == {s.artifact_id for s in bundle.recording.streams}
    assert bundle.graph.operations == ()
    assert bundle.graph.derivations == ()
    # every stream is reachable through the plan §7.1 bridge, graph reused
    for stream in bundle.recording.streams:
        selected = _channel(bundle, stream.acquisition.channel.device_channel)
        assert selected.artifact.artifact_id in roots
        assert selected.graph is bundle.graph


@pytest.mark.parametrize("path", [ECHO_200, FOUR_SENSOR])
def test_decoded_arrays_are_owned_and_read_only(path):
    for stream in read(path).recording.streams:
        data = stream.data
        arrays = [
            data.time_s,
            data.gate_depths_mm,
            data.values,
            data.support.kind,
            data.support.valid,
            data.support.quality,
            data.acquisition.sample_id,
            data.acquisition.acquisition_time_s,
        ]
        assert data.support.kind.dtype == np.uint8
        assert data.support.valid.dtype == np.bool_
        assert data.support.quality.dtype == np.uint32
        for array in arrays:
            assert array.flags["OWNDATA"] is True
            assert array.flags["C_CONTIGUOUS"] is True
            assert array.flags["WRITEABLE"] is False


@pytest.mark.parametrize("path", [ECHO_200, FOUR_SENSOR])
def test_no_absolute_path_leaks_into_any_model(path):
    bundle = read(path)
    forbidden = (
        str(path.resolve()),
        str(path.parent),
        str(Path.cwd()),
        "/home/",
    )

    def walk(node: object) -> None:
        if isinstance(node, str):
            for needle in forbidden:
                assert needle not in node, (needle, node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, np.ndarray):
            return
        else:
            for value in vars(node).values() if hasattr(node, "__dict__") else ():
                walk(value)

    walk(bundle.recording.model_dump(mode="python"))
    walk(bundle.graph.model_dump(mode="python"))
    assert "/home/" not in bundle.graph.model_dump_json()
    assert "/home/" not in bundle.recording.source_asset.model_dump_json()
    assert bundle.recording.source_asset.file_name == path.name


@pytest.mark.parametrize("path", [ECHO_200, FOUR_SENSOR])
def test_load_and_read_agree(path):
    """``load`` (sniff + dispatch) returns the same bundle as the reader."""
    from_load = load(path)
    from_reader = read(path)
    assert isinstance(from_load, ArtifactBundle)
    assert from_load.recording.recording_id == from_reader.recording.recording_id
    assert from_load.graph.root_artifacts == from_reader.graph.root_artifacts


def test_every_discovered_fixture_round_trips_to_a_closed_bundle():
    """STOP/GO: every committed fixture yields a valid closed ``ArtifactBundle``.

    This is the phase's stated acceptance over the whole committed ``data/``
    tree (22 files today, including the genuine ``.BDD`` misnamed ``.jpg``), not
    just the two hand-picked fixtures.
    """
    from udv_echo_process.io import discover_data_files

    paths = discover_data_files(DATA)
    assert paths
    seen_modes = set()
    for path in paths:
        bundle = read(path)
        assert isinstance(bundle, ArtifactBundle)
        assert set(bundle.graph.root_artifacts) == {
            stream.artifact_id for stream in bundle.recording.streams
        }
        assert bundle.graph.operations == ()
        assert bundle.graph.derivations == ()
        assert bundle.recording.acquisition_mode in set(AcquisitionMode)
        for stream in bundle.recording.streams:
            assert (
                select_channel(bundle, stream.acquisition.channel).graph is bundle.graph
            )
        seen_modes.add(bundle.recording.acquisition_mode)
    assert {AcquisitionMode.UNKNOWN, AcquisitionMode.SEQUENTIAL} <= seen_modes
