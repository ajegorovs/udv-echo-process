"""Analysis subpackage: one module per ported Wolfram feature.

- ``rpm.py`` — rotor RPM estimation via FFT peak /2 (ported from
  ``references/wolfram/UDV_Data_Analysis_Echo.txt``).

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

__all__ = [
    "RpmResult",
    "mean_sample_interval_s",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
]
