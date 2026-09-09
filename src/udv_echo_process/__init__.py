"""UDV echo/velocity processing package.

Public API is re-exported here for convenient imports::

    from udv_echo_process import extract, ExtractedData, plot_all, rpm_from_echo
"""

from __future__ import annotations

from udv_echo_process.analysis import (
    RpmResult,
    mean_sample_interval_s,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)

# `load` reads any supported measurement (today: .BDD) into a MultiplexedMeasurement.
from udv_echo_process.io import load
from udv_echo_process.models import (
    ChannelConfig,
    ChannelSeries,
    MultiplexedMeasurement,
    SourceFormat,
    SourceSpec,
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
    FilterMethod,
    FilterParams,
    FilterSpec,
    InterpMethod,
    InterpParams,
    InterpSpec,
    filter,
    filter_sequence,
    resample,
)
from udv_echo_process.viz import (
    discover_data_files,
    plot_all,
    plot_channel_stats,
    plot_recording,
)

__all__ = [
    "ChannelConfig",
    "ChannelFrame",
    "ChannelSeries",
    "ExtractedData",
    "FilterMethod",
    "FilterParams",
    "FilterSpec",
    "InterpMethod",
    "InterpParams",
    "InterpSpec",
    "MeasType",
    "MultiplexedMeasurement",
    "RpmResult",
    "SourceFormat",
    "SourceSpec",
    "discover_data_files",
    "extract",
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
]
