"""Per-channel instrument configuration (Tier-C metadata).

Every channel carries its own static operating config (the DOP3000 stores a
per-channel operation-parameter block). These fields are metadata, not data:
they are optional (a reader may not know all of them) and default-dense, so a
minimally-populated ``ChannelConfig`` is ``ChannelConfig()``.
"""

from __future__ import annotations

from udv_echo_process.models.base import Model


class ChannelConfig(Model):
    """Static per-channel instrument settings for one measurement channel.

    All fields default to ``None`` except where a default is physically
    meaningful, so ``ChannelConfig()`` is always a valid instance. Populated
    by the ``.BDD`` reader from the per-channel op-parameter block; the
    charset is deliberately broad to be lenient across instruments.
    """

    # Acoustic / emission
    source_freq_khz: float | None = None
    pulse_repetition_freq_hz: float | None = None
    burst_length: int | None = None
    emit_power: str | None = None  # "low" | "medium" | "high"
    sensitivity: str | None = None

    # Gate geometry
    gate1_mm: float | None = None
    n_gates: int | None = None
    resolution_mm: float | None = None
    sampling_volume_mm: float | None = None
    max_depth_mm: float | None = None

    # Medium / physics
    sound_speed_ms: float | None = None
    doppler_angle_deg: float | None = None
    velo_max_ms: float | None = None  # ±Nyquist; needed for aliasing

    # TGC / filters / trigger
    tgc_mode: str | None = None
    tgc_start_db: float | None = None
    tgc_end_db: float | None = None
    wall_filter: str | None = None
    trigger_state: str | None = None
    module_scale: int | None = None  # ADC full-scale 1|2|4|8 → 2048|1024|512|256

    def describe(self) -> str:
        """One-line human summary of the configured instrument state."""
        parts = [f"{self.gate1_mm or 0:.2f} mm", f"{self.n_gates or 0} gates"]
        if self.sound_speed_ms:
            parts.append(f"c={self.sound_speed_ms:.0f} m/s")
        if self.pulse_repetition_freq_hz:
            parts.append(f"PRF={self.pulse_repetition_freq_hz:.0f} Hz")
        return ", ".join(parts)
