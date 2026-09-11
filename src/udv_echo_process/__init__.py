"""UDV echo/velocity processing package.

Public API is re-exported here for convenient imports::

    from udv_echo_process import extract, ExtractedData, plot_all, rpm_from_echo
"""

from __future__ import annotations

from udv_echo_process.analysis import (
    RobustGateStatus,
    RobustProfileEnvelopeError,
    RobustProfileInputError,
    RobustProfileSettings,
    RobustProfileSolverError,
    RobustVelocityProfiles,
    RpmResult,
    StateDetectionInputError,
    TvL1Settings,
    detect_operating_states,
    extract_robust_profiles,
    mean_sample_interval_s,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)

# `load` reads any supported measurement (today: .BDD) into an ArtifactBundle:
# a Recording plus the provenance graph that resolves all its channel artifacts.
from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionMode,
    ChannelConfig,
    OperatingStateDetection,
    OperatingStateInterval,
    ProfileStatistics,
    Recording,
    SourceFormat,
    SourceSpec,
    StateDetectionMode,
    StateDetectionSettings,
)
from udv_echo_process.parser import (
    ChannelFrame,
    ExtractedData,
    MeasType,
    extract,
    list_add_files,
    list_stat_add_files,
    load_all_data,
    parse_add_file,
    parse_comma_decimal,
    parse_stat_add_file,
)
from udv_echo_process.process import (
    BsplineInterpSpec,
    CubicInterpSpec,
    FilterSpec,
    InterpSpec,
    LinearInterpSpec,
    MeanFilterSpec,
    MedianFilterSpec,
    MonotoneInterpSpec,
    SavgolFilterSpec,
    SyncSpec,
    TvFilterSpec,
    derive_many,
    filter,
    filter_sequence,
    resample,
    synchronize,
)
from udv_echo_process.provenance import ArtifactBundle
from udv_echo_process.viz import (
    discover_data_files,
    plot_all,
    plot_channel_stats,
    plot_recording,
)

__all__ = [
    "AcquisitionMode",
    "ArtifactBundle",
    "BsplineInterpSpec",
    "ChannelConfig",
    "ChannelFrame",
    "CubicInterpSpec",
    "ExtractedData",
    "FilterSpec",
    "InterpSpec",
    "LinearInterpSpec",
    "MeanFilterSpec",
    "MeasType",
    "MedianFilterSpec",
    "MonotoneInterpSpec",
    "OperatingStateDetection",
    "OperatingStateInterval",
    "ProfileStatistics",
    "Recording",
    "RobustGateStatus",
    "RobustProfileEnvelopeError",
    "RobustProfileInputError",
    "RobustProfileSettings",
    "RobustProfileSolverError",
    "RobustVelocityProfiles",
    "RpmResult",
    "SavgolFilterSpec",
    "SourceFormat",
    "SourceSpec",
    "StateDetectionInputError",
    "StateDetectionMode",
    "StateDetectionSettings",
    "SyncSpec",
    "TvFilterSpec",
    "TvL1Settings",
    "derive_many",
    "detect_operating_states",
    "discover_data_files",
    "extract",
    "extract_robust_profiles",
    "filter",
    "filter_sequence",
    "list_add_files",
    "list_stat_add_files",
    "load",
    "load_all_data",
    "mean_sample_interval_s",
    "parse_add_file",
    "parse_comma_decimal",
    "parse_stat_add_file",
    "plot_all",
    "plot_channel_stats",
    "plot_recording",
    "resample",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
    "synchronize",
]
