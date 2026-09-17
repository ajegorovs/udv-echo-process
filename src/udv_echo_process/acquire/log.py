"""The experiment log: one JSONL record per point, requested vs achieved.

The log is the sweep's memory, and it is written for the *analysis*, not for the
run: the recon driver logged a per-point JSON line mixing the request, the
control read-back, the cycle result and the decoded block (docs/16 §12–§14a),
and that mix is exactly the three-way comparison worth keeping.

What the record must carry, and why:

- the **request** (``ParameterSet``) as planned;
- the **read-back** of the control text — the app's recomputation is silent but
  visible there (805 requested read ``474`` in the wrong write order), so a
  pre-record read-back catches a clamped point for free (docs/16 §14);
- the **timing**: target and achieved ``Time between profile``, because the
  period is an input constraint that sizes the block cap (docs/16 §15 item 3);
- the **stored file** and its decoded block — **the file is the authority, never
  the request** — including the **channel that was read**. The decoder has no
  safe default: reading the wrong channel's block is the easiest possible way to
  "prove" a write failed, and it happened once here (docs/16 §12/§12a).
- a **size signature** check. A leftover recording from a wedged cycle was later
  stored under the *next* point's name as a 1,039,825 B file — 10× a normal
  point — so a size far off the signature invalidates the point; that is the
  cheapest guard against silent contamination (docs/16 §15b).

Records are stored as JSONL so a run can append as it goes and a crash leaves
every completed point behind. A ``record_type`` literal discriminates the header
from the point records.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from udv_echo_process.acquire import plan
from udv_echo_process.acquire.config import (
    ParameterSet,
    ProfileTiming,
    RecordSettings,
)
from udv_echo_process.acquire.plan import SweepDefinition
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DecodedBlock",
    "PointStatus",
    "SizeSignature",
    "SweepLogEntry",
    "SweepLogHeader",
    "SweepPointRecord",
    "append_entry",
    "point_names",
    "point_records",
    "read_entries",
    "sweep_id_for",
]

#: Timestamp format of a sweep id (local time, sortable, no separator ambiguity).
SWEEP_ID_FORMAT = "%Y%m%dT%H%M%S"


class PointStatus(str, Enum):
    """How a point ended.

    ``INVALID`` is for a stored file that exists but cannot represent the
    intended window — a size off the signature, a cap/memory warning seen while
    recording, a leftover recording in the cycle. Those points are kept in the
    log (they are evidence) and excluded from analysis.
    """

    OK = "ok"
    FAILED = "failed"
    INVALID = "invalid"


class DecodedBlock(ValueModel):
    """The stored file's own parameter block for one channel — and its observation window.

    Words, as decoded from the file, for the channel that measured:

    - word 10 is the **0-based resolution rung index**, so the achieved pitch is
      ``(resolution_index + 1) × c / 12000`` (docs/16 §12a);
    - word 2 is the app's own **derived depth** in mm, the cheapest in-file check
      that the window arithmetic landed (docs/15 §2);
    - word 14 (``emissions_per_profile``) is the primary variance axis and word
      13 (``n_gates``) is the count actually used.

    The profile timestamps give the rest, and they are the only evidence for it:
    ``n_profiles``, ``span_s`` (last minus first) and ``achieved_period_s`` (the
    median interval). Those three are what the *window* actually was, as opposed to
    the window that was requested — the app's block is a ring, so a request for a
    longer window than the cap covers stores only the last ``cap × period`` seconds
    and still decodes as a valid point (docs/16 §15b). ``time_s`` is the quantised
    ms/10 footer timestamp, so ``achieved_period_s`` is a measurement at that
    resolution, not a derived quantity.

    ``channel`` and ``n_gates`` are required: a block that does not say which
    channel it came from is not evidence.
    """

    channel: int = Field(ge=1)
    n_gates: int = Field(ge=1)
    depth_mm: int | None = None
    resolution_index: int | None = Field(default=None, ge=0)
    resolution_mm: float | None = Field(default=None, gt=0)
    sound_speed_ms: float | None = Field(default=None, gt=0)
    #: PRF is a **period in µs** in this application (docs/07 §4 item 4).
    prf_us: float | None = Field(default=None, gt=0)
    burst_length: int | None = Field(default=None, ge=1)
    emissions_per_profile: int | None = Field(default=None, ge=1)
    source_freq_khz: float | None = Field(default=None, gt=0)
    size_bytes: int | None = Field(default=None, ge=0)
    #: Profiles the block actually holds — never "how many were asked for".
    n_profiles: int | None = Field(default=None, ge=1)
    #: Last minus first profile timestamp, in seconds. ``0`` for a single profile.
    span_s: float | None = Field(default=None, ge=0)
    #: Median interval between profile timestamps — the achieved period.
    achieved_period_s: float | None = Field(default=None, gt=0)

    @property
    def prf_hz(self) -> float | None:
        """The same PRF in Hz, for the tooling that speaks Hz."""
        if self.prf_us is None:
            return None
        return 1e6 / self.prf_us

    @property
    def achieved_resolution_mm(self) -> float | None:
        """Pitch derived from the rung index — the read-back formula in code."""
        if self.resolution_index is None or self.sound_speed_ms is None:
            return None
        return (self.resolution_index + 1) * self.sound_speed_ms / 12000.0

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object]) -> DecodedBlock:
        """Build from a decoded-word mapping, ignoring keys this model lacks.

        Tolerant on purpose: the reader in ``io/dop`` is free to grow words
        without a matching change here, and an unknown key must not turn a real
        recording into a log failure. Declared fields are validated as usual.
        """
        declared = set(cls.model_fields)
        return cls(
            **{name: value for name, value in mapping.items() if name in declared}
        )


class SizeSignature(ValueModel):
    """The cheap contamination guard: bytes per gate-profile, with a factor.

    Calibrated on the recorded points: 805 gates over ~71 profiles (1.5 s at a
    21.2 ms period) produced 97,993 B and 97,169 B — 1.71 and 1.70 bytes per
    gate-profile. A file off by more than ``factor`` is not this point's data
    (the leftover-recording case was 10× the signature).
    """

    bytes_per_gate_profile: float = Field(default=1.7, gt=0)
    factor: float = Field(default=2.0, ge=1)

    def expected_bytes(self, n_gates: int, profiles: int) -> int:
        """Expected file size in bytes for a block of ``profiles`` × gates."""
        if n_gates <= 0:
            raise ValueError(f"n_gates must be > 0, got {n_gates}")
        if profiles <= 0:
            raise ValueError(f"profiles must be > 0, got {profiles}")
        return round(self.bytes_per_gate_profile * n_gates * profiles)

    def ratio(self, size_bytes: int, n_gates: int, profiles: int) -> float:
        """Observed size over the expected size."""
        return size_bytes / self.expected_bytes(n_gates, profiles)

    def matches(self, size_bytes: int, n_gates: int, profiles: int) -> bool:
        """True when the size is within ``1/factor .. factor`` of expected."""
        return (
            1.0 / self.factor
            <= self.ratio(size_bytes, n_gates, profiles)
            <= self.factor
        )


class SweepLogHeader(ValueModel):
    """The first line of a sweep's log: what the run was.

    Carries the sound speed the plan was computed from, the first gate read from
    the app, ``T`` and the rung list, so a later reader can recompute the ladder
    and the expected rung index of every point without the plan file.
    """

    record_type: Literal["sweep"] = "sweep"
    sweep_id: str
    sound_speed_ms: float = Field(gt=0)
    first_gate_mm: float = Field(ge=0)
    target_depth_mm: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    rungs: tuple[int, ...]
    capture_dir: str
    name_prefix: str
    max_profiles_per_block: int = Field(ge=1)

    @classmethod
    def from_definition(
        cls,
        sweep_id: str,
        definition: SweepDefinition,
        settings: RecordSettings,
    ) -> SweepLogHeader:
        """Describe a sweep from the definition it will run."""
        return cls(
            sweep_id=sweep_id,
            sound_speed_ms=definition.sound_speed_ms,
            first_gate_mm=definition.first_gate_mm,
            target_depth_mm=definition.target_depth_mm,
            duration_s=definition.duration_s,
            rungs=definition.rungs,
            capture_dir=settings.capture_dir,
            name_prefix=settings.name_prefix,
            max_profiles_per_block=settings.max_profiles_per_block,
        )


class SweepPointRecord(ValueModel):
    """One point: requested, read back, stored, decoded — or how it failed."""

    record_type: Literal["point"] = "point"
    sweep_id: str
    key: int = Field(ge=1)
    name: str
    status: PointStatus
    requested: ParameterSet
    timing: ProfileTiming = Field(default_factory=ProfileTiming)
    #: The window that was *asked* for, in seconds. Carried because the retained
    #: fraction is meaningless without it, and neither the request nor the file has it.
    requested_duration_s: float | None = Field(default=None, gt=0)
    #: The block cap in force at this point, so a wrapped block is legible from the log.
    block_cap_profiles: int | None = Field(default=None, ge=1)
    readback_gates: int | None = Field(default=None, ge=0)
    readback_resolution: str | None = None
    file_path: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)
    expected_size_bytes: int | None = Field(default=None, ge=0)
    decoded: DecodedBlock | None = None
    failure: str | None = None
    #: Covariate fields the word-level check *compared* for this point. Empty means
    #: nobody looked — the difference between "it agreed" and "it was never compared".
    covariates_enforced: tuple[str, ...] = ()
    #: Comparisons that disagreed and were deliberately **not** enforced (word 14,
    #: emissions per profile: the declaration is derived, not read off the instrument).
    #: An advisory never invalidates a point; it is here so the disagreement survives
    #: in the record instead of being invisible.
    covariate_advisories: tuple[str, ...] = ()
    #: The covariate fields the check compared *without* enforcing. Read beside
    #: ``covariate_advisories``: a declared field missing from the advisories agreed,
    #: while a field missing from *both* lists was never declared and never compared.
    covariates_advisory: tuple[str, ...] = ()

    @property
    def stored_profiles(self) -> int | None:
        """Profiles the stored block holds; ``None`` when no file was decoded."""
        return None if self.decoded is None else self.decoded.n_profiles

    @property
    def stored_span_s(self) -> float | None:
        """Seconds the stored profiles actually cover; ``None`` when unknown."""
        return None if self.decoded is None else self.decoded.span_s

    @property
    def retained_fraction(self) -> float | None:
        """Stored span over requested window — what the request actually bought.

        ``None`` when either side is unknown. Below 1 means the observation is shorter
        than asked for, which is the app's ring behaviour once the profile count crosses
        the block cap; it is not by itself a reason to refuse the point (the 12 s
        request that stores ~8.4 s is the project's own operating point).
        """
        span = self.stored_span_s
        if span is None or self.requested_duration_s is None:
            return None
        return span / self.requested_duration_s

    @property
    def block_wrapped(self) -> bool | None:
        """True when the stored profile count reached the cap, so the block wrapped.

        ``None`` when either the count or the cap is unknown — *not* ``False``, since
        "it did not wrap" is a claim the missing number cannot support.
        """
        profiles = self.stored_profiles
        if profiles is None or self.block_cap_profiles is None:
            return None
        return profiles >= self.block_cap_profiles

    @property
    def gate_drift(self) -> float | None:
        """Relative gate move the read-back showed; ``None`` if not read back."""
        if self.readback_gates is None:
            return None
        return plan.gate_drift(self.requested.gates, self.readback_gates)

    def gates_clamped(self, threshold: float = plan.GATE_DRIFT_NOTE) -> bool:
        """True when the read-back moved the gate count beyond ``threshold``."""
        drift = self.gate_drift
        return drift is not None and abs(drift) > threshold

    @property
    def size_ratio(self) -> float | None:
        """Stored size over expected size; ``None`` when either is missing."""
        if self.file_size_bytes is None or not self.expected_size_bytes:
            return None
        return self.file_size_bytes / self.expected_size_bytes

    def size_is_plausible(self, signature: SizeSignature | None = None) -> bool | None:
        """Whether the stored size matches the signature; ``None`` if unchecked.

        ``None`` means *unchecked*, never *fine* — a point that was never sized
        has no evidence either way.
        """
        ratio = self.size_ratio
        if ratio is None:
            return None
        sig = signature if signature is not None else SizeSignature()
        return 1.0 / sig.factor <= ratio <= sig.factor


#: One log line: a discriminated union on ``record_type``.
SweepLogEntry = Annotated[
    SweepLogHeader | SweepPointRecord,
    Field(discriminator="record_type"),
]

_ENTRY_ADAPTER: TypeAdapter[SweepLogEntry] = TypeAdapter(SweepLogEntry)


def sweep_id_for(moment: datetime) -> str:
    """The sweep id for a moment: reused as both run id and file-name stamp.

    Passed in rather than read from the clock so the log and the names are
    reproducible in tests, and so a resumed sweep can keep its original id. The
    id is the moment's wall-clock time and carries no offset, so the caller
    supplies a local-time moment (an aware one is accepted unchanged).
    """
    return moment.strftime(SWEEP_ID_FORMAT)


def append_entry(path: Path, entry: SweepLogEntry) -> None:
    """Append one record as a single JSONL line (UTF-8, newline-terminated).

    Create-or-append: a run keeps writing after a crash, and the parent
    directory is created on demand.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json())
        handle.write("\n")


def read_entries(path: Path) -> tuple[SweepLogEntry, ...]:
    """Read every record back, in order; blank lines are skipped.

    A malformed line raises — a log that cannot be parsed is worse to guess at
    than to fail on.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no sweep log at {path}")
    entries: list[SweepLogEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            entries.append(_ENTRY_ADAPTER.validate_python(json.loads(line)))
    return tuple(entries)


def point_records(entries: Iterable[SweepLogEntry]) -> tuple[SweepPointRecord, ...]:
    """Only the point records, dropping the header(s)."""
    return tuple(e for e in entries if isinstance(e, SweepPointRecord))


def point_names(entries: Iterable[SweepLogEntry]) -> frozenset[str]:
    """Every point name already used — the input to ``RecordSettings.next_name``.

    Reusing a name raises the Store dialog's ``file already exists`` warning,
    which wedges the app modal when nothing answers it (docs/16 §12b), so the
    names a run may use come from the log rather than from memory.
    """
    return frozenset(record.name for record in point_records(entries))
