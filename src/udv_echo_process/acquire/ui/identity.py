"""One identity per panel, decided **once** — from the panel's own shape and the screen's context.

Layer 2 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5), and the module
``docs/dop3000/identity-classification-plan.md`` §2 calls for: a panel is classified **before** any
consumer excludes it or votes on it, and every consumer of the resolve then reads that answer
instead of re-deriving panel meaning from a predicate another consumer's decision feeds.

**The circle this module closes.** Before it, ``ui/dialog.py``'s dialog predicate decided which
panel was a dialog, ``_resolve``'s strip vote decided which was the strip *by excluding the
dialogs*, and the generic popup flag was "any panel that hosts a button and is neither" — so a
panel's meaning depended on the other panels' verdicts. Measured on the instrument 2026-09-19
(``docs/dop3000/device-verification.md``, *the four-button strip, block-held* and *sitting C*):
the recording strip's own panel was admitted by the dialog predicate at 453, 502 and 551 px
(each of those panels directly owns exactly one ``TComboBox`` — the ``Show block`` combo — and
``ui.dialog._DIALOG_INPUT_CLASSES`` accepts that for any panel wider than 400 px), the reused
392x132 destructive guard was never admitted at all, the cursor info box won the strip vote when
the strip was excluded from it, and the surface read ``dialog`` for every one of those states.

**The identity is a claim about the panel, and nothing else.** Each item below is warranted by the
panel's own children and the screen's context, in this order (the plan's §2.1, narrowest first):

1. ``MENU_POPUP`` — the ``Parameters`` popup: its demonstrated predicate and its own entries
   (:data:`…ui.menu.PARAMETERS_POPUP_LEFT` / :data:`…ui.menu.PARAMETERS_POPUP_MIN_H`, asked
   through :func:`…ui.menu.entry_buttons`, exactly as :func:`…udop.parameters.parameters_overlay`
   asks it). An unknown button-hosting panel is **not** a popup.
2. ``APPLICATION_DIALOG`` — the browse/store class: a panel owning a ``TSp_Browse`` **and** an
   edit of its own, before the warning family is considered, so a store dialog never loses its
   commit path to a warning rule.
3. ``WARNING`` — the measured family: a compact panel wider than 250 px and taller than 90 px
   whose own bottom band holds a **two-button** pair (measured 392x132, 397x135 and 353x155; the
   store overwrite warning's geometry is not measured, so the family rule — never one rect —
   carries it). "Two" matters: the 453x40 strip's own band resolves six buttons and the grown
   strips' bands resolve none, while the ``Define TGC`` overlay's resolves three.
4. ``MEASUREMENT_STRIP`` — :func:`…ui.strip.strip_row`'s exact geometry (button centres inside the
   panel, button ``top < panel.top + 30``, left to right) **and** that row's centre inside the
   plot's 0.30-0.70 band — the context :meth:`…driver.Win32Actuator._resolve`'s own strip vote
   scores in. It rejects the info box (its owned button's centre lies outside the panel), the
   warnings (two bottom buttons, whose row is nowhere near the panel's top) and ``Define TGC``
   (its measured buttons begin 46-89 px below the panel's top). A direct ``TSp_Sliding_Bar``
   strengthens the identity but is not required — the 453x40 row has none and *is* the strip.
5. ``CURSOR_INFO`` — the incidental painted box: a panel too narrow to be one of this
   application's dialogs, stating no caption, holding no actionable control of its own inside its
   own rect, and containing a caption-less child panel (measured: ``TSp_Panel [908,466,1057,525]``
   holding ``TSp_Panel [916,475,1045,514]`` and owning ``TSp_Button 131918 [917,578,997,598]``,
   whose centre lies **outside** the box). Its painted depth/velocity remain out of scope.
6. ``REPLACEMENT`` — a replacement surface's own widget band: no menubar band and no plot
   resolved anywhere on the screen, while the panel hosts buttons of its own (``Compare
   profiles`` / ``Measure US field``, ``_replacement_evidence``'s own evidence).
7. ``OVERLAY`` — a non-measurement overlay: a panel **over the monitor** (its centre inside the
   plot's *vertical* span — the read that carries ``Define TGC`` splits the display into two plots
   at the same span, so the monitor is the band and the two plots are corroborating evidence) that
   hosts its own ``TSp_Button`` row, is not one of the identities above, and is not full of
   controls (:data:`…ui.dialog._DIALOG_MIN_CHILDREN`, the value-table dialogs' own shape, which is
   what keeps the measured ``Operating parameters`` dialog out of this item). This is ``Define
   TGC``: measured ``TSp_Panel [400,168,850,288]`` = 450x120, six children, two of them
   ``TSp_Value_Button``, four ``TSp_Button`` whose tops begin 46-89 px below the panel's top.
   Unlike the retired ``_overlay_candidates`` this does not require the strip to have resolved —
   in that very read the real strip panel is **absent** from the visible panel set.
8. ``APPLICATION_DIALOG`` — the fallback: :func:`…ui.dialog._is_dialog_panel` unchanged, for the
   measured ``Operating parameters`` dialog (627x384, 21 direct children) and the application's
   other dialogs. Width alone remains insufficient.
9. ``OTHER`` — unknown, and therefore non-actionable: a panel nothing above claims is refused
   rather than guessed at.

**Identity and binding stay separate.** The classification says *what a panel is*; it never says
a press may be taken out of it. The measured 453x40, four-button, no-visible-slider row is
``MEASUREMENT_STRIP`` and stays :attr:`~udv_echo_process.acquire.actuator.StripView.AMBIGUOUS`,
unbound, exactly as :func:`…ui.strip.press_refusal` refuses it (ledger B10).

**The interface, and who reads it.** The module is exported the way the package exports its other
``ui`` pieces (``ui/__init__.py``'s table, re-published by ``driver.py`` for the callers written
against the flat module):

- :func:`panel_identity` ``(panel, kids, *, context=None) -> PanelIdentity`` — one panel, its own
  children and the screen's context, in the order above;
- :func:`classify_panels` ``(panels, kids_of, *, context=None) -> dict[int, PanelIdentity]`` — one
  identity per panel considered, keyed by handle, which is what
  ``Win32Actuator._resolve`` publishes as ``roles["identities"]``;
- :func:`blocking_surface` ``(identities) -> PanelIdentity | None`` — the surface a press must not
  be posted behind (``WARNING`` / ``OVERLAY`` / ``APPLICATION_DIALOG`` / ``MENU_POPUP``), which
  ``_resolve`` publishes as ``roles["blocking_surface"]``;
- :class:`ScreenContext` ``(plot, menubar)`` — the screen's own two facts, and nothing else;
- :func:`context_of` / :func:`with_identities` — the projection's half: an observation's context,
  and the same classification applied to a captured tree that states no inventory (so a fixture
  and a live read answer by one rule).

Nothing here enumerates a window, moves a cursor or presses anything. The entry points answer
from already-resolved rows (:meth:`…driver.Win32Actuator._resolve` publishes its result as
``roles["identities"]``) or from a normalized projection
(:func:`with_identities`, which classifies a captured fixture by the same rules), so a live read and
a committed tree answer alike. **No claim is made that any of this behaves on the device** —
``docs/dop3000/device-verification.md`` settles that, and it stays *device-pending*.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import Enum

from udv_echo_process.acquire.ui.dialog import (
    _DIALOG_INPUT_CLASSES,
    _DIALOG_MIN_CHILDREN,
    _DIALOG_MIN_W,
    _is_dialog_panel,
    bottom_row,
)
from udv_echo_process.acquire.ui.menu import (
    PARAMETERS_POPUP_LEFT,
    PARAMETERS_POPUP_MIN_H,
    entry_buttons,
)
from udv_echo_process.acquire.ui.model import Rect, ScreenObservation
from udv_echo_process.acquire.ui.strip import strip_row
from udv_echo_process.models.base import ValueModel

__all__ = [
    "BLOCKING",
    "PanelIdentity",
    "ScreenContext",
    "blocking_surface",
    "classify_panels",
    "context_of",
    "panel_identity",
    "with_identities",
]


class PanelIdentity(str, Enum):
    """What one panel of the window **is** — decided from its own tree shape and the screen.

    The members are the identities current behaviour needs (plan §2), and each one is warranted
    by its own evidence (see the module docstring): ``MEASUREMENT_STRIP``, ``MENU_POPUP``,
    ``APPLICATION_DIALOG``, ``WARNING``, ``REPLACEMENT``, ``OVERLAY``, ``CURSOR_INFO`` and
    ``OTHER``. They are *identities*, not permissions: no member states that a press may be bound
    to the panel, and ``ui/strip.py``'s own refusal still stands between the ambiguous four-button
    row and any press.
    """

    MEASUREMENT_STRIP = "measurement_strip"
    MENU_POPUP = "menu_popup"
    APPLICATION_DIALOG = "application_dialog"
    WARNING = "warning"
    REPLACEMENT = "replacement"
    OVERLAY = "overlay"
    CURSOR_INFO = "cursor_info"
    OTHER = "other"


#: The identities that are a **blocking surface** — a panel over the measurement screen that a
#: press must not be posted behind, and that a caller has to clear from the UI — in the order
#: :func:`blocking_surface` names them: the narrowest claim first, so the surface reported is the
#: most specific one on the screen. A replacement screen is deliberately **not** here: it is not a
#: panel *over* a measurement screen, it is the surface that replaced it, and
#: :class:`~udv_echo_process.acquire.ui.model.SurfaceKind` is what reports it.
BLOCKING: tuple[PanelIdentity, ...] = (
    PanelIdentity.MENU_POPUP,
    PanelIdentity.APPLICATION_DIALOG,
    PanelIdentity.WARNING,
    PanelIdentity.OVERLAY,
)

#: How many buttons the measured warning family's own bottom band holds (measured: the reused
#: destructive guard, ``TSp_Panel 4393476`` 392x132, exactly two — ``3738758`` at
#: ``[1000,587,1069,612]`` and ``2886516`` at ``[1079,587,1154,612]``, device-verification.md
#: *the removal guard*). The other measured members are 397x135 and 353x155.
_WARNING_BUTTONS = 2

#: The warning family's own floor: a **compact** panel. The same rule ``_find_overlay`` uses (the
#: reference's ``w > 250 and h > 90``), kept as the family rule rather than as a rect.
_WARNING_MIN_W, _WARNING_MIN_H = 250, 90

#: The plot's middle band, as a fraction of the plot's height — the band the resolver's own strip
#: vote scores a candidate in (``0.30 <= frac <= 0.70``). Asked here of the panel's own row, so
#: the classifier and the vote cannot disagree about where a strip's row may sit.
_STRIP_BAND = (0.30, 0.70)

#: The classes that make a control *actionable* — what the cursor info box must not hold inside
#: its own rect for its identity to hold ("no in-panel actionable row": the measured box owns a
#: button, and that button's centre is outside the box).
_ACTIONABLE_CLASSES = (*_DIALOG_INPUT_CLASSES, "TSp_Button", "TSp_Value_Button")

#: The child that makes the info box the box it is: a nested TSp_Panel the application paints
#: inside it (measured ``TSp_Panel 131920`` inside ``TSp_Panel 131916``), both caption-less.
_INFO_BOX_CHILD_CLASS = "TSp_Panel"


class ScreenContext(ValueModel):
    """What the classifier is told about the screen a panel sits on — and nothing more.

    Two facts, both of them already resolved by whoever holds the tree:

    ``plot``
        the monitor's own rect (``roles["plot"]`` / ``observation.plot``), which is what
        "over the monitor" and "inside the plot's middle band" are asked of;
    ``menubar``
        the handle of the panel the menubar's bar resolved in, or ``None`` when no band resolved
        — the replacement evidence (:func:`…ui.layout._replacement_evidence`) stated as context.

    Both are **context**, never identity: nothing below decides what a panel is from its index in
    a panel list, from a screen coordinate or from a handle.
    """

    plot: Rect | None = None
    menubar: int | None = None


def context_of(observation: ScreenObservation) -> ScreenContext:
    """The screen context of a normalized observation — the classifier's other input.

    One line, and written here rather than in :mod:`…ui.model` so the model keeps carrying only
    facts about the tree: the bar's own panel and the monitor's rect are what a *classification*
    needs, not what an observation is.
    """
    band = observation.menu.band
    return ScreenContext(
        plot=observation.plot.rect if observation.plot is not None else None,
        menubar=band.hwnd if band is not None else None,
    )


# ------------------------------------------------------------------- the row reconciliation


def _bounds(control: object) -> tuple[int, int, int, int] | None:
    """One control's rect in screen coordinates, from **either** projection this package carries.

    The resolver's rows state ``left``/``top``/``w``/``h`` (``_visible_children``'s own shape) and
    the normalized projection states a :class:`~udv_echo_process.acquire.ui.model.Rect`. This is
    the one place the two are reconciled, so every warrant below is written once and asked of a
    live tree and of a committed fixture alike. ``None`` when the row states no geometry at all —
    a panel nobody measured is a panel nothing can be claimed about.
    """
    if isinstance(control, Mapping):
        rect = control.get("rect")
        if rect is not None:
            try:
                left, top, right, bottom = (int(value) for value in rect)
            except (TypeError, ValueError):
                return None
            return (left, top, right, bottom)
        left, top = control.get("left"), control.get("top")
        width, height = control.get("w"), control.get("h")
        if None in (left, top, width, height):
            return None
        try:
            return (int(left), int(top), int(left) + int(width), int(top) + int(height))
        except (TypeError, ValueError):
            return None
    rect = getattr(control, "rect", None)  # a UiNode
    return None if rect is None else rect.as_tuple()


def _cls(control: object) -> str:
    """One control's window class — the only identity this application's widgets carry."""
    if isinstance(control, Mapping):
        return str(control.get("cls", ""))
    return str(getattr(control, "cls", ""))


def _text(control: object) -> str:
    """What one control states — evidence, never an identity (every ``TSp_*`` widget is empty)."""
    if isinstance(control, Mapping):
        return str(control.get("text", ""))
    return str(getattr(control, "text", ""))


def _hwnd(control: object) -> int | None:
    """One control's handle as an action reference, or ``None`` when the projection states none."""
    if isinstance(control, Mapping):
        value = control.get("hwnd")
    else:
        value = getattr(control, "hwnd", None)
    return value if isinstance(value, int) else None


