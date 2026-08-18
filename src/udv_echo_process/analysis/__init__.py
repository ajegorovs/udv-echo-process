"""Analysis subpackage: one module per ported Wolfram feature.

- ``rpm.py`` — rotor RPM estimation via FFT peak /2 (ported from
  ``references/wolfram/UDV_Data_Analysis_Echo.txt``).
"""

from __future__ import annotations

from udv_echo_process.analysis.rpm import (
    RpmResult,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)

__all__ = ["RpmResult", "rpm_from_echo", "setpoint_rpm_from_stem"]
