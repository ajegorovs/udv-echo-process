"""The single constructor for transformed per-channel artifacts (plan §8.3).

``derive()`` is the only supported way to build a *derived* artifact: transform
bodies compute owned arrays and a validated spec, then call it. It preserves the
parent's acquisition identity and metadata (unless an explicit replacement is
supplied), resolves the spec to canonical ``params_json``, computes the
operation and artifact ids, inserts one provenance edge into a NEW graph and
returns a closed ``ChannelBundle``. It never mutates its input.

``params_json`` is produced only from ``spec.model_dump(mode="json",
exclude_none=False)`` and encoded as canonical JSON. A pre-encode guard rejects
NaN/Infinity, ndarray, Path, callable and arbitrary Python values before
encoding. Readers resolve ``(kind, schema_version)`` through
:data:`OPERATION_SPEC_REGISTRY` and revalidate with the registered spec —
:func:`revalidate_params` is that path. Phases 4, 5 and 8 extend the registry;
this module holds only what Phase 3 needs.

Phase 7 adds :func:`derive_many`, the recording-level sibling: one operation
node over an ``ArtifactBundle`` with multiple ordered parents and one or more
output artifacts, sharing the canonical operation-id and graph-insertion path
above (plan §8.3).

Per plan §13 a transform does not re-scan its parent at stage entry; the new
output is validated once, by construction.
"""

from __future__ import annotations

import json
import math
from enum import Enum
from typing import Any

from udv_echo_process.models._canonical import canonical_json_bytes
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.models.identity import SignalDescriptor
from udv_echo_process.models.recording import Recording
from udv_echo_process.models.signal import (
    ChannelArtifact,
    SignalData,
    derived_artifact_id,
)
from udv_echo_process.provenance.models import (
    ArtifactBundle,
    ChannelBundle,
    ImplementationRef,
    OperationRecord,
    insert_operation,
    insert_operation_many,
    operation_id_for,
)

#: Operation schema version for the kinds registered in Phase 3. Any semantic
#: change to a registered kind's parameters increments the relevant version
#: (plan §12.6); readers resolve it explicitly through the registry.
OPERATION_SCHEMA_VERSION: int = 1

#: ``(kind, schema_version) -> spec class`` operation registry. Phase 3 holds
#: the identity kinds; phases 4/5/8 register filter, interpolation and storage
#: kinds here (or in their own modules via :func:`register_operation`).
OPERATION_SPEC_REGISTRY: dict[tuple[str, int], type[ValueModel]] = {}

_JSON_SCALARS = (bool, int, str)


def register_operation(
    kind: str,
    spec_type: type[ValueModel],
    *,
    schema_version: int = OPERATION_SCHEMA_VERSION,
) -> None:
    """Register the resolved-parameter spec class for ``(kind, schema_version)``.

    Args:
        kind: stable operation verb, e.g. ``"filter.median"``.
        spec_type: the ``ValueModel`` subclass holding that operation's params.
        schema_version: operation schema version (``>= 1``).

    Raises:
        ValueError: empty kind, ``schema_version < 1``, a non-``ValueModel``
            spec, or a duplicate ``(kind, schema_version)`` registration.
    """
    if not kind or not kind.strip():
        raise ValueError("kind must be a non-empty string")
    if schema_version < 1:
        raise ValueError(f"schema_version must be >= 1, got {schema_version}")
    if not (isinstance(spec_type, type) and issubclass(spec_type, ValueModel)):
        raise TypeError(f"spec_type must be a ValueModel subclass, got {spec_type!r}")
    key = (kind, schema_version)
    if key in OPERATION_SPEC_REGISTRY:
        raise ValueError(
            f"operation ({kind!r}, schema_version={schema_version}) is already "
            "registered"
        )
    OPERATION_SPEC_REGISTRY[key] = spec_type


