"""Offline verification of one stored multiplexed `.BDD` against a completed-block declaration.

This is the **artifact** half of the multiplexed store path: it reads and decodes one
already-stored file, it never touches the instrument, it opens no window and it writes
nothing. The declaration is the same :class:`CompletedBlockDeclaration` the store path
takes, and it is validated *before* the file is hashed or decoded, so an invalid
statement costs no decode and produces no claim.

What a verdict means
--------------------

The declaration states a channel set, a profile count and — on the repeated basis — a
per-visit count with a repeat count. So the exact decoded channel set and the stored
profile count per channel are compared, and a repeated declaration is additionally
compared with the reader's **stored container partition**, projected per channel and
per quantity into *runs*: maximal contiguous stretches of the file's own measurement
containers that carry the same stored vendor block/sequence word. A block, in this
module's reports, always means one such run — never a physical acquisition, round or
visit. The result is one typed clause per comparison:

``CONSISTENT``
    The declared set/count equals what the decoded file holds.
``CONTRADICTED``
    Both facts are known and disagree.
``UNVERIFIABLE``
    A fact could not be established (a declared channel absent from the file, an
    undeclared channel with nothing to compare, more than one decoded stream for one
    channel, or non-finite cells whose summary would be misleading).
``UNREADABLE``
    The file could not be read, decoded, or kept the same content digest across the read.

``UNREADABLE`` is one status for several different situations, and the note is the only
thing that separates them: the path could not be opened, the existing decoder refused
the bytes, or something changed underneath the read. The decoder exposes **no typed
decode error** — it reports "these bytes are not a DOP3000 ``.BDD`` file", a failed
gate/depth cross-check and other integrity refusals alike as ``ValueError`` — so this
command does not claim to distinguish an unsupported *format* from a failed *integrity*
check from an internal *decoder* failure. It keeps the decoder's own words as the reason
instead of classifying them, and a decode failure is never evidence that the file is
corrupt.

Deliberate limits
-----------------

* **No order and no rolling.** The existing model decodes ``AcquisitionMode.SEQUENTIAL``
  from the multiplexer-enable bit and ``UNKNOWN`` otherwise. Sequential emission is not
  evidence of channel order, and roll-over is a runtime option the file does not store.
  Stored block/sequence words and timestamps are reported as stored facts only: the
  manual documents the footer word as a block/sequence number — it is not proof that a
  physical event was acquired — so no round, visit or roll identity is derived from it,
  from timestamps, or from decode order.
* **No word is parsed here.** The stored count compared here is the number of decoded
  profile rows in that channel's own stream, and the container partition is the owning
  reader's ``ProfileContainerEvidence`` from the same single read. A truncated file can
  decode fewer complete containers and is reported as a contradicted count, not as a
  corrupt-file claim.
* **Runs are never merged across a reuse.** Containers sharing one stored word are a
  single run only when they are contiguous in the channel's own container order.
  Per-channel projection tolerates the other channels' containers between them, but a
  word that reappears after a different word is a *reused* number, not more of the same
  block: the partition is then reported unknown rather than summed into a convenient
  total.
* **Zero is signal.** A stream of all zeros is reported with ``abs_max == 0.0``; it is
  not a failure, not a quality grade, and never a statement about the target ("no
  returns" is a physical claim this command does not make).
* **Streams are never merged.** Streams are reported individually and keyed by channel
  *and* quantity; no profile count is merged, overwritten or compared as if two
  quantities were one measurement. Two streams for one channel are *not* assumed to be
  two quantities: a repeated quantity is reported as a repeated quantity (the decoder
  did not report one stream per channel), which is a different fact from two genuinely
  different quantities.
* **The time figure is a span, not coverage.** ``time_span_s`` is the difference
  between the first and last decoded sample times. It is not the requested or expected
  duration, and it says nothing about missing profiles, gaps or completeness.
* **Identity is the content digest, streamed.** The file is hashed through one open
  handle before and after the existing decoder reads it (``hashlib.file_digest``, no
  whole-file buffer), the ``fstat`` identity of those reads is compared, and the
  decoder's own content digest and byte size must equal the hashed digest and size.
  Both sides' actual digests are reported when they disagree. If the bytes moved, the
  report is ``UNREADABLE`` and no clause is called consistent.
"""

from __future__ import annotations

import hashlib
import os
import struct
from enum import Enum
from pathlib import Path

import numpy as np
from pydantic import Field

from udv_echo_process.acquire.store_completed import (
    CompletedBlockDeclaration,
    ProfileCountBasis,
)
from udv_echo_process.io.dop import bdd as bdd_reader
from udv_echo_process.io.dop.bdd import ProfileContainerEvidence
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.signal import ChannelArtifact
from udv_echo_process.provenance import ArtifactBundle

__all__ = [
    "MpxArtifactReport",
    "MpxBlockRun",
    "MpxChannelBlockReport",
    "MpxClause",
    "MpxRepeatVerification",
    "MpxStreamReport",
    "MpxVerdict",
    "verify_mpx_artifact",
]

