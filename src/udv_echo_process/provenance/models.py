"""Normalized provenance: implementation refs, operations and the artifact DAG.

Plan §8.1–§8.2. A per-channel transform records exactly one ``OperationRecord``
node and one ``ArtifactDerivationLink`` edge in an ``ArtifactGraph``; the
artifact itself carries ids, never a copied history list. ``ChannelBundle``
pairs the current artifact with that closed graph, so a transform cannot return
data while silently dropping provenance.

Everything here is immutable and pure: insertion helpers return a *new* graph
and never touch their input, so a failed operation cannot partially update
provenance (plan §8.3). Cycle detection, multi-parent ``derive_many()`` and the
bundle-wide id-versus-graph scan are Phase 7 and are intentionally absent.
"""

from __future__ import annotations

import json
import re
import subprocess
from importlib import metadata
from typing import Any

from pydantic import ValidationInfo, field_validator, model_validator

from udv_echo_process.models._canonical import canonical_json_bytes, stable_id
from udv_echo_process.models.base import ArrayModel, ValueModel
from udv_echo_process.models.signal import ChannelArtifact

#: Opaque id form: ``sha256:`` plus 64 lower-case hex characters.
_SHA256_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")

#: Installed distribution name whose version a default ref records.
_PACKAGE = "udv-echo-process"

#: ``unknown-version`` fallback when the distribution metadata is absent.
_UNKNOWN_VERSION = "0+unknown"


