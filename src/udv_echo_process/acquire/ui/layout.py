"""The pure layout interpreter: which surface is this, and is this state safe to act from.

Layer 2 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5), moved out of
:mod:`udv_echo_process.acquire.driver` **verbatim**. Nothing here calls ``user32``, sends a
message, moves a cursor or enumerates a window: every function answers from an already-resolved
tree and returns either a verdict or a refusal clause.

What the module owns, and why each piece is here rather than in the driver:

- the **shape gate** (:func:`layout_shape_reasons`), the **evidence line**
  (:func:`layout_evidence`) and their composition (:func:`layout_refusal`) — plan §24.3/§24.5,
  pure over the tree so the same tree answers them on a captured fixture, on a fake and on the
  live screen;
- the **surface classification** (:func:`surface_kind`, :func:`classify_surface` and the clauses
  of :func:`surface_clauses`): which surface is this — measurement, overlay, dialog, popup,
  replacement or unknown — decided **before** any press target is resolved, so an overlay cannot
  be read as the strip (ledger B06) and a whole-screen replacement surface is never read as a
  channel mode (ledger B08);
- the **stated process mode** clause (:func:`process_mode_clause`) — the one thing that cannot
  be checked structurally, because only the caption states it;
- the **channel mode** reading (:func:`screen_mode`), which reads a mode out of the panel that
  resolved and never out of the panel that did not (ledger B01);
- the pure geometry this module's own clauses are written in (:func:`_point_in_rect`,
  :func:`_band_margin`, :func:`_client_top`) and the path comparison a Store-dialog field is held
  to (:func:`same_directory`, :func:`normalized_path`).

What is *not* here any more, and why: the menubar's vocabulary and the ``Parameters`` anchor
(:mod:`udv_echo_process.acquire.ui.menu`, Patch 2's widget slice), the dialog's value-table
geometry and the dialog-panel predicate (:mod:`udv_echo_process.acquire.ui.dialog`) and the
strip's row, state and clauses (:mod:`udv_echo_process.acquire.ui.strip`). Each of those is
imported here and re-published, so ``ui.layout``'s callers (the driver among them) keep resolving
while every rule lives with the surface it is about — the names Patch 2's layout slice published
from here are this module's compatibility floor, not its property.

The observation the interpreter reads is normalized in
:mod:`udv_echo_process.acquire.ui.model` — ``Rect``/``UiNode``/``UiTree``, ``SurfaceKind`` and
``ParameterPanelState`` — and :func:`observation_of` is the one projection from the resolver's
role map onto it, so a caller cannot invent a second, differently-typed view of the same tree.

**Evidence.** Everything in this module is *cloud-verified* against the committed control-tree
fixtures (``tests/data/udop-measurement-screen-tree*.json``,
``tests/data/udop-parameters-dialog-tree.json``) and the fixtures the tests synthesise from the
measured crops (``docs/dop3000/ui-crops/``). The rules encoded here were measured live where the
module docstrings say so; **no claim is made that any of them behaves on the device** — that is
``docs/dop3000/device-verification.md``'s business and stays *device-pending*.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from udv_echo_process.acquire.actuator import (
    PARAM_COLUMN_ORDER,
    PROCESS_MODE_PREFIXES,
    ChannelMode,
    OverlayKind,
    ProcessMode,
    process_mode,
)
from udv_echo_process.acquire.ui.dialog import (
    _DIALOG_INPUT_CLASSES,
    _DIALOG_MIN_CHILDREN,
    _DIALOG_MIN_W,
    DIALOG_COLUMN_GAP,
    _column_bands,
    _contains,
    _is_dialog_panel,
)
from udv_echo_process.acquire.ui.menu import (
    MEASURED_BAR,
    MENU_ORDER,
    _inside,
    anchor_clause,
)
from udv_echo_process.acquire.ui.model import (
    ParameterPanelState,
    ScreenObservation,
    SurfaceKind,
    UiNode,
)
from udv_echo_process.acquire.ui.strip import strip_clauses

__all__ = [
    # The names below are ``ui/dialog.py``'s and ``ui/menu.py``'s as of Patch 2's widget slice,
    # imported and re-published here because this module published them first (Patch 2's layout
    # slice) and a caller or a test written against ``ui.layout`` keeps resolving — the same
    # compatibility rule the whole package is under, one level down.
    "DIALOG_COLUMN_GAP",
    "EXPECTED_CONTROL_COUNT",
    "EXPECTED_PANEL_COUNT",
    "MAIN_CLASS",
    "MENU_ORDER",
    "MODE_ASSISTED",
    "MODE_MANUAL",
    "_DIALOG_INPUT_CLASSES",
    "_DIALOG_MIN_CHILDREN",
    "_DIALOG_MIN_W",
    "_column_bands",
    "_contains",
    "_inside",
    "_is_dialog_panel",
    "classify_surface",
    "layout_evidence",
    "layout_refusal",
    "layout_shape_reasons",
    "normalized_path",
    "observation_of",
    "panel_mode",
    "parameter_panel_absent_clause",
    "process_mode_clause",
    "same_directory",
    "screen_mode",
    "surface_clauses",
    "surface_kind",
]

MAIN_CLASS = "TMain_Scr"
# ``MENU_ORDER`` is ``ui/menu.py``'s as of Patch 2's widget slice — the menubar's vocabulary
# belongs with the one menubar binding this driver has — and is imported above and re-published
# here, so ``ui.layout.MENU_ORDER`` and ``driver.MENU_ORDER`` keep resolving.
#: The clean measurement screen's fingerprint **on the reference install, as evidence** — two
#: independent launches. It is no longer a gate (plan §24.5, D4): the instrument's own clean
#: screen states 44 in 4, because its parameter column paints one more row, so the two numbers
#: separate two legitimate layouts rather than a clean screen from an unclean one. What this
#: pair is for now is the comparison a reader makes in :func:`layout_evidence` and in the run's
#: record — a drift worth seeing, never a reason to stop a run.
EXPECTED_CONTROL_COUNT = 43
EXPECTED_PANEL_COUNT = 4

# The dialog constants and the dialog-panel predicate above the bands — ``_DIALOG_MIN_W``,
# ``_DIALOG_MIN_CHILDREN``, ``_DIALOG_INPUT_CLASSES``, ``DIALOG_COLUMN_GAP`` and
# ``_is_dialog_panel`` — are ``ui/dialog.py``'s as of Patch 2's widget slice: they are the rule
# by which this application's dialogs and their value table are read, and that is that module's
# business. They are imported above and re-published here so ``ui.layout``'s callers (the driver
# among them) keep resolving.

#: How much of the client's height a band may occupy and still count as sitting at the client's
#: own top or bottom edge. A **margin, not a coordinate** — the measured menubar is ~25 px of a
#: 1027 px client and the status bar owns the last ~25 px, and nothing binds to either number:
#: the clauses below only ask whether the band the resolver found is painted where a measurement
#: screen paints it. The same argument as :data:`DIALOG_COLUMN_GAP`.
_BAND_MARGIN_FRACTION = 0.15

#: The two ways this application's parameters panel can present a channel, as the names this
#: driver reports them by. The vocabulary is
#: :class:`~udv_echo_process.acquire.actuator.ChannelMode`, which carries what each panel is
#: (they are told apart by structure, never by a caption: every one of these widgets is
#: caption-less).
MODE_ASSISTED, MODE_MANUAL = ChannelMode.ASSISTED.value, ChannelMode.MANUAL.value


def observation_of(roles: Mapping) -> ScreenObservation:
    """The normalized observation of one resolved role map — the interpreters' input.

    One line on purpose: the projection itself lives on the model
    (:meth:`~udv_echo_process.acquire.ui.model.ScreenObservation.from_roles`), written down once
    so the pure rules below cannot read a second, differently-typed view of the same tree.
    """
    return ScreenObservation.from_roles(roles)


# ------------------------------------------------------------------------ the moved geometry


# ``_inside`` — a control's centre inside a panel's rect — is ``ui/menu.py``'s as of Patch 2's
# widget slice (the parameter column and the popup's entries are both read with it), imported
# above and re-published here so ``ui.layout._inside`` keeps resolving.

def _point_in_rect(rect: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    """True when ``point`` lies inside ``rect`` — both in screen coordinates.

    Edge-inclusive on purpose: a point on the clip's boundary is *inside* it, so a move
    there is not clamped and nothing needs releasing.
    """
    left, top, right, bottom = rect
    return left <= point[0] <= right and top <= point[1] <= bottom


# ``_contains``, ``_column_bands`` and ``_is_dialog_panel`` — the dialog's value-table geometry
# and the predicate that identifies a dialog panel — are ``ui/dialog.py``'s as of Patch 2's widget
# slice, imported above and re-published here so a caller that read them from this module (the
# driver's own dialog resolution does) keeps resolving.


def same_directory(shown: str, expected: str | Path) -> bool:
    """True when the dialog's ``Working directory`` text names ``expected``.

    Compared on the *resolved* path, never on the two strings: the application
    renders the path in its own normal form (case, trailing separator, its own
    contraction), and a cosmetic difference must not fail a point — while a real
    difference must never pass as one. An empty or unreadable value is *not* a
    match: "no path shown" is not "the path I expected".
    """
    text = (shown or "").strip().strip('"').strip()
    if not text:
        return False
    try:
        return os.path.normcase(str(Path(text).resolve())) == os.path.normcase(
            str(Path(expected).resolve())
        )
    except (OSError, ValueError):
        return False


def normalized_path(text: str) -> str:
    """A path as it can be compared: trailing separators and case removed, slashes unified."""
    cleaned = text.strip().replace("/", "\\").rstrip("\\")
    return cleaned.casefold()


#: The plot's middle band, as a fraction of its height: the strip floats inside the monitor and
#: the resolver scores a **strip candidate** by the centre of its button row falling in here
#: (``_resolve``'s own ``0.30 <= frac <= 0.70``). The surface classifier applies the *same*
#: rule to every panel rather than to the winner, which is what makes a second button panel in
#: this band visible as an overlay instead of being silently accepted (ledger B06).
_STRIP_BAND = (0.30, 0.70)


def _same_node(one: UiNode, other: UiNode | None) -> bool:
    """True when two projected rows are the same control — by handle, else by identity.

    A handle is only an action reference, but *within one observation* it is the one key that
    survives a re-projection of the same row, so it is what identity comparisons use here; two
    rect-less rows of a partial fixture are compared by object identity.
    """
    if other is None:
        return False
    if one is other:
        return True
    return one.hwnd is not None and one.hwnd == other.hwnd


def _top_of(panel: UiNode) -> int:
    """A panel's screen top, or ``0`` when the projection carries no rect for it."""
    return 0 if panel.rect is None else panel.rect.top


