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
from udv_echo_process.acquire.bridge import (
    BridgeActuator,
    BridgeDispatch,
    BridgeMenu,
    BridgeUnavailable,
    load_table,
)
from udv_echo_process.acquire.column import COLUMN_COMBOS, ColumnChange, ColumnReport
from udv_echo_process.acquire.config import (
    BRIDGE_RUNNER_ENV_VAR,
    RecordSettings,
    bridge_path_from_environment,
)
from udv_echo_process.acquire.driver import Win32Actuator
from udv_echo_process.acquire.plan import SweepDefinition
from udv_echo_process.acquire.runner import PointOutcome, SweepRunner
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.verify import WordFacts, read_words

__all__ = [
    "BRIDGE_RUNNER_ENV",
    "actuator_for",
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


def _menu_opener(table_path: str | Path | None, dispatch: object | None):
    """A `BridgeMenu` for the table the run is using, or ``None`` when that table carries no menu block.

    ``None`` is a refusal the driver already understands (it hovers instead), never a silent substitute: a host
    whose table has no measured menu routines keeps the old step rather than pretending to a capability it has
    not got.
    """
    if dispatch is None:
        return None
    try:
        table = load_table(table_path)
    except BridgeUnavailable:
        return None
    if table.menu is None:
        return None
    return BridgeMenu(table, dispatch)


def actuator_for(
    route: str = "ui",
    channel: int | None = None,
    notes: list[str] | None = None,
    *,
    table_path: str | Path | None = None,
    runner_path: str | Path | None = None,
    target_digest: str | None = None,
    numeric_writes: bool = False,
    cycle: object | None = None,
) -> Win32Actuator | BridgeActuator:
    """The actuator a command should use: ``ui`` (the default) or ``bridge``.

    One function so ``point``/``sweep`` and the CLI cannot disagree about what a route means, and an
    unknown route is an error rather than a silent fall back to the GUI — a run that asked for the
    bridge and silently got the UI route would record data the caller did not ask for.
    """
    if route == "ui":
        return live_actuator(channel, notes)
    if route == "bridge":
        return bridge_actuator(
            channel,
            notes,
            table_path=table_path,
            runner_path=runner_path,
            target_digest=target_digest,
            numeric_writes=numeric_writes,
            cycle=cycle,
        )
    raise ValueError(f"unknown route {route!r}: expected 'ui' or 'bridge'")


def bridge_actuator(
    channel: int | None = None,
    notes: list[str] | None = None,
    *,
    table_path: str | Path | None = None,
    runner_path: str | Path | None = None,
    target_digest: str | None = None,
    numeric_writes: bool = False,
    cycle: object | None = None,
) -> BridgeActuator:
    """The same screen, with the record/store cycle on the bridge route — **opt-in**.

    The GUI actuator is still the inner one, so every parameter write, strip read and overlay answer
    is unchanged; only the cycle at a point's end takes the other path. ``route="ui"`` remains the
    default everywhere, and a host without the table or the dispatch module refuses by name instead
    of recording something it cannot verify.

    ``numeric_writes`` asks the wrapper to write parameters through the bridge's own setter instead of the
    GUI's dialogs. It is off by default and it is the *policy*, not the mechanism: the value is read before and
    after, a mismatch is restored through the GUI write, and an unverifiable restore poisons the actuator for
    the rest of the run. Measured 2026-10-22, a second value commit in a fresh attachment was not honoured —
    which is why this stays opt-in and why the read-back, not the dispatch's report, decides.
    """
    dispatch = bridge_dispatch(runner_path)
    inner = Win32Actuator(
        channel=channel,
        note_sink=None if notes is None else notes.append,
        # The menubar is the one step that used to need the operator's cursor, and this route already carries
        # the dispatch that removes the need: bind it, so a channel verification (which opens the Parameters
        # dialog) no longer requires the application to be the foreground window with a hand on the mouse.
        # `press` stays None on purpose — the driver presses an entry with its own posted press, which needs no
        # cursor either, so only the overlay's opening has to come from the dispatcher.
        menu=_menu_opener(table_path, dispatch),
    )
    return BridgeActuator(
        inner,
        dispatch=dispatch,
        table_path=table_path,
        target_digest=target_digest,
        channel=channel,
        numeric_writes=numeric_writes,
        cycle=cycle,
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


def set_column(
    *,
    sensitivity: str | None = None,
    emitting_power: str | None = None,
    channel: int | None = None,
    notes: list[str] | None = None,
) -> ColumnReport:
    """Set the parameter column's dropdowns **by value text**, and read each one back.

    Not a ``ParamRole`` write: these two are chosen from a list, not typed, and the selection is the app's
    own (``CB_SETCURSEL`` + ``CBN_SELCHANGE`` — the pair the burst transaction already trusts).  The entry is
    found by stepping the widget until the list clamps and matching the text exactly
    (:func:`~udv_echo_process.acquire.ui.combo.select_by_text`), never by counting steps: a build whose list
    is one entry longer must not move the value.

    **A TGC mode change is not part of this call.** It is a dialog workflow, and — measured 2026-10-23 —
    accepting a TGC change resets the receiver settings below it in the column, so a caller that wants both
    sets the TGC mode first and then these; a value set here is not evidence about itself once that happens.

    A refusal (an entry the list does not hold, or a selection the widget did not take) raises, with the
    widget's own words: there is no "probably set" outcome.
    """
    wanted: dict[str, str] = {}
    if sensitivity is not None:
        wanted["Sensitivity"] = sensitivity
    if emitting_power is not None:
        wanted["Emitting power"] = emitting_power
    if not wanted:
        raise AcquisitionError("nothing to set: pass a sensitivity and/or an emitting power")

    actuator = live_actuator(channel, notes)
    combos = actuator._resolve()["combos"]
    changes: list[ColumnChange] = []
    for name in COLUMN_COMBOS:
        if name not in wanted:
            continue
        combo = combos.get(name)
        if combo is None:
            raise AcquisitionError(f"no {name!r} combo in the parameter column")
        before = actuator._get_text(combo["hwnd"])
        selection = actuator.select_combo_by_text(name, wanted[name])
        changes.append(
            ColumnChange(
                combo=name,
                requested=wanted[name],
                before=before,
                readback=selection.readback,
                index=selection.index,
                entries=selection.entries,
                changed=selection.readback != before,
            )
        )

    report = ColumnReport(
        channel=None if channel is None else int(channel),
        changes=tuple(changes),
        verified=all(change.readback == change.requested for change in changes),
    )
    if notes is not None:
        for change in changes:
            notes.append(
                f"{change.combo}: {change.before!r} -> {change.readback!r} "
                # one-based, like the line the command prints: an index a human reads off the UI
                f"(entry {change.index + 1} of {len(change.entries)})"
            )
    return report


def point(
    name: str,
    seconds: float,
    store_dir: Path,
    channel: int | None = None,
    notes: list[str] | None = None,
    *,
    expected_mode: ProcessMode,
    route: str = "ui",
    table_path: str | Path | None = None,
    runner_path: str | Path | None = None,
    target_digest: str | None = None,
    numeric_writes: bool = False,
    cycle: object | None = None,
) -> tuple[bool, Path | str]:
    """One stored point: ``(True, path)`` or ``(False, reason)``.

    The channel is verified before the recording is spent, and the store dialog's working
    directory is asserted against ``store_dir``: a mismatch refuses the point rather than
    scattering files into whatever directory the application remembered.

    ``expected_mode`` is required and keyword-only (plan §24.4): this command records, so it is a
    record path, and the process it was measured against is declared by the caller — never taken
    from whatever happens to be running. The caption is checked against it before the first press.
    """
    return actuator_for(
        route,
        channel,
        notes,
        table_path=table_path,
        runner_path=runner_path,
        target_digest=target_digest,
        numeric_writes=numeric_writes,
        cycle=cycle,
    ).try_record_and_store(name, seconds, store_dir, expected_mode=expected_mode)


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
    route: str = "ui",
    table_path: str | Path | None = None,
    runner_path: str | Path | None = None,
    target_digest: str | None = None,
    numeric_writes: bool = False,
    cycle: object | None = None,
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
    actuator = actuator_for(
        route,
        channel,
        notes,
        table_path=table_path,
        runner_path=runner_path,
        target_digest=target_digest,
        numeric_writes=numeric_writes,
        cycle=cycle,
    )
    settings = RecordSettings(capture_dir=str(store_dir), name_prefix=name_prefix)
    runner = SweepRunner(
        actuator,
        settings,
        store_dir,
        signature=None,
        log_path=log_path,
        channel=channel,
        expected_mode=expected_mode,
        # What the block may hold beyond the requested window.  This was 20 s on the belief that the route's attachments
        # were recorded into the block; measured 2026-10-26, that was the *position* of the fresh-block boundary, not the
        # route's cost.  With the boundary next to the record, a 2 s point stored 2.70 s (68 profiles) - 0.7 s of
        # overshoot, the stop-to-store residual.  Two seconds covers it with room; another window's block is far out.
        window_overhead_s=2.0 if cycle is not None else 0.0,
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
