"""The bridge route as a :class:`~udv_echo_process.acquire.runner.SweepActuator` implementation.

The record/stop/store cycle has been driven through the application's **own** handlers — measured, with
the artifact as the only oracle (`.hermes/scratch/rea-live-controls-20261019/` holds that evidence).
This module makes that cycle selectable from the runner, and nothing else: every primitive still comes
from the GUI actuator, so a point that changes parameters writes them exactly as before.

Three deliberate separations, each of which the tests pin:

- **Vendor facts are not repository content.** Handler addresses, command codes, the ABI, the command
  slot and the accepted build digest live in a table outside the repository
  (:func:`load_table`, ``UDV_BRIDGE_TABLE``).  Without a table this route refuses by name; it never
  falls back to a guess, and it never carries a default address.
- **Execution is supplied, not embedded.** Patching another process and dispatching on its GUI thread
  is a *callable* the operator provides (:class:`BridgeDispatch`); the package owns the request, the
  evidence contract and the refusals.  A host with no such callable gets ``bridge_runner_not_configured``
  instead of a half-executed cycle.
- **The evidence is the artifact.** A dispatch's report is only credited when it says a file was
  stored, that the decoded configuration matched the request, that the target's identity did not
  change, and that the file on disk still hashes to what the dispatch reported.  Anything less is a
  failure with a reason, which is what makes this usable for a sweep rather than for one sitting.

Import safety: this module imports nothing Windows-specific and nothing from ``driver``, so
``udv_echo_process.acquire`` stays importable on any host.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from udv_echo_process.acquire.actuator import STORE_TIMEOUT_S, ProcessMode
from udv_echo_process.acquire.config import (
    BRIDGE_TABLE_ENV_VAR,
    bridge_path_from_environment,
    bridge_table_default_path,
)

__all__ = [
    "BRIDGE_OPERATIONS_REQUIRED",
    "BRIDGE_TABLE_ENV",
    "BRIDGE_TABLE_SCHEMA",
    "BridgeActuator",
    "BridgeDispatch",
    "BridgeDispatchSlot",
    "BridgeEvidence",
    "BridgeOperation",
    "BridgeRefused",
    "BridgeRequest",
    "BridgeSetter",
    "BridgeTable",
    "BridgeUnavailable",
    "BridgeValueCommit",
    "BridgeValueDispatch",
    "default_table_path",
    "evidence_from_report",
    "load_table",
]

#: Environment variable naming the machine-local operation table. Declared in ``config`` — the one
#: module allowed to read the environment — and re-exported here so a caller sets one name.
BRIDGE_TABLE_ENV = BRIDGE_TABLE_ENV_VAR
#: The only table generation this module understands.  A different one is refused, never migrated.
BRIDGE_TABLE_SCHEMA = "udv-bridge-operations-v1"
#: Operations a point's cycle needs; a table without them is refused by the missing name.
BRIDGE_OPERATIONS_REQUIRED = ("record", "stop", "store")


class BridgeUnavailable(Exception):
    """This route cannot be used, with a reason from a fixed vocabulary.

    The reason strings are the interface: a caller (or a log a human reads later) can tell a missing
    table from a foreign build from an unconfigured host without parsing a sentence.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BridgeRefused(RuntimeError):
    """A cycle was refused by evidence, after the point was already dispatched."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BridgeOperation(BaseModel):
    """One allowlisted operation: the handler that sets a command, and the command it sets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    handler: int = Field(ge=0, description="address of the state-change handler")
    code: int = Field(
        ge=0, le=255, description="value written into the shared command slot"
    )
    signature: str = Field(
        "", description="leading bytes at the handler, hex, as decoded"
    )


class BridgeDispatchSlot(BaseModel):
    """Where the pending command lives and which member states it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slot_pointer: int = Field(ge=0)
    status_offset: int = Field(ge=0)


class BridgeSetter(BaseModel):
    """One parameter's own setter and change notification, as addresses in the measured build.

    The vendor's fields are committed by calling the control's setter with the value and then running
    its change notification — not by setting text.  Both addresses are measured, never derived, and the
    bounds are the range the application accepts for that field.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Optional: the attachment resolves these for the running process, which is the authority.  A
    #: table may carry them as a fallback for a host whose discovery cannot answer.
    setter: int | None = Field(default=None, ge=0)
    notify: int | None = Field(default=None, ge=0)
    setter_signature: str = ""
    notify_signature: str = ""
    minimum: float | None = None
    maximum: float | None = None


