"""NPY + manifest store — the storage-schema-1 write/read protocol (plan §9).

Layout (plan §9.1)::

    <bundle>/
    ├── manifest.json      # canonical JSON, sorted keys, compact, one newline
    ├── arrays/<id>/…      # one .npy per owned array, <id> = artifact id minus
    └── COMPLETE           # "<manifest sha256>  manifest.json\\n", written last

Write and read follow §9.3 step by step:

* write validates the whole bundle before I/O, refuses an existing destination,
  stages into a unique sibling directory on the same filesystem, streams each
  file's SHA-256 from the bytes on disk, writes ``COMPLETE`` last, fsyncs, then
  atomically renames staging onto the destination (any failure removes only the
  staging directory this call created);
* read rejects a missing/malformed ``COMPLETE`` first, then verifies the
  manifest hash, the strict schema and all three independent versions, resolves
  every ``ArrayRef`` safely inside the bundle (no symlink, no escape), verifies
  file hash / NPY header dtype+shape / nbytes and loads with
  ``allow_pickle=False``, rejects missing/duplicate/unreferenced arrays,
  reconstructs owned read-only arrays and re-runs all domain/DAG validation and
  the artifact/operation id replay.

Standard-library hashing/filesystem operations plus NumPy only — no pickle, no
new dependency. Every persisted path is bundle-relative; a machine-absolute path
never appears in the manifest or in a store error (AGENTS.md privacy rule).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from udv_echo_process.models._canonical import canonical_json_bytes, sha256_hex
from udv_echo_process.models.acquisition import AcquisitionIndex
from udv_echo_process.models.recording import Recording
from udv_echo_process.models.signal import (
    ChannelArtifact,
    SignalData,
    derived_artifact_id,
    source_artifact_id,
)
from udv_echo_process.models.support import SampleSupport
from udv_echo_process.process.derive import (
    OPERATION_SCHEMA_VERSION,
    revalidate_params,
)
from udv_echo_process.provenance.models import ArtifactBundle, operation_id_for
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

__all__ = [
    "ARRAYS_DIRNAME",
    "COMPLETE_FILENAME",
    "MANIFEST_FILENAME",
    "MigrationRequiredError",
    "StoreError",
    "load_bundle",
    "store_bundle",
]

#: Fixed on-disk names (plan §9.1).
MANIFEST_FILENAME = "manifest.json"
COMPLETE_FILENAME = "COMPLETE"
ARRAYS_DIRNAME = "arrays"

#: Rows-insensitive hashing block for files (bounded peak allocation, plan §13).
_HASH_CHUNK = 1 << 20

#: The literal id prefix stripped to form an artifact directory name.
_ID_PREFIX = "sha256:"


class StoreError(ValueError):
    """A bundle is missing, incomplete, corrupt or unsafe to read (plan §11)."""


class MigrationRequiredError(StoreError):
    """A bundle carries a version this build cannot read and cannot migrate."""


# ── write protocol (plan §9.3) ──────────────────────────────────────────


def store_bundle(bundle: ArtifactBundle, destination: str | Path) -> Path:
    """Write ``bundle`` to a new ``destination`` directory (storage v1).

    Validates the complete bundle before any I/O, stages into a unique sibling
    directory on the same filesystem, streams each array file's SHA-256 from
    disk, writes the canonical manifest and finally the ``COMPLETE`` marker,
    fsyncs and atomically renames staging onto the destination. An existing
    destination is refused (no implicit overwrite) and any failure removes only
    the staging directory this call created.

    Args:
        bundle: the validated recording-level processing state to persist.
        destination: the (not yet existing) bundle directory to create.

    Returns:
        The created destination as a :class:`~pathlib.Path`.

    Raises:
        FileExistsError: when ``destination`` already exists.
        StoreError: when the bundle fails the pre-I/O integrity replay.
        OSError: for a filesystem failure while staging or renaming.
    """
    validated = _validate_for_write(bundle)
    target = Path(destination)
    if os.path.lexists(target):
        raise FileExistsError(
            f"destination {target.name!r} already exists; storage v1 has no "
            "in-place migration, write to a new destination"
        )
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=parent, prefix=f".{target.name}.staging-"))
    try:
        _write_bundle(validated, staging)
        os.rename(staging, target)
        _fsync_dir(parent)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


def _validate_for_write(bundle: object) -> ArtifactBundle:
    """Return a validated bundle, running the id replay before any I/O."""
    if isinstance(bundle, ArtifactBundle):
        validated = bundle
    else:
        try:
            validated = ArtifactBundle.model_validate(bundle)
        except ValidationError as exc:
            raise StoreError(f"cannot store an invalid bundle: {exc}") from exc
    _replay_ids(validated)
    return validated


def _write_bundle(bundle: ArtifactBundle, staging: Path) -> None:
    """Write every array, the manifest and the COMPLETE marker into staging."""
    arrays_root = staging / ARRAYS_DIRNAME
    arrays_root.mkdir()
    stored_streams = []
    for stream in bundle.recording.streams:
        safe = _artifact_dir_name(stream.artifact_id)
        artifact_dir = arrays_root / safe
        artifact_dir.mkdir()
        stored_streams.append(_store_stream(artifact_dir, safe, stream))

    recording = StoredRecordingV1(
        recording_id=bundle.recording.recording_id,
        source_asset=bundle.recording.source_asset,
        acquisition_mode=bundle.recording.acquisition_mode,
        streams=tuple(stored_streams),
        acquisition_order=bundle.recording.acquisition_order,
    )
    manifest = BundleManifestV1(
        storage_schema_version=STORAGE_SCHEMA_VERSION,
        domain_schema_version=DOMAIN_SCHEMA_VERSION,
        operation_schema_version=OPERATION_SCHEMA_VERSION,
        recording=recording,
        graph=bundle.graph,
    )
    raw = canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"
    _write_bytes(staging / MANIFEST_FILENAME, raw)
    manifest_sha = sha256_hex(raw)
    marker = f"{manifest_sha}  {MANIFEST_FILENAME}\n".encode()
    _write_bytes(staging / COMPLETE_FILENAME, marker)
    _fsync_dir(staging)


def _store_stream(
    artifact_dir: Path, safe: str, stream: ChannelArtifact
) -> StoredChannelArtifactV1:
    """Write one artifact's owned arrays and return its typed projection."""
    data = stream.data
    support = StoredSampleSupportV1(
        kind=_write_array(artifact_dir, safe, "support_kind", data.support.kind),
        valid=_write_array(artifact_dir, safe, "support_valid", data.support.valid),
        quality=_write_array(
            artifact_dir, safe, "support_quality", data.support.quality
        ),
    )
    acquisition: StoredAcquisitionIndexV1 | None = None
    if data.acquisition is not None:
        index = data.acquisition
        optional: dict[str, ArrayRef | None] = {}
        for name in ("round_id", "visit_id", "profile_in_visit"):
            array = getattr(index, name)
            optional[name] = (
                None if array is None else _write_array(artifact_dir, safe, name, array)
            )
        acquisition = StoredAcquisitionIndexV1(
            sample_id=_write_array(artifact_dir, safe, "sample_id", index.sample_id),
            acquisition_time_s=_write_array(
                artifact_dir, safe, "acquisition_time_s", index.acquisition_time_s
            ),
            round_id=optional["round_id"],
            visit_id=optional["visit_id"],
            profile_in_visit=optional["profile_in_visit"],
        )
    return StoredChannelArtifactV1(
        artifact_id=stream.artifact_id,
        acquisition=stream.acquisition,
        descriptor=stream.descriptor,
        config=stream.config,
        data=StoredSignalDataV1(
            time_s=_write_array(artifact_dir, safe, "time_s", data.time_s),
            gate_depths_mm=_write_array(
                artifact_dir, safe, "gate_depths_mm", data.gate_depths_mm
            ),
            values=_write_array(artifact_dir, safe, "values", data.values),
            support=support,
            acquisition=acquisition,
        ),
    )


