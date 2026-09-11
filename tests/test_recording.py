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
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionIndex,
    AcquisitionMode,
    AcquisitionRef,
    ChannelArtifact,
    ChannelConfig,
    ChannelKey,
    ProfileStatistics,
    QualityFlag,
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
    derived_artifact_id,
    observed_signal,
    source_artifact,
)
from udv_echo_process.process import (
    LinearInterpSpec,
    MedianFilterSpec,
    SyncSpec,
    derive,
    derive_many,
    filter,
    register_operation,
    revalidate_params,
    schema_version_for,
    synchronize,
)
from udv_echo_process.provenance import (
    ArtifactBundle,
    ArtifactDerivationLink,
    ArtifactGraph,
    ChannelBundle,
    ImplementationRef,
    OperationRecord,
    implementation_ref,
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
    bundle = _bundle((_artifact(6),), mode=AcquisitionMode.SEQUENTIAL)
    source = bundle.recording.streams[0]
    derived = derive(
        select_channel(bundle, ChannelKey(device_channel=6)),
        kind="rec.identity",
        spec=_IdentitySpec(),
        implementation=implementation_ref("udv_echo_process.process.derive.derive"),
        data=_payloads(bundle)[0],
    )
    bundle = replace_channel(bundle, derived)
    stream = bundle.recording.streams[0]
    assert stream.artifact_id != source.artifact_id
    assert stream.artifact_id not in bundle.graph.root_artifacts
    assert stream.artifact_id in {link.artifact_id for link in bundle.graph.derivations}
    assert len(bundle.graph.operations) == 1


def test_artifact_bundle_rejects_a_derived_stream_id_that_does_not_recompute():
    """STOP/GO: a derived stream must be consistent with its operation."""
    root = _artifact(6)
    forged = _artifact_with_id(_id(42), 7)
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
    with pytest.raises(ValidationError, match="consistent"):
        ArtifactBundle(
            recording=_recording((root, forged), mode=AcquisitionMode.SEQUENTIAL),
            graph=graph,
        )


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


# ══ Phase 7 — derive_many() and recording-level synchronization (§7.4, §8.3) ══


class _IdentitySpec(ValueModel):
    """Recording-level identity operation params for the phase-7 tests."""

    scale: float = 1.0


class _RawSpec(ValueModel):
    """Unconstrained params, used to prove derive_many's JSON-safety guard."""

    value: object = None


register_operation("rec.identity", _IdentitySpec)
register_operation("rec.raw", _RawSpec)

_IMPL_P7 = implementation_ref("udv_echo_process.process.derive.derive_many")
_SYNC_KIND = "sync.align"

_GATES = (5.0, 10.0)
_GATE_FACTOR = (1.0, 10.0)

#: Rows that carry no round/visit identity; they only bound the valid domain.
_GUARD = (-1, -1)


def _visit_stream(
    channel: int,
    rows: list[tuple[float, int, int]],
    *,
    base: float = 0.0,
    invalid_rows: tuple[int, ...] = (),
    synthetic_rows: tuple[int, ...] = (),
) -> ChannelArtifact:
    """A synthetic source stream whose rows carry explicit ``(round, visit)`` ids.

    ``rows`` is ``(time_s, round_id, visit_id)`` per row; the sentinel ``-1``
    marks a row with no round/visit identity. Each gate is a known linear ramp
    of ``time_s`` (``base + factor * t``), so aligned values are predictable.
    ``synthetic_rows`` are already-interpolated knots: they keep the synthetic
    sentinel index that ``SignalData`` requires of a row with no observation.
    """
    times = np.array([row[0] for row in rows], dtype=np.float64)
    rounds = np.array([row[1] for row in rows], dtype=np.int64)
    visits = np.array([row[2] for row in rows], dtype=np.int64)
    sample_ids = np.arange(times.size, dtype=np.int64)
    values = base + times[:, None] * np.array(_GATE_FACTOR)[None, :]
    quality = np.zeros(values.shape, dtype=np.uint32)
    for row in invalid_rows:
        values[row, :] = np.nan
        quality[row, :] = int(QualityFlag.OUTLIER)
    for row in synthetic_rows:
        sample_ids[row] = -1
        rounds[row] = -1
        visits[row] = -1
    index = AcquisitionIndex(
        sample_id=sample_ids,
        acquisition_time_s=np.where(sample_ids < 0, np.nan, times),
        round_id=rounds,
        visit_id=visits,
    )
    reference = AcquisitionRef(
        recording_id=_RECORDING_ID,
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    return source_artifact(
        reference,
        _ECHO,
        ChannelConfig(),
        _visit_data(times, values, quality, index, synthetic_rows),
    )


def _visit_data(
    times: np.ndarray,
    values: np.ndarray,
    quality: np.ndarray,
    index: AcquisitionIndex,
    synthetic_rows: tuple[int, ...],
) -> SignalData:
    """Wrap the ramp values as observations, or with synthetic knot kinds."""
    gates = np.array(_GATES, dtype=np.float64)
    if not synthetic_rows:
        return observed_signal(times, gates, values, quality=quality, acquisition=index)
    kinds = np.full(values.shape, int(SupportKind.OBSERVED), dtype=np.uint8)
    for row in synthetic_rows:
        kinds[row, :] = int(SupportKind.INTERPOLATED)
    return SignalData(
        time_s=times,
        gate_depths_mm=gates,
        values=values,
        support=SampleSupport(kind=kinds, valid=np.isfinite(values), quality=quality),
        acquisition=index,
    )


def _sync_bundle(
    streams: tuple[ChannelArtifact, ...],
    *,
    mode: AcquisitionMode = AcquisitionMode.SEQUENTIAL,
) -> ArtifactBundle:
    return _bundle(streams, mode=mode)


def _pair_bundle() -> ArtifactBundle:
    """Two channels of rounds 1-3: A visits at 0/1/2 s, B at 0.1/1.1/2.1 s."""
    channel_a = _visit_stream(
        1, [(-1.0, *_GUARD), (0.0, 1, 0), (1.0, 2, 0), (2.0, 3, 0), (3.0, *_GUARD)]
    )
    channel_b = _visit_stream(
        2,
        [(-1.0, *_GUARD), (0.1, 1, 1), (1.1, 2, 1), (2.1, 3, 1), (3.1, *_GUARD)],
        base=100.0,
    )
    return _sync_bundle((channel_a, channel_b))


def _missing_visit_bundle() -> ArtifactBundle:
    """Three channels; C carries no visit in round 2 and one in round 9."""
    channel_a = _visit_stream(
        1, [(-1.0, *_GUARD), (0.0, 1, 0), (1.0, 2, 0), (2.0, 3, 0), (3.0, *_GUARD)]
    )
    channel_b = _visit_stream(
        2,
        [(-1.0, *_GUARD), (0.1, 1, 1), (1.1, 2, 1), (2.1, 3, 1), (3.1, *_GUARD)],
        base=100.0,
    )
    channel_c = _visit_stream(
        3,
        [(-1.0, *_GUARD), (0.2, 1, 2), (1.5, 9, 0), (2.2, 3, 2), (4.0, *_GUARD)],
        base=200.0,
    )
    return _sync_bundle((channel_a, channel_b, channel_c))


def _sync_spec(
    *,
    reference: str = "earliest",
    unmatched: str = "missing",
    extrapolation: str = "missing",
) -> SyncSpec:
    return SyncSpec(
        interp=LinearInterpSpec(
            extrapolation=extrapolation,  # type: ignore[arg-type]
            max_bracket_span_s=100.0,
            long_gap="missing",
        ),
        reference=reference,  # type: ignore[arg-type]
        unmatched=unmatched,  # type: ignore[arg-type]
    )


def _ramp(times: object, base: float) -> np.ndarray:
    """The expected aligned ramp: ``base + t * factor`` per gate."""
    t = np.asarray(times, dtype=np.float64)
    return base + t[:, None] * np.array(_GATE_FACTOR)[None, :]


def _ids(streams: tuple[ChannelArtifact, ...]) -> tuple[str, ...]:
    return tuple(stream.artifact_id for stream in streams)


# ── SyncSpec ───────────────────────────────────────────────────────────


def test_sync_spec_has_exactly_the_ruled_fields():
    assert set(SyncSpec.model_fields) == {"interp", "reference", "unmatched"}
    spec = _sync_spec()
    assert spec.reference == "earliest"
    assert spec.unmatched == "missing"
    assert spec.interp.method == "linear"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reference", "midpoint"),
        ("unmatched", "skip"),
        ("interp", "linear"),
        ("method", "mean"),
    ],
)
def test_sync_spec_rejects_unknown_policies_and_fields(field, value):
    kwargs: dict[str, object] = {
        "interp": _sync_spec().interp,
        "reference": "earliest",
        "unmatched": "missing",
    }
    kwargs[field] = value
    with pytest.raises(ValidationError):
        SyncSpec(**kwargs)  # type: ignore[arg-type]


