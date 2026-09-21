"""Sweep planning math for the depth sweep (ported, not re-derived).

Every equation here is a *verified* law from the recon project, kept in the shape
it was measured in:

- **``rung_mm(c) = c / 12000``** — the resolution ladder's rung, measured with a
  122-point scan: accepted pitches are exact multiples of the rung, snapping is
  *nearest rung*, and the ladder clamps at rung 120 = ``c / 100`` mm (docs/08
  §1). ``k`` in a plan is the **1-based rung index**, i.e. ``k = word10 + 1``:
  the validated points landed at rungs 0 and 1 for ``k = 1`` and ``k = 2``
  (docs/16 §14). The value written is a request — the achieved pitch is read
  back, because the app silently snaps.
- **``depth = first_gate + gates × resolution``** — the window law, verified
  twice against the app's own derived depth (docs/13 §1), with ``first_gate``
  read from the app (2 mm on the tested channel).
- **``gates = round((target_depth − first_gate) / resolution)``**, clamped to the
  accepted range 4..1000 (docs/08 §2). The app additionally clamps to what fits
  the unambiguous depth budget ``P_max = c × T_prf / 2`` — silently, so the
  count must be read back and this plan checks the budget up front to avoid a
  point that was trimmed without anyone noticing (docs/08 §3).
- **``profiles = T / period``** is *derived*, and must satisfy
  ``profiles <= block cap`` or the observation window silently shrinks: the
  block is a ring, so the stored file covers only the last ``cap × period``
  seconds while still decoding as valid (docs/16 §15b).
- **A clamped write is visible in the control text** — 805 requested read back
  as 474 in the wrong write order — so a pre-record read-back catches a clamped
  point without spending a recording or leaving a junk file behind (docs/16
  §14). :func:`gate_drift` is that check.

``plan_point`` / ``plan_sweep`` produce the plan the runner then writes, reads
back and stores; nothing here touches the GUI.
"""

from __future__ import annotations

import math

from pydantic import Field, field_validator, model_validator

from udv_echo_process.acquire.config import AcquisitionLimits, ParameterSet
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DEFAULT_LIMITS",
    "GATE_DRIFT_NOTE",
    "SweepDefinition",
    "SweepPoint",
    "assert_window_fits",
    "clamp_resolution",
    "depth_mm",
    "fits_depth_budget",
    "gate_drift",
    "gates_for_depth",
    "max_usable_depth_mm",
    "nearest_rung_index",
    "plan_point",
    "plan_sweep",
    "profiles_for_duration",
    "resolution_for_rung",
    "rung_mm",
    "window_fits",
]

#: The measured limits, shared so a plan and its callers cannot disagree.
DEFAULT_LIMITS = AcquisitionLimits()

#: A read-back gate count that moved by more than this fraction is reported.
#: The reference implementation printed its note at 5 % (docs/16 §14).
GATE_DRIFT_NOTE = 0.05


def rung_mm(
    sound_speed_ms: float, *, limits: AcquisitionLimits = DEFAULT_LIMITS
) -> float:
    """One resolution-ladder rung in mm: ``c / 12000`` (docs/08 §1)."""
    if sound_speed_ms <= 0:
        raise ValueError(f"sound_speed_ms must be > 0, got {sound_speed_ms}")
    return sound_speed_ms / limits.rung_divisor


def resolution_for_rung(
    index: int,
    sound_speed_ms: float,
    *,
    limits: AcquisitionLimits = DEFAULT_LIMITS,
) -> float:
    """Pitch of the 0-based ladder rung ``index``: ``(index + 1) × c / 12000``.

    This is also the **read-back** formula: word 10 of the stored block is the
    0-based rung index, so ``resolution_mm = (word10 + 1) × c / 12000`` (verified
    at ``4 -> 0.6083`` for c = 1460 and ``1 -> 0.250`` for c = 1500, docs/16
    §12a). Raising outside ``0..max_rung_index`` keeps the ladder finite: the
    app clamps above it rather than honouring the request.
    """
    if not 0 <= index <= limits.max_rung_index:
        raise ValueError(
            f"rung index must be within 0..{limits.max_rung_index}, got {index}"
        )
    return (index + 1) * rung_mm(sound_speed_ms, limits=limits)


