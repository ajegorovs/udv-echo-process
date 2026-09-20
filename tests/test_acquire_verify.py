"""Tests for ``acquire/verify.py`` — the stored-word check, on real bytes.

Every case writes an actual ``.BDD``-shaped buffer to ``tmp_path`` (uint32
little-endian words at the documented offsets) and reads it back through the
module. Nothing is mocked: the failure this module exists for — a file that
decodes as a perfectly valid block and is still the wrong point — is a byte-level
one, so the tests are byte-level too.

The three pass cases are the points recorded today on the simulator at
c = 1460 m/s, first gate 2 mm, 2 s, emissions 150, PRF 169 us, burst 4, all three
verified good:

    rung 0 -> 805 gates, word10 = 0, word2 = 100, file 102,113 B
    rung 1 -> 403 gates, word10 = 1, word2 = 100, file  67,541 B
    rung 3 -> 201 gates, word10 = 3, word2 =  99, file  50,389 B

Their file sizes are reproduced exactly as well, so the fixtures carry the same
size signature the live points had (size alone is not the check — a stale-buffer
point can be any size — but a fixture that matches the live point in every
recorded respect is the stronger test).
"""

from __future__ import annotations

import inspect
import struct
from pathlib import Path

import pytest

from udv_echo_process.acquire.config import ParameterSet
from udv_echo_process.acquire.verify import (
    ADVISORY_COVARIATES,
    CHANNEL_1_OFFSET_BYTES,
    CHANNEL_STRIDE_BYTES,
    ENFORCED_COVARIATES,
    WORD_EMISSIONS_PER_PROFILE,
    VerificationResult,
    WordFacts,
    read_words,
    verify_stored_point,
)

SOUND_SPEED_MS = 1460
RUNG_MM = SOUND_SPEED_MS / 12000.0  # 0.1216666... mm — the ladder's first rung
FIRST_GATE_MM = 2.0
PRF_US = 169
BURST_LENGTH = 4
EMISSIONS_PER_PROFILE = 150

#: The three live points: rung, gates, the depth word the app wrote, its size,
#: and the pitch as the sidebar states it (3 decimals — a *request*, not the rung).
LIVE_POINTS = (
    {"rung": 0, "gates": 805, "depth_word": 100, "size_bytes": 102_113,
     "resolution_mm": 0.122},
    {"rung": 1, "gates": 403, "depth_word": 100, "size_bytes": 67_541,
     "resolution_mm": 0.243},
    {"rung": 3, "gates": 201, "depth_word": 99, "size_bytes": 50_389,
     "resolution_mm": 0.487},
)


def word_offset(word_index: int, channel: int = 1) -> int:
    """Byte offset of ``word_index`` (0-based) of ``channel`` (1-based)."""
    return (
        CHANNEL_1_OFFSET_BYTES
        + (channel - 1) * CHANNEL_STRIDE_BYTES
        + word_index * 4
    )


def build_bdd(
    path: Path,
    words: dict[tuple[int, int], int],
    *,
    channels: int = 1,
    size_bytes: int | None = None,
) -> Path:
    """Write a ``.BDD``-shaped file whose quoted words carry ``words``.

    ``words`` is keyed by ``(channel, word index)`` — the two numbers the byte
    offset is computed from — so one call can fill several channels. The buffer
    holds every channel and nothing else unless ``size_bytes`` says otherwise, in
    which case it is padded or truncated to exactly that many bytes (which is how
    the truncated-file cases are built).
    """
    minimum = CHANNEL_1_OFFSET_BYTES + channels * CHANNEL_STRIDE_BYTES
    buffer = bytearray(minimum)
    for (channel, index), value in words.items():
        offset = word_offset(index, channel)
        buffer[offset : offset + 4] = struct.pack("<I", value)
    if size_bytes is not None:
        if size_bytes > len(buffer):
            buffer.extend(b"\x00" * (size_bytes - len(buffer)))
        buffer = buffer[:size_bytes]
    path.write_bytes(bytes(buffer))
    return path


def live_words(
    rung: int, gates: int, depth_word: int, *, channel: int = 1
) -> dict[tuple[int, int], int]:
    """The words the three live points were recorded with, for one channel."""
    return {
        (channel, 2): depth_word,
        (channel, 5): PRF_US,
        (channel, 8): BURST_LENGTH,
        (channel, 10): rung,
        (channel, 13): gates,
        (channel, 14): EMISSIONS_PER_PROFILE,
        (channel, 19): SOUND_SPEED_MS,
    }


