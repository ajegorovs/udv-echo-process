"""The ``Parameters`` anchor: the only menubar binding this driver has, and what proves it.

Layer 2 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5), moved out of
:mod:`udv_echo_process.acquire.driver` by Patch 2's widget slice. Nothing here touches ``user32``,
moves a cursor, sends a message or reads a live window: every function answers from an
already-resolved tree.

**What this module is the authority for**

- the menubar's **measured bar** and the vocabulary that names it (:data:`MENU_ORDER`,
  :data:`MEASURED_BAR`) — the eleven names the reference resolver carried and the ten entries
  ``UI-WINDOW-01`` paints, left → right;
- the ``Parameters`` **anchor**: its relative-location signature (:func:`anchor_button`) and the
  refusal that replaces it when the signature cannot be shown (:func:`anchor_clause`) — ledger
  B03;
- the ``Parameters`` popup's own signature (:data:`PARAMETERS_POPUP_LEFT`,
  :data:`PARAMETERS_POPUP_MIN_H` — the panel geometry ``recon/41_burst_sampling_volume.py`` read
  live at ``(169, 55, 401, 250)``) and the order its entries are pressed in
  (:func:`entry_buttons`);
- the prose one popup-entry press is reported with (:func:`observation_text`), and the rule that
  finds a control inside a panel by its centre (:func:`_inside`, which the parameter column's own
  resolution also uses).

**What belongs elsewhere**

- the gesture: the hover that opens this menu is ``Win32Actuator._hover_centre`` and the entry
  press is ``Win32Actuator._press_entry`` — the two gestures the live sessions proved;
- the live reads that confirm the chain — finding the popup panel, requiring it *visible*,
  pressing the topmost entry and verifying the dialog it opened — stay in ``driver.py`` (they
  enumerate windows and send messages: Patch 3's business);
- every dialog fact and the channel comparison are :mod:`udv_echo_process.acquire.ui.dialog`'s.

**There is deliberately no name → button map here.** An index map is not an identity: the
application's variants do not paint the same bar, the entries carry no tree text
(``WM_GETTEXT`` answers ``""`` for every ``TSp_*`` widget), so one absent entry silently renames
every later role. ``Parameters`` therefore has exactly one binding, and it is published only when
the signature below can be shown on the tree at hand — otherwise the run refuses *before* any
cursor movement (architecture invariant 6, ledger B03).

**The signature, and why each clause is there** (UI-WINDOW-01: "`File` `Preferences` `Parameters`
`Compute` `Cursors` `Filters` `Tools` `Channels` `Display`, and then `Help` alone at the band's
right end — so the bar carries ten entries"):

1. the band resolved and hosts buttons — no band, no anchor;
2. the bar's painted length is one of the two measured ones (:data:`MEASURED_BAR_LENGTHS`: the ten
   entries ``UI-WINDOW-01`` paints, or the eleven names :data:`MENU_ORDER` carries, which include
   ``UDV mode`` — the entry ``UI-MENU-01``'s own frame shows this build does not paint). A bar of
   any other length is a painted set the anchor was never measured against, and there is no tree
   text to fall back on;
3. the anchor's **relative location**: it is the third button of the bar. Its position, never an
   index into a name list, is what identifies it. What a *name* can additionally be held to is
   agreement with the bar it was read from — clause 4 — because no tree on this application can
   state a predecessor's name at all: ``Win32Actuator._resolve`` publishes ``roles["menu"] = {}``
   and fills it with the **anchor** once this function has proven one, so the anchor is the only
   entry a live tree ever names. A clause that read a binding as the list of the anchor's
   predecessors therefore read this function's own output and refused the application's own clean
   measurement screen — the first V0 reading after the refactor, on the instrument, 2026-09-18
   (``docs/dop3000/device-verification.md``). The identity a device confirms is settled *after*
   the hover, never by a name: the popup's measured signature, its topmost entry, and the dialog
   that entry opens holding the channel combo (``Win32Actuator._open_parameters_dialog``), any of
   which fails the point by name;
4. what a binding a tree *does* publish is held to: its names follow :data:`MENU_ORDER`'s own
   left → right order, and the entry it binds to ``Parameters`` **is** the third button of the
   bar. A binding that contradicts the bar is refused like any other unproven anchor — the check
   runs in the safe direction (the bar is believed, the map is not).

The count in clause 2 is **not** the visible-control total that architecture invariant 4 forbids
as a gate: it is the bar's own painted entry count, which is exactly the evidence B03 rests on
(an omitted or added entry is what renames the later roles). It is still not a cleanliness or
resume fact — nothing in the identity carries it — and the clause names what it read, so a bar
the vocabulary does not cover is a refusal an operator can act on rather than a silent rename.

What confirms the anchor *after* the hover is the chain the gesture owns: the popup's signature
(:data:`PARAMETERS_POPUP_LEFT`/:data:`PARAMETERS_POPUP_MIN_H`), its entry order
(:func:`entry_buttons`), and the dialog that the topmost entry opens holding the channel combo
(``driver._channel_combo`` → :mod:`udv_echo_process.acquire.ui.dialog`). **No claim is made that
any of this behaves on the device** — ``docs/dop3000/device-verification.md`` (V3) is what settles
it, and it stays *device-pending*.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from udv_echo_process.acquire.ui.model import ScreenObservation, UiNode

__all__ = [
    "ANCHOR_ORDINAL",
    "ANCHOR_PREFIX",
    "MEASURED_BAR",
    "MEASURED_BAR_LENGTHS",
    "MENU_ORDER",
    "PARAMETERS_ENTRY",
    "PARAMETERS_MENU",
    "PARAMETERS_POPUP_LEFT",
    "PARAMETERS_POPUP_MIN_H",
    "anchor_button",
    "anchor_clause",
    "entry_buttons",
    "menubar_buttons",
    "observation_text",
]

#: The menu bar's buttons, left → right — the reference resolver's own vocabulary
#: (``recon/udop_roles.py``). Eleven names: ``UI-WINDOW-01`` shows that the bar the real
#: experiment paints carries ten of them (no ``UDV mode``), so this is a vocabulary and never a
#: claim about the bar on screen — which is why nothing binds a button to a name by position.
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

#: The bar ``UI-WINDOW-01`` paints, left → right, quoted from
#: ``docs/dop3000/ui-element-index.md``: ``File`` ``Preferences`` ``Parameters`` ``Compute``
#: ``Cursors`` ``Filters`` ``Tools`` ``Channels`` ``Display`` and then ``Help`` alone at the
#: band's right end — ten entries, and no entry reading ``UDV mode`` anywhere in the bar
#: (``UI-MENU-01``, the cut crop of the same band).
MEASURED_BAR: tuple[str, ...] = (
    "File",
    "Preferences",
    "Parameters",
    "Compute",
    "Cursors",
    "Filters",
    "Tools",
    "Channels",
    "Display",
    "Help",
)

#: The painted lengths this anchor was measured against — the instrument's own ten
#: (:data:`MEASURED_BAR`, ``UI-WINDOW-01``) and the resolver vocabulary's eleven
#: (:data:`MENU_ORDER`, which carries ``UDV mode``). A bar of any other length is refused: see the
#: module docstring's clause 2.
MEASURED_BAR_LENGTHS: tuple[int, ...] = (len(MEASURED_BAR), len(MENU_ORDER))

#: The menubar button, and the popup entry the channel lives behind — names used in messages only:
#: this application's widgets carry no captions, so nothing here matches a control against them.
PARAMETERS_MENU = "Parameters"
PARAMETERS_ENTRY = "Operating parameters"

#: The measurement channel's own menu entry: the anchor is the button at this **relative
#: location** in the bar (``File``, ``Preferences``, then ``Parameters``).
ANCHOR_ORDINAL = MENU_ORDER.index(PARAMETERS_MENU)
#: The entries that must sit to the anchor's left, in this order, for its location to be the
#: measured one.
ANCHOR_PREFIX: tuple[str, ...] = MENU_ORDER[:ANCHOR_ORDINAL]

#: The popup overlay's own geometry, as read live off the open menu: a caption-less ``TSp_Panel``
#: at ``(169, 55, 401, 250)`` — 195 px tall — with its entries at screen tops 61, 95, 130, 165 and
#: 205 (five of them, three of which the older read mistook for the whole menu). This rect is the
#: **fallback** identity only (the primary one is the panel that was not visible before the
#: hover), and it is the reference's own predicate, ``left == 169 and h > 120``
#: (``recon/41_burst_sampling_volume.py``).
PARAMETERS_POPUP_LEFT, PARAMETERS_POPUP_MIN_H = 169, 120


def _inside(panel: Mapping | None, k: Mapping) -> bool:
    """True when ``k``'s centre lies inside ``panel``'s rect."""
    if panel is None:
        return False
    cx, cy = k["left"] + k["w"] // 2, k["top"] + k["h"] // 2
    return (
        panel["left"] <= cx <= panel["left"] + panel["w"]
        and panel["top"] <= cy <= panel["top"] + panel["h"]
    )


def _left_of(node: UiNode) -> int:
    """A projected button's screen left, or ``0`` when the projection carries no rect for it."""
    return 0 if node.rect is None else node.rect.left