def _bottom_of(panel: UiNode) -> int:
    """A panel's screen bottom, or ``0`` when the projection carries no rect for it."""
    return 0 if panel.rect is None else panel.rect.bottom


def _rect_text(panel: UiNode | None) -> str:
    """A panel's rect as the refusal clauses render it (the tuple form the driver prints).

    ``UiNode`` is what the clauses hold (the observation's own projection, never the raw row), so
    this is the one place a rect is turned into text: a projection that carries no rect — or no
    panel at all — renders as ``"None"``, which is what the clause says about a geometry nobody
    measured. A row that stated its rectangle as ``left/top/w/h`` renders as the resolved tuple,
    because that is the rect the projection itself read (``Rect.from_control``).
    """
    return "None" if panel is None or panel.rect is None else str(panel.rect.as_tuple())


def _client_height(observation: ScreenObservation) -> int:
    """The client's height, as the resolver read it (``0`` when the tree states none)."""
    client = observation.client or (0, 0)
    return int(client[1]) if len(client) > 1 else 0


def _band_margin(observation: ScreenObservation) -> int:
    """The top/bottom band margin for this client — a fraction, never a coordinate."""
    return max(1, int(_client_height(observation) * _BAND_MARGIN_FRACTION))


def _client_top(panel: UiNode, observation: ScreenObservation) -> int:
    """The panel's top relative to the client's top (the origin :meth:`_resolve` read).

    Takes the projected panel and the observation rather than the raw role map, because that is
    what the clauses hold once the tree has been normalized (``observation_of``) — the arithmetic
    is the one the flat module did.
    """
    return _top_of(panel) - int(observation.origin[1])


