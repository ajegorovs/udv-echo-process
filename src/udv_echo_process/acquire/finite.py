"""What a finite multiplexed ``Run`` left behind — and what may be done next.

A finite 1+2 block is started by one native ``Run`` and then **completes itself**:
the application ends the sequence and leaves the block in the store strip, so
nothing presses ``Record`` or ``Stop`` and the post-Run question is a
classification of one snapshot against the request that caused it — not a driver,
not a cycle, not a policy framework.

Measured 2026-10-28 (``docs/dop3000/evidence/finite-multiplex-live-20261028.json``):
a pair at mode ``65585`` took one ``Run`` to ``2162739`` leaving
``Execution_Code`` 5 — one **command identifier**, not a queue depth — so
``Run`` sets bit 1 (:data:`RUN_ARM_BIT`) and the application derives bit 21
(:data:`RUN_DERIVED_BIT`); no other bit moved, no ``Record`` was dispatched, and
the app then drained to 0, cleared the arm bit and left a held store at channel
2. Bit 1 means *armed*, never *recording*: a recording strip with code 0 is a
live run, not a finished one.

The trust boundary is why this is separate from the driver: nothing here reads a
process, a window or a strip, so every field is a *claim* from the caller's own
fresh local snapshots that this module can only check against the others. It
cannot tell a fresh snapshot from a stale one, nor whether ``held_block_token``
was assigned honestly, so the caller owes it a snapshot taken after **this**
run's single dispatch and before anything else is pressed. It never issues
``Record`` or ``Stop``: :attr:`FiniteAction.STORE_COMPLETED` only authorises the
existing store entry point (``RoutineCycle.store_completed_block``), and
:attr:`FiniteAction.REFUSE` is not an abort — stop and leave the instrument as
it is, because a finite block may still be running.
"""

from __future__ import annotations

from enum import Enum
from itertools import pairwise

from pydantic import Field, model_validator

from udv_echo_process.acquire.actuator import StripState, StripView
from udv_echo_process.models.base import ValueModel

__all__ = [
    "RUN_ARM_BIT",
    "RUN_DERIVED_BIT",
    "FiniteAction",
    "FiniteObservation",
    "FiniteRunDecision",
    "FiniteRunReceipt",
    "FiniteRunRequest",
    "classify_finite_run",
]

#: The only mode bits one ``Run`` may touch. Bit 1 is the arm bit the native
#: ``Run`` sets (measured ``65585`` → ``65587``); bit 21 is what the application
#: derives itself, accepted but never required (the restored baseline carries it
#: too). The requested finite flag is **bit 0**, present before the run and a
#: different meaning entirely — conflating the two is how the over-strict
#: post-Run assertion came to reject the application's own state.
RUN_ARM_BIT = 1 << 1
RUN_DERIVED_BIT = 1 << 21
#: The request must be finite: bit 0 set. A participant channel ``c`` is marked
#: by bit ``8 << c`` (channels 1..10 use bits 4..13) and ``channels`` must agree
#: with those bits exactly. Only the measured manual trigger word 4 is valid —
#: external-enable (bit 1) and the guard (bit 6) stay clear.
FINITE_FLAG = 1 << 0
MEMBER_BIT_BASE = 8
MAX_CHANNEL = 10
PARTICIPANT_MASK = 0x3FF0
VALID_TRIGGER_WORD = 4
TRIGGER_EXTERNAL_BIT = 1 << 1
TRIGGER_GUARDED_BIT = 1 << 6
#: ``Execution_Code`` is **one command identifier**, never a queue depth or a
#: counter: ``Run`` writes 5, ``Record`` 28, the Off/refresh path 2, and 0 is
#: idle. A fresh snapshot may therefore state only 0, or this run's own 5.
RUN_COMMAND = 5
IDLE_COMMAND = 0


class FiniteAction(str, Enum):
    """The closed set of things a post-Run snapshot can mean."""

    #: Arming, draining or still recording: no store yet, no new command may run.
    WAIT = "wait"
    #: The owned block completed and drained: the store of that block is permitted.
    STORE_COMPLETED = "store_completed"
    #: Not the expected continuation of the owned run: stop, do not abort.
    REFUSE = "refuse"