def live_point_file(tmp_path: Path, point: dict[str, object]) -> Path:
    rung = int(point["rung"])
    gates = int(point["gates"])
    return build_bdd(
        tmp_path / f"point_rung{rung}.BDD",
        live_words(rung, gates, int(point["depth_word"])),
        size_bytes=int(point["size_bytes"]),
    )


def params_for(
    *,
    gates: int,
    rung: int,
    resolution_mm: float | None = None,
    first_gate_mm: float = FIRST_GATE_MM,
    sound_speed_ms: float = SOUND_SPEED_MS,
    prf_us: float = PRF_US,
    emissions_per_profile: int = EMISSIONS_PER_PROFILE,
    burst_length: int = BURST_LENGTH,
) -> ParameterSet:
    return ParameterSet(
        sound_speed_ms=sound_speed_ms,
        first_gate_mm=first_gate_mm,
        resolution_mm=RUNG_MM * (rung + 1) if resolution_mm is None else resolution_mm,
        gates=gates,
        prf_us=prf_us,
        emissions_per_profile=emissions_per_profile,
        burst_length=burst_length,
    )


# --------------------------------------------------------------------------- #
# The pass cases: the three points recorded on the simulator today.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("point", LIVE_POINTS, ids=lambda p: f"rung{p['rung']}")
def test_live_point_verifies(tmp_path: Path, point: dict[str, object]) -> None:
    path = live_point_file(tmp_path, point)
    assert path.stat().st_size == point["size_bytes"]

    result = verify_stored_point(
        path,
        params_for(
            gates=int(point["gates"]),
            rung=int(point["rung"]),
            resolution_mm=float(point["resolution_mm"]),
        ),
    )

    assert isinstance(result, VerificationResult)
    assert result.mismatches == ()
    assert result.ok is True

    facts = result.facts
    assert facts.gates == point["gates"]
    assert facts.resolution_index == point["rung"]
    assert facts.resolution_mm == pytest.approx((int(point["rung"]) + 1) * RUNG_MM)
    assert facts.depth_mm == point["depth_word"]
    assert facts.sound_speed_ms == SOUND_SPEED_MS
    assert facts.prf_us == PRF_US
    assert facts.emissions_per_profile == EMISSIONS_PER_PROFILE
    assert facts.burst_length == BURST_LENGTH
    assert facts.missing_fields() == ()


@pytest.mark.parametrize("point", LIVE_POINTS, ids=lambda p: f"rung{p['rung']}")
def test_live_point_verifies_with_the_exact_rung_pitch(
    tmp_path: Path, point: dict[str, object]
) -> None:
    """The same three points also pass when the request is the exact rung pitch."""
    path = live_point_file(tmp_path, point)
    result = verify_stored_point(
        path,
        params_for(
            gates=int(point["gates"]),
            rung=int(point["rung"]),
            resolution_mm=(int(point["rung"]) + 1) * RUNG_MM,
        ),
    )
    assert result.ok, result.mismatches


def test_live_point_depth_word_is_the_floor_of_the_snapped_derivation(
    tmp_path: Path,
) -> None:
    """Word 2 tracks first gate + gates x rung pitch, floored — within tolerance.

    Rung 0 at 805 gates derives 99.94 mm and the app stored 100, rung 3 at 201
    gates derives 99.82 mm and the app stored 99; both are inside the 1.5 mm
    default. This is why the depth check is a tolerance, not an equality.
    """
    derived = {
        0: FIRST_GATE_MM + 805 * RUNG_MM,   # 99.942
        1: FIRST_GATE_MM + 403 * 2 * RUNG_MM,  # 100.062
        3: FIRST_GATE_MM + 201 * 4 * RUNG_MM,  # 99.820
    }
    stored = {0: 100, 1: 100, 3: 99}
    for point in LIVE_POINTS:
        rung = int(point["rung"])
        assert abs(derived[rung] - stored[rung]) <= 1.5
        assert abs(derived[rung] - stored[rung]) > 0.0


def test_default_depth_tolerance_is_one_and_a_half_mm() -> None:
    """The documented defaults: 1.5 mm on the depth, covariates advisory."""
    signature = inspect.signature(verify_stored_point)
    assert signature.parameters["depth_tolerance_mm"].default == 1.5
    assert signature.parameters["check_covariates"].default is False