def _client_bottom(panel: UiNode, observation: ScreenObservation) -> int:
    """The panel's bottom relative to the client's top."""
    return _client_top(panel, observation) + (
        0 if panel.rect is None else panel.rect.height
    )


def _menubar_resolved(observation: ScreenObservation) -> bool:
    """True when the menubar band resolved *and* hosts at least one button."""
    return observation.menu.band is not None and bool(observation.menu.buttons)


def _status_bands(observation: ScreenObservation) -> tuple[UiNode, ...]:
    """The panels that reach the client's bottom and sit below the strip — the status band.

    A band **below the strip** that reaches the client's bottom, found by shape rather than by
    its index in the panel list. A sidebar column that runs the height of the window does not
    answer this: it starts above the strip, and the band being asked for is the one under
    everything.
    """
    client_h = _client_height(observation)
    margin = _band_margin(observation)
    strip = observation.strip.panel
    return tuple(
        panel
        for panel in observation.panels
        if not _same_node(panel, observation.menu.band)
        and not _same_node(panel, strip)
        and (strip is None or _top_of(panel) >= _client_bottom(strip, observation))
        and _client_bottom(panel, observation) >= client_h - margin
    )


def _hosts_button_band(observation: ScreenObservation) -> bool:
    """True when some panel of this tree hosts a ``TSp_Button`` of its own, anywhere."""
    return any(
        observation.tree.inside(panel, cls="TSp_Button") for panel in observation.panels
    )


