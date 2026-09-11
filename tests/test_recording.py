"""Phase 6 tests: ``Recording``, terminal statistics and the bridge helpers.

Plan §6.7 (``Recording``, ``ProfileStatistics``), §7.1 (the ``select_channel`` /
``replace_channel`` bridge helpers), §8.1/§8.2 (``ArtifactBundle`` and the DAG
invariants it reuses), §11 (error-message contract), §13 and §14.

The phase's STOP/GO is that acquisition mode is never inferred: a one-stream
recording may be ``SEQUENTIAL`` and a many-stream recording may be
``SIMULTANEOUS``. ``test_mode_selection_never_consults_channel_count`` proves it
by an AST/source scan over the reader and this recording module; the runtime
tests prove it at the model boundary.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.models import (
    AcquisitionIndex,
    AcquisitionMode,
    AcquisitionRef,
    ChannelArtifact,
    ChannelConfig,
    ChannelKey,
    ProfileStatistics,
    Recording,
    SignalDescriptor,
    SignalQuantity,
    SourceAsset,
    SourceFormat,
    SourceSpec,
    observed_signal,
    source_artifact,
)
from udv_echo_process.provenance import (
    ArtifactBundle,
    ArtifactDerivationLink,
    ArtifactGraph,
    ChannelBundle,
    ImplementationRef,
    OperationRecord,
    register_root_artifact,
    replace_channel,
    select_channel,
)

_SRC = Path(__file__).resolve().parents[1] / "src" / "udv_echo_process"
_READER = _SRC / "io" / "dop" / "bdd.py"
_RECORDING_MODULE = _SRC / "models" / "recording.py"

_RECORDING_HEX = "a" * 64
_RECORDING_ID = "sha256:" + _RECORDING_HEX
_OTHER_RECORDING_ID = "sha256:" + "c" * 64
_ASSET_HEX = "b" * 64
_ASSET_ID = "sha256:" + _ASSET_HEX
_OTHER_ASSET_ID = "sha256:" + "d" * 64

_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")

SOURCE_ASSET = SourceAsset(
    asset_id=_ASSET_ID,
    content_sha256=_ASSET_HEX,
    byte_size=2048,
    file_name="fixture.BDD",
    source=SourceSpec(format=SourceFormat.BDD),
)


def _id(n: int) -> str:
    return "sha256:" + f"{n:064x}"


def _index(
    n_rows: int = 3,
    *,
    round_id: object = None,
    visit_id: object = None,
    profile_in_visit: object = None,
) -> AcquisitionIndex:
    return AcquisitionIndex(
        sample_id=np.arange(n_rows, dtype=np.int64),
        acquisition_time_s=np.arange(n_rows, dtype=np.float64),
        round_id=None if round_id is None else np.asarray(round_id, np.int64),
        visit_id=None if visit_id is None else np.asarray(visit_id, np.int64),
        profile_in_visit=(
            None if profile_in_visit is None else np.asarray(profile_in_visit, np.int64)
        ),
    )


def _artifact(
    channel: int,
    *,
    recording_id: str = _RECORDING_ID,
    asset_id: str = _ASSET_ID,
    descriptor: SignalDescriptor = _ECHO,
    acquisition: AcquisitionIndex | None = None,
    n_rows: int = 3,
) -> ChannelArtifact:
    """Build a real SOURCE artifact (id recomputed) for one channel."""
    times = np.arange(n_rows, dtype=np.float64)
    gates = np.array([0.0, 1.0], dtype=np.float64)
    values = times[:, None] + gates[None, :]
    data = observed_signal(
        times,
        gates,
        values,
        acquisition=_index(n_rows) if acquisition is None else acquisition,
    )
    ref = AcquisitionRef(
        recording_id=recording_id,
        source_asset_id=asset_id,
        channel=ChannelKey(device_channel=channel),
    )
    return source_artifact(ref, descriptor, ChannelConfig(), data)


def _artifact_with_id(artifact_id: str, channel: int) -> ChannelArtifact:
    """A hand-id'd artifact, used to force duplicate artifact ids."""
    ref = AcquisitionRef(
        recording_id=_RECORDING_ID,
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    data = observed_signal(
        np.array([0.0, 1.0]),
        np.array([0.0, 1.0]),
        np.array([[0.0, 1.0], [1.0, 2.0]]),
    )
    return ChannelArtifact(
        artifact_id=artifact_id,
        acquisition=ref,
        descriptor=_ECHO,
        config=ChannelConfig(),
        data=data,
    )


def _recording(
    streams: tuple[ChannelArtifact, ...],
    *,
    mode: AcquisitionMode = AcquisitionMode.SIMULTANEOUS,
    order: tuple[ChannelKey, ...] | None = None,
    recording_id: str = _RECORDING_ID,
    asset: SourceAsset = SOURCE_ASSET,
) -> Recording:
    return Recording(
        recording_id=recording_id,
        source_asset=asset,
        acquisition_mode=mode,
        streams=streams,
        acquisition_order=order,
    )


def _bundle(streams: tuple[ChannelArtifact, ...], **kwargs: object) -> ArtifactBundle:
    recording = _recording(streams, **kwargs)  # type: ignore[arg-type]
    graph = ArtifactGraph()
    for stream in recording.streams:
        graph = register_root_artifact(graph, stream.artifact_id)
    return ArtifactBundle(recording=recording, graph=graph)


# ── AcquisitionMode ────────────────────────────────────────────────────


def test_acquisition_mode_values_are_exact():
    assert AcquisitionMode.SIMULTANEOUS.value == "simultaneous"
    assert AcquisitionMode.SEQUENTIAL.value == "sequential"
    assert AcquisitionMode.ROLLING.value == "rolling"
    assert AcquisitionMode.UNKNOWN.value == "unknown"
    assert {member.value for member in AcquisitionMode} == {
        "simultaneous",
        "sequential",
        "rolling",
        "unknown",
    }


def test_acquisition_mode_is_a_str_enum():
    assert isinstance(AcquisitionMode.SEQUENTIAL, str)
    assert AcquisitionMode("rolling") is AcquisitionMode.ROLLING


# ── Recording fields and invariants ────────────────────────────────────


def test_recording_has_exactly_five_fields():
    assert set(Recording.model_fields) == {
        "recording_id",
        "source_asset",
        "acquisition_mode",
        "streams",
        "acquisition_order",
    }


def test_recording_accepts_a_single_stream():
    recording = _recording((_artifact(4),))
    assert len(recording.streams) == 1
    assert recording.acquisition_order is None
    assert recording.streams[0].acquisition.channel == ChannelKey(device_channel=4)


def test_recording_accepts_many_streams_with_an_explicit_order():
    streams = tuple(_artifact(ch) for ch in (6, 7, 8, 9))
    order = tuple(ChannelKey(device_channel=ch) for ch in (6, 7, 8, 9))
    recording = _recording(streams, mode=AcquisitionMode.SEQUENTIAL, order=order)
    assert recording.acquisition_order == order


def test_recording_rejects_empty_streams():
    with pytest.raises(ValidationError, match="streams"):
        _recording(())


def test_recording_rejects_duplicate_channel_keys():
    first = _artifact_with_id(_id(1), 4)
    second = _artifact_with_id(_id(2), 4)
    with pytest.raises(ValidationError, match="channel"):
        _recording((first, second))


def test_recording_rejects_duplicate_artifact_ids():
    first = _artifact_with_id(_id(5), 6)
    second = _artifact_with_id(_id(5), 7)
    with pytest.raises(ValidationError, match="artifact_id"):
        _recording((first, second))


def test_recording_rejects_a_mismatched_recording_id():
    stream = _artifact(4, recording_id=_OTHER_RECORDING_ID)
    with pytest.raises(ValidationError, match="recording_id"):
        _recording((stream,))
    with pytest.raises(ValidationError, match="recording_id"):
        _recording((stream,), recording_id="sha256:" + "e" * 64)


def test_recording_rejects_a_mismatched_source_asset_id():
    stream = _artifact(4, asset_id=_OTHER_ASSET_ID)
    with pytest.raises(ValidationError, match="source_asset_id"):
        _recording((stream,))


@pytest.mark.parametrize(
    "recordings_id",
    ["", "not-a-hash", "sha256:" + "A" * 64, "a" * 64],
    ids=["empty", "not-a-hash", "upper-case", "no-prefix"],
)
def test_recording_rejects_a_bad_recording_id(recordings_id):
    with pytest.raises(ValidationError, match="recording_id"):
        _recording((_artifact(4),), recording_id=recordings_id)


# ── acquisition_order is an exact permutation ──────────────────────────


def test_acquisition_order_must_be_a_duplicate_free_exact_permutation():
    streams = tuple(_artifact(ch) for ch in (6, 7, 8))
    keys = tuple(ChannelKey(device_channel=ch) for ch in (6, 7, 8))
    assert _recording(streams, order=keys[::-1]).acquisition_order == keys[::-1]

    with pytest.raises(ValidationError, match="permutation|duplicate"):
        _recording(streams, order=(keys[0], keys[0], keys[1]))
    with pytest.raises(ValidationError, match="permutation"):
        _recording(streams, order=(keys[0], keys[1]))
    with pytest.raises(ValidationError, match="permutation"):
        _recording(
            streams, order=(keys[0], keys[1], keys[2], ChannelKey(device_channel=99))
        )
    with pytest.raises(ValidationError):
        _recording(streams, order=(keys[0], keys[1], ChannelKey(device_channel=99)))


# ── mode is never inferred ─────────────────────────────────────────────


def test_single_stream_recording_may_be_sequential():
    recording = _recording((_artifact(4),), mode=AcquisitionMode.SEQUENTIAL)
    assert recording.acquisition_mode is AcquisitionMode.SEQUENTIAL


def test_many_stream_recording_may_be_simultaneous():
    streams = tuple(_artifact(ch) for ch in (6, 7, 8, 9))
    recording = _recording(streams, mode=AcquisitionMode.SIMULTANEOUS)
    assert recording.acquisition_mode is AcquisitionMode.SIMULTANEOUS


def test_single_stream_recording_may_be_rolling():
    recording = _recording((_artifact(4),), mode=AcquisitionMode.ROLLING)
    assert recording.acquisition_mode is AcquisitionMode.ROLLING


def test_many_stream_recording_may_be_unknown():
    streams = tuple(_artifact(ch) for ch in (6, 7, 8, 9))
    recording = _recording(streams, mode=AcquisitionMode.UNKNOWN)
    assert recording.acquisition_mode is AcquisitionMode.UNKNOWN


def _len_calls_mentioning_counts(path: Path) -> list[str]:
    """Return any ``len(...)`` call whose argument names streams/channels."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id != "len":
                continue
            for arg in node.args:
                text = ast.unparse(arg).lower()
                if "stream" in text or "channel" in text:
                    offenders.append(text)
    return offenders


def test_mode_selection_never_consults_channel_count():
    """STOP/GO: the reader and this module must not size mode from streams."""
    for path in (_READER, _RECORDING_MODULE):
        assert _len_calls_mentioning_counts(path) == [], path
        assert "len(streams)" not in path.read_text(encoding="utf-8")


def test_mode_decoder_signature_cannot_see_streams():
    """The reader's mode decoder takes only the decoded multiplex flag."""
    tree = ast.parse(_READER.read_text(encoding="utf-8"))
    decoders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_decode_acquisition_mode"
    ]
    assert len(decoders) == 1
    decoder = decoders[0]
    assert len(decoder.args.args) == 1
    assert decoder.args.args[0].arg == "multiplexed"
    for node in ast.walk(decoder):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "len"
        if isinstance(node, ast.Name):
            assert "stream" not in node.id.lower()
            assert "channel" not in node.id.lower()
    assert "_decode_acquisition_mode(" in _READER.read_text(encoding="utf-8")