def _row(control: object) -> dict | None:
    """One control as the row shape the ``ui`` package's geometry rules read.

    ``None`` when it states no rect: every warrant below is geometry, and a rectless row would
    otherwise be read as a zero-sized control at the screen's origin.
    """
    bounds = _bounds(control)
    if bounds is None:
        return None
    left, top, right, bottom = bounds
    return {
        "cls": _cls(control),
        "left": left,
        "top": top,
        "w": right - left,
        "h": bottom - top,
        "text": _text(control),
    }


def _rows(controls: Sequence[object]) -> list[dict]:
    """The rows of a panel's children, rect-less ones dropped — the panel hosts what is measured."""
    return [row for row in (_row(control) for control in controls) if row is not None]


def _centre_inside(panel: Mapping, control: Mapping) -> bool:
    """True when ``control``'s centre lies inside ``panel``'s own rect — ``ui.menu._inside``'s rule.

    The *centre*, not the whole rect, and never ``ui.dialog._contains``: this application lays a
    strip's own row out so that some of its buttons and the ``Show block`` combo extend below the
    panel's rect (measured, 2026-09-19), so a containment test would call the panel's own children
    foreign while an out-of-panel button — the cursor info box's — would still be its own.
    """
    cx = control["left"] + control["w"] // 2
    cy = control["top"] + control["h"] // 2
    return (
        panel["left"] <= cx <= panel["left"] + panel["w"]
        and panel["top"] <= cy <= panel["top"] + panel["h"]
    )