def menubar_buttons(observation: ScreenObservation) -> tuple[UiNode, ...]:
    """The bar's buttons, **left → right** — the evidence the anchor's signature is read from.

    The projection carries the bar two ways, and both are used: ``buttons`` is the bar itself
    (the resolver publishes every button of the band, named or not, so a variant whose painted set
    is not the measured one is still *visible* as evidence), while ``named`` is only the binding
    the resolver proved. A tree that publishes a binding and no bar — a fixture — is read as the
    bar it states, so the rule is the same for a captured tree and a synthesised one.
    """
    return tuple(sorted(observation.menu.buttons, key=_left_of))


def anchor_clause(observation: ScreenObservation) -> str | None:
    """Why the ``Parameters`` anchor cannot be proven on this tree; ``None`` when it can.

    Every branch names what was read, because the clause lands in a run record read by someone
    with no instrument in front of them and it is what an operator has to act on. A refusal here
    is what stops the one real-cursor gesture this driver has: the hover that opens the popup
    (``Win32Actuator._hover_centre``) is never reached, so nothing is moved on the operator's
    desktop and no menu is opened (ledger B03, architecture invariant 6).
    """
    band = observation.menu.band
    bar = menubar_buttons(observation)
    if not bar:
        return (
            "no 'Parameters' button in the menubar: the band hosts no button on this tree "
            f"({len(bar)} of the measured bar's {len(MEASURED_BAR)} entries were found), so which "
            "button means 'Parameters' is unstated and nothing is hovered"
        )
    if band is None:
        return (
            "no 'Parameters' button in the menubar: the band's buttons resolved with no menubar "
            "band panel behind them, so the bar they belong to is not the measured one (the "
            "anchor is read by its location inside that band) and nothing is hovered"
        )
    if len(bar) not in MEASURED_BAR_LENGTHS:
        return (
            "the menubar is not the bar this anchor was measured against: it paints "
            f"{len(bar)} button(s) where the measured bar paints {len(MEASURED_BAR)} "
            f"(UI-WINDOW-01) or {len(MENU_ORDER)} (the resolver's vocabulary, which also carries "
            "'UDV mode'). The entries carry no tree text, so a painted set of another length "
            "renames every later role — a variant that omits one entry shifts the rest — and the "
            "third button cannot be proven to be 'Parameters'. The 'Parameters' anchor is refused "
            "before any cursor movement, and the bar has to be read live before an acquisition is "
            "run against it (ledger B03, device verification V3)"
        )
    if len(bar) <= ANCHOR_ORDINAL:
        return (
            f"no 'Parameters' button in the menubar: the band paints {len(bar)} button(s), so "
            "there is no third entry where the measured bar keeps 'Parameters' and nothing is "
            "hovered (ledger B03)"
        )
    # The position half is the proof on a live tree; the name half is a claim only a tree that
    # states names at all makes — and the claim it can actually make is agreement with the bar it
    # was read from. ``_resolve`` publishes ``roles["menu"] = {}`` and fills it with the *anchor*
    # once this function has proven one, so reading a binding as a list of the anchor's
    # predecessors demanded names no tree states: that read its own output and refused the
    # instrument's own clean measurement screen (V0, 2026-09-18). What is checked instead is what
    # a name can be held to — the vocabulary's own left → right order, and the anchor being the
    # third entry of the bar (module docstring, clause 3).
    bound = sorted(observation.menu.named, key=lambda pair: _left_of(pair[1]))
    if bound:
        order = [name for name, _node in bound]
        known = [name for name in MENU_ORDER if name in set(order)]
        if order != known:
            return (
                "the menubar's bound entries do not follow the vocabulary's own order: the tree "
                f"bound {order} where the bar reads {list(MENU_ORDER)} from left to right, so the "
                "binding is not the measured bar's and the third button is not shown to be "
                "'Parameters' on this tree; nothing is hovered (ledger B03)"
            )
        anchor_node = observation.menu.node_for(PARAMETERS_MENU)
        if (
            anchor_node is not None
            and anchor_node.hwnd is not None
            and anchor_node.hwnd != bar[ANCHOR_ORDINAL].hwnd
        ):
            return (
                "the tree binds 'Parameters' to a button that is not the third entry of the bar: "
                f"it bound it to the entry at left {_left_of(anchor_node)} where the measured bar "
                "keeps it third ('File', 'Preferences', 'Parameters'), so the third button is not "
                "shown to be 'Parameters' and nothing is hovered (ledger B03)"
            )
    return None


