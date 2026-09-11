"""Terminal robust velocity-profile results (absorption plan §4, D1/D2/D5).

The retiring ``udv-analysis`` package produced robust velocity-versus-depth
profiles by fitting a clamped B-spline quantile envelope per depth gate and
reporting the in-envelope **median** and **unscaled median absolute deviation**
(its ``processing/profiles.py``). That is a terminal ``T -> U`` product here:
it drops samples and changes counts, so it adds no ``SignalData`` field, no
``QualityFlag`` and no provenance node (plan D2, D5), and it never mutates the
source artifact or graph.

Why the deviation is *not* an uncertainty
-----------------------------------------
``median_absolute_deviation_mm_s`` is the **unscaled** median absolute
deviation of the retained samples, ``median(|x - median(x)|)``. It estimates
the robust spread of the samples *inside* the envelope — an outlier-rejection
statistic — and is **not** a standard uncertainty, not the standard error of
the median, and not a confidence interval. The Gaussian-equivalent scaling
(``x 1.4826``) is deliberately left to the consumer: the absorbed contract
reports the raw robust deviation and pins which statistic it is in the literal
:attr:`RobustVelocityProfiles.deviation_definition`, so a later JSON/CSV/NPZ
export cannot silently relabel it as an uncertainty (plan §4).

Absorbed invariants (plan §4, §9)
---------------------------------
- the quantile fit is per **depth gate** — an independent 1-D fit over the
  state's profile axis — never across gates;
- in-envelope selection is **inclusive** on both bounds;
- a constant gate, or a disabled envelope, **bypasses** the fit entirely;
- an LP **solver failure is an error**, never synthetic coefficients;
- the fit is **deterministic**.

Deliberately not modelled here
------------------------------
- **Envelope arrays.** The fitted (and TV-smoothed) lower/upper envelope curves
  are an intermediate of the fit. The archived baseline does not persist them —
  its profile NPZ/CSV carry only median, unscaled MAD, retained/input counts
  and the depth axis — so no ``lower_envelope``/``upper_envelope`` field is
  added: a field with no archived reference could not be baseline-verified.
- **A diagnostics dict.** Retained/input counts plus the typed per-gate
  :class:`RobustGateStatus` are the replacement (plan D5).
- An ``opencv`` backend, a worker-count setting and a result cache are not
  absorbed (plan D1, §5): the 2-D TV-L1 solver stays private to this analysis
  chain and the per-gate evaluation is sequential and deterministic.

This module owns the immutable settings and result. Settings are
JSON-oriented; the result's arrays are owned in-memory ndarrays (the
JSON/CSV/NPZ export boundary is the remainder of Phase 2, plan D4).
"""

from __future__ import annotations

import math
import re
from enum import Enum
from typing import Literal

import numpy as np
from pydantic import Field, ValidationInfo, field_validator, model_validator

from udv_echo_process.models.base import ArrayModel, ValueModel, array_field
from udv_echo_process.models.identity import SignalDescriptor, SignalQuantity

#: Opaque artifact-id form: ``sha256:`` plus 64 lower-case hex characters.
_SHA256_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")


class RobustGateStatus(str, Enum):
    """Per-gate outcome of the robust profile step.

    The member *values* are the exact status strings the retiring package
    emitted, so an export can reproduce the archived vocabulary:

    ``unfiltered_or_constant``
        the envelope was disabled, or the gate's samples were constant, so the
        whole sample set was summarised directly;
    ``quantile_envelope``
        the fit retained at least ``settings.minimum_retained_fraction`` of the
        samples;
    ``sparse_quantile_envelope``
        the fit retained fewer samples than that minimum and the caller asked
        for a warning rather than an error (``fail_on_sparse_envelope=False``);
    ``empty_envelope``
        the fit retained no sample at all, so the median and deviation are
        ``NaN`` and the retained count is 0.
    """

    CONSTANT_OR_UNFILTERED = "unfiltered_or_constant"
    QUANTILE_ENVELOPE = "quantile_envelope"
    SPARSE_QUANTILE_ENVELOPE = "sparse_quantile_envelope"
    EMPTY_ENVELOPE = "empty_envelope"


