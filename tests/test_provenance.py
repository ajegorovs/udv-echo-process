"""Phase 3 provenance tests: artifact identity, the operation DAG and bundles.

Plan §6.6, §8.1, §8.2, §13. Locks in deterministic content-addressed source
artifact ids, explicit scientific equality, the model invariants for
``ImplementationRef`` / ``OperationRecord`` / ``ArtifactDerivationLink`` /
``ArtifactGraph`` / ``ChannelBundle`` and pure graph insertion.

The post-landing identity acceptance blockers are locked in here too:
``source_bundle`` replays the SOURCE artifact id from the artifact's own content
and ``OperationRecord`` replays the operation id from its canonical recipe
fields, so a counterfeit id cannot reach a graph through public construction.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import textwrap
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.models import (
    AcquisitionIndex,
    AcquisitionRef,
    ChannelArtifact,
    ChannelConfig,
    ChannelKey,
    QualityFlag,
    SignalDescriptor,
    SignalQuantity,
    ValueModel,
    array_digest,
    artifacts_equal,
    derived_artifact_id,
    observed_signal,
    signals_equal,
    source_artifact,
    source_artifact_id,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.process import derive, register_operation
from udv_echo_process.provenance import (
    ArtifactDerivationLink,
    ArtifactGraph,
    ChannelBundle,
    ImplementationRef,
    OperationRecord,
    implementation_ref,
    insert_operation,
    insert_operation_many,
    operation_id_for,
    register_root_artifact,
    source_bundle,
)

_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ACQ = AcquisitionRef(
    recording_id=recording_id_for(_ASSET_ID),
    source_asset_id=_ASSET_ID,
    channel=ChannelKey(device_channel=1),
)
_OTHER_ACQ = AcquisitionRef(
    recording_id=recording_id_for(_ASSET_ID),
    source_asset_id=_ASSET_ID,
    channel=ChannelKey(device_channel=2),
)
_DESCRIPTOR = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")
_CONFIG = ChannelConfig(sound_speed_ms=1480.0, n_gates=2)
_DATA = observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 4.0]])
_IMPL = ImplementationRef(
    package="udv-echo-process",
    version=metadata.version("udv-echo-process"),
    callable="udv_echo_process.process.derive.derive",
    revision=None,
)


def _id(n: int) -> str:
    return "sha256:" + f"{n:064x}"


def _artifact(**overrides: object) -> ChannelArtifact:
    kwargs: dict[str, object] = {
        "acquisition": _ACQ,
        "descriptor": _DESCRIPTOR,
        "config": _CONFIG,
        "data": _DATA,
    }
    kwargs.update(overrides)
    return source_artifact(**kwargs)  # type: ignore[arg-type]


def _operation(**overrides: object) -> OperationRecord:
    """Build an ``OperationRecord`` whose id replays from its recipe fields.

    The id is computed with the canonical :func:`operation_id_for` equation from
    the (possibly overridden) recipe unless a caller supplies ``operation_id``
    explicitly — only counterfeit-id tests do. So every record built here passes
    the model's replay invariant.
    """
    kwargs: dict[str, Any] = {
        "kind": "test.op",
        "schema_version": 1,
        "params_json": '{"a":1}',
        "implementation": _IMPL,
        "parents": (_id(1),),
        "warnings": (),
    }
    kwargs.update(overrides)
    if "operation_id" not in overrides:
        try:
            kwargs["operation_id"] = operation_id_for(
                kwargs["kind"],
                kwargs["schema_version"],
                kwargs["params_json"],
                kwargs["implementation"],
                kwargs["parents"],
            )
        except ValueError:
            # A deliberately malformed recipe (e.g. non-JSON params) must reach
            # the field validators, which raise first; the id value is moot.
            kwargs["operation_id"] = _id(7)
    return OperationRecord(**kwargs)  # type: ignore[arg-type]


def _graph(**overrides: object) -> ArtifactGraph:
    kwargs: dict[str, object] = {
        "operations": (),
        "derivations": (),
        "root_artifacts": (),
    }
    kwargs.update(overrides)
    return ArtifactGraph(**kwargs)  # type: ignore[arg-type]


# ── array_digest ───────────────────────────────────────────────────────


def test_array_digest_is_deterministic_and_opaque():
    arr = np.array([[1.0, 2.0], [3.0, 4.0]], np.float64)
    digest = array_digest(arr)
    assert _ID_RE.fullmatch(digest)
    assert array_digest(arr) == digest
    assert array_digest(arr.copy()) == digest


def test_array_digest_separates_equal_bytes_with_a_different_shape():
    flat = np.array([1.0, 2.0, 3.0, 4.0], np.float64)
    shaped = flat.reshape(2, 2)
    assert flat.tobytes() == shaped.tobytes()
    assert array_digest(flat) != array_digest(shaped)


def test_array_digest_separates_dtype():
    arr = np.array([1.0, 2.0, 3.0, 4.0], np.float64)
    assert array_digest(arr) != array_digest(arr.astype(np.int64))


def test_array_digest_chunks_large_arrays_deterministically():
    big = np.arange(5000 * 3, dtype=np.float64).reshape(5000, 3)
    assert array_digest(big) == array_digest(big)
    changed = big.copy()
    changed[4999, 2] = -1.0
    assert array_digest(changed) != array_digest(big)


# ── source artifact identity ───────────────────────────────────────────


def test_source_artifact_id_is_deterministic():
    assert source_artifact_id(_ACQ, _DESCRIPTOR, _CONFIG, _DATA) == source_artifact_id(
        _ACQ, _DESCRIPTOR, _CONFIG, _DATA
    )


def test_source_artifact_recomputes_and_matches_its_id():
    artifact = _artifact()
    assert artifact.artifact_id == source_artifact_id(
        artifact.acquisition, artifact.descriptor, artifact.config, artifact.data
    )


def test_source_artifact_rejects_a_non_reproducible_id(monkeypatch):
    import udv_echo_process.models.signal as signal_module

    calls = {"count": 0}
    original = signal_module.source_artifact_id

    def drifting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs) if calls["count"] == 1 else _id(99)

    monkeypatch.setattr(signal_module, "source_artifact_id", drifting)
    with pytest.raises(RuntimeError, match="not reproducible"):
        source_artifact(_ACQ, _DESCRIPTOR, _CONFIG, _DATA)
    assert calls["count"] == 2


def test_source_artifact_id_is_sensitive_to_acquisition_identity():
    assert source_artifact_id(_ACQ, _DESCRIPTOR, _CONFIG, _DATA) != source_artifact_id(
        _OTHER_ACQ, _DESCRIPTOR, _CONFIG, _DATA
    )


def test_source_artifact_id_is_sensitive_to_descriptor():
    assert source_artifact_id(_ACQ, _DESCRIPTOR, _CONFIG, _DATA) != source_artifact_id(
        _ACQ, _VELOCITY, _CONFIG, _DATA
    )


def test_source_artifact_id_is_sensitive_to_config():
    changed = ChannelConfig(sound_speed_ms=1500.0, n_gates=2)
    assert source_artifact_id(_ACQ, _DESCRIPTOR, _CONFIG, _DATA) != source_artifact_id(
        _ACQ, _DESCRIPTOR, changed, _DATA
    )


@pytest.mark.parametrize(
    "data",
    [
        observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 99.0]]),
        observed_signal([0.0, 1.5], [5.0, 10.0], [[1.0, 2.0], [3.0, 4.0]]),
        observed_signal([0.0, 1.0], [5.0, 12.0], [[1.0, 2.0], [3.0, 4.0]]),
        observed_signal(
            [0.0, 1.0],
            [5.0, 10.0],
            [[1.0, 2.0], [3.0, 4.0]],
            quality=[[0, int(QualityFlag.OUTLIER)], [0, 0]],
        ),
    ],
    ids=["values", "time", "gates", "quality"],
)
def test_source_artifact_id_is_sensitive_to_every_array(data):
    assert source_artifact_id(_ACQ, _DESCRIPTOR, _CONFIG, _DATA) != source_artifact_id(
        _ACQ, _DESCRIPTOR, _CONFIG, data
    )


def test_source_artifact_id_is_sensitive_to_acquisition_arrays():
    base = observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 4.0]])
    assert base.acquisition is None
    with_acq = observed_signal(
        [0.0, 1.0],
        [5.0, 10.0],
        [[1.0, 2.0], [3.0, 4.0]],
        acquisition=AcquisitionIndex(
            sample_id=np.array([0, 1], np.int64),
            acquisition_time_s=np.array([0.0, 1.0], np.float64),
        ),
    )
    assert source_artifact_id(_ACQ, _DESCRIPTOR, _CONFIG, base) != source_artifact_id(
        _ACQ, _DESCRIPTOR, _CONFIG, with_acq
    )


def test_source_artifact_id_reproduces_in_a_separate_process():
    expected = source_artifact_id(_ACQ, _DESCRIPTOR, _CONFIG, _DATA)
    src = Path(__file__).resolve().parents[1] / "src"
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(src)!r})
        from udv_echo_process.models import (
            AcquisitionRef,
            ChannelConfig,
            ChannelKey,
            SignalDescriptor,
            SignalQuantity,
            observed_signal,
            source_artifact_id,
        )
        from udv_echo_process.models.identity import recording_id_for

        asset_id = "sha256:" + "1" * 64
        acquisition = AcquisitionRef(
            recording_id=recording_id_for(asset_id),
            source_asset_id=asset_id,
            channel=ChannelKey(device_channel=1),
        )
        descriptor = SignalDescriptor(
            quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module"
        )
        config = ChannelConfig(sound_speed_ms=1480.0, n_gates=2)
        data = observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 4.0]])
        print(source_artifact_id(acquisition, descriptor, config, data))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == expected


# ── scientific equality ────────────────────────────────────────────────


def test_signals_equal_compares_content_not_identity():
    other = observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 4.0]])
    assert _DATA is not other
    assert signals_equal(_DATA, other)
    changed = observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 5.0]])
    assert not signals_equal(_DATA, changed)


def test_signals_equal_treats_matching_missingness_as_equal():
    left = observed_signal(
        [0.0, 1.0], [5.0], [[1.0], [np.nan]], quality=[[0], [int(QualityFlag.OUTLIER)]]
    )
    right = observed_signal(
        [0.0, 1.0], [5.0], [[1.0], [np.nan]], quality=[[0], [int(QualityFlag.OUTLIER)]]
    )
    assert signals_equal(left, right)


def test_artifacts_equal_requires_the_same_id_and_content():
    artifact = _artifact()
    same = _artifact()
    assert artifacts_equal(artifact, same)
    assert not artifacts_equal(artifact, _artifact(descriptor=_VELOCITY))


# ── ChannelArtifact model ──────────────────────────────────────────────


def test_channel_artifact_has_exactly_five_fields():
    assert set(ChannelArtifact.model_fields) == {
        "artifact_id",
        "acquisition",
        "descriptor",
        "config",
        "data",
    }


def test_channel_artifact_requires_every_field():
    base = {
        "artifact_id": _id(1),
        "acquisition": _ACQ,
        "descriptor": _DESCRIPTOR,
        "config": _CONFIG,
    }
    with pytest.raises(ValidationError):
        ChannelArtifact(**base)
    with pytest.raises(ValidationError):
        ChannelArtifact(**base, data=_DATA, derivation="no-sixth-field")


@pytest.mark.parametrize(
    "bad_id",
    ["", "not-a-hash", "sha256:" + "A" * 64, "sha256:" + "a" * 63, "a" * 64],
    ids=["empty", "no-prefix", "upper-case", "short", "no-sha-prefix"],
)
def test_channel_artifact_rejects_bad_artifact_id(bad_id):
    with pytest.raises(ValidationError):
        ChannelArtifact(
            artifact_id=bad_id,
            acquisition=_ACQ,
            descriptor=_DESCRIPTOR,
            config=_CONFIG,
            data=_DATA,
        )


# ── ImplementationRef ──────────────────────────────────────────────────


def test_implementation_ref_accepts_all_fields():
    ref = ImplementationRef(
        package="udv-echo-process",
        version="0.1.0",
        callable="udv_echo_process.process.derive.derive",
        revision="abc1234",
    )
    assert ref.revision == "abc1234"


def test_implementation_ref_revision_is_optional_and_not_required():
    ref = ImplementationRef(package="p", version="1", callable="c")
    assert ref.revision is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package", ""),
        ("version", "  "),
        ("callable", ""),
        ("revision", "   "),
    ],
)
def test_implementation_ref_rejects_blank_strings(field, value):
    kwargs: dict[str, object] = {
        "package": "udv-echo-process",
        "version": "0.1.0",
        "callable": "c",
    }
    kwargs[field] = value
    with pytest.raises(ValidationError):
        ImplementationRef(**kwargs)  # type: ignore[arg-type]


def test_implementation_ref_factory_reads_installed_metadata():
    ref = implementation_ref("udv_echo_process.process.derive.derive")
    assert ref.package == "udv-echo-process"
    assert ref.version == metadata.version("udv-echo-process")
    assert ref.callable == "udv_echo_process.process.derive.derive"
    assert ref.revision is None or isinstance(ref.revision, str)
    assert ref.revision != ""


# ── OperationRecord ────────────────────────────────────────────────────


def test_operation_record_accepts_valid_input():
    record = _operation()
    assert record.parents == (_id(1),)
    assert record.warnings == ()
    assert record.schema_version == 1


def test_operation_record_rejects_empty_parents():
    with pytest.raises(ValidationError) as ei:
        _operation(parents=())
    assert "at least one parent" in str(ei.value)


def test_operation_record_rejects_a_bad_parent_id():
    with pytest.raises(ValidationError):
        _operation(parents=("not-an-id",))


def test_operation_record_rejects_schema_version_below_one():
    with pytest.raises(ValidationError):
        _operation(schema_version=0)


@pytest.mark.parametrize(
    "params_json",
    ["[]", "123", '"x"', "null", "not json", '{"b":1,"a":2}', '{ "a": 1 }'],
    ids=["array", "number", "string", "null", "garbage", "unsorted", "spaced"],
)
def test_operation_record_requires_a_canonical_json_object(params_json):
    with pytest.raises(ValidationError):
        _operation(params_json=params_json)


def test_operation_record_accepts_canonical_json():
    assert (
        _operation(params_json='{"a":1,"b":[1,2]}').params_json == '{"a":1,"b":[1,2]}'
    )


def test_operation_record_rejects_blank_warning():
    with pytest.raises(ValidationError):
        _operation(warnings=("",))


def test_operation_record_rejects_bad_operation_id():
    with pytest.raises(ValidationError):
        _operation(operation_id="nope")


def test_operation_record_accepts_a_replayed_operation_id():
    """A correct record's id equals the canonical equation over its recipe."""
    record = _operation()
    assert record.operation_id == operation_id_for(
        record.kind,
        record.schema_version,
        record.params_json,
        record.implementation,
        record.parents,
    )


