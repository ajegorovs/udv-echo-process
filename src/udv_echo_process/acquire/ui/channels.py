"""Read-only structural reading of the operator-opened ``Channels`` popup.

Scope: **read-only, pure, offline.** Nothing here enumerates a window, sends a message, moves
a cursor, opens or closes a popup, presses a button, touches a combo or writes a field. The
input is one normalized :class:`~udv_echo_process.acquire.ui.model.ScreenObservation` — the
same projection every other interpreter under ``acquire/ui`` reads — so a captured tree and a
live screen are answered by one rule. The live half is
:mod:`udv_echo_process.acquire.channels_read`; this module decides *what the controls mean*.

The split of authority is the package's: this module interprets, an actuator acts. It therefore
returns no target, no press and no write — a caller that wants to act has to resolve again.

Evidence levels, in this repository's vocabulary (``docs/dop3000/device-verification.md``):

* **replay-verified** — ``tests/test_acquire_channels_read.py`` re-derives every statement below
  from a projected shape of a retained capture.
* **caption-attributed** — the custom buttons' captions are painted, not supplied by text queries
  (ledger B15); numeric edit text is read separately. Captions are attributed from the
  ``Channels`` popup capture and the crop set, and only while the band signature matches the one
  it was measured on. Every attributed caption carries its own provenance.
* **unknown** — a state the tree cannot state at all. It is reported as ``UNKNOWN`` and is never
  guessed.

Three rules the shape enforces:

1. **No tick, toggle, rolling or display state is inferred.** All of those widgets are custom
   buttons that paint their glyph; none states its state in text, and every one answers ``""``.
   Their ``state`` field is ``Literal["UNKNOWN"]``, so ``True``/``False`` and ``"unchecked"`` are
   not merely absent — they cannot be represented. An empty text is **not** an unticked cell.
2. **No amount is synthesised.** ``text`` is the exact raw text of the widget that owns it and
   ``value`` is the parse of that text; an empty or unparseable amount is a named refusal, never
   ``0``. The per-channel amounts' channel is caption-only, so it is ``None`` with a reason.
3. **A changed or ambiguous structure is refused, not reinterpreted.** Captions are keyed by the
   measured 8-band signature; a tree that bands differently, or two candidate popups, is a
   named refusal. Nothing falls back to another surface's meaning.

A successful read is a successful *inspection*: ``setup_verified`` is ``False`` on every report,
because nothing here establishes a mode, a tick, or an installed configuration.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from udv_echo_process.acquire.ui.model import ScreenObservation, UiNode, UiTree
from udv_echo_process.models.base import ValueModel

__all__ = [
    "CAPTION_SOURCE",
    "STATES_EVIDENCE",
    "Attribution",
    "ChannelCell",
    "ChannelsRead",
    "ChannelsSurface",
    "EntryRow",
    "ModeToggle",
    "PerChannelAmounts",
    "ValueSlot",
    "resolve_channels",
]

#: The only state a caption-less custom button can have here.
UNKNOWN = "UNKNOWN"

#: A ten-cell channel row is what this build paints (labels ``1``..``10``); a strip of another
#: size is a different surface and is refused rather than re-indexed.
STRIP_SIZE = 10

#: Band kinds in screen order, measured on the retained settings-popup capture
#: (``channels-inspection-20261020T195526-72bf1c``): the ``Use only channel`` toggle beside its
#: ``TSp_Button`` radio strip, ``Enable multiplexer``, ``Roll over the channels``, the
#: ``Use channels`` tick strip, the repeat value, the start-channel combo, the display toggle and
#: the ``For the current channel`` group box. A tree whose bands read otherwise has no captions.
SETTINGS_SIGNATURE: tuple[str, ...] = (
    "toggle+strip",
    "toggle",
    "toggle",
    "strip",
    "value",
    "combo",
    "toggle",
    "group",
)

#: The group box's own band shape: the apply-from combo, its two action buttons on one row, and
#: the two per-channel amounts on the next.
GROUP_SIGNATURE: tuple[str, ...] = ("combo", "buttons", "values")

#: Where an attributed caption comes from, carried on every report so a reader can tell a tree
#: fact from an attribution without opening this file.
CAPTION_SOURCE = (
    "attributed: custom-button captions are painted and caption-less in text queries; edit values "
    "are read separately, so the "
    "captions are the measured ones of the retained settings-popup capture "
    "(channels-inspection-20261020T195526-72bf1c) and the Channels crop; they hold only while the "
    "band signature does"
)

#: Why no state is ever read off a tick or a toggle.
STATES_EVIDENCE = (
    "custom button: caption-less (text == '') and the painted tick/relief is not in the tree "
    "(ledger B15); an empty text is NOT an unticked or off state"
)

_MEASUREMENT_EVIDENCE = (
    "the tree states no text for this control, so the state of the moment is unknown"
)

_PANEL_CLASSES = frozenset({"TSp_Panel", "TPanel"})
_BUTTON_CLASSES = frozenset({"TSp_Button", "TSp_Value_Button"})
#: The cell class of a channel strip — a plain custom button, never a value button.
_CELL_CLASS = "TSp_Button"
#: The value widget: a button that owns exactly one ``Edit`` with its text in it.
_VALUE_CLASS = "TSp_Value_Button"
_EDIT_CLASSES = frozenset({"Edit", "TSp_Edit"})
_MIN_TOLERANCE_PX = 8


class ChannelsSurface(str, Enum):
    """Which surface the popup read resolved to — decided before anything is bound.

    - ``SETTINGS_POPUP`` — the operator-opened ``Channels`` popup in its full, 8-band shape.
    - ``MULTIPLEXER_ON_ENTRY`` — the same panel **clipped to a one-entry strip** while the
      multiplexer is on: its furniture is still declared in the tree but the panel shows one row.
    - ``ABSENT`` — no popup of this shape is up. Not an error in the application; the command
      never opens one.
    - ``AMBIGUOUS`` — two candidate popups are up; a pick would be a guess.
    - ``WRONG_SURFACE`` — an application dialog is in front of the popup, so no popup reading is
      attributable to this screen.
    - ``CHANGED_STRUCTURE`` — one popup-shaped panel whose bands are not the measured ones.
    """

    SETTINGS_POPUP = "settings_popup"
    MULTIPLEXER_ON_ENTRY = "multiplexer_on_entry"
    ABSENT = "absent"
    AMBIGUOUS = "ambiguous"
    WRONG_SURFACE = "wrong_surface"
    CHANGED_STRUCTURE = "changed_structure"


class Attribution(ValueModel):
    """One caption, and exactly what it rests on."""

    caption: str
    provenance: str = CAPTION_SOURCE


class ValueSlot(ValueModel):
    """One amount the application *does* state in text, read from the widget that owns it.

    ``slot`` is the structural position, ``text`` the exact raw text, and ``value`` its parse.
    ``unknown`` says why ``value`` is ``None``; it is set only when the widget states nothing
    parseable, which is also a refusal on the report.

    ``hwnd``/``owner_hwnd`` are **action references, not permission**: the edit the text was read
    from and the value button that owns it, carried so a caller that writes this one field can
    re-resolve the same pair and compare it, rather than guessing a handle. Reading a slot still
    binds nothing, and a reference is stale the moment the tree changes.
    """

    slot: str
    attribution: Attribution
    text: str = ""
    value: int | float | None = None
    unknown: str | None = None
    #: The text control the value was read from, or ``None`` when it did not resolve.
    hwnd: int | None = None
    #: The value button that owns that text control, or ``None`` when it did not resolve.
    owner_hwnd: int | None = None


class ChannelCell(ValueModel):
    """One channel cell of a strip: a tick *candidate* with no readable state.

    There is no ``checked`` field and no boolean, on purpose: the tree states no state for a
    ``TSp_Button``, so "empty text ⇒ unticked" cannot be written without changing this type.
    """

    strip: str
    index: int
    attribution: Attribution
    state: Literal["UNKNOWN"] = UNKNOWN
    state_evidence: str = STATES_EVIDENCE
    hwnd: int | None = None


class ModeToggle(ValueModel):
    """A one-button mode row: named by the caption attributed to its band, state unreadable."""

    attribution: Attribution
    state: Literal["UNKNOWN"] = UNKNOWN
    state_evidence: str = STATES_EVIDENCE
    hwnd: int | None = None


class PerChannelAmounts(ValueModel):
    """The group box's amounts — whose channel the *caption* states and the tree does not."""

    profiles: ValueSlot
    seconds: ValueSlot
    #: ``UNKNOWN`` by construction: the channel the amounts apply from is caption-only here, and
    #: the type has no slot for a number somebody read off a crop.
    channel: Literal["UNKNOWN"] = UNKNOWN
    channel_unknown: str = (
        "the group's painted caption names the channel; the tree states nothing, so the channel "
        "these amounts belong to stays unknown until an operator states it"
    )