# ── decoded topology invariants ────────────────────────────────────────


def test_unique_round_visit_pairs_are_accepted():
    stream = _artifact(
        6,
        n_rows=4,
        acquisition=_index(
            4,
            round_id=[1, 1, 2, 2],
            visit_id=[0, 1, 0, 1],
            profile_in_visit=[0, 1, 0, 1],
        ),
    )
    recording = _recording((stream,), mode=AcquisitionMode.SEQUENTIAL)
    index = recording.streams[0].data.acquisition
    assert index is not None
    assert index.round_id.tolist() == [1, 1, 2, 2]
    assert index.visit_id.tolist() == [0, 1, 0, 1]
    assert index.profile_in_visit.tolist() == [0, 1, 0, 1]


def test_duplicate_round_visit_pairs_are_rejected():
    stream = _artifact(
        6,
        acquisition=_index(
            3,
            round_id=[1, 1, 1],
            visit_id=[0, 0, 0],
            profile_in_visit=[0, 1, 2],
        ),
    )
    with pytest.raises(ValidationError, match="round_id|visit_id"):
        _recording((stream,), mode=AcquisitionMode.SEQUENTIAL)


def test_missing_visits_stay_missing_and_are_not_renumbered():
    stream = _artifact(
        6,
        acquisition=_index(
            3,
            round_id=[1, -1, 2],
            visit_id=[0, -1, 1],
            profile_in_visit=[0, -1, 0],
        ),
    )
    recording = _recording((stream,), mode=AcquisitionMode.SEQUENTIAL)
    index = recording.streams[0].data.acquisition
    assert index is not None
    # the unmatched row keeps the sentinel -1, it is not renumbered to 1
    assert index.round_id.tolist() == [1, -1, 2]
    assert index.visit_id.tolist() == [0, -1, 1]
    assert index.profile_in_visit.tolist() == [0, -1, 0]


