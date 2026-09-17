"""The sweep runner: reset, apply, record, decode — and refuse what is unproven.

One point becomes one stored file and one log record. Measured on the live
application, the failure this loop exists to prevent: a point recorded into a block
that still held ~6,000 stale profiles was stored as an 8.3 MB file — about 60× the
~90 KB such a window produces — while the status bar showed broken negative timing
values; pressing ``CLEAR_AND_RESTART`` first produced a correct 87 KB point. A
contaminated point that reaches the log marked *valid* is the worst outcome this
module can produce, so:

- the block is reset before **every** point, and the reset is confirmed by polling
  for a startable strip view — never by sleeping;
- a file whose size is not within the signature's factor of the expected size is
  refused, and so is a file whose size cannot be checked at all
  (``size_is_plausible() is None`` means *unchecked*, never *fine*);
- the write read-back is compared with the request before a recording is spent, so
  a window the app clamped is refused without leaving a junk file behind;
- every outcome is logged through ``append_entry``, valid or not, and a point is
  ``OK`` only when a file was stored, decoded **and** matched the signature.

**The expectation is built from the specification, never from the file.** The
expected size is ``signature.expected_bytes(requested_gates, profiles)``, with
``profiles = T / period`` from the point's own ``emissions_per_profile`` and
``prf_us`` (the measured ``emissions × PRF + ~1 ms`` law). An expectation taken
from the file under test would simply agree with it — 6,000 stale profiles would
"expect" the 8.3 MB they held. A wrapped block — a window longer than the profile
cap, which ``plan.assert_window_fits`` checks against at plan time — shows up here
as a file far *smaller* than expected, so the same guard covers it.

A failure anywhere in :meth:`SweepRunner.run_point` returns an outcome; it never
raises. Only the :class:`~udv_echo_process.acquire.actuator.Actuator` protocol is
driven — no ``ctypes``, ``win32``, ``pywinauto`` or ``PIL``, no control id, no
screen coordinate, no absolute path — so the module imports on any host and a fake
actuator is a complete substitute.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from udv_echo_process.acquire.actuator import (
    STARTABLE_VIEWS,
    Actuator,
    ParamRole,
    StripControl,
    StripState,
    StripView,
)
from udv_echo_process.acquire.config import ParameterSet, RecordSettings
from udv_echo_process.acquire.log import (
    DecodedBlock,
    PointStatus,
    SizeSignature,
    SweepPointRecord,
    append_entry,
    sweep_id_for,
)
from udv_echo_process.acquire.plan import (
    GATE_DRIFT_NOTE,
    SweepDefinition,
    SweepPoint,
    gate_drift,
    plan_sweep,
    profiles_for_duration,
)
from udv_echo_process.io.dop.bdd import read as _read_bdd

__all__ = [
    "GATE_DRIFT_LIMIT",
    "PERIOD_OVERHEAD_S",
    "RESET_TIMEOUT_S",
    "PointOutcome",
    "SweepActuator",
    "SweepRunner",
]

#: How long the pre-point reset is given to reach a startable view, in seconds. A
#: bound, not a wait: a reset that has not settled by then refuses the point.
RESET_TIMEOUT_S = 20.0

#: The relative gate move the read-back may show before the point is refused — the
#: reference implementation's 5 % (``plan.GATE_DRIFT_NOTE``); beyond it the app has
#: recomputed the window for us.
GATE_DRIFT_LIMIT = GATE_DRIFT_NOTE

#: The constant term of the measured profile-period law: a profile of
#: ``emissions_per_profile`` emissions takes ``emissions × PRF + ~1 ms``. An estimate,
#: used only to count the profiles a window implies (which sizes the size check) —
#: never a substitute for the achieved period, which the actuator cannot report.
PERIOD_OVERHEAD_S = 1e-3


class SweepActuator(Actuator, Protocol):
    """The :class:`Actuator` surface plus the two composed calls a sweep needs.

    ``Actuator`` fixes the primitives; the ordered parameter write and the whole
    record/stop/store cycle are what a sweep calls, and naming them here is what lets
    this module be written and faked against the actuator interface alone.
    """

    def apply_point(self, parameters: ParameterSet) -> Mapping[ParamRole, str]:
        """Apply a window in the committed write order; return the app's read-back."""
        ...

    def try_record_and_store(
        self, name: str, duration_s: float, directory: Path
    ) -> tuple[bool, Path | str]:
        """Record, stop, store as ``name``; ``(True, path)`` or ``(False, reason)``."""
        ...


