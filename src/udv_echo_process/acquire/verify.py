"""Read a stored point's *operation words* and verify the requested parameters.

A stored block can decode as a perfectly valid ``.BDD`` and still be the wrong
point. The app's buffer is a ring, so a short recording stores a full block made
of *stale* profiles from earlier points while the file stays structurally
perfect (docs/16 §15b; live: a 1.5 s point came back as 8,272,897 B because the
buffer still held ~6,000 profiles). File size and a successful decode therefore
cannot tell a good point from a bad one — the words that describe the *operation*
can. This module reads them and compares them with what was requested.

The committed reader :mod:`udv_echo_process.io.dop.bdd` exposes no operation
words (its decode leaves ``resolution_index`` and ``emissions`` ``None``), and
this module does not change it: the words are read here, directly, in four bytes
at a time.

Word map (verified on real files — uint32 little-endian, 256 words per channel,
stride 1024 B, channel 1 at byte offset 548, so word ``i`` of channel ``c`` is at
``548 + (c - 1) * 1024 + i * 4``)::

    2   depth in mm (the FLOOR of ``first_gate + gates x resolution``)
    5   PRF in microseconds
    8   burst length
    10  0-based resolution rung index; ``resolution_mm = (word10 + 1) * c / 12000``
    13  number of gates
    14  emissions per profile
    19  sound speed in m/s

Word 27 is a sampling-volume index (3 at c = 1460 m/s) whose identity is
unresolved; nothing here reads it.

The map was re-checked against the committed recordings on this checkout. The
rung-0 point ``data/dop3010-velocity/sw100-k1-161738.BDD`` (139,193 B) reads
gates 805, word10 0, word2 100, c 1460, PRF 169, word14 150, burst 4 — exactly
the live point recorded today; ``data/dop3010-velocity/sim-label-2.BDD`` reads
378 gates, word10 0, word2 49 at c 1500 (2 + 378 x 0.125 = 49.25, so the stored
word is the floor again); the 4-sensor and echo series all read gates 20, word10
5, word2 69, c 2740, PRF 250, word14 8, burst 4. One disagreement is worth
knowing about: the rung-0 805-gate point derives 99.94 mm and the app stored
**100**, so word 2 is the app's own derivation, not always the floor of this
module's arithmetic — which is why the depth check is a tolerance (1.5 mm
absorbs it) rather than an equality. The covariate words (5, 8, 14, 19) are
therefore read by default; the three a definition asserts about the instrument
(sound speed, PRF, burst — see :data:`ENFORCED_COVARIATES`) are *enforced* when
``check_covariates=True``, and word 14 (emissions per profile, the primary variance
axis) is compared into :attr:`VerificationResult.advisories` instead, because what
has disagreed about it so far was the plan, not the file.

Two rules follow from "a bad point must not read as fine":

- a *missing* word is never silently fine — a field that is absent from a short
  or truncated file is reported as unverifiable, which is ``ok=False``;
- the requested values are read with :func:`getattr`, so this works with the
  package's :class:`~udv_echo_process.acquire.config.ParameterSet` without
  importing it (no pydantic in the runner's path, no import cycle).

Nothing in this module raises on a missing, short or truncated file: the failure
is data, not an exception.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from udv_echo_process.acquire.config import RUNG_DIVISOR

__all__ = [
    "ADVISORY_COVARIATES",
    "CHANNEL_1_OFFSET_BYTES",
    "CHANNEL_STRIDE_BYTES",
    "ENFORCED_COVARIATES",
    "WORDS_PER_CHANNEL",
    "WORD_BURST_LENGTH",
    "WORD_DEPTH_MM",
    "WORD_EMISSIONS_PER_PROFILE",
    "WORD_GATES",
    "WORD_PRF_US",
    "WORD_RESOLUTION_INDEX",
    "WORD_SOUND_SPEED_MS",
    "VerificationResult",
    "WordFacts",
    "read_words",
    "verify_stored_point",
]

#: Byte offset of word 0 of channel 1 in a stored block.
CHANNEL_1_OFFSET_BYTES = 548

#: Distance between the same word of two neighbouring channels.
CHANNEL_STRIDE_BYTES = 1024

#: Words per channel (the stride is 256 uint32 words).
WORDS_PER_CHANNEL = 256

WORD_DEPTH_MM = 2
WORD_PRF_US = 5
WORD_BURST_LENGTH = 8
WORD_RESOLUTION_INDEX = 10
WORD_GATES = 13
WORD_EMISSIONS_PER_PROFILE = 14
WORD_SOUND_SPEED_MS = 19

#: Field name -> word index, for messages that must name the word they read.
_WORD_OF = {
    "depth_mm": WORD_DEPTH_MM,
    "prf_us": WORD_PRF_US,
    "burst_length": WORD_BURST_LENGTH,
    "resolution_index": WORD_RESOLUTION_INDEX,
    "gates": WORD_GATES,
    "emissions_per_profile": WORD_EMISSIONS_PER_PROFILE,
    "sound_speed_ms": WORD_SOUND_SPEED_MS,
}

#: Optional (dialog-only) parameters — the words the *application* holds, which a
#: request can neither write nor read back from the sidebar. Splitting them is the
#: point of this table: see :data:`ENFORCED_COVARIATES` and
#: :data:`ADVISORY_COVARIATES`.
ENFORCED_COVARIATES = (
    "sound_speed_ms",
    "prf_us",
    "burst_length",
)

#: Read, reported and returned, but **not** enforced: word 14
#: (``emissions_per_profile``). Its value in a definition is not an instrument
#: reading yet — it is derived from the period law to reproduce a stored profile
#: count (``52`` in ``test_acquire_runner.py`` is exactly that derivation), which is
#: why the committed point ``sw100-k1-161738.BDD`` stores 150 while the plan said 52.
#: Enforcing it would therefore refuse a point whose core words are all correct, for
#: a disagreement the *request* caused. It becomes enforceable when a campaign is
#: compiled against a live instrument snapshot instead of against a definition (the
#: review's Phase 6); until then its disagreement is an advisory on the record.
ADVISORY_COVARIATES = ("emissions_per_profile",)

_COVARIATES = ENFORCED_COVARIATES + ADVISORY_COVARIATES

#: The app writes integer microseconds; a requested value may carry a fraction.
PRF_TOLERANCE_US = 1.0


@dataclass(frozen=True)
class WordFacts:
    """What the stored words say. ``None`` means *not present*, never zero."""

    gates: int | None = None
    resolution_index: int | None = None
    resolution_mm: float | None = None
    depth_mm: int | None = None
    sound_speed_ms: int | None = None
    prf_us: int | None = None
    emissions_per_profile: int | None = None
    burst_length: int | None = None

    def missing_fields(self) -> tuple[str, ...]:
        """Names of the fields this file could not supply (absent or too short)."""
        return tuple(
            name for name in _WORD_OF if getattr(self, name) is None
        )


@dataclass(frozen=True)
class VerificationResult:
    """``ok`` is ``not mismatches``; every mismatch names field, request, found.

    ``advisories`` are comparisons that disagreed but are not enforced (see
    :data:`ADVISORY_COVARIATES`): they never affect ``ok`` and they are the reason a
    disagreement can be *recorded* without a good point being refused.
    ``enforced_covariates`` names the covariate fields this call enforced, so a
    reader of the log can tell "it agreed" from "nobody looked".
    """

    ok: bool
    mismatches: tuple[str, ...] = ()
    facts: WordFacts = WordFacts()
    advisories: tuple[str, ...] = ()
    enforced_covariates: tuple[str, ...] = ()


def _word_offset(word_index: int, channel: int) -> int:
    """Byte offset of word ``word_index`` of channel ``channel`` (1-based)."""
    return CHANNEL_1_OFFSET_BYTES + (channel - 1) * CHANNEL_STRIDE_BYTES + word_index * 4


def _read_word(handle: BinaryIO, word_index: int, channel: int) -> int | None:
    """One little-endian uint32, or ``None`` when the file ends before it."""
    try:
        handle.seek(_word_offset(word_index, channel))
    except (OSError, ValueError):  # negative offset from a nonsense channel
        return None
    raw = handle.read(4)
    if len(raw) != 4:
        return None
    return int(struct.unpack("<I", raw)[0])


def read_words(path: Path, channel: int = 1) -> WordFacts:
    """Read the operation words of ``path``; absent fields stay ``None``.

    Never raises: a missing file, an unreadable one or one that ends before a
    word all yield ``None`` for the fields the file could not supply, so the
    caller can tell "word says X" from "there is no word".

    ``channel`` addresses the operation table's own channel slot
    (``548 + (channel - 1) * 1024``), which is what a manual-mode acquisition's
    channel means. It is **not** a universal channel selector: on a multiplexed
    recording the table's slots do not describe the recording's channels — measured,
    ``data/4-sensor-velocity/200RPM.BDD`` reads slot 1 as gates 20 at c = 2740 while
    its own streams are channels 6..9 at 55 gates and c = 1460. A slot read that way
    returns a plausible table for a channel the file does not describe there, so a
    multiplexed file must be identified by its decoded streams, not by this table.
    """
    depth: int | None = None
    prf: int | None = None
    burst: int | None = None
    rung: int | None = None
    gates: int | None = None
    emissions: int | None = None
    sound_speed: int | None = None
    try:
        with Path(path).open("rb") as handle:
            depth = _read_word(handle, WORD_DEPTH_MM, channel)
            prf = _read_word(handle, WORD_PRF_US, channel)
            burst = _read_word(handle, WORD_BURST_LENGTH, channel)
            rung = _read_word(handle, WORD_RESOLUTION_INDEX, channel)
            gates = _read_word(handle, WORD_GATES, channel)
            emissions = _read_word(handle, WORD_EMISSIONS_PER_PROFILE, channel)
            sound_speed = _read_word(handle, WORD_SOUND_SPEED_MS, channel)
    except (OSError, ValueError):
        pass

    resolution_mm: float | None = None
    if rung is not None and sound_speed is not None and sound_speed > 0:
        resolution_mm = (rung + 1) * sound_speed / RUNG_DIVISOR

    return WordFacts(
        gates=gates,
        resolution_index=rung,
        resolution_mm=resolution_mm,
        depth_mm=depth,
        sound_speed_ms=sound_speed,
        prf_us=prf,
        emissions_per_profile=emissions,
        burst_length=burst,
    )


def _requested(parameters: object, name: str) -> object | None:
    """Duck-typed read of one requested parameter (``ParameterSet`` compatible)."""
    return getattr(parameters, name, None)


def _as_float(value: object) -> float | None:
    """``float(value)`` when that is meaningful, else ``None`` (no raise)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _number(value: float) -> str:
    """Compact rendering: ``805`` rather than ``805.0``, ``0.121667`` as is."""
    return f"{value:g}"