def test_absence_of_fabricated_indices_when_topology_is_unprovable():
    """A recording never invents round/visit ids the source did not carry."""
    stream = _artifact(4, acquisition=_index(3))
    recording = _recording((stream,), mode=AcquisitionMode.UNKNOWN)
    index = recording.streams[0].data.acquisition
    assert index is not None
    assert index.round_id is None
    assert index.visit_id is None
    assert index.profile_in_visit is None
    assert recording.acquisition_order is None


# ── ProfileStatistics ──────────────────────────────────────────────────


def _statistics(**overrides: object) -> ProfileStatistics:
    kwargs: dict[str, object] = {
        "artifact_id": _id(1),
        "source_artifact_id": _id(2),
        "descriptor": _ECHO,
        "gate_depths_mm": (5.0, 10.0, 15.0),
        "count": (4, 0, 7),
        "mean": (1.0, None, 3.0),
        "std": (0.5, None, 0.25),
        "minimum": (0.0, None, 2.0),
        "maximum": (2.0, None, 4.0),
    }
    kwargs.update(overrides)
    return ProfileStatistics(**kwargs)  # type: ignore[arg-type]


def test_profile_statistics_has_exactly_the_declared_fields():
    assert set(ProfileStatistics.model_fields) == {
        "artifact_id",
        "source_artifact_id",
        "descriptor",
        "gate_depths_mm",
        "count",
        "mean",
        "std",
        "minimum",
        "maximum",
    }


