"""Analysis subpackage: one module per ported Wolfram feature.

- ``rpm.py`` — rotor RPM estimation via FFT peak /2 (ported from
  ``references/wolfram/UDV_Data_Analysis_Echo.txt``).
- ``temporal_projection.py`` — memory-bounded chunk-wise temporal Min / Max /
  Mean / StandardDeviation projections for single-channel images (ported from
  ``references/wolfram/TemporalProjections_v1.1.0.wl``).
"""

from __future__ import annotations

from udv_echo_process.analysis.rpm import (
    RpmResult,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)
from udv_echo_process.analysis.temporal_projection import (
    TemporalProjectionResult,
    temporal_projections,
)
from udv_echo_process.analysis.image_projection import (
    frame_paths,
    project_images,
    save_projections,
    select_frames,
)
from udv_echo_process.analysis.mixer import (
    crop_to_box,
    deflicker,
    enrich_particles,
    largest_component_box,
    normalize,
    particle_mask,
    scale_box,
    top_hat_enhanced,
    tone_map,
)
from udv_echo_process.analysis.feature_track import (
    plot_flow,
    track_grid_flow,
)

__all__ = [
    "RpmResult",
    "rpm_from_echo",
    "setpoint_rpm_from_stem",
    "TemporalProjectionResult",
    "temporal_projections",
    "frame_paths",
    "project_images",
    "save_projections",
    "select_frames",
    "crop_to_box",
    "deflicker",
    "enrich_particles",
    "largest_component_box",
    "normalize",
    "particle_mask",
    "scale_box",
    "top_hat_enhanced",
    "tone_map",
    "plot_flow",
    "track_grid_flow",
]
