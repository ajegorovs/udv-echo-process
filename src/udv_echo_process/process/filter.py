"""Per-gate time filtering — the noise-suppression layer.

After the interpolation stage (``process/sync.py``) has placed a channel on a
uniform time grid, each gate's time series can be filtered along axis 0
(time). The first filter here is **total-variation (ROF) denoising**, which
suppresses noise while preserving sharp jumps — the property a travelling
echo peak or a step in velocity needs, and the thing ``mean``-type smoothing
would smear.

``denoise`` is a closed transform (``ChannelSeries -> ChannelSeries``, per
`docs/pipeline-conventions.md` §4): it returns a *new* series with the same
time grid and gates, so a *sequence of filters* is just applying it again (or
composing several ``FilterSpec``s in order). Nothing filtered is stored on the
model.

Assumption: the input is an **already-resampled, (near-)uniform series** —
``denoise`` is meant to follow ``resample`` in the pipeline. The TV operator
is defined over sample *indices* (assumed equal spacing), so filtering a raw,
gappy, multiplexed cadence in place would bridge its inter-visit gaps
incorrectly.

Algorithm: ROF denoising via ``skimage.restoration.denoise_tv_chambolle``
(the standard off-the-shelf total-variation solver) applied **per gate** as an
independent 1-D problem along time — never as a 2-D image, which would couple
neighbouring gates.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
from pydantic import Field
from skimage.restoration import denoise_tv_chambolle

from udv_echo_process.models.base import Model
from udv_echo_process.models.channel_series import ChannelSeries


class FilterMethod(str, Enum):
    """Fixed set of filter methods (never a bare ``str``).

    Only ``TV`` exists today; adding a method (``mean``, ``savgol``, …) is a
    new member + a branch in ``denoise``'s dispatch — the Enum is the switch
    the ``FilterSpec`` already keys on.
    """

    TV = "tv"


class FilterSpec(Model):
    """Parameters for denoising one ``ChannelSeries`` along time.

    Fields:
        method: the filter family (see ``FilterMethod``). Default TV.
        weight: TV regularization weight ``lambda`` (larger = smoother /
            more aggressive denoising, but can flatten real structure). This
            is **data-scale dependent** — it is a trade-off against the
            signal's own magnitude/range, so it must be tuned per recording
            (the notebook preview is the tool for that). Must be ``> 0``.
        iterations: max inner iterations for the Chambolle solver
            (``denoise_tv_chambolle``'s ``max_num_iter``). Raise it for very
            long series or strong weights; the solver also early-exits on its
            own ``eps`` convergence criterion.
    """

    method: FilterMethod = FilterMethod.TV
    weight: float = Field(
        default=1.0,
        gt=0,
        description="TV regularization weight (larger = smoother; data-scale dependent)",
    )
    iterations: int = Field(
        default=200,
        ge=1,
        description="max Chambolle solver iterations",
    )


def denoise(series: ChannelSeries, spec: FilterSpec) -> ChannelSeries:
    """Total-variation denoise each gate of ``series`` along time (axis 0).

    A pure transform: returns a *new* ``ChannelSeries`` on the *same* time
    grid/gates, whose ``values`` are the per-gate TV-denoised time series of
    the source. The input is never mutated; ``channel``, ``meas_type``,
    ``gate_depths_mm`` and a deep copy of ``config`` carry through.

    Each gate is filtered independently (per-gate 1-D, vectorization is over
    the gate loop) — TV never couples neighbouring gates.

    Args:
        series: an (ideally already-resampled, uniform-cadence) channel.
        spec: method + TV parameters.

    Returns:
        A new ``ChannelSeries`` with ``values`` denoised per gate.

    Raises:
        ValueError: on a source with fewer than two samples or any non-finite
            ``values`` (the filter has no NaN policy yet — reject up front,
            mirroring ``resample``'s ``error`` default).
    """
    _require_filterable(series)

    values = series.values
    filtered = np.empty_like(values, dtype=np.float64)
    for g in range(values.shape[1]):
        filtered[:, g] = denoise_tv_chambolle(
            values[:, g],
            weight=spec.weight,
            max_num_iter=spec.iterations,
        )

    return ChannelSeries(
        channel=series.channel,
        meas_type=series.meas_type,
        gate_depths_mm=list(series.gate_depths_mm),
        time_s=series.time_s,
        values=filtered,
        config=series.config.model_copy(deep=True),
    )


# ── helpers ──────────────────────────────────────────────────────────────


def _require_filterable(series: ChannelSeries) -> None:
    if series.time_count < 2:
        raise ValueError(
            f"denoise: channel {series.channel} has {series.time_count} "
            "sample(s); filtering needs at least two time samples"
        )
    if series.gate_count == 0:
        raise ValueError(f"denoise: channel {series.channel} has no gates")
    if not np.isfinite(series.values).all():
        n_bad = int(np.count_nonzero(~np.isfinite(series.values)))
        raise ValueError(
            f"denoise: channel {series.channel} values hold {n_bad} "
            "non-finite entr(y/ies); clean the source before filtering"
        )