# --------------------------------------------------------------------------- #
# The covariate split: three words a definition asserts about the instrument, and
# one whose declaration has been the wrong side of the comparison.
# --------------------------------------------------------------------------- #


def test_the_settled_covariates_are_the_three_the_live_points_agreed_on() -> None:
    """PRF, sound speed and burst — the words the six live points matched exactly."""
    assert ENFORCED_COVARIATES == ("sound_speed_ms", "prf_us", "burst_length")
    assert ADVISORY_COVARIATES == ("emissions_per_profile",)
    assert set(ENFORCED_COVARIATES).isdisjoint(ADVISORY_COVARIATES)


def test_a_prf_that_disagrees_is_enforced(tmp_path: Path) -> None:
    """A declared PRF is an assertion about the instrument, so a mismatch refuses.

    The stored point carries PRF 169 µs (the configuration of the committed
    ``sw100`` recording); the request says 212 µs, which is what the reference
    install was set to in the session that recorded the six-point campaign. Those
    cannot both be true of one instrument at one moment, and the point must not be
    logged good until that is resolved.
    """
    path = build_bdd(tmp_path / "prf.BDD", live_words(0, 805, 100))

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122, prf_us=212.0),
        check_covariates=True,
    )

    assert result.ok is False
    assert result.mismatches == (
        "prf_us: requested 212, found 169 in word 5 (tolerance 1)",
    )
    assert result.advisories == ()  # word 14 agrees; nothing else to report
    assert result.enforced_covariates == ENFORCED_COVARIATES


def test_emissions_that_disagree_are_an_advisory_not_a_mismatch(tmp_path: Path) -> None:
    """Word 14 is read and reported — and does not refuse the point *by default*.

    The request says 52 emissions; the file says 150. The 52 is not a reading off the
    instrument: it is the period law inverted to reproduce the committed recording's
    own profile count (``EMISSIONS_PER_PROFILE`` in ``test_acquire_runner.py``). So the
    *declaration* is what disagrees, and refusing the point over it would refuse a file
    whose core words are all exactly right. A caller whose request *is* that value raises
    it (:func:`test_a_raised_fact_refuses_instead_of_advising`); the default stays advisory.
    """
    path = build_bdd(tmp_path / "emissions.BDD", live_words(0, 805, 100))

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122, emissions_per_profile=52),
        check_covariates=True,
    )

    assert result.mismatches == ()
    assert result.ok is True
    assert result.advisories == (
        "emissions_per_profile: requested 52, found 150 in word 14",
    )
    # Read either way: the fact reaches the caller whether or not it is enforced.
    assert result.facts.emissions_per_profile == EMISSIONS_PER_PROFILE


def test_an_advisory_needs_no_enforcement_switch(tmp_path: Path) -> None:
    """The comparison is made on every call; only the three settled words refuse.

    The advisory is evidence about the *declaration*, and a caller that never turns
    enforcement on still has to be able to see it.
    """
    path = build_bdd(tmp_path / "emissions.BDD", live_words(0, 805, 100))

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122, emissions_per_profile=52),
    )

    assert result.ok is True
    assert result.enforced_covariates == ()
    assert result.advisories == (
        "emissions_per_profile: requested 52, found 150 in word 14",
    )


def test_a_raised_fact_refuses_instead_of_advising(tmp_path: Path) -> None:
    """The same bytes and the same request, with the caller requiring word 14 to agree.

    This is the post-storage half of a run's policy: a pass whose axis *is* the emissions value
    raises the fact, and then a file whose word disagrees is not that pass's point — ``ok`` false,
    the mismatch naming the field and both sides, and nothing left in the advisories.
    """
    path = build_bdd(tmp_path / "emissions.BDD", live_words(0, 805, 100))

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122, emissions_per_profile=52),
        check_covariates=True,
        strict_covariates=("emissions_per_profile",),
    )

    assert result.ok is False
    assert result.advisories == ()
    assert result.mismatches == (
        "emissions_per_profile: requested 52, found 150 in word 14",
    )
    # Raised fields are enforced fields, and the record says a caller raised them.
    assert "emissions_per_profile" in result.enforced_covariates
    assert result.strict_covariates == ("emissions_per_profile",)
    # And the field is no longer reported as compared-without-enforcing.
    assert result.advisory_covariates == ()