def nearest_rung_index(
    resolution_mm: float,
    sound_speed_ms: float,
    *,
    limits: AcquisitionLimits = DEFAULT_LIMITS,
) -> int:
    """Index of the rung the app would snap ``resolution_mm`` to.

    Nearest rung, measured at every arithmetic midpoint (docs/08 §1), and
    clamped to the ladder ends (0.05 mm comes back as rung 0, 20 mm as rung 119
    at c = 1500). Exact midpoints are the one case the scan did not settle, so
    the tie follows Python's round-half-even rather than an assumed rule.
    """
    if resolution_mm <= 0:
        raise ValueError(f"resolution_mm must be > 0, got {resolution_mm}")
    rung = rung_mm(sound_speed_ms, limits=limits)
    index = round(resolution_mm / rung) - 1
    return max(0, min(limits.max_rung_index, index))


def clamp_resolution(
    resolution_mm: float,
    sound_speed_ms: float,
    *,
    limits: AcquisitionLimits = DEFAULT_LIMITS,
) -> float:
    """The rung value the app would accept for ``resolution_mm``."""
    index = nearest_rung_index(resolution_mm, sound_speed_ms, limits=limits)
    return resolution_for_rung(index, sound_speed_ms, limits=limits)


def gates_for_depth(
    target_depth_mm: float,
    first_gate_mm: float,
    resolution_mm: float,
    *,
    limits: AcquisitionLimits = DEFAULT_LIMITS,
) -> int:
    """Gate count reaching ``target_depth_mm`` at ``resolution_mm``, clamped.

    ``round((target - first_gate) / resolution)`` then clamped to
    ``limits.min_gates..limits.max_gates`` (4..1000 measured, docs/08 §2). The
    app may still clamp further against the depth budget, so the value written is
    read back and the stored file is the authority.
    """
    if resolution_mm <= 0:
        raise ValueError(f"resolution_mm must be > 0, got {resolution_mm}")
    span = target_depth_mm - first_gate_mm
    if span <= 0:
        raise ValueError(
            f"target_depth_mm ({target_depth_mm}) must exceed "
            f"first_gate_mm ({first_gate_mm})"
        )
    return limits.clamp_gates(round(span / resolution_mm))


def depth_mm(first_gate_mm: float, gates: int, resolution_mm: float) -> float:
    """The window law the planning layer applies: ``first_gate + gates × resolution`` (docs/13 §1).

    What the *stored file* carries is a different quantity and is measured: word 2 follows
    ``first_gate + (gates - 1) × pitch`` — the window's last gate — in 40 of 40 files of the
    committed sweep, against 4 of 40 for this form. The two differ by exactly one pitch, which
    sits inside the file check's 1.5 mm tolerance at the fine rungs (0.12-0.49 mm) every
    campaign before this pass ran at and outside it at this pass's 1.85 mm and 2.96 mm rungs.
    So this form is the plan's aim, and the file check predicts the last gate
    (:func:`~udv_echo_process.acquire.verify._check_depth`). Whether the dialog's own ``Depth``
    shows the last gate or one pitch beyond it is still open — the two readings coincide
    inside the rounding at every rung measured so far — and this pass does not depend on the
    answer, because its points declare resolution and gates directly.
    """
    return first_gate_mm + gates * resolution_mm


def max_usable_depth_mm(sound_speed_ms: float, prf_us: float) -> float:
    """Unambiguous reach ``P_max = c × T_prf / 2`` in mm (docs/08 §3).

    PRF is a **period in µs** in this application while other tooling in the
    family speaks Hz, so the µs→s conversion sits here explicitly:
    ``P_max = c [m/s] × T_prf [µs] × 1e-3 / 2`` mm.

    At the measured baseline ``c = 1500 m/s, T_prf = 200 µs`` this is 150 mm;
    at 125 µs it is only 93.75 mm — which is why a 100 mm window needs
    ``T_prf >= 134 µs`` at that sound speed, and why this is checked before
    blaming the ladder (docs/08 §3).
    """
    if prf_us <= 0:
        raise ValueError(f"prf_us must be > 0, got {prf_us}")
    return sound_speed_ms * prf_us * 1e-3 / 2.0


def fits_depth_budget(
    parameters: ParameterSet,
    *,
    limits: AcquisitionLimits = DEFAULT_LIMITS,
) -> bool:
    """True when the window fits ``first_gate + gates × pitch <= P_max``.

    Requires the PRF period on the parameter set: without it the budget is
    unknown and a silent clamp cannot be predicted, so this raises rather than
    guessing (docs/08 §3).
    """
    if parameters.prf_us is None:
        raise ValueError(
            "the depth budget cannot be checked without prf_us on the "
            "parameter set (read it from the app first)"
        )
    return parameters.depth_mm <= max_usable_depth_mm(
        parameters.sound_speed_ms, parameters.prf_us
    )


