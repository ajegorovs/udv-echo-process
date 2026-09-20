"""Word-level pins for the `.BDD` parameter map, reconciled against an
independent decoder (recorded 2026-09-17, DOP3010 / UDOP 6.07.4).

Two independent decoders of the DOP3000/3010 operation-parameter block were
compared word by word:

* **this repo's reader** — ``udv_echo_process.io.dop.bdd`` (hand-transcribed from
  the manual's *DOP3000 parameters table*, see ``docs/dop3000/manual-reference/
  10-storing-and-reading-measures.md`` §10.7, cross-checked against the DOPpy
  reference reader);
* an **independent recon decoder** written during a live instrument-side session
  against the same format (vendored into this repo as
  ``docs/dop3000/udop-automation.md`` §9, which carries the map that session
  pinned against a labelled UI point).

The comparison found **no word on which the two decoders disagree in value**:
every label-pinned word in that map is decoded identically here. The pins below
hold that map down against two real captures, so a future change to the reader
that breaks it fails loudly rather than silently reporting a wrong geometry.

Committed fixtures in ``data/dop3010-velocity`` (copied from the private
instrument-side capture directory; both are genuine ``BINUDOP`` files written by
`Record → Stop → Do store`):

* ``sw100-k1-161738.BDD`` — the finest rung of the ``c = 1460 m/s`` ladder:
  channel **1**, ``word 10 = 0``, 805 gates, ``c = 1460``, PRF 169 µs, burst 4,
  150 emissions/profile, and the file's own window depth ``word 2 = 100 mm``
  (the sweep point the private session's §9 table records).
* ``sim-label-2.BDD`` — a deliberately distinctive second point, differing from
  the first in every value that matters: channel **10**, ``word 10 = 1``
  (0.250 mm at ``c = 1500``), 37 gates, Doppler angle 7°, burst 2, sensitivity
  ``low`` (word 18 = 12), and ``word 2 = 14 mm``.

Why these two: between them they cover **two channels (1 and 10), two resolution
rungs (0 and 1), two sound speeds (1460 and 1500) and 805-fold different gate
counts**, and each carries a *stale configuration in the other channels* — the
"channel trap" (a file holds one independent config per channel, so a decode of
the wrong table reports a wrong-but-consistent point). ``sim-label-2.BDD`` pairs
the used channel-10 table (37 gates) with a stale channel-1 table (378 gates).

The decisive arbitration for the derived gate axis is each file's **own stored
depth pseudo-profile** (profile type 25, ``int16`` hundredths of a millimetre).
It is written by the instrument, independently of any decoder's formula, so the
decoder whose vector reproduces it is the one the instrument used:

* the axis is ``pitch × k + offset`` with ``pitch = (word 10 + 1) × c / 12000``
  (the rung law: the same number the private decoder states, and *not* the
  manual's rounded ``(n+1) × 0.166 µs`` row-10 constant) and
  ``offset = pitch × word 9 / (word 10 + 1) − c × word 46 / 2e6`` (first-gate
  index minus the hardware delay, word 46 documented in ns);
* the axis therefore starts at ``1.7277 mm`` on ``sw100-k1`` and ``5.025 mm`` on
  ``sim-label-2`` — *not* at the UI's ``First gate depth`` control value — and
  reproduces the stored profile to ``0.05 mm``, the profile's own quantisation.

Word 2 is the UI's derived window depth (``First gate depth + gates ×
resolution``), an integer: it is *close to* but not the last gate of the axis
(``100`` vs ``99.5477`` on ``sw100-k1``), which is why it is not used as the
gate axis. Words the independent session verified and that this reader publishes
as stored integers — 14 (emissions/profile), 27 (sampling-volume *index*, never
a millimetre value) and 84 (skipped profiles) — are pinned below against the
same fixtures and against the whole committed mixer sweep. Word 3 (velocity
scale ×100, derivable from word 15, pinned by
``test_velocity_scale_word_three_equals_the_nyquist_decode``) and word 42 (the
session's *probable* ``Tgc [dB]``, which the manual's table instead calls
"internal use") stay undecoded: word 3 is redundant with word 15 and word 42's
identity is not settled (``docs/dop3000/udop-automation.md`` §10).
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.io.dop.bdd import (
    _acquisition_rate_khz,
    _Buffer,
    _multiplexer_enabled,
    _read_op,
    read,
)
from udv_echo_process.models import AcquisitionMode, ChannelKey
from udv_echo_process.provenance import ArtifactBundle, select_channel

DATA = Path("data")
VEL3010 = DATA / "dop3010-velocity"

SW100_K1 = VEL3010 / "sw100-k1-161738.BDD"
SIM_LABEL_2 = VEL3010 / "sim-label-2.BDD"

ECHO_200 = DATA / "echo" / "200.BDD"

#: The committed 40-file mixer sensitivity sweep WP0 inventories.
MIXER_SWEEP = DATA / "mixer-sensitivity-analysis" / "4MHz" / "0500RPM" / "001"

#: Channel whose configuration each fixture actually measured, per the private
#: session's capture log (the block footer byte, verified below).
SW100_K1_CHANNEL = 1
SIM_LABEL_2_CHANNEL = 10

#: (fixture, used channel, stale channel, word values the labels pinned).
#: ``word 2`` is the UI's derived window depth, ``word 3`` the UI's velocity
#: scale ×100, ``word 5`` the PRF period, ``word 8`` the burst length,
#: ``word 13`` the gate count, ``word 18`` the sensitivity parameter,
#: ``word 19`` the sound speed, ``word 20`` the Doppler angle and ``word 21``
#: the module scale.
LABELLED_POINTS = [
    (
        SW100_K1,
        SW100_K1_CHANNEL,
        10,  # stale: the previous point's channel-10 table
        4000,  # wave 0, emitting frequency kHz
        100,  # word 2, depth mm
        169,  # word 5, PRF µs
        4,  # word 8, burst length
        805,  # word 13, gates
        150,  # word 14, emissions/profile
        1460,  # word 19, sound speed m/s
        0,  # word 20, Doppler angle deg
        2048,  # word 21, module scale
        1703,  # word 15, velocity scale factor
    ),
    (
        SIM_LABEL_2,
        SIM_LABEL_2_CHANNEL,
        1,  # stale: the earlier sweep's channel-1 table
        4000,
        14,
        333,
        2,
        37,
        44,
        1500,
        7,
        2048,
        3141,
    ),
]

#: ``(path, channel)`` for every decoded stream these fixtures carry.
FIXTURE_CASES = [
    (SW100_K1, SW100_K1_CHANNEL),
    (SIM_LABEL_2, SIM_LABEL_2_CHANNEL),
]

_PARAM_OFFSET = 548
_PARAM_STRIDE = 1024
_PARAM_WORDS = 256
_MEAS_BASE_OFFSET = 31268

#: Profile type 25 is the stored ``depth`` pseudo-profile (int16, 0.1 mm).
_DEPTH_PROFILE_TYPE = 25

#: The depth pseudo-profile's quantisation: half a tenth of a millimetre. A
#: correct calculated axis agrees with it to this bound and the reader's own
#: tolerance (0.06 mm) leaves one step of head-room.
_PROFILE_QUANTISATION_MM = 0.05

#: Rung of the ``c = 1460 m/s`` ladder on ``sw100-k1`` (word 10 = 0).
_ROW10_ROUNDED_RUNG_S = 0.166e-6


def _raw_words(path: Path, channel: int) -> np.ndarray:
    """Read one channel's 256 little-endian uint32 op-parameter words.

    Deliberately independent of the reader: the same ``548 + 1024*(channel-1)``
    table the vendor decoder uses, read as *unsigned* words so a negative coded
    field can be inspected in both renderings.
    """
    raw = path.read_bytes()
    offset = _PARAM_OFFSET + _PARAM_STRIDE * (channel - 1)
    assert offset + 4 * _PARAM_WORDS <= len(raw), "channel table outside the file"
    return np.frombuffer(raw, dtype="<u4", count=_PARAM_WORDS, offset=offset)


def _footer_rows(path: Path) -> list[tuple[int, int]]:
    """Walk the block chain and return ``(channel, timestamp)`` per block.

    An independent walk of the same length-prefixed chain the reader uses; the
    channel is the byte at ``meas_end - 3`` (manual §10.7 point J) and is the
    *only* statement of which channel a block belongs to.
    """
    raw = path.read_bytes()
    start = _MEAS_BASE_OFFSET
    eof = len(raw)
    rows: list[tuple[int, int]] = []
    while start + 4 <= eof:
        length = struct.unpack_from("<H", raw, start)[0]
        end = start + length
        if length == 0 or end > eof:
            break
        rows.append((raw[end - 3], struct.unpack_from("<I", raw, end - 12)[0]))
        start = end
    return rows


def _depth_profile(path: Path, channel: int) -> np.ndarray:
    """Decode the file's own stored depth pseudo-profile (int16 / 10 mm)."""
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
                if raw[prof + 2] == _DEPTH_PROFILE_TYPE:
                    return (
                        np.frombuffer(
                            raw[prof + 3 : prof + 3 + plen], dtype=np.int16
                        ).astype(float)
                        / 10.0
                    )
                prof += plen + 3
        start = end
    raise AssertionError(f"no stored depth profile for channel {channel} in {path}")