def _replacement_evidence(observation: ScreenObservation) -> bool:
    """True when the client area is another surface's content, not a measurement screen.

    ``UI-OVERLAY-22`` is the measured frame: a whole-window capture of ``Compare profiles`` in
    which the parameter column, the menu band, the strip and the status bar are **all** gone and
    only the surface's own widget band is left (``UI-OVERLAY-19``, ``Measure US field``, is the
    other instance the ledger names). So the evidence is the *absence of the measurement
    skeleton* — no menubar band and no plot — together with a client area that still hosts a
    button band of its own. Nothing about a channel mode is read from it (ledger B08): the same
    frame is what the old reading took for an assisted channel.
    """
    return (
        not _menubar_resolved(observation)
        and observation.plot is None
        and _hosts_button_band(observation)
    )


def _overlay_candidates(observation: ScreenObservation) -> tuple[UiNode, ...]:
    """Panels **besides the resolved strip** that host a button row inside the plot's band.

    The resolver scores a strip candidate by the *centre of its button row* falling in the plot's
    0.30-0.70 band and takes the panel hosting the most buttons, so a button panel sitting in that
    band's middle wins the vote — which is the live incident B06 records, where an open
    ``Define TGC`` panel (``UI-OVERLAY-01``..``UI-OVERLAY-04``, 453x123, caption-less, movable)
    was bound as the strip and the run then diagnosed *its* button row, calling it a known
    ``ready`` row of ``Pause / Record / Clear and restart``.

    This is that same rule applied to every panel rather than to the winner: a panel inside the
    plot, hosting its own ``TSp_Button`` row whose centre falls in the same band, while the strip
    was bound somewhere else — two candidates where a measurement screen has exactly one. The
    candidate is reported, never pressed: the finding is that the panel the resolver bound may be
    an overlay's button panel rather than the recording strip, and that is a refusal.
    """
    strip, plot = observation.strip.panel, observation.plot
    if strip is None or plot is None or plot.rect is None:
        return ()
    band_low, band_high = _STRIP_BAND
    candidates: list[UiNode] = []
    for panel in observation.panels:
        if (
            _same_node(panel, strip)
            or _same_node(panel, observation.menu.band)
            or any(_same_node(panel, dialog) for dialog in observation.dialogs)
        ):
            continue
        if panel.rect is None or not plot.rect.holds_centre_of(panel.rect):
            continue
        buttons = observation.tree.inside(panel, cls="TSp_Button")
        centres = [button.rect.centre for button in buttons if button.rect is not None]
        if not centres:
            continue
        centre_y = sum(y for _x, y in centres) / len(centres)
        fraction = (centre_y - plot.rect.top) / max(1, plot.rect.height)
        if band_low <= fraction <= band_high:
            candidates.append(panel)
    return tuple(candidates)


def surface_kind(observation: ScreenObservation) -> SurfaceKind:
    """Which of the :class:`SurfaceKind` surfaces this observation is.

    **Decided before any press target is resolved** (architecture invariant 3, ledger B06): the
    resolver's own vote can hand an overlay over as the strip candidate, and a diagnosis that
    then starts from the button row blames the strip for a surface problem — the run refused, but
    for the wrong reason, which costs a live slot. The order of the tests is the order of the
    evidence's strength:

    1. a window class that is not the measurement screen's — nothing else about the tree is
       trustworthy, so ``UNKNOWN``;
    2. an application dialog panel is up — ``DIALOG``;
    3. the menubar's own popup is open — ``POPUP`` (it is the strip resolver's decoy);
    4. the measurement skeleton is gone while the client area hosts a widget band —
       ``REPLACEMENT`` (B08: ``Compare profiles`` / ``Measure US field`` replace the client
       area, so "no sidebar and no strip" is another *surface* and not a channel mode);
    5. a second button panel sits in the plot's middle band — ``OVERLAY`` (B06);
    6. the measurement anchors all resolved — ``MEASUREMENT``;
    7. otherwise ``UNKNOWN``: the refusal state, which has no binding and no mode.

    A kind is **not** a press permission: ``MEASUREMENT`` says the surface is the measurement
    screen, and the gate's other clauses (the parameter panel's state, the strip view, the
    process mode) still stand between it and any action.
    """
    if observation.class_name is not None and observation.class_name != MAIN_CLASS:
        return SurfaceKind.UNKNOWN
    if observation.dialogs:
        return SurfaceKind.DIALOG
    if observation.popup_open:
        return SurfaceKind.POPUP
    if _replacement_evidence(observation):
        return SurfaceKind.REPLACEMENT
    if _overlay_candidates(observation):
        return SurfaceKind.OVERLAY
    if (
        not _menubar_resolved(observation)
        or observation.plot is None
        or not _status_bands(observation)
    ):
        return SurfaceKind.UNKNOWN
    return SurfaceKind.MEASUREMENT