def test_a_raised_fact_that_agrees_is_recorded_as_enforced(tmp_path: Path) -> None:
    """A raise that holds leaves no trace but the statement that it was required."""
    path = build_bdd(tmp_path / "emissions.BDD", live_words(0, 805, 100))

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        check_covariates=True,
        strict_covariates=("emissions_per_profile",),
    )

    assert result.ok is True
    assert result.mismatches == ()
    assert "emissions_per_profile" in result.enforced_covariates
    assert result.strict_covariates == ("emissions_per_profile",)


def test_a_raise_applies_without_the_covariate_switch(tmp_path: Path) -> None:
    """The raise is per fact and does not depend on ``check_covariates``.

    A caller that only cares about word 14 says so by naming it; the switch governs the *table's*
    enforced covariates, and turning it off must not silently turn a raised fact back into an
    advisory.
    """
    path = build_bdd(tmp_path / "emissions.BDD", live_words(0, 805, 100))

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122, emissions_per_profile=52),
        strict_covariates=("emissions_per_profile",),
    )

    assert result.ok is False
    assert result.advisories == ()
    assert result.strict_covariates == ("emissions_per_profile",)


def test_raising_a_fact_no_stored_file_carries_is_refused(tmp_path: Path) -> None:
    """A fact nothing can compare must not read as enforced."""
    path = build_bdd(tmp_path / "emissions.BDD", live_words(0, 805, 100))

    with pytest.raises(ValueError) as caught:
        verify_stored_point(
            path,
            params_for(gates=805, rung=0, resolution_mm=0.122),
            strict_covariates=("max_profiles_per_block",),
        )

    message = str(caught.value)
    assert "max_profiles_per_block" in message
    assert "raiseable fields are" in message


def test_a_covariate_nobody_declared_is_not_a_mismatch(tmp_path: Path) -> None:
    """An absent covariate in the request is compared against nothing — and says so.

    The point must not be refused for a field nobody asked about, and the record must not
    claim it was checked either: only the field that *was* declared appears in
    ``enforced_covariates``, so "it agreed" stays distinguishable from "nobody looked".
    """
    path = build_bdd(tmp_path / "no-covariates.BDD", live_words(0, 805, 100))

    result = verify_stored_point(
        path,
        ParameterSet(
            sound_speed_ms=SOUND_SPEED_MS,
            first_gate_mm=FIRST_GATE_MM,
            resolution_mm=0.122,
            gates=805,
        ),
        check_covariates=True,
    )

    assert result.ok is True, result.mismatches
    assert result.advisories == ()
    assert result.enforced_covariates == ("sound_speed_ms",)
    assert result.advisory_covariates == ()
    assert "prf_us" not in result.enforced_covariates
    assert "burst_length" not in result.enforced_covariates


def test_only_the_covariates_the_request_declares_are_reported_as_compared(
    tmp_path: Path,
) -> None:
    """A partial declaration reports exactly what it compared, enforced and advisory."""
    words = live_words(0, 805, 100)
    words[(1, WORD_EMISSIONS_PER_PROFILE)] = 900  # a disagreement, on the advisory word
    path = build_bdd(tmp_path / "partial.BDD", words)

    result = verify_stored_point(
        path,
        ParameterSet(
            sound_speed_ms=SOUND_SPEED_MS,
            first_gate_mm=FIRST_GATE_MM,
            resolution_mm=0.122,
            gates=805,
            prf_us=PRF_US,
            emissions_per_profile=EMISSIONS_PER_PROFILE,
        ),
        check_covariates=True,
    )

    assert result.enforced_covariates == ("sound_speed_ms", "prf_us")
    assert "burst_length" not in result.enforced_covariates
    assert result.advisory_covariates == ("emissions_per_profile",)
    assert len(result.advisories) == 1


# --------------------------------------------------------------------------- #
# Failure cases, one per field the runner must catch.
# --------------------------------------------------------------------------- #