def _stream(path: Path, channel: int):
    bundle: ArtifactBundle = read(path)
    return select_channel(bundle, ChannelKey(device_channel=channel)).artifact


# ── the map the labels pinned, word by word ────────────────────────────


@pytest.mark.parametrize(
    (
        "path",
        "channel",
        "stale_channel",
        "word0",
        "word2",
        "word5",
        "word8",
        "word13",
        "word14",
        "word19",
        "word20",
        "word21",
        "word15",
    ),
    LABELLED_POINTS,
)
def test_labelled_point_words_and_decoded_config_agree(
    path,
    channel,
    stale_channel,
    word0,
    word2,
    word5,
    word8,
    word13,
    word14,
    word19,
    word20,
    word21,
    word15,
):
    """Each word the UI pinned decodes to the value the UI showed.

    This is the end-to-end ``requested → file → reader`` chain for a real
    capture: the words are asserted against the independent unsigned read and
    then against the reader's decoded ``ChannelConfig``.
    """
    words = _raw_words(path, channel)
    assert words[0] == word0  # emitting frequency kHz
    assert words[2] == word2  # UI window depth mm
    assert words[5] == word5  # PRF period µs
    assert words[8] == word8  # burst length
    assert words[13] == word13  # gates
    assert words[14] == word14  # emissions/profile
    assert words[15] == word15  # velocity scale factor (3141 == 1.00)
    assert words[19] == word19  # sound speed m/s
    assert words[20] == word20  # Doppler angle deg
    assert words[21] == word21  # module scale

    config = _stream(path, channel).config
    assert config.source_freq_khz == pytest.approx(word0)
    assert config.n_gates == word13
    assert config.burst_length == word8
    assert config.sound_speed_ms == pytest.approx(word19)
    assert config.doppler_angle_deg == pytest.approx(word20)
    assert config.module_scale == word21
    # word 5 is a *period* in µs; the field names the frequency
    assert config.pulse_repetition_freq_hz == pytest.approx(1e6 / word5)
    # word 7 emitting power: 0 low, 1 medium, 2 high (UI: "Medium")
    assert _raw_words(path, channel)[7] == 1
    assert config.emit_power == "medium"
    # word 18 sensitivity parameter: 8 medium, 12 low (the two labelled points)
    sensitivity_by_word = {8: "medium", 12: "low"}
    assert config.sensitivity == sensitivity_by_word[int(_raw_words(path, channel)[18])]

    # the *stale* table in the same file reports a different, plausible point:
    # this is the channel trap the map warning is about
    assert int(_raw_words(path, stale_channel)[13]) != word13