class EntryRow(ValueModel):
    """The reduced popup's single row — evidence only, and explicitly bound to no action."""

    attribution: Attribution
    state: Literal["UNKNOWN"] = UNKNOWN
    state_evidence: str = STATES_EVIDENCE
    #: ``False`` by construction: this module resolves meaning and never a press target.
    action_bound: Literal[False] = False
    hwnd: int | None = None


class ChannelsRead(ValueModel):
    """What the popup states, and everything it does not — one report, never a partial overlay.

    ``readable`` is ``True`` when the surface resolved and no amount was refused. It says the
    *inspection* succeeded; ``setup_verified`` is ``False`` on every report, because a reading of
    a popup establishes no mode, no tick state and no installed configuration.
    """

    surface: ChannelsSurface
    readable: bool
    #: The popup panel this reading was taken against — an action reference for the resolve that
    #: produced it, and evidence; never an identity and never a press target.
    popup: UiNode | None = None
    signature: tuple[str, ...] = ()
    repeat: ValueSlot | None = None
    start_channel: ValueSlot | None = None
    apply_from: ValueSlot | None = None
    per_channel: PerChannelAmounts | None = None
    channel_ticks: tuple[ChannelCell, ...] = ()
    toggles: tuple[ModeToggle, ...] = ()
    entry: EntryRow | None = None
    caption_source: str = CAPTION_SOURCE
    uncertainties: tuple[str, ...] = ()
    refusals: tuple[str, ...] = ()
    setup_verified: Literal[False] = False