def test_truncated_file_reports_every_absent_word(tmp_path: Path) -> None:
    """A file that ends before the words is unverifiable, never "fine"."""
    full = live_point_file(tmp_path, LIVE_POINTS[0])
    truncated = tmp_path / "cut.BDD"
    truncated.write_bytes(full.read_bytes()[:200])

    facts = read_words(truncated)
    assert facts == WordFacts()
    assert facts.missing_fields() == (
        "depth_mm",
        "prf_us",
        "burst_length",
        "resolution_index",
        "gates",
        "emissions_per_profile",
        "sound_speed_ms",
    )

    result = verify_stored_point(
        truncated, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert result.ok is False
    assert any("gates" in message for message in result.mismatches)
    assert any("word 13 is not present" in message for message in result.mismatches)
    assert any("depth_mm" in message for message in result.mismatches)
    assert any("resolution_index" in message for message in result.mismatches)


def test_partially_present_words_report_only_what_is_missing(tmp_path: Path) -> None:
    """Words before the cut are read; words after it stay None."""
    size = word_offset(14) + 4  # exactly through word 14; word 19 is past the cut
    path = build_bdd(
        tmp_path / "partial.BDD",
        live_words(0, 805, 100),
        size_bytes=size,
    )
    facts = read_words(path)
    assert facts.gates == 805
    assert facts.depth_mm == 100
    assert facts.prf_us == PRF_US
    assert facts.resolution_index == 0
    assert facts.emissions_per_profile == EMISSIONS_PER_PROFILE
    # Word 19 (sound speed) is past the cut, so the pitch cannot be computed.
    assert facts.sound_speed_ms is None
    assert facts.resolution_mm is None
    assert facts.burst_length == BURST_LENGTH  # word 8 is before the cut

    result = verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    # The core three words are all present and all agree, so the point passes:
    # the absent sound speed means the pitch is inverted with the *requested* c,
    # which is the value being verified against anyway.
    assert result.ok is True

    # Enforcing the covariates is what catches the absent word 19.
    enforced = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        check_covariates=True,
    )
    assert enforced.ok is False
    expected = (
        "sound_speed_ms: requested 1460 but word 19 is not present in the "
        "stored file (missing or truncated)"
    )
    assert enforced.mismatches == (expected,)


def test_missing_file_is_a_reason_not_an_exception(tmp_path: Path) -> None:
    path = tmp_path / "no_such_point.BDD"
    assert read_words(path) == WordFacts()
    assert read_words(tmp_path) == WordFacts()  # a directory is not a file either

    result = verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert result.ok is False
    assert result.mismatches
    assert result.facts == WordFacts()


def test_wrong_gate_count_is_reported(tmp_path: Path) -> None:
    """805 was requested; the block was written with auto-gates left on: 474."""
    path = build_bdd(tmp_path / "gates.BDD", live_words(0, 474, 100))
    result = verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert result.ok is False
    assert result.mismatches == (
        "gates: requested 805, found 474 in word 13",
    )


def test_wrong_resolution_rung_is_reported(tmp_path: Path) -> None:
    """The request is rung 0 (0.122 mm); the file says rung 3 (0.487 mm)."""
    path = build_bdd(tmp_path / "rung.BDD", live_words(3, 805, 100))
    result = verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert result.ok is False
    assert len(result.mismatches) == 1
    message = result.mismatches[0]
    assert message.startswith("resolution_index: requested 0.122 mm is rung 0")
    assert "found rung 3" in message
    assert "word 10" in message
    assert result.facts.resolution_index == 3


def test_wrong_depth_is_reported(tmp_path: Path) -> None:
    """Gates and rung match, but the stored depth is a different window."""
    path = build_bdd(tmp_path / "depth.BDD", live_words(0, 805, 250))
    result = verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert result.ok is False
    assert len(result.mismatches) == 1
    assert result.mismatches[0].startswith("depth_mm: requested 99.9417")
    assert "found 250 in word 2" in result.mismatches[0]
    assert "tolerance 1.5" in result.mismatches[0]


def test_depth_tolerance_is_honoured(tmp_path: Path) -> None:
    """A 2 mm depth error passes at the 3 mm tolerance and fails at 1 mm."""
    path = build_bdd(tmp_path / "tol.BDD", live_words(0, 805, 102))

    tight = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        depth_tolerance_mm=1.0,
    )
    assert tight.ok is False
    assert any("depth_mm" in message for message in tight.mismatches)

    loose = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        depth_tolerance_mm=3.0,
    )
    assert loose.ok is True


