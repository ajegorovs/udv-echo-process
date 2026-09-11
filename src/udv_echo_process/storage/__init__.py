"""Persistence: the storage-schema-1 NPY + manifest store (plan §9).

``store_bundle(bundle, destination)`` writes a validated ``ArtifactBundle`` to a
new directory; ``load_bundle(destination)`` reconstructs it, failing closed on
any incomplete/corrupt/unsafe store. The storage schema-internal names stay out
of the package top-level surface (the plan §12 export policy), so they are
reached through ``udv_echo_process.storage``.
"""

from __future__ import annotations

from udv_echo_process.storage.models import (
    ARRAY_DTYPES,
    DOMAIN_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION,
    SUPPORTED_DOMAIN_SCHEMA_VERSIONS,
    SUPPORTED_OPERATION_SCHEMA_VERSIONS,
    SUPPORTED_STORAGE_SCHEMA_VERSIONS,
    ArrayRef,
    BundleManifestV1,
    StoredAcquisitionIndexV1,
    StoredChannelArtifactV1,
    StoredRecordingV1,
    StoredSampleSupportV1,
    StoredSignalDataV1,
)
from udv_echo_process.storage.npy import (
    ARRAYS_DIRNAME,
    COMPLETE_FILENAME,
    MANIFEST_FILENAME,
    MigrationRequiredError,
    StoreError,
    load_bundle,
    store_bundle,
)

__all__ = [
    "ARRAYS_DIRNAME",
    "ARRAY_DTYPES",
    "COMPLETE_FILENAME",
    "DOMAIN_SCHEMA_VERSION",
    "MANIFEST_FILENAME",
    "STORAGE_SCHEMA_VERSION",
    "SUPPORTED_DOMAIN_SCHEMA_VERSIONS",
    "SUPPORTED_OPERATION_SCHEMA_VERSIONS",
    "SUPPORTED_STORAGE_SCHEMA_VERSIONS",
    "ArrayRef",
    "BundleManifestV1",
    "MigrationRequiredError",
    "StoreError",
    "StoredAcquisitionIndexV1",
    "StoredChannelArtifactV1",
    "StoredRecordingV1",
    "StoredSampleSupportV1",
    "StoredSignalDataV1",
    "load_bundle",
    "store_bundle",
]