def classify_surface(roles: Mapping) -> SurfaceKind:
    """The :class:`SurfaceKind` of a resolved role map — the front door for a caller with a tree.

    The same projection :func:`layout_shape_reasons` makes, exposed on its own so a caller (a
    diagnostic, a probe, a preflight) can name the surface without reading the gate's clauses.
    """
    return surface_kind(observation_of(roles))


def surface_clauses(observation: ScreenObservation) -> tuple[str, ...]:
    """One clause per **active non-measurement surface**, first among the gate's clauses.

    This is what "classify before you diagnose" means in the gate: the clauses here are built
    from the *surface* the resolver's tree shows, and they come before the strip row, the
    parameter column and the bands — because the row a wrong-surface screen would diagnose is a
    symptom of the surface being wrong (ledger B06, ledger B08: a replacement surface would
    otherwise be diagnosed as a missing menubar, plot and status *band*). Every clause names the
    evidence it rests on and where it was read, so the refusal is diagnosable from the log alone
    (plan §24.5 D5).

    ``UNKNOWN`` contributes nothing: it is the absence of a classification, and the structural
    clauses of :func:`layout_shape_reasons` (the window class, the menubar band, the plot, the
    status band) already state exactly what was missing.
    """
    clauses: list[str] = []
    if _replacement_evidence(observation):
        band = ", ".join(_rect_text(panel) for panel in observation.panels)
        clauses.append(
            "the active surface is not the measurement screen: no menubar band and no plot "
            f"band resolved while {len(observation.panels)} panel(s) of the client area host "
            f"the surface's own buttons ({band}) — a whole-screen replacement surface "
            "('Compare profiles', 'Measure US field') replaces the client area, so 'no sidebar "
            "and no strip' is another surface here and not a channel mode, and no press may be "
            "bound against it"
        )
    for panel in _overlay_candidates(observation):
        strip = observation.strip.panel
        clauses.append(
            "an overlay is over the measurement screen: "
            f"{_rect_text(panel)} hosts its own button row inside the plot's 0.30-0.70 band "
            "besides the panel the resolver bound as the strip "
            f"({_rect_text(strip) if strip is not None else 'none'}), so that binding may be an "
            "overlay's button panel rather than the recording strip — the strip's own rule (the "
            "button panel in the middle of the plot) is ambiguous on this tree and nothing may "
            "be pressed out of it"
        )
    if observation.dialogs:
        doors = [
            (panel.rect.as_tuple() if panel.rect else None, panel.cls)
            for panel in observation.dialogs
        ]
        clauses.append(
            f"a dialog is up: {len(observation.dialogs)} panel(s) of this screen are application "
            f"dialogs and not the measurement layout ({doors}), so nothing below them is the "
            "surface these roles were bound to"
        )
    if observation.popup_open:
        clauses.append(
            "a menu popup is open: the parameter roles below it would bind to the popup's own "
            "controls (a popup is never dismissed by WM_CLOSE here)"
        )
    return tuple(clauses)


# ------------------------------------------------------------------- the channel mode reading


def panel_mode(panel: dict, kids: Sequence[dict]) -> str:
    """Which mode the application's parameters panel was built for, structurally.

    The slider is the mark: the assisted panel carries the acquisition-rate/quality slider and
    derives resolution and gate count, so it has none of the manual panel's value table.
    """
    if any(k["cls"] == "TSp_Sliding_Bar" for k in kids):
        return MODE_ASSISTED
    return MODE_MANUAL