def _write_array(
    artifact_dir: Path, safe: str, name: str, array: np.ndarray
) -> ArrayRef:
    """Persist one array and build its ``ArrayRef`` from the bytes on disk."""
    file_path = artifact_dir / f"{name}.npy"
    _save_array(file_path, array)
    digest = _hash_file(file_path)
    return ArrayRef(
        path=f"{ARRAYS_DIRNAME}/{safe}/{name}.npy",
        dtype=_dtype_name(array.dtype),
        shape=tuple(int(axis) for axis in array.shape),
        nbytes=int(array.nbytes),
        sha256=digest,
    )


def _save_array(path: Path, array: np.ndarray) -> None:
    """Write one array as ``.npy`` (never pickle) and fsync it."""
    with open(path, "wb") as handle:
        np.save(handle, np.ascontiguousarray(array), allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())


def _write_bytes(path: Path, raw: bytes) -> None:
    """Write ``raw`` and fsync the file."""
    with open(path, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    """Fsync a directory so a rename/marker is durable, where that is possible.

    Windows has no documented, portable way to do this: ``os.O_DIRECTORY`` is
    POSIX-only, ``os.open`` refuses a directory there in every mode (CPython has
    no way to pass ``FILE_FLAG_BACKUP_SEMANTICS``), and ``FlushFileBuffers`` is
    documented for file and volume handles only. An undocumented route exists —
    ``ctypes`` ``CreateFileW`` with ``FILE_FLAG_BACKUP_SEMANTICS |
    GENERIC_WRITE``, which did return TRUE when measured on NTFS — but it is
    unverified, filesystem-dependent (it fails on SMB shares: Go's ``File.Sync``
    takes that route and reports ``ERROR_INVALID_DEVICE_REQUEST`` there), and it
    would add a failure mode in exchange for durability nothing here can
    confirm. So the gate is an explicit no-op on Windows.

    That gives up nothing this store was relying on: every file's bytes are
    already fsynced (:func:`_write_bytes` for the manifest and ``COMPLETE``,
    :func:`_save_array` for each array) before the rename, so only NTFS's own
    ordering for the new directory entry is left to the OS — and the documented
    alternative, ``FILE_FLAG_WRITE_THROUGH``, is a property of the handle used
    for the write, which ``os.rename`` cannot request. On POSIX nothing changes:
    a directory open or fsync failure still propagates.
    """
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _artifact_dir_name(artifact_id: str) -> str:
    """Return the safe directory component: id with only ``sha256:`` removed."""
    name = artifact_id.removeprefix(_ID_PREFIX)
    if not name or name in {".", ".."} or "/" in name or "\\" in name or ":" in name:
        raise StoreError(
            f"artifact id {artifact_id!r} does not map to a safe directory "
            "component; only the literal 'sha256:' prefix may be removed"
        )
    return name


def _dtype_name(dtype: np.dtype) -> Any:
    """Return the storage-v1 dtype name or reject an unsupported dtype."""
    name = np.dtype(dtype).name
    if name not in ARRAY_DTYPES:
        raise StoreError(
            f"array dtype {name!r} is not storable; storage v1 permits "
            f"{list(ARRAY_DTYPES)}"
        )
    return name


def _hash_file(path: Path) -> str:
    """Stream the lower-case hex SHA-256 of a file in bounded chunks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# ── read protocol (plan §9.3) ───────────────────────────────────────────


def load_bundle(bundle_root: str | Path) -> ArtifactBundle:
    """Read and fully validate a storage-v1 bundle directory (plan §9.3).

    Args:
        bundle_root: an existing bundle directory.

    Returns:
        A reconstructed :class:`~udv_echo_process.provenance.ArtifactBundle`
        with owned, C-contiguous, read-only arrays and identical
        artifact/operation ids.

    Raises:
        StoreError: the bundle is missing, incomplete, corrupt, unsafe or fails
            domain/DAG/id validation.
        MigrationRequiredError: a version this build cannot read.
    """
    root = Path(bundle_root)
    if not root.is_dir():
        raise StoreError(f"bundle {root.name!r} is not a directory")

    # 1. Reject a missing/malformed COMPLETE before touching arrays.
    manifest_sha = _read_complete(root)

    # 2. Verify the manifest hash, JSON, versions and strict schema.
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise StoreError(f"missing {MANIFEST_FILENAME} in bundle {root.name!r}")
    raw_manifest = manifest_path.read_bytes()
    actual_sha = sha256_hex(raw_manifest)
    if actual_sha != manifest_sha:
        raise StoreError(
            f"{MANIFEST_FILENAME} hash mismatch: expected {manifest_sha}, "
            f"got {actual_sha}"
        )
    payload = _parse_manifest(raw_manifest, root)
    _check_versions(payload)
    try:
        manifest = BundleManifestV1.model_validate(payload)
    except ValidationError as exc:
        raise StoreError(
            f"{MANIFEST_FILENAME} does not match the storage schema: {exc}"
        ) from exc

    # 3./4. Resolve and verify every ArrayRef, then scan arrays/ for stray files.
    arrays = _read_arrays(root, manifest)

    # 5./6. Reconstruct owned read-only arrays, re-run all validation and replay.
    bundle = _reconstruct(manifest, arrays)
    _replay_ids(bundle)
    return bundle


def _read_complete(root: Path) -> str:
    """Return the manifest SHA-256 declared by a well-formed COMPLETE marker."""
    marker_path = root / COMPLETE_FILENAME
    if not marker_path.is_file():
        raise StoreError(
            f"missing {COMPLETE_FILENAME} marker in bundle {root.name!r}; the "
            "store is incomplete"
        )
    raw = marker_path.read_bytes()
    malformed = StoreError(
        f"malformed {COMPLETE_FILENAME} marker in bundle {root.name!r}; it must "
        f"be '<manifest sha256>  {MANIFEST_FILENAME}\\n'"
    )
    if not raw.endswith(b"\n"):
        raise malformed
    body = raw[:-1]
    if b"\n" in body:
        raise malformed
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise malformed from exc
    digest, separator, name = text.partition("  ")
    if separator != "  " or name != MANIFEST_FILENAME or not _is_hex64(digest):
        raise malformed
    return digest


def _is_hex64(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _parse_manifest(raw: bytes, root: Path) -> dict[str, Any]:
    """Decode the manifest bytes into a JSON object."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StoreError(
            f"{MANIFEST_FILENAME} in bundle {root.name!r} is not valid UTF-8: {exc}"
        ) from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise StoreError(
            f"{MANIFEST_FILENAME} in bundle {root.name!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise StoreError(
            f"{MANIFEST_FILENAME} in bundle {root.name!r} must be a JSON object, "
            f"got {type(payload).__name__}"
        )
    return payload


