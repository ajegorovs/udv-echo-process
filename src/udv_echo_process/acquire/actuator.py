"""The actuator interface: what the GUI-driving implementation must provide.

This module is **pure Python on purpose** — no ``pywinauto``, no ``watchdog``, no
``PIL`` — so the interface can be satisfied by a fake in tests and so importing
``udv_echo_process.acquire`` stays safe on any host. The Windows implementation
lands later; it satisfies :class:`Actuator` and owns the message-based recipes.

Everything here is *binding data or a pure rule*, never a hard-coded window id or
screen coordinate. That property is load-bearing:

- the strip panel is **draggable and morphs** (``98x40`` → ``352x40`` → ``413x123``),
  so it is located structurally and its buttons are identified by their **order in
  the current view** — 134 vs 138 px is too close a width to be an identity
  (docs/16 §7, §10);
- the parameter column is resolved by position (``left == 0``, tall panel, value
  fields top-to-bottom) — see ``PARAM_COLUMN_ORDER``;
- control ids change on every launch (43/43 classes at the same positions, 1/43
  ids in common), so nothing can key on an id.

The ported recipes, kept here as documented constants so the implementation can
not drift from what was verified:

- a strip button needs a **held** press — posted ``WM_LBUTTONDOWN``, ~180 ms,
  ``WM_LBUTTONUP``; an instant down/up in the same millisecond is ignored, which
  is exactly what every early attempt sent (docs/16 §1);
- a numeric field needs ``WM_SETTEXT`` + ``WM_COMMAND(EN_CHANGE)`` + a
  **``VK_RETURN`` key event** — ``WM_SETTEXT`` alone changes the control's text
  and the application keeps its own value (docs/14 §4);
- posted clicks **ignore modality**, so every press is preceded by an overlay
  check (docs/16 §8).

Two of the ported rules are *ordering* rules and live here rather than in the
values module: the write order (resolution before gates) and the safe overlay
answer (leftmost button). Both are table lookups, not branches.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import Field

from udv_echo_process.acquire.config import ParameterSet
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DIALOG_ANCHORS",
    "DIALOG_COLUMN_ROWS",
    "DIALOG_FIELD_ORDER",
    "DIALOG_ONLY_PARAMETERS",
    "NUMERIC_WRITE_RECIPE",
    "OVERLAY_ANSWERS",
    "PARAMETER_WRITE_ORDER",
    "PARAM_COLUMN_ORDER",
    "PRESS_HOLD_MS",
    "PROCESS_MODE_PREFIXES",
    "STARTABLE_VIEWS",
    "STORE_TIMEOUT_S",
    "STRIP_BUTTON_ORDER",
    "VIEW_TIMEOUT_S",
    "Actuator",
    "ChannelMode",
    "DialogControl",
    "DialogField",
    "OverlayKind",
    "ParamRole",
    "ProcessMode",
    "StripControl",
    "StripState",
    "StripView",
    "classify_strip_view",
    "ordered_writes",
    "overlay_answer",
    "press_index",
    "process_mode",
    "strip_controls",
]

#: A strip press must be held: down, ``PRESS_HOLD_MS``, up (docs/16 §1).
PRESS_HOLD_MS = 180

#: How long a view change is polled for before the cycle is declared failed.
VIEW_TIMEOUT_S = 12.0

#: The Store dialog can sit behind a store of a large block; the reference
#: implementation waited up to 40 s for the file to appear (docs/16 §5).
STORE_TIMEOUT_S = 60.0

#: The numeric-field commit recipe, in order. ``WM_SETTEXT`` alone never
#: commits; the ``VK_RETURN`` key event is the commit (docs/14 §4).
NUMERIC_WRITE_RECIPE: tuple[str, ...] = (
    "WM_SETTEXT",
    "WM_COMMAND(EN_CHANGE)",
    "WM_KEYDOWN(VK_RETURN)",
    "WM_KEYUP(VK_RETURN)",
)

#: Parameters with **no** parameter-column field — they are set in the
#: ``Operating parameters`` dialog only, so a sweep that varies one of them needs
#: the dialog path. ``sampling_volume`` is the exception that proves the rule: the
#: app chooses it from the burst length and the physics, so it is read back, never
#: written (docs/16 §13, docs/13 §1).
DIALOG_ONLY_PARAMETERS: tuple[str, ...] = (
    "first_gate_depth",
    "burst_length",
    "sampling_volume",
    "sound_speed",
    "tgc",
)


class ParamRole(str, Enum):
    """A parameter-column value field, by role — never by id or coordinate."""

    US_FREQUENCY = "us_frequency_khz"
    PRF = "prf_us"
    GATES = "gates"
    RESOLUTION = "resolution_mm"
    VELOCITY_SCALE_FACTOR = "velocity_scale_factor"
    EMISSIONS_PER_PROFILE = "emissions_per_profile"
    DOPPLER_ANGLE = "doppler_angle_deg"


#: The parameter column's value fields in their fixed **top-to-bottom** order;
#: that order is the identity of a field (docs/16 §12, ``recon/udop_roles.py``).
PARAM_COLUMN_ORDER: tuple[ParamRole, ...] = (
    ParamRole.US_FREQUENCY,
    ParamRole.PRF,
    ParamRole.GATES,
    ParamRole.RESOLUTION,
    ParamRole.VELOCITY_SCALE_FACTOR,
    ParamRole.EMISSIONS_PER_PROFILE,
    ParamRole.DOPPLER_ANGLE,
)

#: **Write order: resolution first, then the gate count.** This channel has the
#: manual's auto-resolution / auto-selection-of-gates flags set, so writing the
#: resolution makes the app recompute the gate count; writing gates last makes our
#: value the final request it sees. Measured: 805 gates requested → 474 accepted
#: in the wrong order, 805 accepted in this one (docs/16 §14).
PARAMETER_WRITE_ORDER: tuple[ParamRole, ...] = (ParamRole.RESOLUTION, ParamRole.GATES)


class DialogField(str, Enum):
    """A fixed fact that only the ``Operating parameters`` dialog states.

    Three of the six fixed facts are not measurement-screen roles: the sound speed, the first
    gate and the burst length are stated in the dialog's own value table, which the application
    builds for the selected channel when the dialog is opened. They are *not* added to
    :class:`ParamRole`, because that enum is the **column's** vocabulary (its order is the
    column's identity, and a dialog field placed in it would claim a position the column does
    not have); a dialog field gets its own vocabulary and its own reader.
    """

    SOUND_SPEED_MS = "sound_speed_ms"
    FIRST_GATE_MM = "first_gate_mm"
    BURST_LENGTH = "burst_length"


#: Which value field of the dialog states which dialog-only fact, as
#: ``(field, column, row)`` — **measured** on the running application 2026-09-18
#: (``tests/data/udop-parameters-dialog-tree.json``, probe
#: ``tools/live/probes/w1_fixed_facts.py``).
#:
#: The dialog lays its values out as three columns of ``TSp_Value_Button`` widgets, each holding
#: the value's own ``TSp_Edit``: the columns are the bands of those edits' left edges
#: (786 / 987 / 1187 px in a 627x384 dialog at 655,364), and within a column a field's identity
#: is its top-to-bottom position — never an id, never a caption (every one of these widgets is
#: caption-less, and control ids change on every launch). Read together with
#: :data:`DIALOG_ANCHORS`, which is what makes a positional binding safe to trust.
DIALOG_FIELD_ORDER: tuple[tuple[DialogField, int, int], ...] = (
    (DialogField.BURST_LENGTH, 0, 1),
    (DialogField.FIRST_GATE_MM, 1, 1),
    (DialogField.SOUND_SPEED_MS, 2, 4),
)

#: Where the dialog states facts the measurement screen **also** states, as
#: ``(role, column, row)`` — the check that turns the positional binding above into evidence.
#:
#: A dialog that has been re-laid-out (a different software package installed, another field
#: built) would put a *different* value in `(column, row)` while still reading like a value, and
#: a stale binding would then hand the compile a plausible wrong fact — the one failure mode a
#: pre-run check must not have. So every one of these seven anchors must read the same text the
#: parameter column reads before any dialog-only fact is believed; the reader refuses otherwise.
DIALOG_ANCHORS: tuple[tuple[ParamRole, int, int], ...] = (
    (ParamRole.US_FREQUENCY, 0, 0),
    (ParamRole.PRF, 1, 0),
    (ParamRole.GATES, 1, 2),
    (ParamRole.RESOLUTION, 1, 3),
    (ParamRole.EMISSIONS_PER_PROFILE, 2, 0),
    (ParamRole.DOPPLER_ANGLE, 2, 1),
    (ParamRole.VELOCITY_SCALE_FACTOR, 2, 3),
)

#: How many value fields each column of the dialog's table holds, left to right (measured).
#: A dialog that does not build this shape is not the dialog these bindings were measured
#: against, so nothing in it is read.
DIALOG_COLUMN_ROWS: tuple[int, ...] = (4, 6, 5)


class ChannelMode(str, Enum):
    """The two ways this application's parameters panel can present a channel.

    The app states the mode by **which panel it builds for that channel** (measured live
    2026-09-17): a channel in ``ASSISTED`` mode gets the "Assisted mode parameters for channel N"
    panel — 511x384, the ``Shorter acquisition time / Best quality`` slider, derived
    resolution/gate read-outs, and **no sidebar parameter column at all** — while a channel in
    ``MANUAL`` mode gets the "Operating parameters" panel, 627x384, the value table and the two
    indicator buttons, with the sidebar present. Read from that structure rather than inferred
    from a caption: every one of these widgets is caption-less. It is also why
    :data:`DIALOG_ONLY_PARAMETERS` exists — the same channel shows its fixed parameters in the
    dialog and nothing in the column.
    """

    MANUAL = "manual"
    ASSISTED = "assisted"


class ProcessMode(str, Enum):
    """Which **process** is on the screen — the axis :class:`ChannelMode` is not.

    Two modes, and they are a different question from the channel's: ``ChannelMode`` is read
    from *which panel the application builds* for a channel, while this one is the instance
    itself — the simulator or the measurement application running against the instrument — and
    **only the top-level window's caption states it** (measured 2026-09-18: the simulator's
    caption is ``UDOP Simul`` and the instrument's is ``UDOP DOP3010.43``, while the panels,
    the strip and the plot are the same surfaces in both). Nothing structural can tell them
    apart: the two clean layouts were measured at 43 and 44 visible controls, which is a
    difference *caused by* the mode's own panel, not a discriminator of it.

    So a run declares which process it was measured against and this is what the caption is
    matched against (:func:`process_mode`); the two never imply one another.
    """

    SIMULATION = "simulation"
    INSTRUMENT = "instrument"


#: The caption **prefix** that states each process mode, in match order — a fixed vocabulary
#: of two, extended when a third instance is measured. Prefix-matched because the caption
#: carries the software version: the instrument's own caption was ``UDOP DOP3010.43`` and the
#: ``.43`` moves with the release while the name does not (plan §22.1).
PROCESS_MODE_PREFIXES: tuple[tuple[ProcessMode, str], ...] = (
    (ProcessMode.SIMULATION, "UDOP Simul"),
    (ProcessMode.INSTRUMENT, "UDOP DOP3010"),
)


def process_mode(caption: str) -> ProcessMode | None:
    """Which process the caption states, or ``None`` when it states none this driver knows.

    Pure, and deliberately the *only* place the caption vocabulary is applied, so the read
    (``driver.Win32Actuator.window_caption``) and every fake can be judged against one rule.
    ``None`` is a **refusal**, not a default: an empty caption is a window that states nothing,
    and a caption outside this vocabulary is a version this driver was not measured against —
    the same argument as ``routed_channel`` (plan §12.1): nothing may imply a verification.
    """
    text = caption.strip().casefold()
    for mode, prefix in PROCESS_MODE_PREFIXES:
        if text.startswith(prefix.casefold()):
            return mode
    return None


class StripControl(str, Enum):
    """A record-strip button, addressed by role and by its position in the view."""

    PAUSE = "pause"
    RECORD = "record"
    STOP = "stop"
    DO_STORE = "do_store"
    CLEAR_AND_RESTART = "clear_and_restart"
    NEW_ACQUISITION = "new_acquisition"
    REMOVE_CURRENT_BLOCK = "remove_current_block"


class DialogControl(str, Enum):
    """The two ends of a dialog's bottom button pair (never a title, never a rect)."""

    #: Leftmost: ``Cancel`` in every dialog seen, and ``No`` on the overwrite warning.
    SAFE = "safe"
    #: Rightmost: ``Accept`` / ``Do store``.
    CONFIRM = "confirm"