def screen_mode(roles: Mapping) -> ChannelMode | None:
    """The mode of the channel **on the measurement screen**, read without pressing anything.

    :func:`panel_mode` answers the same question from a parameters *dialog*, which costs the
    menubar hover the dialog is opened with. The measurement screen can answer it too, and for
    free: the sidebar parameter column exists only for a channel in manual mode, so a resolved
    column **is** ``MANUAL`` — positive evidence, and the only positive evidence there is.

    **Absence is not evidence of a mode** (ledger B01). The preference *Show fast access
    parameters panel (not available in assisted mode)* can hide the column while the channel
    stays manual — quoted from ``UI-OVERLAY-06``, the ``Preferences`` dialog, where that is the
    ticked checkbox — and the same screen is what an assisted channel paints. A live incident
    disproved the older reading (this function used to answer ``ASSISTED`` from the missing
    column alone), and the cost of guessing is a refused campaign whose diagnosis points at the
    channel's *mode* instead of at the screen's configuration.

    ``None`` therefore means "no mode could be read", whether a dialog or a popup is up, the
    layout is unrecognised, or the column is simply not there. Assisted mode is out of scope for
    this experiment, and a manual acquisition requires the panel **present and complete** —
    which is a refusal about the *screen* and is made by
    :func:`layout_shape_reasons`, not a mode read here.
    """
    observation = observation_of(roles)
    if observation.parameter_roles:
        return ChannelMode.MANUAL
    return None


# ------------------------------------------------------------------------ the layout gate

#: How the absent fast-access panel is explained, in one place, so the gate's clause and the
#: driver's missing-field failure cannot drift apart — and so the wording an operator reads is
#: the wording ``docs/dop3000/acquisition-ui-model.md`` §2 quotes.
_ABSENT_PANEL_REASON = (
    "the fast-access parameter panel is absent: this automation operates a manual channel and "
    "requires that panel present and complete; it may be hidden by Preferences ('Show fast "
    "access parameters panel (not available in assisted mode)') or the channel may be assisted. "
    "Restore/verify the manual measurement screen before continuing"
)


def parameter_panel_absent_clause(separator: str = "") -> str:
    """The one wording for an absent fast-access parameter panel (ledger B01).

    ``separator`` is what a caller prepends when the clause continues a sentence — the driver's
    missing-field failure appends it after the role list — while the gate takes it as a clause of
    its own. The text is deliberately **both readings at once**: a panel hidden by the
    application's own ``Preferences`` option and an assisted channel paint the same screen, so a
    refusal that named only one of them would send the operator to the wrong place (the live
    incident B01 records). Nothing here claims which of the two it is.
    """
    return separator + _ABSENT_PANEL_REASON


