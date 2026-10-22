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

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from udv_echo_process.acquire.ui.model import Rect, ScreenObservation, UiNode

__all__ = [
    "ANCHOR_ORDINAL",
    "ANCHOR_PREFIX",
    "CHANNELS_MENU",
    "DISMISSAL_CLEARANCE_PX",
    "MAX_INTERVAL_S",
    "MAX_PATH_SECONDS",
    "MAX_STEPS",
    "MAX_STEP_PX",
    "MAX_STEP_WORK_S",
    "MEASURED_BAR",
    "MEASURED_BAR_LENGTHS",
    "MENU_ORDER",
    "MIN_INTERVAL_S",
    "PARAMETERS_ENTRY",
    "PARAMETERS_MENU",
    "PARAMETERS_POPUP_LEFT",
    "PARAMETERS_POPUP_MIN_H",
    "Obstacle",
    "PathPlan",
    "anchor_button",
    "anchor_clause",
    "channels_anchor",
    "channels_anchor_clause",
    "dismissal_clause",
    "dismissal_point",
    "entry_buttons",
    "menubar_buttons",
    "observation_text",
    "path_checked_bound_s",
    "step_interval_s",
    "stepped_path",
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


CHANNELS_MENU = "Channels"


def channels_anchor_clause(observation: ScreenObservation) -> str | None:
    """Why the measured ``Channels`` button cannot be proven on this tree; ``None`` when it can.

    The same rule as :func:`anchor_clause`, applied to a different entry and held to the
    **measured** bar alone (ten entries). ``MENU_ORDER``'s eleven names include ``UDV mode``,
    which ``UI-WINDOW-01`` shows this build does not paint: an eleventh painted button means
    the bar is not the one ``Channels`` was measured on, and taking the same ordinal would be
    the index fallback this refusal exists to avoid. Every clause names what it read, and a
    refusal happens before any cursor movement.
    """
    band = observation.menu.band
    bar = menubar_buttons(observation)
    if band is None:
        return (
            "the menubar band did not resolve, so the buttons' containing bar is unstated and "
            "the measured bar's order cannot be shown; nothing is hovered"
        )
    if not bar:
        return (
            "the menubar band hosts no button on this tree, so there is no measured bar to "
            f"read {CHANNELS_MENU!r} from; nothing is hovered"
        )
    if len(bar) != len(MEASURED_BAR):
        return (
            f"the menubar paints {len(bar)} button(s) where the measured bar (UI-WINDOW-01) "
            f"paints {len(MEASURED_BAR)}; a bar of another length renames every later entry (an "
            f"omitted or added entry shifts the rest), so {CHANNELS_MENU!r} at the measured "
            "position cannot be proven and nothing is hovered"
        )
    lefts = [_left_of(node) for node in bar]
    for node in bar:
        if node.rect is None or node.rect.width <= 0 or node.rect.height <= 0:
            return (
                "a menubar button states no measurable rect, so the anchor's own hover point "
                "does not exist on this projection and nothing is hovered"
            )
    if len(set(lefts)) != len(lefts) or any(left <= 0 for left in lefts):
        return (
            f"the menubar's buttons do not state distinct positive screen lefts ({lefts}), so "
            f"two of them are not separable and which one is {CHANNELS_MENU!r} is ambiguous; "
            "nothing is hovered"
        )
    bound = sorted(observation.menu.named, key=lambda pair: _left_of(pair[1]))
    if bound:
        names = [name for name, _node in bound]
        if len(set(names)) != len(names):
            return (
                f"the tree binds more than one menubar button to the same name ({names}), so "
                f"{CHANNELS_MENU!r} is ambiguous and nothing is hovered"
            )
        unknown = [name for name in names if name not in MEASURED_BAR]
        if unknown:
            return (
                f"the tree binds {unknown}, which the measured bar does not paint "
                f"({list(MEASURED_BAR)}); a caption this rule was not measured against is "
                "UNKNOWN, not another entry, and nothing is hovered"
            )
        known = [name for name in MEASURED_BAR if name in set(names)]
        if names != known:
            return (
                f"the menubar's bound entries {names} do not follow the measured bar's own "
                f"left -> right order {list(MEASURED_BAR)}, so the binding is not this bar and "
                f"{CHANNELS_MENU!r} cannot be located; nothing is hovered"
            )
        ordinal = MEASURED_BAR.index(CHANNELS_MENU)
        anchor_node = observation.menu.node_for(CHANNELS_MENU)
        if anchor_node is not None and anchor_node.hwnd != bar[ordinal].hwnd:
            return (
                f"the tree binds {CHANNELS_MENU!r} to a button that is not the measured bar's "
                f"{ordinal + 1}th entry, so the binding contradicts the bar and nothing is "
                "hovered"
            )
    return None


def channels_anchor(observation: ScreenObservation) -> UiNode | None:
    """The measured ``Channels`` button when proven, and ``None`` when it is not.

    The one place that binding is resolved. A caller that gets ``None`` must read
    :func:`channels_anchor_clause` and refuse by name rather than try an ordinal.
    """
    if channels_anchor_clause(observation) is not None:
        return None
    return menubar_buttons(observation)[MEASURED_BAR.index(CHANNELS_MENU)]


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


#: The clearance a dismissal move keeps from the popup it is leaving and from the menubar whose
#: hover owns it. It is a *gap*, never a position: the move is computed from the rectangles below.
DISMISSAL_CLEARANCE_PX = 12


def _bounds(client: Rect, screen: Rect) -> Rect | None:
    """The pixels a dismissal move may occupy: ``client`` ∩ ``screen``, or ``None`` if empty."""
    box = Rect(
        left=max(client.left, screen.left),
        top=max(client.top, screen.top),
        right=min(client.right, screen.right),
        bottom=min(client.bottom, screen.bottom),
    )
    return box if box.right > box.left and box.bottom > box.top else None


def _clamp(value: int, low: int, high: int) -> int:
    """``value`` brought into ``[low, high]`` — the bounds are already known to be non-empty."""
    return max(low, min(value, high))


def _clears(point: tuple[int, int], popup: Rect, band: Rect, bounds: Rect) -> bool:
    """True when ``point`` is inside ``bounds`` and clear of the popup **and** the menubar.

    Edge-inclusive, like the cursor-clip test: a point on the boundary is inside the bounds and
    touching the clearance box is *not* clear of it. The gap is applied on both sides, so the move
    is never a pixel that merely rounds outside the painted rectangle.
    """
    x, y = point
    if not (bounds.left <= x < bounds.right and bounds.top <= y < bounds.bottom):
        return False
    for rect in (popup, band):
        if (
            rect.left - DISMISSAL_CLEARANCE_PX
            <= x
            <= rect.right + DISMISSAL_CLEARANCE_PX
            and rect.top - DISMISSAL_CLEARANCE_PX
            <= y
            <= rect.bottom + DISMISSAL_CLEARANCE_PX
        ):
            return False
    return True


def _dismissal_candidates(popup: Rect, band: Rect, bounds: Rect):
    """Points derived from the popup's own rect, in preference order: below, right, left, above.

    Each is clamped into the client/screen intersection first, so a popup flush against an edge
    still yields a reachable point instead of an off-screen one. The candidate is then held to
    :func:`_clears`; nothing here is a literal position. A recorded literal goes stale with the
    window, so the point is recomputed from this observation every time.
    """
    cx, cy = popup.centre
    yield (
        _clamp(cx, bounds.left, bounds.right - 1),
        _clamp(
            popup.bottom + DISMISSAL_CLEARANCE_PX + 1, bounds.top, bounds.bottom - 1
        ),
    )
    yield (
        _clamp(popup.right + DISMISSAL_CLEARANCE_PX + 1, bounds.left, bounds.right - 1),
        _clamp(cy, bounds.top, bounds.bottom - 1),
    )
    yield (
        _clamp(popup.left - DISMISSAL_CLEARANCE_PX - 1, bounds.left, bounds.right - 1),
        _clamp(cy, bounds.top, bounds.bottom - 1),
    )
    yield (
        _clamp(cx, bounds.left, bounds.right - 1),
        _clamp(popup.top - DISMISSAL_CLEARANCE_PX - 1, bounds.top, bounds.bottom - 1),
    )


def dismissal_point(
    *,
    popup: Rect,
    band: Rect,
    client: Rect,
    screen: Rect,
) -> tuple[int, int] | None:
    """A real-cursor point that dismisses the open popup, or ``None`` when none fits.

    **What is measured, and what is only hypothesised.** Two audits of the archive's behavioural
    probe (``recon/35_capture_probe.py``) agree that it establishes the *opening* gesture — a
    hover on the menubar button, ``SetCursorPos`` then one relative move — and that a popup **entry
    press consumes the popup** while performing that entry's action. It contains **no generic
    close**, so it does not verify that moving the cursor off an arbitrary popup dismisses it. A
    single move off the popup was then tried live (``channels-hover-lifecycle-live-01``): the point
    was read back exactly and the popup stayed up, while the operator's own physical move closed
    it. So the point below is *where a dismissal is aimed*, derived from the live rectangles. One
    live prototype (``channels-stepped-path-live-01``) then walked :func:`stepped_path` to this point
    (13 positions of <= 40 px) and observed ``ABSENT`` on both of its paths. That supports the
    path-versus-jump difference for one geometry; it does not establish the OS mechanism, and only
    an observed ``ABSENT`` read — never this point or a landed path — closes a popup.

    The aiming rule itself is structural and does not depend on the hypothesis: the point is
    **outside the popup and outside the menubar** (a point still on the bar keeps the hover) while
    staying **inside the application's client area and the screen** (a point outside either is
    clamped or refused, and looks like a move that did not take). A caller that reports this point
    as a dismissal must still observe ``ABSENT``; the point alone proves nothing.

    Nothing here is a constant position: the point is derived from the rectangles the live
    observation states. A popup that leaves no such pixel — it covers the client, or the bands do —
    is refused by :func:`dismissal_clause` rather than approximated.
    """
    bounds = _bounds(client, screen)
    if bounds is None:
        return None
    return next(
        (
            point
            for point in _dismissal_candidates(popup, band, bounds)
            if _clears(point, popup, band, bounds)
        ),
        None,
    )


def dismissal_clause(
    *,
    popup: Rect,
    band: Rect,
    client: Rect,
    screen: Rect,
) -> str | None:
    """Why no dismissal point exists on this geometry; ``None`` when one does.

    The clause names every rectangle it read, because it is what a live session has to act on:
    "nothing was moved" is not a diagnosis, while "the popup's clearance box and the menubar leave
    no pixel inside the client and screen" is.
    """
    if (
        dismissal_point(popup=popup, band=band, client=client, screen=screen)
        is not None
    ):
        return None
    bounds = _bounds(client, screen)
    if bounds is None:
        return (
            "no point to move the cursor to for dismissing the popup: the client rectangle "
            f"{client.as_tuple()} and the screen rectangle {screen.as_tuple()} do not overlap, "
            "so there is nowhere inside the application that a real-cursor move could land; "
            "nothing is moved"
        )
    return (
        "no point to move the cursor to for dismissing the popup: the popup "
        f"{popup.as_tuple()} and the menubar band {band.as_tuple()} leave no pixel inside the "
        f"client ∩ screen bounds {bounds.as_tuple()} that is at least "
        f"{DISMISSAL_CLEARANCE_PX} px clear of both, so the one gesture measured to dismiss this "
        "popup (a real-cursor move off it) cannot be aimed anywhere; nothing is moved and the "
        "operator has to close it"
    )


# ------------------------------------------------------------------ the bounded stepped path

#: One ``SetCursorPos`` step never travels further than this. It is the resolution of the
#: gesture: the live prototype (``channels-stepped-path-live-01``) walked 13 positions of
#: <= 40 px and the popup was observed ``ABSENT`` at the end of each path, where one warp to
#: the same point had not closed it. A bigger step is closer to that warp.
MAX_STEP_PX = 40

#: Hard position count for one path — a resource bound, derived from the 2 s budget below and a
#: 20 ms floor interval; a geometry that needs more is refused rather than walked.
MAX_STEPS = 100

#: The planned **interval budget** for one path: the intervals between consecutive positions, derived
#: by :func:`step_interval_s`. It is deliberately *not* a wall-clock deadline — each step's
#: ``SetCursorPos``, read-back and guard are not preemptible, so the walker checks the elapsed time
#: against :func:`path_checked_bound_s` before every move rather than pretending to preempt the OS.
MAX_PATH_SECONDS = 2.0

#: A bounded per-position allowance for the work a step does besides its interval (one
#: ``SetCursorPos``, one read-back, one foreground check). It is what keeps the walker's checked
#: bound an honest one: the bound is the interval budget plus this allowance per position.
MAX_STEP_WORK_S = 0.05


#: Interval between consecutive positions. The upper bound keeps the path visibly continuous;
#: the lower bound keeps a 100-position path inside the budget.
MAX_INTERVAL_S = 0.15
MIN_INTERVAL_S = 0.02


@dataclass(frozen=True)
class Obstacle:
    """One rectangle a path point must not land inside — a *different* menubar entry."""

    name: str
    rect: Rect


@dataclass(frozen=True)
class PathPlan:
    """A derived stepped path, or the reason one cannot be derived.

    ``points`` are the screen positions **after** ``start``, in order, ending exactly at ``goal``.
    ``interval_s`` is the pause between them; ``total_s`` is the **planned interval budget**
    (``len(points) * interval_s``), not an elapsed-time promise — the walker's checked bound adds
    one :data:`MAX_STEP_WORK_S` per position and records what was actually elapsed. A plan with
    ``refusal`` set was never walked.
    """

    start: tuple[int, int]
    goal: tuple[int, int]
    points: tuple[tuple[int, int], ...]
    interval_s: float
    distance_px: float
    step_px: int
    refusal: str | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None and bool(self.points)

    @property
    def total_s(self) -> float:
        return round(len(self.points) * self.interval_s, 4)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "start": list(self.start),
            "goal": list(self.goal),
            "points": [list(point) for point in self.points],
            "steps": len(self.points),
            "distance_px": round(self.distance_px, 2),
            "step_px": self.step_px,
            "interval_s": round(self.interval_s, 4),
            "total_s": self.total_s,
            "refusal": self.refusal,
        }


