"""Time-direction SVD (POD) of one channel's ``(profile, gate)`` velocity field.

Library home of the four-sensor notebook's *mode* view. The contract, the sign
convention, the mean-removal choice and every stated limit live with the result
model in :mod:`udv_echo_process.models.time_modes`; this module is the pure
arithmetic over an already-owned ``(profile, gate)`` matrix plus the two scaling
helpers a figure needs.

Three atomic edits:

- :func:`decompose_time_modes` — the decomposition itself;
- :func:`gate_amplitudes` — a mode's contribution at each gate, in signal units,
  so a mode profile is directly comparable with the mean profile the same field
  carries (``singular_values`` alone is a Frobenius norm over the whole field
  and is not a per-sample amplitude);
- :func:`modes_for_variance_share` — how many modes a stated share needs, either
  of the whole field or — with ``offset`` — of the part left after the leading
  modes a caller keeps as a term of their own (the stationary field, say).

No resampling, no cross-channel pooling and no time alignment: each channel is
decomposed from its own stored profiles (see the model module docstring).
"""

from __future__ import annotations

import math

import numpy as np

from udv_echo_process.models.time_modes import (
    TimeModes,
    TimeModeSignConvention,
    TimeModesSettings,
)

#: The sign rule :func:`decompose_time_modes` applies; pinned here as the single
#: literal the result carries, so a display convention cannot drift from the
#: orientation the arrays were actually flipped to.
SIGN_CONVENTION: TimeModeSignConvention = "max_abs_gate_positive"


class TimeModesInputError(ValueError):
    """The matrix cannot enter a time-direction decomposition."""


def decompose_time_modes(
    values: np.ndarray,
    *,
    unit: str,
    settings: TimeModesSettings | None = None,
) -> TimeModes:
    """Decompose one channel's ``(profile, gate)`` field along the time axis.

    ``values[i, g]`` is stored profile ``i`` at gate ``g`` — the heatmap's own
    matrix, transposed to rows-as-snapshots. Rows are treated as *stored*
    profiles: nothing is interpolated, shifted or resampled, and no time or
    depth axis is read, so the burst/visit structure of a multiplexed
    acquisition does not have to be regular for the decomposition to be exact.

    With ``settings.center`` (the default) each gate's time mean is removed
    first, so the modes are pure fluctuations about it. ``center=False`` factors
    the raw snapshot matrix instead and keeps the static part inside the
    decomposition — mode 1 is then the stationary direction and the modes after
    it are the perturbations about it (see the model module docstring for the
    measured relation between mode 1 and the time mean). Either way the per-gate
    time mean is reported in ``mean_profile``, so ``values - mean_profile`` is
    the anomaly the centred form decomposes.

    Every retained mode is oriented by :data:`SIGN_CONVENTION`: flipped until
    its largest-magnitude gate is positive. numpy's own sign is unspecified, so
    without this the same input could be reported with a mirrored mode.

    Args:
        values: the ``(profile, gate)`` field, e.g. ``ChannelArtifact.data.values``.
        unit: the signal unit the matrix carries (recorded on the result).
        settings: ``TimeModesSettings()`` keeps 3 modes of the centred field.

    Returns:
        The terminal :class:`~udv_echo_process.models.time_modes.TimeModes`.

    Raises:
        TypeError: ``settings`` is not a ``TimeModesSettings``.
        TimeModesInputError: the matrix is not 2-D, has fewer than 2 profiles or
            fewer than 1 gate, carries a non-finite entry, requests more modes
            than the matrix has, or holds no fluctuation at all to decompose
            (a field constant along time, which has no modes to report).
    """
    if settings is not None and not isinstance(settings, TimeModesSettings):
        raise TypeError(
            f"settings must be a TimeModesSettings, got {type(settings).__name__}"
        )
    config = TimeModesSettings() if settings is None else settings

    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2:
        raise TimeModesInputError(
            f"values must be a 2-D (profile, gate) matrix, got shape {array.shape}"
        )
    n_profiles, n_gates = array.shape
    if n_profiles < 2:
        raise TimeModesInputError(
            f"a time-direction decomposition needs at least 2 profiles, got "
            f"{n_profiles}"
        )
    if n_gates < 1:
        raise TimeModesInputError(
            f"a time-direction decomposition needs at least 1 gate, got {n_gates}"
        )
    if not np.isfinite(array).all():
        flat = int(np.flatnonzero(~np.isfinite(array).ravel())[0])
        time_index, gate_index = divmod(flat, n_gates)
        raise TimeModesInputError(
            f"values must be finite (no NaN/Infinity); profile {time_index}, "
            f"gate {gate_index} holds {array[time_index, gate_index]!r} — an "
            "invalid cell has no per-cell exclusion here, so repair or select "
            "a fully observed channel first"
        )

    max_modes = min(n_profiles, n_gates)
    if config.n_modes > max_modes:
        raise TimeModesInputError(
            f"settings.n_modes ({config.n_modes}) exceeds the {max_modes} modes "
            f"a {n_profiles} x {n_gates} matrix can carry"
        )

    mean_profile = array.mean(axis=0)
    field = array - mean_profile if config.center else array
    energy = float(np.sum(field * field))
    if energy <= 0.0:
        raise TimeModesInputError(
            "the field holds no fluctuation to decompose: every profile equals "
            f"the time mean at every gate (total fluctuation energy "
            f"{energy!r}); a constant-in-time channel has no modes"
        )

    coefficients, singular_values, modes = np.linalg.svd(field, full_matrices=False)
    retained = config.n_modes
    for mode_index in range(retained):
        peak = int(np.argmax(np.abs(modes[mode_index])))
        if modes[mode_index, peak] < 0.0:
            modes[mode_index] *= -1.0
            coefficients[:, mode_index] *= -1.0

    explained = (singular_values * singular_values) / energy
    return TimeModes(
        settings=config,
        unit=unit,
        sign_convention=SIGN_CONVENTION,
        n_profiles=n_profiles,
        n_gates=n_gates,
        max_modes=max_modes,
        mean_profile=mean_profile,
        singular_values=singular_values,
        explained_variance_ratio=explained,
        modes=modes[:retained],
        coefficients=coefficients[:, :retained],
        retained_variance_ratio=float(explained[:retained].sum()),
    )