def layout_shape_reasons(roles: Mapping) -> tuple[str, ...]:
    """Every clause of the shape check this resolved tree fails — empty when it passes.

    The gate's structural half (plan §24.3): **one common core plus the manual shape**, the only
    shape this experiment measures on. A screen with no parameter column used to be the accepted
    *assisted* shape, and that acceptance is what ledger B01 removed: the column can be hidden by
    the application's own ``Preferences`` option while the channel stays manual, so its absence
    is refused with a clause that names both readings and claims neither.

    The clauses come in two groups. The **surface group first** (:func:`surface_clauses`): which
    surface is this, before any strip row or parameter column is diagnosed — because the row a
    wrong-surface screen would diagnose is a *symptom* of the surface being wrong, and a refusal
    that named it would send the operator looking for a strip that is not there (ledger B06).

    Then the common core: the window is :data:`MAIN_CLASS`; the menubar band resolves at the
    client's top **with a provable** ``Parameters`` anchor (:func:`…ui.menu.anchor_clause` — an
    unprovable anchor is a refusal *before* the one real-cursor gesture, ledger B03) and a status
    band reaches the client's bottom; the strip panel resolves with a row whose length maps into
    :data:`STRIP_BUTTON_ORDER` (:func:`…ui.strip.strip_clauses` — the silent case §21.3 item 3
    names, *a different button panel in the plot's middle band*, and the ambiguous four-button
    no-slider row of ledger B10, which is refused rather than gated on); and nothing is over it —
    no menu popup and no dialog panel (both of which the surface group has already named). The
    manual shape: that column resolves with its seven :data:`PARAM_COLUMN_ORDER` roles.

    **No total count is a gate here** (plan §24.5, D4): 43 and 44 are two legitimate layouts, so
    the counts are evidence carried by :func:`layout_evidence` and refused on by nothing.

    Pure over an already-resolved role map (:meth:`Win32Actuator._resolve`), so it runs on a
    captured tree on a host with no application at all as well as on a live one — and nothing
    here reads the window, presses anything or opens anything.
    """
    # DEVIATION: the plan lists `_find_overlay(roles)` among the asserted resolvers, but that
    # finder walks parent handles through `win32gui` and cannot be called from a pure function
    # over a resolved tree. The popup and dialog clauses therefore come from the tree's own
    # resolved sets (`open_popup`, `_dialog_panels`' two halves), and the driver's own note adds
    # the `_find_overlay` clause on top (`layout_refusal`, whose `overlay=` is that result).
    observation = observation_of(roles)
    reasons: list[str] = list(surface_clauses(observation))
    panels = list(observation.panels)
    client_h = _client_height(observation)
    margin = _band_margin(observation)

    class_name = observation.class_name
    if class_name != MAIN_CLASS:
        reasons.append(
            f"the window class is {class_name!r} where this measurement screen is {MAIN_CLASS!r}"
        )

    # The menubar, then the `Parameters` anchor: the band has to resolve, and the *anchor* has to
    # be provable — never an index into a name list, which silently renames every later role when
    # a variant omits an entry (ledger B03). Both clauses come from `ui/menu.py`, which owns the
    # bar's vocabulary and the one binding this driver has.
    menu_band = observation.menu.band
    if not _menubar_resolved(observation):
        reasons.append(
            f"the menubar band did not resolve: {len(observation.menu.buttons)} of the "
            f"measured bar's {len(MEASURED_BAR)} entries were found"
            + (" and no panel hosts them" if menu_band is None else "")
        )
    elif _client_top(menu_band, observation) > margin:
        reasons.append(
            f"the menubar band is painted {_client_top(menu_band, observation)} px down a "
            f"{client_h} px client, so it is not the band at the client's top that a "
            "measurement screen paints"
        )
    anchor = anchor_clause(observation)
    if anchor is not None:
        reasons.append(anchor)

    # The strip's own clauses, whole: the row a press is bound to, and the ambiguous row that has
    # no binding at all — ``ui/strip.py`` answers both, so the gate never reads a row itself and
    # never gates on one the crops contradict (ledger B10).
    reasons.extend(strip_clauses(observation))

    if not _status_bands(observation):
        reasons.append(
            f"no status band reaches the client's bottom: the {len(panels)} panel(s) at this "
            f"level end at "
            f"{max((_client_bottom(panel, observation) for panel in panels), default=0)} px of a "
            f"{client_h} px client"
        )

    params = roles.get("params") or {}
    rows = roles.get("param_rows") or []
    panel = observation.parameter_panel
    # The manual shape is the **only** shape this experiment measures on. A column that resolved
    # *without* its roles is the case §24.3 names as neither shape — a binding that would write
    # the wrong fields. A screen with no column at all was the accepted *assisted* shape before
    # ledger B01 and is now a clause of its own: the panel may have been hidden by the
    # application's own `Preferences` option while the channel stayed manual, so the refusal
    # names both readings of the absence and claims neither. The clause belongs to the
    # *measurement screen* — asserted here through the surface classification rather than through
    # a private conjunction of anchors — because naming the missing column on a surface that is
    # not a measurement screen at all is exactly the misdiagnosis ledger B08 records.
    if panel is ParameterPanelState.INCOMPLETE:
        reasons.append(
            f"the sidebar parameter column resolved at "
            f"{_rect_text(observation.parameter_column)} with {len(params)} of the "
            f"{len(PARAM_COLUMN_ORDER)} roles ({[role.value for role in PARAM_COLUMN_ORDER]}) "
            f"and {len(rows)} row(s): that is neither accepted shape, and a point's writes "
            "would land on the wrong fields"
        )
    elif panel is ParameterPanelState.ABSENT and (
        surface_kind(observation) is SurfaceKind.MEASUREMENT
    ):
        reasons.append(
            parameter_panel_absent_clause()
            + f" (this tree resolved {len(params)} of the {len(PARAM_COLUMN_ORDER)} column "
            f"role(s) and {len(rows)} row(s), with no sidebar column panel)"
        )
    return tuple(reasons)


