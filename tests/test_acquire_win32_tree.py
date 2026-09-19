"""The moved enumeration, pinned at its new module boundary — and its projection onto ``ui/model``.

``acquire/win32/tree.py`` owns what Patch 3 moved out of ``driver.py`` about *looking* at a
window: the visible-children enumeration with a real area, the single visibility question, the
walk that names what that filter left out, the main window and the parent lookup, and the live
descendant walk the dialog's table needs. These tests drive the module through a scripted
``win32gui``, so the rules are pinned where they now live; ``tests/test_acquire_driver.py`` still
drives them through ``Win32Actuator`` with the whole window layer faked.

The last two tests pin the package boundary itself: the rows project onto
:class:`~udv_echo_process.acquire.ui.model.UiNode` (the one ``acquire/ui`` import this package
makes, a *type* and not a rule), and nothing in ``acquire/win32/`` uses a UDOP role, a campaign or
a store path.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.ui.model import UiNode
from udv_echo_process.acquire.win32 import tree

WINDOW = 777
MAIN_CLASS = "TMain_Scr"
MENUBAR, POPUP_HIDDEN, PLOT, TINY = 11, 12, 13, 14
CONTROLS: dict[int, tuple[str, tuple[int, int, int, int]]] = {
    MENUBAR: ("TSp_MenuBar", (0, 0, 640, 30)),
    POPUP_HIDDEN: ("TSp_Panel", (169, 55, 401, 250)),
    PLOT: ("TDop_Plot", (200, 65, 400, 400)),
    TINY: ("TSp_Splitter", (10, 10, 11, 11)),  # a real control with no area
}
HIDDEN = {POPUP_HIDDEN}


class FakeGui:
    """``win32gui`` as far as the enumeration and the walk ask it, from one table of controls."""

    class error(Exception):
        """``win32gui.error``: what the live walk catches when a control dies mid-walk."""

    def __init__(self, controls=None, *, window_visible=True, dying: set[int] | None = None) -> None:
        self.controls = dict(CONTROLS if controls is None else controls)
        self.window_visible = window_visible
        self.dying = set(dying or ())
        self.calls: list[tuple] = []

    # ---- the one question
    def IsWindowVisible(self, hwnd: int) -> bool:
        self.calls.append(("IsWindowVisible", hwnd))
        return hwnd not in HIDDEN

    # ---- the rows
    def GetWindowRect(self, hwnd: int) -> tuple[int, int, int, int]:
        return self.controls[hwnd][1]

    def GetClassName(self, hwnd: int) -> str:
        if hwnd not in self.controls:
            raise FakeGui.error(f"{hwnd} is not a control of this window")
        return self.controls[hwnd][0]

    def GetWindowText(self, _hwnd: int) -> str:
        return ""  # every TSp_* widget in this application is caption-less

    def GetDlgCtrlID(self, hwnd: int) -> int:
        return hwnd

    def EnumChildWindows(self, _win: int, callback, _lparam) -> int:
        for hwnd in list(self.controls):
            callback(hwnd, None)
        return 1

    def EnumWindows(self, callback, _lparam) -> int:
        for hwnd in ([WINDOW] if self.window_visible else []) + [900]:
            callback(hwnd, None)
        return 1

    def GetParent(self, hwnd: int) -> int:
        self.calls.append(("GetParent", hwnd))
        return WINDOW

    # ---- the live descendant walk
    def GetWindow(self, hwnd: int, which: int) -> int:
        order = [WINDOW, MENUBAR, POPUP_HIDDEN, PLOT, 0]
        if which == 5:  # GW_CHILD
            return MENUBAR if hwnd == WINDOW else 0
        if which == 2:  # GW_HWNDNEXT
            index = order.index(hwnd)
            return order[index + 1]
        return 0


def gui_with_main_window(controls=None, *, visible: bool = True) -> FakeGui:
    gui = FakeGui(controls, window_visible=visible)
    gui.controls[WINDOW] = (MAIN_CLASS, (0, 0, 1280, 900))  # the window itself, largest
    gui.controls[900] = (MAIN_CLASS, (0, 0, 320, 200))  # a smaller window of the same class
    return gui


# ------------------------------------------------------------------------------ the enumeration


def test_the_enumeration_is_the_visible_children_with_a_real_area() -> None:
    """Visible **and** big enough to hold a control: the pre-created panel and a 1x1 splitter are out.

    Every row carries class, text, rect and the derived geometry the resolver binds against — the
    same keys the flat module produced, because the resolver reads them.
    """
    gui = FakeGui()
    rows = tree._visible_children(WINDOW, gui=lambda: (gui, None))

    assert [row["hwnd"] for row in rows] == [MENUBAR, PLOT]
    assert rows[0] == {
        "hwnd": MENUBAR,
        "cls": "TSp_MenuBar",
        "text": "",
        "rect": (0, 0, 640, 30),
        "left": 0,
        "top": 0,
        "w": 640,
        "h": 30,
        "id": MENUBAR,
    }
    assert POPUP_HIDDEN not in [row["hwnd"] for row in rows]  # the hidden panel is absent
    assert TINY not in [row["hwnd"] for row in rows]  # and so is a control with no area


def test_a_control_the_enumeration_cannot_read_is_skipped_not_fatal() -> None:
    """One unreadable handle mid-walk is a skipped control, never a lost enumeration."""
    gui = FakeGui()
    gui.controls[PLOT] = ("TDop_Plot", None)  # type: ignore[assignment]  # GetWindowRect will fail

    rows = tree._visible_children(WINDOW, gui=lambda: (gui, None))

    assert [row["hwnd"] for row in rows] == [MENUBAR]


def test_presence_is_not_visibility_and_an_unreadable_answer_is_false() -> None:
    """The rule the live run paid for: a pre-created panel is *presented*, never *pressed*.

    Only a positive ``True`` counts as proof: an exception from the visibility read is ``False``,
    because an unreadable answer is not evidence that a control is on screen.
    """
    gui = FakeGui()
    assert tree._is_visible(POPUP_HIDDEN, gui=lambda: (gui, None)) is False
    assert tree._is_visible(MENUBAR, gui=lambda: (gui, None)) is True

    class Broken:
        def __getattr__(self, name: str):
            raise FakeGui.error(f"no {name} for you")

    assert tree._is_visible(MENUBAR, gui=lambda: (Broken(), None)) is False


def test_the_hidden_panel_walk_names_what_the_filter_left_out() -> None:
    """The companion walk: the same tree *without* the visibility filter, evidence and not a target."""
    gui = FakeGui()
    panels = tree._hidden_panels(WINDOW, gui=lambda: (gui, None))

    assert panels == [
        {
            "hwnd": POPUP_HIDDEN,
            "cls": "TSp_Panel",
            "rect": (169, 55, 401, 250),
            "left": 169,
            "top": 55,
            "w": 232,
            "h": 195,
            "id": POPUP_HIDDEN,
        }
    ]


# ------------------------------------------------------------------------- the window and the tree


def test_the_main_window_is_the_largest_visible_one_of_the_class() -> None:
    """Several windows of the class can exist; the resolved one is the one with the area."""
    gui = gui_with_main_window()
    assert tree._main_hwnd(MAIN_CLASS, gui=lambda: (gui, None)) == WINDOW


def test_no_window_refuses_naming_the_class() -> None:
    """A class the application has no visible window for is a named refusal, not a ``None``."""
    gui = FakeGui(window_visible=False)
    gui.controls[900] = ("TForm", (0, 0, 320, 200))  # a window of another class is not the one

    with pytest.raises(driver.AcquisitionError) as excinfo:
        tree._main_hwnd(MAIN_CLASS, gui=lambda: (gui, None))

    assert MAIN_CLASS in str(excinfo.value)
    assert "startup screen" in str(excinfo.value)


def test_children_of_answers_from_the_resolve_s_own_rows() -> None:
    """Identity is the parent map of a resolve that already happened, never a second enumeration."""
    gui = FakeGui()
    roles = {"raw": [{"hwnd": MENUBAR}, {"hwnd": PLOT}, {"hwnd": 999}]}
    gui.controls[999] = ("TSp_Panel", (0, 0, 10, 10))

    class Parents:
        def __init__(self) -> None:
            self.seen: list[int] = []

        def __call__(self, hwnd: int) -> int:
            self.seen.append(hwnd)
            return WINDOW if hwnd == MENUBAR else MENUBAR

    parents = Parents()
    gui.GetParent = parents  # type: ignore[method-assign]

    kids = tree._children_of(MENUBAR, roles, gui=lambda: (gui, None))

    assert [row["hwnd"] for row in kids] == [PLOT, 999]  # the two the map parents to MENUBAR
    assert parents.seen == [MENUBAR, PLOT, 999]  # the resolve's rows were used, nothing else
    assert "EnumChildWindows" not in [call[0] for call in gui.calls]


def test_the_descendant_walk_goes_one_level_past_the_direct_children() -> None:
    """The dialog's table lives *inside* its value buttons, so the resolver's rows stop too soon."""
    gui = FakeGui()

    rows = tree._descendants_of(WINDOW, gui=lambda: (gui, None))

    # The walk is the tree, hidden controls included: filtering is the *other* rule
    # (``_is_visible``), applied by the caller that must not press into a pre-created panel.
    assert [row["hwnd"] for row in rows] == [MENUBAR, POPUP_HIDDEN, PLOT]
    assert rows[0] == {"hwnd": MENUBAR, "cls": "TSp_MenuBar", "left": 0, "top": 0, "w": 640, "h": 30}
    assert "text" not in rows[0]  # read separately, through the same WM_GETTEXT reader as anywhere


def test_a_control_that_dies_mid_walk_is_not_a_failed_read() -> None:
    """``win32gui.error`` on one handle: keep walking, keep the rows already taken."""
    gui = FakeGui()

    def rect(hwnd: int):
        if hwnd == MENUBAR:
            raise FakeGui.error("this control is gone")
        return gui.controls[hwnd][1]

    gui.GetWindowRect = rect  # type: ignore[method-assign]

    rows = tree._descendants_of(WINDOW, gui=lambda: (gui, None))

    assert [row["hwnd"] for row in rows] == [POPUP_HIDDEN, PLOT]


# -------------------------------------------------------------------------- the ui/model projection


def test_the_rows_project_onto_the_ui_node_type() -> None:
    """``ui_nodes`` is one call per row into ``UiNode.from_row`` — the model's own projection.

    No rule of its own: the rectangle is parsed once, visibility travels with the row, and the
    handle and the control id stay *action references* for the resolve that produced them.
    """
    gui = FakeGui()
    rows = tree._visible_children(WINDOW, gui=lambda: (gui, None))

    nodes = tree.ui_nodes(rows)

    assert all(isinstance(node, UiNode) for node in nodes)
    assert [node.cls for node in nodes] == ["TSp_MenuBar", "TDop_Plot"]
    assert [node.hwnd for node in nodes] == [MENUBAR, PLOT]  # a handle is an action reference
    assert [node.control_id for node in nodes] == [MENUBAR, PLOT]
    assert [
        (node.rect.left, node.rect.top, node.rect.right, node.rect.bottom) for node in nodes
    ] == [(0, 0, 640, 30), (200, 65, 400, 400)]
    assert [node.visible for node in nodes] == [True, True]
    assert [node.text for node in nodes] == ["", ""]  # caption-less, like every widget here
    assert tree.ui_nodes([]) == ()


def test_the_win32_package_knows_no_udop_policy() -> None:
    """The boundary Patch 3 draws, asserted: mechanics, no policy, one ``ui`` import (a type).

    A Win32 module that *used* a parameter role, a strip view, a dialog field, the campaign or a
    store path would be a rule that belongs in ``acquire/ui/`` or in the workflow layer above this
    package — and one that imported ``campaign``/``runner``/``verify`` would drag the run's policy
    into the transport. Read off the AST, so the docstrings that *name* what is forbidden (this
    module's own subject) cannot trip it.
    """
    here = Path(tree.__file__).parent
    forbidden_names = {
        "PARAMETERS_MENU",
        "PARAMETERS_ENTRY",
        "PARAM_COLUMN_ORDER",
        "StripView",
        "StripControl",
        "StripState",
        "DIALOG_FIELD_ORDER",
        "DIALOG_ONLY_PARAMETERS",
        "ParameterSet",
        "ChannelSetting",
        "AcquisitionLimits",
        "RecordSettings",
        "process_mode",
        "plan_sweep",
        "verify_stored_point",
    }
    for module in ("messages.py", "cursor.py", "tree.py", "__init__.py"):
        parsed = ast.parse((here / module).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(parsed):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for name in sorted(imported):
            assert name.split(".")[0] not in {"campaign", "runner", "verify"}, f"{module}: {name}"
            if name.startswith("udv_echo_process.acquire"):
                assert name in {
                    "udv_echo_process.acquire.actuator",
                    "udv_echo_process.acquire.driver",
                    "udv_echo_process.acquire.win32",
                    "udv_echo_process.acquire.win32.cursor",
                    "udv_echo_process.acquire.win32.messages",
                    "udv_echo_process.acquire.win32.tree",
                    "udv_echo_process.acquire.ui.model",
                }, f"{module}: {name}"
        used = {node.id for node in ast.walk(parsed) if isinstance(node, ast.Name)}
        used |= {node.attr for node in ast.walk(parsed) if isinstance(node, ast.Attribute)}
        assert not (used & forbidden_names), f"{module} uses {sorted(used & forbidden_names)}"

    # the enumeration the interpreter reads is still the facade's surface
    assert driver._visible_children is tree._visible_children
    assert driver._hidden_panels is tree._hidden_panels
    assert driver._main_hwnd is tree._main_hwnd
    assert driver._children_of is tree._children_of
    assert driver._descendants_of is tree._descendants_of
    assert driver._is_visible is tree._is_visible