def _check_versions(payload: Mapping[str, Any]) -> None:
    """Verify all three independent versions, never collapsing them (plan §9.3)."""
    checks = (
        ("storage_schema_version", SUPPORTED_STORAGE_SCHEMA_VERSIONS),
        ("domain_schema_version", SUPPORTED_DOMAIN_SCHEMA_VERSIONS),
        ("operation_schema_version", SUPPORTED_OPERATION_SCHEMA_VERSIONS),
    )
    for field, supported in checks:
        found = payload.get(field)
        label = field.replace("_", " ")
        if isinstance(found, bool) or not isinstance(found, int) or found < 1:
            raise StoreError(
                f"{MANIFEST_FILENAME} field {field!r} must be a positive integer, "
                f"got {found!r}"
            )
        if found not in supported:
            raise MigrationRequiredError(
                f"unsupported {label} {found}: found {found}, supported "
                f"{list(supported)}; migration required and none exists for "
                f"{label} {found}"
            )


def _iter_refs(manifest: BundleManifestV1) -> Iterator[ArrayRef]:
    """Yield every ``ArrayRef`` in the manifest in a deterministic order."""
    for stream in manifest.recording.streams:
        data = stream.data
        yield data.time_s
        yield data.gate_depths_mm
        yield data.values
        yield data.support.kind
        yield data.support.valid
        yield data.support.quality
        acquisition = data.acquisition
        if acquisition is not None:
            yield acquisition.sample_id
            yield acquisition.acquisition_time_s
            for name in ("round_id", "visit_id", "profile_in_visit"):
                ref = getattr(acquisition, name)
                if ref is not None:
                    yield ref


