"""Domain analysis tools, organized one module per UDV concern.

- ``rpm.py`` — rotor RPM estimation via FFT peak /2 (ported from
  ``references/wolfram/UDV_Data_Analysis_Echo.txt``).
- ``states.py`` — terminal operating-state detection for one axial-velocity
  channel (absorbed from the retiring ``udv-analysis`` package; plan §4).
- ``profiles.py`` — terminal robust median/unscaled-MAD velocity profiles for
  one axial-velocity channel, with the private 2-D TV-L1 preprocessing kept
  beside it in ``_tv_l1.py`` (absorbed from the same package; plan §4, D1).

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
    RpmResult,
    mean_sample_interval_s,
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
from udv_echo_process.models.profiles import (
    RobustGateStatus,
    RobustProfileSettings,
    RobustVelocityProfiles,
    TvL1Settings,
)

__all__ = [
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
    "TvL1Settings",
    "detect_operating_states",
    "extract_robust_profiles",
    "mean_sample_interval_s",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
]