class MenuRowEffect(str, Enum):
    """What pressing a row is known to do — the classification a caller consents to.

    The categories exist because one measured press of ``preferences.assisted_mode`` rewrote five
    acquisition parameters (PRF 600 -> 303, gates 42 -> 735, resolution 2.220 -> 0.123, velocity factor
    1.00 -> 0.50, emissions 50 -> 150).  "Assisted mode" reads like a UI mode and is in fact a preset
    switch, which is exactly the kind of row an unattended sweep must not press by accident.
    """

    #: Paints something (grids, cursors, axis choice).  Safe: no setting and no data changes.
    DISPLAY = "display"
    #: Enables or disables a processing step; the sweep may legitimately want either state.
    FILTER = "filter"
    #: Changes a mode the acquisition depends on, with no preset applied.
    MODE = "mode"
    #: Applies a whole configuration, like ``assisted_mode`` above.  Needs explicit consent.
    PRESET = "preset"
    #: Opens a dialog that must then be answered and closed.  Needs explicit consent.
    DIALOG = "dialog"
    #: Not classified yet.  A press is refused as unavailable rather than guessed at.
    UNKNOWN = "unknown"


#: Effects a caller may press without asking for permission first.
UNGUARDED_EFFECTS = (MenuRowEffect.DISPLAY, MenuRowEffect.FILTER)