def test_stale_buffer_signature_is_caught_by_the_words(tmp_path: Path) -> None:
    """A valid block of *stale* profiles: it decodes, and the words give it away.

    The 1.5 s point that came back as 8,272,897 B was structurally perfect; what
    it could not be was 805 gates at rung 0. The words say what it really was.
    """
    path = build_bdd(
        tmp_path / "stale.BDD",
        live_words(1, 403, 100),  # the previous point's window, all of it
        size_bytes=8_272_897,
    )
    result = verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert result.ok is False
    assert any(message.startswith("gates:") for message in result.mismatches)
    assert any(
        message.startswith("resolution_index:") for message in result.mismatches
    )


# --------------------------------------------------------------------------- #
# Channel geometry and the duck-typed request.
# --------------------------------------------------------------------------- #


def test_channel_stride_selects_the_right_words(tmp_path: Path) -> None:
    """Channel 2's words live 1024 B after channel 1's — the stride is real."""
    path = build_bdd(
        tmp_path / "two_channels.BDD",
        {
            **live_words(0, 805, 100, channel=1),
            **live_words(1, 403, 100, channel=2),
        },
        channels=2,
    )
    assert path.stat().st_size == CHANNEL_1_OFFSET_BYTES + 2 * CHANNEL_STRIDE_BYTES

    first = read_words(path, 1)
    second = read_words(path, 2)
    assert (first.gates, first.resolution_index) == (805, 0)
    assert (second.gates, second.resolution_index) == (403, 1)

    assert verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122), 1
    ).ok
    assert verify_stored_point(
        path, params_for(gates=403, rung=1, resolution_mm=0.243), 2
    ).ok
    # ... and the wrong channel is not silently accepted.
    assert not verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122), 2
    ).ok


def test_duck_typed_request_needs_no_parameterset(tmp_path: Path) -> None:
    """A plain object with the right attributes verifies; nothing is imported."""

    class Request:
        sound_speed_ms = SOUND_SPEED_MS
        first_gate_mm = FIRST_GATE_MM
        resolution_mm = 0.122
        gates = 805

    path = build_bdd(tmp_path / "duck.BDD", live_words(0, 805, 100))
    result = verify_stored_point(path, Request())
    assert result.ok, result.mismatches


def test_a_request_with_no_core_fields_cannot_read_as_fine(tmp_path: Path) -> None:
    """Absent request data is a reason, not silence (the codebase's rule)."""
    path = build_bdd(tmp_path / "empty_request.BDD", live_words(0, 805, 100))

    result = verify_stored_point(path, object())
    assert result.ok is False
    assert any(message.startswith("gates:") for message in result.mismatches)
    assert any(
        message.startswith("resolution_index:") for message in result.mismatches
    )
    assert any(message.startswith("depth_mm:") for message in result.mismatches)


# --------------------------------------------------------------------------- #
# The optional covariates.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("word", "value", "field"),
    (
        (5, 200, "prf_us"),
        (8, 8, "burst_length"),
        (19, 1500, "sound_speed_ms"),
    ),
)
def test_a_settled_covariate_disagreement_is_reported(
    tmp_path: Path, word: int, value: int, field: str
) -> None:
    """The dialog-only words a definition asserts about the instrument are checked."""
    words = live_words(0, 805, 100)
    words[(1, word)] = value
    path = build_bdd(tmp_path / f"cov_{field}.BDD", words)

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        check_covariates=True,
    )
    assert result.ok is False
    assert any(message.startswith(f"{field}:") for message in result.mismatches)


def test_an_emissions_disagreement_is_reported_as_an_advisory(tmp_path: Path) -> None:
    """The fourth word is carried in the file, read, and reported — not enforced."""
    words = live_words(0, 805, 100)
    words[(1, 14)] = 300
    path = build_bdd(tmp_path / "cov_emissions.BDD", words)

    result = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        check_covariates=True,
    )
    assert result.mismatches == ()
    assert result.ok is True
    assert any(
        message.startswith("emissions_per_profile:") for message in result.advisories
    )


