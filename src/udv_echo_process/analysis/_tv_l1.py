"""Private 2-D TV-L1 primal-dual preprocessing for the robust-profile chain.

**Private by decision (absorption plan D1).** The retiring ``udv-analysis``
package offered a 2-D (depth x time) total-variation filter with **L1** data
fidelity as a configurable preprocessing stage. Absorbing it as a public
``FilterSpec`` branch would change this repo's segment, edge and support
semantics for every consumer, so the solver is kept private to the *terminal
robust-profile analysis chain*: it is called only by
:func:`udv_echo_process.analysis.profiles.extract_robust_profiles`, it is not
exported, it registers no operation and it creates no provenance node. Should a
real gate-coupling use case appear, promoting it is a separate contract review.

Algorithm (faithful to the source's ``custom_tv_l1``)
-----------------------------------------------------
Minimise ``|u - f|_1 + regularization * TV_isotropic(u)`` on the
zero-to-one normalized field with a forward-backward primal-dual iteration:
dual ascent on the forward differences, projection of the dual pair onto the
``L1``-ball of radius ``regularization``, then explicit primal descent and a
proximal ``L1`` shrink against the observation.

The arithmetic deliberately stays in ``float32`` exactly as the source did,
including the transposed (depth x time) working orientation: the archived
baseline was produced by that code path, so the dtype and the operation order
are part of the absorbed algorithm, not an implementation detail. A constant
(zero-range) field returns a ``float64`` copy of the input unchanged, which is
the source's own shortcut. Non-finite or non-2-D input is refused rather than
propagated.

One documented deviation: the source's divergence boundary terms index the
second-to-last element of each axis, so a field with a **single profile** (or a
single gate) raised ``IndexError``. Those terms are identically zero on a
length-one axis (there are no gradients to accumulate), so the kernel guards
both axis blocks: a one-profile retained state is processed as a 1-D gate
regularization instead of crashing, and every result on an axis of length >= 2
is bit-identical to the source (the archived baseline replay proves it).

The iteration's stability condition (``primal_step * dual_step * 8 < 1``) is
enforced once, at :class:`~udv_echo_process.models.profiles.TvL1Settings`
construction, so it is unconstructible here rather than re-checked per call.
"""

from __future__ import annotations

import numpy as np

from udv_echo_process.models.profiles import TvL1Settings


def tv_l1_primal_dual(field_mm_s: np.ndarray, settings: TvL1Settings) -> np.ndarray:
    """Denoise one depth x time field with the private 2-D TV-L1 solver.

    Args:
        field_mm_s: the state's ``(T, G)`` velocity field in mm/s.
        settings: solver parameters; ``TvL1Settings()`` reproduces the archived
            baseline.

    Returns:
        A new ``(T, G)`` ``float64`` array. The input is never modified, and a
        zero-range field is returned as an exact copy.

    Raises:
        ValueError: the field is not a finite 2-D array.
    """
    source = np.asarray(field_mm_s, dtype=np.float32).T
    if source.ndim != 2 or not np.all(np.isfinite(source)):
        raise ValueError(
            f"the velocity field must be a finite 2-D array, got rank {source.ndim}"
        )
    source_minimum = float(np.min(source))
    source_range = float(np.ptp(source))
    if source_range <= 0:
        return np.array(field_mm_s, dtype=np.float64, order="C", copy=True)

    observed = (source - source_minimum) / source_range
    estimate = observed.copy()
    extrapolated = estimate.copy()
    dual_x = np.zeros_like(estimate)
    dual_y = np.zeros_like(estimate)
    for _ in range(settings.max_iterations):
        gradient_x = np.zeros_like(estimate)
        gradient_y = np.zeros_like(estimate)
        gradient_x[:, :-1] = extrapolated[:, 1:] - extrapolated[:, :-1]
        gradient_y[:-1, :] = extrapolated[1:, :] - extrapolated[:-1, :]
        dual_x += settings.dual_step * gradient_x
        dual_y += settings.dual_step * gradient_y
        magnitude = np.sqrt(dual_x * dual_x + dual_y * dual_y)
        scale = np.maximum(1.0, magnitude / settings.regularization)
        dual_x /= scale
        dual_y /= scale

        divergence = np.zeros_like(estimate)
        # A single-profile state has no time differences (and a single-gate
        # field no depth differences); the source's unguarded boundary terms
        # raised IndexError there. Both skipped terms are identically zero
        # because an axis of length one carries no gradients, so this guard is
        # a documented robustness deviation that changes no archival result.
        if estimate.shape[1] > 1:
            divergence[:, 0] += dual_x[:, 0]
            divergence[:, 1:-1] += dual_x[:, 1:-1] - dual_x[:, :-2]
            divergence[:, -1] -= dual_x[:, -2]
        if estimate.shape[0] > 1:
            divergence[0, :] += dual_y[0, :]
            divergence[1:-1, :] += dual_y[1:-1, :] - dual_y[:-2, :]
            divergence[-1, :] -= dual_y[-2, :]

        previous = estimate
        primal_input = estimate + settings.primal_step * divergence
        residual = primal_input - observed
        estimate = observed + np.sign(residual) * np.maximum(
            np.abs(residual) - settings.primal_step, 0.0
        )
        extrapolated = 2.0 * estimate - previous
        if settings.tolerance > 0:
            rms_change = float(np.sqrt(np.mean((estimate - previous) ** 2)))
            rms_level = float(np.sqrt(np.mean(previous * previous)))
            relative_change = rms_change / max(rms_level, np.finfo(np.float32).eps)
            if relative_change < settings.tolerance:
                break

    filtered = (np.clip(estimate, 0.0, 1.0) * source_range + source_minimum).T.astype(
        np.float64, copy=False
    )
    return filtered
