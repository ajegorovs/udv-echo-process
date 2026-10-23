"""The menubar step without a pointer: a dispatcher opens the overlay, and the cursor machinery stands down.

The application's menubar ignores posted messages and opens on a real hover, which is why this one step has
always needed the operator's cursor — and why ``allow_real_input=False`` refused it outright. A dispatcher
bound inside the process removes both conditions, so what is pinned here is precisely that: with a menu bound,
the overlay is opened by calling it, the cursor is never read, saved, moved or restored, the foreground is not
demanded, and the unattended setting stops refusing; without one, every one of those still happens.
"""

from __future__ import annotations

from typing import Any

import pytest

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.udop import parameters
from udv_echo_process.acquire.ui.menu import OverlayOpener


class Opener:
    """A dispatcher that records what it was asked for."""

    def __init__(self) -> None:
        self.opened: list[Any] = []
        self.closed = 0

    def open_menu(self, menu: str | int) -> object:
        self.opened.append(menu)
        return {"ok": True}

    def close_menu(self) -> object:
        self.closed += 1
        return {"ok": True}


class Probe(driver.Win32Actuator):
    """``_open_parameters_dialog`` with everything tree-shaped stubbed, and the cursor calls recorded.

    The method is the seam under test: what it does with the pointer is the whole question, so the rest of the
    workflow is answered by the test rather than by a live window.
    """

    def __init__(self, *, menu: OverlayOpener | None = None, allow_real_input: bool = True) -> None:
        self._menu = menu
        self._allow_real_input = allow_real_input
        self._note_sink = None
        self.last_entry_attempt = None
        self.touched: list[str] = []

    # --- the tree, answered by the test -------------------------------------------------------
    def _resolve(self) -> dict:
        return {
            "open_popup": False,
            "menu": {parameters.PARAMETERS_MENU: {"hwnd": 4242}},
            "params": {},
            "window": 1,
            "raw": {},
        }

    def _panel_map(self) -> dict:
        return {}

    def _poll_parameters_overlay(self, before: dict) -> dict:
        self.touched.append("poll")
        return {"hwnd": 99, "rect": (0, 0, 10, 10)}

    def _press_entry(self, entry: dict, overlay: dict) -> dict:
        self.touched.append("press-entry")
        return {"hwnd": 100, "rect": (0, 0, 10, 10)}

    def _channel_combo(self, panel: dict) -> dict:
        return {"hwnd": 101}

    def _assert_assisted_unchanged(self, sidebar_before: bool) -> None:
        return None

    # --- the pointer, which must stay untouched when a dispatcher is bound --------------------
    def _require_foreground(self, window: Any) -> None:
        self.touched.append("require-foreground")

    def _cursor_position(self) -> tuple[int, int]:
        self.touched.append("cursor-position")
        return (0, 0)

    def _hover_centre(self, hwnd: int) -> tuple[int, int]:
        self.touched.append("hover")
        return (1, 1)

    def _restore_cursor(self, saved: Any) -> None:
        self.touched.append("restore-cursor")


@pytest.fixture(autouse=True)
def no_dialog_guard(monkeypatch):
    """The dialog/popup clauses are the resolver's; this file tests the opening step only."""
    monkeypatch.setattr(parameters, "dialog_up_clause", lambda roles: None)
    monkeypatch.setattr(parameters, "_entry_buttons", lambda overlay, raw: [{"rect": (1, 2, 3, 4)}])


class TestWithADispatcher:
    def test_the_overlay_is_opened_by_the_call_and_never_by_the_cursor(self):
        opener = Opener()
        probe = Probe(menu=opener)
        panel = probe._open_parameters_dialog()

        assert panel == {"hwnd": 100, "rect": (0, 0, 10, 10)}
        assert opener.opened == [parameters.PARAMETERS_MENU]
        assert "hover" not in probe.touched
        assert "cursor-position" not in probe.touched
        assert "restore-cursor" not in probe.touched
        assert "require-foreground" not in probe.touched
        # the workflow after the overlay is the same one, entry press included
        assert probe.touched == ["poll", "press-entry"]

    def test_an_unattended_host_may_open_the_dialog_at_all(self):
        # Without a dispatcher this same call refuses by name; with one it is an ordinary step.
        probe = Probe(menu=Opener(), allow_real_input=False)
        assert probe._open_parameters_dialog()["hwnd"] == 100


class TestWithoutADispatcher:
    def test_an_unattended_host_is_still_refused_by_name(self):
        probe = Probe(allow_real_input=False)
        with pytest.raises(driver.AcquisitionError) as caught:
            probe._open_parameters_dialog()
        assert "cannot be opened without real input" in str(caught.value)

    def test_an_attended_host_still_hovers(self):
        probe = Probe(allow_real_input=True)
        probe._open_parameters_dialog()
        assert "hover" in probe.touched
        assert "cursor-position" in probe.touched
        assert "restore-cursor" in probe.touched


class TestTheProtocol:
    def test_a_structural_opener_satisfies_it(self):
        assert isinstance(Opener(), OverlayOpener)

    def test_the_bridge_menu_satisfies_it(self):
        from udv_echo_process.acquire.bridge import BridgeMenu, BridgeTable

        table = BridgeTable.model_validate(
            {
                "schema": "udv-bridge-operations-v1",
                "image_sha256": "a" * 64,
                "caption_prefix": "UDOP DOP3010",
                "abi": {"self": "eax", "sender": "edx", "stack_args": 0, "returns": "ret"},
                "dispatch": {"slot_pointer": 0x7812D0, "status_offset": 0x474},
                "operations": {
                    "record": {"handler": 0x71F034, "code": 28},
                    "stop": {"handler": 0x71F034, "code": 28},
                    "store": {"handler": 0x71F060, "code": 29},
                },
                "menu": {"enter": 0x6D9AF8, "leave": 0x6D9BB8,
                         "order": ["File", "Preferences", "Parameters"]},
            }
        )
        menu = BridgeMenu(table, lambda call: {"ok": True}, None)
        assert isinstance(menu, OverlayOpener)