def test_channel_comes_from_the_block_footer_not_the_table_position():
    """Every block's footer channel decides which table a stream is built from.

    ``sim-label-2.BDD`` measures on channel 10 while channel 1 still carries the
    first point's 378-gate table; a reader that assumed channel 1 (or the first
    non-empty table) would report 378 gates and 169 µs for a 37-gate recording.
    """
    for path, channel in FIXTURE_CASES:
        footer_channels = {ch for ch, _ in _footer_rows(path)}
        assert footer_channels == {channel}

        bundle = read(path)
        assert len(bundle.recording.streams) == 1
        stream = bundle.recording.streams[0]
        assert stream.acquisition.channel == ChannelKey(device_channel=channel)
        assert stream.config.n_gates == int(_raw_words(path, channel)[13])
        # the stale sibling table holds a different configuration
        stale = 1 if channel != 1 else 10
        assert int(_raw_words(path, stale)[13]) != int(_raw_words(path, channel)[13])

    # concrete pair: used 10 (37 gates) vs stale 1 (378 gates)
    assert int(_raw_words(SIM_LABEL_2, 10)[13]) == 37
    assert int(_raw_words(SIM_LABEL_2, 1)[13]) == 378


def test_prf_word_is_a_microsecond_period_converted_to_hz():
    assert _stream(SIM_LABEL_2, 10).config.pulse_repetition_freq_hz == pytest.approx(
        1e6 / 333
    )
    assert _stream(SW100_K1, 1).config.pulse_repetition_freq_hz == pytest.approx(
        1e6 / 169
    )