def test_covariates_are_off_by_default(tmp_path: Path) -> None:
    """Word 14 is not enforced unless asked: a real point disagrees on it."""
    words = live_words(0, 805, 100)
    words[(1, 5)] = 200
    path = build_bdd(tmp_path / "no_covariates.BDD", words)

    default = verify_stored_point(
        path, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert default.ok is True
    assert default.facts.prf_us == 200  # read, and returned, but not enforced

    enforced = verify_stored_point(
        path,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        check_covariates=True,
    )
    assert enforced.ok is False
    assert any(message.startswith("prf_us:") for message in enforced.mismatches)


def test_unrequested_covariates_are_not_mismatches(tmp_path: Path) -> None:
    """A None covariate means "not asked for", so the file's word is not a fault."""
    words = live_words(0, 805, 100)
    words[(1, 5)] = 200
    words[(1, 14)] = 300
    path = build_bdd(tmp_path / "unrequested.BDD", words)

    request = ParameterSet(
        sound_speed_ms=SOUND_SPEED_MS,
        first_gate_mm=FIRST_GATE_MM,
        resolution_mm=0.122,
        gates=805,
    )
    result = verify_stored_point(path, request, check_covariates=True)
    assert result.ok, result.mismatches
    assert result.facts.prf_us == 200  # read, and no one asked to compare it


# --------------------------------------------------------------------------- #
# Real committed recordings (skipped when the fixture is not in this checkout).
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The rung-0, 805-gate point this sweep plans — 139,193 B of real recording.
REAL_RUNG0 = REPO_ROOT / "data/dop3010-velocity/sw100-k1-161738.BDD"

#: A c = 1500 point: 378 gates at rung 0 (0.125 mm), depth word 49.
REAL_C1500 = REPO_ROOT / "data/dop3010-velocity/sim-label-2.BDD"


def test_real_rung0_point_reads_the_live_words() -> None:
    if not REAL_RUNG0.is_file():
        pytest.skip(f"fixture not in this checkout: {REAL_RUNG0}")

    facts = read_words(REAL_RUNG0)
    assert facts == WordFacts(
        gates=805,
        resolution_index=0,
        resolution_mm=pytest.approx(RUNG_MM),
        depth_mm=100,
        sound_speed_ms=SOUND_SPEED_MS,
        prf_us=PRF_US,
        emissions_per_profile=EMISSIONS_PER_PROFILE,
        burst_length=BURST_LENGTH,
    )
    assert facts.missing_fields() == ()

    result = verify_stored_point(
        REAL_RUNG0, params_for(gates=805, rung=0, resolution_mm=0.122)
    )
    assert result.ok, result.mismatches

    # Word 2 (100) is the app's own derivation, not this module's floor (99.94);
    # that 0.06 mm is what the tolerance is for, and a tight one must fail it.
    assert not verify_stored_point(
        REAL_RUNG0,
        params_for(gates=805, rung=0, resolution_mm=0.122),
        depth_tolerance_mm=0.01,
    ).ok

    # Its words say emissions 150; a request of 52 cannot be confirmed by it — and
    # since what disagrees is the *declaration* (52 is the period law inverted, not an
    # instrument reading), the disagreement is an advisory on a point that still passes.
    declared = verify_stored_point(
        REAL_RUNG0,
        ParameterSet(
            sound_speed_ms=SOUND_SPEED_MS,
            first_gate_mm=FIRST_GATE_MM,
            resolution_mm=0.122,
            gates=805,
            emissions_per_profile=52,
        ),
        check_covariates=True,
    )
    assert declared.mismatches == ()
    assert declared.ok is True
    assert declared.advisories == (
        "emissions_per_profile: requested 52, found 150 in word 14",
    )


def test_real_c1500_point_verifies_against_its_plan() -> None:
    if not REAL_C1500.is_file():
        pytest.skip(f"fixture not in this checkout: {REAL_C1500}")

    facts = read_words(REAL_C1500)
    assert facts.gates == 378
    assert facts.resolution_index == 0
    assert facts.depth_mm == 49
    assert facts.sound_speed_ms == 1500
    assert facts.resolution_mm == pytest.approx(0.125)

    result = verify_stored_point(
        REAL_C1500,
        ParameterSet(
            sound_speed_ms=1500,
            first_gate_mm=FIRST_GATE_MM,
            resolution_mm=0.125,
            gates=378,
            prf_us=PRF_US,
            emissions_per_profile=EMISSIONS_PER_PROFILE,
            burst_length=BURST_LENGTH,
        ),
        check_covariates=True,
    )
    assert result.ok, result.mismatches
    # 2 + 378 x 0.125 = 49.25 mm: the file stores the floor, within 1.5 mm.
    assert abs(49.25 - facts.depth_mm) <= 1.5