def resolve_operation_spec(kind: str, schema_version: int) -> type[ValueModel]:
    """Return the registered spec class for ``(kind, schema_version)``.

    Raises:
        ValueError: when the pair is not registered (never guessed).
    """
    try:
        return OPERATION_SPEC_REGISTRY[(kind, schema_version)]
    except KeyError as exc:
        raise ValueError(
            f"no operation registered for kind {kind!r}, "
            f"schema_version {schema_version}"
        ) from exc


def schema_version_for(kind: str) -> int:
    """Return the single registered schema version for ``kind``.

    Raises:
        ValueError: when the kind is unregistered or has multiple versions.
    """
    versions = sorted(
        version
        for (registered_kind, version) in OPERATION_SPEC_REGISTRY
        if registered_kind == kind
    )
    if not versions:
        raise ValueError(f"no operation registered for kind {kind!r}")
    if len(versions) > 1:
        raise ValueError(
            f"kind {kind!r} has multiple registered schema versions {versions}; "
            "resolve (kind, schema_version) explicitly"
        )
    return versions[0]


def revalidate_params(kind: str, schema_version: int, params_json: str) -> ValueModel:
    """Parse ``params_json`` and revalidate it with the registered spec.

    The reader path of plan §8.1: the text must decode to a JSON object and
    every registered field must validate. An unknown ``(kind, schema_version)``
    pair is rejected rather than guessed.

    Args:
        kind: operation verb.
        schema_version: operation schema version.
        params_json: canonical JSON object of resolved parameters.

    Returns:
        The revalidated spec instance.

    Raises:
        ValueError: unknown operation, malformed JSON or a non-object payload.
        pydantic.ValidationError: the object fails the registered spec.
    """
    spec_type = resolve_operation_spec(kind, schema_version)
    try:
        parsed = json.loads(params_json)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{kind!r} params_json is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TypeError(
            f"{kind!r} params_json must be a JSON object, got {type(parsed).__name__}"
        )
    return spec_type.model_validate(parsed)


def _reject_non_json(
    value: Any, *, kind: str, subject: str, path: str, prefix: str = "derive"
) -> None:
    """Raise unless every value is a JSON-safe primitive/container.

    Numbers must be finite; ndarray, Path, callable and any other Python object
    are rejected before encoding (plan §8.1). ``subject`` names the channel or
    recording being derived and ``prefix`` the public callable that failed.
    """
    if value is None or isinstance(value, _JSON_SCALARS):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"{prefix}: {subject} operation {kind!r} param {path!r} is a "
                f"non-finite float ({value!r}); NaN/Infinity are rejected "
                "before encoding"
            )
        return
    if isinstance(value, Enum):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"{prefix}: {subject} operation {kind!r} param {path!r} "
                    f"has a non-string key {key!r}"
                )
            _reject_non_json(
                item, kind=kind, subject=subject, path=f"{path}.{key}", prefix=prefix
            )
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_json(
                item,
                kind=kind,
                subject=subject,
                path=f"{path}[{index}]",
                prefix=prefix,
            )
        return
    described = "a callable" if callable(value) else f"a {type(value).__name__}"
    raise ValueError(
        f"{prefix}: {subject} operation {kind!r} param {path!r} "
        f"holds {described}; params must be JSON-safe "
        "(object/array/string/number/boolean/null)"
    )


def _canonical_params_json(
    spec: ValueModel, *, kind: str, subject: str, prefix: str = "derive"
) -> str:
    """Resolve ``spec`` to its canonical ``params_json`` object (plan §8.1)."""
    try:
        python_values = spec.model_dump(mode="python", exclude_none=False)
    except Exception as exc:
        raise ValueError(
            f"{prefix}: {subject} operation {kind!r} params "
            f"cannot be read from the spec: {exc}"
        ) from exc
    _reject_non_json(
        python_values, kind=kind, subject=subject, path="spec", prefix=prefix
    )
    try:
        json_values = spec.model_dump(mode="json", exclude_none=False)
    except Exception as exc:
        raise ValueError(
            f"{prefix}: {subject} operation {kind!r} params "
            f"cannot be serialized to JSON: {exc}"
        ) from exc
    _reject_non_json(
        json_values, kind=kind, subject=subject, path="spec", prefix=prefix
    )
    try:
        return canonical_json_bytes(json_values).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{prefix}: {subject} operation {kind!r} params "
            f"are not canonical-JSON encodable: {exc}"
        ) from exc