def _read_arrays(root: Path, manifest: BundleManifestV1) -> dict[str, np.ndarray]:
    """Verify and load every referenced array, then reject stray/duplicate files."""
    refs = list(_iter_refs(manifest))
    paths = [ref.path for ref in refs]
    duplicates = sorted({path for path in paths if paths.count(path) > 1})
    if duplicates:
        raise StoreError(
            f"duplicate array path {duplicates[0]!r} referenced more than once in "
            f"{MANIFEST_FILENAME}"
        )
    arrays: dict[str, np.ndarray] = {}
    for ref in refs:
        arrays[ref.path] = _load_array(root, ref)

    on_disk = _array_files(root)
    referenced = set(paths)
    unreferenced = sorted(on_disk - referenced)
    if unreferenced:
        raise StoreError(
            f"unreferenced array file(s) under {ARRAYS_DIRNAME}/: {unreferenced}"
        )
    missing = sorted(referenced - on_disk)
    if missing:
        raise StoreError(f"missing array file(s) under {ARRAYS_DIRNAME}/: {missing}")
    return arrays


def _array_files(root: Path) -> set[str]:
    """Return every file path (bundle-relative POSIX) under ``arrays/``."""
    arrays_root = root / ARRAYS_DIRNAME
    if not arrays_root.is_dir():
        raise StoreError(f"missing {ARRAYS_DIRNAME}/ directory in bundle {root.name!r}")
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(arrays_root, followlinks=False):
        for name in filenames:
            full = Path(dirpath) / name
            found.add(full.relative_to(root).as_posix())
        for name in dirnames:
            full = Path(dirpath) / name
            if full.is_symlink():
                found.add(full.relative_to(root).as_posix())
    return found


