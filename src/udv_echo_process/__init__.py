"""UDV echo/velocity processing package.

Public API is re-exported here for convenient imports::

    from udv_echo_process import extract, ExtractedData, plot_all, rpm_from_echo
"""

from __future__ import annotations

from udv_echo_process.analysis import (
    RpmResult,
    rpm_from_echo,
    setpoint_rpm_from_stem,
    TemporalProjectionResult,
    temporal_projections,
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
from udv_echo_process.viz import (
    plot_all,
    plot_channel_stats,
    plot_recording,
)

__all__ = [
    "ChannelFrame",
    "ExtractedData",
    "MeasType",
    "RpmResult",
    "TemporalProjectionResult",
    "extract",
    "list_add_files",
    "list_stat_add_files",
    "load_all_data",
    "parse_add_file",
    "parse_comma_decimal",
    "parse_stat_add_file",
    "plot_all",
    "plot_channel_stats",
    "plot_recording",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
    "temporal_projections",
]
