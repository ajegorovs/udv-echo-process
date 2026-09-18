"""Unattended UDOP acquisition — the pure-logic core.

Four concerns, one module each:

- :mod:`~udv_echo_process.acquire.plan` — the sweep planning math (ladder,
  gate count, window depth, profile-vs-cap assertion);
- :mod:`~udv_echo_process.acquire.config` — the configuration value objects a
  sweep is described by (limits, parameter set, profile timing, record settings);
- :mod:`~udv_echo_process.acquire.log` — the experiment log: one JSONL record
  per point, requested vs read-back vs decoded, plus the size-signature guard;
- :mod:`~udv_echo_process.acquire.actuator` — the actuator interface the
  GUI-driving implementation satisfies, plus the ported binding tables and
  ordering rules (resolution before gates, safe overlay answer).

Nothing here imports ``pywinauto``, ``watchdog`` or ``PIL``, and nothing binds a
control id or a screen coordinate: the Windows dependency and the live bindings
belong to the implementation that satisfies
:class:`~udv_echo_process.acquire.actuator.Actuator`. Every rule encoded in this
package was verified on the running application first — the module docstrings
cite where.
"""

from __future__ import annotations

from udv_echo_process.acquire.actuator import (
    DIALOG_ONLY_PARAMETERS,
    NUMERIC_WRITE_RECIPE,
    OVERLAY_ANSWERS,
    PARAM_COLUMN_ORDER,
    PARAMETER_WRITE_ORDER,
    PRESS_HOLD_MS,
    STARTABLE_VIEWS,
    STORE_TIMEOUT_S,
    STRIP_BUTTON_ORDER,
    VIEW_TIMEOUT_S,
    Actuator,
    ChannelMode,
    DialogControl,
    OverlayKind,
    ParamRole,
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    ordered_writes,
    overlay_answer,
    press_index,
    strip_controls,
)
from udv_echo_process.acquire.config import (
    CHANNEL_ENV_VAR,
    DEFAULT_CHANNEL,
    DEFAULT_MAX_PROFILES_PER_BLOCK,
    MAX_CHANNEL,
    MIN_CHANNEL,
    RUNG_DIVISOR,
    AcquisitionLimits,
    ChannelSetting,
    ParameterSet,
    ProfileTiming,
    RecordSettings,
    channel_from_environment,
)
from udv_echo_process.acquire.log import (
    DecodedBlock,
    PointStatus,
    SizeSignature,
    SweepLogEntry,
    SweepLogHeader,
    SweepPointRecord,
    append_entry,
    point_names,
    point_records,
    read_entries,
    sweep_id_for,
)
from udv_echo_process.acquire.plan import (
    GATE_DRIFT_NOTE,
    SweepDefinition,
    SweepPoint,
    assert_window_fits,
    clamp_resolution,
    depth_mm,
    fits_depth_budget,
    gate_drift,
    gates_for_depth,
    max_usable_depth_mm,
    nearest_rung_index,
    plan_point,
    plan_sweep,
    profiles_for_duration,
    resolution_for_rung,
    rung_mm,
    window_fits,
)
from udv_echo_process.acquire.snapshot import (
    FIXED_FACT_FIELDS,
    CompilationIdentity,
    FactSource,
    InstrumentFact,
    InstrumentSnapshot,
    Provenance,
    declared,
    identity_digest,
    routed,
    unreadable,
)

__all__ = [
    "CHANNEL_ENV_VAR",
    "DEFAULT_CHANNEL",
    "DEFAULT_MAX_PROFILES_PER_BLOCK",
    "DIALOG_ONLY_PARAMETERS",
    "FIXED_FACT_FIELDS",
    "GATE_DRIFT_NOTE",
    "MAX_CHANNEL",
    "MIN_CHANNEL",
    "NUMERIC_WRITE_RECIPE",
    "OVERLAY_ANSWERS",
    "PARAMETER_WRITE_ORDER",
    "PARAM_COLUMN_ORDER",
    "PRESS_HOLD_MS",
    "RUNG_DIVISOR",
    "STARTABLE_VIEWS",
    "STORE_TIMEOUT_S",
    "STRIP_BUTTON_ORDER",
    "VIEW_TIMEOUT_S",
    "AcquisitionLimits",
    "Actuator",
    "ChannelMode",
    "ChannelSetting",
    "CompilationIdentity",
    "DecodedBlock",
    "DialogControl",
    "FactSource",
    "InstrumentFact",
    "InstrumentSnapshot",
    "OverlayKind",
    "ParamRole",
    "ParameterSet",
    "PointStatus",
    "ProfileTiming",
    "Provenance",
    "RecordSettings",
    "SizeSignature",
    "StripControl",
    "StripState",
    "StripView",
    "SweepDefinition",
    "SweepLogEntry",
    "SweepLogHeader",
    "SweepPoint",
    "SweepPointRecord",
    "append_entry",
    "assert_window_fits",
    "channel_from_environment",
    "clamp_resolution",
    "classify_strip_view",
    "declared",
    "depth_mm",
    "fits_depth_budget",
    "gate_drift",
    "gates_for_depth",
    "identity_digest",
    "max_usable_depth_mm",
    "nearest_rung_index",
    "ordered_writes",
    "overlay_answer",
    "plan_point",
    "plan_sweep",
    "point_names",
    "point_records",
    "press_index",
    "profiles_for_duration",
    "read_entries",
    "resolution_for_rung",
    "routed",
    "rung_mm",
    "strip_controls",
    "sweep_id_for",
    "unreadable",
    "window_fits",
]