# ── the derived gate geometry ──────────────────────────────────────────


def test_resolution_is_the_rung_index_law_on_both_rungs():
    """``resolution_mm = (word 10 + 1) × c / 12000`` — the rung law.

    Verified on rung 0 (``0.1216667 mm`` at 1460) and rung 1 (``0.250 mm`` at
    1500) in the same session, and re-derived here from words 10 and 19 alone.
    The reader reaches the same number through the acquisition-rate word (word
    29's packed rate byte ``6`` → 6000 kHz), so the two decoders' spellings of
    the pitch must agree exactly.
    """
    cases = [
        (SW100_K1, 1, 0, 1460, 0.12166666666666667),
        (SIM_LABEL_2, 10, 1, 1500, 0.25),
    ]
    for path, channel, rung, sound, expected in cases:
        words = _raw_words(path, channel)
        assert int(words[10]) == rung
        assert int(words[19]) == sound
        law = (int(words[10]) + 1) * int(words[19]) / 12000.0
        assert law == pytest.approx(expected, abs=1e-12)
        config = _stream(path, channel).config
        assert config.resolution_mm == pytest.approx(law, abs=1e-12)
        # and the reader's own inputs decode the rate the rung law assumes
        assert _acquisition_rate_khz(_read_op(_Buffer(path.read_bytes()), channel)) == (
            pytest.approx(6000.0)
        )


