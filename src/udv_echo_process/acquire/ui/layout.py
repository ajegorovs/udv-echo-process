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
- the **stated process mode** clause (:func:`process_mode_clause`) — the one thing that cannot
  be checked structurally, because only the caption states it;
- the **channel mode** reading (:func:`screen_mode`), read off the panel that resolved;
- the pure geometry the binding rules are written in (:func:`_inside`,
  :func:`_point_in_rect`, :func:`_contains`, :func:`_column_bands`) and the dialog-panel
  predicate (:func:`_is_dialog_panel`), plus the path comparison a Store-dialog field is held to
  (:func:`same_directory`, :func:`normalized_path`).

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
from itertools import pairwise
from pathlib import Path

from udv_echo_process.acquire.actuator import (
    PARAM_COLUMN_ORDER,
    PROCESS_MODE_PREFIXES,
    STRIP_BUTTON_ORDER,
    ChannelMode,
    OverlayKind,
    ProcessMode,
    StripView,
    process_mode,
)
from udv_echo_process.acquire.ui.model import (
    ParameterPanelState,
    ScreenObservation,
)

__all__ = [
    "DIALOG_COLUMN_GAP",
    "EXPECTED_CONTROL_COUNT",
    "EXPECTED_PANEL_COUNT",
    "MAIN_CLASS",
    "MENU_ORDER",
    "MODE_ASSISTED",
    "MODE_MANUAL",
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
]

MAIN_CLASS = "TMain_Scr"
#: The menu bar's buttons, left -> right (``recon/udop_roles.py``).
MENU_ORDER: tuple[str, ...] = (
    "File",
    "Preferences",
    "Parameters",
    "Compute",
    "Cursors",
    "Filters",
    "Tools",
    "Channels",
    "UDV mode",
    "Display",
    "Help",
)
#: The clean measurement screen's fingerprint **on the reference install, as evidence** — two
#: independent launches. It is no longer a gate (plan §24.5, D4): the instrument's own clean
#: screen states 44 in 4, because its parameter column paints one more row, so the two numbers
#: separate two legitimate layouts rather than a clean screen from an unclean one. What this
#: pair is for now is the comparison a reader makes in :func:`layout_evidence` and in the run's
#: record — a drift worth seeing, never a reason to stop a run.
EXPECTED_CONTROL_COUNT = 43
EXPECTED_PANEL_COUNT = 4

#: How a **dialog** is identified, from the reference's own predicate
#: (``recon/41_burst_sampling_volume.py``, ``find_dialog``): a panel that is not part of
#: the measurement layout, is wider than :data:`_DIALOG_MIN_W`, and is full of controls —
#: at least :data:`_DIALOG_MIN_CHILDREN` direct children, or holding a ``TSp_Browse``.
#: The measured operating dialog (627x384, read live) also holds input controls of its
#: own directly — a header combo and seven ``TSp_Value_Button`` fields — which is the same
#: kind of structural evidence and is accepted by the same predicate, so a dialog the
#: reference would have found is never rejected here.
_DIALOG_MIN_W, _DIALOG_MIN_CHILDREN = 400, 15

#: How wide a gap between two value fields' left edges makes them different **columns** of the
#: dialog's table. Measured 2026-09-18: fields inside one column sit within 5 px of each other
#: (786/783/788) while the columns are 200 px apart (786 → 987 → 1187), so anything from ~50 to
#: ~190 px separates them and the middle of that range is not a magic number but a margin.
DIALOG_COLUMN_GAP = 100
#: The classes that make a panel an *input* panel rather than a strip or a warning row.
_DIALOG_INPUT_CLASSES = ("TEdit", "TSp_Edit", "TComboBox", "TSp_Value_Button")

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


def _inside(panel: dict | None, k: dict) -> bool:
    """True when ``k``'s centre lies inside ``panel``'s rect."""
    if panel is None:
        return False
    cx, cy = k["left"] + k["w"] // 2, k["top"] + k["h"] // 2
    return (
        panel["left"] <= cx <= panel["left"] + panel["w"]
        and panel["top"] <= cy <= panel["top"] + panel["h"]
    )