def anchor_button(observation: ScreenObservation) -> UiNode | None:
    """The bar's ``Parameters`` button when the anchor is **proven**, and ``None`` when it is not.

    The one place the anchor is resolved: the third button of the bar, published only after
    :func:`anchor_clause` has found nothing to refuse on. A caller that gets ``None`` has no
    binding and must refuse by name rather than try a location — that is the whole difference
    between an anchor and an index (ledger B03).
    """
    if anchor_clause(observation) is not None:
        return None
    bar = menubar_buttons(observation)
    return bar[ANCHOR_ORDINAL] if len(bar) > ANCHOR_ORDINAL else None


def entry_buttons(overlay: dict, kids: Sequence[dict]) -> list[dict]:
    """The overlay's entries: every ``TSp_Button`` lying inside it, **screen order**.

    Geometry is the only identity available: this application's widgets carry no captions
    (``GetWindowText`` is empty on every ``TSp_*`` widget), so a title can never find an
    entry — that was the live bug. The entries are the buttons whose centre lies inside
    the overlay's rect, ordered by screen ``top`` and then ``left``, because enumeration
    order is *not* screen order: the reference pressed ``Default parameters`` the once it
    trusted it (``recon/41_burst_sampling_volume.py``, docs/16 §13a). The **first** in
    this order is ``Operating parameters``.
    """
    return sorted(
        (k for k in kids if k["cls"] == "TSp_Button" and _inside(overlay, k)),
        key=lambda k: (k["top"], k["left"]),
    )