def _load_array(root: Path, ref: ArrayRef) -> np.ndarray:
    """Resolve, hash-verify, header-verify and load one referenced array."""
    full = _resolve_array_path(root, ref.path)
    digest = _hash_file(full)
    if digest != ref.sha256:
        raise StoreError(
            f"array {ref.path!r} hash mismatch: expected {ref.sha256}, got {digest}"
        )
    shape, fortran_order, dtype = _read_npy_header(full, ref.path)
    expected_dtype = np.dtype(ref.dtype)
    if dtype != expected_dtype:
        raise StoreError(
            f"array {ref.path!r} dtype mismatch: expected {ref.dtype}, header has "
            f"{dtype.name!r}"
        )
    if tuple(shape) != tuple(ref.shape):
        raise StoreError(
            f"array {ref.path!r} shape mismatch: expected {tuple(ref.shape)}, "
            f"header has {tuple(shape)}"
        )
    if fortran_order:
        raise StoreError(
            f"array {ref.path!r} is Fortran-ordered; storage v1 stores C-order arrays"
        )
    array = np.load(full, allow_pickle=False)
    if int(array.nbytes) != ref.nbytes:
        raise StoreError(
            f"array {ref.path!r} nbytes mismatch: expected {ref.nbytes}, got "
            f"{int(array.nbytes)}"
        )
    array = np.ascontiguousarray(array)
    array.flags.writeable = False
    return array


def _read_npy_header(
    path: Path, rel_path: str
) -> tuple[tuple[int, ...], bool, np.dtype]:
    """Read a ``.npy`` header (magic/version, shape, Fortran flag, dtype)."""
    try:
        with open(path, "rb") as handle:
            version = np.lib.format.read_magic(handle)
            if version == (1, 0):
                shape, fortran_order, dtype = np.lib.format.read_array_header_1_0(
                    handle
                )
            elif version == (2, 0):
                shape, fortran_order, dtype = np.lib.format.read_array_header_2_0(
                    handle
                )
            else:
                raise StoreError(
                    f"array {rel_path!r} uses unsupported NPY format version {version}"
                )
    except StoreError:
        raise
    except (OSError, ValueError, EOFError) as exc:
        raise StoreError(
            f"array {rel_path!r} has an unreadable NPY header: {exc}"
        ) from exc
    return tuple(shape), bool(fortran_order), np.dtype(dtype)