def _over_monitor(plot: Rect, row: Mapping) -> bool:
    """True when ``row``'s centre lies **over the monitor** — inside the plot's vertical span.

    The monitor is the vertical band the plots paint in, and the clause is asked of one plot's
    ``top``/``bottom`` on purpose: the ``Define TGC`` read carries **two** plots
    (``[200,65,1045,1006]`` and ``[1065,65,1910,1006]``, the overlay splitting the display), at the
    same vertical span — so a rule that demanded containment in one plot's rect would call the
    overlay's own panel "not over the monitor" depending on which plot the resolver happened to
    hand over. The two plots are corroborating evidence; the band is the discriminator. What this
    excludes is exactly the measurement skeleton's own bands, which sit above the plot's top (the
    menubar, measured ``(0,23,1920,55)``) or below its bottom (the status bar, ``(0,1016,1920,1050)``).
    """
    centre_y = row["top"] + row["h"] // 2
    return plot.top <= centre_y <= plot.bottom


# ------------------------------------------------------------------------- the nine warrants


def _is_menu_popup(panel: Mapping, kids: Sequence[Mapping]) -> bool:
    """The ``Parameters`` popup: the demonstrated signature, **and** entries of its own inside it.

    ``recon/41_burst_sampling_volume.py`` read the live popup at ``left == 169`` with ``h > 120``,
    and both facts are :mod:`…ui.menu`'s already-measured constants — reused here rather than
    restated, so this identity and the hover's own poll cannot disagree about which menu is up.
    The entries are :func:`…ui.menu.entry_buttons`' question, which is why a panel that merely
    hosts some button somewhere is not a popup (it was, before this module: measured
    ``open_popup`` ``True`` for the ``Define TGC`` overlay, for every warning box and for the
    cursor info box).
    """
    if panel["left"] != PARAMETERS_POPUP_LEFT or panel["h"] <= PARAMETERS_POPUP_MIN_H:
        return False
    return bool(entry_buttons(panel, kids))