# ---------------------------------------------------------------------------------------------
# geometry: bands, not absolute coordinates
# ---------------------------------------------------------------------------------------------


def _tolerance(nodes: tuple[UiNode, ...]) -> int:
    heights = [node.rect.height for node in nodes if node.rect is not None]
    return max(_MIN_TOLERANCE_PX, min(heights) // 2) if heights else _MIN_TOLERANCE_PX


def _bands(nodes: tuple[UiNode, ...]) -> list[list[UiNode]]:
    """Group nodes into visual bands by vertical **centre**, left → right inside each band.

    Only relative distance is used, so a capture translated by a constant offset bands
    identically: a rect is a property of the moment a surface was shown, never an identity.
    """
    bands: list[list[UiNode]] = []
    current: list[UiNode] = []
    anchor: int | None = None
    tolerance = _tolerance(nodes)
    for node in sorted(
        nodes, key=lambda n: (n.rect.centre[1], n.rect.left) if n.rect else (0, 0)
    ):
        centre = node.rect.centre[1] if node.rect else 0
        if anchor is None or centre - anchor > tolerance:
            if current:
                bands.append(current)
            current, anchor = [node], centre
        else:
            current.append(node)
    if current:
        bands.append(current)
    return [sorted(band, key=lambda n: n.rect.left if n.rect else 0) for band in bands]


def _children(tree: UiTree, panel: UiNode) -> tuple[UiNode, ...]:
    """The panel's own visible children that state a rect — the only rows a rule may read."""
    return tuple(
        node
        for node in tree.children(panel)
        if node.visible and node.rect is not None and node.hwnd is not None
    )


def _strip_children(tree: UiTree, panel: UiNode) -> tuple[UiNode, ...]:
    """The panel's ten cells, left → right; empty when the panel is not a ten-cell strip."""
    kids = _children(tree, panel)
    if len(kids) != STRIP_SIZE or any(kid.cls != _CELL_CLASS for kid in kids):
        return ()
    if len({kid.rect.left for kid in kids}) != STRIP_SIZE:
        return ()
    return kids


def _edit_under(tree: UiTree, owner: UiNode) -> UiNode | None:
    """The one text control ``owner`` owns — its own ``Edit``, never a sibling's."""
    edits = [kid for kid in _children(tree, owner) if kid.cls in _EDIT_CLASSES]
    return edits[0] if len(edits) == 1 else None


def _kind(tree: UiTree, band: list[UiNode], group_hwnds: set[int | None]) -> str:
    """What one band of a popup is, from its own members."""
    if len(band) == 1:
        node = band[0]
        if node.hwnd in group_hwnds:
            return "group"
        if node.cls == "TComboBox" and _edit_under(tree, node) is not None:
            return "combo"
        if node.cls == _VALUE_CLASS and _edit_under(tree, node) is not None:
            return "value"
        if node.cls == _CELL_CLASS:
            return "toggle"
        if node.cls in _PANEL_CLASSES and _strip_children(tree, node):
            return "strip"
        return "unknown"
    strip = next(
        (
            node
            for node in band
            if node.cls in _PANEL_CLASSES and _strip_children(tree, node)
        ),
        None,
    )
    if strip is not None and len(band) == 2:
        other = next(node for node in band if node.hwnd != strip.hwnd)
        if other.cls == _CELL_CLASS:
            return "toggle+strip"
    # The amounts row is asked **before** the plain-button row: a value button is a button, and
    # reading the group's two amounts as "two action buttons" is exactly the mislabel to avoid.
    if len(band) == 2 and all(
        node.cls == _VALUE_CLASS and _edit_under(tree, node) is not None
        for node in band
    ):
        return "values"
    if all(node.cls == _CELL_CLASS for node in band):
        size = len(band)
        return "buttons" if size == 2 else ("strip" if size == STRIP_SIZE else "row")
    return "row"


def _signature(tree: UiTree, kids: tuple[UiNode, ...]) -> tuple[str, ...]:
    """The band kinds of one popup panel, in screen order.

    ``group`` is decided structurally: a band of one panel-class child that does **not** host a
    ten-cell strip is the amounts box, while a panel that does host one is a channel strip. Two
    different questions, so the group's handle is never inferred from a position.
    """
    group_hwnds = {
        node.hwnd
        for node in kids
        if node.cls in _PANEL_CLASSES and not _strip_children(tree, node)
    }
    return tuple(_kind(tree, band, group_hwnds) for band in _bands(kids))


# ---------------------------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------------------------


def _parse(kind: str, text: str) -> int | float | None:
    stripped = text.strip()
    try:
        if kind == "int":
            return int(stripped) if stripped.lstrip("-").isdigit() else None
        value = float(stripped.replace(",", "."))
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def _slot(
    slot: str, caption: str, owner: UiNode | None, edit: UiNode | None
) -> tuple[ValueSlot, str | None]:
    """One amount, plus the refusal it earns when the widget states nothing parseable."""
    value_kind = "float" if slot == "seconds" else "int"
    text = "" if edit is None else edit.text
    value = _parse(value_kind, text)
    slot_model = ValueSlot(
        slot=slot,
        attribution=Attribution(caption=caption),
        text=text,
        value=value,
        hwnd=None if edit is None else edit.hwnd,
        owner_hwnd=None if owner is None else owner.hwnd,
        unknown=None
        if value is not None
        else f"the {slot} widget states {text!r}, which is not a {value_kind} amount; nothing is assumed",
    )
    refusal = None
    if value is None:
        refusal = (
            f"{slot}: the widget states {text!r}, which is not a {value_kind} amount "
            f"(owner hwnd {None if owner is None else owner.hwnd}); nothing is assumed"
        )
    return slot_model, refusal


# ---------------------------------------------------------------------------------------------
# the settings popup
# ---------------------------------------------------------------------------------------------


def _strip_tokens(
    tree: UiTree, caption: str, panel: UiNode, strip: str
) -> tuple[ChannelCell, ...]:
    return tuple(
        ChannelCell(
            strip=strip,
            index=index,
            attribution=Attribution(caption=f"{caption} · channel {index}"),
            hwnd=cell.hwnd,
        )
        for index, cell in enumerate(_strip_children(tree, panel), start=1)
    )


def _settings(
    tree: UiTree, panel: UiNode, kids: tuple[UiNode, ...], signature: tuple[str, ...]
) -> ChannelsRead:
    bands = _bands(kids)
    group = next(
        (
            node
            for node in kids
            if node.cls in _PANEL_CLASSES and not _strip_children(tree, node)
        ),
        None,
    )
    refusals: list[str] = []
    uncertainties: list[str] = [
        (
            "a successful inspection is not a verified setup: no mode, tick, rolling or display "
            "state is established by this reading, and nothing was pressed"
        ),
        (
            "the popup's own presence is the operator's action; the tree may be transient, so "
            "this reading is evidence about a moment and not proof that a mode is active"
        ),
    ]

    def one(kind: str) -> UiNode | None:
        return next(
            (band[0] for band in bands if _kind(tree, band, set()) == kind), None
        )

    toggles: list[ModeToggle] = []
    toggle_captions = [
        "Use only channel",
        "Enable multiplexer",
        "Roll over the channels",
        "Display all channels in the same graph",
    ]
    for band in bands:
        for node in band:
            if node.cls == _CELL_CLASS and _edit_under(tree, node) is None:
                caption = (
                    toggle_captions[len(toggles)]
                    if len(toggles) < len(toggle_captions)
                    else UNKNOWN
                )
                toggles.append(
                    ModeToggle(attribution=Attribution(caption=caption), hwnd=node.hwnd)
                )

    channel_ticks: list[ChannelCell] = []
    for band in bands:
        kind = _kind(tree, band, set())
        for node in band:
            if node.cls in _PANEL_CLASSES and _strip_children(tree, node):
                # Two strips on this surface, and they are not the same control: the one beside
                # the ``Use only channel`` toggle is its radio row, the standalone one is the
                # ``Use channels`` tick row. The band kind is what tells them apart.
                if kind == "toggle+strip":
                    channel_ticks.extend(
                        _strip_tokens(
                            tree, "Use only channel", node, "use_only_channel"
                        )
                    )
                else:
                    channel_ticks.extend(
                        _strip_tokens(tree, "Use channels", node, "use_channels")
                    )

    repeat_owner = one("value")
    start_owner = one("combo")
    repeat, repeat_refusal = _slot(
        "repeat",
        "Repeat the acquisition sequence",
        repeat_owner,
        None if repeat_owner is None else _edit_under(tree, repeat_owner),
    )
    start, start_refusal = _slot(
        "start_channel",
        "Start the sequence by using channel",
        start_owner,
        None if start_owner is None else _edit_under(tree, start_owner),
    )
    for refusal in (repeat_refusal, start_refusal):
        if refusal is not None:
            refusals.append(refusal)

    per_channel: PerChannelAmounts | None = None
    apply_from: ValueSlot | None = None
    if group is None:
        refusals.append(
            "the group box (per-channel amounts and their two action buttons) did not resolve, so "
            "no profiles/seconds/apply-from value is bound"
        )
    else:
        group_kids = _children(tree, group)
        group_bands = _bands(group_kids)
        group_signature = tuple(_kind(tree, band, set()) for band in group_bands)
        if group_signature != GROUP_SIGNATURE:
            refusals.append(
                f"the group box's bands read {group_signature!r}; the measured shape is "
                f"{GROUP_SIGNATURE!r} — nothing in it is bound"
            )
        else:
            combo_band, button_band, value_band = group_bands
            apply_owner = combo_band[0]
            apply_from, refusal = _slot(
                "apply_from",
                "Apply parameters from channel",
                apply_owner,
                _edit_under(tree, apply_owner),
            )
            if refusal is not None:
                refusals.append(refusal)
            profiles_owner, seconds_owner = value_band[0], value_band[1]
            profiles, profiles_refusal = _slot(
                "profiles",
                "Acquire ... Profiles",
                profiles_owner,
                _edit_under(tree, profiles_owner),
            )
            seconds, seconds_refusal = _slot(
                "seconds",
                "... during seconds",
                seconds_owner,
                _edit_under(tree, seconds_owner),
            )
            for refusal in (profiles_refusal, seconds_refusal):
                if refusal is not None:
                    refusals.append(refusal)
            per_channel = PerChannelAmounts(profiles=profiles, seconds=seconds)
            uncertainties.append(
                "the per-channel amounts' channel is caption-only: the group's painted caption "
                "names it and the tree states nothing, so it is carried as unknown"
            )
            uncertainties.append(
                "profiles and seconds are attributed by their left-to-right order on the measured "
                "build; the tree states neither caption, so a build that swaps the two boxes would "
                f"be read swapped (buttons: {[node.hwnd for node in button_band]!r})"
            )

    return ChannelsRead(
        surface=ChannelsSurface.SETTINGS_POPUP,
        readable=not refusals,
        popup=panel,
        signature=signature,
        repeat=repeat,
        start_channel=start,
        apply_from=apply_from,
        per_channel=per_channel,
        channel_ticks=tuple(channel_ticks),
        toggles=tuple(toggles),
        uncertainties=tuple(uncertainties),
        refusals=tuple(refusals),
    )


# ---------------------------------------------------------------------------------------------
# the surfaces it refuses, and the reduced one
# ---------------------------------------------------------------------------------------------


def _refused(
    surface: ChannelsSurface,
    refusals: tuple[str, ...],
    *,
    panel: UiNode | None = None,
    signature: tuple[str, ...] = (),
) -> ChannelsRead:
    if surface is ChannelsSurface.ABSENT:
        subscription = (
            "no Channels popup is open on this window; this command never opens one"
        )
        refusals = refusals or (f"{subscription} — open Channels by hand and re-run",)
    return ChannelsRead(
        surface=surface,
        readable=False,
        popup=panel,
        signature=signature,
        uncertainties=(
            "nothing was pressed, opened or closed; the screen was read once",
        ),
        refusals=refusals,
    )


def _entry(tree: UiTree, panel: UiNode, kids: tuple[UiNode, ...]) -> ChannelsRead:
    contained = tuple(
        kid
        for kid in kids
        if panel.rect is not None and panel.rect.holds_centre_of(kid.rect)
    )
    row = contained[0]
    return ChannelsRead(
        surface=ChannelsSurface.MULTIPLEXER_ON_ENTRY,
        readable=True,
        popup=panel,
        signature=("clip+entry",),
        entry=EntryRow(
            attribution=Attribution(
                caption="Disable multiplexer",
                provenance=(
                    "operator-attributed for the reduced popup of this build (the multiplexer-on "
                    "capture of 2026-10-20 states the caption beside its one painted entry); the "
                    "tree states no text for the widget, so the caption belongs to the surface"
                ),
            ),
            hwnd=row.hwnd,
        ),
        uncertainties=(
            (
                "the popup is clipped to one entry and still declares the settings furniture "
                "outside its own rect; those rows are not shown, so no amount is read from them"
            ),
            (
                "the entry's effect is unobserved: no press is bound and nothing here "
                "establishes which mode the application is in"
            ),
            f"the single contained row (hwnd {row.hwnd}) states no text; its state is unknown",
        ),
    )


def _panel_nodes(observation: ScreenObservation) -> tuple[UiNode, ...]:
    """The panels this screen states — the resolver's list, else the tree's own top-level ones.

    A live role map publishes ``panels``; a captured tree may state none, and a screen whose
    panels were never projected is still readable by structure, the same way
    :meth:`UiTree.children` falls back to containment. Without that fallback a partial fixture
    would read as "no popup is up", which is a claim about a screen it never looked at.
    """
    if observation.panels:
        return observation.panels
    window = observation.tree.window
    panels = tuple(
        node for node in observation.tree.visible() if node.cls in _PANEL_CLASSES
    )
    if not observation.tree.parent_of or window is None:
        return panels
    return tuple(
        node for node in panels if observation.tree.parent(node.hwnd) == window
    )


def _candidates(
    observation: ScreenObservation,
) -> list[tuple[UiNode, tuple[UiNode, ...]]]:
    """Panels that could be the popup: a ten-cell strip or a toggle-beside-strip first band.

    The measurement screen's own furniture is excluded by identity (the menubar band, the
    recording strip, the plot and any dialog panel), so a clean screen resolves nothing here
    rather than being read as a popup that changed.
    """
    excluded = {node.hwnd for node in observation.dialogs}
    if observation.menu.band is not None:
        excluded.add(observation.menu.band.hwnd)
    if observation.strip.panel is not None:
        excluded.add(observation.strip.panel.hwnd)
    if observation.plot is not None:
        excluded.add(observation.plot.hwnd)
    found: list[tuple[UiNode, tuple[UiNode, ...]]] = []
    seen: set[int | None] = set()
    for panel in _panel_nodes(observation):
        if (
            panel.hwnd is None
            or panel.hwnd in excluded
            or panel.hwnd in seen
            or panel.rect is None
            or not panel.visible
        ):
            continue
        seen.add(panel.hwnd)
        kids = _children(observation.tree, panel)
        if len(kids) < 2:
            continue
        hosts_strip = any(
            kid.cls in _PANEL_CLASSES
            and len(_strip_children(observation.tree, kid)) == STRIP_SIZE
            for kid in kids
        )
        first = _kind(observation.tree, _bands(kids)[0], set())
        if hosts_strip or first == "toggle+strip":
            found.append((panel, kids))
    return found


def resolve_channels(observation: ScreenObservation) -> ChannelsRead:
    """Read the operator-opened ``Channels`` popup out of one screen observation.

    Decided in this order, and each answer is final: an application dialog in front (the popup
    cannot be read over it), then how many popup-shaped panels are up (none / more than one),
    then the single panel's own shape — the reduced one-entry clip, the measured 8-band settings
    popup, or a structure this module has no captions for.

    The screen is read **once**, from ``observation``; nothing here enumerates or presses.
    """
    if observation.dialogs:
        named = ", ".join(
            f"hwnd {panel.hwnd} class {panel.cls}" for panel in observation.dialogs
        )
        return _refused(
            ChannelsSurface.WRONG_SURFACE,
            (
                (
                    f"an application dialog is in front ({named}): the Channels popup cannot be "
                    "read over it, and this command answers no dialog"
                ),
            ),
            panel=observation.dialogs[0],
        )

    candidates = _candidates(observation)
    if not candidates:
        return _refused(ChannelsSurface.ABSENT, ())
    if len(candidates) > 1:
        named = "; ".join(
            f"hwnd {panel.hwnd} at {panel.rect.as_tuple()!r}" for panel, _ in candidates
        )
        return _refused(
            ChannelsSurface.AMBIGUOUS,
            (
                (
                    f"{len(candidates)} panels could be the Channels popup ({named}): a pick "
                    "would be a guess, so nothing is bound"
                ),
            ),
            panel=candidates[0][0],
        )

    panel, kids = candidates[0]
    signature = _signature(observation.tree, kids)
    contained = tuple(
        kid
        for kid in kids
        if panel.rect is not None and panel.rect.holds_centre_of(kid.rect)
    )
    if len(contained) == 1 and len(kids) > 1 and signature != SETTINGS_SIGNATURE:
        return _entry(observation.tree, panel, kids)
    if signature == SETTINGS_SIGNATURE:
        return _settings(observation.tree, panel, kids, signature)
    return _refused(
        ChannelsSurface.CHANGED_STRUCTURE,
        (
            (
                f"the popup's bands read {signature!r}, and the measured settings popup's are "
                f"{SETTINGS_SIGNATURE!r}; the captions hold only for the measured signature, so "
                "nothing is bound"
            ),
        ),
        panel=panel,
        signature=signature,
    )