def _resolve_operation(
    kind: str, spec: ValueModel, *, subject: str, prefix: str
) -> int:
    """Return the registered schema version, requiring the exact spec class."""
    schema_version = schema_version_for(kind)
    registered = resolve_operation_spec(kind, schema_version)
    if type(spec) is not registered:
        raise ValueError(
            f"{prefix}: {subject} operation {kind!r} expects spec "
            f"{registered.__name__}, got {type(spec).__name__}"
        )
    return schema_version


def derive(
    parent: ChannelBundle,
    *,
    kind: str,
    spec: ValueModel,
    implementation: ImplementationRef,
    data: SignalData,
    warnings: tuple[str, ...] = (),
    descriptor: SignalDescriptor | None = None,
    config: ChannelConfig | None = None,
) -> ChannelBundle:
    """Build the transformed artifact and its provenance edge (plan §8.3).

    The only constructor for transformed artifacts. It validates the resolved
    JSON params, preserves acquisition identity, uses the parent's descriptor
    and config unless an explicit replacement is supplied, computes the
    operation and artifact ids, validates the fully built output once by
    construction, inserts the record into a NEW validated graph and returns the
    closed bundle. The input bundle and graph are never mutated, and ``data``
    must already own its arrays (constructing a fresh ``SignalData`` gives that).

    Args:
        parent: the validated bundle this operation consumes.
        kind: registered operation verb.
        spec: the branch-specific spec; must match the registered spec class.
        implementation: which build of the operation ran.
        data: the new output payload (owned arrays, validated by construction).
        warnings: scientifically meaningful fallbacks/counts, never logs or
            timestamps; empty is ``()``.
        descriptor: explicit replacement descriptor, else the parent's.
        config: explicit replacement config, else the parent's.

    Returns:
        A new closed :class:`~udv_echo_process.provenance.ChannelBundle`.

    Raises:
        ValueError: unregistered kind, mismatched spec type or non-JSON params.
        pydantic.ValidationError: the output artifact or the extended DAG fails.
    """
    channel = parent.artifact.acquisition.channel
    subject = f"channel {channel.device_channel}"
    schema_version = _resolve_operation(kind, spec, subject=subject, prefix="derive")
    params_json = _canonical_params_json(
        spec, kind=kind, subject=subject, prefix="derive"
    )
    if not isinstance(data, SignalData):
        # Validate a non-model payload exactly once, through the model, before
        # it is hashed — never trust a raw mapping (plan §8.3, §13).
        data = SignalData.model_validate(data)
    acquisition = parent.artifact.acquisition
    output_descriptor = parent.artifact.descriptor if descriptor is None else descriptor
    output_config = parent.artifact.config if config is None else config
    parents = (parent.artifact.artifact_id,)

    operation_id = operation_id_for(
        kind, schema_version, params_json, implementation, parents
    )
    artifact_id = derived_artifact_id(
        operation_id, acquisition, output_descriptor, output_config, data
    )
    artifact = ChannelArtifact(
        artifact_id=artifact_id,
        acquisition=acquisition,
        descriptor=output_descriptor,
        config=output_config,
        data=data,
    )
    record = OperationRecord(
        operation_id=operation_id,
        kind=kind,
        schema_version=schema_version,
        params_json=params_json,
        implementation=implementation,
        parents=parents,
        warnings=warnings,
    )
    graph = insert_operation(parent.graph, record, artifact_id=artifact.artifact_id)
    return ChannelBundle(artifact=artifact, graph=graph)


