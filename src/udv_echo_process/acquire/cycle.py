"""The record → stop → store cycle, composed from routine calls and one dialog commit.

This is the message route's own cycle, as an object rather than a script. Every part of it has been measured on the live
application: the strip routines take the form object this instance was primed with and write the application's own command
codes (so no input starts or stops a recording), the store raises a dialog whose name field is a plain edit, and that
dialog's `Accept` takes a posted press because a modal is the active window.

What the class adds over a sequence of calls is the discipline the rest of this package already applies: a name already
used is refused before anything is recorded, a store that produces no file is a failure rather than a hope, and a stored
file is only accepted when it decodes to a stream. The caller and the dialog are injected, so all of that is testable
without an instrument.

**A pointer is not a capability.** A routine address is only usable against the process *instance* it was observed on:
the same pid reused by another process, a relaunched application, or a different build all invalidate it, and calling
through a stale owning object is how an access violation is produced rather than an error. So the cycle carries a
:class:`CycleBinding` — the identity, and the owner and routine references with the observation they came from — and
refuses, before the first call, when the live identity disagrees with it or when a guard is missing. The identity reader,
the owner check and the strip reader are injected; nothing here knows how to read a process. The same facts are checked
again before **every** dispatch and before the dialog commit, so a restart during a recording stops the cycle instead of
naming the next point's file from another instance's dialog.

**A dispatched `ok` is not a state transition.** The application answers a routine call whether or not it acted, so the
strip is read back after a start and after a stop, the expected view has to arrive within a bounded wait, and the report
says which view was last *confirmed*. :attr:`RoutineCycle.last_report` keeps that report on every exit, success or
refusal, so a caller can serialize evidence instead of the reason alone.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from udv_echo_process.acquire.actuator import StripState, StripView
from udv_echo_process.models.base import ValueModel

__all__ = [
    "CycleBinding",
    "CycleReport",
    "CycleRoutines",
    "CycleStage",
    "Decoder",
    "IdentityReader",
    "ObservedAddress",
    "OwnerCheck",
    "ProcessIdentity",
    "RoutineCaller",
    "RoutineCycle",
    "SpanMeter",
    "StoreDialog",
    "StripReader",
]


@dataclass(frozen=True)
class CycleRoutines:
    """The three routine addresses and the object this instance's primed form is at.

    The addresses come from the machine-local table; ``form`` comes from observing the application — a recorded value is
    stale for a different instance by construction, so it is carried explicitly rather than remembered anywhere.
    """

    record: int
    store: int
    form: int


class ProcessIdentity(ValueModel):
    """Which process instance, and which build, the addresses were observed on.

    ``created_ns`` is the process *creation* stamp, and it is what makes ``pid`` usable: a pid is reused by the operating
    system, so a matching pid with another creation time is a different process and every pointer observed on the old one
    is stale. Both are required — an unknown identity is not a permissive one.
    """

    #: Process id the observation was taken in.
    pid: int = Field(ge=1)
    #: Creation stamp of that process, in the unit the reader reports (ns since the epoch here).
    created_ns: int = Field(ge=1)
    #: Digest of the executable the addresses were measured against (``BridgeTable.image_sha256``).
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ObservedAddress(ValueModel):
    """One address, and where it was observed from.

    ``source`` is metadata rather than a check: it records the observation a reader can go back to (a table entry, a
    primed-widget census), so a binding can be audited instead of trusted. A zero address is *constructible* and is
    refused by the cycle as ``cycle_owner_null`` / ``cycle_routine_null:<field>``, because a null pointer is a fact worth
    naming rather than a construction error.
    """

    address: int = Field(ge=0)
    source: str = Field(min_length=1)


class CycleBinding(ValueModel):
    """Everything a dispatch through this cycle is conditional on.

    The routines come from the machine-local table and the owner from observing the application; a recorded value is
    stale for a different instance by construction, so the whole binding is carried explicitly rather than remembered
    anywhere.
    """

    identity: ProcessIdentity
    #: The owning object the strip routines are called with (the primed form/panel pointer).
    owner: ObservedAddress
    record: ObservedAddress
    store: ObservedAddress


class RoutineCaller(Protocol):
    """Execute one routine call inside the application and report whether it ran."""

    def __call__(self, address: int, form: int) -> dict: ...


class IdentityReader(Protocol):
    """Read the live process identity: the pid, its creation stamp and the running build's digest.

    A host reads this from the process it is attached to. It must answer for the *current* instance — a cached identity
    defeats the whole check — and may answer ``None`` when the process is gone, which the cycle refuses.
    """

    def __call__(self) -> ProcessIdentity | None: ...


class OwnerCheck(Protocol):
    """Whether ``owner`` is still a readable, mapped object in the live application.

    ``True`` only: anything else (a raise included) is ``cycle_owner_unreadable``. A truthy non-boolean is
    ``cycle_owner_evidence_invalid``, because a check that did not answer yes-or-no did not check anything.
    """

    def __call__(self, owner: int) -> bool: ...


class StripReader(Protocol):
    """Read the strip's current view — structure in, view derived out.

    ``StripState`` is what a host reads (it carries the slider); ``StripView`` (or its value string) is accepted for a
    reader that only has the classified view. ``None`` is a refusal, never an assumption.
    """

    def __call__(self) -> StripState | StripView | str | None: ...


class StoreDialog(Protocol):
    """Name the block a store just raised a dialog for, and commit it."""

    def commit(self, name: str) -> bool: ...


class Decoder(Protocol):
    """What counts as a stored recording: a file that decodes to at least one stream."""

    def __call__(self, path: Path) -> int: ...


class SpanMeter(Protocol):
    """How much time the stored block spans, from the block's own timestamps.

    **It is not the recording window.** Measured 2026-10-24: a store issued after a 4 s recording wrote 397.17 s of
    profiles, because the application stores the buffer it has been filling, not the interval between our record and stop.
    The earlier ~20 s blocks were 20 s of buffer, not 20 s of window. So a span is reported for the record and is not used
    to judge the recording; the artifact's structure and its own geometry are what can be judged.

    A cycle cannot know this from its own clock: the stop is a separate attachment, and the recording keeps writing until
    the application processes it. Measured: a 4 s request produced a 20.657 s block, because each routine call costs an
    attachment. So the duration is read from the artifact, which is the only honest source — and the limit below is an
    allowance for that overhead rather than a tolerance on the request.

    Measured attempt at removing the overhead (2026-10-23): issuing record, holding the application's GUI thread for 3 s
    inside the stub, then stop and store, produced no dialog and no file. The application consumes its command slot on its
    own loop, so holding that loop collapses three commands into the last one. The window therefore cannot be shortened
    this way, and the overhead is a property of the route until a caller can span two boundaries without blocking.
    """

    def __call__(self, path: Path) -> float: ...


class CycleStage(str, Enum):
    """Where a cycle was when it stopped, so a refusal is attributable to a step.

    The stage in a :class:`CycleReport` is the *last* step entered: a refusal during the pre-flight checks reports
    ``preflight``, one that happened while confirming a start reports ``record``, and so on.
    """

    #: Before any call: name, binding, guards, parameters, identity, owner, initial strip view.
    PREFLIGHT = "preflight"
    #: The start routine was (or was about to be) dispatched, and the start confirmed.
    RECORD = "record"
    #: The stop routine was (or was about to be) dispatched, and the stop confirmed.
    STOP = "stop"
    #: The store routine was (or was about to be) dispatched.
    STORE = "store"
    #: The store dialog was committed (or was about to be).
    COMMIT = "commit"
    #: The written file: its presence, its decode count, its span.
    VERIFY = "verify"
    #: The cycle stored an artifact and returned it.
    DONE = "done"


class CycleReport(ValueModel):
    """What the cycle did, so a caller can report evidence rather than an inference.

    Immutable and attached to the cycle as :attr:`RoutineCycle.last_report` on **every** exit — including the refusals
    that happen before the first call. ``stage`` says where the cycle stopped, ``last_view`` is the last strip view it
    actually confirmed, and ``recorded_span_s`` is declared here (it used to be assigned to a field the class did not
    have) so serializing the report does not lose it.
    """

    name: str
    stage: CycleStage = CycleStage.PREFLIGHT
    recorded: bool = False
    stopped: bool = False
    store_requested: bool = False
    dialog_committed: bool = False
    stored: bool = False
    streams: int = Field(default=0, ge=0)
    #: The stored block's own elapsed time — the buffer's age, not the window (see :class:`SpanMeter`).  A malformed
    #: reading (NaN, infinity, a negative interval) is refused by the cycle before a report is built, so a report can
    #: only ever carry a real span.
    recorded_span_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    #: The last strip view this cycle confirmed by reading it back.
    last_view: StripView | None = None
    reason: str | None = None


def _default_span(path: Path) -> float:
    """The block's own elapsed time, from its first to its last profile."""
    from udv_echo_process.io.dop import bdd

    times = bdd.read(path).recording.streams[0].data.time_s
    return float(times[-1] - times[0]) if len(times) > 1 else 0.0