#: What the existing reader can raise for bytes it will not decode. It has **no typed
#: decode error**: ``ValueError`` covers "not a .BDD file", gate/depth disagreement and
#: pydantic validation; ``struct.error`` and ``IndexError`` escape the fixed-header
#: buffer on a truncated file. This tuple is a containment boundary, not a classifier —
#: see the module docstring on why ``UNREADABLE`` does not name which of those happened.
_DECODE_ERRORS = (ValueError, OSError, struct.error, IndexError)


class MpxVerdict(str, Enum):
    """What one artifact check established about the declaration."""

    CONSISTENT = "consistent"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"
    UNREADABLE = "unreadable"


class MpxRepeatVerification(str, Enum):
    """What the check established about the declared repeat count.

    A repeated declaration is compared against the reader's **stored container
    partition**, projected per channel and quantity into runs of contiguous
    containers sharing one stored block/sequence word. It is never compared
    against a visit identity: the format documents that footer word as a
    block/sequence number, so ``PARTITION_CONSISTENT`` means "the stored runs
    split the rows the declaration says", not "M visits ran".
    """

    #: The declaration stated no repeat count, so nothing is claimed about visits.
    NOT_DECLARED = "not-declared"
    #: A repeat count was stated, but the stored containers do not settle the partition
    #: (one run, an unreadable word, a reused non-contiguous word, mixed quantities,
    #: or channels whose ordered run sequences differ).
    UNKNOWN = "unknown"
    #: The stored runs match the stated repeats x per-visit split.
    PARTITION_CONSISTENT = "partition-consistent"
    #: The stored runs contradict the stated repeats x per-visit split.
    PARTITION_CONTRADICTED = "partition-contradicted"


class MpxClause(ValueModel):
    """One typed comparison result, with both sides kept when both are numbers."""

    subject: str
    status: MpxVerdict
    detail: str
    expected: int | None = None
    observed: int | None = None


class MpxStreamReport(ValueModel):
    """One decoded stream's honest, non-graded summary.

    ``profiles`` is the decoded row count, ``gates`` the decoded gate count. The value
    counts are over finite cells only; ``nonzero_samples`` counts rows with at least one
    finite nonzero value. ``abs_max`` is over finite cells and is ``None`` when no cell
    is finite — it is never a quality grade and an all-zero stream reports ``0.0``.
    """

    channel: int
    quantity: str
    unit: str
    profiles: int = Field(ge=0)
    gates: int = Field(ge=0)
    time_start_s: float | None = None
    time_end_s: float | None = None
    #: Last decoded sample time minus first: a span, never a completeness claim.
    time_span_s: float | None = None
    finite_values: int = Field(ge=0)
    non_finite_values: int = Field(ge=0)
    nonzero_samples: int = Field(ge=0)
    nonzero_values: int = Field(ge=0)
    abs_max: float | None = None


class MpxBlockRun(ValueModel):
    """One run of contiguous stored containers sharing a block/sequence word.

    A run is the module's unit of report-level "block": maximal consecutive
    containers (in that channel's own container order, so other channels'
    containers between them are ignored) that carry the **same** stored word for
    one quantity. ``block_number`` is that raw stored word; ``None`` when the
    run's own container footers did not carry an identity. ``containers`` and
    ``source_ordinals`` keep the reader's source evidence, so a reviewer can see
    which containers were merged into the run and how many rows it holds.

    A word that reappears after a different word starts a *new* run and is never
    merged with the earlier one: reuse is reported, not summed away. Counts are
    never summed across quantities.
    """

    channel: int
    quantity: str
    block_number: int | None
    containers: int = Field(ge=0)
    source_ordinals: tuple[int, ...] = ()
    profiles: int = Field(ge=0)


class MpxChannelBlockReport(ValueModel):
    """One channel's stored container partition beside its **configured** block words.

    ``groups`` are the channel's runs in source order, per quantity.
    ``stored_block_numbers`` lists the runs' stored words in first-run order, so a
    reused word appears once here while ``len(groups)`` shows the reuse.
    ``blocks_with_unknown_number`` counts runs whose stored word was absent.

    ``configured_containers_in_mode`` is op word 53 ("Nb blocks in multiplexer
    mode") and ``configured_profiles_per_container`` is op word 51 ("Nb profiles
    in block in multiplexer mode") — the vendor's configured words, reported
    separately from the containers the file actually stores. They are never
    substituted for the observed partition and never used as a divisor.
    """

    channel: int
    groups: tuple[MpxBlockRun, ...] = ()
    stored_block_numbers: tuple[int, ...] = ()
    blocks_with_unknown_number: int = Field(ge=0)
    configured_containers_in_mode: int | None = None
    configured_profiles_per_container: int | None = None