class OverlayKind(str, Enum):
    """A panel that is up while it should not be (docs/16 §8).

    The app reuses one geometry for all its warnings, so the file-exists warning
    is not distinguishable from any other warning by structure; a ``WARNING``
    answered during a store therefore means "the name was taken — retry with a
    fresh one" (docs/16 §12b).
    """

    STORE_DIALOG = "store_dialog"
    WARNING = "warning"


#: Which button answers an overlay; ``None`` means **do not press anything**.
#: The Store dialog is not an overlay to dismiss — it is where the point's name is
#: set and the store committed, so the caller fills its two ``TEdit`` fields and
#: presses :attr:`DialogControl.CONFIRM`. Every warning is answered with the LEFT
#: button so an existing file is never silently replaced (docs/16 §8, §12b).
OVERLAY_ANSWERS: dict[OverlayKind, DialogControl | None] = {
    OverlayKind.STORE_DIALOG: None,
    OverlayKind.WARNING: DialogControl.SAFE,
}


class StripView(str, Enum):
    """The strip's view, recognised structurally (button count + slider presence)."""

    #: One top-row button: ``[Stop]``.
    RECORDING = "recording"
    #: Stopped with data, no slider: the ``Record`` row (3 or 4 buttons).
    READY = "ready"
    #: After ``Stop``: three top-row buttons **and** a ``TSp_Sliding_Bar`` child.
    STORE = "store"
    #: Anything else — do not guess, refuse the cycle.
    UNKNOWN = "unknown"