def observation_text(observation: Mapping | None) -> str:
    """What one popup-entry press actually did, as one clause for a failure message.

    The observations recorded by :meth:`Win32Actuator._observe_entry_attempt` are reported
    verbatim — which gesture was used, whether the overlay was *visible*, whether the
    popup closed, any panel that appeared that was not up before and its top-level child
    classes — because "the entry opened no dialog" is not a diagnosis: the live run has to
    be read back from what the application *did*, and the next run has to be able to say
    what it saw.
    """
    if not observation:
        return "no popup entry press was attempted, so nothing was observed"
    fresh = observation["new_panels"]
    if fresh:
        appeared = "; ".join(
            f"a new panel at {p['rect']} with top-level children {list(p['classes'])}"
            for p in fresh
        )
    else:
        appeared = "no new panel or dialog appeared at all"
    dialog = observation["dialog"]
    if dialog is not None:
        appeared += f"; the dialog found holds {list(dialog['classes'])}"
    failed = " (the gesture itself failed)" if observation["gesture_failed"] else ""
    return (
        f"the {observation['gesture']} on the popup entry at "
        f"{observation['entry_rect'][:2]} (rect {observation['entry_rect']}){failed} "
        f"{'left open' if not observation['overlay_closed'] else 'closed'} the popup, "
        f"whose overlay was "
        f"{'visible' if observation['overlay_visible'] else 'NOT visible'}, and "
        f"{appeared}"
    )