def layout_evidence(roles: Mapping) -> str:
    """What this tree is, as one sentence: the counts, the panels, the strip's view, the shapes.

    The evidence half of the gate (plan §24.5, D4). A total count is **not** a gate: ``43`` and
    ``44`` separate the reference install's clean layout from the instrument's, not a clean
    screen from an unclean one, so the numbers are carried here, into the reading
    (``ScreenFingerprint.layout_evidence``) and into the run's record, where a reader comparing
    two sessions can see a drift — while nothing a run does is stopped by one.

    Read off the normalized observation (:func:`observation_of`), so the sentence and the clauses
    above are answers about the *same* tree. The **surface kind** and the **parameter panel's
    state** are carried here for the same reason the counts are: they are the readings an
    operator needs beside a refusal, and the two together are what tell "this is another
    surface" and "this channel has no manual panel to write" apart from "the tree was read
    wrong" (ledger B01, B08).
    """
    observation = observation_of(roles)
    panels = list(observation.panels)
    row = list(observation.strip.row)
    params = observation.parameter_roles
    dialogs = len(observation.dialogs)
    return (
        f"{observation.class_name}: {len(observation.tree.nodes)} visible controls in "
        f"{len(panels)} panels (the reference install's clean screen reads "
        f"{EXPECTED_CONTROL_COUNT} in {EXPECTED_PANEL_COUNT}); the strip's row holds "
        f"{len(row)} button(s) in view {observation.strip.state_reading!r}; the parameter column "
        f"resolved with {len(params)} of {len(PARAM_COLUMN_ORDER)} role(s); the active surface "
        f"reads {surface_kind(observation).value!r} with the fast-access panel "
        f"{observation.parameter_panel.value!r}; "
        f"{'a menu popup is open' if observation.popup_open else 'no menu popup'}; "
        f"{dialogs} dialog panel(s)"
    )


def process_mode_clause(caption: str, expected: ProcessMode) -> str | None:
    """One clause when ``caption`` does not state ``expected``; ``None`` when it does.

    The mode rung (plan §24.4), and the one thing that cannot be checked structurally: the
    caption is the only surface that states which process is on the screen. ``None`` from
    :func:`…actuator.process_mode` is a **refusal, not a default** — an empty caption states
    nothing, and a caption outside the fixed vocabulary is a version this driver was not
    measured against — on the same argument as ``routed_channel`` (§12.1).

    Pure over the string that was read, so the clause a live refusal shows is the clause the
    tests pin, and the caption names itself in it (D5).
    """
    stated = process_mode(caption)
    if stated is expected:
        return None
    if not caption.strip():
        return (
            "nothing stated the mode: the top-level window's caption is empty, so which process "
            f"this screen is in is unstated where this run was measured against "
            f"{expected.value!r}"
        )
    if stated is None:
        names = [prefix for _mode, prefix in PROCESS_MODE_PREFIXES]
        return (
            f"the caption {caption!r} states no process mode this driver knows ({names}), where "
            f"this run was measured against {expected.value!r}"
        )
    return (
        f"the process mode is {stated.value!r} where this run was measured against "
        f"{expected.value!r} (the caption read {caption!r})"
    )


def layout_refusal(
    roles: Mapping,
    *,
    overlay: OverlayKind | None = None,
    caption: str = "",
    expected_mode: ProcessMode | None = None,
) -> str | None:
    """The refusal for one resolved tree — one clause per reason, or ``None`` when it passes.

    The composition ``Win32Actuator.layout_note`` answers with, written as a pure function so
    the whole gate is testable on a captured tree: the shape clauses
    (:func:`layout_shape_reasons`), the overlay ``_find_overlay`` found for this same tree, and —
    when a run states one — the mode clause (:func:`process_mode_clause`). **Separate clauses,
    each naming what was read** (plan §24.5, D5): a single "unclean layout" sentence is what made
    yesterday's refusal look like a layout drift when it was a mode the run was not measured
    against.

    ``expected_mode=None`` is the diagnostic reading (``acquire status``, the probe path): the
    shape is still checked and the mode is not — a diagnostic that refused would be useless, and
    the *stated* mode is reported as a fact instead.
    """
    # DEVIATION: §24.3 lists "the process mode is stated" as the last clause of the common core,
    # but the same section heads the shape check *mode-independent* and gives it a signature over
    # an already-resolved tree (``layout_shape_reasons(roles)``) — and the caption is a separate
    # read that the tree does not carry. So the mode is a clause of *this* composition, added only
    # when a run states an expectation, and the pure shape check stays mode-independent.
    parts = list(layout_shape_reasons(roles))
    if overlay is not None:
        parts.append(
            f"an overlay is up ({overlay.value!r}): it is not the measurement layout, and "
            "nothing under it resolves to the widgets these roles were bound to"
        )
    if expected_mode is not None:
        clause = process_mode_clause(caption, expected_mode)
        if clause is not None:
            parts.append(clause)
    if not parts:
        return None
    return "; ".join(parts) + f" — the screen reads: {layout_evidence(roles)}"