#: The top-row button order per ``(view, button_count)``, left → right.
#: The identity of a button is its **position in the view**, never its width.
#: ``record_and_store`` may only start from a verified ``READY`` view: starting
#: from ``RECORDING`` stores a leftover recording under the next point's name
#: (docs/16 §15b).
STRIP_BUTTON_ORDER: dict[tuple[StripView, int], tuple[StripControl, ...]] = {
    (StripView.RECORDING, 1): (StripControl.STOP,),
    (StripView.READY, 3): (
        StripControl.PAUSE,
        StripControl.RECORD,
        StripControl.CLEAR_AND_RESTART,
    ),
    # The no-slider row is documented both with and without a `Do store`; both
    # readings keep `Record` at index 1, which is what the reference
    # implementation relied on (`row[1]` = Record, docs/16 §7/§10).
    (StripView.READY, 4): (
        StripControl.PAUSE,
        StripControl.RECORD,
        StripControl.DO_STORE,
        StripControl.CLEAR_AND_RESTART,
    ),
    (StripView.STORE, 3): (
        StripControl.NEW_ACQUISITION,
        StripControl.DO_STORE,
        StripControl.CLEAR_AND_RESTART,
    ),
    (StripView.STORE, 4): (
        StripControl.NEW_ACQUISITION,
        StripControl.DO_STORE,
        StripControl.CLEAR_AND_RESTART,
        StripControl.REMOVE_CURRENT_BLOCK,
    ),
}