def test_profile_statistics_accepts_the_declared_shape():
    stats = _statistics()
    assert stats.count == (4, 0, 7)
    assert stats.mean[1] is None
    assert stats.descriptor == _ECHO


@pytest.mark.parametrize("field", ["count", "mean", "std", "minimum", "maximum"])
def test_profile_statistics_tuples_have_gate_length(field):
    with pytest.raises(ValidationError, match=field):
        _statistics(**{field: (1.0, 2.0)})


def test_profile_statistics_requires_at_least_one_gate():
    with pytest.raises(ValidationError, match="gate_depths_mm"):
        _statistics(
            gate_depths_mm=(),
            count=(),
            mean=(),
            std=(),
            minimum=(),
            maximum=(),
        )


def test_profile_statistics_count_must_be_nonnegative():
    with pytest.raises(ValidationError, match="count"):
        _statistics(count=(4, -1, 7))


@pytest.mark.parametrize("field", ["mean", "std", "minimum", "maximum"])
def test_profile_statistics_zero_count_requires_none(field):
    with pytest.raises(ValidationError, match=field):
        _statistics(**{field: (1.0, 9.0, 3.0)})


def test_profile_statistics_zero_count_requires_all_four_none():
    stats = _statistics(
        count=(0,),
        mean=(None,),
        std=(None,),
        minimum=(None,),
        maximum=(None,),
        gate_depths_mm=(5.0,),
    )
    assert stats.count == (0,)
    assert stats.mean == (None,)


