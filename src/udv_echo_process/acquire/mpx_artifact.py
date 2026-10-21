"""Offline verification of one stored multiplexed `.BDD` against a completed-block declaration.

This is the **artifact** half of the multiplexed store path: it reads and decodes one
already-stored file, it never touches the instrument, it opens no window and it writes
nothing. The declaration is the same :class:`CompletedBlockDeclaration` the store path
takes, and it is validated *before* the file is hashed or decoded, so an invalid
statement costs no decode and produces no claim.

What a verdict means
--------------------

Only two things are compared, because they are the two things the declaration states:
the exact decoded channel set and the stored profile count per channel. The result is
one typed clause per comparison:

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
  No round/visit/roll count is inferred from block numbering, timestamps, or the order
  in which profiles happen to decode.
* **No per-channel profile count is read from a private word parser.** The stored count
  compared here is the number of decoded profile rows in that channel's own stream.
  A truncated file can decode fewer complete blocks and is reported as a contradicted
  count, not as a corrupt-file claim.
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
from udv_echo_process.io import load
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.signal import ChannelArtifact
from udv_echo_process.provenance import ArtifactBundle

__all__ = [
    "MpxArtifactReport",
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
    """What the check established about the *number of stored visits*.

    Only ever one of these two: this decoder has no visit/block partition to compare, so a
    declared repeat count can never be called verified.
    """

    #: The declaration stated no repeat count, so nothing is claimed about visits.
    NOT_DECLARED = "not-declared"
    #: A repeat count was stated; the actual count/partition is not decoded and is unknown.
    UNKNOWN = "unknown"


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
    #: The operator's stated per-visit count (``None`` on the legacy total basis).
    declared_profiles_per_visit: int | None = None
    #: The operator's stated repeat count (``None`` when no repeat was declared).
    declared_sequence_repeats: int | None = None
    count_basis: ProfileCountBasis = ProfileCountBasis.STATED_TOTAL
    #: Whether the number of stored visits could be checked. Always ``unknown`` when repeats
    #: were declared, because the decoder flattens every stored block into one stream.
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
                "actual repeats/visits unknown (not decoded)"
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
        bundle = load(target)
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
    sha256: str,
    byte_size: int,
    stat_note: str,
) -> MpxArtifactReport:
    """Build the report from an already-decoded, identity-checked bundle."""
    streams = tuple(_summarize_stream(stream) for stream in bundle.recording.streams)
    decoded_channels = tuple(sorted({stream.channel for stream in streams}))
    clauses = list(_channel_clauses(decoded_channels, declaration))
    clauses.extend(_profile_clauses(streams, declaration))
    clauses.extend(_repeat_clauses(declaration))
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
        declared_profiles_per_visit=declaration.profiles_per_visit,
        declared_sequence_repeats=declaration.sequence_repeats,
        count_basis=declaration.count_basis,
        repeat_verification=(
            MpxRepeatVerification.NOT_DECLARED
            if declaration.sequence_repeats is None
            else MpxRepeatVerification.UNKNOWN
        ),
        repeat_note=declaration.repeat_verification_unknown,
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


def _repeat_clauses(
    declaration: CompletedBlockDeclaration,
) -> tuple[MpxClause, ...]:
    """The repeat count's own clause: always unverifiable, because nothing decodes visits.

    This is not a missing feature worked around privately: the existing reader accumulates
    every stored block of a channel into one stream, and no block/visit/round field is owned
    or decoded. The clause therefore states the unknown rather than letting a matching total
    read as a verified repeat count, and the overall verdict becomes ``unverifiable`` for any
    repeated declaration even when the total agrees.
    """
    if declaration.sequence_repeats is None:
        return ()
    expected = declaration.expected_total_profiles
    return (
        MpxClause(
            subject="repeats",
            status=MpxVerdict.UNVERIFIABLE,
            detail=(
                f"the operator stated {declaration.sequence_repeats} repeat(s) of "
                f"{declaration.profiles_per_visit} profile(s) per visit, so the expected total "
                f"is {expected} = {declaration.sequence_repeats} x "
                f"{declaration.profiles_per_visit} (operator-stated arithmetic); only that "
                "total can be compared, because the decoder flattens every stored block into "
                "one stream per channel and decodes no repeat, block or visit count — the "
                f"actual number of stored visits is unknown, and a total of {expected} per "
                f"channel is not proof that {declaration.sequence_repeats} visit(s) ran"
            ),
            expected=declaration.sequence_repeats,
        ),
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
