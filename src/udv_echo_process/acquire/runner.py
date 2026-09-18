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
  ``OK`` only when a file was stored, decoded, matched the signature **and** was
  verified against the request;
- **a point that leaves the application's state unverified or unstartable stops the
  run.** A layout that is not the measurement one, an overlay that is not
  recognised, a block that will not come back startable, a parameter write that
  raised, a cycle that failed or claimed a store that is not there: none of those
  say *this point was bad*, they say *we no longer know where the application is*.
  Continuing from there burns every remaining point into an identical failure — a
  wedged application answers every point the same way — so the runner trips a
  circuit breaker instead: the remaining points are **not attempted**, the outcome
  tuple ends at the aborting point, and that outcome carries ``aborted=True`` and
  says so in its reason (:data:`ABORT_NOTE`). A point refused *for its own sake* —
  a clamped read-back, a file whose size is off the signature, a file that will not
  decode, a verification mismatch — is a normal point failure: the application
  finished that point and its state is known, so the sweep continues. The boundary
  is the stored file: everything before a file exists is the application's state and
  trips the breaker, everything after it is evidence about that file and does not;
- **on a panel the runner does not recognise, the policy is refuse and stop — never
  press.** A posted press ignores modality, so a button on an unknown panel is the
  one press that does real damage (``Replace ?`` answered *yes*, a strip press
  landing on a dialog). The actuator answers and reports the panels it owns
  (:data:`~udv_echo_process.acquire.actuator.OVERLAY_ANSWERS`); anything else — and
  a Store dialog at a moment the runner is not mid-store — refuses the point
  without pressing anything and trips the same breaker. No button on a panel that
  is not one of the known ones is ever pressed;
- **the stored file is checked against the request, not only against its size.**
  After a successful store the file goes to
  :mod:`udv_echo_process.acquire.verify` (``verify_stored_point``), which reads the
  file's own words and compares them with the point's requested parameters: the
  size signature says *a file this size*, only the words say *this file*. A
  verification failure invalidates the point, with the mismatch strings in the
  reason, and a verification that **cannot run** is the same refusal: the check is
  mandatory, because a stored file whose words nobody read is not this point's data.
  The name is imported with a guard for the broken-install case rather than to make
  verification optional — that branch refuses the point, it does not pass it with a
  note. (This is the one check this module cannot make for itself: its own decode
  leaves the op words' raw index and emissions unset — see :func:`_decode` — and a
  rule may never be derived from the file it is checking.)

**The expectation is built from the specification, never from the file.** The
expected size is ``signature.expected_bytes(requested_gates, profiles)``, with
``profiles = T / period`` from the point's own ``emissions_per_profile`` and
``prf_us`` (the measured ``emissions × PRF + ~1 ms`` law). An expectation taken
from the file under test would simply agree with it — 6,000 stale profiles would
"expect" the 8.3 MB they held.

That guard is a **gross contamination check** and is treated as one: at the
production window length a factor-2 band admitted a block holding 0.62 of what the
period law predicted, so passing it means "not grossly contaminated", not "this is
the window that was asked for". The retained window is answered instead by the
stored file's own profile timestamps — count, span and the achieved period — which
land in the record as ``decoded.n_profiles``/``span_s``/``timing.achieved_s``, and
are what ``requested_duration_s``/``retained_fraction``/``block_wrapped`` are read
against. A wrapped block therefore appears in the record as what it is (a shorter
observation) rather than as a size anomaly a later reader has to re-derive.

A failure anywhere in :meth:`SweepRunner.run_point` returns an outcome; it never
raises. A failure that says nothing about the application's state fails that one
point; a failure that leaves the state unverified or unstartable additionally trips
the circuit breaker, so :meth:`SweepRunner.run` stops there instead of spending the
rest of the plan on a wedged application. Only the
:class:`~udv_echo_process.acquire.actuator.Actuator` protocol is
driven — no ``ctypes``, ``win32``, ``pywinauto`` or ``PIL``, no control id, no
screen coordinate, no absolute path — so the module imports on any host and a fake
actuator is a complete substitute.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import numpy as np

from udv_echo_process.acquire.actuator import (
    OVERLAY_ANSWERS,
    STARTABLE_VIEWS,
    Actuator,
    OverlayKind,
    ParamRole,
    StripControl,
    StripState,
    StripView,
)
from udv_echo_process.acquire.config import (
    ChannelSetting,
    ParameterSet,
    ProfileTiming,
    RecordSettings,
)
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
from udv_echo_process.acquire.snapshot import DialogParameters, InstrumentSnapshot
from udv_echo_process.io.dop.bdd import read as _read_bdd

