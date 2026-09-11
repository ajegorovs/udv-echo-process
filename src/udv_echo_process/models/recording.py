"""Recording-level state and terminal statistical products (plan §6.7).

``Recording`` closes a multi-channel acquisition: the stream artifacts, the
source-asset identity they all belong to and the acquisition mode/order. It
never *infers* mode from the number of streams — the reader decodes it, and an
unprovable file carries :attr:`AcquisitionMode.UNKNOWN` (§6.7, §14). The
``ArtifactBundle`` that wraps a ``Recording`` with its provenance graph lives in
:mod:`udv_echo_process.provenance.models` (§8.1).

``ProfileStatistics`` is a *terminal* result, not a recording: a JSON-oriented
per-gate summary (plan §6.7) that intentionally carries no ndarray.
"""

from __future__ import annotations

import math
import re
from collections.abc import Hashable, Sequence

from pydantic import ValidationInfo, field_validator, model_validator

from udv_echo_process.models.acquisition import AcquisitionMode
from udv_echo_process.models.base import ArrayModel, ValueModel
from udv_echo_process.models.identity import ChannelKey, SignalDescriptor, SourceAsset
from udv_echo_process.models.signal import ChannelArtifact

#: Opaque id form: ``sha256:`` plus 64 lower-case hex characters.
_SHA256_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")

#: The four per-gate statistic tuples of :class:`ProfileStatistics`.
_STATISTIC_FIELDS = ("mean", "std", "minimum", "maximum")


def _check_opaque_id(value: str, *, field_name: str | None) -> str:
    text = value.strip()
    if not _SHA256_ID_RE.fullmatch(text):
        raise ValueError(
            f"{field_name} must be an opaque lower-case 'sha256:<64 hex>' id, "
            f"got {value!r}"
        )
    return text


def _duplicates(values: Sequence[Hashable]) -> list[tuple[int, int, Hashable]]:
    """Return ``(first_index, second_index, value)`` for each repeated value."""
    seen: dict[Hashable, int] = {}
    found: list[tuple[int, int, Hashable]] = []
    for index, value in enumerate(values):
        if value in seen:
            found.append((seen[value], index, value))
        else:
            seen[value] = index
    return found


class Recording(ArrayModel):
    """One recorded acquisition: its source, mode and channel streams (§6.7).

    Exactly five fields. Invariants enforced here:

    - ``streams`` is non-empty;
    - every stream's ``AcquisitionRef.recording_id`` equals ``recording_id`` and
      every ``source_asset_id`` equals ``source_asset.asset_id``;
    - channel keys and artifact ids are unique;
    - a supplied ``acquisition_order`` is a duplicate-free exact permutation of
      the stream channel keys;
    - within each stream, decoded ``(round_id, visit_id)`` pairs are unique
      among matched rows (``>= 0``); unmatched rows keep the ``-1`` sentinel and
      are never renumbered.

    Mode is a plain field: it is never derived from the field set, so a
    one-stream recording may be ``SEQUENTIAL`` and a many-stream recording may
    be ``SIMULTANEOUS``.
    """

    recording_id: str
    source_asset: SourceAsset
    acquisition_mode: AcquisitionMode
    streams: tuple[ChannelArtifact, ...]
    acquisition_order: tuple[ChannelKey, ...] | None = None

    @field_validator("recording_id")
    @classmethod
    def _check_recording_id(cls, value: str, info: ValidationInfo) -> str:
        return _check_opaque_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _check_invariants(self) -> Recording:
        if not self.streams:
            raise ValueError(
                "streams must contain at least one channel artifact, got 0 "
                "(an empty recording is not a recording)"
            )
        self._check_stream_identity()
        self._check_stream_uniqueness()
        self._check_acquisition_order()
        self._check_stream_topology()
        return self

    def _check_stream_identity(self) -> None:
        asset_id = self.source_asset.asset_id
        for index, stream in enumerate(self.streams):
            ref = stream.acquisition
            channel = ref.channel.device_channel
            if ref.recording_id != self.recording_id:
                raise ValueError(
                    f"stream {index} (channel {channel}) has acquisition "
                    f"recording_id {ref.recording_id!r} but recording "
                    f"{self.recording_id!r} expects its own id"
                )
            if ref.source_asset_id != asset_id:
                raise ValueError(
                    f"stream {index} (channel {channel}) has acquisition "
                    f"source_asset_id {ref.source_asset_id!r} but recording "
                    f"source asset is {asset_id!r}"
                )

    def _check_stream_uniqueness(self) -> None:
        channels = [
            stream.acquisition.channel.device_channel for stream in self.streams
        ]
        for first, second, channel in _duplicates(channels):
            raise ValueError(
                f"stream channel keys must be unique; channel {channel} appears "
                f"at indexes {first} and {second}"
            )
        artifact_ids = [stream.artifact_id for stream in self.streams]
        for first, second, artifact_id in _duplicates(artifact_ids):
            raise ValueError(
                f"stream artifact_id values must be unique; {artifact_id!r} "
                f"appears at indexes {first} and {second}"
            )

    def _check_acquisition_order(self) -> None:
        order = self.acquisition_order
        if order is None:
            return
        ordered_channels = [key.device_channel for key in order]
        for first, second, channel in _duplicates(ordered_channels):
            raise ValueError(
                f"acquisition_order must be duplicate-free; channel {channel} "
                f"appears at indexes {first} and {second}"
            )
        stream_channels = sorted(
            stream.acquisition.channel.device_channel for stream in self.streams
        )
        if sorted(ordered_channels) != stream_channels:
            raise ValueError(
                "acquisition_order must be an exact permutation of the stream "
                f"channel keys; got {ordered_channels}, streams are "
                f"{stream_channels}"
            )

    def _check_stream_topology(self) -> None:
        """Decoded ``(round_id, visit_id)`` pairs must be unique per stream."""
        for stream in self.streams:
            index = stream.data.acquisition
            if index is None or index.round_id is None or index.visit_id is None:
                continue
            channel = stream.acquisition.channel.device_channel
            matched = (index.round_id >= 0) & (index.visit_id >= 0)
            pairs = list(
                zip(
                    index.round_id[matched].tolist(),
                    index.visit_id[matched].tolist(),
                    strict=True,
                )
            )
            for first, second, pair in _duplicates(pairs):
                raise ValueError(
                    f"stream channel {channel} has a repeated (round_id, "
                    f"visit_id) pair {pair} at rows {first} and {second} in "
                    f"recording {self.recording_id!r}"
                )