#: Views a point cycle may start from. ``RECORDING`` is never a legal start: a
#: running recording keeps its data and the next ``Do store`` writes it (docs/16
#: §15b).
STARTABLE_VIEWS: tuple[StripView, ...] = (StripView.READY, StripView.STORE)


def classify_strip_view(button_count: int, has_slider: bool) -> StripView:
    """Recognise the strip's view from structure alone (docs/16 §3, §7).

    The slider is decisive: it exists only in the store view. Otherwise one
    top-row button means a recording in progress, 3-4 mean stopped with data, and
    anything else is unrecognised.
    """
    if button_count < 0:
        raise ValueError(f"button_count must be >= 0, got {button_count}")
    if has_slider:
        return StripView.STORE
    if button_count == 1:
        return StripView.RECORDING
    if button_count in (3, 4):
        return StripView.READY
    return StripView.UNKNOWN


def strip_controls(view: StripView, button_count: int) -> tuple[StripControl, ...]:
    """The top-row controls of a view, left → right."""
    try:
        return STRIP_BUTTON_ORDER[(view, button_count)]
    except KeyError:
        raise ValueError(
            f"no known button row for view {view.value!r} with "
            f"{button_count} button(s); the view must be re-resolved, not guessed"
        ) from None


def press_index(view: StripView, control: StripControl, button_count: int) -> int:
    """Left→right index of ``control`` in ``view`` — the binding of a press.

    The implementation resolves the strip panel structurally, sorts the top row
    by ``left`` and presses the widget at this index. This is the whole reason
    button widths must not be used as identity.
    """
    row = strip_controls(view, button_count)
    try:
        return row.index(control)
    except ValueError:
        raise ValueError(
            f"no {control.value!r} in the {view.value!r} view "
            f"({[c.value for c in row]})"
        ) from None