def _strip_non_empty(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def _check_opaque_id(value: str, *, field_name: str) -> str:
    text = _strip_non_empty(value, field_name=field_name)
    if not _SHA256_ID_RE.fullmatch(text):
        raise ValueError(
            f"{field_name} must be an opaque lower-case 'sha256:<64 hex>' id, "
            f"got {value!r}"
        )
    return text


def installed_version() -> str:
    """Return the installed ``udv-echo-process`` version.

    Falls back to ``"0+unknown"`` when the distribution metadata is missing
    (an uninstalled source tree), so a reference is never blocked on packaging.
    """
    try:
        return metadata.version(_PACKAGE)
    except metadata.PackageNotFoundError:
        return _UNKNOWN_VERSION


def current_revision() -> str | None:
    """Return the checkout's short git SHA, or ``None`` when unavailable.

    Read-only and best-effort: a missing ``git`` binary or a non-repository
    working directory yields ``None``. A revision is never required (plan §8.1).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except OSError, subprocess.CalledProcessError:
        return None
    revision = result.stdout.strip()
    return revision or None


class ImplementationRef(ValueModel):
    """Which callable produced an operation, and which build of it.

    ``revision`` is a git SHA only when available and is never required, so a
    model built outside a checkout remains valid.
    """

    package: str
    version: str
    callable: str
    revision: str | None = None

    @field_validator("package", "version", "callable")
    @classmethod
    def _check_non_empty(cls, value: str, info: ValidationInfo) -> str:
        return _strip_non_empty(value, field_name=info.field_name)

    @field_validator("revision")
    @classmethod
    def _check_optional_revision(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        return _strip_non_empty(value, field_name=info.field_name)


def implementation_ref(
    callable_name: str, *, revision: str | None = None
) -> ImplementationRef:
    """Build an :class:`ImplementationRef` for ``callable_name``.

    ``version`` comes from the installed distribution metadata and ``revision``
    is the checkout's short git SHA when discoverable — pass it explicitly to
    keep a caller in control, or leave it ``None`` and it is probed once here.

    Args:
        callable_name: fully-qualified public callable, e.g.
            ``"udv_echo_process.process.derive.derive"``.
        revision: explicit git revision, or ``None`` to probe the checkout.

    Returns:
        A validated :class:`ImplementationRef`.
    """
    return ImplementationRef(
        package=_PACKAGE,
        version=installed_version(),
        callable=callable_name,
        revision=revision if revision is not None else current_revision(),
    )


class OperationRecord(ValueModel):
    """One logical operation node: recipe, implementation and ordered parents."""

    operation_id: str
    kind: str
    schema_version: int
    params_json: str
    implementation: ImplementationRef
    parents: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @field_validator("operation_id")
    @classmethod
    def _check_operation_id(cls, value: str, info: ValidationInfo) -> str:
        return _check_opaque_id(value, field_name=info.field_name)

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, value: str, info: ValidationInfo) -> str:
        return _strip_non_empty(value, field_name=info.field_name)

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"schema_version must be >= 1, got {value}")
        return value

    @field_validator("params_json")
    @classmethod
    def _check_params_json(cls, value: str, info: ValidationInfo) -> str:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{info.field_name} must be a canonical JSON object: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            # pydantic wraps ValueError (not TypeError) into ValidationError.
            raise ValueError(  # noqa: TRY004
                f"{info.field_name} must encode a JSON object, got "
                f"{type(parsed).__name__}"
            )
        try:
            canonical = canonical_json_bytes(parsed).decode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{info.field_name} must be canonical JSON: {exc}"
            ) from exc
        if canonical != value:
            raise ValueError(
                f"{info.field_name} must be canonical JSON (sorted keys, compact "
                f"separators); got {value!r}"
            )
        return value

    @field_validator("parents")
    @classmethod
    def _check_parents(
        cls, value: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        if not value:
            raise ValueError(
                f"{info.field_name} must contain at least one parent artifact id"
            )
        for parent in value:
            _check_opaque_id(parent, field_name=info.field_name)
        return value

    @field_validator("warnings")
    @classmethod
    def _check_warnings(
        cls, value: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        return tuple(
            _strip_non_empty(item, field_name=info.field_name) for item in value
        )


class ArtifactDerivationLink(ValueModel):
    """Mapping from one derived artifact id to the operation that produced it."""

    artifact_id: str
    operation_id: str

    @field_validator("artifact_id", "operation_id")
    @classmethod
    def _check_ids(cls, value: str, info: ValidationInfo) -> str:
        return _check_opaque_id(value, field_name=info.field_name)


def _require_unique(values: tuple[str, ...], *, field_name: str, label: str) -> None:
    seen: dict[str, int] = {}
    for index, value in enumerate(values):
        if value in seen:
            raise ValueError(
                f"{field_name} must have unique {label} values; {value!r} appears "
                f"at indexes {seen[value]} and {index}"
            )
        seen[value] = index


class ArtifactGraph(ValueModel):
    """Normalized provenance DAG: operations, derivation links and roots.

    Enforces the Phase-3 subset of the §8.2 invariants: unique operation ids,
    unique derived artifact ids, duplicate-free roots, one link per derived
    artifact, every link pointing at an existing operation, no root/derived
    overlap, and every parent resolving through ``derivations`` or exactly once
    in ``root_artifacts`` (no dangling reference). Cycle detection and the
    bundle-wide artifact scan are Phase 7.
    """

    operations: tuple[OperationRecord, ...] = ()
    derivations: tuple[ArtifactDerivationLink, ...] = ()
    root_artifacts: tuple[str, ...] = ()

    @field_validator("root_artifacts")
    @classmethod
    def _check_root_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for artifact_id in value:
            _check_opaque_id(artifact_id, field_name="root_artifacts")
        return value

    @model_validator(mode="after")
    def _check_dag(self) -> ArtifactGraph:
        operation_ids = tuple(operation.operation_id for operation in self.operations)
        derived_ids = tuple(link.artifact_id for link in self.derivations)
        _require_unique(operation_ids, field_name="operations", label="operation_id")
        _require_unique(derived_ids, field_name="derivations", label="artifact_id")
        _require_unique(
            self.root_artifacts, field_name="root_artifacts", label="artifact id"
        )

        known_operations = set(operation_ids)
        for index, link in enumerate(self.derivations):
            if link.operation_id not in known_operations:
                raise ValueError(
                    f"derivations[{index}] references unknown operation "
                    f"{link.operation_id!r}"
                )

        root_ids = set(self.root_artifacts)
        overlap = root_ids & set(derived_ids)
        if overlap:
            offender = min(overlap)
            raise ValueError(
                "an artifact cannot be both a root and a derived artifact; "
                f"{offender!r} is in both"
            )

        resolvable = root_ids | set(derived_ids)
        for index, operation in enumerate(self.operations):
            for parent in operation.parents:
                if parent not in resolvable:
                    raise ValueError(
                        f"operations[{index}] ({operation.operation_id!r}) has "
                        f"unresolved parent {parent!r}; a parent must be a derived "
                        "artifact or a root artifact"
                    )
        return self


class ChannelBundle(ArrayModel):
    """Canonical per-channel processing state: one artifact plus its DAG."""

    artifact: ChannelArtifact
    graph: ArtifactGraph

    @model_validator(mode="after")
    def _check_artifact_resolves(self) -> ChannelBundle:
        artifact_id = self.artifact.artifact_id
        derived = {link.artifact_id for link in self.graph.derivations}
        if artifact_id not in derived and artifact_id not in set(
            self.graph.root_artifacts
        ):
            raise ValueError(
                f"bundle artifact {artifact_id!r} does not resolve in the graph "
                "(it is neither a root artifact nor a derived artifact)"
            )
        return self


def register_root_artifact(graph: ArtifactGraph, artifact_id: str) -> ArtifactGraph:
    """Return a NEW graph with ``artifact_id`` registered as a root artifact.

    Pure and atomic: the input graph is untouched and a rejected id (duplicate
    root or root/derived overlap) adds nothing.

    Args:
        graph: the graph to extend.
        artifact_id: a source/external artifact id with no operation mapping.

    Returns:
        A new validated :class:`ArtifactGraph`.

    Raises:
        pydantic.ValidationError: when the id is already a root or is derived.
    """
    return ArtifactGraph(
        operations=graph.operations,
        derivations=graph.derivations,
        root_artifacts=(*graph.root_artifacts, artifact_id),
    )


def insert_operation(
    graph: ArtifactGraph,
    operation: OperationRecord,
    *,
    artifact_id: str,
) -> ArtifactGraph:
    """Return a NEW graph with ``operation`` and its single derivation link added.

    Pure and atomic (plan §8.3): the input graph is never mutated and a failed
    insert (duplicate operation/artifact id, unresolved parent) raises while
    leaving the input untouched — the replacement graph is validated whole by
    :class:`ArtifactGraph`, so there is no partial update.

    Args:
        graph: the graph to extend.
        operation: the operation node to append.
        artifact_id: the *derived* artifact id the operation produced.

    Returns:
        A new validated :class:`ArtifactGraph`.

    Raises:
        pydantic.ValidationError: when an invariant of the extended DAG fails.
    """
    return ArtifactGraph(
        operations=(*graph.operations, operation),
        derivations=(
            *graph.derivations,
            ArtifactDerivationLink(
                artifact_id=artifact_id, operation_id=operation.operation_id
            ),
        ),
        root_artifacts=graph.root_artifacts,
    )


def source_bundle(artifact: ChannelArtifact) -> ChannelBundle:
    """Wrap a SOURCE artifact in a closed one-node bundle (root registration).

    Args:
        artifact: a source artifact whose id was content-derived.

    Returns:
        A :class:`ChannelBundle` whose graph registers the artifact as a root.
    """
    return ChannelBundle(
        artifact=artifact,
        graph=register_root_artifact(ArtifactGraph(), artifact.artifact_id),
    )


def operation_id_for(
    kind: str,
    schema_version: int,
    params_json: str,
    implementation: ImplementationRef,
    parents: tuple[str, ...],
) -> str:
    """Return the deterministic operation id (plan §8.2).

    Hashes the canonical JSON of kind, schema version, resolved params,
    implementation and the ORDERED parents. Wall clock, path and object address
    never participate, so equal inputs produce equal ids and a parent reorder
    produces a different one.

    Args:
        kind: stable operation verb, e.g. ``"filter.median"``.
        schema_version: registered operation schema version (``>= 1``).
        params_json: canonical JSON object of resolved parameters.
        implementation: which build of the operation ran.
        parents: ordered parent artifact ids.

    Returns:
        A lower-case ``sha256:<64 hex>`` id.
    """
    try:
        params: Any = json.loads(params_json)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"params_json must be canonical JSON: {exc}") from exc
    return stable_id(
        {
            "kind": kind,
            "schema_version": schema_version,
            "params": params,
            "implementation": implementation.model_dump(mode="json"),
            "parents": list(parents),
        }
    )
