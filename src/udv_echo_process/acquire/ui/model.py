"""Normalized UI observations — the pure input of every interpreter under ``acquire/ui``.

Layer 1 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5). An
interpreter under this package reads *these* types and not a live window: the Win32 enumeration
(``acquire/win32/tree._visible_children`` since Patch 3 — still reachable as
``driver._visible_children`` through the facade's compatibility import), the visibility rule and
the control-id bookkeeping stay in the Win32 package, and what arrives here is the **normalized
projection** of that enumeration.

Three rules are structural, and each of them was paid for live:

1. **No ``HWND`` is a semantic identity.** ``UiNode.hwnd`` is carried as an *action reference*
   for the resolve that produced it — control ids change on every launch (43/43 classes at the
   same positions, 1/43 ids in common) and a handle changes with them — so nothing here derives
   meaning from one. Identity is a role: class + containing panel + order inside it.
2. **Visibility is part of the projection.** ``_visible_children`` is what the resolver walks,
   and the ``Parameters`` popup panel is *pre-created* in the tree with ``IsWindowVisible ==
   False`` and only *shown* on the hover — presence is not visibility, and a rule that accepted
   presence presses real coordinates into empty screen. ``UiNode.visible`` therefore exists and
   a node that does not state it is treated as visible only because the enumeration that
   produced it already filtered.
3. **Raw rows are diagnostics.** The rect of a surface is a property of the moment it was
   shown (the strip is draggable: it floats inside the monitor and morphs ``98x40`` →
   ``352x40`` → ``413x123``), so a captured rect describes a *reading* and never a constant
   that could be bound to.

:class:`ScreenObservation` is the record the layout interpreter consumes, and
:meth:`ScreenObservation.from_roles` is the **one place** a resolved role map
(:meth:`~udv_echo_process.acquire.driver.Win32Actuator._resolve`) is projected onto it —
written down once so a caller cannot invent a second, differently-typed view of the same tree.
Everything above it is behaviour: plain functions in :mod:`udv_echo_process.acquire.ui.layout`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from udv_echo_process.acquire.actuator import PARAM_COLUMN_ORDER, StripView
from udv_echo_process.models.base import ValueModel

__all__ = [
    "DialogObservation",
    "MenuObservation",
    "ParameterPanelState",
    "Rect",
    "ScreenObservation",
    "StripObservation",
    "SurfaceKind",
    "UiNode",
    "UiTree",
    "read_parameter_panel",
]


class SurfaceKind(str, Enum):
    """Which surface is on the screen — decided **before** any press target is resolved.

    Treating every extra panel as "an overlay" is what produced the wrong diagnosis in ledger
    B06 and B08, so the kinds are distinct (``docs/dop3000/acquisition-ui-model.md`` §1):

    - ``MEASUREMENT`` — the clean measurement screen: menubar band, parameter column, monitor,
      recording strip, status bar. The whole predicate, not just "no dialog is up".
    - ``OVERLAY`` — a panel drawn *over* the measurement surface: the ``Parameters`` popup, the
      ``Operating parameters`` dialog's siblings, ``Define TGC``, the power↔TGC ``Warning``.
    - ``DIALOG`` — an application dialog panel (identified structurally: not the sidebar, wider
      than 400 px, full of controls) whose widgets are not the layout's.
    - ``POPUP`` — the menubar's own popup panel, which is also the strip resolver's decoy.
    - ``REPLACEMENT`` — a surface that **replaces the client area**, so "no sidebar / no strip"
      is not a mode, it is another surface: ``Measure US field`` and ``Compare profiles``.
    - ``UNKNOWN`` — anything the model cannot classify. It has no binding and no mode, and it
      is a refusal state rather than a default.
    """

    MEASUREMENT = "measurement"
    OVERLAY = "overlay"
    DIALOG = "dialog"
    POPUP = "popup"
    REPLACEMENT = "replacement"
    UNKNOWN = "unknown"


class ParameterPanelState(str, Enum):
    """The fast-access parameter column: the manual screen's own precondition.

    ``PRESENT_COMPLETE`` is the manual shape (the column resolved with all of its
    :data:`~udv_echo_process.acquire.actuator.PARAM_COLUMN_ORDER` roles).
    ``ABSENT`` is a screen with no column panel *and* no rows at all — the state the
    ``Preferences`` option *Show fast access parameters panel (not available in assisted mode)*
    produces on a manual channel, and the state an assisted channel produces as well, which is
    exactly why it is a state and not a mode (ledger B01).
    ``INCOMPLETE`` is a column that resolved without all of its roles: neither accepted shape,
    and a point's writes would land on the wrong fields.
    """

    PRESENT_COMPLETE = "present_complete"
    ABSENT = "absent"
    INCOMPLETE = "incomplete"


class Rect(ValueModel):
    """One control's rectangle in screen coordinates, and the geometry the rules ask of it.

    The comparisons here are the ones the driver's own rules were measured with, so a rule
    cannot drift from the geometry it was written against:

    - :meth:`contains_point` is **edge-inclusive**, like the cursor-clip test: a point on the
      boundary is inside, which is why a move there is never clamped;
    - :meth:`contains` is the nesting test (``outer`` wraps ``inner``), which is how a value
      field is found inside its ``TSp_Value_Button`` row;
    - :meth:`holds_centre_of` is the test the strip's own rule uses — the **centre** of a
      button lies inside the panel — and it is deliberately not the same question as
      :meth:`contains`.
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        """The rectangle's width in pixels."""
        return self.right - self.left

    @property
    def height(self) -> int:
        """The rectangle's height in pixels."""
        return self.bottom - self.top

    @property
    def centre(self) -> tuple[int, int]:
        """The rectangle's centre, as the ``_inside``/cursor rules compute it (integer)."""
        return (self.left + self.width // 2, self.top + self.height // 2)

    def as_tuple(self) -> tuple[int, int, int, int]:
        """The ``(left, top, right, bottom)`` tuple the driver's messages render."""
        return (self.left, self.top, self.right, self.bottom)

    def contains_point(self, point: tuple[int, int]) -> bool:
        """True when ``point`` lies inside the rectangle — edge-inclusive, in screen space."""
        return (
            self.left <= point[0] <= self.right and self.top <= point[1] <= self.bottom
        )

    def contains(self, other: Rect) -> bool:
        """True when ``other`` lies inside this rectangle, as the application lays them out."""
        return (
            self.left <= other.left
            and self.top <= other.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def holds_centre_of(self, other: Rect) -> bool:
        """True when ``other``'s centre lies inside this rectangle."""
        return self.contains_point(other.centre)

    @classmethod
    def from_control(cls, control: Mapping) -> Rect | None:
        """The rectangle of one resolved row — from its ``rect``, or from ``left/top/w/h``.

        ``None`` when the row states neither: a caller that gets ``None`` has no geometry to
        reason from and must refuse rather than assume a rect (a panel projected from a partial
        fixture states no rect at all, and inventing one would bind a press to a rectangle
        nobody measured).
        """
        rect = control.get("rect")
        if rect is not None:
            try:
                left, top, right, bottom = (int(value) for value in rect)
            except (TypeError, ValueError):
                return None
            return cls(left=left, top=top, right=right, bottom=bottom)
        left, top = control.get("left"), control.get("top")
        width, height = control.get("w"), control.get("h")
        if None in (left, top, width, height):
            return None
        try:
            return cls(
                left=int(left),
                top=int(top),
                right=int(left) + int(width),
                bottom=int(top) + int(height),
            )
        except (TypeError, ValueError):
            return None


class UiNode(ValueModel):
    """One control of the normalized projection: its class, its rect, and its evidence.

    ``cls`` is the *role* half of a control's identity (with its containing panel and its order
    inside it); ``text`` is what the control states, carried as evidence and never as an
    identity — every ``TSp_*`` widget in this application is caption-less (``WM_GETTEXT``
    answers ``""``) and the captions an operator sees are the crops' business (ledger B15).
    ``hwnd`` and ``control_id`` are action references for the resolve that produced them.
    """

    cls: str
    rect: Rect | None = None
    visible: bool = True
    text: str = ""
    hwnd: int | None = None
    control_id: int | None = None

    @classmethod
    def from_row(cls, row: Mapping) -> UiNode:
        """Project one resolved row (``_visible_children``'s own dict) onto a node."""
        hwnd, control_id = row.get("hwnd"), row.get("id")
        return cls(
            cls=str(row.get("cls", "")),
            rect=Rect.from_control(row),
            visible=bool(row.get("visible", True)),
            text=str(row.get("text", "")),
            hwnd=hwnd if isinstance(hwnd, int) else None,
            control_id=control_id if isinstance(control_id, int) else None,
        )


class UiTree(ValueModel):
    """The window's controls as a **normalized visible projection**.

    ``nodes`` is what the enumeration reported as visible with a real area — the same list the
    resolver binds roles against — and the raw rows beyond it (the pre-created, hidden panels a
    ``_hidden_panels`` walk finds) stay diagnostics: they are *named* in a refusal and never
    bound, because a hidden panel's rect is where a press would land on nothing.

    ``parent_of`` is the projection's own **parent links** (``roles["parent_of"]``), carried so
    "this panel's own children" is a question a pure rule can ask of a captured tree as well as of
    a live one (``Win32Actuator._resolve`` reads the same relationship live, from ``GetParent``).
    A tree that states no links is read by containment instead (:meth:`children`), which is what a
    partial fixture — every widget hanging off the window — is asking for.
    """

    window: int | None = None
    nodes: tuple[UiNode, ...] = ()
    #: ``hwnd → parent hwnd``, exactly as the resolver published it: the tree's own structure, and
    #: never an identity — a handle is an action reference for the resolve that produced it.
    parent_of: tuple[tuple[int, int], ...] = ()

    def parent(self, hwnd: int | None) -> int | None:
        """The parent this projection states for ``hwnd``, or ``None`` when it states none."""
        if hwnd is None:
            return None
        return dict(self.parent_of).get(hwnd)

    def children(self, panel: UiNode | None) -> tuple[UiNode, ...]:
        """The panel's **own** children — by the projection's parent links, else by containment.

        The links are asked first because they are the stronger statement: a panel's own children
        are what the application gave it, and the resolver binds against exactly that relationship
        (``GetParent``). Only a tree that states no child for this panel falls back to
        :meth:`inside` — the rows whose centre lies inside its rect — so a fixture whose widgets
        all hang off the window is still read as the screen it depicts. A panel that states no
        rect hosts nothing either way, which is the same refusal :meth:`inside` makes.
        """
        if panel is None or panel.rect is None:
            return ()
        links = dict(self.parent_of)
        own = tuple(
            node
            for node in self.nodes
            if node is not panel and node.hwnd is not None and links.get(node.hwnd) == panel.hwnd
        )
        return own or self.inside(panel)

    def node(self, hwnd: int | None) -> UiNode | None:
        """The projected node holding ``hwnd``, or ``None`` — a handle is a lookup, not a role."""
        if hwnd is None:
            return None
        return next((node for node in self.nodes if node.hwnd == hwnd), None)

    def visible(self) -> tuple[UiNode, ...]:
        """The nodes this projection carries as visible."""
        return tuple(node for node in self.nodes if node.visible)

    def inside(self, panel: UiNode | None, cls: str | None = None) -> tuple[UiNode, ...]:
        """The nodes whose **centre** lies inside ``panel``, optionally of one class.

        The panel's own rect is what decides, and a panel that states no rect hosts nothing:
        guessing a rectangle here would put a press on a control nobody measured.
        """
        if panel is None or panel.rect is None:
            return ()
        return tuple(
            node
            for node in self.nodes
            if node is not panel
            and node.rect is not None
            and panel.rect.holds_centre_of(node.rect)
            and (cls is None or node.cls == cls)
        )


class MenuObservation(ValueModel):
    """The menubar as the resolver saw it: its band, its buttons, and what it bound.

    ``buttons`` is the **bar itself**, left → right — every button of the band, named or not, which
    is the evidence the ``Parameters`` anchor's signature is read from. ``named`` is what the
    resolver was able to *prove*: as of Patch 2's widget slice that is at most the one anchor,
    because a name assigned by position is not an identity — the application's variants do not
    paint the same menubar and the entries carry no tree text, so an index map silently renames
    every later role when one entry is absent (ledger B03). Both are carried so a menu interpreter
    (:mod:`udv_echo_process.acquire.ui.menu`) can tell "the anchor did not resolve" from "the bar
    is not the measured one".
    """

    band: UiNode | None = None
    buttons: tuple[UiNode, ...] = ()
    named: tuple[tuple[str, UiNode], ...] = ()

    def node_for(self, name: str) -> UiNode | None:
        """The button the resolver bound to ``name``, or ``None`` when it bound none."""
        return next((node for bound, node in self.named if bound == name), None)


class StripObservation(ValueModel):
    """The recording strip: the panel that hosted the row, the row itself, and its state.

    A press is bound to a button's **position in the current row** (the panel is draggable and
    morphs), so what matters is which panel the resolver bound, how many buttons its top row
    holds and whether it carries a slider — never a width (134 vs 138 px is too close an
    identity) and never a caption.
    """

    panel: UiNode | None = None
    row: tuple[UiNode, ...] = ()
    #: The ``StripView`` **name** the resolver classified, kept as the reading it is: the state
    #: string a tree carries is evidence about a moment, and re-classifying it here would let a
    #: second opinion disagree with the row it was read from.
    state_reading: str | None = None
    #: The slider mark the resolver read off the panel's **own children** and classified that view
    #: from, projected from ``roles["strip_slider"]`` — never re-read here, so this cannot answer a
    #: slider the classification did not (see :meth:`ScreenObservation.from_roles`).
    has_slider: bool = False


class DialogObservation(ValueModel):
    """One application dialog panel: the panel, its children, and the channel it states.

    ``channel`` is what the dialog's own channel combo read — the fact a run compares against
    the channel it routed before any other dialog fact is believed (ledger B17). It is ``None``
    when the dialog stated none, which is not the same as a dialog that was never read.
    """

    panel: UiNode
    children: tuple[UiNode, ...] = ()
    channel: str | None = None


class ScreenObservation(ValueModel):
    """What the application shows, normalized — the layout interpreter's whole input.

    Built by :meth:`from_roles` from the resolver's own role map, so the observation cannot
    disagree with the tree a press would be taken against. The fields are the facts the surface
    predicate is written in (``docs/dop3000/acquisition-ui-model.md`` §2): the window class, the
    menubar band and its buttons, the plot, the strip candidate, the dialog and popup panels,
    the parameter column with its roles, and the visible-control total — the last of which is
    **evidence and never a gate** (plan §24.5 D4: the reference install's clean screen reads 43
    in 4 and the instrument's own 44 in 4, and both are legitimate layouts).

    ``identities`` is the classified inventory (``roles["identities"]`` — one
    :class:`~udv_echo_process.acquire.ui.identity.PanelIdentity` per panel the resolver
    considered) and ``blocking_surface`` the surface that blocks a press when one is up. Both are
    carried as the **values** of the identity vocabulary rather than as its members, because this
    module is the model the interpreter modules are written against and importing the classifier
    here would close a cycle (``ui/identity.py`` imports ``ui/menu.py``, which imports this
    module). :func:`…ui.identity.with_identities` completes them for a map that states none.
    """

    class_name: str | None = None
    client: tuple[int, int] = (0, 0)
    origin: tuple[int, int] = (0, 0)
    tree: UiTree = UiTree()
    panels: tuple[UiNode, ...] = ()
    menu: MenuObservation = MenuObservation()
    plot: UiNode | None = None
    strip: StripObservation = StripObservation()
    dialogs: tuple[UiNode, ...] = ()
    popup_open: bool = False
    parameter_column: UiNode | None = None
    parameter_panel: ParameterPanelState = ParameterPanelState.ABSENT
    parameter_roles: tuple[str, ...] = ()
    parameter_rows: int = 0
    control_count: int = 0
    #: The classified inventory: ``(panel hwnd, PanelIdentity value)`` for every panel the
    #: resolver considered — one classification, taken before any consumer excludes or votes on a
    #: panel, and read here rather than re-derived.
    identities: tuple[tuple[int, str], ...] = ()
    #: The identity of the surface that blocks an action while it is up (``WARNING`` / ``OVERLAY``
    #: / ``APPLICATION_DIALOG`` / ``MENU_POPUP``), or ``None``. It is what ``popup_open`` never
    #: was: ``open_popup`` asked whether *any* panel besides the bands hosted a button, which was
    #: true of the ``Define TGC`` overlay, of every warning box and of the cursor info box.
    blocking_surface: str | None = None

    def identity_of(self, panel: UiNode | None) -> str | None:
        """The identity value this observation classified for ``panel``, or ``None``.

        A handle is a lookup here, exactly as it is in :meth:`UiTree.node`: the identity belongs to
        the panel the resolve considered, not to a handle that survives it.
        """
        if panel is None or panel.hwnd is None:
            return None
        return dict(self.identities).get(panel.hwnd)

    @classmethod
    def from_roles(cls, roles: Mapping) -> ScreenObservation:
        """Project a resolved role map onto the observation — the single place it is written.

        Tolerant by construction: a role map captured from a fixture (or from a driver fake)
        states only the keys its own case needed, and a projection that insisted on all of them
        would make every partial tree unreadable — including the ones the gate is *supposed* to
        refuse. A key that is absent projects as "not resolved", which is exactly what the
        refusal says about it.
        """
        nodes = tuple(UiNode.from_row(row) for row in (roles.get("raw") or ()))
        tree = UiTree(
            window=roles.get("window"),
            nodes=nodes,
            # The projection's parent links, as the resolver published them: ``{hwnd: parent}``.
            # A map that states none leaves the tree read by containment (``UiTree.children``).
            parent_of=tuple(
                (int(hwnd), int(parent))
                for hwnd, parent in (roles.get("parent_of") or {}).items()
                if hwnd is not None and parent is not None
            ),
        )
        by_hwnd = {node.hwnd: node for node in nodes if node.hwnd is not None}

        def project(row: Mapping | None) -> UiNode | None:
            """The projected node for one resolved row — the same node the tree carries."""
            if row is None:
                return None
            hwnd = row.get("hwnd")
            return by_hwnd.get(hwnd) or UiNode.from_row(row)

        panels = tuple(
            node for node in (project(panel) for panel in (roles.get("panels") or ())) if node
        )
        menu_rows = roles.get("menu") or {}
        # The bar is ``menu_buttons`` when the resolver published it — every button of the band,
        # named or not — and otherwise the rows the resolver did bind, so a tree that states only
        # a binding (a fixture, a fake) is still read by the same rule as a captured one.
        menu_bar = roles.get("menu_buttons") or tuple(menu_rows.values())
        menu = MenuObservation(
            band=project(roles.get("menu_band")),
            buttons=tuple(node for node in (project(row) for row in menu_bar) if node),
            named=tuple(
                (str(name), node)
                for name, node in (
                    (name, project(row)) for name, row in menu_rows.items()
                )
                if node is not None
            ),
        )
        strip_panel = project(roles.get("strip_panel"))
        # The slider's mark has **one** authority, and it is the resolver's: ``_resolve`` reads it off
        # the strip panel's own children (``ui.strip.has_slider``), carries it as ``strip_slider`` and
        # classifies ``state`` from that same reading, so a map that states the reading is projected
        # from it and nothing else. Re-reading it here over every node whose centre falls inside the
        # panel is what let a *nested* widget answer a slider the view and the press binding were
        # never classified with — one tree, two opinions. Only a partial (legacy) map that states no
        # reading is answered for: from the view it classified (``STORE`` **is** the slider's view,
        # the fallback ``udop.recording._state_of`` reads a captured tree with), and from the tree's
        # own nodes when it states no view either, so a captured tree with no window behind it still
        # reads — but never over a reading the resolver already took.
        if "strip_slider" in roles:
            has_slider = bool(roles["strip_slider"])
        elif roles.get("state") is not None:
            has_slider = roles.get("state") == StripView.STORE.value
        else:
            has_slider = any(
                node.cls == "TSp_Sliding_Bar" for node in tree.inside(strip_panel)
            )
        strip = StripObservation(
            panel=strip_panel,
            row=tuple(
                node for node in (project(row) for row in (roles.get("strip_row") or ())) if node
            ),
            state_reading=None if roles.get("state") is None else str(roles["state"]),
            has_slider=has_slider,
        )
        dialog_hwnds = set(roles.get("value_dialogs") or ()) | set(
            roles.get("browse_dialogs") or ()
        )
        column = project(roles.get("left_panel"))
        params = roles.get("params") or {}
        rows = roles.get("param_rows") or ()
        return cls(
            class_name=roles.get("class_name"),
            client=tuple(roles.get("client") or (0, 0)),
            origin=tuple(roles.get("origin") or (0, 0)),
            tree=tree,
            panels=panels,
            menu=menu,
            plot=project(roles.get("plot")),
            strip=strip,
            dialogs=tuple(panel for panel in panels if panel.hwnd in dialog_hwnds),
            popup_open=bool(roles.get("open_popup")),
            parameter_column=column,
            parameter_panel=read_parameter_panel(column, len(params), len(rows)),
            parameter_roles=tuple(
                getattr(role, "value", str(role)) for role in params
            ),
            parameter_rows=len(rows),
            control_count=len(nodes),
            # The classified inventory, as the map states it: values, in the map's own order (the
            # resolver publishes its panels top-down). A map that states none carries none, and
            # ``ui/identity.with_identities`` — which the one projection, ``ui.layout.observation_of``,
            # always runs — classifies that same tree by the same rules.
            identities=tuple(
                (int(hwnd), str(getattr(kind, "value", kind)))
                for hwnd, kind in (roles.get("identities") or {}).items()
                if isinstance(hwnd, int)
            ),
            blocking_surface=(
                None
                if roles.get("blocking_surface") is None
                else str(getattr(roles["blocking_surface"], "value", roles["blocking_surface"]))
            ),
        )


def read_parameter_panel(
    column: UiNode | None, roles_resolved: int, rows: int
) -> ParameterPanelState:
    """Which of the three states the fast-access parameter panel is in, from the tree alone.

    The rule is a *reading*, never a mode (ledger B01): a screen with no column at all is the
    state a manual channel reaches with the panel switched off in ``Preferences``, so nothing
    that reads it may promote it to a channel mode — the caller refuses on the *screen*, naming
    both possibilities. The distinction between ``ABSENT`` and ``INCOMPLETE`` is the same one
    plan §24.3 draws: no column anywhere is a screen whose panel is gone, while a column that
    resolved without its roles is a binding that would write the wrong fields.
    """
    if column is None and roles_resolved == 0 and rows == 0:
        return ParameterPanelState.ABSENT
    if column is not None and roles_resolved >= len(PARAM_COLUMN_ORDER):
        return ParameterPanelState.PRESENT_COMPLETE
    return ParameterPanelState.INCOMPLETE