def gate_drift(requested_gates: int, readback_gates: int) -> float:
    """Relative move from the requested to the read-back gate count.

    Positive means the app **reduced** the count (its auto-resolution /
    auto-gates flags recompute it), negative means it raised it. The reference
    implementation noted a move beyond 5 % of the request (docs/16 §14).
    """
    if requested_gates <= 0:
        raise ValueError(f"requested_gates must be > 0, got {requested_gates}")
    return 1.0 - readback_gates / requested_gates


#: The instrument's fixed number of extra emissions per profile, ``N_Stb`` in the manual's
#: law (docs/dop3000/manual-reference/08-the-parameters.md §8.8): emissions the instrument
#: spends on its own internal computation, beyond the ``N_PRF`` that make up the profile.
PROFILE_INTERNAL_EMISSIONS = 16

#: The transfer term ``T_tran`` of that same law, in seconds — the mean time the internal
#: processor spends handing a profile's data to memory. The manual calls it a mean that
#: "may occasionally vary quite a lot due to the Windows environment", so this is an
#: estimate of that mean at the historical ``~1 ms``, not a measured constant.
PROFILE_TRANSFER_S = 1e-3


def profile_period_s(emissions_per_profile: int, prf_us: float) -> float:
    """The profile period the manual's law predicts for one configuration, in seconds.

    ``T_profile ≈ T_tran + T_prf · (N_Stb + N_PRF)`` (docs/08 §8.8), with the two terms as
    :data:`PROFILE_TRANSFER_S` and :data:`PROFILE_INTERNAL_EMISSIONS`. At the pass's 600 µs
    PRF that is ``9.6 ms + 1 ms``. The first term is worth naming separately: 9.6 ms is the
    instrument's own 16 emissions, while the ~10.4 ms intercept a stored file measures is
    that 9.6 ms **and** the transfer term together — two quantities that are close at
    600 µs and are not the same thing.

    This is the *expectation* the profile count and the gross size guard are derived from.
    It is never a substitute for the achieved period, which is read back from each stored
    file's own profile timestamps and is that point's certificate.
    """
    if emissions_per_profile < 0:
        raise ValueError(
            f"emissions_per_profile must be >= 0, got {emissions_per_profile}"
        )
    if prf_us <= 0:
        raise ValueError(f"prf_us must be > 0, got {prf_us}")
    return (
        prf_us * 1e-6 * (emissions_per_profile + PROFILE_INTERNAL_EMISSIONS)
        + PROFILE_TRANSFER_S
    )