def test_gate_axis_is_the_rung_ladder_minus_the_hardware_delay():
    """The canonical axis, rebuilt independently, then checked against the file.

    Built here from words 10 + 19 (rung pitch) and words 9 + 46 (first-gate index
    and the manual's hardware delay in ns) — a different spelling from the
    reader's ``(word 10 + 1) / (2 × rate)`` form — then compared with:

    * the reader's own vector (must be identical), and
    * the file's stored depth pseudo-profile (must agree within its 0.1 mm
      quantisation).

    ``sw100-k1`` additionally refutes the manual's *rounded* row-10 constant:
    its 805 gates amplify the 0.4 % error between ``0.166 µs`` and the exact
    ``1/6 MHz`` rung into a 0.34 mm departure from the stored profile, which is
    why the reader uses the decoded acquisition rate rather than ``0.166e-6``.
    """
    for path, channel in FIXTURE_CASES:
        words = _raw_words(path, channel)
        gates, rung, first_gate = int(words[13]), int(words[10]), int(words[9])
        sound, hw_delay_ns = int(words[19]), int(words[46])

        pitch = (rung + 1) * sound / 12000.0
        offset = pitch * first_gate / (rung + 1) - sound * hw_delay_ns / 2e6
        expected = offset + pitch * np.arange(gates)

        got = _stream(path, channel).data.gate_depths_mm
        assert got.shape == (gates,)
        assert np.allclose(got, expected, atol=1e-9)

        profile = _depth_profile(path, channel)
        assert profile.shape == (gates,)
        assert float(np.max(np.abs(got - profile))) <= _PROFILE_QUANTISATION_MM

    # the rounded manual constant does not reproduce sw100-k1's stored profile
    words = _raw_words(SW100_K1, 1)
    gates, sound, hw_delay_ns = int(words[13]), int(words[19]), int(words[46])
    rounded_pitch = (int(words[10]) + 1) * sound * _ROW10_ROUNDED_RUNG_S / 2 * 1e3
    rounded_axis = (
        rounded_pitch * int(words[9]) / (int(words[10]) + 1)
        - sound * hw_delay_ns / 2e6
        + rounded_pitch * np.arange(gates)
    )
    assert float(np.max(np.abs(rounded_axis - _depth_profile(SW100_K1, 1)))) > (
        _PROFILE_QUANTISATION_MM
    )


def test_word_two_is_the_ui_window_depth_not_the_gate_axis():
    """Word 2 is the UI's integer window depth, not a gate position.

    ``sw100-k1``'s axis ends at ``99.5477 mm`` while its word 2 reads ``100``
    (the UI's ``First gate depth 2 + 805 × 0.1217``); ``sim-label-2``'s ends at
    ``14.025`` against word 2 = ``14``. Treating word 2 as the last gate would
    misplace the axis, which is why the reader derives it from words 9/10/19/46
    and merely agrees with word 2 to within its own rounding.
    """
    cases = [(SW100_K1, 1, 100), (SIM_LABEL_2, 10, 14)]
    for path, channel, window_mm in cases:
        assert int(_raw_words(path, channel)[2]) == window_mm
        last_gate = float(_stream(path, channel).data.gate_depths_mm[-1])
        assert abs(last_gate - window_mm) <= 0.5

    last_gate = float(_stream(SW100_K1, 1).data.gate_depths_mm[-1])
    assert abs(last_gate - 100) > 0.1  # not interchangeable with word 2


def test_stored_depth_profile_is_quantised_to_tenths_of_a_millimetre():
    """The validation input's quantisation is why the tolerance is 0.05 mm."""
    for path, channel in FIXTURE_CASES:
        profile = _depth_profile(path, channel)
        assert np.allclose(profile * 10, np.round(profile * 10), atol=1e-9)


def test_velocity_scale_word_three_equals_the_nyquist_decode():
    """Word 3 (UI "Velocity scale", mm/s ×100) equals word 15's Nyquist decode.

    Word 3 is the display copy the label pinned (``46866`` → ``468.7 mm/s``,
    ``29269`` → ``292.7``, ``28359`` → ``283.6``); the reader computes the same
    number from word 15's raw scale factor, the PRF, the sound speed, the
    Doppler angle and the emitting frequency. Reproducing an independently
    verified *different* word to 0.01 mm/s is the strongest available check of
    that decode, since word 3 itself is not decoded.
    """
    for path, channel in FIXTURE_CASES:
        words = _raw_words(path, channel)
        assert _stream(path, channel).config.velo_max_ms == pytest.approx(
            int(words[3]) / 100.0, abs=0.01
        )

    assert _stream(SIM_LABEL_2, 10).config.velo_max_ms == pytest.approx(
        283.59, abs=0.01
    )
    assert _stream(SW100_K1, 1).config.velo_max_ms == pytest.approx(292.69, abs=0.01)


# ── op-word coding details ─────────────────────────────────────────────