class FiniteRunRequest(ValueModel):
    """The one run this snapshot is judged against.

    ``channels`` is the requested **membership in visit order** — ascending,
    unique, within 1..10 — and its last element is the channel a completed block
    must be left on. The mode must carry the finite flag, agree with the
    participant bits and carry no arm bit: an already-armed baseline is a
    rollover replay.
    """

    channels: tuple[int, ...]
    #: Global ``Mpx_Nb_Sequences``: requested repetitions of the participant sequence.
    sequences: int = Field(ge=1)
    trigger_word: int = Field(ge=0)
    mode_before: int = Field(ge=0)
    #: Whether the run requires the un-assisted (manual) parameter panel.
    manual_only: bool = True
    #: The caller's own name for this run: the only identity a held block and a
    #: receipt can be matched against.
    run_token: str = Field(min_length=1)

    @model_validator(mode="after")
    def _one_ordered_finite_pair(self) -> FiniteRunRequest:
        channels = self.channels
        if not channels:
            raise ValueError("channels must name at least one participant")
        if any(channel < 1 or channel > MAX_CHANNEL for channel in channels):
            raise ValueError(f"every channel must be within 1..{MAX_CHANNEL}")
        if any(left >= right for left, right in pairwise(channels)):
            raise ValueError("channels must be strictly ascending (visit order)")
        if not self.mode_before & FINITE_FLAG:
            raise ValueError("mode_before does not carry the finite flag")
        if self.mode_before & RUN_ARM_BIT:
            raise ValueError("mode_before already carries the Run arm bit")
        wanted = sum(MEMBER_BIT_BASE << channel for channel in channels)
        if (self.mode_before & PARTICIPANT_MASK) != wanted:
            raise ValueError("mode_before's participant bits do not match channels")
        if self.trigger_word & (TRIGGER_EXTERNAL_BIT | TRIGGER_GUARDED_BIT):
            raise ValueError("trigger_word enables external trigger or the guard")
        if self.trigger_word != VALID_TRIGGER_WORD:
            raise ValueError(f"trigger_word must be the measured {VALID_TRIGGER_WORD}")
        return self


class FiniteRunReceipt(ValueModel):
    """The caller's record of the one ``Run`` it dispatched.

    ``invocations`` is what makes the receipt worth having: zero means the run
    was never dispatched, more than one means it was replayed, and a replayed
    run can no longer be credited with the block that followed it. The two
    dispatch counts are expected to be zero — a finite block completes itself —
    and ``pending_after_run`` is the ``Execution_Code`` the dispatch left, one
    command identifier that a Run leaves at exactly :data:`RUN_COMMAND`.
    """

    run_token: str = Field(min_length=1)
    #: Opaque instance identity as the caller read it; empty means unknown.
    identity: str = ""
    invocations: int = Field(ge=0)
    #: ``Execution_Code`` just after the dispatch — the single command Run queues.
    pending_after_run: int = Field(ge=0)
    record_dispatches: int = Field(ge=0)
    stop_dispatches: int = Field(ge=0)


class FiniteObservation(ValueModel):
    """One fresh read of the application after the run, as the caller saw it.

    Fields follow the live snapshot vocabulary: ``mode_after`` is ``Mpx_Mode``,
    ``sequences`` is ``Mpx_Nb_Sequences``, ``current_channel`` is
    ``Current_Channel``, ``trigger_word`` is ``Trigger_Mode``, ``pending`` is
    ``Execution_Code`` (one command identifier, never a depth), ``assisted_mode``
    is ``Assisted_Mode`` and ``error`` is the application's own error state.
    ``strip`` is the structural reading: the store view is recognised by slider
    presence; this bounded classifier additionally requires the measured two-button
    finite STORE shape without treating that shape as a button-role binding.
    """

    strip: StripState
    identity: str = ""
    error: str = ""
    mode_after: int = Field(ge=0)
    pending: int = Field(ge=0)
    sequences: int = Field(ge=0)
    participants: tuple[int, ...] = ()
    current_channel: int | None = Field(default=None, ge=1)
    assisted_mode: bool = False
    trigger_word: int = Field(ge=0)
    #: Which run the caller saw the held block come from; empty when it cannot
    #: say, which makes the block foreign rather than owned.
    held_block_token: str = ""


class FiniteRunDecision(ValueModel):
    """The action, and — on a refusal — exactly one named boundary that failed."""

    action: FiniteAction
    reasons: tuple[str, ...] = ()
    store_token: str = ""