class MpxArtifactReport(ValueModel):
    """The whole check: file identity, decoded streams, clauses and one verdict."""

    file_name: str
    file_sha256: str | None
    byte_size: int | None
    identity_verified: bool
    identity_note: str
    acquisition_mode: str
    mode_note: str
    declared_channels: tuple[int, ...]
    #: The operator's stated **total** per channel, or ``None`` when the count is stated as a
    #: per-visit count and a repeat count instead. Never a decoded fact.
    declared_profiles_per_channel: int | None
    #: The expected stored total per channel, normalized once by the declaration: the stated
    #: total on the legacy basis, or ``per_visit * repeats`` — the operator's arithmetic, not a
    #: decoding of what happened.
    expected_total_profiles: int
    decoded_channels: tuple[int, ...]
    streams: tuple[MpxStreamReport, ...] = ()
    #: The reader's stored container partition per channel, as runs beside the
    #: configured block words it reports separately. Empty when nothing could be
    #: decoded.
    block_partition: tuple[MpxChannelBlockReport, ...] = ()
    #: The operator's stated per-visit count (``None`` on the legacy total basis).
    declared_profiles_per_visit: int | None = None
    #: The operator's stated repeat count (``None`` when no repeat was declared).
    declared_sequence_repeats: int | None = None
    count_basis: ProfileCountBasis = ProfileCountBasis.STATED_TOTAL
    #: Whether the stored container partition could be compared. ``unknown`` when repeats
    #: were declared but the partition is unsettled (one run, an unknown stored word, a
    #: reused non-contiguous word, more than one quantity, or differing run sequences).
    repeat_verification: MpxRepeatVerification = MpxRepeatVerification.NOT_DECLARED
    #: The repeat unknown in words, empty on the legacy basis.
    repeat_note: str = ""
    clauses: tuple[MpxClause, ...] = ()
    verdict: MpxVerdict

    def summary(self) -> str:
        """One line for a person; every enum is interpolated by ``.value``."""
        identity = "verified" if self.identity_verified else "NOT verified"
        head = (
            f"{self.file_name}: {self.verdict.value}; sha256 "
            f"{self.file_sha256 or 'unknown'}; {self.byte_size} bytes; identity "
            f"{identity}; mode {self.acquisition_mode}"
        )
        if self.repeat_verification is MpxRepeatVerification.UNKNOWN:
            head += (
                f"; expected total {self.expected_total_profiles} per channel from "
                f"{self.declared_sequence_repeats} repeat(s) x "
                f"{self.declared_profiles_per_visit} per visit (operator-stated arithmetic); "
                "stored container partition unknown"
            )
        elif self.repeat_verification is not MpxRepeatVerification.NOT_DECLARED:
            head += (
                f"; expected split {self.declared_sequence_repeats} run(s) x "
                f"{self.declared_profiles_per_visit} profile(s) per channel; stored "
                f"container partition {self.repeat_verification.value} (block/sequence "
                "words, not a visit law)"
            )
        if not self.streams:
            return f"{head}; {self.identity_note}"
        streams = "; ".join(
            f"ch {stream.channel} {stream.quantity} {stream.profiles} profiles x "
            f"{stream.gates} gates, "
            + (
                "time unknown"
                if stream.time_span_s is None
                else f"span {stream.time_span_s:.4g} s"
            )
            + (
                ", abs_max unknown"
                if stream.abs_max is None
                else f", abs_max {stream.abs_max:.6g} {stream.unit}"
            )
            + (
                f", {stream.non_finite_values} non-finite"
                if stream.non_finite_values
                else ""
            )
            for stream in self.streams
        )
        return f"{head}; decoded channels {list(self.decoded_channels)}; {streams}"


def _unreadable(
    path: Path,
    declaration: CompletedBlockDeclaration,
    *,
    sha256: str | None,
    byte_size: int | None,
    note: str,
) -> MpxArtifactReport:
    """A report that establishes nothing and says so once."""
    return MpxArtifactReport(
        file_name=path.name,
        file_sha256=sha256,
        byte_size=byte_size,
        identity_verified=False,
        identity_note=note,
        acquisition_mode="unknown",
        mode_note="not decoded",
        declared_channels=tuple(sorted(declaration.channels)),
        declared_profiles_per_channel=declaration.profiles_per_channel,
        expected_total_profiles=declaration.expected_total_profiles,
        decoded_channels=(),
        declared_profiles_per_visit=declaration.profiles_per_visit,
        declared_sequence_repeats=declaration.sequence_repeats,
        count_basis=declaration.count_basis,
        repeat_verification=(
            MpxRepeatVerification.NOT_DECLARED
            if declaration.sequence_repeats is None
            else MpxRepeatVerification.UNKNOWN
        ),
        repeat_note=declaration.repeat_verification_unknown,
        clauses=(MpxClause(subject="file", status=MpxVerdict.UNREADABLE, detail=note),),
        verdict=MpxVerdict.UNREADABLE,
    )