def test_operation_record_rejects_a_counterfeit_operation_id():
    """Public construction rejects an id that does not replay (acceptance #2)."""
    recipe: dict[str, Any] = {
        "kind": "test.op",
        "schema_version": 1,
        "params_json": '{"a":1}',
        "implementation": _IMPL,
        "parents": (_id(1),),
    }
    real = operation_id_for(**recipe)
    counterfeit = _id(7) if real != _id(7) else _id(8)
    with pytest.raises(ValidationError, match="does not replay"):
        OperationRecord(operation_id=counterfeit, **recipe)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "test.other"),
        ("schema_version", 2),
        ("params_json", '{"a":2}'),
        (
            "implementation",
            ImplementationRef(package="p", version="1", callable="c"),
        ),
        ("parents", (_id(2),)),
    ],
)
def test_operation_record_rejects_an_id_from_a_different_recipe(field, value):
    """Changing any canonical recipe input invalidates the previously valid id."""
    record = _operation()
    kwargs: dict[str, Any] = {
        "kind": record.kind,
        "schema_version": record.schema_version,
        "params_json": record.params_json,
        "implementation": record.implementation,
        "parents": record.parents,
    }
    kwargs[field] = value
    with pytest.raises(ValidationError, match="does not replay"):
        OperationRecord(operation_id=record.operation_id, **kwargs)


