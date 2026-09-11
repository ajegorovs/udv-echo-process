"""Normalized provenance for the UDV signal model (plan §8).

``ChannelBundle`` is the canonical per-channel processing state: one
``ChannelArtifact`` plus the closed ``ArtifactGraph`` that records how it was
produced. Public transforms are ``ChannelBundle -> ChannelBundle`` and every one
of them calls ``udv_echo_process.process.derive.derive`` — the single
constructor for transformed artifacts.
"""

from __future__ import annotations

from udv_echo_process.provenance.models import (
    ArtifactDerivationLink,
    ArtifactGraph,
    ChannelBundle,
    ImplementationRef,
    OperationRecord,
    current_revision,
    implementation_ref,
    insert_operation,
    installed_version,
    operation_id_for,
    register_root_artifact,
    source_bundle,
)

__all__ = [
    "ArtifactDerivationLink",
    "ArtifactGraph",
    "ChannelBundle",
    "ImplementationRef",
    "OperationRecord",
    "current_revision",
    "implementation_ref",
    "insert_operation",
    "installed_version",
    "operation_id_for",
    "register_root_artifact",
    "source_bundle",
]