#: The word-level check. ``acquire/verify.py`` ships in this package, so *not
#: importable* is a broken install rather than a verdict about a stored file — and the
#: one thing this module must never do is call a point good because the rule that could
#: have refused it was missing. The name is resolved at call time (``_verify_stored``),
#: and the import failure is kept as a guard rather than an import error so that state
#: stays testable; what it costs is a refused point, never an `OK` one.
try:
    from udv_echo_process.acquire.verify import read_words, verify_stored_point
except ImportError:  # pragma: no cover - a broken install, and it must not pass
    read_words = None  # type: ignore[assignment]
    verify_stored_point = None  # type: ignore[assignment]

__all__ = [
    "ABORT_NOTE",
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

#: The constant term of the manual's profile-period law, ``T_profile ≈ T_tran +
#: T_prf · (16 + N_PRF)``: the transfer term, kept as the 16-emission equivalent of
#: the measured ``~1 ms``. The law is corroborated structurally — word 17 of the
#: parameter block is 16 in every file, i.e. that constant is stored by the
#: application itself (docs/dop3000/udop-automation.md §8, corrected) — so this is
#: the *expectation* the profile count is sized from, never a substitute for the
#: achieved period, which is read back per configuration as the certificate.
PERIOD_OVERHEAD_S = 1e-3

#: The sentence every aborted point's reason carries. An abort is not a worse point
#: failure — it is the run being cut short — and the reason is the only part of that
#: a later reader of the log has, so it says so in words as well as in
#: :attr:`PointOutcome.aborted`.
ABORT_NOTE = (
    "the run stops here: the application's state is not verified, so the remaining "
    "points are not attempted"
)


class SweepActuator(Actuator, Protocol):
    """The :class:`Actuator` surface plus the composed calls a sweep needs.

    ``Actuator`` fixes the primitives; the ordered parameter write, the whole
    record/stop/store cycle, the one reading of the instrument's fixed state and the
    ``Operating parameters`` dialog read are what a sweep calls, and naming them here is what
    lets this module be written and faked against the actuator interface alone.

    ``instrument_snapshot`` and ``read_dialog_parameters`` are **additive**: neither has a
    caller in this module's own cycle, and no existing primitive changed to make room for
    them, so an implementation that satisfied the port before still does — it gains two
    methods.
    """

    def apply_point(self, parameters: ParameterSet) -> Mapping[ParamRole, str]:
        """Apply a window in the committed write order; return the app's read-back."""
        ...

    def ensure_channel(self) -> int:
        """Verify the measurement channel from the dialog and return it."""
        ...

    def read_dialog_parameters(self) -> DialogParameters:
        """Read the three dialog-only facts off the ``Operating parameters`` dialog.

        The **campaign** path needs this and the sweep path does not: the sound speed, the
        first gate and the burst length live in that dialog alone, and ``instrument_snapshot``
        states them only when a caller hands them over (``dialog_parameters=``) — it never
        opens the dialog itself, deliberately, because reading it means a modal the operator
        watches open and closed and the reading's own contract is that it presses nothing.
        So the read is a step of its own, taken *before* the snapshot and handed to it, and a
        caller that skips it gets those three facts as ``unreadable`` with the reason, which
        the compile refuses on rather than proceeding on a declaration
        (``snapshot.SUPPORTED_READ_FACTS``, plan §9.2).

        It is read-only with respect to the configuration — it opens the dialog, reads the
        table and closes it again — and a dialog that states nothing is a reading with a
        ``reason``, never a raise and never a guess.
        """
        ...

    def instrument_snapshot(
        self,
        *,
        routed_channel: int | None,
        dialog_parameters: DialogParameters | None = None,
    ) -> InstrumentSnapshot:
        """Read the instrument's current state, pressing nothing that changes it.

        Read-only with respect to the configuration: it writes no parameter, accepts no
        dialog and selects no channel. Routing to the requested channel is a separate step
        that happens *before* it, and this call hands over what that step established — the
        channel :meth:`ensure_channel` selected and read back, or ``None`` when nothing
        routed one, which the reading then carries as ``unreadable`` rather than as a claim.

        ``dialog_parameters`` is the same kind of hand-over for the three facts only the
        ``Operating parameters`` dialog states (its reader is ``read_dialog_parameters``):
        passing what that step read makes them ``read`` facts, and omitting it carries them as
        ``unreadable`` with the reason. The channel is required and keyword-only so that no
        caller can have a channel taken for granted on its behalf; this one is optional because
        a caller that cannot have read the dialog and one that merely did not are different
        states, and only the second leaves a caller free to say so.

        The reading is the *evidence*: which channel and mode are active, which fixed facts
        the instrument itself states and which nothing can read yet
        (:mod:`~udv_echo_process.acquire.snapshot`).
        """
        ...

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        verify_channel: bool = True,
    ) -> tuple[bool, Path | str]:
        """Record, stop, store as ``name``; ``(True, path)`` or ``(False, reason)``.

        ``verify_channel=False`` skips the dialog read for a point whose run has already
        verified the channel once (:meth:`SweepRunner._verify_channel_once`).
        """
        ...