def _streamed_identity(target: Path) -> tuple[str, os.stat_result]:
    """Hash one file through a single open handle and stat that same handle.

    Streamed on purpose: a recording is not bounded by memory, so the digest is taken by
    :func:`hashlib.file_digest` over the open handle rather than by reading the whole
    file into a buffer. The ``fstat`` describes the very handle that was hashed, so the
    metadata and the digest belong to the same open file.

    Returns:
        The lower-case hex SHA-256 of the bytes read and that handle's stat.
    """
    with target.open("rb") as handle:
        info = os.fstat(handle.fileno())
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    return sha256, info


def _stat_identity(info: os.stat_result) -> str:
    """The stat fields compared across both reads, for a note a person can check."""
    return (
        f"device {info.st_dev}, inode {info.st_ino}, {info.st_size} bytes, "
        f"mtime_ns {info.st_mtime_ns}"
    )


def _same_stat(before: os.stat_result, after: os.stat_result) -> bool:
    """Whether both reads opened the same file object with the same size and mtime."""
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def _decode(target: Path) -> tuple[ArtifactBundle, ProfileContainerEvidence]:
    """Decode one file through the owning reader: bundle plus container evidence.

    One seam, one read. The reader parses every word; this module only consumes
    its facts, so no block/word interpretation lives here.
    """
    return bdd_reader.read_with_containers(target)


def verify_mpx_artifact(
    path: Path | str, declaration: CompletedBlockDeclaration
) -> MpxArtifactReport:
    """Verify one stored `.BDD` against a completed-block declaration.

    The declaration is judged first (raising :class:`ValueError` with its refused
    clauses, before any read). The file is then streamed through SHA-256 and stat'ed,
    decoded by the existing :func:`udv_echo_process.io.load`, and streamed and stat'ed
    again: changed bytes, a changed stat identity or a decoder content identity that
    disagrees with either read yields an ``UNREADABLE`` report and no consistent claim.
    The decoder is not modified and no private word parser is used, so a decode refusal
    arrives as whatever the reader raised (``ValueError`` today) and is kept verbatim.

    Args:
        path: the stored measurement file to verify.
        declaration: the operator's stated channels and per-channel profile count.

    Returns:
        A typed report whose ``verdict`` is ``consistent``, ``contradicted``,
        ``unverifiable`` or ``unreadable``.

    Raises:
        ValueError: the declaration itself is not a valid completed-block statement.
            Nothing is read or decoded in that case.
    """
    refused = declaration.clauses()
    if refused:
        raise ValueError("; ".join(refused))

    target = Path(path)
    try:
        sha_before, stat_before = _streamed_identity(target)
    except OSError as exc:
        return _unreadable(
            target,
            declaration,
            sha256=None,
            byte_size=None,
            note=f"cannot read the file: {exc}",
        )
    size_before = int(stat_before.st_size)

    try:
        # The decoder owns both facts: the bundle it always produced and its own
        # per-block account of the same bytes. No word parsing happens here.
        bundle, evidence = _decode(target)
    except _DECODE_ERRORS as exc:
        return _unreadable(
            target,
            declaration,
            sha256=sha_before,
            byte_size=size_before,
            note=(
                f"decode failed ({type(exc).__name__}): {exc}; the decoder does not say "
                "whether this is an unsupported format, a failed integrity check or an "
                "internal failure, and a decode failure is not proof of corruption"
            ),
        )

    try:
        sha_after, stat_after = _streamed_identity(target)
    except OSError as exc:
        return _unreadable(
            target,
            declaration,
            sha256=sha_before,
            byte_size=size_before,
            note=f"the file could not be re-read after decode: {exc}",
        )
    if sha_before != sha_after:
        return _unreadable(
            target,
            declaration,
            sha256=sha_before,
            byte_size=size_before,
            note=(
                "the file's streamed content digest changed while it was being verified: "
                f"{sha_before} -> {sha_after} "
                f"({_stat_identity(stat_before)} -> {_stat_identity(stat_after)}); "
                "no claim is verified against replaced bytes"
            ),
        )

    asset = bundle.recording.source_asset
    if asset.content_sha256 != sha_before or asset.byte_size != size_before:
        return _unreadable(
            target,
            declaration,
            sha256=sha_before,
            byte_size=size_before,
            note=(
                "the decoder's own content identity disagrees with the streamed bytes: "
                f"decoder states sha256 {asset.content_sha256}, {asset.byte_size} bytes; "
                f"both streamed reads gave sha256 {sha_before}, {size_before} bytes"
            ),
        )

    return _report_from_bundle(
        target,
        bundle,
        declaration,
        evidence=evidence,
        sha256=sha_before,
        byte_size=size_before,
        stat_note=(
            f"{_stat_identity(stat_before)} (identical on both reads)"
            if _same_stat(stat_before, stat_after)
            else (
                f"{_stat_identity(stat_before)} -> {_stat_identity(stat_after)}: the stat "
                "identity changed while the content digest did not"
            )
        ),
    )