def test_graph_validation_rejects_a_counterfeit_operation_id_on_reload():
    """A graph parsed from stored JSON replays each operation id (plan §9.3)."""
    record = _operation()
    payload: dict[str, Any] = {
        "operations": [{**record.model_dump(mode="json"), "operation_id": _id(7)}],
        "derivations": [],
        "root_artifacts": [],
    }
    with pytest.raises(ValidationError, match="does not replay"):
        ArtifactGraph.model_validate(payload)


# ── ArtifactDerivationLink ─────────────────────────────────────────────


def test_artifact_derivation_link_valid():
    link = ArtifactDerivationLink(artifact_id=_id(2), operation_id=_id(7))
    assert link.artifact_id == _id(2)


@pytest.mark.parametrize("field", ["artifact_id", "operation_id"])
def test_artifact_derivation_link_rejects_bad_ids(field):
    kwargs = {"artifact_id": _id(2), "operation_id": _id(7)}
    kwargs[field] = "sha256:" + "z" * 64
    with pytest.raises(ValidationError):
        ArtifactDerivationLink(**kwargs)


# ── ArtifactGraph invariants ───────────────────────────────────────────


def test_empty_graph_is_valid():
    graph = ArtifactGraph()
    assert graph.operations == graph.derivations == graph.root_artifacts == ()