def _default_decoder(path: Path) -> int:
    """Count the streams a stored block decodes to, using the repository's own reader."""
    from udv_echo_process.io.dop import bdd

    bundle = bdd.read(path)
    return len(getattr(bundle.recording, "streams", []) or [])


#: Characters that make a token a **path** rather than a stem: a separator or a drive colon chooses a file
#: outside the directory the run was told to watch, which is the one thing the store name must not do.
_NAME_PATH_CHARS = frozenset("/\\:")
#: Characters Windows does not carry in a name at all. Refused rather than replaced.
_NAME_FORBIDDEN_CHARS = frozenset('<>"|?*')
#: Device names Windows reserves whatever the extension — ``CON.BDD`` is still the console.
_NAME_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
#: What the store appends, so a token that already ends in it would name ``x.BDD.BDD``.
_STORE_SUFFIX = ".bdd"


def _name_problem(name: str) -> str | None:
    """Why ``name`` is not one file stem this cycle may store under, or ``None`` when it is.

    The cycle appends ``.BDD`` to whatever it is handed and then watches that path, so the token is a
    *target*, not a label: one carrying a separator or a drive colon chooses a file outside the directory
    the run was told to watch; an embedded NUL makes the path probe raise instead of answer; and a token
    that already carries the suffix names ``x.BDD.BDD``. Each is refused **as given** — nothing is
    trimmed, normalised or repaired, because a repaired token stores a file under a name the caller never
    supplied and every later comparison would then agree with itself.

    Dots inside the stem and non-ASCII names are ordinary and stay allowed: this is a shape check, not a
    naming registry. The reason quotes the token character for character, so a refusal is checkable
    against what was actually asked for.
    """
    if not name:
        return f"store_name_invalid:{name}:empty"
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        return f"store_name_invalid:{name}:control"
    if name.strip() != name:
        return f"store_name_invalid:{name}:padded"
    if any(character in _NAME_PATH_CHARS for character in name):
        return f"store_name_invalid:{name}:path"
    if any(character in _NAME_FORBIDDEN_CHARS for character in name):
        return f"store_name_invalid:{name}:forbidden"
    if name in (".", ".."):
        return f"store_name_invalid:{name}:relative"
    if name.lower().endswith(_STORE_SUFFIX):
        return f"store_name_invalid:{name}:suffix"
    if name.split(".", 1)[0].lower() in _NAME_RESERVED:
        return f"store_name_invalid:{name}:reserved"
    return None