def classify_finite_run(
    request: FiniteRunRequest,
    receipt: FiniteRunReceipt | None,
    observation: FiniteObservation,
) -> FiniteRunDecision:
    """Classify one post-Run snapshot against the run that caused it.

    A refusal names the **first** boundary that failed, so a reader learns one
    cause rather than a pile of consequences, and an application error always
    outranks the evidence questions. All tokens share the prefix ``finite_``:
    ``application_error``, ``receipt_missing``, ``receipt_foreign``,
    ``receipt_not_dispatched``, ``receipt_replayed``,
    ``receipt_record_dispatched``, ``receipt_stop_dispatched``,
    ``receipt_pending_invalid``, ``identity_unknown``, ``identity_changed``,
    ``trigger_changed``, ``participants_changed``, ``sequences_changed``,
    ``assisted_mode``, ``mode_unexpected_bits``, ``mode_not_armed``,
    ``pending_unexpected``, ``current_channel_unexpected``, ``strip_ambiguous``,
    ``strip_unknown``, ``store_shape_unmeasured``, ``held_block_foreign`` and
    ``no_completed_block``.

    ``STORE_COMPLETED`` is authorised only by a drained, owned store view — which
    may already have cleared :data:`RUN_ARM_BIT`, because a successful finite
    completion clears it. A recording strip with :data:`IDLE_COMMAND` is a live
    run and waits; the bounded deadline belongs to the caller.
    """
    held_completed = (
        observation.pending == IDLE_COMMAND
        and observation.strip.view is StripView.STORE
        and observation.held_block_token == request.run_token
    )
    reason = _first_refusal(
        request, receipt, observation, held_completed=held_completed
    )
    if reason is not None:
        return FiniteRunDecision(action=FiniteAction.REFUSE, reasons=(reason,))
    if held_completed:
        return FiniteRunDecision(
            action=FiniteAction.STORE_COMPLETED, store_token=request.run_token
        )
    return FiniteRunDecision(action=FiniteAction.WAIT)


def _first_refusal(
    request: FiniteRunRequest,
    receipt: FiniteRunReceipt | None,
    observation: FiniteObservation,
    *,
    held_completed: bool,
) -> str | None:
    """The first boundary this snapshot fails, or ``None`` when it continues the run."""
    if observation.error:
        return "finite_application_error"
    if receipt is None:
        return "finite_receipt_missing"
    if receipt.run_token != request.run_token:
        return "finite_receipt_foreign"
    if receipt.invocations == 0:
        return "finite_receipt_not_dispatched"
    if receipt.invocations > 1:
        return "finite_receipt_replayed"
    if receipt.record_dispatches:
        return "finite_receipt_record_dispatched"
    if receipt.stop_dispatches:
        return "finite_receipt_stop_dispatched"
    if receipt.pending_after_run != RUN_COMMAND:
        return "finite_receipt_pending_invalid"
    if not receipt.identity or not observation.identity:
        return "finite_identity_unknown"
    if receipt.identity != observation.identity:
        return "finite_identity_changed"
    if observation.trigger_word != request.trigger_word:
        return "finite_trigger_changed"
    if observation.participants != request.channels:
        return "finite_participants_changed"
    if observation.sequences != request.sequences:
        return "finite_sequences_changed"
    if request.manual_only and observation.assisted_mode:
        return "finite_assisted_mode"
    # The mode delta one run is allowed to make.
    delta = request.mode_before ^ observation.mode_after
    if delta & ~(RUN_ARM_BIT | RUN_DERIVED_BIT):
        return "finite_mode_unexpected_bits"
    # ``Execution_Code`` is one identifier: only idle or this run's own command.
    if observation.pending not in (IDLE_COMMAND, RUN_COMMAND):
        return "finite_pending_unexpected"
    view = observation.strip.view
    stores_held = view is StripView.STORE
    if not (observation.mode_after & RUN_ARM_BIT) and not held_completed:
        return "finite_mode_not_armed"
    if observation.current_channel not in request.channels:
        return "finite_current_channel_unexpected"
    if (
        observation.pending == IDLE_COMMAND
        and stores_held
        and observation.current_channel != request.channels[-1]
    ):
        return "finite_current_channel_unexpected"
    # The held block: only the owned, completed one may be stored.
    if view is StripView.AMBIGUOUS:
        return "finite_strip_ambiguous"
    if view is StripView.UNKNOWN:
        return "finite_strip_unknown"
    if stores_held and observation.strip.button_count != 2:
        return "finite_store_shape_unmeasured"
    if stores_held and (
        observation.pending == IDLE_COMMAND or observation.held_block_token
    ):
        if observation.held_block_token != request.run_token:
            return "finite_held_block_foreign"
    elif observation.pending == IDLE_COMMAND and view is StripView.READY:
        return "finite_no_completed_block"
    return None