def test_graph_accepts_a_root_and_a_resolvable_chain():
    root = _id(1)
    operation = _operation(parents=(root,))
    graph = ArtifactGraph(
        operations=(operation,),
        derivations=(
            ArtifactDerivationLink(
                artifact_id=_id(2), operation_id=operation.operation_id
            ),
        ),
        root_artifacts=(root,),
    )
    assert graph.root_artifacts == (root,)


def test_graph_accepts_a_parent_resolved_through_derivations():
    root = _id(1)
    first = _operation(parents=(root,))
    second = _operation(parents=(_id(2),))
    graph = ArtifactGraph(
        operations=(first, second),
        derivations=(
            ArtifactDerivationLink(artifact_id=_id(2), operation_id=first.operation_id),
            ArtifactDerivationLink(artifact_id=_id(3), operation_id=first.operation_id),
            ArtifactDerivationLink(
                artifact_id=_id(4), operation_id=second.operation_id
            ),
        ),
        root_artifacts=(root,),
    )
    assert len(graph.derivations) == 3
    assert graph.operations[1].parents == (_id(2),)


def test_graph_rejects_duplicate_operation_ids():
    with pytest.raises(ValidationError) as ei:
        _graph(operations=(_operation(), _operation()))
    assert "unique operation_id" in str(ei.value)


