"""The ``Parameters`` anchor: the only menubar binding this driver has, and what proves it.

Layer 2 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5), moved out of
:mod:`udv_echo_process.acquire.driver` by Patch 2's widget slice. Nothing here touches ``user32``,
moves a cursor, sends a message or reads a live window: every function answers from an
already-resolved tree.

**What this module is the authority for**

- the menubar's **measured bar** and the vocabulary that names it (:data:`MENU_ORDER`,
  :data:`MEASURED_BAR`) — the eleven names the reference resolver carried and the ten entries
  ``UI-WINDOW-01`` paints, left → right;
- the menubar's own vocabulary and popup signature the resolver's menubar step is written
  against (the ``Parameters`` *name* and the popup's geometry);
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

**The menubar's binding is the resolver's, unchanged, and it is pinned by ledger B03.** An
index map is not an identity — the application's variants do not paint the same bar and the
entries carry no tree text, so one absent entry silently renames every later role — and
``tests/test_acquire_ui_counterexamples.py`` carries that as a strict xfail until the anchor's
structural signature lands. What this module owns today is the bar's vocabulary
(:data:`MENU_ORDER`), the popup's own geometry and the entry order the gesture reads it with; the
anchor rule and the refusal it needs are **target** (ledger B03,
``docs/dop3000/device-verification.md`` V3), and no claim is made that any of it behaves on the
device.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from udv_echo_process.acquire.ui.model import ScreenObservation, UiNode

__all__ = [
    "MENU_ORDER",
    "PARAMETERS_ENTRY",
    "PARAMETERS_MENU",
    "PARAMETERS_POPUP_LEFT",
    "PARAMETERS_POPUP_MIN_H",
    "entry_buttons",
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

#: The menubar button, and the popup entry the channel lives behind — names used in messages only:
#: this application's widgets carry no captions, so nothing here matches a control against them.
PARAMETERS_MENU = "Parameters"
PARAMETERS_ENTRY = "Operating parameters"

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