class BridgeMenuRow(BaseModel):
    """One pressable row: which overlay it lives in, and where it sits inside that overlay.

    A row is addressed by **position**, not by ordinal: several overlays are two-column, so "the first row"
    names nothing in particular, while the offset from the overlay's own top-left is stable for one build.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    menu: str = Field(min_length=1, description="the overlay's name in the table's order")
    offset: tuple[int, int] = Field(description="pixels from the overlay's top-left to the row")
    component: str | None = Field(default=None, description="the form component, for the record")
    effect: MenuRowEffect = Field(
        default=MenuRowEffect.UNKNOWN,
        description="what pressing it does; only DISPLAY and FILTER are unguarded",
    )


class BridgeMenuRoutines(BaseModel):
    """The two routines that show and hide a menu overlay, and this build's menu order.

    ``enter`` takes the menu index in EAX (Delphi's ``register`` convention) and ``leave`` takes nothing;
    both are measured addresses.  ``order`` names the indices, because a menu number whose meaning lives
    only in the table is not something a caller can be expected to get right — measured on the instrument,
    the order is ``File, Preferences, Parameters, Compute, Display, Filters, Cursors, Tools, Help, Mpx,
    UDV_MD`` for indices 1..11.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enter: int = Field(ge=0, description="address of the routine that shows overlay #index")
    leave: int = Field(ge=0, description="address of the routine that hides the current overlay")
    order: tuple[str, ...] = Field(
        default=(), description="menu names in index order; index = position + 1"
    )
    count: int | None = Field(default=None, ge=1, description="indices the build accepts")

    @property
    def indices(self) -> dict[str, int]:
        return {name: position + 1 for position, name in enumerate(self.order)}

    def index_of(self, menu: str | int) -> int:
        """The index for a menu, by name or by number, or a refusal that names the request."""
        limit = self.count if self.count is not None else (len(self.order) or None)
        if isinstance(menu, int) and not isinstance(menu, bool):
            index = menu
        else:
            index = self.indices.get(str(menu), 0)
            if not index:
                raise BridgeUnavailable(f"bridge_menu_index:{menu}")
        if index < 1 or (limit is not None and index > limit):
            raise BridgeUnavailable(f"bridge_menu_index:{menu}")
        return index


class BridgeTable(BaseModel):
    """The machine-local facts this route needs, validated as a whole.

    ``image_sha256`` is the build the addresses were measured against. A table is only usable on that
    build, and :class:`BridgeActuator` checks the caller's digest against it rather than trusting that
    the operator kept the pair together.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: str = Field(alias="schema")
    image_sha256: str
    caption_prefix: str = ""
    abi: dict[str, Any] = Field(default_factory=dict)
    dispatch: BridgeDispatchSlot
    operations: dict[str, BridgeOperation]
    #: Per-parameter setters, by role name (``emissions_per_profile`` …).  Empty for a table that only
    #: carries the command operations, which is what a record-only host needs.
    setters: dict[str, BridgeSetter] = Field(default_factory=dict)
    #: The menu overlay routines, when the build's addresses are known.  Optional: a table that only
    #: carries the record/store cycle stays valid, and a caller that asks for a menu gets
    #: ``bridge_menu_missing`` rather than an invented address.
    menu: BridgeMenuRoutines | None = None
    #: Rows a caller may ask for by name, e.g. ``filters.moving_average``.  Positions are a property of the
    #: build, so they are machine-local like the addresses; a name that is absent is a refusal, never a guess.
    rows: dict[str, BridgeMenuRow] = Field(default_factory=dict)

    def operation(self, name: str) -> BridgeOperation:
        try:
            return self.operations[name]
        except KeyError:
            raise BridgeUnavailable(f"bridge_table_operation:{name}") from None


def default_table_path() -> Path | None:
    """Where the table is expected when the caller named none, or ``None`` when nowhere is known.

    The location is machine-local by design: ``%LOCALAPPDATA%`` on Windows, and nothing on a host that
    has no such notion — a checkout must never be the place vendor facts are looked for.
    """
    return bridge_table_default_path()


def load_table(path: str | Path | None = None) -> BridgeTable:
    """Load and validate the operation table, or refuse with a reason.

    Precedence: the argument, then :data:`BRIDGE_TABLE_ENV`, then :func:`default_table_path`.  Each
    step is named in the refusal so an unconfigured host is distinguishable from a broken table.
    """
    if path is None:
        configured = bridge_path_from_environment(BRIDGE_TABLE_ENV_VAR)
        if configured:
            path = configured
        else:
            candidate = bridge_table_default_path()
            if candidate is None or not candidate.is_file():
                raise BridgeUnavailable("bridge_table_not_configured")
            path = candidate
    location = Path(path)
    if not location.is_file():
        raise BridgeUnavailable(f"bridge_table_missing:{location.as_posix()}")
    try:
        raw = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeUnavailable(
            f"bridge_table_unreadable:{location.as_posix()}:{exc}"
        ) from None
    if not isinstance(raw, Mapping):
        raise BridgeUnavailable("bridge_table_invalid:not an object")
    found = raw.get("schema")
    if found != BRIDGE_TABLE_SCHEMA:
        raise BridgeUnavailable(f"bridge_table_schema:{found}")
    try:
        table = BridgeTable.model_validate(dict(raw))
    except ValidationError as exc:  # the error carries the detail the refusal needs
        raise BridgeUnavailable(f"bridge_table_invalid:{exc}") from None
    for name in BRIDGE_OPERATIONS_REQUIRED:
        if name not in table.operations:
            raise BridgeUnavailable(f"bridge_table_operation:{name}")
    return table


@dataclass(frozen=True)
class BridgeRequest:
    """What a dispatch is asked to do — the whole of it, so the report can be checked against it."""

    name: str
    duration_s: float
    directory: Path
    expected_mode: str
    channel: int | None
    verify_channel: bool
    table_digest: str
    operations: tuple[str, ...] = BRIDGE_OPERATIONS_REQUIRED
    extras: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "duration_s": self.duration_s,
            "directory": self.directory.as_posix(),
            "expected_mode": self.expected_mode,
            "channel": self.channel,
            "verify_channel": self.verify_channel,
            "table_digest": self.table_digest,
            "operations": list(self.operations),
            "extras": dict(self.extras),
        }


@dataclass(frozen=True)
class BridgeValueCommit:
    """One numeric write asked of the machine-local value dispatch.

    ``previous`` is the application's own text for the field before the attempt, carried so the
    dispatch's report can be checked against it and so a restore asks for a value that was *observed*
    rather than assumed.
    """

    role: str
    value: float
    previous: str
    table_digest: str
    setter: int | None
    notify: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "value": self.value,
            "previous": self.previous,
            "table_digest": self.table_digest,
            "setter": self.setter,
            "notify": self.notify,
        }


@runtime_checkable
class BridgeValueDispatch(Protocol):
    """The machine-local numeric commit: call the field's setter, then its change notification.

    Returns ``committed`` (the dispatch believes it wrote), ``setter_calls`` (exactly one, or the
    call is refused), and ``readback`` when it could read the field afterwards.  The actuator does not
    trust ``committed``: it reads the field itself through the GUI half and decides on that.
    """

    def __call__(self, request: BridgeValueCommit) -> Mapping[str, Any]: ...


@runtime_checkable
class BridgeDispatch(Protocol):
    """The machine-local execution: take a request, return the route's report.

    Implementations live outside this repository (they embed vendor addresses and patch a process).
    The report is the shape :func:`evidence_from_report` reads; a dispatch that returns anything else
    fails the point rather than passing it through.
    """

    def __call__(self, request: BridgeRequest) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class BridgeEvidence:
    """What a dispatch's report is allowed to mean — parsed, then checked."""

    stored: bool
    stored_path: Path | None
    stored_sha256: str | None
    config_matches: bool | None
    identity_unchanged: bool | None
    reason: str | None
    raw: Mapping[str, Any]


def _as_number(text: object) -> float | None:
    try:
        return float(str(text).strip())
    except TypeError, ValueError:
        return None


def _same_numeric(text: object, value: float | None) -> bool:
    """Whether the application's own text states ``value`` — the only thing that counts as a write."""
    observed = _as_number(text)
    if observed is None or value is None:
        return False
    return math.isclose(observed, float(value), rel_tol=1e-9, abs_tol=1e-9)


def _missing(key: str) -> BridgeUnavailable:
    return BridgeUnavailable(f"bridge_evidence_incomplete:{key}")


def evidence_from_report(report: Mapping[str, Any]) -> BridgeEvidence:
    """Parse a dispatch report, refusing by key rather than assuming a shape.

    Two accepted shapes, because both exist in the evidence: ``stored`` as an object (the route's
    report) and ``stored`` as a flag with the path at the top level.  A stored point must name its
    file; a report that does not is incomplete, not stored.
    """
    if not isinstance(report, Mapping):
        raise _missing("report")
    stored_field = report.get("stored")
    if isinstance(stored_field, Mapping):
        stored = bool(stored_field.get("stored"))
        stored_path = stored_field.get("stored_path")
        stored_sha = stored_field.get("stored_sha256")
        reason = stored_field.get("reason") or report.get("reason")
    elif isinstance(stored_field, bool):
        stored = stored_field
        stored_path = report.get("stored_path")
        stored_sha = report.get("stored_sha256")
        reason = report.get("reason")
    else:
        raise _missing("stored")
    decoded = report.get("decoded") or {}
    config_matches = (
        decoded.get("config_matches") if isinstance(decoded, Mapping) else None
    )
    if config_matches is None:
        config_matches = report.get("config_matches")
    identity_unchanged = report.get("identity_unchanged")
    if stored:
        if not stored_path:
            raise _missing("stored_path")
        if identity_unchanged is None:
            raise _missing("identity_unchanged")
    blockers = report.get("blockers") or ()
    if reason is None and blockers:
        reason = "; ".join(str(item) for item in blockers)
    return BridgeEvidence(
        stored=stored,
        stored_path=Path(str(stored_path)) if stored_path else None,
        stored_sha256=str(stored_sha) if stored_sha else None,
        config_matches=None if config_matches is None else bool(config_matches),
        identity_unchanged=None
        if identity_unchanged is None
        else bool(identity_unchanged),
        reason=None if reason is None else str(reason),
        raw=report,
    )


class BridgeActuator:
    """``SweepActuator`` whose record/store cycle is the bridge route; everything else delegated.

    Construction is explicit and opt-in: the caller hands over the GUI actuator to delegate to, the
    dispatch that performs the cycle, and (optionally) the table and the digest of the build the
    addresses were measured against.  Nothing here touches Windows, so the class is exercised on any
    host against fakes.
    """

    def __init__(
        self,
        inner: Any,
        *,
        dispatch: BridgeDispatch | None = None,
        table: BridgeTable | None = None,
        table_path: str | Path | None = None,
        target_digest: str | None = None,
        channel: int | None = None,
        numeric_writes: bool = False,
        value_dispatch: BridgeValueDispatch | None = None,
        cycle: StoreCycle | None = None,
    ) -> None:
        self._inner = inner
        self._dispatch = dispatch
        #: The message route's own cycle.  When present it replaces the host dispatch for record/stop/store, so a
        #: bridge run stops delegating its cycle to a runner that presses buttons.
        self._cycle = cycle
        self._value_dispatch = value_dispatch
        #: Set once a write could not be verified *and* could not be restored.  From then on this
        #: actuator writes nothing: a second write on top of an unknown value is worse than a stop.
        self._poisoned: str | None = None
        #: Every write this actuator made, with what it read back — the evidence a caller logs.
        self.value_writes: list[dict[str, Any]] = []
        self._table = table
        self._table_path = table_path
        self._target_digest = target_digest
        self._channel = channel
        self._numeric_writes = bool(numeric_writes)

    # -- delegation ------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        """Everything not overridden is the inner actuator's, unchanged and unreimplemented."""
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    # -- the table -------------------------------------------------------
    @property
    def table(self) -> BridgeTable:
        if self._table is None:
            self._table = load_table(self._table_path)
        return self._table

    def unavailable(self) -> str | None:
        """Why this actuator could not run a cycle right now, or ``None`` when nothing blocks it."""
        try:
            table = self.table
        except BridgeUnavailable as exc:
            return exc.reason
        if (
            self._target_digest is not None
            and table.image_sha256 != self._target_digest
        ):
            return f"bridge_digest_unknown:{self._target_digest}"
        if self._dispatch is None:
            return "bridge_runner_not_configured"
        return None

    # -- numeric writes (declared, not wired) ----------------------------
    def value_write_blocker(self, role: str, value: float) -> str | None:
        """Why a numeric write for ``role`` cannot be made, or ``None`` when nothing blocks it.

        The refusal vocabulary is the deliverable here: a caller that asks for a bridge numeric write
        learns *which* fact is missing (the switch, the table, the setter, the range, the build) instead
        of getting a silent fall back to the GUI route.
        """
        if not self._numeric_writes:
            return "bridge_numeric_writes_not_enabled"
        try:
            table = self.table
        except BridgeUnavailable as exc:
            return exc.reason
        if (
            self._target_digest is not None
            and table.image_sha256 != self._target_digest
        ):
            return f"bridge_digest_unknown:{self._target_digest}"
        setter = table.setters.get(str(role))
        if setter is None:
            return f"bridge_setter_missing:{role}"
        if setter.minimum is not None and value < setter.minimum:
            return f"bridge_value_out_of_range:{role}:{value}"
        if setter.maximum is not None and value > setter.maximum:
            return f"bridge_value_out_of_range:{role}:{value}"
        return None

    def write_parameter(self, role, value: str) -> None:
        """A numeric write with guarded compensation: verify it, and restore through the same setter.

        The policy, agreed 2026-10-22 — one mechanism, no second implementation:

        - the field is read before the attempt and read again after it; the write counts only when the
          read-back states the requested value, never because the dispatch said it wrote;
        - a mismatch gets **exactly one** restore, through the same setter, to the value that was read
          before the attempt;
        - a restore that reads back correct raises ``bridge_write_rolled_back:<role>``: the write
          failed and the application is where it was;
        - a restore that cannot be verified poisons this actuator
          (``bridge_write_unverified:<role>``): every later write is refused with
          ``bridge_writes_poisoned``, because the next write would build on a value nobody knows.

        With ``numeric_writes=False`` (the default) this is the GUI actuator's own write, unchanged.
        """
        if not self._numeric_writes:
            return self._inner.write_parameter(role, value)
        try:
            numeric = float(str(value))
        except TypeError, ValueError:
            raise BridgeRefused(f"bridge_value_not_numeric:{value}") from None
        blocker = self.value_write_blocker(role, numeric)
        if blocker is not None:
            raise BridgeRefused(blocker)
        if self._poisoned is not None:
            raise BridgeRefused(f"bridge_writes_poisoned:{self._poisoned}")
        if self._value_dispatch is None:
            raise BridgeRefused("bridge_value_runner_not_configured")

        previous = str(self._inner.read_parameter(role))
        # A write asking for the value the field already holds is a no-op, and a read-back cannot tell
        # it from a transition: the field says the requested value either way.  Saying so is the
        # difference between evidence and a coincidence, so it is recorded and no dispatch happens.
        if _same_numeric(previous, numeric):
            self.value_writes.append(
                {
                    "role": str(role),
                    "value": numeric,
                    "previous": previous,
                    "readback": previous,
                    "restored": False,
                    "verified": False,
                    "unchanged": True,
                }
            )
            return
        self._value_dispatch(self._value_request(role, numeric, previous))
        observed = str(self._inner.read_parameter(role))
        entry = {
            "role": str(role),
            "value": numeric,
            "previous": previous,
            "readback": observed,
            "restored": False,
            "verified": False,
        }
        if _same_numeric(observed, numeric):
            entry["verified"] = True
            self.value_writes.append(entry)
            return

        previous_numeric = _as_number(previous)
        restored = None
        if previous_numeric is not None:
            # The compensation is **not** another dispatch: measured 2026-10-22, a fresh attach cannot
            # commit again even with identical addresses and state, while one attach can commit twice.
            # So the repair goes through the GUI write — the reliable mechanism, and the one an operator
            # would use by hand. A bridge write that needs repairing is a bridge write that already
            # failed; asking the same route to undo it would repeat the failure in a way the read-back
            # cannot distinguish from success.
            self._inner.write_parameter(role, previous)
            restored = str(self._inner.read_parameter(role))
        if previous_numeric is not None and _same_numeric(restored, previous_numeric):
            entry["restored"] = True
            entry["restored_to"] = restored
            self.value_writes.append(entry)
            raise BridgeRefused(
                f"bridge_write_rolled_back:{role}:{numeric}->{observed}"
            )

        self._poisoned = f"{role}:{observed}"
        entry["poisoned"] = True
        self.value_writes.append(entry)
        raise BridgeRefused(f"bridge_write_unverified:{role}:{observed}")

    def _value_request(self, role, value: float, previous: str) -> BridgeValueCommit:
        setter = self.table.setters[str(role)]
        return BridgeValueCommit(
            role=str(role),
            value=float(value),
            previous=str(previous),
            table_digest=self.table.image_sha256,
            setter=setter.setter,
            notify=setter.notify,
        )

    # -- the cycle -------------------------------------------------------
    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: ProcessMode,
        verify_channel: bool = True,
    ) -> tuple[bool, Path | str]:
        """Record, stop, store — the bridge route — and credit only artifact-backed evidence."""
        if self._cycle is None:
            blocker = self.unavailable()
            if blocker is not None:
                return False, blocker
        table = self.table
        directory = Path(directory)
        note = self._inner.process_mode_note(expected_mode)
        if note is not None:
            return False, f"bridge_mode_mismatch:{note}"
        taken = (
            sorted(path.name for path in directory.glob(f"{name}*") if path.is_file())
            if directory.is_dir()
            else []
        )
        if taken:
            return False, f"store_name_taken:{taken[0]}"
        request = BridgeRequest(
            name=name,
            duration_s=float(duration_s),
            directory=directory,
            expected_mode=expected_mode.value,
            channel=self._channel,
            verify_channel=verify_channel,
            table_digest=table.image_sha256,
        )
        if self._cycle is not None:
            ok, outcome = self._cycle.try_record_and_store(
                name, duration_s, directory, expected_mode=expected_mode
            )
            if not ok:
                return False, str(outcome)
            path = Path(outcome)
            if not path.is_file():
                return False, f"bridge_artifact_mismatch:{path.as_posix()}"
            return True, path
        assert self._dispatch is not None  # narrowed by `unavailable()`
        try:
            evidence = evidence_from_report(self._dispatch(request))
        except BridgeUnavailable as exc:
            return False, exc.reason
        if not evidence.stored:
            return False, evidence.reason or "bridge_not_stored"
        if evidence.config_matches is False:
            return False, "bridge_decode_mismatch"
        if evidence.identity_unchanged is False:
            return False, "bridge_identity_changed"
        path = evidence.stored_path
        assert path is not None  # required by evidence_from_report when stored
        if not path.is_file():
            return False, f"bridge_artifact_mismatch:{path.as_posix()}"
        if evidence.stored_sha256 is not None:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != evidence.stored_sha256:
                return False, f"bridge_artifact_mismatch:{path.as_posix()}"
        return True, path

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: ProcessMode,
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        """The composed cycle, raising the same reason :meth:`try_record_and_store` returns."""
        ok, evidence = self.try_record_and_store(
            name, duration_s, directory, expected_mode=expected_mode
        )
        if not ok:
            raise BridgeRefused(str(evidence))
        assert isinstance(evidence, Path)
        return evidence