def _is_browse_dialog(panel: Mapping, kids: Sequence[Mapping]) -> bool:
    """The store/browse dialog: an edit **and** a ``TSp_Browse`` of its own — discriminator first.

    Asked before the warning family so a store dialog can never be read as a warning, whatever
    geometry the application reuses for its warning boxes: this is the class that carries the name
    field and the commit path (docs/16 §12b), and the failure that misreads it costs the block.
    """
    return any(kid["cls"] == "TSp_Browse" for kid in kids) and any(
        kid["cls"] in ("TEdit", "TSp_Edit") for kid in kids
    )


def _is_warning(panel: Mapping, kids: Sequence[Mapping]) -> bool:
    """The measured warning family: compact, and with a **two-button** bottom band of its own.

    The family rule rather than one rect, because the store overwrite warning's geometry is not
    measured while the destructive guard the removal raises is (392x132; 397x135 and 353x155 are
    the other measured members). ``bottom_row`` is :mod:`…ui.dialog`'s own band — the panel's last
    70 px — and asking for exactly two buttons there is what keeps this rule off the strip's own
    panel: the 453x40 row resolves six entries in that band, the grown 502/551 rows resolve none,
    and ``Define TGC``'s panel resolves three.

    **A value table of its own disqualifies it.** Every measured guard carries its two buttons and
    nothing else, while the values dialog class (``Operating parameters``, ``Record settings``) is
    exactly the class that holds ``TSp_Value_Button``s *directly* — the same discriminator
    :meth:`…driver.Win32Actuator._resolve` splits the dialogs by. Without this clause a compact
    command dialog whose bottom band happens to hold two buttons would be claimed as a warning and
    would then leave the dialog union entirely, so the panel a caller asked to read would answer as
    a destructive guard instead. Found by the change's own adversarial review; no measured warning
    carries a value button, so the clause is bounded by the evidence rather than by a guess.
    """
    if any(kid["cls"] == "TSp_Value_Button" for kid in kids):
        return False
    return (
        len(bottom_row(panel, kids)) == _WARNING_BUTTONS
        and panel["w"] > _WARNING_MIN_W
        and panel["h"] > _WARNING_MIN_H
    )