class RoutineCycle:
    """Record, stop and store through the application's own routines, then commit its dialog.

    ``duration_s`` is the recording window: the stop call is issued after it, because the application has no "record for
    N seconds" command. A failed routine call does not raise — it stops the cycle and returns the reason, because a caller
    that has to unwind mid-cycle needs the state, not an exception it cannot see.

    **Fail-closed by default.** Construction stays compatible with an unbound caller, but a cycle with no binding, or with
    any of the three guards missing, refuses before its first call (``cycle_binding_missing`` /
    ``cycle_guard_missing:<identity|owner_valid|read_strip>``). There is deliberately no unguarded mode: the press-based
    route is a different object, and a flag here would be the stale-pointer hazard with an opt-out. A producer can ask the
    same question without running a cycle: :attr:`binding` is public and read-only, and
    :meth:`configuration_problem` is a pure check of what the cycle holds — it reads nothing live.
    """

    def __init__(
        self,
        *,
        caller: RoutineCaller,
        routines: CycleRoutines,
        dialog: StoreDialog,
        binding: CycleBinding | None = None,
        identity: IdentityReader | None = None,
        owner_valid: OwnerCheck | None = None,
        read_strip: StripReader | None = None,
        decode: Decoder | None = None,
        measure_span: SpanMeter | None = None,
        max_span_s: float | None = None,
        stop_settle_s: float = 1.5,
        store_settle_s: float = 1.5,
        store_timeout_s: float = 30.0,
        state_timeout_s: float = 5.0,
        poll_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._caller = caller
        self._routines = routines
        self._dialog = dialog
        #: What every dispatch is conditional on.  ``None`` is not "unchecked": it is a refusal at call time.
        self._binding = binding
        self._identity = identity
        self._owner_valid = owner_valid
        self._read_strip = read_strip
        self._decode = decode or _default_decoder
        self._measure_span = measure_span or _default_span
        #: An optional ceiling on the reported span, off by default.  It exists because callers can need one (a buffer that
        #: has been filling for hours is worth noticing), but it is *not* a window check: the span is the buffer's age, so
        #: refusing on it would refuse perfectly good points whose buffer happened to be older.
        self._max_span_s = None if max_span_s is None else float(max_span_s)
        self._stop_settle_s = stop_settle_s
        self._store_settle_s = store_settle_s
        self._store_timeout_s = store_timeout_s
        #: How long a start or a stop may take to show up in the strip before it is a refusal.  With ``poll_s`` at zero the
        #: read happens once, which is what keeps a fake-driven test from waiting on a clock.
        self._state_timeout_s = state_timeout_s
        self._poll_s = poll_s
        self._sleep = sleep
        #: The report of the last invocation, reset at the start of each one so a caller can never read a stale victory.
        self._last_report: CycleReport | None = None

    @property
    def last_report(self) -> CycleReport | None:
        """The report of the most recent :meth:`try_record_and_store`, or ``None`` before the first."""
        return self._last_report

    @property
    def binding(self) -> CycleBinding | None:
        """The binding this cycle will dispatch under, or ``None`` when it has none.

        Public and read-only so a factory can refuse an unusable cycle before it opens the application.
        """
        return self._binding

    # -- the guards ------------------------------------------------------
    def configuration_problem(self) -> str | None:
        """Why this cycle must not dispatch at all, or ``None`` — **pure, and it reads nothing live**.

        It answers the three questions a producer can settle without touching the instrument: is there a binding, are
        the three guards present and callable, and does the binding name the same pointers the routines do. Every check is
        on values already held, so calling it cannot attach to a process, read a strip or check an owner.
        """
        if self._binding is None:
            return "cycle_binding_missing"
        for name, guard in (
            ("identity", self._identity),
            ("owner_valid", self._owner_valid),
            ("read_strip", self._read_strip),
        ):
            if guard is None:
                return f"cycle_guard_missing:{name}"
            if not callable(guard):
                return f"cycle_guard_invalid:{name}"
        return self._binding_problem()

    def _binding_problem(self) -> str | None:
        """The binding's own defects: a null pointer, or a value that contradicts the routines."""
        binding = self._binding
        if binding is None:  # narrowed by configuration_problem(); kept so this reads on its own
            return "cycle_binding_missing"
        for field in ("record", "store"):
            if getattr(binding, field).address == 0:
                return f"cycle_routine_null:{field}"
        if binding.owner.address == 0:
            return "cycle_owner_null"
        for field, address in (
            ("record", self._routines.record),
            ("store", self._routines.store),
            ("owner", self._routines.form),
        ):
            if getattr(binding, field).address != address:
                return f"cycle_binding_conflict:{field}"
        return None

    def _identity_problem(self) -> str | None:
        """Whether the live instance and build are still the ones this binding was observed on."""
        binding = self._binding
        if binding is None or self._identity is None:  # narrowed by configuration_problem(); kept so this reads on its own
            return "cycle_guard_missing:identity"
        try:
            seen = self._identity()
        except Exception as exc:  # noqa: BLE001 - an unreadable identity is a refusal, not a crash
            return f"cycle_identity_unavailable:{type(exc).__name__}"
        if seen is None:
            return "cycle_identity_unavailable:null"
        if not isinstance(seen, ProcessIdentity):
            return f"cycle_identity_invalid:{type(seen).__name__}"
        bound = binding.identity
        if seen.pid != bound.pid:
            return f"cycle_pid_changed:{bound.pid}!={seen.pid}"
        if seen.created_ns != bound.created_ns:
            # Same pid, another creation: the pid was reused, so the pointer belongs to a process that is gone.
            return f"cycle_instance_changed:{bound.created_ns}!={seen.created_ns}"
        if seen.image_sha256 != bound.image_sha256:
            return f"cycle_build_changed:{bound.image_sha256[:12]}!={seen.image_sha256[:12]}"
        return None

    def _owner_problem(self) -> str | None:
        """Whether the owning object the routines are called with is still readable."""
        binding = self._binding
        if binding is None or self._owner_valid is None:  # narrowed by configuration_problem(); kept so this reads on its own
            return "cycle_guard_missing:owner_valid"
        owner = binding.owner.address
        try:
            readable = self._owner_valid(owner)
        except Exception as exc:  # noqa: BLE001 - an unreadable owner is a refusal, not a crash
            return f"cycle_owner_unreadable:{type(exc).__name__}"
        if readable is True:
            return None
        if not isinstance(readable, bool):
            return f"cycle_owner_evidence_invalid:{type(readable).__name__}"
        return f"cycle_owner_unreadable:0x{owner:x}"

    def _live_problem(self) -> str | None:
        """Both halves of the revalidation, in the order a failure should read: instance, then object."""
        return self._identity_problem() or self._owner_problem()

    # -- the strip -------------------------------------------------------
    def _read_view(self) -> tuple[StripView | None, str | None]:
        """One strip reading, normalised to a view, or a reason it could not be taken."""
        if self._read_strip is None:  # narrowed by configuration_problem(); kept so this reads on its own
            return None, "cycle_guard_missing:read_strip"
        try:
            reading = self._read_strip()
        except Exception as exc:  # noqa: BLE001 - an unreadable strip is a refusal, not a crash
            return None, f"strip_state_unreadable:{type(exc).__name__}"
        if reading is None:
            return None, "strip_state_unreadable:null"
        if isinstance(reading, StripState):
            return reading.view, None
        if isinstance(reading, StripView):
            return reading, None
        if isinstance(reading, str):
            try:
                return StripView(reading), None
            except ValueError:
                return None, f"strip_state_unreadable:{reading}"
        return None, f"strip_state_unreadable:{type(reading).__name__}"

    def _await_view(
        self, target: StripView, stage: CycleStage
    ) -> tuple[StripView | None, str | None]:
        """Read the strip until ``target`` shows up within the bounded wait, or name the view that did not move."""
        seen, problem = self._read_view()
        if problem is not None:
            return None, problem
        if seen is target:
            return seen, None
        waited = 0.0
        while self._poll_s > 0 and waited < self._state_timeout_s:
            problem = self._sleep_or(float(self._poll_s), "state")
            if problem is not None:
                return seen, problem
            waited += float(self._poll_s)
            seen, problem = self._read_view()
            if problem is not None:
                return None, problem
            if seen is target:
                return seen, None
        return seen, f"{stage.value}_not_confirmed:{seen.value if seen else 'unknown'}"

    def _sleep_or(self, seconds: float, what: str) -> str | None:
        """Wait, and report a clock that refuses rather than letting the exception escape the cycle.

        The sleep is injected, so it can fail like any other collaborator. A raise here happens *between* two application
        steps, which makes it exactly the case the every-exit report exists for: the caller needs to know which wait was
        lost and what had already been confirmed.
        """
        try:
            self._sleep(float(seconds))
        except Exception as exc:  # noqa: BLE001 - a broken clock is evidence, not a crash
            return f"cycle_sleep_failed:{what}:{type(exc).__name__}"
        return None

    # -- the dispatch ----------------------------------------------------
    def _dispatch(self, stage: CycleStage, address: int) -> tuple[dict | None, str | None]:
        """Revalidate, then dispatch one routine, reading the answer strictly.

        The revalidation lives here rather than at the top of the cycle because the interesting change is the one that
        happens *during* a recording: a restart between the start and the stop must not be answered by calling the new
        instance's object with the old instance's pointer.
        """
        problem = self._live_problem()
        if problem is not None:
            return None, problem
        try:
            result = self._caller(address, self._routines.form)
        except Exception as exc:  # noqa: BLE001 - a raising caller is evidence, not a crash
            return None, f"{stage.value}_call_raised:{type(exc).__name__}"
        if not isinstance(result, Mapping):
            return None, f"{stage.value}_evidence_invalid:result"
        if "ok" not in result:
            return None, f"{stage.value}_evidence_invalid:ok"
        # Exactly True: the caller says it dispatched, and a truthy stand-in says nothing.
        if result["ok"] is True:
            return dict(result), None
        if result["ok"] is False:
            return None, f"{stage.value}_not_dispatched:{_reason(dict(result))}"
        return None, f"{stage.value}_evidence_invalid:ok"

    def try_record_and_store(
        self, name: str, duration_s: float, directory: Path, *, expected_mode: object = None
    ) -> tuple[bool, Path | str]:
        """Run one cycle. Returns the stored path, or a reason prefixed so a caller can tell the stages apart."""
        self._last_report = None
        name = str(name)  # the report is built from it, so it must never be what raises
        directory = Path(directory)
        #: The facts accumulated so far; every exit builds a fresh immutable report from them.
        facts: dict[str, Any] = {}

        def remember(stage: CycleStage, reason: str | None = None, **extra: Any) -> str | None:
            self._last_report = CycleReport(
                name=name, stage=stage, reason=reason, **{**facts, **extra}
            )
            return reason

        def refuse(stage: CycleStage, reason: str, **extra: Any) -> tuple[bool, str]:
            remember(stage, reason, **extra)
            return False, reason

        # Before the token becomes a path at all: `_name_problem` is the only check that can answer for a
        # name carrying NUL — past this line, ``Path.exists`` would raise instead of refuse.
        problem = _name_problem(name)
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)
        target = directory / f"{name}.BDD"

        if target.exists():
            # A taken name raises the application's overwrite warning, and an unanswered warning wedges the run.
            return refuse(CycleStage.PREFLIGHT, f"store_name_taken:{target.name}")

        # Order matters: what the cycle *is* (binding, guards, pointers) before what it was asked to do, and the null
        # pointers before the contradiction check, so a null is reported as the null it is.
        problem = self.configuration_problem()
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)

        for field, value in (
            ("duration_s", duration_s),
            ("state_timeout_s", self._state_timeout_s),
            ("poll_s", self._poll_s),
            ("stop_settle_s", self._stop_settle_s),
            ("store_settle_s", self._store_settle_s),
            ("store_timeout_s", self._store_timeout_s),
        ):
            if not _bounded(value):
                return refuse(CycleStage.PREFLIGHT, f"cycle_parameter_invalid:{field}")
        if self._poll_s <= 0 and (self._state_timeout_s > 0 or self._store_timeout_s > 0):
            # A wait with no interval is a hot spin, not a bound: the loop would add nothing to its own clock.
            return refuse(CycleStage.PREFLIGHT, "cycle_parameter_invalid:poll_s")

        problem = self._live_problem()
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)

        view, problem = self._read_view()
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)
        facts["last_view"] = view
        if view is not StripView.READY:
            # A recording already running belongs to somebody else, and a held block is data this cycle did not take.
            return refuse(
                CycleStage.PREFLIGHT,
                f"cycle_strip_not_ready:{view.value if view else 'unknown'}",
            )

        _result, problem = self._dispatch(CycleStage.RECORD, self._routines.record)
        if problem is not None:
            return refuse(CycleStage.RECORD, problem)
        view, problem = self._await_view(StripView.RECORDING, CycleStage.RECORD)
        if problem is not None:
            # No confirmed RECORDING view: nothing may record a successful start.
            return refuse(CycleStage.RECORD, problem, last_view=view)
        facts["last_view"] = view
        facts["recorded"] = True

        problem = self._sleep_or(float(duration_s), "window")
        if problem is not None:
            return refuse(CycleStage.RECORD, problem)

        # record and stop are the same handler.
        _result, problem = self._dispatch(CycleStage.STOP, self._routines.record)
        if problem is not None:
            return refuse(CycleStage.STOP, problem)
        view, problem = self._await_view(StripView.STORE, CycleStage.STOP)
        if problem is not None:
            return refuse(CycleStage.STOP, problem, last_view=view)
        facts["last_view"] = view
        facts["stopped"] = True

        problem = self._sleep_or(self._stop_settle_s, "stop_settle")
        if problem is not None:
            return refuse(CycleStage.STOP, problem)

        return self._store_held_block(
            name=name, target=target, facts=facts, remember=remember, refuse=refuse
        )

    def store_completed_block(self, name: str, directory: Path) -> tuple[bool, Path | str]:
        """Store the block the application is already holding — Record, Stop and Clear are out of reach.

        This entry point does not end a recording itself: a finite multiplexed sequence closes
        itself (manual §11), so the application owns the completion and the cycle only owns the store.
        The only routine it can dispatch is :attr:`CycleRoutines.store`, which is what makes that promise
        structural rather than a rule somebody remembers.

        Admission is an **observed** store view — the slider-bearing row :func:`classify_strip_view` names
        :attr:`StripView.STORE`, at any button count, because this entry point presses no button and so
        needs no column binding — plus a name the directory does not already hold and a fresh reading of
        the instance and its owning object. A row is not a completion claim: with ``repeats > 1`` several
        blocks exist and a press route would have to choose one, which is exactly what nothing here does.
        What the block *contains* is settled afterwards by the artifact, not by this method.
        """
        self._last_report = None
        name = str(name)  # the report is built from it, so it must never be what raises
        directory = Path(directory)
        facts: dict[str, Any] = {}

        def remember(stage: CycleStage, reason: str | None = None, **extra: Any) -> str | None:
            self._last_report = CycleReport(
                name=name, stage=stage, reason=reason, **{**facts, **extra}
            )
            return reason

        def refuse(stage: CycleStage, reason: str, **extra: Any) -> tuple[bool, str]:
            remember(stage, reason, **extra)
            return False, reason

        # The same invariant as the recording entry point, in the same place: the token is checked before
        # it is ever joined to the directory, so no path probe, none of the native store and no dialog name
        # can be reached by a token that is not one stem.
        problem = _name_problem(name)
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)
        target = directory / f"{name}.BDD"

        if target.exists():
            # A taken name raises the application's overwrite warning, and an unanswered warning wedges the run.
            return refuse(CycleStage.PREFLIGHT, f"store_name_taken:{target.name}")

        problem = self.configuration_problem()
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)

        # Only the waits this entry point actually uses: it has no window and no stop settle.
        for field, value in (
            ("store_settle_s", self._store_settle_s),
            ("store_timeout_s", self._store_timeout_s),
            ("poll_s", self._poll_s),
        ):
            if not _bounded(value):
                return refuse(CycleStage.PREFLIGHT, f"cycle_parameter_invalid:{field}")
        if self._poll_s <= 0 and self._store_timeout_s > 0:
            return refuse(CycleStage.PREFLIGHT, "cycle_parameter_invalid:poll_s")

        problem = self._live_problem()
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)

        view, problem = self._read_view()
        if problem is not None:
            return refuse(CycleStage.PREFLIGHT, problem)
        facts["last_view"] = view
        if view is not StripView.STORE:
            # Nothing is pressed from this state: a ready row has no block to store, a recording one is
            # somebody else's unfinished acquisition, and unknown/ambiguous are rows no evidence binds.
            return refuse(
                CycleStage.PREFLIGHT,
                f"store_completed_strip_not_store:{view.value if view else 'unknown'}",
            )

        return self._store_held_block(
            name=name, target=target, facts=facts, remember=remember, refuse=refuse
        )

    def _store_held_block(
        self,
        *,
        name: str,
        target: Path,
        facts: dict[str, Any],
        remember: Callable[..., str | None],
        refuse: Callable[..., tuple[bool, str]],
    ) -> tuple[bool, Path | str]:
        """From a held block's store dispatch to the verified file — the tail both entry points share.

        One implementation on purpose: the dispatch, the settle, the revalidation before a name is
        committed, the commit itself, the wait for the application's own file, its decode and its span
        are the same facts whether this process ended the acquisition or found it ended. Two copies
        would be two chances for the store half to drift apart.
        """
        _result, problem = self._dispatch(CycleStage.STORE, self._routines.store)
        if problem is not None:
            return refuse(CycleStage.STORE, problem)
        facts["store_requested"] = True
        problem = self._sleep_or(self._store_settle_s, "store_settle")
        if problem is not None:
            return refuse(CycleStage.STORE, problem)

        # The last check before a name is committed: a dialog raised by another instance would name this point's file.
        problem = self._live_problem()
        if problem is not None:
            return refuse(CycleStage.COMMIT, problem)
        try:
            committed = self._dialog.commit(name)
        except Exception as exc:  # noqa: BLE001 - a raising commit is evidence, not a crash
            return refuse(CycleStage.COMMIT, f"store_dialog_raised:{type(exc).__name__}")
        if committed is not True:
            if not isinstance(committed, bool):
                return refuse(
                    CycleStage.COMMIT,
                    f"store_dialog_evidence_invalid:{type(committed).__name__}",
                )
            return refuse(CycleStage.COMMIT, "store_dialog_not_committed")
        facts["dialog_committed"] = True

        # The file is the application's own evidence; wait for it rather than assuming the commit wrote it.
        waited = 0.0
        while waited < self._store_timeout_s:
            if (_store_file_size(target) or 0) > 0:
                break
            problem = self._sleep_or(self._poll_s, "store_poll")
            if problem is not None:
                return refuse(CycleStage.VERIFY, problem)
            waited += self._poll_s
        size = _store_file_size(target)
        if size is None:
            return refuse(CycleStage.VERIFY, f"store_file_missing:{target.name}")
        if size == 0:
            # A file the application created and wrote nothing into is neither a missing store nor a block: the
            # commit happened and the content did not.  Refused by name **here**, before a decoder is asked about
            # it, because a stream count read out of no bytes is not evidence of anything — and a decoder that
            # answers anyway (a permissive double, another reader) would credit the point with a file that holds
            # nothing.  The size is the store's own evidence, so it is checked as one.
            return refuse(CycleStage.VERIFY, f"store_file_empty:{target.name}")

        try:
            decoded = self._decode(target)
        except Exception as exc:  # noqa: BLE001 - an undecodable block is a failed store, not a crash
            return refuse(CycleStage.VERIFY, f"store_undecodable:{type(exc).__name__}")
        # A count is a count: a negative or non-integer answer is malformed evidence, and it never enters the report.
        if isinstance(decoded, bool) or not isinstance(decoded, int):
            return refuse(
                CycleStage.VERIFY, f"store_decoded_streams_invalid:{type(decoded).__name__}"
            )
        if decoded < 0:
            return refuse(CycleStage.VERIFY, f"store_decoded_streams_invalid:{decoded}")
        streams = decoded
        facts["streams"] = streams
        if streams < 1:
            return refuse(CycleStage.VERIFY, "store_decoded_no_streams")

        try:
            span = float(self._measure_span(target))
        except Exception as exc:  # noqa: BLE001 - an unmeasurable span is a refusal, not a pass
            return refuse(CycleStage.VERIFY, f"store_span_unmeasurable:{type(exc).__name__}")
        # A span is an elapsed time: NaN, infinity and a negative answer are malformed readings, not measurements.
        if not math.isfinite(span) or span < 0.0:
            return refuse(CycleStage.VERIFY, f"store_span_invalid:{span}")
        facts["recorded_span_s"] = span
        if self._max_span_s is not None and span > self._max_span_s:
            # Only when a caller explicitly asks for a ceiling.  The span is the buffer's age, not the window, so this is a
            # "the application was not in the state this run expected" check, not a duration check.
            return refuse(
                CycleStage.VERIFY,
                f"recorded_span_over_limit:{span:.2f}s>{self._max_span_s:.2f}s",
            )

        facts["stored"] = True
        remember(CycleStage.DONE)
        return True, target


def _store_file_size(path: Path) -> int | None:
    """The stored file's size, or ``None`` when there is no file to judge.

    One reading for both the wait and the check after it, and it keeps the two answers apart that matter:
    ``None`` is "nothing arrived" and ``0`` is "a file arrived empty".  An unreadable path is reported the
    same way as an absent one rather than raising out of a cycle whose refusal vocabulary is its output.
    """
    try:
        return path.stat().st_size if path.is_file() else None
    except OSError:  # an unmeasurable path cannot be shown to hold a block
        return None


def _bounded(value: object) -> bool:
    """Whether ``value`` is a finite, non-negative number — the only numeric validation a cycle needs.

    It exists to keep a wait bounded: a NaN or a negative timeout turns a polling loop into either a hot spin or an
    endless one. Nothing here judges a span or a window.
    """
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0.0


def _reason(result: dict) -> str:
    errors = result.get("errors") or []
    if errors:
        return str(errors[0])
    return str(result.get("status") or "unknown")