def test_profile_statistics_rejects_non_finite_statistics():
    with pytest.raises(ValidationError, match="mean"):
        _statistics(mean=(1.0, None, float("nan")))


def test_profile_statistics_rejects_bad_ids():
    with pytest.raises(ValidationError, match="artifact_id"):
        _statistics(artifact_id="nope")
    with pytest.raises(ValidationError, match="source_artifact_id"):
        _statistics(source_artifact_id="sha256:" + "A" * 64)


def test_profile_statistics_contains_no_ndarray_anywhere():
    """The terminal result is JSON-oriented: no ndarray at any depth."""
    dumped = _statistics().model_dump(mode="python")

    def walk(node: object) -> None:
        assert not isinstance(node, np.ndarray), node
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(dumped)
    json_text = _statistics().model_dump_json()
    assert "ndarray" not in json_text
    assert json_text.startswith("{")


# ── ArtifactBundle ─────────────────────────────────────────────────────


def test_artifact_bundle_requires_every_stream_to_resolve_in_the_graph():
    streams = tuple(_artifact(ch) for ch in (6, 7))
    graph = register_root_artifact(ArtifactGraph(), streams[0].artifact_id)
    with pytest.raises(ValidationError, match="resolve"):
        ArtifactBundle(recording=_recording(streams), graph=graph)


def test_artifact_bundle_registers_all_streams_as_roots():
    streams = tuple(_artifact(ch) for ch in (6, 7, 8, 9))
    bundle = _bundle(streams, mode=AcquisitionMode.SEQUENTIAL)
    assert set(bundle.graph.root_artifacts) == {
        stream.artifact_id for stream in streams
    }
    assert bundle.graph.operations == ()
    assert bundle.graph.derivations == ()


def test_artifact_bundle_accepts_a_stream_resolved_by_a_derivation():
    """A carried artifact may resolve through a derivation, not only a root."""
    root = _artifact(6)
    derived = _artifact_with_id(_id(42), 7)
    operation = OperationRecord(
        operation_id=_id(7),
        kind="test.op",
        schema_version=1,
        params_json='{"a":1}',
        implementation=ImplementationRef(
            package="udv-echo-process", version="0.0.0", callable="test"
        ),
        parents=(root.artifact_id,),
    )
    graph = ArtifactGraph(
        operations=(operation,),
        derivations=(ArtifactDerivationLink(artifact_id=_id(42), operation_id=_id(7)),),
        root_artifacts=(root.artifact_id,),
    )
    bundle = ArtifactBundle(
        recording=_recording((root, derived), mode=AcquisitionMode.SEQUENTIAL),
        graph=graph,
    )
    assert bundle.graph.derivations[0].artifact_id == derived.artifact_id


# ── select_channel / replace_channel ───────────────────────────────────