class TvL1Settings(ValueModel):
    """Private 2-D TV-L1 primal-dual solver settings (plan D1).

    The solver minimises ``L1`` data fidelity plus ``regularization`` times the
    isotropic total variation of the depth x time field, with a forward-backward
    primal-dual iteration. Defaults mirror the values the retiring package
    documented as its ``[tv_filter]`` defaults, so ``TvL1Settings()`` reproduces
    the archived baseline runs.

    There is no ``method``/``backend`` field (the custom solver is the only one
    absorbed, plan D1), no ``enabled`` field (the caller's
    :attr:`RobustProfileSettings.apply_tv_filter` gates the step) and no
    ``opencv_lambda``. The iteration's stability condition
    ``primal_step * dual_step * 8 < 1`` is enforced *here*, so an unstable
    configuration is unconstructible instead of raising mid-solve — an
    intentional strengthening of the source, which validated it on entry to the
    solver.
    """

    regularization: float = 0.5
    max_iterations: int = 30
    tolerance: float = 0.0
    primal_step: float = 0.35
    dual_step: float = 0.35

    @field_validator("regularization", "primal_step", "dual_step")
    @classmethod
    def _check_positive_finite(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and positive, got {value!r}"
            )
        return float(value)

    @field_validator("tolerance")
    @classmethod
    def _check_tolerance(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and non-negative, got {value!r}"
            )
        return float(value)

    @field_validator("max_iterations")
    @classmethod
    def _check_max_iterations(cls, value: int) -> int:
        if value < 1:
            raise ValueError(f"max_iterations must be at least 1, got {value}")
        return int(value)

    @model_validator(mode="after")
    def _check_stability(self) -> TvL1Settings:
        if self.primal_step * self.dual_step * 8 >= 1:
            raise ValueError(
                "the primal-dual iteration is unstable unless "
                "primal_step * dual_step * 8 < 1, got "
                f"{self.primal_step * self.dual_step * 8!r}"
            )
        return self