def test_sync_spec_round_trips_through_the_operation_registry():
    spec = _sync_spec(reference="mean", unmatched="error")
    params_json = json.dumps(
        spec.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    assert schema_version_for(_SYNC_KIND) == 1
    assert revalidate_params(_SYNC_KIND, 1, params_json) == spec


# ── derive_many() ──────────────────────────────────────────────────────


def _payloads(bundle: ArtifactBundle, *, scale: float = 1.0) -> tuple[SignalData, ...]:
    return tuple(
        observed_signal(
            stream.data.time_s,
            stream.data.gate_depths_mm,
            stream.data.values * scale,
        )
        for stream in bundle.recording.streams
    )


def test_derive_many_maps_every_output_to_one_operation():
    bundle = _sync_bundle((_artifact(1), _artifact(2)))
    out = derive_many(
        bundle,
        kind="rec.identity",
        spec=_IdentitySpec(),
        implementation=_IMPL_P7,
        data=_payloads(bundle),
    )
    assert len(out.graph.operations) == 1
    operation = out.graph.operations[0]
    assert operation.parents == _ids(bundle.recording.streams)
    assert len(out.graph.derivations) == 2
    produced = {
        link.artifact_id
        for link in out.graph.derivations
        if link.operation_id == operation.operation_id
    }
    assert produced == set(_ids(out.recording.streams))
    # each output id hashes the SHARED operation id plus its own payload
    for stream in out.recording.streams:
        expected = derived_artifact_id(
            operation.operation_id,
            stream.acquisition,
            stream.descriptor,
            stream.config,
            stream.data,
        )
        assert stream.artifact_id == expected
    assert out.recording.recording_id == bundle.recording.recording_id
    assert out.graph.root_artifacts == bundle.graph.root_artifacts


def test_derive_many_preserves_per_stream_identity_and_is_deterministic():
    bundle = _sync_bundle((_artifact(1), _artifact(2)))
    first = derive_many(
        bundle,
        kind="rec.identity",
        spec=_IdentitySpec(),
        implementation=_IMPL_P7,
        data=_payloads(bundle),
    )
    second = derive_many(
        bundle,
        kind="rec.identity",
        spec=_IdentitySpec(),
        implementation=_IMPL_P7,
        data=_payloads(bundle),
    )
    assert _ids(first.recording.streams) == _ids(second.recording.streams)
    for before, after in zip(
        first.recording.streams, second.recording.streams, strict=True
    ):
        assert before.acquisition == after.acquisition
        assert before.descriptor == after.descriptor
        assert before.config == after.config


def test_derive_many_requires_one_output_per_stream():
    bundle = _sync_bundle((_artifact(1), _artifact(2)))
    with pytest.raises(ValueError, match="one output payload per stream"):
        derive_many(
            bundle,
            kind="rec.identity",
            spec=_IdentitySpec(),
            implementation=_IMPL_P7,
            data=(_payloads(bundle)[0],),
        )


def test_derive_many_rejects_a_non_signal_payload():
    bundle = _sync_bundle((_artifact(1),))
    with pytest.raises(ValidationError):
        derive_many(
            bundle,
            kind="rec.identity",
            spec=_IdentitySpec(),
            implementation=_IMPL_P7,
            data=({"values": 1},),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "raw",
    [float("nan"), float("inf"), np.arange(3), Path("params.npy"), (lambda: None)],
    ids=["nan", "inf", "ndarray", "path", "callable"],
)
def test_derive_many_rejects_non_json_params(raw):
    bundle = _sync_bundle((_artifact(1),))
    with pytest.raises(ValueError, match="derive_many: recording"):
        derive_many(
            bundle,
            kind="rec.raw",
            spec=_RawSpec(value=raw),
            implementation=_IMPL_P7,
            data=_payloads(bundle),
        )


def test_derive_many_rejects_an_unregistered_kind_or_wrong_spec():
    bundle = _sync_bundle((_artifact(1),))
    with pytest.raises(ValueError, match="no operation registered"):
        derive_many(
            bundle,
            kind="rec.missing",
            spec=_IdentitySpec(),
            implementation=_IMPL_P7,
            data=_payloads(bundle),
        )
    with pytest.raises(ValueError, match="expects spec"):
        derive_many(
            bundle,
            kind="rec.raw",
            spec=_IdentitySpec(),
            implementation=_IMPL_P7,
            data=_payloads(bundle),
        )


# ── synchronization: one operation, reference policies, support ────────


def test_synchronize_emits_exactly_one_recording_level_operation():
    bundle = _pair_bundle()
    before = bundle.graph
    out = synchronize(bundle, _sync_spec())
    assert isinstance(out, ArtifactBundle)
    assert out is not bundle
    assert len(out.graph.operations) == len(before.operations) + 1
    assert len(out.graph.derivations) == len(before.derivations) + 2
    operation = out.graph.operations[-1]
    assert operation.kind == _SYNC_KIND
    assert operation.parents == _ids(bundle.recording.streams)
    produced = {
        link.artifact_id
        for link in out.graph.derivations
        if link.operation_id == operation.operation_id
    }
    assert produced == set(_ids(out.recording.streams))
    for stream in out.recording.streams:
        assert stream.artifact_id == derived_artifact_id(
            operation.operation_id,
            stream.acquisition,
            stream.descriptor,
            stream.config,
            stream.data,
        )
    assert out.recording.recording_id == bundle.recording.recording_id
    assert out.recording.source_asset == bundle.recording.source_asset
    assert out.recording.acquisition_mode is bundle.recording.acquisition_mode
    assert len(out.recording.streams) == len(bundle.recording.streams)


def test_synchronize_earliest_keeps_the_reference_stream_observed_and_indexed():
    out = synchronize(_pair_bundle(), _sync_spec(reference="earliest"))
    channel_a, channel_b = out.recording.streams
    grid = np.array([0.0, 1.0, 2.0])
    assert np.allclose(channel_a.data.time_s, grid)
    assert np.allclose(channel_b.data.time_s, grid)
    # A's own visits define the reference grid: exact knots stay OBSERVED ...
    assert np.array_equal(
        channel_a.data.support.kind,
        np.full((3, 2), int(SupportKind.OBSERVED), dtype=np.uint8),
    )
    assert np.allclose(channel_a.data.values, _ramp(grid, 0.0))
    # ... and keep their real row index (sample id, round/visit, actual time)
    index = channel_a.data.acquisition
    assert index is not None
    assert index.sample_id.tolist() == [1, 2, 3]
    assert index.round_id.tolist() == [1, 2, 3]
    assert index.visit_id.tolist() == [0, 0, 0]
    assert np.allclose(index.acquisition_time_s, grid)
    assert np.array_equal(channel_a.data.support.quality, np.zeros((3, 2), np.uint32))
    # B is sampled at times it never acquired: interpolated and time-aligned
    assert np.array_equal(
        channel_b.data.support.kind,
        np.full((3, 2), int(SupportKind.INTERPOLATED), dtype=np.uint8),
    )
    assert np.allclose(channel_b.data.values, _ramp(grid, 100.0))
    assert np.array_equal(
        channel_b.data.support.quality,
        np.full((3, 2), int(QualityFlag.TIME_ALIGNED), dtype=np.uint32),
    )


@pytest.mark.parametrize(
    ("policy", "grid", "exact_channel"),
    [
        ("latest", [0.1, 1.1, 2.1], 1),
        ("mean", [0.05, 1.05, 2.05], None),
    ],
)
def test_synchronize_reference_policy_selects_the_target_row_times(
    policy, grid, exact_channel
):
    out = synchronize(_pair_bundle(), _sync_spec(reference=policy))
    channel_a, channel_b = out.recording.streams
    assert np.allclose(channel_a.data.time_s, grid)
    assert np.allclose(channel_b.data.time_s, grid)
    assert np.allclose(channel_a.data.values, _ramp(grid, 0.0))
    assert np.allclose(channel_b.data.values, _ramp(grid, 100.0))
    observed = np.full((3, 2), int(SupportKind.OBSERVED), dtype=np.uint8)
    interpolated = np.full((3, 2), int(SupportKind.INTERPOLATED), dtype=np.uint8)
    expected_a, expected_b = (
        (interpolated, observed) if exact_channel == 1 else (interpolated, interpolated)
    )
    assert np.array_equal(channel_a.data.support.kind, expected_a)
    assert np.array_equal(channel_b.data.support.kind, expected_b)


def test_synchronize_keeps_actual_times_and_never_writes_the_reference_grid():
    bundle = _pair_bundle()
    out = synchronize(bundle, _sync_spec(reference="earliest"))
    channel_a, channel_b = out.recording.streams
    grid = np.array([0.0, 1.0, 2.0])
    # A's aligned rows are its own acquisitions: the actual time is preserved
    index = channel_a.data.acquisition
    assert index is not None
    assert np.allclose(index.acquisition_time_s, grid)
    # B acquired at 0.1/1.1/2.1 s, so no aligned row may claim an acquisition
    # at the reference times: the actual-time channel stays unattributed
    index = channel_b.data.acquisition
    assert index is not None
    assert np.isnan(index.acquisition_time_s).all()
    assert (index.sample_id == -1).all()
    assert (index.round_id == -1).all()
    assert (index.visit_id == -1).all()
    assert not np.array_equal(index.acquisition_time_s, grid)
    source_b = bundle.recording.streams[1]
    source_index = source_b.data.acquisition
    assert source_index is not None
    assert source_index.round_id.tolist() == [-1, 1, 2, 3, -1]
    assert np.allclose(source_index.acquisition_time_s[[1, 2, 3]], [0.1, 1.1, 2.1])


def test_synchronize_accumulates_quality_bits_never_replaces_them():
    """An invalid observed knot becomes MISSING with the primitive's bits."""
    channel_a = _visit_stream(
        1, [(-1.0, *_GUARD), (0.0, 1, 0), (1.0, 2, 0), (2.0, 3, 0), (3.0, *_GUARD)]
    )
    channel_b = _visit_stream(
        2,
        [(-1.0, *_GUARD), (0.1, 1, 1), (1.1, 2, 1), (2.1, 3, 1), (3.1, *_GUARD)],
        base=100.0,
        invalid_rows=(1,),
    )
    out = synchronize(_sync_bundle((channel_a, channel_b)), _sync_spec())
    channel_b_out = out.recording.streams[1]
    expected = (
        int(QualityFlag.OUTLIER)
        | int(QualityFlag.GAP_TOO_LONG)
        | int(QualityFlag.TIME_ALIGNED)
    )
    assert np.array_equal(
        channel_b_out.data.support.kind,
        np.array([[0, 0], [0, 0], [int(SupportKind.INTERPOLATED)] * 2], np.uint8),
    )
    assert np.array_equal(
        channel_b_out.data.support.quality,
        np.array(
            [
                [expected, expected],
                [expected, expected],
                [int(QualityFlag.TIME_ALIGNED)] * 2,
            ],
            np.uint32,
        ),
    )
    assert np.isnan(channel_b_out.data.values[0]).all()


def test_synchronize_marks_reinterpolated_ancestry():
    """A synthetic ancestor adds REINTERPOLATED on top of TIME_ALIGNED."""
    channel_a = _visit_stream(
        1, [(-1.0, *_GUARD), (0.0, 1, 0), (1.0, 2, 0), (2.0, 3, 0), (3.0, *_GUARD)]
    )
    channel_b = _visit_stream(
        2,
        [(-1.0, *_GUARD), (0.05, 1, 1), (1.5, *_GUARD), (2.1, 2, 1), (3.0, *_GUARD)],
        base=100.0,
        synthetic_rows=(2,),
    )
    out = synchronize(_sync_bundle((channel_a, channel_b)), _sync_spec())
    channel_b_out = out.recording.streams[1]
    assert np.allclose(channel_b_out.data.time_s, [0.0, 1.0])
    quality = channel_b_out.data.support.quality
    assert (quality[0] == int(QualityFlag.TIME_ALIGNED)).all()
    expected = int(QualityFlag.REINTERPOLATED) | int(QualityFlag.TIME_ALIGNED)
    assert (quality[1] == expected).all()
    assert (channel_b_out.data.support.kind[1] == int(SupportKind.INTERPOLATED)).all()


# ── synchronization: absent/unmatched visits and hard errors ───────────


def test_synchronize_unmatched_visits_are_missing_and_alignment_uncertain():
    bundle = _missing_visit_bundle()
    out = synchronize(bundle, _sync_spec())
    channel_c = out.recording.streams[2]
    # C has no visit in round 2 and one unmatched round 9 that yields no row
    assert np.allclose(channel_c.data.time_s, [0.0, 1.0, 2.0])
    kinds = channel_c.data.support.kind
    quality = channel_c.data.support.quality
    aligned = int(QualityFlag.TIME_ALIGNED)
    uncertain = int(QualityFlag.ALIGNMENT_UNCERTAIN)
    assert (kinds[0] == int(SupportKind.INTERPOLATED)).all()
    assert (quality[0] == aligned).all()
    assert (kinds[1] == int(SupportKind.MISSING)).all()
    assert (quality[1] == uncertain).all()
    assert np.isnan(channel_c.data.values[1]).all()
    assert (kinds[2] == int(SupportKind.INTERPOLATED)).all()
    assert (quality[2] == aligned).all()
    index = channel_c.data.acquisition
    assert index is not None
    assert index.sample_id.tolist() == [-1, -1, -1]
    assert (index.round_id == -1).all()
    operation = out.graph.operations[-1]
    assert operation.warnings == ("1 unmatched channel visit marked missing",)


def test_synchronize_absent_visits_are_never_renumbered_or_filled_by_position():
    out = synchronize(_missing_visit_bundle(), _sync_spec())
    channel_c = out.recording.streams[2]
    # exactly one output row per matched round, and the single-stream round 9
    # visit (t = 1.5 s) is simply absent — not shifted into another row
    assert channel_c.data.time_s.size == 3
    assert 1.5 not in channel_c.data.time_s.tolist()
    channel_a, _channel_b, _channel_c = out.recording.streams
    assert channel_a.data.time_s.size == 3


def test_synchronize_unmatched_error_raises_naming_channel_and_round():
    with pytest.raises(ValueError, match="unmatched='error'") as ei:
        synchronize(_missing_visit_bundle(), _sync_spec(unmatched="error"))
    assert "channel 3" in str(ei.value)
    assert "round 2" in str(ei.value)


def test_synchronize_rejects_a_stream_without_round_visit_identity():
    bundle = _sync_bundle((_artifact(4),))
    with pytest.raises(ValueError, match=r"explicit \(round_id, visit_id\)"):
        synchronize(bundle, _sync_spec())


def test_synchronize_rejects_duplicate_round_visit_pairs():
    # ``Recording`` already refuses a repeated pair, so the reader path cannot
    # deliver one; skip model validation to exercise synchronize's own guard.
    stream = _visit_stream(
        1,
        [(-1.0, *_GUARD), (0.0, 1, 0), (1.0, 1, 0), (2.0, 2, 0), (3.0, *_GUARD)],
    )
    graph = register_root_artifact(ArtifactGraph(), stream.artifact_id)
    recording = Recording.model_construct(
        recording_id=_RECORDING_ID,
        source_asset=SOURCE_ASSET,
        acquisition_mode=AcquisitionMode.SEQUENTIAL,
        streams=(stream,),
        acquisition_order=None,
    )
    bundle = ArtifactBundle.model_construct(recording=recording, graph=graph)
    with pytest.raises(ValueError, match="duplicate"):
        synchronize(bundle, _sync_spec())


def test_synchronize_rejects_ambiguous_visits_within_a_matched_round():
    channel_a = _visit_stream(
        1, [(-1.0, *_GUARD), (0.0, 1, 0), (0.5, 1, 1), (2.0, *_GUARD)]
    )
    channel_b = _visit_stream(2, [(-1.0, *_GUARD), (0.1, 1, 0), (2.0, *_GUARD)])
    with pytest.raises(ValueError, match="ambiguous"):
        synchronize(_sync_bundle((channel_a, channel_b)), _sync_spec())


def test_synchronize_rejects_nonmonotonic_round_order():
    channel_a = _visit_stream(
        1, [(-1.0, *_GUARD), (0.0, 2, 0), (1.0, 1, 0), (2.0, *_GUARD)]
    )
    channel_b = _visit_stream(
        2, [(-1.0, *_GUARD), (0.1, 2, 0), (1.1, 1, 0), (2.0, *_GUARD)], base=100.0
    )
    with pytest.raises(ValueError, match="nonmonotonic"):
        synchronize(_sync_bundle((channel_a, channel_b)), _sync_spec())


def test_synchronize_requires_at_least_two_channels_per_matched_round():
    channel_a = _visit_stream(1, [(-1.0, *_GUARD), (0.0, 1, 0), (2.0, *_GUARD)])
    channel_b = _visit_stream(2, [(-1.0, *_GUARD), (0.1, 2, 0), (2.0, *_GUARD)])
    with pytest.raises(ValueError, match="no round_id is shared"):
        synchronize(_sync_bundle((channel_a, channel_b)), _sync_spec())


def test_synchronize_rejects_a_non_sync_spec():
    with pytest.raises(TypeError, match="SyncSpec"):
        synchronize(_pair_bundle(), _sync_spec().interp)  # type: ignore[arg-type]


def test_real_bdd_fixtures_carry_no_round_visit_identity_to_match():
    """The DOP format cannot prove round/visit identity, so sync refuses it."""
    bundle = load(Path("data") / "4-sensor-velocity" / "200RPM.BDD")
    assert bundle.recording.acquisition_mode is AcquisitionMode.SEQUENTIAL
    with pytest.raises(ValueError, match=r"explicit \(round_id, visit_id\)"):
        synchronize(bundle, _sync_spec())


# ── synchronization: purity, traceability and the DAG ──────────────────


def test_synchronize_leaves_its_input_untouched_and_is_deterministic():
    bundle = _pair_bundle()
    before = (
        _ids(bundle.recording.streams),
        bundle.graph.operations,
        bundle.graph.derivations,
        bundle.graph.root_artifacts,
    )
    first = synchronize(bundle, _sync_spec())
    second = synchronize(bundle, _sync_spec())
    assert _ids(first.recording.streams) == _ids(second.recording.streams)
    assert (
        first.graph.operations[-1].operation_id
        == second.graph.operations[-1].operation_id
    )
    after = (
        _ids(bundle.recording.streams),
        bundle.graph.operations,
        bundle.graph.derivations,
        bundle.graph.root_artifacts,
    )
    assert before == after


def test_synchronized_streams_trace_to_their_source_roots():
    out = synchronize(_pair_bundle(), _sync_spec())
    operation = out.graph.operations[-1]
    producers = {link.artifact_id: link.operation_id for link in out.graph.derivations}
    for stream in out.recording.streams:
        assert producers[stream.artifact_id] == operation.operation_id
    assert set(operation.parents) <= set(out.graph.root_artifacts)


def test_filtered_streams_synchronize_and_trace_to_sources():
    bundle = _pair_bundle()
    key = ChannelKey(device_channel=1)
    filtered = filter(
        select_channel(bundle, key), MedianFilterSpec(window=3, max_gap_s=10.0)
    )
    bundle = replace_channel(bundle, filtered)
    out = synchronize(bundle, _sync_spec())
    assert len(out.graph.operations) == 2
    assert [op.kind for op in out.graph.operations] == ["filter.median", _SYNC_KIND]
    operation = out.graph.operations[-1]
    produced_by_filter = {
        link.artifact_id
        for link in out.graph.derivations
        if link.operation_id == out.graph.operations[0].operation_id
    }
    assert set(operation.parents) <= produced_by_filter | set(out.graph.root_artifacts)
    assert operation.parents[0] in produced_by_filter


def test_bundle_json_metadata_projection_has_no_ndarray_and_no_absolute_path():
    out = synchronize(_pair_bundle(), _sync_spec())
    projection: dict[str, object] = {
        "recording": {
            "recording_id": out.recording.recording_id,
            "source_asset": out.recording.source_asset.model_dump(mode="json"),
            "acquisition_mode": out.recording.acquisition_mode.value,
            "streams": [
                {
                    "artifact_id": stream.artifact_id,
                    "acquisition": stream.acquisition.model_dump(mode="json"),
                    "descriptor": stream.descriptor.model_dump(mode="json"),
                    "config": stream.config.model_dump(mode="json"),
                }
                for stream in out.recording.streams
            ],
        },
        "graph": out.graph.model_dump(mode="json"),
    }
    text = json.dumps(projection, sort_keys=True)
    assert "/home" not in text
    assert "ndarray" not in text

    def walk(node: object) -> None:
        assert not isinstance(node, np.ndarray), node
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(projection)
    graph = projection["graph"]
    assert isinstance(graph, dict)
    assert len(graph["operations"]) == 1
