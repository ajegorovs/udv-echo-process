"""Phase 8 storage tests: the NPY + manifest store (plan §9, §13, §14).

Red-green-refactor acceptance for ``udv_echo_process.storage``: round-trips of
observed/missing/synthetic payloads (with and without the optional acquisition
index) over a multi-generation ``derive`` + ``filter`` DAG, a committed ``.BDD``
fixture through ``tmp_path``, and failure injection for every §9.3 read rule —
incomplete/incorrect ``COMPLETE``, corrupt manifest/array content, dtype/shape/
nbytes mismatch, the three independent unknown versions, unsafe array paths,
duplicate/unreferenced arrays, an existing destination and an interrupted write.

The STOP/GO gates are proven here: the manifest does not scale with ``T*G``,
pickle is never used, and a partially written destination can never be mistaken
for complete.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.io.dop.bdd import read as read_bdd
from udv_echo_process.models import (
    AcquisitionIndex,
    AcquisitionMode,
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    Recording,
    SampleSupport,
    SignalData,
    SignalDescriptor,
    SignalQuantity,
    SourceAsset,
    SourceFormat,
    SourceSpec,
    SupportKind,
    ValueModel,
    missing_signal,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models._canonical import canonical_json_bytes
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.process import (
    MeanFilterSpec,
    MedianFilterSpec,
    derive,
    filter,
    register_operation,
)
from udv_echo_process.provenance import (
    ArtifactBundle,
    ArtifactGraph,
    implementation_ref,
    register_root_artifact,
    replace_channel,
    select_channel,
)
from udv_echo_process.storage import (
    ArrayRef,
    BundleManifestV1,
    MigrationRequiredError,
    StoredAcquisitionIndexV1,
    StoredChannelArtifactV1,
    StoredRecordingV1,
    StoredSampleSupportV1,
    StoredSignalDataV1,
    StoreError,
    load_bundle,
    store_bundle,
)
from udv_echo_process.storage.models import ARRAY_DTYPES

DATA = Path("data")
ECHO_200 = DATA / "echo" / "200.BDD"

MANIFEST = "manifest.json"
COMPLETE = "COMPLETE"
ARRAYS = "arrays"

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "src" / "udv_echo_process" / "storage"

# ── shared fixtures ─────────────────────────────────────────────────────

_HEX = "a" * 64
_IMPL = implementation_ref("udv_echo_process.process.derive.derive")

_ASSET = SourceAsset(
    asset_id="sha256:" + _HEX,
    content_sha256=_HEX,
    byte_size=4096,
    file_name="fixture.BDD",
    source=SourceSpec(format=SourceFormat.BDD),
)
_RECORDING_ID = recording_id_for(_ASSET.asset_id)
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")


class StorageNoopSpec(ValueModel):
    """A trivial registered operation used to exercise ``derive`` in a DAG."""

    method: str = "storage-noop"
    scale: float = 1.0


register_operation("storage.noop", StorageNoopSpec)


def _gates(n: int) -> np.ndarray:
    return np.arange(1, n + 1, dtype=np.float64)


def _observed_index(length: int, *, optional: bool) -> AcquisitionIndex:
    ids = np.arange(length, dtype=np.int64) + 11
    if not optional:
        return AcquisitionIndex(
            sample_id=ids,
            acquisition_time_s=np.arange(length, dtype=np.float64) * 0.5,
        )
    return AcquisitionIndex(
        sample_id=ids,
        acquisition_time_s=np.arange(length, dtype=np.float64) * 0.5,
        round_id=np.arange(length, dtype=np.int64),
        visit_id=np.zeros(length, dtype=np.int64),
        profile_in_visit=np.arange(length, dtype=np.int64),
    )


def _synthetic_index(length: int) -> AcquisitionIndex:
    return AcquisitionIndex(
        sample_id=np.full(length, -1, dtype=np.int64),
        acquisition_time_s=np.full(length, np.nan, dtype=np.float64),
    )


def _signal(kind: str, *, with_index: bool) -> SignalData:
    if kind == "observed":
        length, gates = 6, 3
        values = np.arange(length * gates, dtype=np.float64).reshape(length, gates)
        index = _observed_index(length, optional=True) if with_index else None
        return observed_signal(
            np.arange(length, dtype=np.float64) * 0.5,
            _gates(gates),
            values,
            acquisition=index,
        )
    if kind == "missing":
        length, gates = 5, 3
        index = _synthetic_index(length) if with_index else None
        return missing_signal(
            np.arange(length, dtype=np.float64) * 0.5, _gates(gates), acquisition=index
        )
    assert kind == "synthetic"
    length, gates = 6, 3
    values = np.full((length, gates), np.nan, dtype=np.float64)
    values[:4] = np.arange(4 * gates, dtype=np.float64).reshape(4, gates) + 1.0
    kind_arr = np.array(
        [SupportKind.OBSERVED] * 4 + [SupportKind.MISSING] * 2, dtype=np.uint8
    )
    kind_arr = np.repeat(kind_arr[:, None], gates, axis=1)
    valid = kind_arr == int(SupportKind.OBSERVED)
    support = SampleSupport(
        kind=kind_arr,
        valid=valid,
        quality=np.zeros((length, gates), dtype=np.uint32),
    )
    index = None
    if with_index:
        index = AcquisitionIndex(
            sample_id=np.array([1, 2, 3, 4, -1, -1], dtype=np.int64),
            acquisition_time_s=np.array(
                [0.0, 0.5, 1.0, 1.5, np.nan, np.nan], dtype=np.float64
            ),
            round_id=np.array([0, 1, 2, 3, -1, -1], dtype=np.int64),
            visit_id=np.array([0, 0, 0, 0, -1, -1], dtype=np.int64),
            profile_in_visit=np.array([0, 1, 2, 3, -1, -1], dtype=np.int64),
        )
    return SignalData(
        time_s=np.arange(length, dtype=np.float64) * 0.5,
        gate_depths_mm=_gates(gates),
        values=values,
        support=support,
        acquisition=index,
    )


def _build_artifact(channel: int, kind: str, *, with_index: bool):
    data = _signal(kind, with_index=with_index)
    acquisition = AcquisitionRef(
        recording_id=_RECORDING_ID,
        source_asset_id=_ASSET.asset_id,
        channel=ChannelKey(device_channel=channel),
    )
    config = ChannelConfig(n_gates=data.gate_depths_mm.shape[0], sound_speed_ms=1480.0)
    return source_artifact(acquisition, _ECHO, config, data)


def _bundle(
    artifacts: tuple, *, order: tuple[ChannelKey, ...] | None = None
) -> ArtifactBundle:
    graph = ArtifactGraph()
    for artifact in artifacts:
        graph = register_root_artifact(graph, artifact.artifact_id)
    return ArtifactBundle(
        recording=Recording(
            recording_id=_RECORDING_ID,
            source_asset=_ASSET,
            acquisition_mode=AcquisitionMode.UNKNOWN,
            streams=tuple(artifacts),
            acquisition_order=order,
        ),
        graph=graph,
    )


def _fresh(data: SignalData) -> SignalData:
    acquisition = data.acquisition
    if acquisition is not None:
        acquisition = AcquisitionIndex(
            sample_id=acquisition.sample_id,
            acquisition_time_s=acquisition.acquisition_time_s,
            round_id=acquisition.round_id,
            visit_id=acquisition.visit_id,
            profile_in_visit=acquisition.profile_in_visit,
        )
    return SignalData(
        time_s=data.time_s,
        gate_depths_mm=data.gate_depths_mm,
        values=data.values.copy(),
        support=SampleSupport(
            kind=data.support.kind,
            valid=data.support.valid,
            quality=data.support.quality,
        ),
        acquisition=acquisition,
    )


def _deepen(bundle: ArtifactBundle, channel: int) -> ArtifactBundle:
    """A multi-generation DAG: filter, filter, derive, filter (4 operations)."""
    channel_bundle = select_channel(bundle, ChannelKey(device_channel=channel))
    channel_bundle = filter(channel_bundle, MedianFilterSpec(window=3, max_gap_s=10.0))
    channel_bundle = filter(channel_bundle, MeanFilterSpec(window=3, max_gap_s=10.0))
    channel_bundle = derive(
        channel_bundle,
        kind="storage.noop",
        spec=StorageNoopSpec(),
        implementation=_IMPL,
        data=_fresh(channel_bundle.artifact.data),
    )
    channel_bundle = filter(channel_bundle, MedianFilterSpec(window=5, max_gap_s=10.0))
    return replace_channel(bundle, channel_bundle)


# ── manifest / array comparison helpers ─────────────────────────────────


def _signal_arrays(data: SignalData) -> list[tuple[str, np.ndarray]]:
    entries = [
        ("time_s", data.time_s),
        ("gate_depths_mm", data.gate_depths_mm),
        ("values", data.values),
        ("support_kind", data.support.kind),
        ("support_valid", data.support.valid),
        ("support_quality", data.support.quality),
    ]
    acquisition = data.acquisition
    if acquisition is not None:
        entries.append(("sample_id", acquisition.sample_id))
        entries.append(("acquisition_time_s", acquisition.acquisition_time_s))
        for name in ("round_id", "visit_id", "profile_in_visit"):
            array = getattr(acquisition, name)
            if array is not None:
                entries.append((name, array))
    return entries


def _assert_arrays_identical(left: SignalData, right: SignalData) -> None:
    left_arrays = dict(_signal_arrays(left))
    right_arrays = dict(_signal_arrays(right))
    assert set(left_arrays) == set(right_arrays)
    for name, array in left_arrays.items():
        other = right_arrays[name]
        assert array.dtype == other.dtype, name
        assert array.shape == other.shape, name
        assert array.tobytes() == other.tobytes(), name


def _assert_bundle_equal(loaded: ArtifactBundle, original: ArtifactBundle) -> None:
    assert loaded is not original
    assert loaded.recording.recording_id == original.recording.recording_id
    assert loaded.recording.source_asset == original.recording.source_asset
    assert loaded.recording.acquisition_mode == original.recording.acquisition_mode
    assert loaded.recording.acquisition_order == original.recording.acquisition_order
    assert loaded.graph == original.graph
    assert [op.operation_id for op in loaded.graph.operations] == [
        op.operation_id for op in original.graph.operations
    ]
    assert len(loaded.recording.streams) == len(original.recording.streams)
    for loaded_stream, original_stream in zip(
        loaded.recording.streams, original.recording.streams, strict=True
    ):
        assert loaded_stream.artifact_id == original_stream.artifact_id
        assert loaded_stream.acquisition == original_stream.acquisition
        assert loaded_stream.descriptor == original_stream.descriptor
        assert loaded_stream.config == original_stream.config
        _assert_arrays_identical(loaded_stream.data, original_stream.data)
        for _, array in _signal_arrays(loaded_stream.data):
            assert array.flags["OWNDATA"] is True
            assert array.flags["C_CONTIGUOUS"] is True
            assert array.flags["WRITEABLE"] is False


def _manifest_dict(bundle_dir: Path) -> dict:
    return json.loads((bundle_dir / MANIFEST).read_text())


def _array_path(bundle_dir: Path, index: int, *keys: str) -> Path:
    node = _manifest_dict(bundle_dir)["recording"]["streams"][index]["data"]
    for key in keys:
        node = node[key]
    return bundle_dir / node["path"]


def _write_complete(bundle_dir: Path, raw: bytes) -> None:
    digest = hashlib.sha256(raw).hexdigest()
    (bundle_dir / COMPLETE).write_bytes(f"{digest}  {MANIFEST}\n".encode())


def _write_manifest(bundle_dir: Path, raw: bytes) -> None:
    (bundle_dir / MANIFEST).write_bytes(raw)
    _write_complete(bundle_dir, raw)


def _mutate_manifest(bundle_dir: Path, mutate) -> None:
    data = _manifest_dict(bundle_dir)
    mutate(data)
    _write_manifest(bundle_dir, canonical_json_bytes(data) + b"\n")


def _alias(dst: dict, src: dict) -> None:
    if "path" in src:
        dst.clear()
        dst.update(src)
        return
    for key, value in src.items():
        if isinstance(value, dict):
            _alias(dst[key], value)


# ── round-trips ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["observed", "missing", "synthetic"])
@pytest.mark.parametrize("with_index", [False, True])
def test_round_trip_observed_missing_synthetic(tmp_path, kind, with_index):
    bundle = _deepen(_bundle((_build_artifact(4, kind, with_index=with_index),)), 4)
    assert len(bundle.graph.operations) == 4
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    loaded = load_bundle(destination)
    _assert_bundle_equal(loaded, bundle)
    assert len(loaded.graph.derivations) == 4
    assert loaded.graph.root_artifacts == bundle.graph.root_artifacts


@pytest.mark.parametrize("with_index", [False, True])
def test_round_trip_multi_channel_with_order(tmp_path, with_index):
    first = _build_artifact(6, "observed", with_index=with_index)
    second = _build_artifact(7, "observed", with_index=with_index)
    bundle = _deepen(
        _bundle(
            (first, second),
            order=(ChannelKey(device_channel=6), ChannelKey(device_channel=7)),
        ),
        6,
    )
    destination = tmp_path / "multi"
    store_bundle(bundle, destination)
    loaded = load_bundle(destination)
    _assert_bundle_equal(loaded, bundle)
    # one directory per artifact, named by the id with only the prefix removed
    for stream in bundle.recording.streams:
        safe = stream.artifact_id.removeprefix("sha256:")
        assert (destination / ARRAYS / safe).is_dir()


def test_round_trip_committed_bdd_fixture(tmp_path):
    bundle = read_bdd(ECHO_200)
    destination = tmp_path / "echo200"
    store_bundle(bundle, destination)
    loaded = load_bundle(destination)
    _assert_bundle_equal(loaded, bundle)
    assert loaded.recording.source_asset == bundle.recording.source_asset
    assert loaded.graph.operations == ()
    assert loaded.recording.streams[0].data.values.shape == (4180, 26)
    assert loaded.recording.streams[0].data.acquisition is not None


def test_manifest_contains_arefs_and_no_inline_arrays(tmp_path):
    bundle = _deepen(_bundle((_build_artifact(4, "synthetic", with_index=True),)), 4)
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    manifest = _manifest_dict(destination)
    stream = manifest["recording"]["streams"][0]
    refs = [
        stream["data"]["time_s"],
        stream["data"]["gate_depths_mm"],
        stream["data"]["values"],
        stream["data"]["support"]["kind"],
        stream["data"]["support"]["valid"],
        stream["data"]["support"]["quality"],
        stream["data"]["acquisition"]["sample_id"],
        stream["data"]["acquisition"]["acquisition_time_s"],
        stream["data"]["acquisition"]["round_id"],
        stream["data"]["acquisition"]["visit_id"],
        stream["data"]["acquisition"]["profile_in_visit"],
    ]
    for ref in refs:
        assert set(ref) == {"path", "dtype", "shape", "nbytes", "sha256"}
        assert ref["dtype"] in ARRAY_DTYPES
        assert ref["path"].startswith(f"{ARRAYS}/")
        assert ":" not in ref["path"]

    def walk(node: object) -> None:
        if isinstance(node, list):
            assert len(node) <= 8  # only shape/operation/metadata tuples
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(manifest)


def test_manifest_models_are_typed_and_deeply_immutable(tmp_path):
    bundle = _deepen(_bundle((_build_artifact(4, "synthetic", with_index=True),)), 4)
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    manifest = BundleManifestV1.model_validate(_manifest_dict(destination))
    assert manifest.storage_schema_version == 1
    assert isinstance(manifest.graph, ArtifactGraph)
    assert isinstance(manifest.recording, StoredRecordingV1)
    assert isinstance(manifest.recording.streams, tuple)
    stream = manifest.recording.streams[0]
    assert isinstance(stream, StoredChannelArtifactV1)
    assert isinstance(stream.data, StoredSignalDataV1)
    assert isinstance(stream.data.values, ArrayRef)
    assert isinstance(stream.data.support, StoredSampleSupportV1)
    assert isinstance(stream.data.acquisition, StoredAcquisitionIndexV1)
    assert stream.data.acquisition.round_id is not None
    # deeply immutable: frozen children and tuple containers, no dict/list
    assert isinstance(stream.data.support.kind, ArrayRef)
    with pytest.raises((ValidationError, TypeError)):
        stream.data.values.path = "other"  # type: ignore[misc]
    with pytest.raises((ValidationError, TypeError)):
        manifest.recording = manifest.recording  # type: ignore[misc]


def test_manifest_has_no_absolute_path(tmp_path):
    bundle = _deepen(_bundle((_build_artifact(4, "observed", with_index=True),)), 4)
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    text = (destination / MANIFEST).read_text()
    assert "/home/" not in text
    assert str(tmp_path) not in text
    for stream in _manifest_dict(destination)["recording"]["streams"]:
        for name in ("time_s", "gate_depths_mm", "values"):
            assert not Path(stream["data"][name]["path"]).is_absolute()


# ── STOP/GO gates ───────────────────────────────────────────────────────


def _observed_bundle(length: int, gates: int) -> tuple[ArtifactBundle, int]:
    values = np.arange(length * gates, dtype=np.float64).reshape(length, gates)
    data = observed_signal(
        np.arange(length, dtype=np.float64) * 0.5, _gates(gates), values
    )
    acquisition = AcquisitionRef(
        recording_id=_RECORDING_ID,
        source_asset_id=_ASSET.asset_id,
        channel=ChannelKey(device_channel=4),
    )
    artifact = source_artifact(
        acquisition,
        _ECHO,
        ChannelConfig(n_gates=gates),
        data,
    )
    payload = sum(array.nbytes for _, array in _signal_arrays(data))
    return _bundle((artifact,)), payload


def test_manifest_size_does_not_scale_with_times_gates(tmp_path):
    small_bundle, small_payload = _observed_bundle(31, 17)
    large_bundle, large_payload = _observed_bundle(997, 991)
    small_dir = tmp_path / "small"
    large_dir = tmp_path / "large"
    store_bundle(small_bundle, small_dir)
    store_bundle(large_bundle, large_dir)
    small = (small_dir / MANIFEST).read_bytes()
    large = (large_dir / MANIFEST).read_bytes()
    # T*G grows ~1875x and the payload by megabytes, the manifest by a few bytes
    assert large_payload > 100 * small_payload
    assert large_payload - small_payload > 1_000_000
    assert len(large) - len(small) <= 64
    assert len(large) < 4000
    assert len(small) < 4000


def test_storage_package_never_uses_pickle():
    offenders: list[str] = []
    save_load_calls = 0
    for path in sorted(STORAGE_DIR.rglob("*.py")):
        source = path.read_text()
        if "import pickle" in source or "allow_pickle=True" in source:
            offenders.append(str(path))
        save_load_calls += source.count("allow_pickle=False")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"save", "load"}
            ):
                kwargs = {kw.arg for kw in node.keywords}
                assert "allow_pickle" in kwargs, (path, node.lineno)
    assert offenders == []
    assert save_load_calls >= 2


def test_partial_destination_fails_closed(tmp_path):
    bundle = _bundle((_build_artifact(4, "observed", with_index=True),))
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)

    removed = tmp_path / "removed_complete"
    shutil.copytree(destination, removed)
    (removed / COMPLETE).unlink()
    with pytest.raises(StoreError, match="COMPLETE"):
        load_bundle(removed)

    corrupted = tmp_path / "corrupted_complete"
    shutil.copytree(destination, corrupted)
    (corrupted / COMPLETE).write_bytes(b"garbage\n")
    with pytest.raises(StoreError, match="COMPLETE"):
        load_bundle(corrupted)


# ── failure injection: marker and manifest ──────────────────────────────


@pytest.fixture
def stored(tmp_path):
    bundle = _bundle((_build_artifact(4, "observed", with_index=True),))
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    return destination


def test_absent_complete_marker_fails_closed(stored):
    (stored / COMPLETE).unlink()
    with pytest.raises(StoreError, match="COMPLETE"):
        load_bundle(stored)


def test_incorrect_complete_contents_fail_closed(stored):
    (stored / COMPLETE).write_bytes(b"not the marker\n")
    with pytest.raises(StoreError, match="COMPLETE"):
        load_bundle(stored)


def test_complete_hash_mismatch_fails_closed(stored):
    (stored / COMPLETE).write_bytes(f"{'0' * 64}  {MANIFEST}\n".encode())
    with pytest.raises(StoreError, match="hash"):
        load_bundle(stored)


def test_corrupt_manifest_json_fails_closed(stored):
    _write_manifest(stored, b"{ this is not json")
    with pytest.raises(StoreError, match="JSON"):
        load_bundle(stored)


# ── failure injection: array integrity ──────────────────────────────────


def test_corrupt_array_file_hash_mismatch_fails_closed(stored):
    path = _array_path(stored, 0, "values")
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])
    with pytest.raises(StoreError, match="hash mismatch"):
        load_bundle(stored)


def test_truncated_array_file_hash_mismatch_fails_closed(stored):
    path = _array_path(stored, 0, "support", "kind")
    path.write_bytes(path.read_bytes()[:16])
    with pytest.raises(StoreError, match="hash mismatch"):
        load_bundle(stored)


def test_missing_referenced_array_file_fails_closed(stored):
    _array_path(stored, 0, "gate_depths_mm").unlink()
    with pytest.raises(StoreError, match="missing"):
        load_bundle(stored)


def test_wrong_dtype_fails_closed(stored):
    def mutate(data: dict) -> None:
        data["recording"]["streams"][0]["data"]["values"]["dtype"] = "int64"

    _mutate_manifest(stored, mutate)
    with pytest.raises(StoreError, match="dtype"):
        load_bundle(stored)


def test_wrong_shape_fails_closed(stored):
    def mutate(data: dict) -> None:
        data["recording"]["streams"][0]["data"]["values"]["shape"] = [3, 3]

    _mutate_manifest(stored, mutate)
    with pytest.raises(StoreError, match="shape"):
        load_bundle(stored)


def test_wrong_nbytes_fails_closed(stored):
    def mutate(data: dict) -> None:
        data["recording"]["streams"][0]["data"]["values"]["nbytes"] = 1

    _mutate_manifest(stored, mutate)
    with pytest.raises(StoreError, match="nbytes"):
        load_bundle(stored)


def test_unreferenced_array_file_fails_closed(stored):
    (stored / ARRAYS / "extra.npy").write_bytes(b"stray")
    with pytest.raises(StoreError, match="unreferenced"):
        load_bundle(stored)


def test_duplicate_array_path_fails_closed(tmp_path):
    first = _build_artifact(4, "observed", with_index=False)
    second = _build_artifact(5, "observed", with_index=False)
    bundle = _bundle((first, second))
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    manifest = _manifest_dict(destination)
    streams = manifest["recording"]["streams"]
    _alias(streams[1]["data"], streams[0]["data"])
    safe = streams[1]["artifact_id"].removeprefix("sha256:")
    shutil.rmtree(destination / ARRAYS / safe)
    _write_manifest(destination, canonical_json_bytes(manifest) + b"\n")
    with pytest.raises(StoreError, match="duplicate"):
        load_bundle(destination)


# ── failure injection: versions ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("storage_schema_version", 2, "storage schema version"),
        ("domain_schema_version", 99, "domain schema version"),
        ("operation_schema_version", 7, "operation schema version"),
    ],
)
def test_unknown_versions_require_migration(stored, field, value, fragment):
    _mutate_manifest(stored, lambda data: data.__setitem__(field, value))
    with pytest.raises(MigrationRequiredError, match=fragment) as raised:
        load_bundle(stored)
    message = str(raised.value)
    assert str(value) in message
    assert "1" in message


def test_operation_kind_must_revalidate(tmp_path, monkeypatch):
    """A stored recipe the current registry does not know fails closed (§8.1)."""
    from udv_echo_process.process.derive import OPERATION_SPEC_REGISTRY

    bundle = _deepen(_bundle((_build_artifact(4, "observed", with_index=False),)), 4)
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    monkeypatch.delitem(OPERATION_SPEC_REGISTRY, ("storage.noop", 1))
    with pytest.raises(StoreError, match="storage.noop"):
        load_bundle(destination)


# ── failure injection: unsafe array paths ───────────────────────────────


def test_absolute_array_path_rejected(stored):
    def mutate(data: dict) -> None:
        data["recording"]["streams"][0]["data"]["values"]["path"] = "/etc/passwd"

    _mutate_manifest(stored, mutate)
    with pytest.raises(StoreError, match="relative"):
        load_bundle(stored)


def test_parent_traversal_array_path_rejected(stored):
    def mutate(data: dict) -> None:
        data["recording"]["streams"][0]["data"]["values"]["path"] = "../evil.npy"

    _mutate_manifest(stored, mutate)
    with pytest.raises(StoreError, match="relative"):
        load_bundle(stored)


def test_symlinked_array_path_rejected(stored):
    path = _array_path(stored, 0, "values")
    path.unlink()
    os.symlink(_array_path(stored, 0, "time_s").name, path)
    with pytest.raises(StoreError, match="symlink"):
        load_bundle(stored)


# ── failure injection: destination and interrupted write ────────────────


def test_existing_destination_is_refused(tmp_path):
    bundle = _bundle((_build_artifact(4, "observed", with_index=True),))
    destination = tmp_path / "bundle"
    store_bundle(bundle, destination)
    with pytest.raises(FileExistsError, match="exists"):
        store_bundle(bundle, destination)


def test_interrupted_write_cleans_staging_and_leaves_no_destination(
    tmp_path, monkeypatch
):
    from udv_echo_process.storage import npy

    bundle = _bundle((_build_artifact(4, "observed", with_index=True),))
    destination = tmp_path / "bundle"
    real = npy._save_array
    calls = {"count": 0}

    def flaky(path, array):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated crash mid-write")
        return real(path, array)

    monkeypatch.setattr(npy, "_save_array", flaky)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store_bundle(bundle, destination)
    assert calls["count"] == 2
    assert not destination.exists()
    assert list(tmp_path.glob(f".{destination.name}.staging-*")) == []


# ── platform gate: directory flush ─────────────────────────────────────


def test_fsync_dir_survives_the_platform_directory_flush_gap(tmp_path, monkeypatch):
    """Windows cannot flush a directory, so the gate must not mask POSIX failures."""
    from udv_echo_process.storage import npy

    assert npy._fsync_dir(tmp_path) is None
    if os.name == "nt":
        return

    def explode(descriptor):
        raise OSError("simulated directory fsync failure")

    monkeypatch.setattr(npy.os, "fsync", explode)
    with pytest.raises(OSError, match="simulated directory fsync failure"):
        npy._fsync_dir(tmp_path)