def _resolve_array_path(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` safely inside ``root`` (no symlink, no escape)."""
    relative = Path(rel_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise StoreError(
            f"array path {rel_path!r} is not a normalized relative POSIX path "
            "inside the bundle"
        )
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise StoreError(
                f"array path {rel_path!r} traverses a symlink at {part!r}; "
                "storage v1 rejects symlinked arrays"
            )
    full = root / relative
    if not full.exists():
        raise StoreError(f"missing array file {rel_path!r}")
    if not full.is_file():
        raise StoreError(f"array path {rel_path!r} is not a regular file")
    resolved_root = os.path.realpath(root)
    resolved = os.path.realpath(full)
    if os.path.commonpath([resolved_root, resolved]) != resolved_root:
        raise StoreError(f"array path {rel_path!r} escapes the bundle root")
    return full


def _reconstruct(
    manifest: BundleManifestV1, arrays: Mapping[str, np.ndarray]
) -> ArtifactBundle:
    """Rebuild the runtime domain bundle from the manifest and loaded arrays."""
    try:
        streams = []
        for stream in manifest.recording.streams:
            stored = stream.data
            acquisition = None
            index = stored.acquisition
            if index is not None:
                acquisition = AcquisitionIndex(
                    sample_id=arrays[index.sample_id.path],
                    acquisition_time_s=arrays[index.acquisition_time_s.path],
                    round_id=(
                        None if index.round_id is None else arrays[index.round_id.path]
                    ),
                    visit_id=(
                        None if index.visit_id is None else arrays[index.visit_id.path]
                    ),
                    profile_in_visit=(
                        None
                        if index.profile_in_visit is None
                        else arrays[index.profile_in_visit.path]
                    ),
                )
            data = SignalData(
                time_s=arrays[stored.time_s.path],
                gate_depths_mm=arrays[stored.gate_depths_mm.path],
                values=arrays[stored.values.path],
                support=SampleSupport(
                    kind=arrays[stored.support.kind.path],
                    valid=arrays[stored.support.valid.path],
                    quality=arrays[stored.support.quality.path],
                ),
                acquisition=acquisition,
            )
            streams.append(
                ChannelArtifact(
                    artifact_id=stream.artifact_id,
                    acquisition=stream.acquisition,
                    descriptor=stream.descriptor,
                    config=stream.config,
                    data=data,
                )
            )
        recording = Recording(
            recording_id=manifest.recording.recording_id,
            source_asset=manifest.recording.source_asset,
            acquisition_mode=manifest.recording.acquisition_mode,
            streams=tuple(streams),
            acquisition_order=manifest.recording.acquisition_order,
        )
        return ArtifactBundle(recording=recording, graph=manifest.graph)
    except ValidationError as exc:
        raise StoreError(
            f"bundle fails domain/DAG validation after load: {exc}"
        ) from exc


def _replay_ids(bundle: ArtifactBundle) -> None:
    """Recompute every operation and root/derived artifact id (plan §9.3 step 6).

    Also resolves every operation through the registry and revalidates its
    ``params_json`` with the registered spec (plan §8.1's reader rule), so a
    stored recipe the current build no longer understands fails closed.
    """
    graph = bundle.graph
    for index, operation in enumerate(graph.operations):
        try:
            revalidate_params(
                operation.kind, operation.schema_version, operation.params_json
            )
        except (ValueError, ValidationError) as exc:
            raise StoreError(
                f"operations[{index}] kind {operation.kind!r} schema_version "
                f"{operation.schema_version} cannot be revalidated with the "
                f"registered operation spec: {exc}"
            ) from exc
        expected = operation_id_for(
            operation.kind,
            operation.schema_version,
            operation.params_json,
            operation.implementation,
            operation.parents,
        )
        if expected != operation.operation_id:
            raise StoreError(
                f"operations[{index}] operation_id {operation.operation_id!r} does "
                f"not replay: recomputes to {expected!r} from kind "
                f"{operation.kind!r} and its params"
            )
    producer = {link.artifact_id: link.operation_id for link in graph.derivations}
    for index, stream in enumerate(bundle.recording.streams):
        channel = stream.acquisition.channel.device_channel
        operation_id = producer.get(stream.artifact_id)
        if operation_id is None:
            expected = source_artifact_id(
                stream.acquisition, stream.descriptor, stream.config, stream.data
            )
        else:
            expected = derived_artifact_id(
                operation_id,
                stream.acquisition,
                stream.descriptor,
                stream.config,
                stream.data,
            )
        if expected != stream.artifact_id:
            raise StoreError(
                f"recording stream {index} (channel {channel}) artifact_id "
                f"{stream.artifact_id!r} does not replay: recomputes to "
                f"{expected!r} from its content"
            )
