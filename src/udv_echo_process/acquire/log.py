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
from the point records — and, since the job boundary's one instrument write
needed a durable record of its own, from a **verified burst mutation** too
(``docs/dop3000/failed-invocation-provenance.md`` §O4). An entry type this build
does not know refuses the whole log rather than being read past: the log is the
record of a job, and a reader that skipped an entry it could not understand
would answer questions about a history it had silently shortened.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError

from udv_echo_process.acquire import plan
from udv_echo_process.acquire.actuator import BurstWriteResult
from udv_echo_process.acquire.config import (
    ParameterSet,
    ProfileTiming,
    RecordSettings,
)
from udv_echo_process.acquire.plan import SweepDefinition
from udv_echo_process.models.base import ValueModel

__all__ = [
    "KNOWN_RECORD_TYPES",
    "DecodedBlock",
    "PointStatus",
    "SizeSignature",
    "SweepBurstMutation",
    "SweepLogEntry",
    "SweepLogHeader",
    "SweepPointRecord",
    "append_entry",
    "burst_mutations",
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
    ``n_profiles``, ``span_s`` (last minus first) and ``achieved_period_s`` — the
    **full-span effective interval**, ``span_s / (n_profiles - 1)``. Those three are what
    the *window* actually was, as opposed to the window that was requested — the app's
    block is a ring, so a request for a longer window than the cap covers stores only the
    last ``cap × period`` seconds and still decodes as a valid point (docs/16 §15b).

    ``achieved_period_s`` is the full-span interval and not the median adjacent interval,
    following the convention :mod:`udv_echo_process.analysis.rpm` established for this
    timebase: the DOP timestamps are quantized, so the median adjacent interval is the
    dominant timestamp quantum rather than the sampling period, and calibrating on it
    shifted every recovered RPM by a measured 0.562% on the committed fixtures. The
    median is kept beside it as the diagnostic (``median_interval_s``) together with the
    regularity measure that module guards on (``interval_deviation``, the maximum
    relative deviation from the median). ``time_s`` is the quantised 0.1 ms footer
    timestamp, so all three are measurements at that resolution, not derivations.

    Using the full-span interval makes the window relation exact rather than
    approximate: ``span_s == (n_profiles - 1) × achieved_period_s``.

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
    #: Op word 27 — the stored **receiver-bandwidth-definition index**, carried as
    #: provenance beside the burst the file was recorded at (plan §B6). It is *not* the
    #: dialog's effective Sampling-volume thickness in millimetres and has no
    #: millimetre counterpart anywhere in this record: no reviewed relation turns the
    #: index into a length, and burst length can move that thickness while the index
    #: stays fixed (``1`` at burst 4/10/18 in every B4/B5 recording). The dialog's own
    #: effective-mm statement is the job boundary's evidence
    #: (``actuator.BurstWriteResult.after_sampling_volume``), not this field.
    bandwidth_definition_index: int | None = Field(default=None, ge=0)
    emissions_per_profile: int | None = Field(default=None, ge=1)
    source_freq_khz: float | None = Field(default=None, gt=0)
    size_bytes: int | None = Field(default=None, ge=0)
    #: Profiles the block actually holds — never "how many were asked for".
    n_profiles: int | None = Field(default=None, ge=1)
    #: Last minus first profile timestamp, in seconds. ``0`` for a single profile.
    span_s: float | None = Field(default=None, ge=0)
    #: **Full-span effective interval**, ``span_s / (n_profiles - 1)`` — the profile
    #: period this recording supports, and the convention ``analysis/rpm.py`` calibrates
    #: on (never the median adjacent interval; see the class docstring).
    achieved_period_s: float | None = Field(default=None, gt=0)
    #: The median adjacent interval, kept as a diagnostic: on a quantized timebase it is
    #: the dominant timestamp quantum rather than the period.
    median_interval_s: float | None = Field(default=None, gt=0)
    #: ``max(|interval - median_interval|) / median_interval`` — the regularity measure
    #: ``analysis/rpm.py`` refuses a structurally sampled axis on.
    interval_deviation: float | None = Field(default=None, ge=0)

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
    """The cheap BDD-contamination guard: container + depth block + signal blocks.

    The format itself gives the expectation (``io/dop/bdd.py``): 31,268 fixed bytes,
    one depth block of ``19 + 2*gates`` bytes, then one signal block of
    ``19 + gates`` bytes per profile. The complete sparse pass reproduces that equation
    byte-for-byte on all 26 files. The earlier payload-only calibration
    (``1.7*gates*profiles``) omitted the container; it tolerated ordinary blocks only
    because they carried many profiles, then falsely rejected the four valid
    emissions-128 files at 3.14x when their 144 profiles made the fixed bytes dominant.

    ``factor`` remains deliberately gross: the requested period predicts the profile
    count before storage, while the file's timestamps establish the achieved count only
    afterwards. A leftover recording stored under the next point's name was still more
    than 10x a normal point and remains outside the band.
    """

    container_bytes: int = Field(default=31_268, ge=0)
    block_overhead_bytes: int = Field(default=19, ge=0)
    depth_bytes_per_gate: float = Field(default=2.0, gt=0)
    bytes_per_gate_profile: float = Field(default=1.0, gt=0)
    factor: float = Field(default=2.0, ge=1)

    def expected_bytes(self, n_gates: int, profiles: int) -> int:
        """Expected BDD bytes for one depth block and ``profiles`` signal blocks."""
        if n_gates <= 0:
            raise ValueError(f"n_gates must be > 0, got {n_gates}")
        if profiles <= 0:
            raise ValueError(f"profiles must be > 0, got {profiles}")
        depth_block = self.block_overhead_bytes + self.depth_bytes_per_gate * n_gates
        signal_block = self.block_overhead_bytes + self.bytes_per_gate_profile * n_gates
        return round(self.container_bytes + depth_block + profiles * signal_block)

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
        than asked for and deserves investigation; it is not by itself a reason to refuse
        the point. The completed sparse pass retained 12.4651-12.5713 s for every 12 s
        request, disproving an earlier ~8.4 s ring-buffer interpretation.
        """
        span = self.stored_span_s
        if span is None or self.requested_duration_s is None:
            return None
        return span / self.requested_duration_s

    @property
    def expected_profiles(self) -> float | None:
        """Profiles the request implies: ``requested_duration_s / timing.target_s``.

        Derived from the plan's period law, so it is only as good as the plan's
        declaration — word 14 is the known case where that is not the instrument's own
        value. ``None`` when either input is missing.
        """
        target = self.timing.target_s
        if target is None or self.requested_duration_s is None:
            return None
        return self.requested_duration_s / target

    @property
    def block_at_cap(self) -> bool | None:
        """The stored profile count reached the declared cap — an observation, nothing more.

        Reaching the cap is compatible with the run having produced exactly that many
        profiles, so it is not on its own evidence that anything was overwritten. See
        :attr:`block_wrapped` for the claim; this is the fact.

        ``None`` when either the count or the cap is unknown — *not* ``False``, since
        "it did not reach the cap" is a claim the missing number cannot support.
        """
        profiles = self.stored_profiles
        if profiles is None or self.block_cap_profiles is None:
            return None
        return profiles >= self.block_cap_profiles

    @property
    def block_wrapped(self) -> bool | None:
        """True only when the block was over-produced *and* cut off at the cap.

        A wrap means profiles were produced and thrown away, which takes two facts: the
        stored count reached the cap, and the request implies more profiles than the cap
        could hold. Either one alone is not enough — a run that produced exactly the cap
        never overwrote anything, and its stored file looks identical to one that
        produced 40% more. Hence three answers rather than two:

        - ``False`` when the count is *below* the cap: nothing was retained past it, so
          nothing was lost, whatever the request implied;
        - ``True`` when the count is at the cap and the request implies more than the cap;
        - ``None`` otherwise — at the cap with no over-production evidence, or with a
          number missing. ``None`` is the honest answer at the boundary, where the count
          cannot distinguish "produced exactly the cap" from "produced more and wrapped".

        The cap is a declared setting rather than a live instrument fact until campaigns
        compile against a snapshot, so ``True`` is conditional on that declaration being
        right; the trigger for the property is the reader who needs to know whether early
        profiles are missing, and ``None`` says "not established".
        """
        at_cap = self.block_at_cap
        if at_cap is False:
            return False
        cap = self.block_cap_profiles
        expected = self.expected_profiles
        if at_cap is None or cap is None or expected is None:
            return None
        if expected > cap:
            return True
        return None

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


class SweepBurstMutation(ValueModel):
    """The job boundary's **verified burst transition**, appended where it happened.

    The boundary's write (:func:`~udv_echo_process.acquire.campaign._transit_burst_length`) is real
    the moment the application accepts it, while the job manifest — until this record existed, its
    only durable record — is written at the *end* of the invocation. Anything that refuses in
    between (the post-write compile, the resume-identity comparison; the boundary's own
    ``write -> verify -> compile -> record`` order) therefore left a real mutation in no artifact
    at all: no manifest was rewritten, the log held no entry for it, and the next invocation seeds
    its history from the *previous* manifest. The log is append-only and already per-job, so the
    verified transition is appended there instead, immediately after the write and before anything
    that can still refuse (``docs/dop3000/failed-invocation-provenance.md`` §O4, §5.1, §5.2).

    Three fields are decisions rather than descriptions:

    - ``mutation_id`` is the **occurrence identity**, a fresh uuid4 hex minted at the append. Two
      genuinely distinct mutations can be semantically identical — ``10 -> 18``, the instrument
      later returned to ``10``, ``10 -> 18`` again — and the job's ``burst_transitions`` is an
      *ordered history of occurrences*, not a set of distinct state changes. An identity derived
      from the transition's content (request plus the before/after rows plus the state) would
      silently collapse the second write into the first (§5.3);
    - ``occurred_at`` is when the instrument was moved, not when the invocation ended. It is what
      orders repeated identical transitions, and it is a local-time moment like a sweep id and a
      manifest's own stamps;
    - ``transition`` is the driver's own
      :class:`~udv_echo_process.acquire.actuator.BurstWriteResult` **verbatim**: the evidence, not
      a boolean — the request, the state, the dialog's own channel and mode, both rows on both
      sides of the write, the dependent sampling-volume statement, the refusal overlay and the
      reason.

    Only a ``VERIFIED`` transition is ever written here, because only a ``VERIFIED`` transition
    moved anything: ``UNCHANGED`` and ``UNVERIFIED`` kept nothing
    (:class:`~udv_echo_process.acquire.actuator.BurstState`), so neither is a mutation that needs a
    record and neither must ever be read as one.
    """

    record_type: Literal["burst_mutation"] = "burst_mutation"
    #: The **occurrence** identity — see the class docstring. Unique per mutation by construction,
    #: and never a function of what the mutation says.
    mutation_id: str = Field(min_length=1)
    #: When the instrument was moved (local time, the caller's ``local now``).
    occurred_at: datetime
    #: The job whose boundary spent the write (``CampaignDefinition.job``).
    job: str = Field(min_length=1)
    #: The definition's fingerprint (``campaign.campaign_fingerprint``): attribution without the
    #: manifest, which a refused invocation never writes.
    fingerprint: str = Field(min_length=1)
    #: The channel the run **routed** and the write was verified against. The transition carries the
    #: dialog's own channel field; this is the routing answer it was compared with, which is what
    #: makes the record tell the two apart. ``None`` only for a caller that routed nothing.
    routed_channel: int | None = None
    #: The driver's evidence, verbatim — the durable half of the mutation.
    transition: BurstWriteResult


#: Every ``record_type`` this build's :data:`SweepLogEntry` union can read. A log line whose type is
#: not one of these **refuses the log** (:func:`read_entries`) instead of being skipped: an
#: acquisition log is forward-schema, and an older checkout that read past an entry it could not
#: understand would resume — and report — on a history it had silently shortened (§O4).
KNOWN_RECORD_TYPES: tuple[str, ...] = ("sweep", "point", "burst_mutation")


#: One log line: a discriminated union on ``record_type``.
SweepLogEntry = Annotated[
    SweepLogHeader | SweepPointRecord | SweepBurstMutation,
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

    A malformed line raises, and so does a line whose ``record_type`` this build does not know: a
    log that cannot be parsed is worse to guess at than to fail on, and a log with an entry whose
    meaning this build cannot state is worse to read *past* — the reader would then answer
    questions about a job from a history it had silently shortened. Refusing the whole log is the
    honest answer to both, and the refusal names the file, the line and what it found
    (:data:`KNOWN_RECORD_TYPES`).
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no sweep log at {path}")
    entries: list[SweepLogEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            entries.append(_entry_from_line(line, path=path, number=number))
    return tuple(entries)


def _entry_from_line(line: str, *, path: Path, number: int) -> SweepLogEntry:
    """One line as an entry — or a :class:`ValueError` naming the file, the line and the problem.

    The union is discriminated on ``record_type``, so pydantic's own refusal for a type this build
    does not know is about a *tag* and says nothing about the log it came from. This makes the
    refusal explicit and keeps the two cases apart: an **unknown type** (which refuses on the
    policy §O4 chose) and a **damaged record** of a type this build does know (which refuses
    because a partly-understood record is not a record).
    """
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: line {number}: not JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise TypeError(
            f"{path}: line {number}: a log entry is a JSON object, not {type(payload).__name__}"
        )
    declared = payload.get("record_type")
    if declared not in KNOWN_RECORD_TYPES:
        raise ValueError(
            f"{path}: line {number}: record type {declared!r} is not one this build knows "
            f"({'|'.join(KNOWN_RECORD_TYPES)}): the log is refused rather than read past an entry "
            "whose meaning this build cannot state"
        )
    try:
        return _ENTRY_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise ValueError(
            f"{path}: line {number}: not a valid {declared!r} record: {exc}"
        ) from exc


def burst_mutations(entries: Iterable[SweepLogEntry]) -> tuple[SweepBurstMutation, ...]:
    """Only the burst-mutation records, in the order they were appended.

    The ordered history the boundary spent, read back: each entry is one *occurrence* (its own
    ``mutation_id``), so a caller that folds these into a job's history must consume one entry per
    transition in sequence and never key on the transition's content (§5.3).
    """
    return tuple(e for e in entries if isinstance(e, SweepBurstMutation))


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