def test_graph_rejects_duplicate_derived_artifact_ids():
    first = _operation()
    second = _operation(params_json='{"a":2}')
    links = (
        ArtifactDerivationLink(artifact_id=_id(2), operation_id=first.operation_id),
        ArtifactDerivationLink(artifact_id=_id(2), operation_id=second.operation_id),
    )
    with pytest.raises(ValidationError) as ei:
        _graph(operations=(first, second), derivations=links)
    assert "unique artifact_id" in str(ei.value)


def test_graph_rejects_duplicate_root_artifacts():
    with pytest.raises(ValidationError) as ei:
        _graph(root_artifacts=(_id(1), _id(1)))
    assert "unique" in str(ei.value)


def test_graph_rejects_a_link_to_an_unknown_operation():
    with pytest.raises(ValidationError) as ei:
        _graph(
            derivations=(
                ArtifactDerivationLink(artifact_id=_id(2), operation_id=_id(7)),
            )
        )
    assert "unknown operation" in str(ei.value)


def test_graph_rejects_a_dangling_parent():
    with pytest.raises(ValidationError) as ei:
        _graph(operations=(_operation(parents=(_id(9),)),))
    assert "unresolved parent" in str(ei.value)


def test_graph_rejects_root_and_derived_overlap():
    operation = _operation(parents=(_id(1),))
    with pytest.raises(ValidationError) as ei:
        _graph(
            operations=(operation,),
            derivations=(
                ArtifactDerivationLink(
                    artifact_id=_id(1), operation_id=operation.operation_id
                ),
            ),
            root_artifacts=(_id(1),),
        )
    assert "both a root and a derived artifact" in str(ei.value)


# ── pure graph insertion ───────────────────────────────────────────────


def test_register_root_artifact_is_pure():
    graph = _graph()
    updated = register_root_artifact(graph, _id(1))
    assert graph.root_artifacts == ()
    assert updated.root_artifacts == (_id(1),)
    again = register_root_artifact(updated, _id(2))
    assert updated.root_artifacts == (_id(1),)
    assert again.root_artifacts == (_id(1), _id(2))


def test_register_root_artifact_rejects_a_duplicate():
    graph = register_root_artifact(_graph(), _id(1))
    with pytest.raises(ValidationError):
        register_root_artifact(graph, _id(1))
    assert graph.root_artifacts == (_id(1),)


def test_insert_operation_is_pure_and_adds_one_edge():
    root = _id(1)
    graph = register_root_artifact(_graph(), root)
    operation = _operation(parents=(root,))
    updated = insert_operation(graph, operation, artifact_id=_id(2))
    assert graph.operations == () and graph.derivations == ()
    assert updated.operations == (operation,)
    assert updated.derivations == (
        ArtifactDerivationLink(artifact_id=_id(2), operation_id=operation.operation_id),
    )
    assert updated.root_artifacts == (root,)


def test_failing_insert_leaves_the_input_graph_unchanged():
    root = _id(1)
    graph = register_root_artifact(_graph(), root)
    record = _operation(parents=(root,))
    first = insert_operation(graph, record, artifact_id=_id(2))
    with pytest.raises(ValidationError):
        insert_operation(first, _operation(parents=(root,)), artifact_id=_id(3))
    assert first.operations == (_operation(parents=(root,)),)
    assert first.derivations == (
        ArtifactDerivationLink(artifact_id=_id(2), operation_id=record.operation_id),
    )