@dataclass(frozen=True)
class PointOutcome:
    """What one point did: the file, the decoded block, and whether it counts.

    ``ok`` is true only for a point that was stored, decoded and matched the size
    signature. A point that is not ok may still carry a ``file`` — an invalid file is
    evidence and is kept — so a non-``None`` file must never be read as success.
    """

    point: SweepPoint | None
    ok: bool
    file: Path | None
    status: PointStatus
    reason: str | None
    decoded: DecodedBlock | None


@dataclass
class _Attempt:
    """The working record of one point, and the log line's raw material.

    ``status`` is the single source of truth: ``ok`` is derived from it, so a point
    cannot be reported good and logged bad.
    """

    point: SweepPoint
    name: str
    status: PointStatus = PointStatus.FAILED
    file: Path | None = None
    reason: str | None = None
    decoded: DecodedBlock | None = None
    readback_gates: int | None = None
    readback_resolution: str | None = None
    size_bytes: int | None = None
    expected_bytes: int | None = None


class SweepRunner:
    """Run planned points against an :class:`Actuator` and log what happened.

    One runner is one sweep: it holds the sweep id that stamps every point name and
    log record and the names already used, so a run cannot re-use a name — a taken
    name raises the Store dialog's overwrite warning, which wedges the application
    when nothing answers it.
    """

    def __init__(
        self,
        actuator: Actuator,
        settings: RecordSettings,
        directory: Path,
        signature: SizeSignature | None = None,
        log_path: Path | None = None,
    ) -> None:
        """Bind a runner to its actuator, its naming and where points land.

        ``signature=None`` means the calibrated default (1.7 B per gate-profile,
        factor 2); ``log_path=None`` returns outcomes without writing a JSONL log.
        """
        self._actuator: SweepActuator = cast(SweepActuator, actuator)
        self._settings = settings
        self._directory = Path(directory)
        self._signature = SizeSignature() if signature is None else signature
        self._log_path = None if log_path is None else Path(log_path)
        self._sweep_id = sweep_id_for(datetime.now(tz=UTC).astimezone())
        #: Log entries that could not be written. Never silent, never fatal.
        self.log_errors: list[str] = []
        self._used_names: set[str] = set()

    def run_point(
        self, point: SweepPoint, duration_s: float, *, reset: bool = True
    ) -> PointOutcome:
        """Run one point end to end and return its outcome; never raise.

        In order: reset the block (unless ``reset=False``) and confirm a startable
        view; apply the parameters and compare the read-back with the request; record
        and store under a free name; decode the stored file; check its size against
        the signature; append one log entry, valid or not; return. Only a caller that
        has just reset the block itself should pass ``reset=False`` — a stale block is
        stored under this point's name otherwise.
        """
        try:
            attempt = self._execute(point, duration_s, reset=reset)
        except Exception as exc:  # noqa: BLE001 - reported as an outcome below
            name = self._settings.point_name(point.key, self._sweep_id)
            attempt = _Attempt(point=point, name=name)
            self._fail(attempt, f"the point cycle raised {type(exc).__name__}: {exc}")
        self._report(attempt)
        return self._outcome(attempt)

    def run(
        self, definition: SweepDefinition, duration_s: float
    ) -> tuple[PointOutcome, ...]:
        """Plan ``definition`` and run every point in order, with ``T = duration_s``.

        The sweep does not stop at the first bad point: a failed or refused point is
        logged and the next one starts, so one contaminated window costs one point.
        Raises ``ValueError`` when ``duration_s`` is not positive or the definition
        cannot be planned (``plan_sweep`` refuses a point the app would clamp).
        """
        if duration_s <= 0:
            raise ValueError(f"duration_s must be > 0, got {duration_s}")
        return tuple(
            self.run_point(point, duration_s) for point in plan_sweep(definition)
        )

    def _execute(
        self, point: SweepPoint, duration_s: float, *, reset: bool
    ) -> _Attempt:
        """Steps 1-5 of a point; returns the attempt, good or bad."""
        attempt = _Attempt(
            point=point,
            name=self._settings.next_name(point.key, self._sweep_id, self._used_names),
        )
        if duration_s <= 0:
            return self._fail(attempt, f"duration_s must be > 0, got {duration_s}")
        try:
            note = self._actuator.layout_note()
        except Exception as exc:  # noqa: BLE001 - an unchecked layout is not clean
            note = f"the layout check failed ({type(exc).__name__}: {exc})"
        if note is not None:
            # Roles may resolve to the wrong widgets; no point may start on this.
            return self._fail(attempt, f"not the measurement layout: {note}")
        if reset:
            failure = self._reset_block()
            if failure is not None:
                return self._fail(attempt, failure)

        # (2) apply the window, then compare the app's read-back with the request.
        parameters = point.parameters
        try:
            readbacks = self._actuator.apply_point(parameters)
        except Exception as exc:  # noqa: BLE001 - reported, never raised onwards
            return self._fail(attempt, f"applying the parameters failed: {exc!r}")
        refusal = self._check_readback(attempt, parameters, readbacks)
        if refusal is not None:
            # Refused before recording: no recording spent, no junk file left.
            return self._fail(attempt, refusal, status=PointStatus.INVALID)

        # The size expectation — step (5)'s input — is computed here, from the
        # specification only: a failed store still logs what the size should have been.
        period: float | None = None
        if parameters.emissions_per_profile and parameters.prf_us:
            period = parameters.emissions_per_profile * parameters.prf_us * 1e-6
            period += PERIOD_OVERHEAD_S
        profiles = profiles_for_duration(duration_s, period) if period else None
        if profiles:
            attempt.expected_bytes = self._signature.expected_bytes(
                parameters.gates, profiles
            )

        # (3) name the file and run the cycle.
        self._used_names.add(attempt.name)
        try:
            stored, result = self._actuator.try_record_and_store(
                attempt.name, duration_s, self._directory
            )
        except Exception as exc:  # noqa: BLE001 - reported, never raised onwards
            return self._fail(attempt, f"the record/store cycle raised {exc!r}")
        if not stored:
            return self._fail(attempt, f"the record/store cycle failed: {result}")
        path = Path(str(result))
        attempt.file = path
        self._used_names.add(path.name)
        if not path.is_file():
            return self._fail(
                attempt,
                f"the cycle reported a store to {path.name}, which does not exist",
                status=PointStatus.INVALID,
            )
        try:
            attempt.size_bytes = path.stat().st_size
        except OSError as exc:
            return self._fail(
                attempt,
                f"{path.name} could not be measured: {exc}",
                status=PointStatus.INVALID,
            )

        # (4) the file is the authority: decode it.
        try:
            attempt.decoded = _decode(path)
        except Exception as exc:  # noqa: BLE001 - a file we cannot read is not a point
            return self._fail(
                attempt,
                f"{path.name} could not be decoded: {exc!r}",
                status=PointStatus.INVALID,
            )

        # (5) the size check, through the log's own record, so the rule stays owned
        # there and a later reader can re-derive the verdict from the log alone.
        record = self._record(attempt, PointStatus.OK)
        plausible = record.size_is_plausible(self._signature)
        if plausible is None:
            return self._fail(
                attempt,
                f"the size signature cannot verify this point: {attempt.size_bytes} B "
                "were stored but no expected size can be derived (the point carries no "
                "emissions_per_profile and prf_us) — an unchecked size is not evidence "
                "that this file is the point's data",
                status=PointStatus.INVALID,
            )
        if not plausible:
            ratio = (attempt.size_bytes or 0) / (attempt.expected_bytes or 1)
            return self._fail(
                attempt,
                f"the stored file is {attempt.size_bytes} B where the signature "
                f"expects ~{attempt.expected_bytes} B for {parameters.gates} gates "
                f"x {profiles} profiles ({ratio:.2f}x, limit "
                f"{self._signature.factor:g}x): a file this far off the signature is "
                "not this point's data",
                status=PointStatus.INVALID,
            )
        attempt.status = PointStatus.OK
        return attempt

    def _reset_block(self) -> str | None:
        """Press ``CLEAR_AND_RESTART`` and confirm a startable view; ``None`` if clean.

        The guard the 8.3 MB point is paid for: a block that still holds an earlier
        recording is stored under *this* point's name, far off the signature. Every
        press is bracketed by polled waits, never by a sleep; an unreadable state or a
        strip that has not come back somewhere startable within :data:`RESET_TIMEOUT_S`
        refuses the point rather than pressing blind.
        """
        try:
            state = self._actuator.strip_state()
        except Exception as exc:  # noqa: BLE001 - reported as a reason
            return f"the strip state could not be read ({type(exc).__name__}: {exc})"
        if state.view is StripView.RECORDING:
            # A leftover recording must not survive into this point: stop it first, so
            # it can never be stored under this point's name.
            try:
                self._actuator.press(StripControl.STOP)
            except Exception as exc:  # noqa: BLE001 - reported as a reason
                return f"stopping the running recording failed ({exc!r})"
        if state.view not in STARTABLE_VIEWS:
            # Never press blindly into an unrecognised view (or one left recording):
            # give it the bounded window to settle, then refuse.
            state, failure = self._poll_startable()
            if state is None:
                return failure
        if state.view not in STARTABLE_VIEWS:
            return (
                f"the strip is in the {state.view.value!r} view, not a startable one "
                f"({[v.value for v in STARTABLE_VIEWS]}): the point is refused"
            )
        try:
            self._actuator.press(StripControl.CLEAR_AND_RESTART)
        except Exception as exc:  # noqa: BLE001 - reported as a reason
            return f"the pre-point block reset failed ({type(exc).__name__}: {exc})"
        state, failure = self._poll_startable()
        if state is None:
            return failure
        if state.view not in STARTABLE_VIEWS:
            return (
                f"after CLEAR_AND_RESTART the strip is in the {state.view.value!r} "
                f"view after {RESET_TIMEOUT_S:.0f} s: the block was not reset, so the "
                "point is refused rather than stored into a possibly stale block"
            )
        return None

    def _poll_startable(self) -> tuple[StripState | None, str | None]:
        """Poll (bounded inside the actuator) for a startable view, or say why not."""
        try:
            state = self._actuator.wait_for_view(
                STARTABLE_VIEWS, timeout_s=RESET_TIMEOUT_S
            )
        except Exception as exc:  # noqa: BLE001 - a wedged view is refused, not retried
            return None, (
                f"waiting {RESET_TIMEOUT_S:.0f} s for a startable strip view failed "
                f"({type(exc).__name__}: {exc})"
            )
        return state, None

    def _check_readback(
        self,
        attempt: _Attempt,
        parameters: ParameterSet,
        readbacks: Mapping[ParamRole, str],
    ) -> str | None:
        """Compare the app's read-back with the request; a ``str`` refuses the point.

        The gate count is the one that decides: with the manual's auto-resolution /
        auto-gates flags set the app recomputes it behind a silent write (805 requested
        read back as 474 in the wrong write order), so a move beyond
        :data:`GATE_DRIFT_LIMIT` means this window is not the planned one. The
        resolution read-back is logged alongside it; the achieved pitch comes from the
        stored file, which is the authority.
        """
        gates_text = readbacks.get(ParamRole.GATES)
        if gates_text is None:
            return "no gate count in the read-back: the window cannot be confirmed"
        try:
            attempt.readback_gates = int(str(gates_text).strip())
        except ValueError:
            return f"the gate read-back {gates_text!r} is not a number"
        drift = gate_drift(parameters.gates, attempt.readback_gates)
        if abs(drift) > GATE_DRIFT_LIMIT:
            return (
                f"the app read back {attempt.readback_gates} gates for the "
                f"{parameters.gates} requested ({drift:+.1%}, limit "
                f"{GATE_DRIFT_LIMIT:.0%}): the window was clamped, so the point cannot "
                "represent the planned depth"
            )
        resolution_text = readbacks.get(ParamRole.RESOLUTION)
        if resolution_text is not None:
            attempt.readback_resolution = str(resolution_text)
        return None

    def _record(self, attempt: _Attempt, status: PointStatus) -> SweepPointRecord:
        """The log record for an attempt, at the status it ended with."""
        return SweepPointRecord(
            sweep_id=self._sweep_id,
            key=attempt.point.key,
            name=attempt.name,
            status=status,
            requested=attempt.point.parameters,
            readback_gates=attempt.readback_gates,
            readback_resolution=attempt.readback_resolution,
            file_path=None if attempt.file is None else str(attempt.file),
            file_size_bytes=attempt.size_bytes,
            expected_size_bytes=attempt.expected_bytes,
            decoded=attempt.decoded,
            failure=attempt.reason,
        )

    def _report(self, attempt: _Attempt) -> None:
        """Append one log entry — valid or not — when a log path is set.

        A log failure never changes an outcome and never raises: the file is on disk
        and the outcome is returned either way, and the failure is kept on
        :attr:`log_errors` so it cannot go unnoticed.
        """
        if self._log_path is None:
            return
        try:
            append_entry(self._log_path, self._record(attempt, attempt.status))
        except Exception as exc:  # noqa: BLE001 - logging must not fail a point
            self.log_errors.append(
                f"{attempt.name}: the log entry could not be appended "
                f"({type(exc).__name__}: {exc})"
            )

    def _fail(
        self, attempt: _Attempt, reason: str, *, status: PointStatus | None = None
    ) -> _Attempt:
        """Mark an attempt not-ok and return it — the only way a point ends badly."""
        attempt.status = status or PointStatus.FAILED
        attempt.reason = reason
        return attempt

    @staticmethod
    def _outcome(attempt: _Attempt) -> PointOutcome:
        """The immutable outcome for an attempt; ``ok`` is derived from its status."""
        return PointOutcome(
            point=attempt.point,
            ok=attempt.status is PointStatus.OK,
            file=attempt.file,
            status=attempt.status,
            reason=attempt.reason,
            decoded=attempt.decoded,
        )


