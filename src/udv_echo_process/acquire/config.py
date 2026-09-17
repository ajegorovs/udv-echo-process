"""Configuration value objects for unattended UDOP acquisition.

These are the *inputs* a sweep is described by. They are pure (no Windows
dependency, no file I/O), so the planning math, the experiment log and the
actuator interface can all be exercised on any host; the GUI-driving
implementation lands later and satisfies :class:`~udv_echo_process.acquire.actuator.Actuator`.

Every rule encoded here was measured on the running application, not derived:

- **The resolution ladder.** One rung is ``c / 12000`` mm, the app snaps a
  written value to the *nearest* rung, and the ladder clamps at the top rung
  ``c / 100`` mm (docs/08 §1). A written value is therefore a request, never an
  achieved value — the achieved pitch is read back (from the file: word 10 is
  the 0-based rung index, ``resolution_mm = (word10 + 1) × c / 12000``).
- **Seconds specify a point.** A point is a fixed observation window ``T`` in
  seconds because the physics is time-dependent, not profile-dependent;
  the achieved ``Time between profile`` is an *input constraint* to read and
  log per point, and ``profiles = T / period`` is derived from it (docs/16 §15
  item 3).
- **The block cap bounds the window.** ``Do not keep in a block more profiles
  than`` is a setting, not a hardware limit, and exceeding it does **not** stop
  the recording: the block is a ring, so the stored file silently covers only
  the last ``cap × period`` seconds while still decoding as valid (docs/16
  §15b). ``profiles <= cap`` must therefore be asserted per point.
- **Write order matters.** ``Resolution`` is written before ``Nb of gates``,
  because this channel has the manual's auto-resolution / auto-gates flags set:
  writing the resolution makes the app recompute the gate count and silently
  trim the gates just written (805 requested → 474 accepted in the wrong order,
  docs/16 §14).

The ordered write itself lives in ``acquire.actuator`` (it is the actuator's
job to pick the control); this module owns the values.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field, field_validator, model_validator

from udv_echo_process.models.base import ValueModel

__all__ = [
    "DEFAULT_MAX_PROFILES_PER_BLOCK",
    "RUNG_DIVISOR",
    "AcquisitionLimits",
    "ParameterSet",
    "ProfileTiming",
    "RecordSettings",
]

#: One resolution-ladder rung is ``sound_speed / RUNG_DIVISOR`` mm (docs/08 §1).
RUNG_DIVISOR = 12000.0

#: Default block cap in profiles. The app accepted ``1000000`` on the tested
#: installation (docs/16 §15b); the effective limit was never established, so
#: this is a default to state explicitly, never to trust silently.
DEFAULT_MAX_PROFILES_PER_BLOCK = 1_000_000


class AcquisitionLimits(ValueModel):
    """The limits the application enforces on a point's window geometry.

    Defaults are the *measured* ones: gates 4..1000 accepted (1001 clamped,
    docs/08 §2) and the resolution ladder is 120 rungs, ``(index + 1) × c/12000``
    mm, topping out at ``c / 100`` mm (docs/08 §1). Overriding them is how a
    narrower real-unit surface (missing optional packages) is expressed — but
    the app still has the final word, so every write is read back.
    """

    rung_divisor: float = Field(default=RUNG_DIVISOR, gt=0)
    min_gates: int = Field(default=4, ge=1)
    max_gates: int = Field(default=1000, ge=1)
    #: Highest 0-based rung index: 119 means 120 rungs, i.e. ``(index + 1) <= 120``.
    max_rung_index: int = Field(default=119, ge=0)

    @model_validator(mode="after")
    def _check_gate_range(self) -> AcquisitionLimits:
        if self.min_gates > self.max_gates:
            raise ValueError(
                f"min_gates ({self.min_gates}) must not exceed "
                f"max_gates ({self.max_gates})"
            )
        return self

    def clamp_gates(self, gates: int) -> int:
        """Bring a requested gate count into the accepted range."""
        return max(self.min_gates, min(self.max_gates, gates))

    def max_resolution_mm(self, sound_speed_ms: float) -> float:
        """Top rung of the ladder: ``c / 100`` mm (docs/08 §1)."""
        rungs = self.max_rung_index + 1
        return rungs * sound_speed_ms / self.rung_divisor


class ParameterSet(ValueModel):
    """The instrument parameters that define one point's measurement window.

    ``resolution_mm`` and ``gates`` are the two the depth sweep writes; the
    optional covariates (``prf_us``, ``emissions_per_profile``,
    ``burst_length``) are dialog-only parameters that are read once and carried
    with the point so the depth-budget check and the log are complete.

    ``resolution_mm`` is the *requested* pitch. The app snaps it to the nearest
    rung, so the achieved pitch must be read back — from the stored file's word
    10, never from a control's text and never from this object.
    """

    sound_speed_ms: float = Field(gt=0)
    first_gate_mm: float = Field(ge=0)
    resolution_mm: float = Field(gt=0)
    gates: int = Field(ge=1)
    prf_us: float | None = Field(default=None, gt=0)
    emissions_per_profile: int | None = Field(default=None, ge=1)
    burst_length: int | None = Field(default=None, ge=1)

    @property
    def depth_mm(self) -> float:
        """Derived window depth ``first_gate + gates × resolution`` (docs/13 §1).

        The application writes its own derived depth into the file (word 2),
        which is the authority; this property is the plan's prediction.
        """
        return self.first_gate_mm + self.gates * self.resolution_mm

    @property
    def resolution_text(self) -> str:
        """The ladder value as it must be written: 3 decimals.

        The sidebar displays 3 decimals, so writing ``0.121667`` shows
        ``0.122``; that is the app's rounding, not a failed write (docs/16
        §12a). Write 3-decimal values and read the achieved rung from the file.
        """
        return f"{self.resolution_mm:.3f}"


class ProfileTiming(ValueModel):
    """Target vs achieved ``Time between profile`` for one point (docs/16 §15).

    ``achieved_s`` is not a curiosity: the profile period is what constrains the
    parameter matrix, it is the only honest basis for deriving a profile count
    (``T / period``), and it sizes the block cap. It is read per point — the
    first evidence for the period law (``≈ emissions × PRF + ~1 ms``) is a rough
    law, not a substitute for a measurement.
    """

    target_s: float | None = Field(default=None, gt=0)
    achieved_s: float | None = Field(default=None, gt=0)

    def within_tolerance(self, rtol: float = 0.1) -> bool:
        """True when the achieved period is within ``rtol`` of the target.

        Returns ``False`` when either side is missing: an unmeasured period
        cannot support the derivation, so "no data" must not read as "fine".
        """
        if rtol < 0:
            raise ValueError(f"rtol must be >= 0, got {rtol}")
        if self.target_s is None or self.achieved_s is None:
            return False
        return abs(self.achieved_s - self.target_s) <= rtol * self.target_s


class RecordSettings(ValueModel):
    """Where a stored point lands, how it is named, and how big a block may get.

    ``max_profiles_per_block`` mirrors the app's ``Do not keep in a block more
    profiles than`` setting. Set it above the largest point's profile count and
    the block question never arises for a single-channel sweep; a point that
    exceeds it wraps silently (docs/16 §15b), so the count is asserted per point
    by :func:`udv_echo_process.acquire.plan.assert_window_fits`.

    Names must be unique: the Store dialog keeps the *previous* name, and
    reusing one raises the ``file already exists -> replace ?`` warning that
    wedges the app modal if nothing answers it (docs/16 §12b). ``point_name``
    therefore carries the sweep-stable key and a stamp, and :meth:`next_name`
    walks the ``b``-suffix retry the reference implementation used.
    """

    capture_dir: str = Field(default="capture", min_length=1)
    name_prefix: str = Field(min_length=1)
    max_profiles_per_block: int = Field(
        default=DEFAULT_MAX_PROFILES_PER_BLOCK, ge=1
    )

    @field_validator("capture_dir", "name_prefix")
    @classmethod
    def _check_no_surrounding_space(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(f"must not carry surrounding whitespace, got {value!r}")
        return value

    def point_name(self, key: int, stamp: str) -> str:
        """``<prefix>-k<key>-<stamp>`` — collision-proof by construction.

        ``stamp`` is the sweep id (a timestamp supplied by the caller), so a
        later run can never re-use an earlier run's name.
        """
        if not stamp:
            raise ValueError("stamp must not be empty")
        return f"{self.name_prefix}-k{key}-{stamp}"

    def next_name(self, key: int, stamp: str, used: Iterable[str]) -> str:
        """First free name for ``key`` at ``stamp``, appending ``b`` while taken.

        The stored names come from the log (``acquire.log.point_names``), so a
        resumed sweep does not overwrite a file it already produced.
        """
        taken = set(used)
        name = self.point_name(key, stamp)
        while name in taken:
            name += "b"
        return name