def overlay_answer(kind: OverlayKind) -> DialogControl | None:
    """Which button answers ``kind``; ``None`` means the caller handles it."""
    return OVERLAY_ANSWERS[kind]


def ordered_writes(parameters: ParameterSet) -> tuple[tuple[ParamRole, str], ...]:
    """The ordered ``(role, value)`` writes that apply one point's window.

    Resolution before gates, always — see :data:`PARAMETER_WRITE_ORDER`. The
    resolution is written at 3 decimals to match the app's display, and the gate
    count as an integer (docs/16 §12a, §14).

    Only the two depth-window fields are here. ``PARAM_COLUMN_ORDER``'s other
    fields are covariates read once per sweep, and anything in
    :data:`DIALOG_ONLY_PARAMETERS` has no column field at all.
    """
    values: dict[ParamRole, str] = {
        ParamRole.RESOLUTION: parameters.resolution_text,
        ParamRole.GATES: str(parameters.gates),
    }
    return tuple((role, values[role]) for role in PARAMETER_WRITE_ORDER)


class ScreenFingerprint(ValueModel):
    """What the application's screen is, read-only, as one record.

    The first thing to read on a machine that is not the one the measurements came from
    (``docs/dop3000/live-bringup.md`` §4). The counts are **evidence, not a verdict**: the
    reference install's clean manual screen is 43 visible controls in 4 panels and the
    instrument's own is 44 in 4, and an **assisted-mode** channel is 3 panels, so a count
    decides nothing on its own — the shape verdict and the stated process mode do
    (``layout_shape_reasons``, ``process_mode``), and the counts are here so a drift between
    two sessions is visible to a reader. The strip view says which of the three buttons means
    what, and the overlay says whether a modal is up while it should not be; the geometry is
    there so a screen that does not match can be described.

    JSON-serialisable on purpose: a fingerprint belongs in the job log beside the point it
    preceded.
    """

    class_name: str
    hwnd: int
    rect: tuple[int, int, int, int]
    maximized: bool
    screen: tuple[int, int]
    panels: int = Field(ge=0)
    visible_controls: int = Field(ge=0)
    strip: StripState
    overlay: OverlayKind | None = None
    layout_note: str | None = None
    #: The top-level window's caption as it was read (``WM_GETTEXT``): the one surface that
    #: states which process is on the screen. Kept as read — the vocabulary is applied by
    #: :func:`process_mode`, and a refusal names this string rather than a parsed value.
    caption: str = ""
    #: Which process the caption states, or ``None`` when it states none this driver knows —
    #: which is a refusal on the record paths and never a default (:func:`process_mode`).
    process_mode: ProcessMode | None = None
    #: The clauses of ``driver.layout_shape_reasons`` that failed for this screen; empty means
    #: it is one of the two accepted shapes with nothing over it. This is the verdict, where the
    #: counts above are the evidence (:data:`driver.EXPECTED_CONTROL_COUNT` is a reference
    #: reading of one install, never a gate).
    layout_shape_reasons: tuple[str, ...] = ()
    #: The counts, the panels and the strip's view as one sentence — carried on a **passing**
    #: screen too, because ``layout_note``'s contract is to be ``None`` there and the number a
    #: reader compares across sessions still has to live somewhere.
    #:
    # DEVIATION: §24.6's row says "each count appears in the note", and §24.3 keeps
    # ``layout_note()`` ``None`` whenever the shape passes — so a *passing* screen has no note to
    # put the count in. The count therefore rides here on the reading as well (and the refusal
    # note ends with this same sentence), which is what D4 asks for in words: "it stays in the
    # reading, in the note and in the record".
    layout_evidence: str = ""
    #: ``None`` when this session cannot read the cursor at all (the agent's own shell runs
    #: in a service session: ``GetCursorPos`` fails there with error 1459).
    cursor: tuple[int, int] | None = None
    is_foreground: bool = False