def _is_measurement_strip(
    panel: Mapping, kids: Sequence[Mapping], plot: Rect | None
) -> bool:
    """The recording strip: its own top row, in the plot's middle band — identity, not a vote.

    :func:`…ui.strip.strip_row` answers the row (button centres inside the panel, button ``top <
    panel.top + 30``, left to right) and the resolver's ``0.30-0.70`` plot-band rule answers
    *where* that row sits; both are the geometry the strip is already bound with, so the classifier
    and the binding cannot drift. No plot resolved means no band to place the row in, and the
    honest answer is "not shown to be a strip" rather than a guess — a replacement screen has no
    plot at all. The slider is *not* required: the measured 453x40 four-button row has none and is
    the strip (its view stays ambiguous — identity is not a binding).
    """
    row = strip_row(panel, kids)
    if not row or plot is None:
        return False
    centre_y = sum(kid["top"] + kid["h"] / 2 for kid in row) / len(row)
    fraction = (centre_y - plot.top) / max(1, plot.height)
    return _STRIP_BAND[0] <= fraction <= _STRIP_BAND[1]


def _is_cursor_info(panel: Mapping, kids: Sequence[Mapping]) -> bool:
    """The cursor info box: small, caption-less, holding a caption-less child panel, no in-panel row.

    Measured 2026-09-19: ``TSp_Panel 131916 [908,466,1057,525]`` = 149x59, its one child
    ``TSp_Panel 131920 [916,475,1045,514]``, both visible and caption-less, and the button it owns
    (``131918``) paints at ``[917,578,997,598]`` — **outside** its own rect. An owned button
    outside the panel confers neither strip nor popup identity, which is exactly the misreading
    this item removes from the strip vote. The box's painted depth/velocity are out of scope: no
    control in the tree carries them.
    """
    if panel["w"] > _DIALOG_MIN_W or panel["text"].strip():
        return False
    if any(kid["cls"] in _ACTIONABLE_CLASSES and _centre_inside(panel, kid) for kid in kids):
        return False
    return any(
        kid["cls"] == _INFO_BOX_CHILD_CLASS and not kid["text"].strip() for kid in kids
    )