def _decode(path: Path, channel: int | None = None) -> DecodedBlock:
    """Decode a stored point into the log's :class:`DecodedBlock`.

    The one place this module touches the committed ``.BDD`` reader
    (``udv_echo_process.io.dop.bdd.read``), so a change in that reader's surface is
    absorbed here and nowhere else.

    ``channel`` selects the channel to read; ``None`` means *the only channel carrying
    data in the file*. The reader reports one artifact per channel that produced
    profiles, and a multi-channel file is refused rather than guessed at — reading the
    wrong channel's block is the easiest possible way to "prove" a write failed.
    ``resolution_index`` and ``emissions_per_profile`` are left unset: the reader
    exposes neither op word 10 nor word 14, and this module never derives a check
    quantity from the file it is checking. ``depth_mm`` is the file's own depth axis
    rounded to whole mm. Raises ``ValueError`` for a file with no channel data, with
    more than one channel's, or with a block lacking the gate count the log requires.
    """
    name = Path(path).name
    streams = tuple(_read_bdd(Path(path)).recording.streams)
    if channel is not None:
        streams = tuple(
            s for s in streams if int(s.acquisition.channel.device_channel) == channel
        )
        if not streams:
            raise ValueError(f"{name} carries no data for channel {channel}")
    if len(streams) > 1:
        carried = [int(s.acquisition.channel.device_channel) for s in streams]
        raise ValueError(
            f"{name} carries {len(streams)} channels ({carried}); a point's block is "
            "one channel's, so the channel must be named explicitly rather than guessed"
        )
    if not streams:
        raise ValueError(f"{name} carries no decoded channel data")

    stream = streams[0]
    config = stream.config
    mapping: dict[str, object] = {
        "channel": int(stream.acquisition.channel.device_channel),
        "n_gates": config.n_gates,
        "depth_mm": None if config.max_depth_mm is None else round(config.max_depth_mm),
        "resolution_mm": config.resolution_mm,
        "sound_speed_ms": config.sound_speed_ms,
        "prf_us": _period_us(config.pulse_repetition_freq_hz),
        "burst_length": config.burst_length,
        "source_freq_khz": config.source_freq_khz,
        "size_bytes": Path(path).stat().st_size,
    }
    try:
        return DecodedBlock.from_mapping(mapping)
    except ValueError as exc:
        raise ValueError(f"{name} decoded a block the log cannot hold: {exc}") from exc


def _period_us(freq_hz: float | None) -> float | None:
    """The µs *period* for a PRF frequency — this application stores a period."""
    return None if not freq_hz else 1e6 / float(freq_hz)