def test_insert_operation_rejects_an_unresolved_parent():
    graph = _graph()
    with pytest.raises(ValidationError) as ei:
        insert_operation(graph, _operation(parents=(_id(9),)), artifact_id=_id(2))
    assert "unresolved parent" in str(ei.value)
    assert graph.operations == ()


# ── bundles ────────────────────────────────────────────────────────────


def test_source_bundle_registers_the_artifact_as_a_root():
    bundle = source_bundle(_artifact())
    assert bundle.graph.root_artifacts == (bundle.artifact.artifact_id,)
    assert bundle.graph.operations == ()
    assert bundle.graph.derivations == ()


def test_source_bundle_rejects_a_counterfeit_artifact_id():
    """The source id is replayed from the artifact's content (acceptance #1)."""
    genuine = _artifact()
    counterfeit = ChannelArtifact(
        artifact_id=_id(99),
        acquisition=genuine.acquisition,
        descriptor=genuine.descriptor,
        config=genuine.config,
        data=genuine.data,
    )
    assert counterfeit.artifact_id != source_artifact_id(
        counterfeit.acquisition,
        counterfeit.descriptor,
        counterfeit.config,
        counterfeit.data,
    )
    with pytest.raises(ValueError, match="not a reproducible SOURCE artifact id"):
        source_bundle(counterfeit)


def test_source_bundle_rejects_an_id_from_different_content():
    """The replay uses the artifact's OWN fields, not just the id's shape."""
    genuine = _artifact()
    swapped = ChannelArtifact(
        artifact_id=genuine.artifact_id,
        acquisition=genuine.acquisition,
        descriptor=_VELOCITY,
        config=genuine.config,
        data=genuine.data,
    )
    with pytest.raises(ValueError, match="not a reproducible SOURCE artifact id"):
        source_bundle(swapped)


def test_source_bundle_rejects_a_derived_artifact_id():
    """A derived id is validly formatted but is not a SOURCE root id."""
    genuine = _artifact()
    derived_id = derived_artifact_id(
        _id(7),
        genuine.acquisition,
        genuine.descriptor,
        genuine.config,
        genuine.data,
    )
    derived = ChannelArtifact(
        artifact_id=derived_id,
        acquisition=genuine.acquisition,
        descriptor=genuine.descriptor,
        config=genuine.config,
        data=genuine.data,
    )
    with pytest.raises(ValueError, match="not a reproducible SOURCE artifact id"):
        source_bundle(derived)


def test_channel_bundle_requires_a_resolvable_artifact():
    with pytest.raises(ValidationError) as ei:
        ChannelBundle(artifact=_artifact(), graph=ArtifactGraph())
    assert "does not resolve" in str(ei.value)


def test_channel_bundle_accepts_a_root_artifact():
    artifact = _artifact()
    bundle = source_bundle(artifact)
    assert bundle.artifact.artifact_id == artifact.artifact_id


# ── derived artifact id + operation id ─────────────────────────────────


def test_derived_artifact_id_changes_with_the_operation_id():
    assert derived_artifact_id(_id(7), _ACQ, _DESCRIPTOR, _CONFIG, _DATA) != (
        derived_artifact_id(_id(8), _ACQ, _DESCRIPTOR, _CONFIG, _DATA)
    )


def test_derived_artifact_id_changes_with_array_content():
    changed = observed_signal([0.0, 1.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 5.0]])
    assert derived_artifact_id(_id(7), _ACQ, _DESCRIPTOR, _CONFIG, _DATA) != (
        derived_artifact_id(_id(7), _ACQ, _DESCRIPTOR, _CONFIG, changed)
    )


def test_derived_artifact_id_changes_with_descriptor_and_config():
    assert derived_artifact_id(_id(7), _ACQ, _DESCRIPTOR, _CONFIG, _DATA) != (
        derived_artifact_id(_id(7), _ACQ, _VELOCITY, _CONFIG, _DATA)
    )
    other_config = ChannelConfig(n_gates=2, sound_speed_ms=1500.0)
    assert derived_artifact_id(_id(7), _ACQ, _DESCRIPTOR, _CONFIG, _DATA) != (
        derived_artifact_id(_id(7), _ACQ, _DESCRIPTOR, other_config, _DATA)
    )