def step_interval_s(steps: int, *, max_seconds: float = MAX_PATH_SECONDS) -> float:
    """The interval derived for ``steps`` positions inside ``max_seconds`` — or ``0.0`` if impossible.

    The budget is shared equally: each position gets ``max_seconds / steps`` and that whole share
    is the interval, capped at :data:`MAX_INTERVAL_S`. ``0.0`` means the share is below
    :data:`MIN_INTERVAL_S`, i.e. this many steps cannot be walked inside the bound at a rate that
    is still a path rather than a warp — the caller refuses instead of enlarging the step.
    """
    if steps <= 0:
        return 0.0
    share = max_seconds / steps
    interval = min(MAX_INTERVAL_S, share)
    return interval if interval >= MIN_INTERVAL_S else 0.0


def path_checked_bound_s(steps: int, *, max_seconds: float = MAX_PATH_SECONDS) -> float:
    """The walker's checked bound for ``steps`` positions: the interval budget plus per-step work.

    This is the value :func:`…win32.cursor._move_real_cursor_stepped` compares elapsed time
    against **before each move**. It is a checked bound, not a hard deadline: a blocking OS call
    already in progress cannot be interrupted, so the walker can only refuse to start the next
    step once the bound is exceeded — and it records the actual elapsed time beside the planned
    interval budget.
    """
    return round(max(0, steps) * MAX_STEP_WORK_S + max_seconds, 4)