def _report_from_bundle(
    path: Path,
    bundle: ArtifactBundle,
    declaration: CompletedBlockDeclaration,
    *,
    evidence: ProfileContainerEvidence | None = None,
    sha256: str,
    byte_size: int,
    stat_note: str,
) -> MpxArtifactReport:
    """Build the report from an already-decoded, identity-checked bundle."""
    streams = tuple(_summarize_stream(stream) for stream in bundle.recording.streams)
    decoded_channels = tuple(sorted({stream.channel for stream in streams}))
    partition = _channel_block_reports(evidence) if evidence is not None else ()
    clauses = list(_channel_clauses(decoded_channels, declaration))
    clauses.extend(_profile_clauses(streams, declaration))
    repeat_clause = _repeat_clauses(declaration, partition)
    if repeat_clause is not None:
        clauses.append(repeat_clause)
    clauses.extend(_data_clauses(streams))
    verdict = _verdict(clauses)
    mode = bundle.recording.acquisition_mode
    return MpxArtifactReport(
        file_name=path.name,
        file_sha256=sha256,
        byte_size=byte_size,
        identity_verified=True,
        identity_note=(
            "the streamed SHA-256 and byte size were equal on both reads, the decoder's "
            "own content digest and size equal them, and stat identity was "
            f"{stat_note}; this is content identity, not proof that the file was never "
            "rewritten with the same bytes"
        ),
        acquisition_mode=mode.value,
        mode_note=(
            "reported as decoded, never as a declaration match: sequential means the "
            "multiplexer-enable bit was set, not that channel order or roll-over is known; "
            "rolling is never inferred"
        ),
        declared_channels=tuple(sorted(declaration.channels)),
        declared_profiles_per_channel=declaration.profiles_per_channel,
        expected_total_profiles=declaration.expected_total_profiles,
        decoded_channels=decoded_channels,
        streams=streams,
        block_partition=partition,
        declared_profiles_per_visit=declaration.profiles_per_visit,
        declared_sequence_repeats=declaration.sequence_repeats,
        count_basis=declaration.count_basis,
        repeat_verification=_repeat_verification(repeat_clause),
        repeat_note=_repeat_note(declaration, repeat_clause),
        clauses=tuple(clauses),
        verdict=verdict,
    )


def _summarize_stream(stream: ChannelArtifact) -> MpxStreamReport:
    """Summarize one decoded ``ChannelArtifact`` without grading or physical claims."""
    data = stream.data
    values = np.asarray(data.values, dtype=np.float64)
    finite = np.isfinite(values)
    finite_count = int(finite.sum())
    nonzero_cells = finite & (values != 0.0)
    times = np.asarray(data.time_s, dtype=np.float64)
    time_start = float(times[0]) if times.size and np.isfinite(times[0]) else None
    time_end = float(times[-1]) if times.size and np.isfinite(times[-1]) else None
    # A span between the first and last decoded sample, never coverage of the block:
    # nothing here establishes that no profile is missing or that the duration was met.
    span = (
        time_end - time_start
        if time_start is not None and time_end is not None
        else None
    )
    return MpxStreamReport(
        channel=int(stream.acquisition.channel.device_channel),  # type: ignore[attr-defined]
        quantity=stream.descriptor.quantity.value,  # type: ignore[attr-defined]
        unit=stream.descriptor.unit,  # type: ignore[attr-defined]
        profiles=int(values.shape[0]),
        gates=int(values.shape[1]),
        time_start_s=time_start,
        time_end_s=time_end,
        time_span_s=span,
        finite_values=finite_count,
        non_finite_values=int(values.size - finite_count),
        nonzero_samples=int(nonzero_cells.any(axis=1).sum()),
        nonzero_values=int(nonzero_cells.sum()),
        abs_max=(float(np.max(np.abs(values[finite]))) if finite_count else None),
    )


def _channel_clauses(
    decoded_channels: tuple[int, ...], declaration: CompletedBlockDeclaration
) -> tuple[MpxClause, ...]:
    """The exact decoded channel set against the declared set."""
    declared = tuple(sorted(declaration.channels))
    if declared == decoded_channels:
        return (
            MpxClause(
                subject="channels",
                status=MpxVerdict.CONSISTENT,
                detail=f"declared and decoded channel sets are both {list(declared)}",
            ),
        )
    missing = sorted(set(declared) - set(decoded_channels))
    extra = sorted(set(decoded_channels) - set(declared))
    parts = [
        f"declared {list(declared)}, decoded {list(decoded_channels)}",
    ]
    if missing:
        parts.append(f"declared but not decoded: {missing}")
    if extra:
        parts.append(f"decoded but not declared: {extra}")
    return (
        MpxClause(
            subject="channels",
            status=MpxVerdict.CONTRADICTED,
            detail="; ".join(parts),
        ),
    )