def _is_replacement(
    panel: Mapping, kids: Sequence[Mapping], context: ScreenContext
) -> bool:
    """A replacement surface's own widget band — the measurement skeleton is gone, its band is here.

    ``_replacement_evidence``'s own two facts stated as context: no menubar band resolved
    anywhere and no plot. ``Compare profiles`` / ``Measure US field`` replace the client area
    (UI-OVERLAY-19/21/22), so what is left of the window is the surface's own widget band — and
    that band is what the resolver would otherwise bind as a strip, which is what makes this a
    *surface* finding rather than a strip finding (ledger B08).
    """
    return (
        context.menubar is None
        and context.plot is None
        and any(kid["cls"] == "TSp_Button" and _centre_inside(panel, kid) for kid in kids)
    )


def _is_overlay(panel: Mapping, kids: Sequence[Mapping], plot: Rect | None) -> bool:
    """A non-measurement overlay: over the monitor, with a button row of its own.

    Measured ``Define TGC``: ``TSp_Panel [400,168,850,288]`` = 450x120, six direct children, two of
    them ``TSp_Value_Button`` and four ``TSp_Button`` whose tops begin 46-89 px below the panel's
    own top (so item 4's warrant, which asks for the strip's row inside the panel's top 30 px,
    does not claim it) — and the real recording strip panel is **absent** from that read's visible
    panel set, which is why this warrant may not be "a second button panel beside the strip"
    (the retired ``_overlay_candidates``, which returned empty exactly there).

    "Not full of controls" is what keeps the measured ``Operating parameters`` dialog out of this
    item, so item 8's predicate still claims it: that dialog is 627x384 with 21 direct children.
    The clause is :data:`…ui.dialog._DIALOG_MIN_CHILDREN`, the reference's own "full of controls"
    floor, and never a width.
    """
    if plot is None or not _over_monitor(plot, panel):
        return False
    if not any(kid["cls"] == "TSp_Button" and _centre_inside(panel, kid) for kid in kids):
        return False
    return len(kids) < _DIALOG_MIN_CHILDREN and not any(
        kid["cls"] == "TSp_Browse" for kid in kids
    )


# ----------------------------------------------------------------------------- the entry points


def panel_identity(
    panel: object,
    kids: Sequence[object],
    *,
    context: ScreenContext | None = None,
) -> PanelIdentity:
    """What one panel is, from its own row, its own children and the screen's context.

    ``panel`` and ``kids`` are rows of either projection the package carries (the resolver's
    ``left``/``top``/``w``/``h`` rows, or :class:`~udv_echo_process.acquire.ui.model.UiNode`), and
    ``kids`` must be the panel's **own** children: ``_resolve`` reads them with
    ``win32gui.GetParent`` and the normalized projection with ``UiTree.children``. A panel that
    states no rect is ``OTHER`` — nothing about it is measured.

    Ordered from the narrowest actionable shape to the broadest fallback (module docstring). The
    order is the specification: every claim is tested against *this* panel, so no consumer's
    verdict can feed another's.
    """
    context = ScreenContext() if context is None else context
    own = _row(panel)
    if own is None:
        return PanelIdentity.OTHER
    children = _rows(kids)
    if _is_menu_popup(own, children):
        return PanelIdentity.MENU_POPUP
    if _is_browse_dialog(own, children):
        return PanelIdentity.APPLICATION_DIALOG
    if _is_warning(own, children):
        return PanelIdentity.WARNING
    if _is_measurement_strip(own, children, context.plot):
        return PanelIdentity.MEASUREMENT_STRIP
    if _is_cursor_info(own, children):
        return PanelIdentity.CURSOR_INFO
    if _is_replacement(own, children, context):
        return PanelIdentity.REPLACEMENT
    if _is_overlay(own, children, context.plot):
        return PanelIdentity.OVERLAY
    if _is_dialog_panel(own, children):
        return PanelIdentity.APPLICATION_DIALOG
    return PanelIdentity.OTHER