def _usable_sound_speed(*candidates: object) -> float | None:
    """First positive numeric candidate — the file's own word wins."""
    for candidate in candidates:
        number = _as_float(candidate)
        if number is not None and number > 0:
            return number
    return None


def _rung_index_for(resolution_mm: float, sound_speed_ms: float) -> int:
    """Invert ``resolution_mm = (index + 1) * c / 12000``: nearest rung, ties up.

    ``plan.nearest_rung_index`` documents that exact midpoints were never settled
    on the rig, so a tie here is not evidence of anything; half-up is taken and
    the result is clamped to rung 0 rather than raising on a nonsense request.
    """
    rungs = resolution_mm * RUNG_DIVISOR / sound_speed_ms
    return max(0, math.floor(rungs + 0.5) - 1)


def _compare_number(
    mismatches: list[str],
    *,
    field: str,
    requested: object | None,
    found: int | None,
    tolerance: float = 0.0,
    required: bool = False,
) -> None:
    """Record a request-vs-word disagreement for one scalar field."""
    word = _WORD_OF[field]
    if requested is None:
        if required:
            mismatches.append(
                f"{field}: nothing requested to compare with word {word} — "
                "the stored point cannot be confirmed"
            )
        return
    want = _as_float(requested)
    if want is None:
        mismatches.append(
            f"{field}: requested value {requested!r} is not a number — "
            f"cannot check word {word}"
        )
        return
    if found is None:
        mismatches.append(
            f"{field}: requested {_number(want)} but word {word} is not present "
            "in the stored file (missing or truncated)"
        )
        return
    if abs(want - float(found)) > tolerance:
        suffix = f" (tolerance {tolerance:g})" if tolerance else ""
        mismatches.append(
            f"{field}: requested {_number(want)}, found {found} in word {word}"
            f"{suffix}"
        )