def stepped_path(
    *,
    start: tuple[int, int],
    goal: tuple[int, int],
    bounds: Rect,
    obstacles: Sequence[Obstacle] = (),
    step_px: int = MAX_STEP_PX,
    max_seconds: float = MAX_PATH_SECONDS,
) -> PathPlan:
    """The bounded stepped path from ``start`` to ``goal``, or a refusal naming why not.

    Pure: no window, no cursor, no clock. The rules, in order:

    - ``step_px`` must be a positive integer no larger than :data:`MAX_STEP_PX`;
    - ``bounds`` must be non-empty and must contain both ends;
    - the number of positions is ``ceil(distance / step_px)``, at least one, at most
      :data:`MAX_STEPS`; each is the linear interpolation and the last is ``goal`` exactly;
    - an intermediate position inside an :class:`Obstacle` is refused; index 0 is the **start**,
      where the pointer already is;
    - the interval is :func:`step_interval_s`; ``0.0`` means the path cannot fit the budget.

    Clearance of the goal from the popup and the menubar is not re-derived here: the caller
    passes :func:`dismissal_point`'s own answer, which is the owning rule for it.
    """
    if not isinstance(step_px, int) or step_px <= 0 or step_px > MAX_STEP_PX:
        return PathPlan(
            start=start,
            goal=goal,
            points=(),
            interval_s=0.0,
            distance_px=0.0,
            step_px=step_px,
            refusal=(
                f"the requested step of {step_px!r} px is not an integer in 1..{MAX_STEP_PX}: this "
                f"path exists to walk *consecutive small* positions, so a step larger than "
                f"{MAX_STEP_PX} px is refused rather than walked"
            ),
        )
    if bounds.right <= bounds.left or bounds.bottom <= bounds.top:
        return PathPlan(
            start=start,
            goal=goal,
            points=(),
            interval_s=0.0,
            distance_px=0.0,
            step_px=step_px,
            refusal=(
                f"the walkable bounds {bounds.as_tuple()} are empty, so no position on a path "
                "could be shown to lie on the application's screen and client area; nothing is "
                "moved"
            ),
        )
    for label, point in (("start", start), ("goal", goal)):
        if not bounds.contains_point(point):
            return PathPlan(
                start=start,
                goal=goal,
                points=(),
                interval_s=0.0,
                distance_px=0.0,
                step_px=step_px,
                refusal=(
                    f"the path's {label} {point} lies outside the walkable bounds "
                    f"{bounds.as_tuple()} (client ∩ screen), so the OS would clamp a step there "
                    "and the result would be read as a dismissal that did not work; nothing is "
                    "moved"
                ),
            )

    dx, dy = goal[0] - start[0], goal[1] - start[1]
    distance = math.hypot(dx, dy)
    steps = max(1, math.ceil(distance / step_px))
    if steps > MAX_STEPS:
        return PathPlan(
            start=start,
            goal=goal,
            points=(),
            interval_s=0.0,
            distance_px=distance,
            step_px=step_px,
            refusal=(
                f"the path from {start} to {goal} is {distance:.1f} px and needs {steps} "
                f"positions at <= {step_px} px, beyond the {MAX_STEPS}-position bound; a bigger "
                "step would stop being the gesture under test, so nothing is moved"
            ),
        )
    interval = step_interval_s(steps, max_seconds=max_seconds)
    if interval == 0.0:
        return PathPlan(
            start=start,
            goal=goal,
            points=(),
            interval_s=0.0,
            distance_px=distance,
            step_px=step_px,
            refusal=(
                f"{steps} positions cannot be spaced inside the {max_seconds:.1f} s path bound at "
                f">= {MIN_INTERVAL_S:.2f} s apart (a share of "
                f"{max_seconds / steps:.4f} s each); a faster path is a warp again, so nothing is "
                "moved"
            ),
        )

    points: list[tuple[int, int]] = []
    for index in range(1, steps + 1):
        if index == steps:
            points.append((int(goal[0]), int(goal[1])))
            continue
        points.append(
            (
                round(start[0] + dx * index / steps),
                round(start[1] + dy * index / steps),
            )
        )

    for index, point in enumerate(points, start=1):
        for obstacle in obstacles:
            if obstacle.rect.contains_point(point):
                return PathPlan(
                    start=start,
                    goal=goal,
                    points=(),
                    interval_s=interval,
                    distance_px=distance,
                    step_px=step_px,
                    refusal=(
                        f"position {index} of {steps} on the path from {start} to {goal} is "
                        f"{point}, inside the menubar entry {obstacle.name!r} at "
                        f"{obstacle.rect.as_tuple()}: stepping through another entry can open "
                        "that entry's menu, so this path is refused before anything is moved"
                    ),
                )

    return PathPlan(
        start=start,
        goal=goal,
        points=tuple(points),
        interval_s=interval,
        distance_px=distance,
        step_px=step_px,
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
