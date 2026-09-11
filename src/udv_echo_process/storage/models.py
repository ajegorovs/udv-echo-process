"""Typed, deeply immutable on-disk projection of the signal model (plan §9.2).

Storage schema 1 stores every scientific, support and acquisition array as a
separate ``.npy`` file next to a canonical ``manifest.json``. The manifest does
not embed arrays; it references each one through an :class:`ArrayRef` (relative
POSIX path, dtype, shape, nbytes, file SHA-256). :class:`StoredRecordingV1` and
its nested stream/data/support/index models *mirror* the runtime
``Recording -> ChannelArtifact -> SignalData -> SampleSupport/AcquisitionIndex``
structure with every ndarray replaced by an ``ArrayRef``, using tuples and
frozen :class:`~udv_echo_process.models.base.ValueModel` children only — never
an untyped ``dict``/``list`` container — so the manifest is deeply immutable
after validation and carries no inline array and no absolute source path.

The three persisted versions (``storage``, ``domain``, ``operation``) are
independent fields, never collapsed into one ``version`` (plan §9.3). This
module defines the storage/domain supported sets; the operation version comes
from :data:`udv_echo_process.process.derive.OPERATION_SCHEMA_VERSION`.

Path safety lives on :class:`ArrayRef`: every manifest path is a normalized,
relative POSIX path with no absolute path, no ``..``, no empty/``.`` segment and
no backslash. The filesystem-side checks (existence, symlink, escape under the
bundle root) live in :mod:`udv_echo_process.storage.npy`.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from udv_echo_process.models.acquisition import AcquisitionMode
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.models.identity import (
    AcquisitionRef,
    ChannelKey,
    SignalDescriptor,
    SourceAsset,
)
from udv_echo_process.process.derive import OPERATION_SCHEMA_VERSION
from udv_echo_process.provenance.models import ArtifactGraph

#: On-disk manifest layout version. ``Literal[1]`` on the manifest model.
STORAGE_SCHEMA_VERSION: Literal[1] = 1

#: Version of the persisted domain projection (:class:`StoredRecordingV1` and
#: its children). Bumped whenever the stored domain shape changes.
DOMAIN_SCHEMA_VERSION: int = 1

#: Storage versions this build can read. Version 1 has no migration-on-read.
SUPPORTED_STORAGE_SCHEMA_VERSIONS: tuple[int, ...] = (1,)

#: Domain projection versions this build can read.
SUPPORTED_DOMAIN_SCHEMA_VERSIONS: tuple[int, ...] = (1,)

#: Operation schema versions this build can read (the registry's current one).
SUPPORTED_OPERATION_SCHEMA_VERSIONS: tuple[int, ...] = (OPERATION_SCHEMA_VERSION,)

#: Array dtypes storage v1 permits. Anything else (object/string/structured/
#: complex/float32/…) is rejected rather than silently converted.
ARRAY_DTYPES: tuple[str, ...] = ("float64", "int64", "uint8", "uint32", "bool")

_ARRAY_DTYPE_LITERAL = Literal["float64", "int64", "uint8", "uint32", "bool"]

_HEX64_RE = re.compile(r"[0-9a-f]{64}")


class ArrayRef(ValueModel):
    """One serialized array: where it lives and how to verify it (plan §9.2).

    ``path`` is a normalized relative POSIX path *inside* the bundle; ``dtype``
    is one of the five storage-v1 dtypes; ``shape`` is the logical array shape;
    ``nbytes`` the payload size; ``sha256`` the file SHA-256 streamed from the
    bytes on disk (not an array digest). The manifest holds only references —
    never array content.
    """

    path: str
    dtype: _ARRAY_DTYPE_LITERAL
    shape: tuple[int, ...]
    nbytes: int = Field(ge=0)
    sha256: str

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str, info: ValidationInfo) -> str:
        if not value or "\\" in value:
            raise ValueError(
                f"{info.field_name} must be a normalized relative POSIX path "
                f"inside the bundle, got {value!r}"
            )
        pure = PurePosixPath(value)
        if (
            pure.is_absolute()
            or str(pure) != value
            or not pure.parts
            or any(part in ("", ".", "..") for part in pure.parts)
        ):
            raise ValueError(
                f"{info.field_name} must be a normalized relative POSIX path "
                "(no absolute path, '.', '..', empty segment or trailing "
                f"separator), got {value!r}"
            )
        return value

    @field_validator("shape")
    @classmethod
    def _check_shape(
        cls, value: tuple[int, ...], info: ValidationInfo
    ) -> tuple[int, ...]:
        for axis in value:
            if axis < 0:
                raise ValueError(
                    f"{info.field_name} axes must be nonnegative, got {value}"
                )
        return value

    @field_validator("sha256")
    @classmethod
    def _check_sha256(cls, value: str, info: ValidationInfo) -> str:
        if not _HEX64_RE.fullmatch(value):
            raise ValueError(
                f"{info.field_name} must be 64 lower-case hex characters, got {value!r}"
            )
        return value


class StoredSampleSupportV1(ValueModel):
    """Mirror of ``SampleSupport`` with each ``(T, G)`` plane an ``ArrayRef``."""

    kind: ArrayRef
    valid: ArrayRef
    quality: ArrayRef


class StoredAcquisitionIndexV1(ValueModel):
    """Mirror of ``AcquisitionIndex``; optional id planes stay ``None``."""

    sample_id: ArrayRef
    acquisition_time_s: ArrayRef
    round_id: ArrayRef | None = None
    visit_id: ArrayRef | None = None
    profile_in_visit: ArrayRef | None = None


class StoredSignalDataV1(ValueModel):
    """Mirror of ``SignalData`` with every ndarray replaced by an ``ArrayRef``."""

    time_s: ArrayRef
    gate_depths_mm: ArrayRef
    values: ArrayRef
    support: StoredSampleSupportV1
    acquisition: StoredAcquisitionIndexV1 | None = None


class StoredChannelArtifactV1(ValueModel):
    """Mirror of ``ChannelArtifact``: identity/metadata verbatim, arrays refs."""

    artifact_id: str
    acquisition: AcquisitionRef
    descriptor: SignalDescriptor
    config: ChannelConfig
    data: StoredSignalDataV1


class StoredRecordingV1(ValueModel):
    """Mirror of ``Recording``: a tuple of typed stream projections.

    ``streams`` is a tuple of :class:`StoredChannelArtifactV1`, never a list, and
    every child is a frozen ``ValueModel``, so the projection is deeply
    immutable and contains no inline scientific/support/index array.
    """

    recording_id: str
    source_asset: SourceAsset
    acquisition_mode: AcquisitionMode
    streams: tuple[StoredChannelArtifactV1, ...]
    acquisition_order: tuple[ChannelKey, ...] | None = None

    @model_validator(mode="after")
    def _check_streams(self) -> StoredRecordingV1:
        if not self.streams:
            raise ValueError(
                "streams must contain at least one stored channel artifact, got 0"
            )
        seen: set[str] = set()
        for index, stream in enumerate(self.streams):
            if stream.artifact_id in seen:
                raise ValueError(
                    f"streams[{index}] repeats artifact_id "
                    f"{stream.artifact_id!r}; stored artifact ids must be unique"
                )
            seen.add(stream.artifact_id)
        return self


class BundleManifestV1(ValueModel):
    """The storage-schema-1 manifest (plan §9.2).

    Exactly five top-level fields: the storage version literal and the two
    independent domain/operation versions, the typed recording projection and
    the provenance graph.
    """

    storage_schema_version: Literal[1]
    domain_schema_version: int = Field(ge=1)
    operation_schema_version: int = Field(ge=1)
    recording: StoredRecordingV1
    graph: ArtifactGraph