def test_op_words_are_read_as_signed_int32():
    """Coded words are signed: word 22 reads ``-97``, not ``4294967199``.

    ``200.BDD``'s stale channels carry a negative velocity offset (word 22) and a
    negative word 30; the independent unsigned read shows both renderings, and
    the reader must decode the signed one — the velocity wrap correction
    (``d + offset``) only means anything on the signed value.
    """
    raw = ECHO_200.read_bytes()
    for channel in (1, 2, 3):
        words = _raw_words(ECHO_200, channel)
        assert int(words[22]) == 4294967199  # -97 as int32
        assert int(words[30]) == 4294967286  # -10 as int32
        op = _read_op(_Buffer(raw), channel)
        assert op["velo_offset"] == -97
        assert op["prf_us"] == int(words[5])


# ── sweep metadata exposed for the manifest (WP0) ──────────────────────


def test_emissions_profile_volume_index_and_skipped_profiles_are_exposed():
    """Words 14, 27 and 84 reach the public ``ChannelConfig`` as stored ints.

    Each word is checked twice: against the independent unsigned read of the
    channel table, and against the reader's decoded ``ChannelConfig``. The
    values are the *stored* integers — word 27 stays an index (the instrument's
    own ``Sampling volume`` option-list position), never a millimetre value.
    """
    cases = [
        (SW100_K1, 1, 150, 3, 0),
        (SIM_LABEL_2, 10, 44, 3, 0),
        (ECHO_200, 4, 8, 5, 0),
    ]
    for path, channel, emissions, volume_index, skipped in cases:
        words = _raw_words(path, channel)
        assert int(words[14]) == emissions
        assert int(words[27]) == volume_index
        assert int(words[84]) == skipped

        config = _stream(path, channel).config
        assert config.emissions_per_profile == emissions
        assert config.sampling_volume_index == volume_index
        assert config.skipped_profiles == skipped
        # the index is not a length: no reviewed index → mm conversion exists, so
        # the millimetre field must stay unset rather than guess one
        assert config.sampling_volume_mm is None


def test_every_mixer_sweep_file_exposes_the_stored_sweep_words():
    """WP0's fixture evidence: the committed sweep holds one triple everywhere.

    The 40 committed files of ``data/mixer-sensitivity-analysis/4MHz/0500RPM/001``
    carry ``word 14 = 20``, ``word 27 = 4`` and ``word 84 = 0`` (the dataset
    README's base state of 20 emissions/profile); the reader must expose those
    integers on every one of them, discovered from the directory rather than a
    hand-maintained list.
    """
    files = sorted(MIXER_SWEEP.rglob("*.BDD"))
    assert len(files) == 40
    for path in files:
        stream = read(path).recording.streams[0]
        channel = stream.acquisition.channel.device_channel
        words = _raw_words(path, channel)
        assert int(words[14]) == 20
        assert int(words[27]) == 4
        assert int(words[84]) == 0
        assert stream.config.emissions_per_profile == 20
        assert stream.config.sampling_volume_index == 4
        assert stream.config.skipped_profiles == 0


def test_acquisition_rate_word_is_the_packed_table_not_a_scalar():
    """Word 29 is four bytes: byte 0 indexes the rate; the reader must not
    treat its ``0x280C0600`` rendering as a scalar rate."""
    for path, channel in FIXTURE_CASES:
        words = _raw_words(path, channel)
        assert int(words[29]) == 671876608  # (0, 6, 12, 40) as a uint32
        assert struct.unpack("<4b", words[29].tobytes()) == (0, 6, 12, 40)
        op = _read_op(_Buffer(path.read_bytes()), channel)
        assert op["aquisition_rate"] == (0, 6, 12, 40)
        assert _acquisition_rate_khz(op) == pytest.approx(6000.0)