def gate_amplitudes(modes: TimeModes) -> np.ndarray:
    """Return the retained modes' gate amplitudes in the signal unit.

    Entry ``[k, g]`` is the mode's signed contribution at gate ``g``, scaled so
    that its magnitude is the **root-mean-square over the profile axis** of that
    mode's fluctuation at that gate::

        amplitude[k, g] = singular_values[k] * modes[k, g] / sqrt(n_profiles)

    That is what makes a mode profile plottable and comparable with the field's
    own mean profile: summing its square over *every* available mode reproduces
    the gate's mean-square fluctuation (a Parseval identity, exact up to
    float64), and summing over only the retained modes gives the part of it they
    carry.

    The sign is the mode's own orientation (see
    :data:`SIGN_CONVENTION`); a negative amplitude is one direction of the
    fluctuation, not a defect.
    """
    scale = modes.singular_values[: modes.modes.shape[0]] / math.sqrt(modes.n_profiles)
    return np.ascontiguousarray(scale[:, None] * modes.modes)


def modes_for_variance_share(
    modes: TimeModes, share: float = 0.95, *, offset: int = 0
) -> int:
    """Return how many modes carry at least ``share`` of the energy considered.

    Counted in the reported order over the available modes, so the answer is
    "the cumulative **energy** share reaches this at mode *n*" — it says nothing
    about whether any of those modes is a coherent structure (see the model
    module docstring on reading the spectrum).

    ``offset`` is what separates two readings of the same spectrum, and it is
    the reason this helper is not just a ``cumsum``:

    - ``offset=0`` (default) — the plain field question: how many modes carry
      this share of the whole field.
    - ``offset=k`` — the *kept-separately* question: the first ``k`` modes are
      excluded from both sides (they are treated as a term of their own), and
      the returned count is **additional** modes carrying ``share`` of what is
      left. With an uncentred decomposition whose mode 1 is the stationary
      field, ``offset=1`` answers "how many perturbation modes are needed for
      90% of the non-stationary energy" — the stationary-plus-perturbation
      reading this library supports (see the model module docstring).

    Args:
        modes: any decomposition result.
        share: target cumulative share of the energy considered, in ``(0, 1]``.
        offset: how many leading modes are set aside, ``0 <= offset <
            max_modes``.

    Returns:
        The mode count, never more than the modes available after ``offset``.
    """
    if not math.isfinite(share) or not 0.0 < share <= 1.0:
        raise ValueError(f"share must be finite and lie in (0, 1], got {share!r}")
    if offset < 0 or offset >= modes.max_modes:
        raise ValueError(
            f"offset must lie in [0, {modes.max_modes}), got {offset!r}: it sets "
            "aside that many leading modes, so at least one must remain"
        )
    remaining = modes.explained_variance_ratio[offset:]
    cumulative = np.cumsum(remaining)
    target = share * float(remaining.sum())
    index = int(np.searchsorted(cumulative, target, side="left"))
    return min(index + 1, modes.max_modes - offset)


__all__ = [
    "SIGN_CONVENTION",
    "TimeModesInputError",
    "decompose_time_modes",
    "gate_amplitudes",
    "modes_for_variance_share",
]
