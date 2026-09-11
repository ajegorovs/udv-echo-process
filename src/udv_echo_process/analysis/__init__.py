"""Domain analysis tools, organized one module per UDV concern.

- ``rpm.py`` — rotor RPM estimation via FFT peak /2 (ported from
  ``references/wolfram/UDV_Data_Analysis_Echo.txt``).
- ``states.py`` — terminal operating-state detection for one axial-velocity
  channel (absorbed from the retiring ``udv-analysis`` package; plan §4).

The optical/camera ports (mixer, feature tracking, image/temporal
projections) were removed: their canonical, further-developed copies live in
the sibling ``python-image-processing-notebooks`` repo.
"""

from __future__ import annotations

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

__all__ = [
    "OperatingStateDetection",
    "OperatingStateInterval",
    "RpmResult",
    "StateDetectionInputError",
    "StateDetectionMode",
    "StateDetectionSettings",
    "detect_operating_states",
    "mean_sample_interval_s",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
]