def _profile_clauses(
    streams: tuple[MpxStreamReport, ...], declaration: CompletedBlockDeclaration
) -> tuple[MpxClause, ...]:
    """The stored profile count per channel, kept per stream and never conflated.

    ``expected`` is the declaration's normalized expected **total** — the stated total on the
    legacy basis, or the operator's per-visit count times the operator's repeat count. That
    product is arithmetic over the operator's numbers: it is not a decoded partition, so a
    matching count says nothing about how many visits the file actually holds (see
    :func:`_repeat_clauses`).
    """
    declared = set(declaration.channels)
    expected_total = declaration.expected_total_profiles
    by_channel: dict[int, list[MpxStreamReport]] = {}
    for stream in streams:
        by_channel.setdefault(stream.channel, []).append(stream)
    clauses: list[MpxClause] = []
    for channel in sorted(declared | set(by_channel)):
        subject = f"profiles:channel {channel}"
        found = by_channel.get(channel, [])
        if not found:
            clauses.append(
                MpxClause(
                    subject=subject,
                    status=MpxVerdict.UNVERIFIABLE,
                    detail=(
                        f"channel {channel} was declared but not decoded, so there is no "
                        "stored count to compare"
                    ),
                    expected=expected_total,
                )
            )
            continue
        if len(found) > 1:
            quantities = sorted({stream.quantity for stream in found})
            counts = [stream.profiles for stream in found]
            if len(quantities) > 1:
                reason = (
                    f"channel {channel} decoded {len(found)} streams of more than one "
                    f"quantity ({', '.join(quantities)} with profile counts {counts}); "
                    "their counts stay separate and are not compared as one measurement"
                )
            else:
                reason = (
                    f"channel {channel} decoded {len(found)} streams of the same quantity "
                    f"({quantities[0]} with profile counts {counts}), not of two different "
                    "quantities: the decoder did not report one stream per channel, so "
                    "which stream the declaration's count refers to is not established"
                )
            clauses.append(
                MpxClause(
                    subject=subject,
                    status=MpxVerdict.UNVERIFIABLE,
                    detail=reason,
                    expected=expected_total,
                )
            )
            continue
        stream = found[0]
        if channel not in declared:
            clauses.append(
                MpxClause(
                    subject=subject,
                    status=MpxVerdict.UNVERIFIABLE,
                    detail=(
                        f"channel {channel} was decoded ({stream.quantity}) but not declared, "
                        f"so its {stream.profiles} stored profiles have no declared count"
                    ),
                    observed=stream.profiles,
                )
            )
            continue
        expected = expected_total
        consistent = stream.profiles == expected
        detail = _profile_detail(expected, stream, declaration)
        if not consistent:
            detail += (
                "; a shorter decode can mean a truncated file, which is reported as "
                "this count and not as a corruption verdict"
            )
        clauses.append(
            MpxClause(
                subject=subject,
                status=(
                    MpxVerdict.CONSISTENT if consistent else MpxVerdict.CONTRADICTED
                ),
                detail=detail,
                expected=expected,
                observed=stream.profiles,
            )
        )
    return tuple(clauses)


def _profile_detail(
    expected: int, stream: MpxStreamReport, declaration: CompletedBlockDeclaration
) -> str:
    """Name the expected total's basis so the count is never silently converted."""
    if declaration.count_basis is ProfileCountBasis.STATED_TOTAL:
        return f"declared {expected}, decoded {stream.profiles} profiles ({stream.quantity})"
    return (
        f"expected {expected} profiles per channel = {declaration.sequence_repeats} "
        f"repeat(s) x {declaration.profiles_per_visit} per visit (operator-stated "
        f"arithmetic), decoded {stream.profiles} profiles ({stream.quantity})"
    )


def _channel_block_reports(
    evidence: ProfileContainerEvidence,
) -> tuple[MpxChannelBlockReport, ...]:
    """Project the reader's per-container facts into per-channel runs.

    Only the owning reader's facts are used. For each channel and quantity the
    containers carrying that quantity are taken in **source order** and cut into
    maximal runs of equal stored word, so the other channels' containers (and
    other quantities' containers) between them do not break a run: that
    interleave is the normal multiplexer pattern, not a partition boundary.

    A word that reappears after a different word opens a *new* run and is never
    merged into the earlier one, so a reused non-contiguous number stays visible
    as two runs instead of being summed into one convenient group. Containers
    whose stored word is unknown keep their own run with ``block_number=None``
    and their rows; ``source_ordinals`` and ``containers`` keep the evidence.
    """
    reports: list[MpxChannelBlockReport] = []
    for channel in sorted({c.channel for c in evidence.containers}):
        containers = [c for c in evidence.containers if c.channel == channel]
        quantities = sorted({p.quantity for c in containers for p in c.profiles})
        groups: list[MpxBlockRun] = []
        for quantity in quantities:
            # (stored word, container ordinals, row count) of the run being built.
            current: tuple[int | None, list[int], int] | None = None
            for container in containers:  # already in source order
                rows = 0
                for count in container.profiles:
                    if count.quantity == quantity:
                        rows = count.profiles
                        break
                if rows == 0:
                    continue
                if current is not None and current[0] == container.stored_sequence:
                    current[1].append(container.source_ordinal)
                    current = (current[0], current[1], current[2] + rows)
                    continue
                if current is not None:
                    groups.append(
                        MpxBlockRun(
                            channel=channel,
                            quantity=quantity,
                            block_number=current[0],
                            containers=len(current[1]),
                            source_ordinals=tuple(current[1]),
                            profiles=current[2],
                        )
                    )
                current = (container.stored_sequence, [container.source_ordinal], rows)
            if current is not None:
                groups.append(
                    MpxBlockRun(
                        channel=channel,
                        quantity=quantity,
                        block_number=current[0],
                        containers=len(current[1]),
                        source_ordinals=tuple(current[1]),
                        profiles=current[2],
                    )
                )
        setting = evidence.configured_for(channel)
        reports.append(
            MpxChannelBlockReport(
                channel=channel,
                groups=tuple(groups),
                stored_block_numbers=tuple(
                    dict.fromkeys(
                        group.block_number
                        for group in groups
                        if group.block_number is not None
                    )
                ),
                blocks_with_unknown_number=sum(
                    1 for group in groups if group.block_number is None
                ),
                configured_containers_in_mode=(
                    setting.containers_in_mode if setting is not None else None
                ),
                configured_profiles_per_container=(
                    setting.profiles_per_container if setting is not None else None
                ),
            )
        )
    return tuple(reports)