def test_other_multiplexer_bits_do_not_set_the_acquisition_mode():
    """Word 52 = ``0x10010`` sets bits 4 and 16 but **not** bit 0.

    Both fixtures are single-channel recordings (the UI showed one channel and
    each block's footer names it), so the mode must stay ``UNKNOWN`` even though
    other bits of the multiplexer word are set: only bit index 0 — the manual's
    1-based "bit 1: if set multiplexer enables" — proves multiplexed operation.
    """
    for path, channel in FIXTURE_CASES:
        words = _raw_words(path, channel)
        assert int(words[52]) == 0x10010
        assert int(words[52]) & 0b1 == 0
        assert int(words[52]) & 0b10000  # bit 4: a selected channel
        assert int(words[52]) & 0x10000  # bit 16: first channel field
        assert _multiplexer_enabled((int(words[52]),)) is False
        assert read(path).recording.acquisition_mode is AcquisitionMode.UNKNOWN


# ── derived cadence (words 5, 14 and 17 against the decoded times) ─────


def _add_tbd_ms(path: Path) -> tuple[int, np.ndarray]:
    """Read the vendor ASCII export's ``TBD [ms]`` column and its channel."""
    lines = path.read_text(encoding="latin-1").splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("Amp\t"))
    rows = [line for line in lines[header + 1 :] if line.strip()]
    channels = {int(row.split("\t")[-1]) for row in rows}
    assert len(channels) == 1, "export carries more than one channel section"
    return channels.pop(), np.array(
        [float(row.split("\t")[-3].replace(",", ".")) for row in rows]
    )


def test_profile_timestamps_match_the_vendor_ascii_export():
    """The decoded time axis is the instrument's own, tick for tick.

    ``200.BDD`` ships with the vendor's ``.ADD`` export of the same recording,
    whose ``TBD [ms]`` column is written by the instrument, not by any decoder
    here. All 4180 rows agree with the reader's ``time_s`` — which confirms the
    block-chain walk, the footer timestamp at ``meas_end - 12`` and the
    0.1 ms/``1e-4 s`` tick — so the profile cadence below can be trusted as the
    instrument's own.
    """
    channel, exported_ms = _add_tbd_ms(ECHO_200.with_suffix(".ADD"))
    decoded_ms = _stream(ECHO_200, channel).data.time_s * 1e3
    assert decoded_ms.shape == exported_ms.shape
    assert float(np.max(np.abs(decoded_ms - exported_ms))) <= 0.005


@pytest.mark.parametrize(
    ("path", "channel"),
    [(ECHO_200, 4), (SIM_LABEL_2, 10), (SW100_K1, 1)],
)
def test_profile_period_is_the_emission_train_including_stabilization(path, channel):
    """The period is ``(word 14 + word 17) x word 5``, not ``word 14 x word 5``.

    Word 14 (emissions/profile) and word 17 (emissions for stabilization, ``16``
    in every file available here) are both verified words; the private session's
    rule "``T_profile`` ~ emissions x PRF + ~1 ms" (``udop-automation.md`` §8)
    omits word 17 and therefore under-predicts every measured cadence — by 66 %
    on ``200.BDD``, whose channel 4 asks for ``8 x 125 µs = 1 ms`` while the
    instrument's own cadence (and its ``.ADD`` export) reads 3.1-3.2 ms, exactly
    ``(8 + 16) x 125 µs``. The residual (0.1-1.6 ms over the files measured) is
    the transfer/round-trip term, which is why the bound below is a band rather
    than an equality. This matters to the caller's ``T <= cap x period``
    assertion, which is only conservative while the period is not under-stated.
    """
    words = _raw_words(path, channel)
    prf_us, emissions, stabilization = (
        int(words[5]),
        int(words[14]),
        int(words[17]),
    )
    assert stabilization == 16
    train_ms = (emissions + stabilization) * prf_us / 1000.0
    emissions_only_ms = emissions * prf_us / 1000.0

    step_ms = float(np.median(np.diff(_stream(path, channel).data.time_s)) * 1e3)
    assert abs(step_ms - train_ms) <= max(0.25, 0.1 * train_ms)
    assert step_ms > emissions_only_ms  # word 14 alone cannot account for it