@dataclass(frozen=True)
class MenuCall:
    """One call asked of the machine-local menu dispatch.

    ``action`` is ``enter`` or ``leave`` so the dispatch can report what it did, and ``index`` is present
    only for ``enter``.  ``routines_digest`` pins the two addresses the call was derived from, so a report
    cannot be credited against a different pair.
    """

    action: str
    address: int
    index: int | None
    routines_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "address": self.address,
            "index": self.index,
            "routines_digest": self.routines_digest,
        }


@runtime_checkable
class StoreCycle(Protocol):
    """The message route's own record/stop/store cycle, injected rather than dispatched to a host runner.

    Structural on purpose: :class:`~udv_echo_process.acquire.cycle.RoutineCycle` satisfies it, and so does any object with
    the same call, which keeps this wrapper testable without an instrument.
    """

    def try_record_and_store(
        self, name: str, duration_s: float, directory: Path, *, expected_mode: object = None
    ) -> tuple[bool, Path | str]: ...


@runtime_checkable
class MenuDispatch(Protocol):
    """The machine-local execution of one menu routine call.

    Implementations live outside this repository (they call into a patched process).  The report is read
    for ``ok``, an optional ``overlay_painted`` and a ``reason``; anything else is ignored rather than
    trusted.
    """

    def __call__(self, call: MenuCall) -> Mapping[str, Any]: ...