class PreflightReport(ValueModel):
    """One whole cycle's shape with **nothing stored** — the operator's sequence, made read-only.

    Every step's outcome is a field rather than only a line of output, because the point of a
    preflight is to be read back afterwards on an instrument nobody here can see. ``channel``
    is ``None`` when the run did not name one (the driver's own setting then decides, see
    :class:`~udv_echo_process.acquire.config.ChannelSetting`).
    """

    started_from: str
    view_after_record: str
    held_s: float = Field(gt=0)
    view_after_stop: str
    view_after_cancel: str
    channel: int | None = Field(default=None, ge=1)
    store_dialog_size: str | None = None
    store_dialog_children: int | None = Field(default=None, ge=0)
    store_name: str | None = None
    store_first_edit: str | None = None
    store_working_directory: str | None = None
    #: ``None`` when the caller named no directory to compare against.
    working_directory_matches: bool | None = None
    notes: tuple[str, ...] = ()


class StripState(ValueModel):
    """What the strip shows right now: structure in, view derived out.

    ``view`` is derived from the structure so a state cannot contradict itself;
    every press re-resolves the strip afterwards, because the panel's own rect
    and its child list change with the view.
    """

    button_count: int = Field(ge=0)
    has_slider: bool = False
    #: The store slider's maximum: the *selected block's* profile count, i.e. a
    #: free "how much is there to store" readout (docs/16 §3, §7).
    slider_max: int | None = Field(default=None, ge=0)

    @property
    def view(self) -> StripView:
        """The view this structure implies."""
        return classify_strip_view(self.button_count, self.has_slider)

    @property
    def controls(self) -> tuple[StripControl, ...]:
        """The top-row controls, left → right (empty for an unknown view)."""
        try:
            return strip_controls(self.view, self.button_count)
        except ValueError:
            return ()

    @property
    def is_startable(self) -> bool:
        """True when a point cycle may legally start from here."""
        return self.view in STARTABLE_VIEWS

    def index_of(self, control: StripControl) -> int:
        """Left→right index of ``control`` in this state's row."""
        return press_index(self.view, control, self.button_count)