class ProfileStatistics(ValueModel):
    """Terminal per-gate summary of one channel (plan §6.7).

    Every tuple has gate length; ``count`` is nonnegative; a zero count requires
    all four statistic values at that gate to be ``None``. This JSON-oriented
    result intentionally contains no ndarray.
    """

    artifact_id: str
    source_artifact_id: str
    descriptor: SignalDescriptor
    gate_depths_mm: tuple[float, ...]
    count: tuple[int, ...]
    mean: tuple[float | None, ...]
    std: tuple[float | None, ...]
    minimum: tuple[float | None, ...]
    maximum: tuple[float | None, ...]

    @field_validator("artifact_id", "source_artifact_id")
    @classmethod
    def _check_ids(cls, value: str, info: ValidationInfo) -> str:
        return _check_opaque_id(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _check_invariants(self) -> ProfileStatistics:
        n_gates = len(self.gate_depths_mm)
        if n_gates < 1:
            raise ValueError(
                f"gate_depths_mm must contain at least one gate, got {n_gates}"
            )
        for index, depth in enumerate(self.gate_depths_mm):
            if not math.isfinite(depth):
                raise ValueError(
                    f"gate_depths_mm must be finite; index {index} has value {depth!r}"
                )
            if index and depth <= self.gate_depths_mm[index - 1]:
                raise ValueError(
                    "gate_depths_mm must be strictly increasing; index "
                    f"{index} violates with adjacent values "
                    f"{self.gate_depths_mm[index - 1]} then {depth}"
                )
        for name in ("count", *_STATISTIC_FIELDS):
            length = len(getattr(self, name))
            if length != n_gates:
                raise ValueError(
                    f"{name} must have gate length {n_gates}, got {length}"
                )
        for index, count in enumerate(self.count):
            if count < 0:
                raise ValueError(
                    f"count must be nonnegative, got {count} at gate {index}"
                )
        for name in _STATISTIC_FIELDS:
            values = getattr(self, name)
            for index, (count, value) in enumerate(
                zip(self.count, values, strict=True)
            ):
                if count == 0 and value is not None:
                    raise ValueError(
                        f"zero count at gate {index} requires {name} to be "
                        f"None, got {value!r}"
                    )
                if value is not None and not math.isfinite(value):
                    raise ValueError(
                        f"{name} must be finite or None, got {value!r} at gate {index}"
                    )
        return self