def _configured_note(partition: tuple[MpxChannelBlockReport, ...]) -> str:
    """Name the configured vendor block words separately from the observed partition."""
    parts = [
        f"ch {report.channel}: op 53 = {report.configured_containers_in_mode}, "
        f"op 51 = {report.configured_profiles_per_container}"
        for report in partition
    ]
    return (
        "configured multiplexer block words ("
        + "; ".join(parts)
        + ") are configuration: they are not evidence that those profile containers, or "
        "those runs, exist in this file, and they are not substituted for the stored "
        "block/sequence words"
    )


def _repeat_clauses(
    declaration: CompletedBlockDeclaration,
    partition: tuple[MpxChannelBlockReport, ...],
) -> MpxClause | None:
    """Compare the stated repeats x per-visit split with the stored container runs.

    The comparison is against the reader's own container evidence, projected per
    channel and quantity into runs of *contiguous* containers sharing one stored
    block/sequence word — never against an arithmetic total, never against op
    word 53, and never by summing a reused word across the file. Each stored word
    must also be one instance and the ordered run sequence must agree across the
    declared channels; only then is the partition called consistent or
    contradicted. A single run, an unknown word, a reused non-contiguous word, a
    channel whose containers mix quantities, or channels with differing ordered
    sequences stay ``unverifiable``. The clause says in words that the vendor word
    is a block/sequence number, not a visit identity, so consistency is a
    statement about stored containers only.
    """
    if declaration.sequence_repeats is None:
        return None
    repeats = declaration.sequence_repeats
    per_visit = declaration.profiles_per_visit
    assert per_visit is not None  # guaranteed by the declaration's own clauses

    statuses: list[MpxVerdict] = []
    details: list[str] = []
    sequences: dict[int, tuple[int | None, ...]] = {}
    by_channel = {report.channel: report for report in partition}
    for channel in sorted(declaration.channels):
        report = by_channel.get(channel)
        if report is None or not report.groups:
            details.append(f"ch {channel}: no stored profile rows were decoded")
            statuses.append(MpxVerdict.UNVERIFIABLE)
            continue
        quantities = sorted({group.quantity for group in report.groups})
        if len(quantities) > 1:
            details.append(
                f"ch {channel}: its containers carry more than one quantity "
                f"({', '.join(quantities)}); the counts stay separate and no split is claimed"
            )
            statuses.append(MpxVerdict.UNVERIFIABLE)
            continue
        if report.blocks_with_unknown_number:
            details.append(
                f"ch {channel}: {report.blocks_with_unknown_number} stored run(s) have an "
                f"unknown block/sequence number; their decoded counts are preserved as "
                f"{[(group.block_number, group.profiles) for group in report.groups]}"
            )
            statuses.append(MpxVerdict.UNVERIFIABLE)
            continue
        numbers = [group.block_number for group in report.groups]
        rows = [group.profiles for group in report.groups]
        reused = sorted({number for number in numbers if numbers.count(number) > 1})
        if reused:
            details.append(
                f"ch {channel}: the stored block/sequence word(s) {reused} reappear in "
                f"more than one non-contiguous run ({len(numbers)} run(s) holding "
                f"{rows} profile(s)); a reused word is not merged, so the partition is "
                "not settled by these containers"
            )
            statuses.append(MpxVerdict.UNVERIFIABLE)
            continue
        sequences[channel] = tuple(numbers)
        observed = f"ch {channel}: {len(numbers)} stored run(s) {numbers} holding {rows} profile(s)"
        if len(numbers) == 1 and repeats > 1:
            details.append(
                observed
                + " — a single stored run cannot show the per-visit split, so the "
                "stated repeats are not settled by this file"
            )
            statuses.append(MpxVerdict.UNVERIFIABLE)
        elif len(numbers) == repeats and all(rows_ == per_visit for rows_ in rows):
            details.append(observed + f", matching {repeats} x {per_visit}")
            statuses.append(MpxVerdict.CONSISTENT)
        else:
            details.append(
                observed + f", which does not match the stated {repeats} run(s) x "
                f"{per_visit} profile(s)"
            )
            statuses.append(MpxVerdict.CONTRADICTED)

    # One ordered sequence across channels: a shared partition is only claimed
    # when every settled declared channel carries the same run order. Per-channel
    # projection already tolerates the multiplexer's channel interleave, so a
    # differing order is a real disagreement between channels, not an artefact.
    if len(set(sequences.values())) > 1:
        descriptions = "; ".join(
            f"ch {channel}: {list(sequence)}"
            for channel, sequence in sorted(sequences.items())
        )
        details.append(
            "the ordered stored run sequence differs between channels "
            f"({descriptions}); a shared partition is not established"
        )
        statuses.append(MpxVerdict.UNVERIFIABLE)

    if MpxVerdict.CONTRADICTED in statuses:
        status = MpxVerdict.CONTRADICTED
    elif MpxVerdict.UNVERIFIABLE in statuses:
        status = MpxVerdict.UNVERIFIABLE
    else:
        status = MpxVerdict.CONSISTENT
    detail = (
        f"the operator stated {repeats} repeat(s) of {per_visit} profile(s) per visit "
        f"(expected total {declaration.expected_total_profiles} per channel, operator "
        "arithmetic); the reader's stored container partition per channel and quantity "
        "is "
        + "; ".join(details)
        + ". The footer word is documented as a block/sequence number, not a visit "
        "identity, so this compares contiguous stored containers and does not "
        "establish a visit law; " + _configured_note(partition) + "."
    )
    return MpxClause(
        subject="repeats",
        status=status,
        detail=detail,
        expected=repeats,
        observed=(
            max(
                (len(report.stored_block_numbers) for report in partition),
                default=0,
            )
            if partition
            else None
        ),
    )


