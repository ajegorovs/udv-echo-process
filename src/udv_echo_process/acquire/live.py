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

import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path

from udv_echo_process.acquire.actuator import (
    BurstWriteResult,
    PreflightReport,
    ProcessMode,
    ScreenFingerprint,
)
from udv_echo_process.acquire.bridge import BridgeActuator, BridgeDispatch
from udv_echo_process.acquire.config import (
    BRIDGE_RUNNER_ENV_VAR,
    RecordSettings,
    bridge_path_from_environment,
)
from udv_echo_process.acquire.driver import Win32Actuator
from udv_echo_process.acquire.plan import SweepDefinition
from udv_echo_process.acquire.runner import PointOutcome, SweepRunner
from udv_echo_process.acquire.verify import WordFacts, read_words

__all__ = [
    "BRIDGE_RUNNER_ENV",
    "bridge_actuator",
    "bridge_dispatch",
    "decode",
    "live_actuator",
    "point",
    "preflight",
    "select_channel",
    "set_burst_length",
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


def live_actuator(
    channel: int | None = None, notes: list[str] | None = None
) -> Win32Actuator:
    """A driver bound to ``channel`` (``None`` takes the ``UDV_CHANNEL`` setting)."""
    return Win32Actuator(
        channel=channel, note_sink=None if notes is None else notes.append
    )


#: Re-exported for callers that set it; the variable itself is declared in ``config``, which is the
#: one module allowed to read the environment.
BRIDGE_RUNNER_ENV = BRIDGE_RUNNER_ENV_VAR


def bridge_dispatch(runner_path: str | Path | None = None) -> BridgeDispatch | None:
    """The machine-local dispatch, loaded by path — or ``None`` when the host has none configured.

    ``None`` is a refusal the caller can see (:meth:`BridgeActuator.unavailable`), never a silent
    fallback: a host without the module gets ``bridge_runner_not_configured`` from the actuator
    rather than a cycle that starts and cannot finish.
    """
    configured = runner_path or bridge_path_from_environment(BRIDGE_RUNNER_ENV_VAR)
    if not configured:
        return None
    location = Path(configured)
    if not location.is_file():
        return None
    spec = importlib.util.spec_from_file_location("udv_bridge_runner", location)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["udv_bridge_runner"] = module
    spec.loader.exec_module(module)
    dispatch = getattr(module, "dispatch", None)
    return dispatch if callable(dispatch) else None


def bridge_actuator(
    channel: int | None = None,
    notes: list[str] | None = None,
    *,
    table_path: str | Path | None = None,
    runner_path: str | Path | None = None,
    target_digest: str | None = None,
) -> BridgeActuator:
    """The same screen, with the record/store cycle on the bridge route — **opt-in**.

    The GUI actuator is still the inner one, so every parameter write, strip read and overlay answer
    is unchanged; only the cycle at a point's end takes the other path. ``route="ui"`` remains the
    default everywhere, and a host without the table or the dispatch module refuses by name instead
    of recording something it cannot verify.
    """
    inner = Win32Actuator(
        channel=channel, note_sink=None if notes is None else notes.append
    )
    return BridgeActuator(
        inner,
        dispatch=bridge_dispatch(runner_path),
        table_path=table_path,
        target_digest=target_digest,
        channel=channel,
    )


def status(
    channel: int | None = None, notes: list[str] | None = None
) -> ScreenFingerprint:
    """Read the screen: layout fingerprint, strip view, process mode, cursor. Presses nothing.

    A **diagnostic**, and it therefore refuses nothing (plan §24.4): the mode is *reported* —
    ``process_mode``, the shape verdict and the counts are all fields of the fingerprint — so the
    question "which process is in front of me?" is answered on either mode with exit code 0. What
    refuses on a mismatch is the record path, which declares an expectation first.
    """
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
    return live_actuator(channel, notes).preflight(
        seconds, expect_directory=expect_directory
    )


def set_burst_length(
    requested: int,
    channel: int | None = None,
    notes: list[str] | None = None,
) -> BurstWriteResult:
    """Make the running application record at burst ``requested``, through its own dialog.

    The second command that can change the instrument, and the smaller of the two: the routing
    step runs first (:meth:`~udv_echo_process.acquire.driver.Win32Actuator.ensure_channel`), and
    its **verified** channel is what the transition is handed as the channel it was routed to —
    so a dialog stating another channel is refused before anything is written. The transition
    itself is the driver's own transaction (open, read both rows, select by value, accept,
    re-open, read both rows again); this command only composes the two steps and returns what was
    verified.

    A transition that was **refused** is a result rather than an exception
    (:class:`~udv_echo_process.acquire.actuator.BurstWriteResult`'s ``state`` and ``reason``);
    a transition that reached ``Accept`` and did not verify raises, and ``udv_acquire`` reports it
    as one line and a non-zero exit code. Nothing here retries: the sampling volume the
    application re-selected from the burst is part of the state it accepted, and this command
    never writes that row — it reads it, before and after
    (``docs/dop3000/burst-length-control-plan.md``).
    """
    actuator = live_actuator(channel, notes)
    routed = actuator.ensure_channel()
    return actuator.write_dialog_burst_length(requested, routed_channel=routed)


def point(
    name: str,
    seconds: float,
    store_dir: Path,
    channel: int | None = None,
    notes: list[str] | None = None,
    *,
    expected_mode: ProcessMode,
) -> tuple[bool, Path | str]:
    """One stored point: ``(True, path)`` or ``(False, reason)``.

    The channel is verified before the recording is spent, and the store dialog's working
    directory is asserted against ``store_dir``: a mismatch refuses the point rather than
    scattering files into whatever directory the application remembered.

    ``expected_mode`` is required and keyword-only (plan §24.4): this command records, so it is a
    record path, and the process it was measured against is declared by the caller — never taken
    from whatever happens to be running. The caption is checked against it before the first press.
    """
    return live_actuator(channel, notes).try_record_and_store(
        name, seconds, store_dir, expected_mode=expected_mode
    )


def sweep(
    seconds: float,
    store_dir: Path,
    rungs: Sequence[int],
    channel: int | None = None,
    *,
    expected_mode: ProcessMode,
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

    ``expected_mode`` is required and keyword-only (plan §24.4) and goes to the runner's own
    construction, so every point of the sweep refuses before it writes anything if the process in
    front is not the one the sweep was measured against.
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
        expected_mode=expected_mode,
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
