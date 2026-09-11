"""Shared Pydantic models — the authoritative type layer.

`models/` imports nothing from `io`/`process`/`analysis`/`viz`; everything else
imports `models`. This one-way rule is what keeps the layers swappable and the
import graph cycle-free (the key correctness constraint of the rebuild).
"""

from __future__ import annotations

from udv_echo_process.models.acquisition import AcquisitionIndex, AcquisitionMode
from udv_echo_process.models.base import ArrayModel, ValueModel
from udv_echo_process.models.channel_config import ChannelConfig
from udv_echo_process.models.identity import (
    AcquisitionRef,
    ChannelKey,
    SignalDescriptor,
    SignalQuantity,
    SourceAsset,
)
from udv_echo_process.models.io import MeasType, SourceFormat, SourceSpec
from udv_echo_process.models.recording import ProfileStatistics, Recording
from udv_echo_process.models.signal import (
    ChannelArtifact,
    SignalData,
    array_digest,
    artifacts_equal,
    derived_artifact_id,
    missing_signal,
    observed_signal,
    signals_equal,
    source_artifact,
    source_artifact_id,
)
from udv_echo_process.models.support import QualityFlag, SampleSupport, SupportKind

__all__ = [
    "AcquisitionIndex",
    "AcquisitionMode",
    "AcquisitionRef",
    "ArrayModel",
    "ChannelArtifact",
    "ChannelConfig",
    "ChannelKey",
    "MeasType",
    "ProfileStatistics",
    "QualityFlag",
    "Recording",
    "SampleSupport",
    "SignalData",
    "SignalDescriptor",
    "SignalQuantity",
    "SourceAsset",
    "SourceFormat",
    "SourceSpec",
    "SupportKind",
    "ValueModel",
    "array_digest",
    "artifacts_equal",
    "derived_artifact_id",
    "missing_signal",
    "observed_signal",
    "signals_equal",
    "source_artifact",
    "source_artifact_id",
]