def test_operation_id_for_is_deterministic_and_ordered():
    base = operation_id_for("a", 1, '{"x":1}', _IMPL, (_id(1),))
    assert base == operation_id_for("a", 1, '{"x":1}', _IMPL, (_id(1),))
    assert operation_id_for("b", 1, '{"x":1}', _IMPL, (_id(1),)) != base
    assert operation_id_for("a", 2, '{"x":1}', _IMPL, (_id(1),)) != base
    assert operation_id_for("a", 1, '{"x":2}', _IMPL, (_id(1),)) != base
    assert operation_id_for("a", 1, '{"x":1}', _IMPL, (_id(2),)) != base
    ordered = operation_id_for("a", 1, '{"x":1}', _IMPL, (_id(1), _id(2)))
    swapped = operation_id_for("a", 1, '{"x":1}', _IMPL, (_id(2), _id(1)))
    assert ordered != swapped


# ══ Phase 7 — normalized DAG invariants, bounded metadata, the long chain ══


class _ChainSpec(ValueModel):
    """Identity-scale operation params for the phase-7 chain tests."""

    scale: float = 1.0


register_operation("prov.chain", _ChainSpec)

_CHAIN_IMPL = implementation_ref("udv_echo_process.process.derive.derive")


def _chain_step(bundle: ChannelBundle) -> ChannelBundle:
    """One recorded identity operation over ``bundle`` (a fresh payload copy)."""
    source = bundle.artifact.data
    data = observed_signal(source.time_s, source.gate_depths_mm, source.values.copy())
    return derive(
        bundle,
        kind="prov.chain",
        spec=_ChainSpec(),
        implementation=_CHAIN_IMPL,
        data=data,
    )


def _chain(bundle: ChannelBundle, steps: int) -> ChannelBundle:
    for _ in range(steps):
        bundle = _chain_step(bundle)
    return bundle


def _tokens(text: str) -> int:
    """Count opaque ``sha256:`` ids in ``text``."""
    return len(_ID_RE.findall(text))


def _artifact_metadata(artifact: ChannelArtifact) -> dict[str, object]:
    """An artifact's JSON metadata: identity + descriptor + config, no arrays."""
    return {
        "artifact_id": artifact.artifact_id,
        "acquisition": artifact.acquisition.model_dump(mode="json"),
        "descriptor": artifact.descriptor.model_dump(mode="json"),
        "config": artifact.config.model_dump(mode="json"),
    }


def _artifact_metadata_text(artifact: ChannelArtifact) -> str:
    return json.dumps(_artifact_metadata(artifact), sort_keys=True)


# ── cycles, ordering and reachability ──────────────────────────────────


def test_graph_rejects_a_cycle():
    """A derived artifact must never be an ancestor of its own operation."""
    first = _operation(parents=(_id(2),))
    second = _operation(parents=(_id(1),))
    with pytest.raises(ValidationError) as ei:
        _graph(
            operations=(first, second),
            derivations=(
                ArtifactDerivationLink(
                    artifact_id=_id(1), operation_id=first.operation_id
                ),
                ArtifactDerivationLink(
                    artifact_id=_id(2), operation_id=second.operation_id
                ),
            ),
        )
    assert "cycle" in str(ei.value)


def test_graph_rejects_operations_that_are_not_topologically_ordered():
    """A parent operation must precede its child even without a cycle."""
    parent = _operation(parents=(_id(1),))
    child = _operation(parents=(_id(2),))
    with pytest.raises(ValidationError, match="topologically ordered"):
        _graph(
            operations=(child, parent),
            derivations=(
                ArtifactDerivationLink(
                    artifact_id=_id(2), operation_id=parent.operation_id
                ),
                ArtifactDerivationLink(
                    artifact_id=_id(3), operation_id=child.operation_id
                ),
            ),
            root_artifacts=(_id(1),),
        )


def _two_step_graph() -> ArtifactGraph:
    """``root A -> operation 7 -> artifact 2 -> operation 8 -> artifact 3``."""
    root = _id(1)
    graph = insert_operation(
        register_root_artifact(ArtifactGraph(), root),
        _operation(parents=(root,)),
        artifact_id=_id(2),
    )
    return insert_operation(
        graph,
        _operation(parents=(_id(2),)),
        artifact_id=_id(3),
    )


def test_graph_topology_is_deterministic_and_parents_precede_children():
    graph = _two_step_graph()
    assert [op.parents for op in graph.operations] == [(_id(1),), (_id(2),)]
    producers = {link.artifact_id: link.operation_id for link in graph.derivations}
    index = {op.operation_id: i for i, op in enumerate(graph.operations)}
    for operation in graph.operations:
        for parent in operation.parents:
            producer = producers.get(parent)
            if producer is not None:
                assert index[producer] < index[operation.operation_id]


