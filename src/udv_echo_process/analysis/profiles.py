"""Terminal robust velocity-versus-depth profiles for one velocity channel.

Absorbed from the retiring ``udv-analysis`` ``processing/profiles.py``
(absorption plan §4, decisions D1/D2/D5). The chain is **2-D TV-L1
preprocessing of the state's depth x time field -> a clamped B-spline quantile
envelope fitted independently per depth gate -> inclusive in-envelope
selection -> median and unscaled median-absolute-deviation per gate**. It is a
terminal ``T -> U`` producer here, not a ``ChannelBundle -> ChannelBundle``
transform: it drops samples and changes counts, so it adds no payload field, no
``QualityFlag``, no provenance node and no derived artifact, and it neither
mutates the source artifact nor touches its graph (plan D2, D5).

Input contract
--------------
The caller supplies the per-channel :class:`~udv_echo_process.provenance.
ChannelBundle` *and* the :class:`~udv_echo_process.models.states.
OperatingStateDetection` that was run on it. The two are cross-checked before
any arithmetic:

- the bundle artifact's ``artifact_id`` must equal the detection's
  ``artifact_id`` (the same source artifact — otherwise the intervals index a
  different recording);
- the descriptors must be equal and must measure
  :attr:`~udv_echo_process.models.identity.SignalQuantity.AXIAL_VELOCITY`
  (which fixes the unit at mm/s);
- the payload shape must match the detection's ``profile_count`` x
  ``gate_count``.

Only the detection's **retained** (``kept``) intervals enter the result; a
detection with no retained state is refused rather than silently returning an
empty result.

Invalid-sample policy (explicit, documented)
--------------------------------------------
``SignalData`` marks an unusable cell ``support.valid == False`` with a NaN
value, and the envelope fit is defined per gate over the state's finite samples
only — the source *refused* a non-finite field. This terminal step therefore
does the same: any invalid cell is refused with a
:class:`RobustProfileInputError` naming the count and first coordinate. It never
relabels support, never sets ``QualityFlag.EXCLUDED`` and never mutates the
artifact; the caller repairs or selects a fully observed channel first.

Absorbed invariants
-------------------
- the quantile fit is per **depth gate** and the envelope is TV-smoothed along
  the profile axis (the absorbed ``envelope_tv_weight``);
- selection is **inclusive** on both envelope bounds;
- a constant gate, or ``use_quantile_envelope=False``, bypasses the fit;
- an LP **solver failure is an error** — no synthetic coefficients;
- the result is **deterministic**: gates are evaluated sequentially, so no
  thread scheduling or cache state can reorder anything (the source's
  thread-pool width is deliberately not absorbed).

The private 2-D TV-L1 kernel lives in
:mod:`udv_echo_process.analysis._tv_l1` (plan D1) and the parameters are the
frozen :class:`~udv_echo_process.models.profiles.RobustProfileSettings`.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import BSpline, CubicSpline
from scipy.optimize import linprog
from scipy.sparse import eye as sparse_eye
from scipy.sparse import hstack as sparse_hstack
from skimage.restoration import denoise_tv_chambolle

from udv_echo_process.analysis._tv_l1 import tv_l1_primal_dual
from udv_echo_process.models.identity import SignalQuantity
from udv_echo_process.models.profiles import (
    RobustGateStatus,
    RobustProfileSettings,
    RobustVelocityProfiles,
)
from udv_echo_process.models.states import OperatingStateDetection
from udv_echo_process.provenance import ChannelBundle


class RobustProfileInputError(ValueError):
    """The inputs cannot enter robust velocity-profile extraction."""


class RobustProfileSolverError(RuntimeError):
    """The quantile LP failed; no synthetic coefficients are ever returned."""


class RobustProfileEnvelopeError(RuntimeError):
    """The quantile envelope retained fewer samples than configured."""


def _quantile_envelope_controls(
    sample_index: np.ndarray,
    normalized_samples: np.ndarray,
    control_index: np.ndarray,
    knot_count: int,
    probabilities: tuple[float, float],
    order: int,
    lp_methods: tuple[str, ...],
) -> tuple[np.ndarray, np.ndarray]:
    """Fit the two quantile curves with a clamped non-extrapolating B-spline LP.

    The clamped knot vector repeats its first and last knot ``order`` times, so
    the basis is a partition of unity with no extrapolation; the LP minimises
    the asymmetric (quantile) ``L1`` objective ``p * s+ + (1 - p) * s-`` subject
    to ``B c + s+ - s- = y``, and the fitted curve is evaluated at the
    (coarser) envelope control points — the absorbed non-extrapolating
    "corrected" fit, not a pointwise quantile.

    Args:
        sample_index: 1-based sample positions, shape ``(T,)``.
        normalized_samples: the gate's samples mapped into ``[0, 1]``.
        control_index: positions at which the fitted control values are
            evaluated, shape ``(C + 1,)``.
        knot_count: number of B-spline intervals.
        probabilities: the ``(lower, upper)`` quantile probabilities.
        order: B-spline order.
        lp_methods: scipy HiGHS method names, tried in order.

    Returns:
        The lower and upper control-value curves.

    Raises:
        RobustProfileSolverError: the B-spline basis is not a valid
            non-negative partition of unity, or every LP method failed.
    """
    base_knots = np.linspace(
        float(sample_index[0]), float(sample_index[-1]), int(knot_count) + 1
    )
    knot_vector = np.concatenate(
        (
            np.repeat(base_knots[0], order),
            base_knots,
            np.repeat(base_knots[-1], order),
        )
    )
    sample_basis = BSpline.design_matrix(
        sample_index, knot_vector, order, extrapolate=False
    ).tocsc()
    control_basis = BSpline.design_matrix(
        control_index, knot_vector, order, extrapolate=False
    ).tocsc()
    if sample_basis.data.size and (
        not np.all(np.isfinite(sample_basis.data))
        or float(np.min(sample_basis.data)) < -1e-12
    ):
        raise RobustProfileSolverError(
            "the corrected B-spline basis is invalid (non-finite or negative entries)"
        )
    if not np.allclose(
        np.asarray(sample_basis.sum(axis=1)).ravel(), 1.0, rtol=1e-10, atol=1e-10
    ):
        raise RobustProfileSolverError(
            "the corrected B-spline basis does not sum to one, so the "
            "quantile fit has no probabilistic meaning"
        )

    sample_count = sample_index.size
    basis_count = sample_basis.shape[1]
    equality_matrix = sparse_hstack(
        (
            sample_basis,
            sparse_eye(sample_count, format="csc"),
            -sparse_eye(sample_count, format="csc"),
        ),
        format="csc",
    )
    bounds = [(None, None)] * basis_count + [(0.0, None)] * (2 * sample_count)
    controls: list[np.ndarray] = []
    for probability in probabilities:
        objective = np.concatenate(
            (
                np.zeros(basis_count),
                np.full(sample_count, probability),
                np.full(sample_count, 1.0 - probability),
            )
        )
        result = None
        failures: list[str] = []
        for method in lp_methods:
            candidate = linprog(
                objective,
                A_eq=equality_matrix,
                b_eq=normalized_samples,
                bounds=bounds,
                method=method,
            )
            if candidate.success and candidate.x is not None:
                result = candidate
                break
            failures.append(
                f"{method}: status={candidate.status}, message={candidate.message}"
            )
        if result is None:
            raise RobustProfileSolverError(
                "the quantile LP failed for probability "
                f"{probability:g} and no synthetic coefficients are returned: "
                + " | ".join(failures)
            )
        controls.append(
            np.asarray(control_basis @ result.x[:basis_count], dtype=np.float64).ravel()
        )
    return controls[0], controls[1]


def _summarize_gate(
    samples: np.ndarray, settings: RobustProfileSettings
) -> tuple[float, float, int, RobustGateStatus]:
    """Summarize one gate's samples inside its quantile envelope.

    Returns ``(median, unscaled_mad, retained_count, status)``. The deviation is
    the **unscaled** median absolute deviation of the retained samples and is
    not an uncertainty (see
    :mod:`udv_echo_process.models.profiles`). An empty envelope returns
    ``(nan, nan, 0, EMPTY_ENVELOPE)``; a constant gate (or a disabled envelope)
    bypasses the fit and retains every sample.

    Raises:
        RobustProfileInputError: the samples are not a finite non-empty vector.
        RobustProfileSolverError: the quantile LP failed.
        RobustProfileEnvelopeError: fewer than
            ``settings.minimum_retained_fraction`` of the samples were retained
            and ``settings.fail_on_sparse_envelope`` is set.
    """
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or not np.all(np.isfinite(values)):
        raise RobustProfileInputError(
            "velocity-gate samples must be a finite non-empty vector, got "
            f"rank {values.ndim}, size {values.size}"
        )
    median_all = float(np.median(values))
    sample_range = float(np.ptp(values))
    if not settings.use_quantile_envelope or sample_range <= 1e-12:
        deviation = float(np.median(np.abs(values - median_all)))
        return (
            median_all,
            deviation,
            int(values.size),
            RobustGateStatus.CONSTANT_OR_UNFILTERED,
        )

    sample_index = np.arange(1, values.size + 1, dtype=np.float64)
    sample_minimum = float(np.min(values))
    normalized = (values - sample_minimum) / sample_range
    knot_count = max(1, int(np.floor(settings.knot_size_factor * values.size + 0.5)))
    control_index = np.linspace(
        sample_index[0], sample_index[-1], settings.envelope_control_values + 1
    )
    lower, upper = _quantile_envelope_controls(
        sample_index,
        normalized,
        control_index,
        knot_count,
        (settings.lower_quantile, settings.upper_quantile),
        settings.spline_order,
        settings.lp_methods,
    )
    lower = sample_minimum + sample_range * lower
    upper = sample_minimum + sample_range * upper
    if settings.envelope_tv_weight > 0:
        lower = denoise_tv_chambolle(
            lower, weight=settings.envelope_tv_weight, channel_axis=None
        )
        upper = denoise_tv_chambolle(
            upper, weight=settings.envelope_tv_weight, channel_axis=None
        )
    lower_at_samples = CubicSpline(control_index, lower)(sample_index)
    upper_at_samples = CubicSpline(control_index, upper)(sample_index)
    lower_at_samples, upper_at_samples = (
        np.minimum(lower_at_samples, upper_at_samples),
        np.maximum(lower_at_samples, upper_at_samples),
    )
    # Inclusive on both bounds, exactly as the source selected.
    retained = values[(values >= lower_at_samples) & (values <= upper_at_samples)]
    if retained.size == 0:
        return np.nan, np.nan, 0, RobustGateStatus.EMPTY_ENVELOPE

    retained_fraction = retained.size / values.size
    status = RobustGateStatus.QUANTILE_ENVELOPE
    if retained_fraction < settings.minimum_retained_fraction:
        message = (
            f"Quantile envelopes retained {retained.size}/{values.size} "
            f"samples ({retained_fraction:.1%}), below the configured "
            f"{settings.minimum_retained_fraction:.1%} minimum."
        )
        if settings.fail_on_sparse_envelope:
            raise RobustProfileEnvelopeError(message)
        status = RobustGateStatus.SPARSE_QUANTILE_ENVELOPE
    median = float(np.median(retained))
    deviation = float(np.median(np.abs(retained - median)))
    return median, deviation, int(retained.size), status


def extract_robust_profiles(
    bundle: ChannelBundle,
    detection: OperatingStateDetection,
    settings: RobustProfileSettings | None = None,
) -> RobustVelocityProfiles:
    """Extract robust median/unscaled-MAD profiles for every retained state.

    Terminal producer (absorption plan §4). Reads the channel bundle's
    ``(T, G)`` axial-velocity payload, slices the detection's retained states
    and summarizes each kept state x gate. The input bundle — its artifact,
    payload, support and provenance graph — is never modified, and no derived
    artifact or operation node is created.

    Args:
        bundle: the per-channel bundle (from ``select_channel``) to analyse.
        detection: the operating-state detection of *that same* artifact, whose
            retained intervals select the rows.
        settings: profile parameters; ``RobustProfileSettings()`` defaults
            reproduce the archived baseline.

    Returns:
        The validated terminal result, with owned read-only arrays.

    Raises:
        RobustProfileInputError: the inputs are not a ``ChannelBundle`` plus
            ``OperatingStateDetection``, the artifact ids / descriptors /
            dimensions disagree, the channel is not axial velocity, it carries
            an invalid ``SampleSupport`` cell, or it has no retained state.
        RobustProfileSolverError: the quantile LP failed for a gate.
        RobustProfileEnvelopeError: a gate fell below
            ``minimum_retained_fraction`` with ``fail_on_sparse_envelope`` set.
    """
    if not isinstance(bundle, ChannelBundle):
        raise TypeError(
            "extract_robust_profiles expects a ChannelBundle, got "
            f"{type(bundle).__name__}"
        )
    if not isinstance(detection, OperatingStateDetection):
        raise TypeError(
            "extract_robust_profiles expects the OperatingStateDetection of "
            f"the same channel, got {type(detection).__name__}"
        )
    config = RobustProfileSettings() if settings is None else settings
    if not isinstance(config, RobustProfileSettings):
        raise TypeError(
            f"settings must be a RobustProfileSettings, got {type(config).__name__}"
        )

    artifact = bundle.artifact
    data = artifact.data
    descriptor = artifact.descriptor
    if descriptor.quantity is not SignalQuantity.AXIAL_VELOCITY:
        raise RobustProfileInputError(
            "robust velocity profiles require an axial-velocity channel; "
            f"channel {artifact.acquisition.channel.device_channel} measures "
            f"{descriptor.quantity.value!r} ({descriptor.unit!r})"
        )
    if artifact.artifact_id != detection.artifact_id:
        raise RobustProfileInputError(
            "the detection was run on a different artifact than this bundle "
            f"({detection.artifact_id!r} vs {artifact.artifact_id!r}); the "
            "profile rows would index another recording's profiles"
        )
    if descriptor != detection.descriptor:
        raise RobustProfileInputError(
            "the bundle and the detection must describe the same channel: "
            f"descriptor {descriptor.model_dump()!r} vs "
            f"{detection.descriptor.model_dump()!r}"
        )

    values = data.values
    profile_count, gate_count = values.shape
    if profile_count != detection.profile_count:
        raise RobustProfileInputError(
            "the payload's profile axis must match the detection's "
            f"profile_count: payload has {profile_count}, detection has "
            f"{detection.profile_count}"
        )
    if gate_count != detection.gate_count:
        raise RobustProfileInputError(
            "the payload's gate axis must match the detection's gate_count: "
            f"payload has {gate_count}, detection has {detection.gate_count}"
        )

    invalid = ~data.support.valid
    if invalid.any():
        count = int(invalid.sum())
        flat = int(np.flatnonzero(invalid.ravel())[0])
        time_i, gate_i = divmod(flat, gate_count)
        noun = "cell" if count == 1 else "cells"
        raise RobustProfileInputError(
            "robust velocity profiles require a fully valid channel: "
            f"{count} invalid {noun}, first at (time={time_i}, gate={gate_i}); "
            "invalid SampleSupport has no per-cell exclusion in this terminal "
            "step, so repair or select a fully observed channel first (the "
            "source artifact is left unchanged; no QualityFlag is set)"
        )

    kept = [interval for interval in detection.intervals if interval.kept]
    if not kept:
        raise RobustProfileInputError(
            "the operating-state detection retained no state "
            f"(all {len(detection.intervals)} candidate spans were dropped by "
            "minimum_relative_duration), so there are no profiles to extract"
        )

    medians = np.full((len(kept), gate_count), np.nan, dtype=np.float64)
    deviations = np.full((len(kept), gate_count), np.nan, dtype=np.float64)
    retained_counts = np.zeros((len(kept), gate_count), dtype=np.int64)
    statuses: list[tuple[RobustGateStatus, ...]] = []
    for row, interval in enumerate(kept):
        field = values[interval.start_index : interval.stop_index_exclusive]
        if config.apply_tv_filter:
            field = tv_l1_primal_dual(field, config.tv_l1)
        else:
            field = np.asarray(field, dtype=np.float64)
        row_statuses: list[RobustGateStatus] = []
        for gate in range(gate_count):
            median, deviation, count, status = _summarize_gate(field[:, gate], config)
            medians[row, gate] = median
            deviations[row, gate] = deviation
            retained_counts[row, gate] = count
            row_statuses.append(status)
        statuses.append(tuple(row_statuses))

    return RobustVelocityProfiles(
        settings=config,
        artifact_id=artifact.artifact_id,
        detection_artifact_id=detection.artifact_id,
        descriptor=descriptor,
        gate_count=gate_count,
        state_numbers=tuple(interval.state_number for interval in kept),
        retained_intervals=tuple(kept),
        median_velocity_mm_s=medians,
        median_absolute_deviation_mm_s=deviations,
        retained_sample_count=retained_counts,
        input_sample_count=np.asarray(
            [interval.profile_count for interval in kept], dtype=np.int64
        ),
        gate_status=tuple(statuses),
    )


__all__ = [
    "RobustProfileEnvelopeError",
    "RobustProfileInputError",
    "RobustProfileSolverError",
    "extract_robust_profiles",
]