class RobustProfileSettings(ValueModel):
    """Frozen parameters for one robust velocity-profile extraction run.

    Defaults mirror the retiring package's documented ``[profiles]`` and
    ``[tv_filter]`` defaults, so ``RobustProfileSettings()`` reproduces the
    archived baseline runs. The 2-D TV-L1 preprocessing settings are nested in
    :attr:`tv_l1` and gated by :attr:`apply_tv_filter`; the solver itself is
    private to this terminal chain (plan D1).

    Not absorbed from the source config: ``enabled`` (the caller decides whether
    to run the step), ``max_workers`` (per-gate evaluation is sequential and
    deterministic here), ``reuse_saved_results`` and the output/manifest cache
    (plan §5).
    """

    apply_tv_filter: bool = True
    tv_l1: TvL1Settings = Field(default_factory=TvL1Settings)
    use_quantile_envelope: bool = True
    lower_quantile: float = 0.05
    upper_quantile: float = 0.95
    knot_size_factor: float = 0.05
    spline_order: int = 3
    lp_methods: tuple[str, ...] = ("highs", "highs-ipm")
    envelope_control_values: int = 500
    envelope_tv_weight: float = 1.0
    minimum_retained_fraction: float = 0.50
    fail_on_sparse_envelope: bool = True

    @field_validator("lower_quantile", "upper_quantile")
    @classmethod
    def _check_quantile(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{info.field_name} must lie in [0, 1], got {value!r}")
        return float(value)

    @model_validator(mode="after")
    def _check_quantile_order(self) -> RobustProfileSettings:
        if not self.lower_quantile < self.upper_quantile:
            raise ValueError(
                "profile quantiles must satisfy lower_quantile < upper_quantile, "
                f"got {self.lower_quantile!r} and {self.upper_quantile!r}"
            )
        return self

    @field_validator("knot_size_factor")
    @classmethod
    def _check_knot_size_factor(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and positive, got {value!r}"
            )
        return float(value)

    @field_validator("envelope_tv_weight")
    @classmethod
    def _check_envelope_tv_weight(cls, value: float, info: ValidationInfo) -> float:
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(
                f"{info.field_name} must be finite and non-negative, got {value!r}"
            )
        return float(value)

    @field_validator("minimum_retained_fraction")
    @classmethod
    def _check_minimum_retained_fraction(
        cls, value: float, info: ValidationInfo
    ) -> float:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{info.field_name} must lie in [0, 1], got {value!r}")
        return float(value)

    @field_validator("spline_order")
    @classmethod
    def _check_spline_order(cls, value: int) -> int:
        if value < 0:
            raise ValueError(f"spline_order must be >= 0, got {value}")
        return int(value)

    @field_validator("envelope_control_values")
    @classmethod
    def _check_envelope_control_values(cls, value: int) -> int:
        if value < 2:
            raise ValueError(f"envelope_control_values must be >= 2, got {value}")
        return int(value)

    @field_validator("lp_methods")
    @classmethod
    def _check_lp_methods(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        methods = tuple(str(item).strip() for item in value)
        if not methods:
            raise ValueError("lp_methods must list at least one scipy linprog method")
        if len(set(methods)) != len(methods):
            raise ValueError(f"lp_methods must be unique, got {methods!r}")
        if any(not method for method in methods):
            raise ValueError(f"lp_methods entries must be non-empty, got {methods!r}")
        return methods


class RobustVelocityProfiles(ArrayModel):
    """Strict terminal result of one channel's robust velocity profiles.

    One row per **retained state**, in the detection's interval order, and one
    column per depth gate — the same ``(S, G)`` layout, field names and dtypes
    the archived baseline NPZ stores, so an archived replay can compare arrays
    directly (no reshuffling).

    Scalar/array fields
    -------------------
    ``settings``
        the parameters actually used;
    ``artifact_id`` / ``detection_artifact_id``
        the source channel artifact the payload was read from *and* the artifact
        the operating-state detection ran on. They must be the same id: the
        profiles are only meaningful for the detection's own recording, so a
        mismatched pair is unconstructible;
    ``descriptor``
        the channel's quantity/unit; must be axial velocity (mm/s);
    ``gate_count``
        the gate-axis length ``G`` the arrays must agree with;
    ``state_numbers``
        the retained state numbers, running ``1..S`` in interval order;
    ``median_velocity_mm_s``
        per state x gate median of the in-envelope samples, ``NaN`` for an
        empty envelope;
    ``median_absolute_deviation_mm_s``
        per state x gate **unscaled** median absolute deviation of those
        samples, ``NaN`` for an empty envelope — a robust spread statistic, not
        an uncertainty (see the module docstring);
    ``retained_sample_count`` / ``input_sample_count``
        the per (state, gate) in-envelope count and the per-state profile count
        it was drawn from (plan D5: rejection lives in these counts, never in
        ``SampleSupport`` or a new quality flag);
    ``gate_status``
        the typed per-gate :class:`RobustGateStatus`;
    ``deviation_definition``
        a literal naming the deviation statistic, so no consumer has to guess.
    """

    settings: RobustProfileSettings
    artifact_id: str
    detection_artifact_id: str
    descriptor: SignalDescriptor
    gate_count: int
    state_numbers: tuple[int, ...]
    median_velocity_mm_s: array_field(np.float64, rank=2)
    median_absolute_deviation_mm_s: array_field(np.float64, rank=2)
    retained_sample_count: array_field(np.int64, rank=2)
    input_sample_count: array_field(np.int64, rank=1)
    gate_status: tuple[tuple[RobustGateStatus, ...], ...]
    deviation_definition: Literal["unscaled_median_absolute_deviation"] = (
        "unscaled_median_absolute_deviation"
    )

    @field_validator("artifact_id", "detection_artifact_id")
    @classmethod
    def _check_artifact_id(cls, value: str, info: ValidationInfo) -> str:
        text = value.strip()
        if not _SHA256_ID_RE.fullmatch(text):
            raise ValueError(
                f"{info.field_name} must be an opaque lower-case "
                f"'sha256:<64 hex>' id, got {value!r}"
            )
        return text

    @model_validator(mode="after")
    def _check_invariants(self) -> RobustVelocityProfiles:
        if self.descriptor.quantity is not SignalQuantity.AXIAL_VELOCITY:
            raise ValueError(
                "robust velocity profiles are defined for an axial-velocity "
                f"channel, got {self.descriptor.quantity.value!r}"
            )
        if self.artifact_id != self.detection_artifact_id:
            raise ValueError(
                "artifact_id and detection_artifact_id must name the same "
                "source artifact (the profiles belong to the detection's own "
                f"channel), got {self.artifact_id!r} and "
                f"{self.detection_artifact_id!r}"
            )
        state_count = len(self.state_numbers)
        if state_count < 1:
            raise ValueError("state_numbers must list at least one retained state")
        expected_numbers = tuple(range(1, state_count + 1))
        if self.state_numbers != expected_numbers:
            raise ValueError(
                "state_numbers must run 1..N in retained-state order, got "
                f"{self.state_numbers!r}"
            )
        if self.gate_count < 1:
            raise ValueError(f"gate_count must be >= 1, got {self.gate_count}")
        if self.input_sample_count.shape != (state_count,):
            raise ValueError(
                f"input_sample_count must have shape ({state_count},), got "
                f"{self.input_sample_count.shape}"
            )
        if not (self.input_sample_count >= 1).all():
            raise ValueError(
                "every retained state must have at least one input profile, got "
                f"{self.input_sample_count.tolist()}"
            )
        expected_shape = (state_count, self.gate_count)
        for name in (
            "median_velocity_mm_s",
            "median_absolute_deviation_mm_s",
            "retained_sample_count",
        ):
            shape = getattr(self, name).shape
            if shape != expected_shape:
                raise ValueError(
                    f"{name} must have shape {expected_shape} "
                    "(state x gate), got {shape}"
                )
        if len(self.gate_status) != state_count:
            raise ValueError(
                f"gate_status must have {state_count} state rows, got "
                f"{len(self.gate_status)}"
            )
        short = [
            index
            for index, row in enumerate(self.gate_status)
            if len(row) != self.gate_count
        ]
        if short:
            raise ValueError(
                f"gate_status rows must have {self.gate_count} gates; rows "
                f"{short} do not"
            )
        self._check_status_semantics()
        return self

    def _status_mask(self, status: RobustGateStatus) -> np.ndarray:
        """Boolean ``(S, G)`` mask of the cells carrying ``status``."""
        return np.array(
            [[cell is status for cell in row] for row in self.gate_status],
            dtype=bool,
        )

    def _check_status_semantics(self) -> None:
        """Tie every per-gate status to the arrays and the settings."""
        median = self.median_velocity_mm_s
        deviation = self.median_absolute_deviation_mm_s
        retained = self.retained_sample_count
        inputs = np.repeat(self.input_sample_count[:, None], self.gate_count, axis=1)
        empty = self._status_mask(RobustGateStatus.EMPTY_ENVELOPE)
        constant = self._status_mask(RobustGateStatus.CONSTANT_OR_UNFILTERED)
        sparse = self._status_mask(RobustGateStatus.SPARSE_QUANTILE_ENVELOPE)
        envelope = self._status_mask(RobustGateStatus.QUANTILE_ENVELOPE)

        missing = np.isnan(median)
        if not np.array_equal(missing, np.isnan(deviation)):
            raise ValueError(
                "median_velocity_mm_s and median_absolute_deviation_mm_s must "
                "be NaN for exactly the same gates (an empty envelope has "
                "neither statistic), got NaNs at "
                f"{np.argwhere(missing).tolist()} and "
                f"{np.argwhere(np.isnan(deviation)).tolist()}"
            )
        if not np.array_equal(missing, empty):
            raise ValueError(
                "median_velocity_mm_s/median_absolute_deviation_mm_s must be "
                "NaN exactly for the empty_envelope gates, got NaNs at "
                f"{np.argwhere(missing).tolist()} for empty gates at "
                f"{np.argwhere(empty).tolist()}"
            )
        if not (retained >= 0).all():
            raise ValueError("retained_sample_count must be non-negative")
        if not np.array_equal(retained == 0, empty):
            raise ValueError(
                "retained_sample_count must be 0 exactly for the "
                "empty_envelope gates, got counts "
                f"{np.argwhere(retained == 0).tolist()} for empty gates at "
                f"{np.argwhere(empty).tolist()}"
            )
        if not (retained <= inputs).all():
            raise ValueError(
                "retained_sample_count must not exceed input_sample_count "
                "(the envelope can only drop samples)"
            )
        if not np.isfinite(median[~empty]).all():
            raise ValueError(
                "median_velocity_mm_s must be finite for every non-empty gate"
            )
        if not np.isfinite(deviation[~empty]).all():
            raise ValueError(
                "median_absolute_deviation_mm_s must be finite for every non-empty gate"
            )
        if not (deviation[~empty] >= 0.0).all():
            raise ValueError(
                "median_absolute_deviation_mm_s must be non-negative "
                "(it is an unscaled median absolute deviation)"
            )

        settings = self.settings
        if constant.any() and not np.array_equal(retained[constant], inputs[constant]):
            raise ValueError(
                "a constant_or_unfiltered gate bypasses the envelope, so it "
                "must retain every input sample"
            )
        if not settings.use_quantile_envelope and not constant.all():
            raise ValueError(
                "with use_quantile_envelope disabled every gate bypasses the "
                "fit and must report constant_or_unfiltered, got "
                f"{[status.value for row in self.gate_status for status in row]}"
            )
        fraction = retained / inputs
        minimum = settings.minimum_retained_fraction
        if sparse.any():
            if settings.fail_on_sparse_envelope:
                raise ValueError(
                    "sparse_quantile_envelope cannot appear while "
                    "fail_on_sparse_envelope is set: the producer raises "
                    "instead of returning a sparse gate"
                )
            if not (fraction[sparse] < minimum).all():
                raise ValueError(
                    "a sparse_quantile_envelope gate must retain fewer than "
                    f"minimum_retained_fraction ({minimum!r}) of its samples"
                )
        if envelope.any() and not (fraction[envelope] >= minimum).all():
            raise ValueError(
                "a quantile_envelope gate must retain at least "
                f"minimum_retained_fraction ({minimum!r}) of its samples"
            )


__all__ = [
    "RobustGateStatus",
    "RobustProfileSettings",
    "RobustVelocityProfiles",
    "TvL1Settings",
]