def test_every_operation_is_reachable_from_a_root_artifact():
    graph = _two_step_graph()
    producers = {link.artifact_id: link.operation_id for link in graph.derivations}
    by_id = {op.operation_id: op for op in graph.operations}
    reachable = set(graph.root_artifacts)
    changed = True
    while changed:
        changed = False
        for artifact_id, operation_id in producers.items():
            if artifact_id in reachable:
                continue
            if all(parent in reachable for parent in by_id[operation_id].parents):
                reachable.add(artifact_id)
                changed = True
    assert reachable >= set(producers)


def test_graph_rejects_duplicate_links():
    operation = _operation()
    link = ArtifactDerivationLink(
        artifact_id=_id(2), operation_id=operation.operation_id
    )
    with pytest.raises(ValidationError, match="unique artifact_id"):
        _graph(operations=(operation,), derivations=(link, link))


def test_insert_operation_many_adds_one_node_and_every_link():
    root = _id(1)
    graph = register_root_artifact(ArtifactGraph(), root)
    operation = _operation(parents=(root,))
    updated = insert_operation_many(graph, operation, artifact_ids=(_id(2), _id(3)))
    assert graph.operations == () and graph.derivations == ()
    assert updated.operations == (operation,)
    assert updated.derivations == (
        ArtifactDerivationLink(artifact_id=_id(2), operation_id=operation.operation_id),
        ArtifactDerivationLink(artifact_id=_id(3), operation_id=operation.operation_id),
    )
    with pytest.raises(ValueError, match="at least one"):
        insert_operation_many(graph, operation, artifact_ids=())
    with pytest.raises(ValidationError):
        insert_operation_many(
            updated,
            _operation(parents=(root,)),
            artifact_ids=(_id(2),),
        )


# ── JSON-only params, bounded artifact metadata, the long chain ─────────


def _reject_json_constant(name: str) -> None:
    raise AssertionError(f"non-finite JSON constant {name!r}")


def _walk_json(node: object) -> None:
    """Assert ``node`` is a pure JSON value (no ndarray/Path/callable/NaN)."""
    if node is None or isinstance(node, (bool, int, str)):
        return
    if isinstance(node, float):
        assert math.isfinite(node), node
        return
    if isinstance(node, dict):
        for key, value in node.items():
            assert isinstance(key, str), key
            _walk_json(value)
        return
    if isinstance(node, list):
        for item in node:
            _walk_json(item)
        return
    raise AssertionError(f"non-JSON value {node!r}")


def test_operation_params_json_is_canonical_json_only():
    bundle = _chain(source_bundle(_artifact()), 3)
    assert len(bundle.graph.operations) == 3
    for operation in bundle.graph.operations:
        parsed = json.loads(operation.params_json, parse_constant=_reject_json_constant)
        assert isinstance(parsed, dict)
        _walk_json(parsed)
        canonical = json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        assert canonical == operation.params_json
        _walk_json(operation.model_dump(mode="json"))


def test_artifact_metadata_is_bounded_and_carries_no_history():
    bundle = source_bundle(_artifact())
    sizes: list[int] = []
    for _ in range(120):
        bundle = _chain_step(bundle)
        sizes.append(len(_artifact_metadata_text(bundle.artifact)))
    assert len(sizes) == 120
    # the artifact's own metadata never grows: nothing is copied into it
    assert len(set(sizes)) == 1
    assert _tokens(_artifact_metadata_text(bundle.artifact)) == 3


def test_long_chain_is_o1_per_artifact_and_one_node_per_operation():
    bundle = _chain(source_bundle(_artifact()), 120)
    links = bundle.graph.derivations
    assert len(bundle.graph.operations) == 120
    assert len(links) == 120
    assert bundle.graph.root_artifacts == (
        source_bundle(_artifact()).artifact.artifact_id,
    )
    assert len({op.operation_id for op in bundle.graph.operations}) == 120
    assert len({link.artifact_id for link in links}) == 120
    # exactly one node per operation, each consuming exactly its predecessor
    previous = bundle.graph.root_artifacts[0]
    for operation, link in zip(bundle.graph.operations, links, strict=True):
        assert operation.parents == (previous,)
        previous = link.artifact_id
    # the terminal artifact is a plain five-field record: its provenance is its
    # own id plus the one operation id the graph links to it, never a history
    assert set(ChannelArtifact.model_fields) == {
        "artifact_id",
        "acquisition",
        "descriptor",
        "config",
        "data",
    }
    final = bundle.artifact
    assert _tokens(_artifact_metadata_text(final)) == 3
    assert [
        link.operation_id for link in links if link.artifact_id == final.artifact_id
    ] == [bundle.graph.operations[-1].operation_id]