@dataclass(frozen=True)
class PointOutcome:
    """What one point did: the file, the decoded block, and whether it counts.

    ``ok`` is true only for a point that was stored, decoded, matched the size
    signature **and** verified against the request. A point that is not ok may still
    carry a ``file`` — an invalid file is evidence and is kept — so a non-``None``
    file must never be read as success.

    ``aborted`` is the second, different thing a caller has to see: ``ok=False`` says
    *this point was bad*, ``aborted=True`` says *the application's state is not
    verified and the run was cut short here*, i.e. no later point was attempted and
    the outcome tuple ends at this one (:meth:`SweepRunner.run`). An aborted outcome
    is never ok, and its ``reason`` ends with :data:`ABORT_NOTE`.
    """

    point: SweepPoint | None
    ok: bool
    file: Path | None
    status: PointStatus
    reason: str | None
    decoded: DecodedBlock | None
    aborted: bool = False


@dataclass
class _Attempt:
    """The working record of one point, and the log line's raw material.

    ``status`` is the single source of truth: ``ok`` is derived from it, so a point
    cannot be reported good and logged bad. ``aborted`` is set only by
    :meth:`SweepRunner._fail` with ``abort=True``, and it is the one field that
    reaches the caller as more than this point's own verdict.
    """

    point: SweepPoint
    name: str
    status: PointStatus = PointStatus.FAILED
    #: The window that was asked for, and the period the request implies — the two
    #: inputs the retained fraction and the timing certificate are read against.
    duration_s: float | None = None
    period_s: float | None = None
    file: Path | None = None
    reason: str | None = None
    decoded: DecodedBlock | None = None
    readback_gates: int | None = None
    readback_resolution: str | None = None
    size_bytes: int | None = None
    expected_bytes: int | None = None
    aborted: bool = False
    #: Comparisons the verifier made and *recorded* but did not enforce (word 14).
    advisories: tuple[str, ...] = ()
    #: The covariate fields the verifier enforced for this point.
    enforced_covariates: tuple[str, ...] = ()
    #: The covariate fields it compared without enforcing — a field that was not
    #: declared appears in neither list, because it was never compared.
    advisory_covariates: tuple[str, ...] = ()


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
        *,
        channel: int | None = None,
    ) -> None:
        """Bind a runner to its actuator, its naming and where points land.

        ``signature=None`` means the calibrated default (1.7 B per gate-profile,
        factor 2); ``log_path=None`` returns outcomes without writing a JSONL log.

        ``channel`` is the measurement channel, taken from the one knob
        (:class:`~udv_echo_process.acquire.config.ChannelSetting`): explicit here,
        else ``UDV_CHANNEL``, else the default. It is not a sweep-level detail —
        a stored file holds an independent configuration per channel and a decode
        of the wrong channel's block once "disproved" a write that had worked
        (docs/16 §12, the channel trap) — so the runner names it on every decode
        instead of letting the reader guess between channels.
        """
        self._actuator: SweepActuator = cast(SweepActuator, actuator)
        self._settings = settings
        self._directory = Path(directory)
        self._signature = SizeSignature() if signature is None else signature
        self._log_path = None if log_path is None else Path(log_path)
        self._channel_setting = (
            ChannelSetting() if channel is None else ChannelSetting(channel=channel)
        )
        self._sweep_id = sweep_id_for(datetime.now(tz=UTC).astimezone())
        #: Set once the measurement channel has been read from the dialog for this run.
        self._channel_verified = False
        #: The channel the routing step established, or ``None`` until one has. Kept rather
        #: than discarded because it is the *evidence* a campaign's compile is handed.
        self._routed_channel: int | None = None
        #: Log entries that could not be written. Never silent, never fatal.
        self.log_errors: list[str] = []
        self._used_names: set[str] = set()

    @property
    def channel(self) -> int:
        """The measurement channel every point is decoded on."""
        return self._channel_setting.channel

    @property
    def routed_channel(self) -> int | None:
        """The channel the routing step established, or ``None`` until one routed.

        :meth:`~udv_echo_process.acquire.runner.SweepActuator.ensure_channel` returns the
        channel the application's own dialog confirmed, and that return is exactly what a
        campaign's reading has to be handed (``instrument_snapshot(*, routed_channel)``)
        before a compile will accept the channel as established: the reading cannot read the
        channel itself — doing so costs the menubar gesture the routing step pays — so a caller
        that routed and threw the value away has nothing the compile can accept, and it refuses
        with "the reading carries no routed channel" instead of recording points under a
        channel nobody verified (``campaign._routed_channel``).

        Kept here rather than re-read by the caller so that the channel the dialog was opened
        for and the channel a compile is told about cannot become two different readings of one
        dialog. ``None`` until the first routing happened, and the routing happens once per run
        (:meth:`_verify_channel_once`), so it is also the run's own answer to "which channel did
        we actually measure on".
        """
        return self._routed_channel

    def _verify_channel_once(self) -> None:
        """Verify the measurement channel from the dialog, once per run.

        The channel is the one thing a stored block cannot be *checked* against after the
        fact: another channel's block decodes as a valid point that is not this point
        (docs/16 §12), which is why it is read from the dialog before the first recording is
        spent. Doing it for **every** point re-opened the same modal once per point while
        proving nothing new — nothing inside a run changes the channel, and the decode proves
        the channel of every file afterwards, refusing a file that carries no data for the
        channel it is asked for. So the dialog opens once, and a mid-run channel change still
        fails the point that follows it, on its own file.

        The dialog's answer is kept on :attr:`routed_channel` rather than dropped: it is the
        value a campaign's compile is handed as evidence, and re-reading the dialog for that
        caller would open the same modal a second time for a value this call already has.
        """
        if self._channel_verified:
            return
        self._routed_channel = self._actuator.ensure_channel()
        self._channel_verified = True

    def run_point(
        self, point: SweepPoint, duration_s: float, *, reset: bool = True
    ) -> PointOutcome:
        """Run one point end to end and return its outcome; never raise.

        In order: reset the block (unless ``reset=False``) and confirm a startable
        view; apply the parameters and compare the read-back with the request; record
        and store under a free name; decode the stored file; check its size against
        the signature; verify the file's own words against the request; append one log
        entry, valid or not; return. Only a caller that has just reset the block
        itself should pass ``reset=False`` — a stale block is stored under this
        point's name otherwise.

        Two kinds of bad point come back, and a sweep must tell them apart: a failure
        of the point itself (``ok=False``, ``aborted=False`` — the application is
        where it was and the next point may run) and a failure that leaves the
        application's state unverified or unstartable (``aborted=True`` — nothing
        later may be attempted, see :meth:`run`).
        """
        try:
            attempt = self._execute(point, duration_s, reset=reset)
        except Exception as exc:  # noqa: BLE001 - reported as an outcome below
            name = self._settings.point_name(point.key, self._sweep_id)
            attempt = _Attempt(point=point, name=name)
            # An exception out of the cycle is the least verified state there is:
            # nothing here knows how far the application got.
            self._fail(
                attempt,
                f"the point cycle raised {type(exc).__name__}: {exc}",
                abort=True,
            )
        self._report(attempt)
        return self._outcome(attempt)

    def run(
        self, definition: SweepDefinition, duration_s: float
    ) -> tuple[PointOutcome, ...]:
        """Plan ``definition`` and run points in order until the breaker trips.

        The points come from :func:`plan_sweep`; a list that is already planned — a
        campaign's, which may also carry a window per point — goes through
        :meth:`run_points` instead.

        ``T = duration_s``. A point that fails for its own sake — a clamped read-back,
        a file whose size is off the signature, a file that will not decode, a
        verification mismatch — is logged and the next one starts: one contaminated
        window costs one point. A point that leaves the application's state unverified
        or unstartable is where the run **ends**: the remaining points are not
        attempted at all, so the returned tuple is shorter than the plan and its last
        outcome carries ``aborted=True`` (and :data:`ABORT_NOTE` in its reason). A
        caller distinguishing "this point was bad" from "the run was cut short" only
        has to look at that flag.

        Raises ``ValueError`` when ``duration_s`` is not positive or the definition
        cannot be planned (``plan_sweep`` refuses a point the app would clamp).
        """
        if duration_s <= 0:
            raise ValueError(f"duration_s must be > 0, got {duration_s}")
        return self.run_points(plan_sweep(definition), duration_s)

    def run_points(
        self, points: Iterable[SweepPoint], duration_s: float | None = None
    ) -> tuple[PointOutcome, ...]:
        """Run an explicit sequence of points, in the given order, until the breaker trips.

        The seam a **campaign** needs. A sweep's points are its rungs, so :meth:`run` expands
        them from the definition; a campaign's points are an explicit list — each with its own
        label and, when the campaign says so, its own window — and they arrive already planned
        (``acquire.campaign.plan_campaign``). ``duration_s`` forces one window on every point;
        ``None`` uses each point's own ``duration_s``, which is what that caller passes, since
        a campaign may plan different windows for different points while a
        :class:`~udv_echo_process.acquire.plan.SweepDefinition`'s points never differ.

        The loop and its rules are :meth:`run`'s, unchanged: a point that fails for its own
        sake is logged and the next one starts, and a point that leaves the application's
        state unverified or unstartable **ends** the run — the remaining points are not
        attempted, so the returned tuple is shorter than ``points`` and its last outcome
        carries ``aborted=True``.

        Raises ``ValueError`` when ``duration_s`` is given and is not positive.
        """
        if duration_s is not None and duration_s <= 0:
            raise ValueError(f"duration_s must be > 0, got {duration_s}")
        outcomes: list[PointOutcome] = []
        for point in points:
            window = point.duration_s if duration_s is None else duration_s
            outcome = self.run_point(point, window)
            outcomes.append(outcome)
            if outcome.aborted:
                break  # the state is not verified: the rest of the list is void
        return tuple(outcomes)

    def _execute(
        self, point: SweepPoint, duration_s: float, *, reset: bool
    ) -> _Attempt:
        """Steps 1-6 of a point; returns the attempt, good or bad.

        Every return on the application's half of the cycle (the layout, the overlay
        guard, the reset, the write, the store) carries ``abort=True``: those failures
        say the application's state is unknown, not that this point's data was bad.
        From the moment the stored file exists the failures are this file's, and the
        sweep may carry on.
        """
        attempt = _Attempt(
            point=point,
            name=self._settings.next_name(point.key, self._sweep_id, self._used_names),
            duration_s=duration_s,
        )
        if duration_s <= 0:
            return self._fail(attempt, f"duration_s must be > 0, got {duration_s}")
        try:
            note = self._actuator.layout_note()
        except Exception as exc:  # noqa: BLE001 - an unchecked layout is not clean
            note = f"the layout check failed ({type(exc).__name__}: {exc})"
        if note is not None:
            # Roles may resolve to the wrong widgets; no point may start on this, and
            # a layout that is not the measurement one does not fix itself by waiting.
            return self._fail(
                attempt, f"not the measurement layout: {note}", abort=True
            )
        overlay = self._overlay_guard()
        if overlay is not None:
            return self._fail(attempt, overlay, abort=True)
        if reset:
            failure = self._reset_block()
            if failure is not None:
                return self._fail(attempt, failure, abort=True)

        # (2) apply the window, then compare the app's read-back with the request.
        parameters = point.parameters
        # The parameter column is only the column while no panel is over it.
        overlay = self._overlay_guard()
        if overlay is not None:
            return self._fail(attempt, overlay, abort=True)
        try:
            readbacks = self._actuator.apply_point(parameters)
        except Exception as exc:  # noqa: BLE001 - reported, never raised onwards
            # A write that raised left the app's model unknown: no point may follow it.
            return self._fail(
                attempt, f"applying the parameters failed: {exc!r}", abort=True
            )
        refusal = self._check_readback(attempt, parameters, readbacks)
        if refusal is not None:
            # Refused before recording: no recording spent, no junk file left. The
            # application answered and is where it was, so the sweep continues.
            return self._fail(attempt, refusal, status=PointStatus.INVALID)

        # The size expectation — step (5)'s input — is computed here, from the
        # specification only: a failed store still logs what the size should have been.
        period: float | None = None
        if parameters.emissions_per_profile and parameters.prf_us:
            period = parameters.emissions_per_profile * parameters.prf_us * 1e-6
            period += PERIOD_OVERHEAD_S
        attempt.period_s = period
        profiles = profiles_for_duration(duration_s, period) if period else None
        if profiles:
            attempt.expected_bytes = self._signature.expected_bytes(
                parameters.gates, profiles
            )

        # (3) the channel, once per run, before the first recording is spent. Anchored here
        # rather than per point: see `_verify_channel_once`.
        try:
            self._verify_channel_once()
        except Exception as exc:  # noqa: BLE001 - an unverified channel is not a point
            return self._fail(
                attempt, f"the measurement channel could not be verified: {exc}", abort=True
            )

        # (4) name the file and run the cycle.
        self._used_names.add(attempt.name)
        overlay = self._overlay_guard()  # the guard the cycle's own presses cannot undo
        if overlay is not None:
            return self._fail(attempt, overlay, abort=True)
        try:
            stored, result = self._actuator.try_record_and_store(
                attempt.name,
                duration_s,
                self._directory,
                verify_channel=False,  # verified once per run, below and before the first
            )
        except Exception as exc:  # noqa: BLE001 - reported, never raised onwards
            # The step is unaccounted for: a dialog may be up and a recording may
            # still be running, so the next point cannot be trusted with the app.
            return self._fail(
                attempt, f"the record/store cycle raised {exc!r}", abort=True
            )
        if not stored:
            return self._fail(
                attempt, f"the record/store cycle failed: {result}", abort=True
            )
        path = Path(str(result))
        attempt.file = path
        self._used_names.add(path.name)
        if not path.is_file():
            return self._fail(
                attempt,
                f"the cycle reported a store to {path.name}, which does not exist: the "
                "step is unverifiable, so the application's state cannot be trusted",
                status=PointStatus.INVALID,
                abort=True,
            )
        try:
            attempt.size_bytes = path.stat().st_size
        except OSError as exc:
            # The file is there and its size is not: that is this file's problem, and
            # the application is past the point of the cycle.
            return self._fail(
                attempt,
                f"{path.name} could not be measured: {exc}",
                status=PointStatus.INVALID,
            )

        # (4) the file is the authority: decode it — on the channel this run
        # measures on, from the one knob, never guessed between channels.
        try:
            attempt.decoded = _decode(path, self._channel_setting.channel)
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
        # (6) the file's own words, against the request. The size signature says "a file
        # this size"; only the file's words say "the file this point asked for".
        return self._verify_stored(attempt, path, parameters)

    def _verify_stored(
        self, attempt: _Attempt, path: Path, parameters: ParameterSet
    ) -> _Attempt:
        """Step (6): the stored file's words against the point's requested parameters.

        ``acquire/verify.py`` is imported above with a broken-install guard, so ``None``
        here means the sibling module is not there at all. The point is then **refused**:
        keeping the size guard's verdict and saying so in the reason still logged a
        point `OK` whose words nobody had read, and a size signature is a gross
        contamination check — it cannot say whether this file is this point's data. A
        point refused here fails for its own sake (the file is as bad as it is going to
        be), so it does not trip the circuit breaker.

        A verifier that raises is not "unavailable": it produced no verdict at all,
        which is worse than a mismatch, so the point is refused rather than passed on
        a shrug. Either way this is the file's problem, not the application's, so it
        never trips the circuit breaker.

        The channel is forwarded from the one knob the decode above used. Without it
        the reader defaults to channel 1 while the decode read the run's channel, so
        every point of a channel-2 run comes back with mismatches that belong to
        another channel's block — *gates: requested 10, found 20* for a file whose
        channel 2 is exactly right. A point refused on another channel's words is
        still a wasted live slot, and the fix belongs here rather than in the caller:
        the two reads of one file must name the same channel.
        """
        if verify_stored_point is None:
            return self._fail(
                attempt,
                f"{path.name} was never checked against this point's requested "
                "parameters: the word-level check (udv_echo_process.acquire.verify) "
                "is not available in this install, so the size signature is the only "
                "evidence there is — and a size cannot say whether this file is this "
                "point's data",
                status=PointStatus.INVALID,
            )
        try:
            verification = verify_stored_point(
                path,
                parameters,
                channel=self._channel_setting.channel,
                check_covariates=True,
            )
        except Exception as exc:  # noqa: BLE001 - no verdict is not a pass
            return self._fail(
                attempt,
                f"{path.name} could not be verified against the request "
                f"({type(exc).__name__}: {exc}): a file whose words were never read is "
                "not this point's data",
                status=PointStatus.INVALID,
            )
        # Kept whether or not the verdict is ok: the comparisons the verifier made but
        # does not enforce are the evidence a later reader cannot reconstruct (word 14's
        # 150 against a plan's 52 is the case), and an invalidated point is exactly
        # where someone will want them.
        attempt.advisories = tuple(
            str(item) for item in (getattr(verification, "advisories", None) or ())
        )
        attempt.enforced_covariates = tuple(
            str(item)
            for item in (getattr(verification, "enforced_covariates", None) or ())
        )
        # What the check *compared* without enforcing, for the same reason: word 14
        # being absent from the advisories must be readable as "it agreed" rather than
        # "nobody declared it".
        attempt.advisory_covariates = tuple(
            str(item)
            for item in (getattr(verification, "advisory_covariates", None) or ())
        )
        if not verification.ok:
            mismatches = tuple(str(item) for item in (verification.mismatches or ()))
            detail = "; ".join(mismatches) or "the verifier named no mismatch"
            return self._fail(
                attempt,
                f"{path.name} does not say what the point asked for: {detail}",
                status=PointStatus.INVALID,
            )
        attempt.status = PointStatus.OK
        return attempt

    def _overlay_guard(self) -> str | None:
        """Ask the actuator to clear any overlay; ``None`` when it is safe to press.

        The rule this enforces: **nothing is pressed on a panel the runner does not
        recognise**. A posted press ignores modality, so a button on an unknown panel
        is the one press that can do real damage (``Replace ?`` answered *yes*, a strip
        press landing on a dialog), and no amount of retrying makes an unknown panel
        known. The actuator answers the panels it owns — the warnings in
        :data:`~udv_echo_process.acquire.actuator.OVERLAY_ANSWERS` — and reports what
        was up; the Store dialog is reported back *untouched* because its fields are
        the caller's, and at this point in the cycle the runner is not mid-store, so
        its presence means the run is out of step with the application.

        A refusal here is an abort, not a point failure: an unrecognised panel is not
        this point's fault and it is still up for the next one.
        """
        try:
            kind = self._actuator.answer_overlay()
        except Exception as exc:  # noqa: BLE001 - an unchecked overlay is not clean
            return (
                f"the overlay check failed ({type(exc).__name__}: {exc}), so the "
                "application's state is not known"
            )
        if kind is None:
            return None
        try:
            known = kind in OVERLAY_ANSWERS
        except TypeError:  # unhashable: not a panel kind this runner knows
            known = False
        if not known:
            return (
                f"an unrecognised panel ({kind!r}) is up: no button on a panel that is "
                "not one of the known ones is pressed, so this point is refused"
            )
        if kind is OverlayKind.STORE_DIALOG:
            return (
                "the Store dialog is up when the runner is not mid-store: the run is "
                "out of step with the application, and nothing is typed into it"
            )
        return None

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
        """The log record for an attempt, at the status it ended with.

        The window evidence is assembled here from what the point was asked for and what
        the file turned out to hold: ``requested_duration_s`` (the request),
        ``block_cap_profiles`` (the configuration it ran under), ``timing`` (the
        period the request implies, against the period the profile timestamps measured)
        and the decoded block's own ``n_profiles``/``span_s``. Together those are the
        difference between "the plan says 12 s" and "the file covers 8.4 s of it" —
        which the app's ring behaviour makes two different facts.
        """
        duration = attempt.duration_s
        return SweepPointRecord(
            sweep_id=self._sweep_id,
            key=attempt.point.key,
            name=attempt.name,
            status=status,
            requested=attempt.point.parameters,
            timing=ProfileTiming(
                target_s=attempt.period_s,
                achieved_s=(
                    None if attempt.decoded is None
                    else attempt.decoded.achieved_period_s
                ),
            ),
            requested_duration_s=duration if duration and duration > 0 else None,
            block_cap_profiles=self._settings.max_profiles_per_block,
            readback_gates=attempt.readback_gates,
            readback_resolution=attempt.readback_resolution,
            file_path=None if attempt.file is None else str(attempt.file),
            file_size_bytes=attempt.size_bytes,
            expected_size_bytes=attempt.expected_bytes,
            decoded=attempt.decoded,
            failure=attempt.reason,
            covariate_advisories=attempt.advisories,
            covariates_advisory=attempt.advisory_covariates,
            covariates_enforced=attempt.enforced_covariates,
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
        self,
        attempt: _Attempt,
        reason: str,
        *,
        status: PointStatus | None = None,
        abort: bool = False,
    ) -> _Attempt:
        """Mark an attempt not-ok and return it — the only way a point ends badly.

        ``abort=True`` is the circuit breaker: it marks the attempt as one that leaves
        the application's state unverified or unstartable, which is what
        :meth:`run` stops on. The reason carries :data:`ABORT_NOTE` as well as the
        flag, because the reason is the only part of an abort that the log keeps.
        """
        attempt.status = status or PointStatus.FAILED
        attempt.reason = f"{reason}; {ABORT_NOTE}" if abort else reason
        attempt.aborted = abort
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
            aborted=attempt.aborted,
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
    ``depth_mm`` is the file's own depth axis rounded to whole mm. Raises ``ValueError``
    for a file with no channel data, with more than one channel's, or with a block
    lacking the gate count the log requires.

    What the record says about the *window* comes from the same read: the profile count,
    the span from the first profile's timestamp to the last, and the full-span effective
    interval — ``span / (count - 1)``, the convention ``analysis/rpm.py`` calibrates this
    timebase on — with the median adjacent interval and its maximum relative deviation
    kept beside it as diagnostics. Those are measurements of what the file holds — the
    app's block is a ring, so they are the only honest answer to "how long was this
    observation".

    Two words the canonical reader does not expose are filled differently.
    ``resolution_index`` stays unset (the reader reports the pitch, and this module
    never derives a check quantity from the file it is checking).
    ``emissions_per_profile`` *is* read, through ``acquire/verify.py``'s word reader
    and only for the record — see :func:`_stored_emissions`; the same value decides
    nothing here.
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
    channel_read = int(stream.acquisition.channel.device_channel)
    times = np.asarray(stream.data.time_s, dtype=np.float64)
    profile_count = int(times.shape[0])
    span_s = float(times[-1] - times[0]) if profile_count else None
    achieved_period_s: float | None = None
    median_interval_s: float | None = None
    interval_deviation: float | None = None
    if profile_count >= 2:
        # The convention `analysis/rpm.py` calibrates on for this timebase: the full-span
        # effective interval, never the median adjacent interval. The DOP timestamps are
        # quantized, so the median is the dominant timestamp quantum rather than the
        # sampling period (rpm.py measures a 0.562% RPM shift from calibrating on it).
        # The median and its maximum relative deviation are kept as diagnostics.
        intervals = np.diff(times)
        effective = float((times[-1] - times[0]) / (profile_count - 1))
        achieved_period_s = effective if effective > 0 else None
        median = float(np.median(intervals))
        if median > 0:
            median_interval_s = median
            interval_deviation = float(np.max(np.abs(intervals - median))) / median
    mapping: dict[str, object] = {
        "channel": channel_read,
        "n_gates": config.n_gates,
        "depth_mm": None if config.max_depth_mm is None else round(config.max_depth_mm),
        "resolution_mm": config.resolution_mm,
        "sound_speed_ms": config.sound_speed_ms,
        "prf_us": _period_us(config.pulse_repetition_freq_hz),
        "burst_length": config.burst_length,
        "source_freq_khz": config.source_freq_khz,
        "size_bytes": Path(path).stat().st_size,
        # The window the file actually covers — the authority on how much observation
        # the point bought, as opposed to how much it asked for. The period is the
        # full-span effective interval (see `_decode`).
        "n_profiles": profile_count,
        "span_s": span_s,
        "achieved_period_s": achieved_period_s,
        "median_interval_s": median_interval_s,
        "interval_deviation": interval_deviation,
        # Word 14: read here because `bdd.ChannelConfig` has no field for it (the
        # canonical reader's docstring says so), and the variance axis is worth having
        # in the record.
        "emissions_per_profile": _stored_emissions(Path(path), channel_read),
    }
    try:
        return DecodedBlock.from_mapping(mapping)
    except ValueError as exc:
        raise ValueError(f"{name} decoded a block the log cannot hold: {exc}") from exc


def _stored_emissions(path: Path, channel: int) -> int | None:
    """Word 14 of the channel that measured, or ``None`` when it cannot be read.

    Read through ``acquire/verify.py``'s word reader because the canonical reader has
    no field for it (``io/dop/bdd.py``'s docstring lists word 14 among the words it
    verifies but does not decode). ``read_words`` addresses the operation table's own
    channel slot, which is what a manual-mode acquisition's channel means — see its
    docstring for what it is not: on a multiplexed recording those slots do not
    describe the recording's channels.

    Never raises, and never refuses a decode: the value is recorded evidence, not a
    rule, so a channel word that cannot be read leaves the field unset rather than
    failing a stored point that is otherwise perfectly readable.
    """
    if read_words is None:  # pragma: no cover - a broken install
        return None
    return read_words(path, channel).emissions_per_profile


def _period_us(freq_hz: float | None) -> float | None:
    """The µs *period* for a PRF frequency — this application stores a period."""
    return None if not freq_hz else 1e6 / float(freq_hz)