def classify_panels(
    panels: Sequence[object],
    kids_of: Callable[[object], Sequence[object]],
    *,
    context: ScreenContext | None = None,
) -> dict[int, PanelIdentity]:
    """One identity per panel **considered** — the single pass every consumer reads.

    ``kids_of(panel)`` states a panel's own children (the caller owns that question: the resolver
    walks the live tree from the handle, the normalized projection keeps the parent links). Every
    panel the caller hands over is classified, and a panel whose projection states no handle is
    left out: the inventory is keyed by handle because that is what a resolve can carry, and a
    handle is an action reference for the moment of that resolve — never an identity.
    """
    context = ScreenContext() if context is None else context
    identities: dict[int, PanelIdentity] = {}
    for panel in panels:
        hwnd = _hwnd(panel)
        if hwnd is None:
            continue
        identities[hwnd] = panel_identity(panel, kids_of(panel), context=context)
    return identities


def blocking_surface(identities: Mapping[int, PanelIdentity]) -> PanelIdentity | None:
    """The classified surface a press must not be posted behind, or ``None`` when none is up.

    ``WARNING`` / ``OVERLAY`` / ``APPLICATION_DIALOG`` / ``MENU_POPUP``, the narrowest claim first
    (:data:`BLOCKING`), or ``None``. This is the result that replaces what ``roles["open_popup"]``
    used to stand in for — it was "a panel besides the menu bar, the status bar and the strip hosts
    buttons", which was true of the ``Define TGC`` overlay, of every warning box and of the cursor
    info box — so narrowing ``open_popup`` to a *menu* erases no safety information: the surfaces
    that block are named here, and the ones that do not (``CURSOR_INFO``, ``OTHER``,
    ``REPLACEMENT``) are not.

    **Two panels that are both strips is a surface of its own.** A measurement screen paints exactly
    one recording strip, so a screen on which the strip's own warrant is satisfied twice has a second
    button panel over the monitor — the finding ledger B06 was written from ("two candidates where a
    measurement screen has exactly one: the panel the resolver bound may be an overlay's button panel
    rather than the recording strip"). Nothing may be posted behind a binding the screen cannot
    settle, so this answers ``OVERLAY`` for that screen. The rule reads the per-panel claims only —
    which panels *are* strips — and never which of them the resolver bound.
    """
    up = set(identities.values())
    blocking = next((kind for kind in BLOCKING if kind in up), None)
    if blocking is not None:
        return blocking
    if sum(1 for kind in identities.values() if kind is PanelIdentity.MEASUREMENT_STRIP) > 1:
        return PanelIdentity.OVERLAY
    return None


def with_identities(observation: ScreenObservation) -> ScreenObservation:
    """The observation with every panel's identity — the classifier's pass over a projection.

    A map the resolver produced states its identities, and they are projected as they stand: one
    classification, taken at the resolve, never a second opinion here. A map that states **none**
    — a captured fixture, a hand-built role map — is classified by the same rules, from the same
    panel shapes and the same context, so a fixture and a live read answer alike; children come
    from ``UiTree.children``, which reads the projection's own parent links and falls back to
    containment for a tree that states none (the fixtures' projection).

    ``blocking_surface`` is derived from the identities when the map states an inventory but no
    surface, so a partial map is not read as "nothing is blocking".
    """
    if not observation.identities:
        context = context_of(observation)
        identities = classify_panels(
            list(observation.panels), observation.tree.children, context=context
        )
        surface = blocking_surface(identities)
        return observation.model_copy(
            update={
                "identities": tuple(
                    (hwnd, kind.value) for hwnd, kind in identities.items()
                ),
                "blocking_surface": None if surface is None else surface.value,
            }
        )
    if observation.blocking_surface is not None:
        return observation
    stated: dict[int, PanelIdentity] = {}
    for hwnd, value in observation.identities:
        try:
            stated[hwnd] = PanelIdentity(value)
        except ValueError:  # a map stating a name this vocabulary does not carry
            continue
    surface = blocking_surface(stated)
    if surface is None:
        return observation
    return observation.model_copy(update={"blocking_surface": surface.value})
