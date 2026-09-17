"""The supported live commands: what an operator runs against the instrument.

Each function builds a live actuator, drives it through its **public** surface, and returns a
report object; the printing, the JSON and the exit codes belong to
:mod:`udv_echo_process.cli`. Nothing here reaches into a private member of the driver — which
is exactly what separates these commands from the reconnaissance probes they replace
(``tools/live/probes/``, still present for what a command does not cover: a geometry probe, a
one-off measurement).

These commands drive a *running* application, so they work only from the session that owns its
screen — see ``tools/live/README.md`` for why, and how to dispatch them. Nothing else about
them is host-specific: they take the channel, the store directory and the instrument's
measurement values as arguments, so an instrument whose configuration differs is described by
its arguments rather than assumed.

The one write to the instrument among the read-mostly commands is :func:`select_channel`: it
writes the channel only when the dialog is not already on it (the driver's own rule), and a
*failed* selection leaves the application where it was.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from udv_echo_process.acquire.actuator import PreflightReport, ScreenFingerprint
from udv_echo_process.acquire.config import RecordSettings
from udv_echo_process.acquire.driver import Win32Actuator
from udv_echo_process.acquire.plan import SweepDefinition
from udv_echo_process.acquire.runner import PointOutcome, SweepRunner
from udv_echo_process.acquire.verify import WordFacts, read_words

__all__ = [
    "decode",
    "live_actuator",
    "point",
    "preflight",
    "select_channel",
    "status",
    "sweep",
]

#: The instrument's own measurement values, as measured on the reference install (sound speed,
#: first gate, window depth, PRF period, emissions per profile, burst). They are *defaults for
#: an argument*, never a fallback the caller cannot see: a sweep on another instrument passes
#: its own, read off that instrument (``docs/dop3000/live-bringup.md`` §4).
DEFAULT_MEASUREMENT = {
    "sound_speed_ms": 1460.0,
    "first_gate_mm": 2.0,
    "target_depth_mm": 99.0,
    "prf_us": 212.0,
    "emissions_per_profile": 150,
    "burst_length": 4,
}


def live_actuator(channel: int | None = None, notes: list[str] | None = None) -> Win32Actuator:
    """A driver bound to ``channel`` (``None`` takes the ``UDV_CHANNEL`` setting)."""
    return Win32Actuator(
        channel=channel, note_sink=None if notes is None else notes.append
    )


def status(channel: int | None = None, notes: list[str] | None = None) -> ScreenFingerprint:
    """Read the screen: layout fingerprint, strip view, overlay, cursor. Presses nothing."""
    return live_actuator(channel, notes).screen_fingerprint()


def select_channel(
    channel: int, notes: list[str] | None = None
) -> tuple[int, ScreenFingerprint]:
    """Verify the measurement channel (writing it only if the dialog is not already on it).

    The one command that can change the instrument: everything recorded afterwards lands on this
    channel, and a point recorded on the wrong one decodes as a valid point that is not the
    point (``docs/16`` §12). Returns the verified channel and the screen it left behind.
    """
    actuator = live_actuator(channel, notes)
    verified = actuator.ensure_channel()
    return verified, actuator.screen_fingerprint()


def preflight(
    seconds: float = 2.0,
    channel: int | None = None,
    *,
    expect_directory: Path | None = None,
    notes: list[str] | None = None,
) -> PreflightReport:
    """One whole cycle with nothing stored: record, stop, read the Store dialog, cancel it."""
    return live_actuator(channel, notes).preflight(seconds, expect_directory=expect_directory)


def point(
    name: str,
    seconds: float,
    store_dir: Path,
    channel: int | None = None,
    notes: list[str] | None = None,
) -> tuple[bool, Path | str]:
    """One stored point: ``(True, path)`` or ``(False, reason)``.

    The channel is verified before the recording is spent, and the store dialog's working
    directory is asserted against ``store_dir``: a mismatch refuses the point rather than
    scattering files into whatever directory the application remembered.
    """
    return live_actuator(channel, notes).try_record_and_store(name, seconds, store_dir)


def sweep(
    seconds: float,
    store_dir: Path,
    rungs: Sequence[int],
    channel: int | None = None,
    *,
    name_prefix: str = "sweep",
    log_path: Path | None = None,
    notes: list[str] | None = None,
    **measurement: float,
) -> tuple[PointOutcome, ...]:
    """A multi-point sweep through :class:`SweepRunner`, one JSONL entry per point.

    ``rungs`` are 1-based resolution-ladder indices (``k``); the ladder, the gate count and the
    depth budget come from :mod:`udv_echo_process.acquire.plan`, so a point the application
    would silently clamp is refused before a recording is spent. ``measurement`` takes the
    instrument's own values (:data:`DEFAULT_MEASUREMENT`) — pass the ones this instrument
    reports.
    """
    values = {**DEFAULT_MEASUREMENT, **measurement}
    actuator = live_actuator(channel, notes)
    settings = RecordSettings(capture_dir=str(store_dir), name_prefix=name_prefix)
    runner = SweepRunner(
        actuator,
        settings,
        store_dir,
        signature=None,
        log_path=log_path,
        channel=channel,
    )
    definition = SweepDefinition(
        duration_s=seconds,
        rungs=tuple(rungs),
        **values,  # type: ignore[arg-type]
    )
    return runner.run(definition, seconds)


def decode(path: Path, channel: int) -> WordFacts:
    """A stored file's own operation words, read on the channel that measured.

    The certificate for a point: the file is the authority, and the words say which channel's
    block it is (a block that carries no data for the channel asked for is refused here rather
    than read as someone else's point).
    """
    return read_words(Path(path), channel=channel)