def _repeat_verification(clause: MpxClause | None) -> MpxRepeatVerification:
    """Map the repeat clause's status onto the report's repeat field."""
    if clause is None:
        return MpxRepeatVerification.NOT_DECLARED
    if clause.status is MpxVerdict.CONSISTENT:
        return MpxRepeatVerification.PARTITION_CONSISTENT
    if clause.status is MpxVerdict.CONTRADICTED:
        return MpxRepeatVerification.PARTITION_CONTRADICTED
    return MpxRepeatVerification.UNKNOWN


def _repeat_note(
    declaration: CompletedBlockDeclaration, clause: MpxClause | None
) -> str:
    """The repeat field's own words: the declaration's unknown, or the block caveat."""
    if clause is None:
        return ""
    if clause.status is MpxVerdict.UNVERIFIABLE:
        return declaration.repeat_verification_unknown
    return (
        f"{clause.status.value} as a stored container partition: the file's own "
        f"block/sequence words group contiguous containers into {clause.observed} run(s) "
        "per channel; the format documents that word as a block/sequence number, not a "
        "visit identity, so this is not a decoded visit or round count"
    )


def _data_clauses(streams: tuple[MpxStreamReport, ...]) -> tuple[MpxClause, ...]:
    """Make non-finite cells and an unknown time axis explicit."""
    clauses: list[MpxClause] = []
    for stream in streams:
        if stream.non_finite_values:
            clauses.append(
                MpxClause(
                    subject=f"data:channel {stream.channel}",
                    status=MpxVerdict.UNVERIFIABLE,
                    detail=(
                        f"{stream.non_finite_values} non-finite cell(s) of "
                        f"{stream.finite_values + stream.non_finite_values}; the counts and "
                        "abs_max cover finite cells only"
                    ),
                    observed=stream.non_finite_values,
                )
            )
        if stream.time_span_s is None:
            clauses.append(
                MpxClause(
                    subject=f"time:channel {stream.channel}",
                    status=MpxVerdict.UNVERIFIABLE,
                    detail=(
                        "the stream's time axis has no finite first/last sample time, so no "
                        "span is reported; this says nothing about missing profiles"
                    ),
                )
            )
    return tuple(clauses)


def _verdict(clauses: list[MpxClause] | tuple[MpxClause, ...]) -> MpxVerdict:
    """One verdict from the clauses: contradiction wins, then unverifiable."""
    statuses = {clause.status for clause in clauses}
    if MpxVerdict.CONTRADICTED in statuses:
        return MpxVerdict.CONTRADICTED
    if MpxVerdict.UNVERIFIABLE in statuses:
        return MpxVerdict.UNVERIFIABLE
    return MpxVerdict.CONSISTENT