def profiles_for_duration(duration_s: float, period_s: float) -> int:
    """Profile count for the window ``T`` at the *achieved* period.

    Derived, never the point's definition (docs/16 §15 item 3), and rounded up:
    a cap check that rounded down would accept a point whose window is already
    saturating.
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}")
    if period_s <= 0:
        raise ValueError(f"period_s must be > 0, got {period_s}")
    return math.ceil(duration_s / period_s)


def window_fits(
    duration_s: float, period_s: float, max_profiles_per_block: int
) -> bool:
    """True when ``T / period`` fits the block cap (docs/16 §15b)."""
    return profiles_for_duration(duration_s, period_s) <= max_profiles_per_block


def assert_window_fits(
    duration_s: float, period_s: float, max_profiles_per_block: int
) -> int:
    """Assert the window fits the cap; return the derived profile count.

    Raising is the point: the app does not stop at the cap, the block is a ring,
    so the stored file would cover only the last ``cap × period`` seconds and
    would still decode as a valid point (docs/16 §15b). Either free the cap or
    shorten ``T``.
    """
    profiles = profiles_for_duration(duration_s, period_s)
    if profiles > max_profiles_per_block:
        raise ValueError(
            f"{duration_s} s at {period_s} s/profile needs {profiles} profiles, "
            f"above the block cap of {max_profiles_per_block}: the block would "
            "wrap and the stored file would cover only its last "
            f"{max_profiles_per_block * period_s:.3f} s"
        )
    return profiles


class SweepDefinition(ValueModel):
    """What a depth sweep is: the fixed window, the rung list, and ``T``.

    ``rungs`` are 1-based rung indices (``k``), so ``k = 1`` is the finest rung
    of the ladder, matching the stored ``res_idx = k - 1``. ``prf_us`` and the
    other covariates are optional here because they are read from the app: when
    present, :func:`plan_sweep` rejects a point the app would silently clamp.
    """

    sound_speed_ms: float = Field(gt=0)
    #: ``First gate depth [mm]`` as read from the app: 2 mm on the tested channel.
    first_gate_mm: float = Field(ge=0)
    target_depth_mm: float = Field(gt=0)
    #: ``T``: the observation window in seconds — what defines a point.
    duration_s: float = Field(gt=0)
    rungs: tuple[int, ...]
    prf_us: float | None = Field(default=None, gt=0)
    emissions_per_profile: int | None = Field(default=None, ge=1)
    burst_length: int | None = Field(default=None, ge=1)
    limits: AcquisitionLimits = Field(default_factory=AcquisitionLimits)

    @field_validator("rungs")
    @classmethod
    def _check_rungs(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("rungs must not be empty")
        for key in value:
            if key < 1:
                raise ValueError(f"rung multipliers are 1-based, got k={key}")
        if len(set(value)) != len(value):
            raise ValueError(f"rungs must be unique, got {list(value)}")
        return value

    @model_validator(mode="after")
    def _check_window(self) -> SweepDefinition:
        if self.target_depth_mm <= self.first_gate_mm:
            raise ValueError(
                f"target_depth_mm ({self.target_depth_mm}) must exceed "
                f"first_gate_mm ({self.first_gate_mm})"
            )
        return self

    @property
    def rung_mm(self) -> float:
        """The ladder rung for this definition's sound speed."""
        return rung_mm(self.sound_speed_ms, limits=self.limits)

    def parameters_for(self, key: int) -> ParameterSet:
        """The requested parameter set for one 1-based rung index."""
        if key > self.limits.max_rung_index + 1:
            raise ValueError(
                f"k={key} is above the ladder's {self.limits.max_rung_index + 1} "
                "rungs (the app would clamp the pitch, not honour it)"
            )
        resolution = round(key * self.rung_mm, 6)
        gates = gates_for_depth(
            self.target_depth_mm,
            self.first_gate_mm,
            resolution,
            limits=self.limits,
        )
        return ParameterSet(
            sound_speed_ms=self.sound_speed_ms,
            first_gate_mm=self.first_gate_mm,
            resolution_mm=resolution,
            gates=gates,
            prf_us=self.prf_us,
            emissions_per_profile=self.emissions_per_profile,
            burst_length=self.burst_length,
        )


class SweepPoint(ValueModel):
    """One planned point: a rung index, its parameter request, and ``T``.

    The parameter set carries the *request*; the achieved resolution and gate
    count come from the stored file's block for the channel that measured, and
    are held by the log record, not here.
    """

    key: int = Field(ge=1)
    parameters: ParameterSet
    duration_s: float = Field(gt=0)

    @property
    def rung_index(self) -> int:
        """0-based ladder index — the value the file reports as word 10."""
        return self.key - 1

    @property
    def expected_depth_mm(self) -> float:
        """Plan prediction of the window depth, to 3 decimals.

        The app's own derived depth (word 2, integer mm) is the authority; a
        mismatch means the write was clamped, which the pre-record read-back
        should already have caught.
        """
        return round(self.parameters.depth_mm, 3)

    def expected_profiles(self, period_s: float) -> int:
        """Derived profile count at a measured period (``T / period``)."""
        return profiles_for_duration(self.duration_s, period_s)


def plan_point(key: int, definition: SweepDefinition) -> SweepPoint:
    """Plan one point at 1-based rung index ``key``."""
    return SweepPoint(
        key=key,
        parameters=definition.parameters_for(key),
        duration_s=definition.duration_s,
    )


def plan_sweep(definition: SweepDefinition) -> tuple[SweepPoint, ...]:
    """Expand the rung list into points, finest rung first (the given order).

    When the definition carries the PRF period, every point's window is checked
    against ``P_max = c × T_prf / 2`` here rather than discovered as a silently
    trimmed gate count later (docs/08 §3).
    """
    points = tuple(plan_point(key, definition) for key in definition.rungs)
    if definition.prf_us is not None:
        p_max = max_usable_depth_mm(definition.sound_speed_ms, definition.prf_us)
        for point in points:
            if not fits_depth_budget(point.parameters):
                raise ValueError(
                    f"point k={point.key} wants {point.parameters.depth_mm:.3f} mm "
                    f"but the depth budget at PRF {definition.prf_us} us is "
                    f"{p_max:.3f} mm: the app would silently reduce the gate count "
                    "(lower the target depth, raise the PRF period, or raise the "
                    "first gate)"
                )
    return points