@runtime_checkable
class MenuPress(Protocol):
    """The machine-local press of one row inside an open overlay.

    A press is *not* a dispatch: it is a window message to the row's own handle, which is what makes the
    control toggle its state and fire the handler that derives from it.  The report must name the handle it
    pressed, so a caller can tell a press that happened from one that merely returned.
    """

    def __call__(self, offset: tuple[int, int]) -> Mapping[str, Any]: ...


@runtime_checkable
class MenuCensus(Protocol):
    """What is painted *over* the main window right now — overlays and dialogs, never fixed chrome.

    The application's failure modes are visible here and nowhere else.  A dropdown left behind by a hover
    stays painted and refuses to close; a press can raise a `Warning` or a `Fatal error` that waits for an
    answer; and a press whose handler closes its own overlay leaves nothing behind.  A mapping is enough:
    ``{"surfaces": ["TSp_Panel:391,160,841,280", ...]}``, one stable identifier per painted surface.

    Fixed chrome — the parameter column, the strip — must not be reported, or every check below would
    refuse everything.  Supplying a census is optional only because enumerating surfaces is the host's
    business; without one this class cannot tell you what a press did.
    """

    def __call__(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class MenuEvidence:
    """What a menu routine call is allowed to mean."""

    action: str
    index: int | None
    painted: bool | None
    reason: str | None
    raw: Mapping[str, Any]
    surfaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class MenuPressEvidence:
    """What a row press is allowed to mean: which handle was pressed, and where it was."""

    offset: tuple[int, int]
    handle: int
    raw: Mapping[str, Any]


def _routines_digest(routines: BridgeMenuRoutines) -> str:
    payload = json.dumps(routines.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class BridgeMenu:
    """Open, press and close a menu overlay through the application's own routines.

    The three steps are the ones measured on the instrument: ``@Panels@Enter_Menu(index)`` shows an
    overlay with no pointer involved, a posted press on the row's own handle performs the click (the
    control toggles its state, repaints and fires the form's handler), and
    ``@Panels@Leave_Current_Menu()`` hides it again.

    What this class refuses, and why each refusal exists:

    - **a press while nothing is open** (``bridge_menu_not_open``): the press needs a row that exists; a
      press into a closed overlay would land on whatever is under it;
    - **a press without a press mechanism** (``bridge_menu_press_unavailable``): a host that supplies only
      the dispatch cannot press, and saying so is better than dispatching a handler that reads a state
      nobody set — measured on the instrument, that quietly does nothing;
    - **a table without the routines** (``bridge_menu_missing``) and an unknown menu
      (``bridge_menu_index:<request>``): the index meanings live in the table, never in this module.

    Note on closing: ``leave`` acts on the application's notion of the *current* menu, which ``enter``
    sets.  An overlay left behind by a hover in the app's stuck state is not closed by it — that is a
    property of the application, not of this class, and it is why ``open_menu`` records what it opened.
    """

    def __init__(
        self,
        table: BridgeTable,
        dispatch: MenuDispatch,
        press: MenuPress | None = None,
        census: MenuCensus | None = None,
    ) -> None:
        self._table = table
        self._dispatch = dispatch
        self._press = press
        self._census = census
        self._open: int | None = None
        self._surfaces: frozenset[str] = frozenset()

    @property
    def routines(self) -> BridgeMenuRoutines:
        if self._table.menu is None:
            raise BridgeUnavailable("bridge_menu_missing")
        return self._table.menu

    @property
    def open_index(self) -> int | None:
        """The overlay this instance opened and has not closed, or ``None``."""
        return self._open

    def index_of(self, menu: str | int) -> int:
        """Resolve a menu name or number against the table's order."""
        return self.routines.index_of(menu)

    def open_menu(self, menu: str | int) -> MenuEvidence:
        """Show an overlay: ``enter`` with the resolved index.

        With a census, an already-painted surface is a refusal (``bridge_menu_surface_already_painted``):
        opening a menu on top of a leftover overlay is how an unattended run presses a row in a panel it did
        not open, and the application has no way back from that state on its own.
        """
        routines = self.routines
        index = routines.index_of(menu)
        before = self._surfaces_now()
        if before:
            if self._open == index and before == self._surfaces:
                # The menu this instance opened is still painted — measured on the instrument, a row's
                # handler does not always close its overlay.  Re-opening the same menu is a no-op, not a
                # hazard: the panel is the one whose rows we are addressing.
                return MenuEvidence(
                    action="enter",
                    index=index,
                    painted=True,
                    reason=None,
                    raw={"already_open": True},
                    surfaces=tuple(sorted(before)),
                )
            raise BridgeRefused(f"bridge_menu_surface_already_painted:{min(before)}")
        evidence = self._call("enter", routines.enter, index)
        self._open = index
        self._surfaces = self._surfaces_now()
        if self._census is not None:
            evidence = replace(
                evidence, painted=bool(self._surfaces), surfaces=tuple(sorted(self._surfaces))
            )
        return evidence

    def close_menu(self) -> MenuEvidence:
        """Hide the overlay the application considers current.

        With a census, a surface still painted afterwards is a refusal
        (``bridge_menu_still_painted``) and the menu stays recorded as open.  Measured on the instrument: an
        overlay left behind by a hover in the application's stuck state is *not* closed by ``leave``, and a
        caller that believed it had closed would go on to press into the wrong panel.
        """
        routines = self.routines
        evidence = self._call("leave", routines.leave, None)
        after = self._surfaces_now()
        if after:
            raise BridgeRefused(f"bridge_menu_still_painted:{min(after)}")
        self._open = None
        self._surfaces = frozenset()
        if self._census is not None:
            evidence = replace(evidence, painted=False, surfaces=())
        return evidence

    def row(self, entry: str) -> BridgeMenuRow:
        """The named row, or a refusal naming it."""
        if entry not in self._table.rows:
            raise BridgeUnavailable(f"bridge_menu_row:{entry}")
        return self._table.rows[entry]

    def press(self, entry: str, *, allow: Collection[str] = (), hold_ms: int = 180) -> MenuPressEvidence:
        """Press the row called ``entry``, which must belong to the overlay that is open.

        The menu check is not pedantry: pressing a position in the *wrong* overlay would press whatever
        happens to sit there, and the whole point of a name is that it cannot drift into another menu.

        ``allow`` names effects the caller consents to (``"preset"``, ``"dialog"``, ``"mode"``).  Display
        and filter rows need no consent; anything unclassified is refused as unavailable, because a row
        nobody has looked at is not a row a sweep should press.
        """
        row = self.row(entry)
        index = self.routines.index_of(row.menu)
        if self._open is None:
            raise BridgeRefused("bridge_menu_not_open")
        if self._open != index:
            raise BridgeRefused(f"bridge_menu_row_other_menu:{row.menu}")
        if row.effect is MenuRowEffect.UNKNOWN:
            raise BridgeUnavailable(f"bridge_menu_row_effect_unknown:{entry}")
        permitted = {effect.value if isinstance(effect, MenuRowEffect) else str(effect) for effect in allow}
        if row.effect not in UNGUARDED_EFFECTS and row.effect.value not in permitted:
            raise BridgeRefused(f"bridge_menu_row_effect:{entry}:{row.effect.value}")
        return self.press_row(row.offset, hold_ms=hold_ms, allow=allow)

    def press_row(
        self,
        offset: tuple[int, int],
        *,
        hold_ms: int = 180,
        allow: Collection[str] = (),
    ) -> MenuPressEvidence:
        """Press the row at ``offset`` inside the open overlay.

        ``hold_ms`` is carried for the mechanism's sake only; the press itself is posted and must be a
        held press, not an instant down/up, or the control does not register it.
        """
        if self._open is None:
            raise BridgeRefused("bridge_menu_not_open")
        if self._press is None:
            raise BridgeUnavailable("bridge_menu_press_unavailable")
        report = self._press((int(offset[0]), int(offset[1])))
        if not isinstance(report, Mapping):
            raise BridgeUnavailable("bridge_menu_press_report_invalid")
        reason = report.get("reason") or report.get("error")
        if report.get("pressed") is not True:
            raise BridgeRefused(f"bridge_menu_press_failed:{reason or 'not_pressed'}")
        handle = report.get("handle", report.get("hwnd"))
        if handle is None:
            raise BridgeUnavailable("bridge_menu_press_handle_missing")
        raised = self._surfaces_now() - self._surfaces
        permitted = {effect.value if isinstance(effect, MenuRowEffect) else str(effect) for effect in allow}
        if raised and "dialog" not in permitted:
            # A press that raised something has not finished: the application is waiting on an answer.
            # The caller either declared that it expects this (``allow`` carries "dialog") or the step is
            # refused while the panel is left as it is, for a human or a policy to settle.
            raise BridgeRefused(f"bridge_menu_press_raised_surface:{min(raised)}")
        return MenuPressEvidence(
            offset=(int(offset[0]), int(offset[1])), handle=int(handle), raw=dict(report)
        )

    def _surfaces_now(self) -> frozenset[str]:
        """The painted surfaces, as identifiers; empty when no census was supplied."""
        if self._census is None:
            return frozenset()
        report = self._census()
        if not isinstance(report, Mapping):
            raise BridgeUnavailable("bridge_menu_census_report_invalid")
        surfaces = report.get("surfaces", ())
        if isinstance(surfaces, str):
            raise BridgeUnavailable("bridge_menu_census_report_invalid")
        return frozenset(str(surface) for surface in surfaces)

    def _call(self, action: str, address: int, index: int | None) -> MenuEvidence:
        call = MenuCall(
            action=action,
            address=address,
            index=index,
            routines_digest=_routines_digest(self.routines),
        )
        report = self._dispatch(call)
        if not isinstance(report, Mapping):
            raise BridgeUnavailable("bridge_menu_report_invalid")
        reason = report.get("reason") if report.get("reason") is not None else report.get("error")
        painted = report.get("overlay_painted")
        evidence = MenuEvidence(
            action=action,
            index=index,
            painted=None if painted is None else bool(painted),
            reason=None if reason is None else str(reason),
            raw=dict(report),
        )
        if report.get("ok") is False or (report.get("ok") is None and evidence.reason):
            raise BridgeRefused(f"bridge_menu_call_failed:{action}:{evidence.reason}")
        return evidence