def test_select_channel_returns_the_matching_stream_and_reuses_the_graph():
    streams = tuple(_artifact(ch) for ch in (6, 7, 8, 9))
    bundle = _bundle(streams, mode=AcquisitionMode.SEQUENTIAL)
    selected = select_channel(bundle, ChannelKey(device_channel=8))
    assert isinstance(selected, ChannelBundle)
    assert selected.artifact is bundle.recording.streams[2]
    assert selected.graph is bundle.graph  # no provenance copying
    assert (
        select_channel(bundle, ChannelKey(device_channel=6)).artifact
        is (bundle.recording.streams[0])
    )


def test_select_channel_rejects_an_absent_channel():
    bundle = _bundle((_artifact(4),))
    with pytest.raises(ValueError, match="channel"):
        select_channel(bundle, ChannelKey(device_channel=7))


def test_select_channel_leaves_its_input_untouched():
    streams = tuple(_artifact(ch) for ch in (6, 7))
    bundle = _bundle(streams, mode=AcquisitionMode.SEQUENTIAL)
    before = bundle.recording.streams
    select_channel(bundle, ChannelKey(device_channel=6))
    assert bundle.recording.streams == before
    assert bundle.graph.root_artifacts == tuple(
        stream.artifact_id for stream in streams
    )


def test_replace_channel_replaces_exactly_one_stream():
    streams = tuple(_artifact(ch) for ch in (6, 7, 8, 9))
    bundle = _bundle(streams, mode=AcquisitionMode.SEQUENTIAL)
    replacement = _artifact(8, descriptor=_VELOCITY)
    assert replacement.artifact_id != streams[2].artifact_id
    graph = register_root_artifact(bundle.graph, replacement.artifact_id)
    updated = replace_channel(bundle, ChannelBundle(artifact=replacement, graph=graph))
    assert len(updated.recording.streams) == 4
    assert updated.recording.streams[2].artifact_id == replacement.artifact_id
    assert [s.artifact_id for s in updated.recording.streams[:2]] == [
        s.artifact_id for s in streams[:2]
    ]
    assert updated.recording.streams[3].artifact_id == streams[3].artifact_id
    assert updated.graph is graph  # adopts the returned validated graph
    assert updated.recording.recording_id == _RECORDING_ID


def test_replace_channel_leaves_its_input_untouched():
    streams = tuple(_artifact(ch) for ch in (6, 7))
    bundle = _bundle(streams, mode=AcquisitionMode.SEQUENTIAL)
    before = bundle.recording.streams
    replacement = _artifact(6, descriptor=_VELOCITY)
    graph = register_root_artifact(bundle.graph, replacement.artifact_id)
    replace_channel(bundle, ChannelBundle(artifact=replacement, graph=graph))
    assert bundle.recording.streams == before
    assert bundle.recording.streams[0].artifact_id == streams[0].artifact_id


def test_replace_channel_requires_the_same_recording_and_channel_identity():
    streams = tuple(_artifact(ch) for ch in (6, 7))
    bundle = _bundle(streams, mode=AcquisitionMode.SEQUENTIAL)

    wrong_recording = _artifact(6, recording_id=_OTHER_RECORDING_ID)
    with pytest.raises(ValueError, match="recording"):
        replace_channel(
            bundle,
            ChannelBundle(
                artifact=wrong_recording,
                graph=register_root_artifact(
                    ArtifactGraph(), wrong_recording.artifact_id
                ),
            ),
        )

    absent = _artifact(99)
    with pytest.raises(ValueError, match="channel"):
        replace_channel(
            bundle,
            ChannelBundle(
                artifact=absent,
                graph=register_root_artifact(ArtifactGraph(), absent.artifact_id),
            ),
        )

    wrong_asset = _artifact(6, asset_id=_OTHER_ASSET_ID)
    with pytest.raises(ValueError, match="source_asset_id"):
        replace_channel(
            bundle,
            ChannelBundle(
                artifact=wrong_asset,
                graph=register_root_artifact(ArtifactGraph(), wrong_asset.artifact_id),
            ),
        )