def derive_many(
    parent: ArtifactBundle,
    *,
    kind: str,
    spec: ValueModel,
    implementation: ImplementationRef,
    data: tuple[SignalData, ...],
    warnings: tuple[str, ...] = (),
) -> ArtifactBundle:
    """Build a recording-level, multi-output operation (plan §8.3, §7.4).

    The recording-level sibling of :func:`derive`: ONE logical operation with
    multiple ORDERED parents — the bundle's stream artifacts in recording order
    — that produces one or more output artifacts. It reuses the whole
    construction path: the same canonical ``params_json``, the same operation-id
    equation (kind, schema version, resolved params, implementation and the
    ordered parent ids) and the same pure graph insertion. Every output artifact
    maps to that single operation, and each output id hashes the SHARED
    operation id plus its own payload. The input bundle and graph are never
    mutated.

    ``data`` must hold exactly one validated payload per stream, in the same
    order, so each output keeps its stream's acquisition identity, descriptor
    and config while its signal content is the supplied payload.

    Args:
        parent: the validated recording-level bundle this operation consumes.
        kind: registered operation verb.
        spec: the branch-specific spec; must match the registered spec class.
        implementation: which build of the operation ran.
        data: one output payload per stream, in recording order.
        warnings: scientifically meaningful fallbacks/counts, never logs or
            timestamps; empty is ``()``.

    Returns:
        A new closed :class:`~udv_echo_process.provenance.ArtifactBundle`.

    Raises:
        TypeError: a single ``SignalData`` was passed instead of a sequence.
        ValueError: unregistered kind, mismatched spec type, non-JSON params or
            an output count that does not match the stream count.
        pydantic.ValidationError: an output artifact or the extended DAG fails.
    """
    recording = parent.recording
    subject = f"recording {recording.recording_id}"
    schema_version = _resolve_operation(
        kind, spec, subject=subject, prefix="derive_many"
    )
    params_json = _canonical_params_json(
        spec, kind=kind, subject=subject, prefix="derive_many"
    )
    if isinstance(data, SignalData):
        raise TypeError(
            f"derive_many: {subject} operation {kind!r} expects a sequence of "
            "output payloads, one per stream, got a single SignalData"
        )
    payloads = tuple(
        payload
        if isinstance(payload, SignalData)
        else SignalData.model_validate(payload)
        for payload in data
    )
    streams = recording.streams
    if len(payloads) != len(streams):
        raise ValueError(
            f"derive_many: {subject} operation {kind!r} needs one output "
            f"payload per stream ({len(streams)} stream(s), {len(payloads)} "
            "payload(s))"
        )
    parents = tuple(stream.artifact_id for stream in streams)
    operation_id = operation_id_for(
        kind, schema_version, params_json, implementation, parents
    )
    outputs = tuple(
        ChannelArtifact(
            artifact_id=derived_artifact_id(
                operation_id,
                stream.acquisition,
                stream.descriptor,
                stream.config,
                payload,
            ),
            acquisition=stream.acquisition,
            descriptor=stream.descriptor,
            config=stream.config,
            data=payload,
        )
        for stream, payload in zip(streams, payloads, strict=True)
    )
    record = OperationRecord(
        operation_id=operation_id,
        kind=kind,
        schema_version=schema_version,
        params_json=params_json,
        implementation=implementation,
        parents=parents,
        warnings=warnings,
    )
    graph = insert_operation_many(
        parent.graph, record, artifact_ids=tuple(a.artifact_id for a in outputs)
    )
    return ArtifactBundle(
        recording=Recording(
            recording_id=recording.recording_id,
            source_asset=recording.source_asset,
            acquisition_mode=recording.acquisition_mode,
            streams=outputs,
            acquisition_order=recording.acquisition_order,
        ),
        graph=graph,
    )