def _point_in_rect(rect: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    """True when ``point`` lies inside ``rect`` — both in screen coordinates.

    Edge-inclusive on purpose: a point on the clip's boundary is *inside* it, so a move
    there is not clamped and nothing needs releasing.
    """
    left, top, right, bottom = rect
    return left <= point[0] <= right and top <= point[1] <= bottom


def _contains(outer: Mapping, inner: Mapping) -> bool:
    """True when ``inner``'s rect lies inside ``outer``'s, as the application lays them out."""
    return (
        outer["left"] <= inner["left"]
        and outer["top"] <= inner["top"]
        and inner["left"] + inner["w"] <= outer["left"] + outer["w"]
        and inner["top"] + inner["h"] <= outer["top"] + outer["h"]
    )


def _column_bands(lefts: Sequence[int]) -> list[int]:
    """Column index per left edge, splitting where the gap is wider than :data:`DIALOG_COLUMN_GAP`.

    The bands are derived rather than hard-coded so that the *rule* is evidence — the columns of
    this table are 200 px apart while fields inside one are within a few px (measured) — and the
    shape that comes out of it is then checked against :data:`DIALOG_COLUMN_ROWS`.
    """
    if not lefts:
        return []
    order = sorted(set(lefts))
    band = {order[0]: 0}
    for previous, current in pairwise(order):
        band[current] = band[previous] + (1 if current - previous > DIALOG_COLUMN_GAP else 0)
    return [band[left] for left in lefts]


def _is_dialog_panel(panel: dict, kids: Sequence[dict]) -> bool:
    """True when ``panel`` is one of this application's modal dialogs.

    The reference's own predicate, kept: a panel is a dialog when it is full of controls —
    at least :data:`_DIALOG_MIN_CHILDREN` direct children, or a ``TSp_Browse`` among them
    — and is wider than :data:`_DIALOG_MIN_W` (``recon/41_burst_sampling_volume.py``:
    ``len(kids) >= 15 or any(k["cls"] == "TSp_Browse" for k in kids)``, then
    ``dlg["w"] > 400``). The measured operating dialog (627x384) holds a header combo and
    seven value buttons *directly*, so holding input controls of its own
    (:data:`_DIALOG_INPUT_CLASSES`) is the same kind of evidence and is accepted here too:
    a dialog the reference would have found is never rejected by this driver.
    """
    if panel["w"] <= _DIALOG_MIN_W:
        return False
    if len(kids) >= _DIALOG_MIN_CHILDREN:
        return True
    if any(k["cls"] == "TSp_Browse" for k in kids):
        return True
    return any(k["cls"] in _DIALOG_INPUT_CLASSES for k in kids)


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


def _client_top(panel: Mapping, roles: Mapping) -> int:
    """The panel's top relative to the client's top (the origin :meth:`_resolve` read)."""
    origin = roles.get("origin") or (0, 0)
    return int(panel["top"]) - int(origin[1])


def _client_bottom(panel: Mapping, roles: Mapping) -> int:
    """The panel's bottom relative to the client's top."""
    return _client_top(panel, roles) + int(panel["h"])


def layout_shape_reasons(roles: Mapping) -> tuple[str, ...]:
    """Every clause of the shape check this resolved tree fails — empty when it passes.

    The gate's structural half (plan §24.3): **one common core plus the manual shape**, the only
    shape this experiment measures on. A screen with no parameter column used to be the accepted
    *assisted* shape, and that acceptance is what ledger B01 removed: the column can be hidden by
    the application's own ``Preferences`` option while the channel stays manual, so its absence
    is refused with a clause that names both readings and claims neither.

    The common core: the window is :data:`MAIN_CLASS`; the menubar band resolves at the client's
    top and a status band reaches the client's bottom; the strip panel resolves with a row whose
    length maps into :data:`STRIP_BUTTON_ORDER` (the silent case §21.3 item 3 names: *a different
    button panel in the plot's middle band*); and nothing is over it — no menu popup and no
    dialog panel. The manual shape: that column resolves with its seven
    :data:`PARAM_COLUMN_ORDER` roles.

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
    reasons: list[str] = []
    panels = list(roles.get("panels") or ())
    client = roles.get("client") or (0, 0)
    client_h = int(client[1]) if len(client) > 1 else 0
    margin = max(1, int(client_h * _BAND_MARGIN_FRACTION))

    class_name = roles.get("class_name")
    if class_name != MAIN_CLASS:
        reasons.append(
            f"the window class is {class_name!r} where this measurement screen is {MAIN_CLASS!r}"
        )

    menu = roles.get("menu") or {}
    menu_band = roles.get("menu_band")
    if menu_band is None or not menu:
        reasons.append(
            f"the menubar band did not resolve: {len(menu)} of {len(MENU_ORDER)} menubar "
            "button(s) were found"
            + (" and no panel hosts them" if menu_band is None else "")
        )
    elif _client_top(menu_band, roles) > margin:
        reasons.append(
            f"the menubar band is painted {_client_top(menu_band, roles)} px down a "
            f"{client_h} px client, so it is not the band at the client's top that a "
            "measurement screen paints"
        )

    strip = roles.get("strip_panel")
    row = list(roles.get("strip_row") or ())
    view = None
    if roles.get("state") is not None:
        try:
            view = StripView(str(roles["state"]))
        except ValueError:
            view = None
    if strip is None:
        reasons.append(
            "no recording strip panel resolved: no short button-hosting panel sits in the "
            "plot's 0.30-0.70 band, so which buttons mean pause, record and stop is unstated"
        )
    elif roles.get("plot") is None:
        reasons.append(
            "the plot band did not resolve, so the strip's own rule (the button panel in the "
            "middle of the plot) could not be applied to the panel that was found"
        )
    elif view is None or (view, len(row)) not in STRIP_BUTTON_ORDER:
        reasons.append(
            f"the strip's row holds {len(row)} button(s) in view {roles.get('state')!r}, which "
            "is no row in STRIP_BUTTON_ORDER: a different button panel sits in the plot's "
            "middle band, and a press would be bound to the wrong position"
        )

    # A band **below the strip** that reaches the client's bottom — the status bar, found by shape
    # rather than by its index in the panel list. A sidebar column that runs the height of the
    # window does not answer this: it starts above the strip, and the band being asked for is the
    # one under everything.
    status_bands = [
        panel
        for panel in panels
        if panel is not menu_band
        and panel is not strip
        and (strip is None or int(panel["top"]) >= _client_bottom(strip, roles))
        and _client_bottom(panel, roles) >= client_h - margin
    ]
    if not status_bands:
        reasons.append(
            f"no status band reaches the client's bottom: the {len(panels)} panel(s) at this "
            f"level end at "
            f"{max((_client_bottom(panel, roles) for panel in panels), default=0)} px of a "
            f"{client_h} px client"
        )

    if roles.get("open_popup"):
        reasons.append(
            "a menu popup is open: the parameter roles below it would bind to the popup's own "
            "controls (a popup is never dismissed by WM_CLOSE here)"
        )

    dialogs = sorted(
        (roles.get("value_dialogs") or set()) | (roles.get("browse_dialogs") or set())
    )
    if dialogs:
        doors = [
            (panel["rect"], panel["cls"])
            for panel in panels
            if panel["hwnd"] in set(dialogs)
        ]
        reasons.append(
            f"a dialog is up: {len(dialogs)} panel(s) of this screen are application dialogs "
            f"and not the measurement layout ({doors}), so nothing below them is the surface "
            "these roles were bound to"
        )

    params = roles.get("params") or {}
    rows = roles.get("param_rows") or []
    column = roles.get("left_panel")
    panel = observation_of(roles).parameter_panel
    # The manual shape is the **only** shape this experiment measures on. A column that resolved
    # *without* its roles is the case §24.3 names as neither shape — a binding that would write
    # the wrong fields. A screen with no column at all was the accepted *assisted* shape before
    # ledger B01 and is now a clause of its own: the panel may have been hidden by the
    # application's own `Preferences` option while the channel stayed manual, so the refusal
    # names both readings of the absence and claims neither. The clause belongs to the
    # *measurement screen* — the common core above is what establishes that this tree is one —
    # because naming the missing column on a surface that is not a measurement screen at all is
    # exactly the misdiagnosis ledger B08 records.
    if panel is ParameterPanelState.INCOMPLETE:
        reasons.append(
            f"the sidebar parameter column resolved at "
            f"{None if column is None else column['rect']} with {len(params)} of the "
            f"{len(PARAM_COLUMN_ORDER)} roles ({[role.value for role in PARAM_COLUMN_ORDER]}) "
            f"and {len(rows)} row(s): that is neither accepted shape, and a point's writes "
            "would land on the wrong fields"
        )
    elif panel is ParameterPanelState.ABSENT and (
        class_name == MAIN_CLASS
        and menu_band is not None
        and menu
        and roles.get("plot") is not None
        and status_bands
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
    above are answers about the *same* tree. The **parameter panel's state** is carried here for
    the same reason the counts are: it is the reading an operator needs beside a refusal, and it
    is what tells "this channel has no manual panel to write" apart from "the panel was there and
    the tree was read wrong" (ledger B01).
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
        f"resolved with {len(params)} of {len(PARAM_COLUMN_ORDER)} role(s); the fast-access "
        f"panel reads {observation.parameter_panel.value!r}; "
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