@runtime_checkable
class Actuator(Protocol):
    """The GUI-driving surface a UDOP implementation must satisfy.

    Implementations must respect three contracts that were each paid for once:

    1. **Resolve structurally, never by id or coordinate.** Controls are located
       by role and geometry (the strip by its widgets' parent, the parameter
       column by position); nothing may key on a control id, and the strip must be
       re-resolved after every press (§7, §10).
    2. **Hold every strip press** (:data:`PRESS_HOLD_MS`) and **commit every
       numeric write** with the key event — the app's model, not the control's
       text, is what the read-back is compared against.
    3. **Check for an overlay before every press** (posted clicks ignore
       modality) and never leave one behind: an overlay left open traps the
       operator's cursor in the app (docs/16 §8, §9).
    """

    def layout_note(self) -> str | None:
        """A note when the screen is not one of the accepted measurement shapes.

        ``None`` means *a measurement screen of some mode with nothing over it* — the structural
        clauses of ``driver.layout_shape_reasons`` (the window class, the menubar and status
        bands, a strip whose row length maps into :data:`STRIP_BUTTON_ORDER`, no popup and no
        dialog panel, plus one of the two accepted shapes: a resolved sidebar parameter column
        with its seven roles, or no parameter column at all). **No total count is a gate** (plan
        §24.5, D4): 43 and 44 are two legitimate layouts, so the counts are carried as evidence in
        the note and refused on by nothing here.

        A note — a popup, a dialog panel, a screen satisfying neither shape — means parameter
        roles may resolve to the wrong widgets, so a run must refuse to start. ``None`` says
        nothing about *which* mode the screen is: that is the caption's statement and is checked
        against a declared expectation (``record_and_store(*, expected_mode)``).
        """
        ...

    def read_parameter(self, role: ParamRole) -> str:
        """The parameter column's current text for ``role``.

        The text is the *control's* value, which is why it is only used for the
        pre-record gate-clamp check; the stored file is the authority (docs/16
        §14).
        """
        ...

    def write_parameter(self, role: ParamRole, value: str) -> None:
        """Write and commit one parameter column field.

        Must use the numeric commit recipe (:data:`NUMERIC_WRITE_RECIPE`) — a
        write without the key event leaves the display changed and the model
        untouched (docs/14 §4).
        """
        ...

    def strip_state(self) -> StripState:
        """The strip's current structure, freshly resolved."""
        ...

    def wait_for_view(
        self, views: Iterable[StripView], *, timeout_s: float = VIEW_TIMEOUT_S
    ) -> StripState:
        """Poll until the strip reaches one of ``views``, then return its state.

        Returns the last state seen on timeout — the caller decides whether that
        is a failure, so a wedged view is reported rather than retried blindly.
        """
        ...

    def press(self, control: StripControl) -> None:
        """Press one strip button of the *current* view, held, by position."""
        ...

    def answer_overlay(self) -> OverlayKind | None:
        """Answer an overlay if one is up, and say what it was.

        Returns ``None`` when nothing was up. For
        :attr:`OverlayKind.STORE_DIALOG` nothing is pressed (the caller owns the
        name and the commit); for :attr:`OverlayKind.WARNING` the LEFT button is
        pressed (:func:`overlay_answer`).
        """
        ...

    def set_store_name(self, name: str) -> None:
        """Write the Store dialog's file-name field with the commit recipe.

        ``name`` must be unique: a repeat raises the overwrite warning, which
        wedges the app modal when unanswered (docs/16 §12b).
        """
        ...

    def commit_store(self) -> None:
        """Press the Store dialog's rightmost bottom button (``Do store``)."""
        ...

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        """Wait for a file that was not in ``directory`` before, and return it.

        Detects the *new name* rather than the arrival of any file, and the
        caller still has to let it quiesce before decoding: nothing is written
        before ``Do store``, but a file being written is not a file finished
        (docs/09 §5, docs/16 §7).
        """
        ...

    def record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: ProcessMode,
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        """The composed cycle: record ``duration_s``, stop, store as ``name``.

        ``expected_mode`` is **required and keyword-only** so no cycle can leave the expectation
        implied (plan §24.4): the process this run was measured against is a declaration the
        caller makes, and the screen's own caption is checked against it before the first press.
        A screen whose caption states the other process — or states none at all — refuses here,
        naming the caption, rather than recording data the run cannot claim.

        The contract, all of it measured:

        - start only from a verified :attr:`StripView.READY` (or dismiss a store
          view first) — never from :attr:`StripView.RECORDING`, or a leftover
          recording is stored under this point's name (docs/16 §15b);
        - answer overlays at every step, including the file-exists warning, which
          must be answered with ``No`` and then retried under a fresh name;
        - ``duration_s`` is the specification of the point; the achieved profile
          period is read from the status bar and logged, and the block cap must
          already have been checked against it
          (:func:`udv_echo_process.acquire.plan.assert_window_fits`);
        - return the stored file's path; the file's size and content are the
          authority, so the caller sizes it against the signature and decodes it
          (:mod:`udv_echo_process.acquire.log`).
        """
        ...