def _check_depth(
    mismatches: list[str],
    *,
    requested_parameters: object,
    facts: WordFacts,
    sound_speed_ms: float | None,
    tolerance_mm: float,
) -> None:
    """Compare word 2 with the depth the *requested* window should have.

    The prediction is ``first_gate + gates x rung_pitch``: the app writes its own
    derived depth, and the pitch it uses is the *snapped* rung (the requested
    pitch is only a request — ``plan`` and docs/16 §12a), so the snapped rung,
    not the requested decimal, is what the prediction multiplies.
    """
    word = WORD_DEPTH_MM
    requested_resolution = _as_float(_requested(requested_parameters, "resolution_mm"))
    requested_gates = _as_float(_requested(requested_parameters, "gates"))
    requested_first_gate = _as_float(_requested(requested_parameters, "first_gate_mm"))

    if facts.depth_mm is None:
        mismatches.append(
            f"depth_mm: word {word} is not present in the stored file "
            "(missing or truncated) — the requested window was not confirmed"
        )
        return
    if requested_first_gate is None:
        mismatches.append(
            f"depth_mm: no first_gate_mm requested — cannot predict the window "
            f"depth to compare with word {word} (found {facts.depth_mm})"
        )
        return
    if requested_resolution is None or requested_gates is None:
        mismatches.append(
            "depth_mm: requested resolution_mm and gates are needed to predict "
            f"the window depth, so word {word} (found {facts.depth_mm}) is "
            "unconfirmed"
        )
        return
    if sound_speed_ms is None:
        mismatches.append(
            "depth_mm: no usable sound speed (word 19 absent and none requested) "
            "— the rung pitch is unknown, so the depth cannot be predicted"
        )
        return

    index = _rung_index_for(requested_resolution, sound_speed_ms)
    pitch_mm = (index + 1) * sound_speed_ms / RUNG_DIVISOR
    predicted_mm = requested_first_gate + requested_gates * pitch_mm
    if abs(predicted_mm - facts.depth_mm) > tolerance_mm:
        mismatches.append(
            f"depth_mm: requested {_number(predicted_mm)} "
            f"(first gate {_number(requested_first_gate)} + "
            f"{_number(requested_gates)} x {_number(pitch_mm)}), found "
            f"{facts.depth_mm} in word {word} (tolerance {tolerance_mm:g})"
        )


