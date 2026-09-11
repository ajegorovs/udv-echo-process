"""Shared processing-segment helpers for the transform stages (plan §7.1, D4).

A gate's rows divide into *segments* wherever an invalid/missing cell sits or
where the time step exceeds the method's ``max_gap_s``. No window or
interpolator may cross a segment boundary, and index-based methods (SAVGOL,
TV) additionally require every processed segment to be truly uniform. This
module is the one private place that logic lives, so ``filter`` (and phase 5's
interpolators) cannot drift apart.

Everything here is private to ``udv_echo_process.process``: the module is not
re-exported, and its helpers carry a leading underscore.
"""

from __future__ import annotations

import numpy as np

#: Inclusive start, exclusive stop row range of one per-gate segment.
_Segment = tuple[int, int]


def _segment_rows(
    time_s: np.ndarray, valid: np.ndarray, max_gap_s: float
) -> list[_Segment]:
    """Split one gate's ``(T,)`` rows into time-contiguous valid segments.

    An invalid row closes the current segment (it is a boundary); two
    consecutive valid rows also start a new segment when their time step
    exceeds ``max_gap_s``. Returns ``(start, stop)`` pairs with ``stop``
    exclusive, in row order, covering exactly the maximal runs of valid rows
    no window may cross.

    Args:
        time_s: the ``(T,)`` strictly increasing per-row time coordinate.
        valid: the ``(T,)`` per-cell validity mask for this gate.
        max_gap_s: largest time gap a segment may span (a larger gap splits).

    Returns:
        A list of ``(start, stop)`` row ranges, ordered by ``start``.
    """
    segments: list[_Segment] = []
    start = -1
    n_rows = valid.shape[0]
    for row in range(n_rows):
        if not valid[row]:
            if start >= 0:
                segments.append((start, row))
                start = -1
            continue
        if start < 0:
            start = row
        elif time_s[row] - time_s[row - 1] > max_gap_s:
            segments.append((start, row))
            start = row
    if start >= 0:
        segments.append((start, n_rows))
    return segments


def _uniformity_error(
    dt: np.ndarray,
    *,
    method: str,
    channel: int,
    start: int,
    stop: int,
    uniform_rtol: float,
) -> ValueError:
    """Build the method/channel/segment-specific non-uniform-cadence error.

    Names the method, the segment row range, the median ``dt``, the worst
    ``dt`` and its row pair, and the configured tolerance (plan §11).
    """
    median_dt = float(np.median(dt))
    deviation = np.abs(dt - median_dt)
    worst = int(np.argmax(deviation))
    return ValueError(
        f"filter.{method}: channel {channel} segment rows [{start}, {stop}) is "
        f"not truly uniform: median dt={median_dt!r} s, worst dt="
        f"{float(dt[worst])!r} s (row {start + worst}->{start + worst + 1}), "
        f"uniform_rtol={uniform_rtol!r}"
    )


def _require_truly_uniform(
    time_s: np.ndarray,
    start: int,
    stop: int,
    *,
    method: str,
    channel: int,
    uniform_rtol: float,
) -> None:
    """Require every adjacent ``dt`` in ``[start, stop)`` to match the median.

    The rule is exactly plan §7.2: ``np.allclose(dt, median(dt),
    rtol=uniform_rtol, atol=0)`` over *all* adjacent intervals, including a
    shortened final one (the superseded special case is gone). A segment of
    fewer than three rows has fewer than two intervals and is trivially
    uniform.

    Raises:
        ValueError: when the segment is not truly uniform. Never skipped.
    """
    dt = np.diff(time_s[start:stop])
    if dt.size < 2:
        return
    if not np.allclose(dt, np.median(dt), rtol=uniform_rtol, atol=0):
        raise _uniformity_error(
            dt,
            method=method,
            channel=channel,
            start=start,
            stop=stop,
            uniform_rtol=uniform_rtol,
        )
