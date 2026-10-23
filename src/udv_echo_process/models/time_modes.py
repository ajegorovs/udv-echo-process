"""Terminal time-direction SVD (POD) of one channel's ``(profile, gate)`` field.

The decomposition answers *"which depth structures does this heatmap vary
through?"*: the field is read as a snapshot matrix ``X`` of shape
``(n_profiles, n_gates)`` — one stored profile per row, exactly as the heatmap
draws it — and factored as

    X - mean = U @ diag(singular_values) @ Vt

so that ``modes[k]`` is the unit-norm **gate** shape of mode ``k`` (the
"velocity vs gate" profile the caller asked for), ``coefficients[:, k]`` is its
unit-norm temporal coefficient, and ``explained_variance_ratio[k]`` is the share
of the field's fluctuation energy it carries.

Four contract points this module owns:

- **Only ``X`` is decomposed; the time axis is never touched.** The DOP
  acquisition is multiplexed — a channel is visited in bursts of ~4 profiles at
  ~25 ms with a ~372 ms gap between visits — so the profile axis is not uniform.
  The SVD itself needs no uniform axis (rows are stored profiles that really
  exist), and nothing here resamples, interpolates or shifts anything. What the
  burst structure *does* affect is the weighting of the ensemble: the marginal
  profiles of a visit are near-duplicates, so the decomposition is vetted by the
  visit pattern as well as by the flow. That is a stated limit of the reading,
  not a hidden defect, and it is why a temporal coefficient must not be
  read as a spectrum.
- **One channel at a time.** The four probes of the 2x2 mounting are never
  sampled at the same instant (~112 ms apart in the visit order), so a joint
  decomposition across channels would first require the alignment decision this
  analysis deliberately does not make. Decomposing each channel independently
  involves no alignment at all; comparing the resulting mode *shapes* needs only
  the shared gate grid.
- **The mean is a setting, and the two readings answer different questions.**
  ``center=False`` factors the raw snapshot matrix: mode 1 is then the
  **stationary** direction — measured on the committed four-sensor fixture it is
  the time-mean profile (r = +0.9992…+0.9999, and 99.9-100% of the mean field's
  energy lies inside it) — and modes 2+ are the perturbations about it, measured
  to be essentially orthogonal to that mean (|cos| <= 0.018 on the same fixture),
  so they are secondary effects rather than a repeat of the stationary part.
  That is the reading the four-sensor notebook presents, on the owner's stated
  rig behaviour (a stationary flow carrying perturbations). ``center=True`` (the
  default) removes each gate's time mean first and reports it in
  :attr:`TimeModes.mean_profile`, so the modes are pure fluctuations — the
  classical POD/anomaly form, and the right one when the *variation about* a
  mean is the question. One matrix supports both; the caller states which, and
  the result records the setting it was built with.
- **The sign is a convention, not a measurement.** numpy's SVD sign is
  unspecified, so every retained mode is oriented by one stated rule
  (:data:`TimeModeSignConvention`). Relative signs *within* one channel's
  decomposition are then meaningful; across channels they are not, because the
  mounts' sign convention is not decoded.

Deliberately not modelled here: mode count selection (the caller states how many
modes to keep), any statistical significance test for a mode, a temporal
spectrum of the coefficients, and any pooling across channels or recordings.
Only settings and scalars are JSON-oriented; the arrays are owned in-memory
ndarrays for the separate export boundary.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import ValidationInfo, field_validator, model_validator

from udv_echo_process.models.base import ArrayModel, ValueModel, array_field

#: The single sign rule a decomposition is reported with. numpy's ``svd`` sign is
#: unspecified (LAPACK-dependent), so every retained mode is flipped until its
#: largest-magnitude gate is positive. Deterministic for a given input, and it
#: keeps a mode's own shape readable; it does **not** make signs comparable
#: between channels or mounts.
TimeModeSignConvention = Literal["max_abs_gate_positive"]

#: Round-off tolerance for the orthonormality and share identities below. The
#: orthogonal entries are compared against an exact zero, so a relative
#: tolerance alone would be vacuous for them: the absolute floor carries it.
_ORTHONORMAL_RTOL = 1e-8
_ORTHONORMAL_ATOL = 1e-10

#: Round-off tolerance for the explained-variance sum (a float64 identity).
_SHARE_ATOL = 1e-9


class TimeModesSettings(ValueModel):
    """Frozen parameters for one time-direction decomposition.

    ``n_modes``
        how many modes to retain as profiles/coefficients. All singular values
        and shares are always reported for every available mode (``max_modes``
        = ``min(n_profiles, n_gates)``), so a small retained count costs no
        information about the spectrum; it is bounded by ``max_modes`` and
        refused above it rather than silently truncated.
    ``center``
        subtract each gate's time mean before factoring. ``True`` (the default)
        gives the classical anomaly/POD form: the modes are pure fluctuations
        and the removed mean is reported in ``mean_profile``. ``False`` keeps
        the mean and gives the stationary/perturbation reading — mode 1 is the
        stationary direction, modes 2+ the perturbations about it (see the
        module docstring; this is what the four-sensor notebook draws).
    """

    n_modes: int = 3
    center: bool = True

    @field_validator("n_modes")
    @classmethod
    def _check_n_modes(cls, value: int, info: ValidationInfo) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must be >= 1, got {value}")
        return int(value)


class TimeModes(ArrayModel):
    """Strict terminal result of one channel's time-direction decomposition.

    Shapes, with ``N`` profiles, ``G`` gates, ``K = min(N, G)`` available modes
    and ``R = settings.n_modes`` retained ones:

    ``mean_profile``            ``(G,)`` — the per-gate time mean, signal units.
                                          It is exactly the term ``center=True``
                                          removes (so ``values -
                                          mean_profile`` is the decomposed
                                          anomaly); with ``center=False`` it is
                                          reported too, as the field's static
                                          part, which mode 1 then reproduces
                                          (see the module docstring).
    ``singular_values``         ``(K,)`` — non-increasing, in signal units (a
                                          Frobenius norm over the whole field,
                                          not a per-sample amplitude)
    ``explained_variance_ratio````(K,)`` — non-negative, sums to 1
    ``modes``                   ``(R, G)`` — unit-norm gate shapes
    ``coefficients``            ``(N, R)`` — unit-norm temporal coefficients
    ``retained_variance_ratio`` scalar — the share the ``R`` modes carry

    ``unit`` is the signal unit the arrays carry (stated by the caller, so a
    downstream export cannot relabel a mm/s decomposition as something else) and
    ``sign_convention`` pins the orientation rule the modes were flipped to.
    """

    settings: TimeModesSettings
    unit: str
    sign_convention: TimeModeSignConvention
    n_profiles: int
    n_gates: int
    max_modes: int
    mean_profile: array_field(np.float64, rank=1)
    singular_values: array_field(np.float64, rank=1)
    explained_variance_ratio: array_field(np.float64, rank=1)
    modes: array_field(np.float64, rank=2)
    coefficients: array_field(np.float64, rank=2)
    retained_variance_ratio: float

    @field_validator("unit")
    @classmethod
    def _check_unit(cls, value: str, info: ValidationInfo) -> str:
        text = value.strip()
        if not text:
            raise ValueError(f"{info.field_name} must be a non-empty signal unit")
        return text

    @field_validator("n_profiles")
    @classmethod
    def _check_n_profiles(cls, value: int) -> int:
        if value < 2:
            raise ValueError(
                f"n_profiles must be >= 2 (a decomposition needs a spread of "
                f"profiles), got {value}"
            )
        return int(value)

    @field_validator("n_gates")
    @classmethod
    def _check_n_gates(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"n_gates must be >= 1, got {value}")
        return int(value)

    @field_validator("retained_variance_ratio")
    @classmethod
    def _check_retained(cls, value: float, info: ValidationInfo) -> float:
        # A full-basis retained share is a sum of float64 shares, so it can land
        # a couple of ulps above 1.0; the ceiling is round-off, not 1 + epsilon.
        if not math.isfinite(value) or not 0.0 < value <= 1.0 + _SHARE_ATOL:
            raise ValueError(
                f"{info.field_name} must be finite and lie in (0, 1] (within "
                f"{_SHARE_ATOL!r} of float64 round-off), got {value!r}"
            )
        return float(value)

    @model_validator(mode="after")
    def _check_invariants(self) -> TimeModes:
        expected_max = min(self.n_profiles, self.n_gates)
        if self.max_modes != expected_max:
            raise ValueError(
                f"max_modes must be min(n_profiles, n_gates) = {expected_max}, "
                f"got {self.max_modes}"
            )
        retained = self.settings.n_modes
        if retained > self.max_modes:
            raise ValueError(
                f"settings.n_modes ({retained}) must not exceed max_modes "
                f"({self.max_modes}): {self.n_profiles} profiles x "
                f"{self.n_gates} gates carry at most {self.max_modes} modes"
            )

        shapes = {
            "mean_profile": ((self.n_gates,), self.mean_profile),
            "singular_values": ((self.max_modes,), self.singular_values),
            "explained_variance_ratio": (
                (self.max_modes,),
                self.explained_variance_ratio,
            ),
            "modes": ((retained, self.n_gates), self.modes),
            "coefficients": ((self.n_profiles, retained), self.coefficients),
        }
        for name, (expected, array) in shapes.items():
            if array.shape != expected:
                raise ValueError(
                    f"{name} must have shape {expected}, got {array.shape}"
                )
            if not np.isfinite(array).all():
                index = int(np.flatnonzero(~np.isfinite(array).ravel())[0])
                raise ValueError(
                    f"{name} must be finite (no NaN/Infinity); flat index "
                    f"{index} has value {array.ravel()[index]}"
                )

        if (self.singular_values < 0.0).any():
            raise ValueError("singular_values must be non-negative")
        if (np.diff(self.singular_values) > 0.0).any():
            raise ValueError("singular_values must be non-increasing")
        if (self.explained_variance_ratio < 0.0).any():
            raise ValueError("explained_variance_ratio must be non-negative")
        if not math.isclose(
            float(self.explained_variance_ratio.sum()), 1.0, abs_tol=_SHARE_ATOL
        ):
            raise ValueError(
                "explained_variance_ratio must sum to 1 over every available "
                f"mode, got {float(self.explained_variance_ratio.sum())!r}"
            )

        gram = self.modes @ self.modes.T
        if not np.allclose(
            gram,
            np.eye(retained),
            rtol=_ORTHONORMAL_RTOL,
            atol=_ORTHONORMAL_ATOL,
        ):
            raise ValueError(
                "modes must be orthonormal rows (unit gate profiles); the Gram "
                f"matrix deviates from the identity by "
                f"{float(np.max(np.abs(gram - np.eye(retained))))!r}"
            )
        gram_t = self.coefficients.T @ self.coefficients
        if not np.allclose(
            gram_t,
            np.eye(retained),
            rtol=_ORTHONORMAL_RTOL,
            atol=_ORTHONORMAL_ATOL,
        ):
            raise ValueError(
                "coefficients must be orthonormal columns (unit temporal "
                "coefficients); the Gram matrix deviates from the identity by "
                f"{float(np.max(np.abs(gram_t - np.eye(retained))))!r}"
            )

        expected_retained = float(self.explained_variance_ratio[:retained].sum())
        if not math.isclose(
            self.retained_variance_ratio, expected_retained, abs_tol=_SHARE_ATOL
        ):
            raise ValueError(
                "retained_variance_ratio must equal the sum of the first "
                f"settings.n_modes shares ({expected_retained!r}), got "
                f"{self.retained_variance_ratio!r}"
            )

        peaks = [float(mode[int(np.argmax(np.abs(mode)))]) for mode in self.modes]
        if any(peak < 0.0 for peak in peaks):
            raise ValueError(
                f"modes must follow sign_convention={self.sign_convention!r} "
                "(every retained mode's largest-magnitude gate is positive); "
                f"got peaks {peaks!r}"
            )
        return self


__all__ = [
    "TimeModeSignConvention",
    "TimeModes",
    "TimeModesSettings",
]