def verify_stored_point(
    path: Path,
    requested_parameters: object,
    channel: int = 1,
    *,
    depth_tolerance_mm: float = 1.5,
    check_covariates: bool = False,
) -> VerificationResult:
    """Verify a stored point's own words against the parameters requested.

    Checked, in order: gates exactly (word 13), the resolution rung the requested
    pitch inverts to (word 10), the window depth within ``depth_tolerance_mm``
    (word 2). Every disagreement and every *unverifiable* field becomes a string
    naming the field, the request and the found value.

    With ``check_covariates=True`` the dialog-only words are enforced as well:
    sound speed (word 19), PRF (word 5, within :data:`PRF_TOLERANCE_US`) and burst
    length (word 8) — the three a definition asserts about the *instrument*, and the
    three the six-point live campaign matched exactly (request 212 µs / 1460 m/s / 4
    against the stored words of every point). They are off by default for this
    module's own callers, which verify a *file*, not a run.

    Emissions per profile (word 14) is read, returned in :class:`WordFacts` and
    compared into :attr:`VerificationResult.advisories` — never into ``ok``. The
    disagreement that forced that decision is a real committed point
    (``sw100-k1-161738.BDD``, 805 gates at rung 0, all three core words as
    requested) storing word 14 = 150 against a plan that said 52; the 52 is the
    period law inverted to reproduce that recording's profile count, not a reading
    off the instrument, so the *request* is what is wrong. It becomes enforceable
    once a campaign compiles against a live snapshot instead of a definition.

    ``requested_parameters`` is duck-typed: ``gates``, ``resolution_mm``,
    ``first_gate_mm`` and the optional covariates are read with ``getattr``, so a
    :class:`~udv_echo_process.acquire.config.ParameterSet` works without this
    module importing it. A covariate that was not requested (``None``) is not a
    mismatch, but a missing *core* request is: an unconfirmable point is not a
    good point.

    ``depth_tolerance_mm`` defaults to 1.5 mm, which absorbs the two things that
    legitimately move word 2 off the requested decimal — the app stores the floor
    of its own derivation, and it derives from the snapped rung while the request
    is a 3-decimal display value.

    Never raises: a missing file is ``ok=False`` with a reason, because a point
    whose parameters cannot be confirmed must not read as fine.
    """
    tolerance_mm = abs(float(depth_tolerance_mm))
    mismatches: list[str] = []

    try:
        facts = read_words(path, channel)
    except (OSError, TypeError, ValueError, struct.error) as exc:
        # read_words promises not to raise, and by contract it cannot: this is
        # the belt-and-braces path for a path-like whose own ``open`` misbehaves.
        reason = f"{exc.__class__.__name__}: {exc}"
        return VerificationResult(
            ok=False,
            mismatches=(f"file: could not be read ({reason})",),
            facts=WordFacts(),
        )

    _compare_number(
        mismatches,
        field="gates",
        requested=_requested(requested_parameters, "gates"),
        found=facts.gates,
        required=True,
    )

    requested_resolution = _as_float(_requested(requested_parameters, "resolution_mm"))
    sound_speed = _usable_sound_speed(
        facts.sound_speed_ms, _requested(requested_parameters, "sound_speed_ms")
    )
    if requested_resolution is None:
        mismatches.append(
            "resolution_index: nothing requested to compare with word "
            f"{WORD_RESOLUTION_INDEX} — the rung the file was written at cannot "
            "be confirmed"
        )
    elif facts.resolution_index is None:
        mismatches.append(
            f"resolution_index: requested {_number(requested_resolution)} mm but "
            f"word {WORD_RESOLUTION_INDEX} is not present in the stored file "
            "(missing or truncated)"
        )
    elif sound_speed is None:
        mismatches.append(
            "resolution_index: no usable sound speed (word 19 absent and none "
            f"requested) — the requested pitch cannot be turned into a rung, so "
            f"word {WORD_RESOLUTION_INDEX} (found {facts.resolution_index}) is "
            "unconfirmed"
        )
    else:
        expected_index = _rung_index_for(requested_resolution, sound_speed)
        if expected_index != facts.resolution_index:
            achieved = (
                f"{_number(facts.resolution_mm)} mm"
                if facts.resolution_mm is not None
                else "unknown pitch"
            )
            expected_mm = (expected_index + 1) * sound_speed / RUNG_DIVISOR
            mismatches.append(
                f"resolution_index: requested {_number(requested_resolution)} mm "
                f"is rung {expected_index} "
                f"({_number(expected_mm)} mm), found rung "
                f"{facts.resolution_index} ({achieved}) in word "
                f"{WORD_RESOLUTION_INDEX}"
            )

    _check_depth(
        mismatches,
        requested_parameters=requested_parameters,
        facts=facts,
        sound_speed_ms=sound_speed,
        tolerance_mm=tolerance_mm,
    )

    enforced: tuple[str, ...] = ()
    if check_covariates:
        enforced = ENFORCED_COVARIATES
        for field in ENFORCED_COVARIATES:
            tolerance = PRF_TOLERANCE_US if field == "prf_us" else 0.0
            _compare_number(
                mismatches,
                field=field,
                requested=_requested(requested_parameters, field),
                found=getattr(facts, field),
                tolerance=tolerance,
            )

    # Read and reported even when not enforced: a disagreement the request caused is
    # evidence, and it is only visible at all if something writes it down.
    advisories: list[str] = []
    for field in ADVISORY_COVARIATES:
        _compare_number(
            advisories,
            field=field,
            requested=_requested(requested_parameters, field),
            found=getattr(facts, field),
        )

    return VerificationResult(
        ok=not mismatches,
        mismatches=tuple(mismatches),
        facts=facts,
        advisories=tuple(advisories),
        enforced_covariates=enforced,
    )
