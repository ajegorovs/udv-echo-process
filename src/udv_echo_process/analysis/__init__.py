"""Domain analysis tools, organized one module per UDV concern.

- ``rpm.py`` — rotor RPM estimation via FFT peak /2 (ported from
  ``references/wolfram/UDV_Data_Analysis_Echo.txt``): the legacy
  ``ExtractedData`` tuple entry point plus the artifact-model terminal
  ``rpm_from_channel(ChannelBundle) -> EchoRpmEstimate``.
- ``states.py`` — terminal operating-state detection for one axial-velocity
  channel (absorbed from the retiring ``udv-analysis`` package; plan §4).
- ``profiles.py`` — terminal robust median/unscaled-MAD velocity profiles for
  one axial-velocity channel, with the private 2-D TV-L1 preprocessing kept
  beside it in ``_tv_l1.py`` (absorbed from the same package; plan §4, D1).
- ``time_modes.py`` — terminal time-direction SVD (POD) of one channel's
  ``(profile, gate)`` field: the gate mode shapes, their temporal coefficients
  and the two scalings a figure needs. One channel at a time, no resampling and
  no cross-channel alignment (see the model module docstring for the limits).

The optical/camera ports (mixer, feature tracking, image/temporal
projections) were removed: their canonical, further-developed copies live in
the sibling ``python-image-processing-notebooks`` repo.
"""

from __future__ import annotations

from udv_echo_process.analysis.profiles import (
    RobustProfileEnvelopeError,
    RobustProfileInputError,
    RobustProfileSolverError,
    extract_robust_profiles,
)
from udv_echo_process.analysis.rpm import (
    EchoRpmInputError,
    RpmResult,
    mean_sample_interval_s,
    rpm_from_channel,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)
from udv_echo_process.analysis.states import (
    OperatingStateDetection,
    OperatingStateInterval,
    StateDetectionInputError,
    StateDetectionMode,
    StateDetectionSettings,
    detect_operating_states,
)
from udv_echo_process.analysis.time_modes import (
    TimeModesInputError,
    decompose_time_modes,
    gate_amplitudes,
    modes_for_variance_share,
)
from udv_echo_process.models.profiles import (
    RobustGateStatus,
    RobustProfileSettings,
    RobustVelocityProfiles,
    TvL1Settings,
)
from udv_echo_process.models.rpm import EchoRpmEstimate, EchoRpmSettings
from udv_echo_process.models.time_modes import TimeModes, TimeModesSettings

__all__ = [
    "EchoRpmEstimate",
    "EchoRpmInputError",
    "EchoRpmSettings",
    "OperatingStateDetection",
    "OperatingStateInterval",
    "RobustGateStatus",
    "RobustProfileEnvelopeError",
    "RobustProfileInputError",
    "RobustProfileSettings",
    "RobustProfileSolverError",
    "RobustVelocityProfiles",
    "RpmResult",
    "StateDetectionInputError",
    "StateDetectionMode",
    "StateDetectionSettings",
    "TimeModes",
    "TimeModesInputError",
    "TimeModesSettings",
    "TvL1Settings",
    "decompose_time_modes",
    "detect_operating_states",
    "extract_robust_profiles",
    "gate_amplitudes",
    "mean_sample_interval_s",
    "modes_for_variance_share",
    "rpm_from_channel",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
]
