"""The menu route: open an overlay, press a row, close it — with the refusals this repository owns.

The vendor facts (the two routine addresses and the index order) live in the machine-local table, exactly
as the command codes do.  These tests supply a table and two fakes, and pin what the class promises:
what it passes to the dispatch, what it refuses, and what it will not credit.
"""

from __future__ import annotations

import json

import pytest

from udv_echo_process.acquire.bridge import (
    BRIDGE_TABLE_SCHEMA,
    BridgeMenu,
    BridgeRefused,
    BridgeTable,
    BridgeUnavailable,
    load_table,
)

BUILD = "a" * 64
ENTER, LEAVE = 0x6D9AF8, 0x6D9BB8
ORDER = ("File", "Preferences", "Parameters", "Compute", "Display", "Filters", "Cursors",
         "Tools", "Help", "Mpx", "UDV_MD")


def table_dict(*, menu: dict | None = None) -> dict:
    table = {
        "schema": BRIDGE_TABLE_SCHEMA,
        "image_sha256": BUILD,
        "caption_prefix": "UDOP DOP3010",
        "abi": {"self": "eax", "sender": "edx", "stack_args": 0, "returns": "ret"},
        "dispatch": {"slot_pointer": 0x7812D0, "status_offset": 0x474},
        "operations": {
            "record": {"handler": 0x71F034, "code": 28},
            "stop": {"handler": 0x71F034, "code": 28},
            "store": {"handler": 0x71F060, "code": 29},
        },
    }
    if menu is not None:
        table["menu"] = menu
    return table


def menu_block(**overrides) -> dict:
    block = {"enter": ENTER, "leave": LEAVE, "order": list(ORDER)}
    block.update(overrides)
    return block


class Dispatch:
    """Records the calls it is given and answers with a scripted report."""

    def __init__(self, report: dict | None = None) -> None:
        self.calls: list = []
        self.report = report if report is not None else {"ok": True, "overlay_painted": True}

    def __call__(self, call):
        self.calls.append(call)
        return self.report


class Press:
    """Records the offsets it is asked to press and answers as the window layer would."""

    def __init__(self, report: dict | None = None) -> None:
        self.offsets: list[tuple[int, int]] = []
        self.report = report if report is not None else {"pressed": True, "handle": 4242}

    def __call__(self, offset):
        self.offsets.append(tuple(offset))
        return self.report


def menu(table_dict_overrides: dict | None = None, **kwargs) -> BridgeMenu:
    table = BridgeTable.model_validate(table_dict(menu=menu_block(**(table_dict_overrides or {}))))
    return BridgeMenu(table, kwargs.get("dispatch") or Dispatch(), kwargs.get("press", Press()))


class TestTheOrder:
    def test_a_name_resolves_to_its_index(self):
        assert menu().index_of("File") == 1
        assert menu().index_of("Filters") == 6
        assert menu().index_of("UDV_MD") == 11

    def test_a_number_is_taken_as_an_index(self):
        assert menu().index_of(3) == 3

    def test_an_unknown_name_is_refused_by_the_request(self):
        with pytest.raises(BridgeUnavailable) as caught:
            menu().index_of("Nowhere")
        assert caught.value.reason == "bridge_menu_index:Nowhere"

    def test_an_index_outside_the_order_is_refused(self):
        with pytest.raises(BridgeUnavailable) as caught:
            menu().index_of(12)
        assert caught.value.reason == "bridge_menu_index:12"

    def test_zero_is_not_a_menu(self):
        with pytest.raises(BridgeUnavailable):
            menu().index_of(0)

    def test_an_explicit_count_limits_the_indices(self):
        # A build with fewer menus: the order still names them, the count decides what is accepted.
        bridge = menu({"count": 3})
        assert bridge.index_of("Parameters") == 3
        with pytest.raises(BridgeUnavailable):
            bridge.index_of("Compute")


class TestOpeningAndClosing:
    def test_opening_calls_enter_with_the_index_and_pins_the_routines(self):
        dispatch = Dispatch()
        bridge = menu(dispatch=dispatch)
        evidence = bridge.open_menu("Filters")

        call = dispatch.calls[0]
        assert call.action == "enter"
        assert call.address == ENTER
        assert call.index == 6
        assert len(call.routines_digest) == 64
        assert evidence.action == "enter"
        assert evidence.index == 6
        assert evidence.painted is True
        assert bridge.open_index == 6

    def test_closing_calls_leave_without_an_index(self):
        dispatch = Dispatch()
        bridge = menu(dispatch=dispatch)
        bridge.open_menu("Help")
        bridge.close_menu()

        leave = dispatch.calls[1]
        assert leave.action == "leave"
        assert leave.address == LEAVE
        assert leave.index is None
        assert bridge.open_index is None

    def test_the_digest_is_the_routines_not_the_table(self):
        first = Dispatch()
        second = Dispatch()
        menu(dispatch=first).open_menu("File")
        menu(dispatch=second).open_menu("File")
        assert first.calls[0].routines_digest == second.calls[0].routines_digest

        other = Dispatch()
        menu({"enter": ENTER + 1}, dispatch=other).open_menu("File")
        assert other.calls[0].routines_digest != first.calls[0].routines_digest

    def test_a_failed_call_is_a_refusal_with_the_reason(self):
        dispatch = Dispatch({"ok": False, "reason": "dispatch_boundary_changed"})
        with pytest.raises(BridgeRefused) as caught:
            menu(dispatch=dispatch).open_menu("File")
        assert "bridge_menu_call_failed:enter:dispatch_boundary_changed" in str(caught.value)

    def test_a_report_naming_only_a_reason_is_a_failure(self):
        dispatch = Dispatch({"reason": "wrong_gui_thread"})
        with pytest.raises(BridgeRefused):
            menu(dispatch=dispatch).open_menu("File")

    def test_a_table_without_the_routines_refuses_by_name(self):
        table = BridgeTable.model_validate(table_dict())
        bridge = BridgeMenu(table, Dispatch(), Press())
        with pytest.raises(BridgeUnavailable) as caught:
            bridge.open_menu("File")
        assert caught.value.reason == "bridge_menu_missing"

    def test_the_report_must_be_a_mapping(self):
        bridge = menu(dispatch=lambda call: ["not", "a", "mapping"])  # type: ignore[arg-type]
        with pytest.raises(BridgeUnavailable) as caught:
            bridge.open_menu("File")
        assert caught.value.reason == "bridge_menu_report_invalid"


class TestPressingARow:
    def test_a_press_needs_an_open_overlay(self):
        press = Press()
        bridge = menu(press=press)
        with pytest.raises(BridgeRefused) as caught:
            bridge.press_row((14, 40))
        assert str(caught.value) == "bridge_menu_not_open"
        assert press.offsets == []

    def test_a_press_without_a_mechanism_is_unavailable_not_silent(self):
        table = BridgeTable.model_validate(table_dict(menu=menu_block()))
        bridge = BridgeMenu(table, Dispatch(), None)
        bridge.open_menu("Filters")
        with pytest.raises(BridgeUnavailable) as caught:
            bridge.press_row((14, 40))
        assert caught.value.reason == "bridge_menu_press_unavailable"

    def test_a_press_carries_the_offset_and_returns_the_handle(self):
        press = Press({"pressed": True, "handle": 1234})
        bridge = menu(press=press)
        bridge.open_menu("Filters")
        evidence = bridge.press_row((14, 40))

        assert press.offsets == [(14, 40)]
        assert evidence.offset == (14, 40)
        assert evidence.handle == 1234

    def test_a_press_that_reports_failure_is_refused_with_its_reason(self):
        press = Press({"pressed": False, "reason": "no entry at that offset"})
        bridge = menu(press=press)
        bridge.open_menu("Filters")
        with pytest.raises(BridgeRefused) as caught:
            bridge.press_row((99, 99))
        assert "bridge_menu_press_failed:no entry at that offset" in str(caught.value)

    def test_a_press_without_a_handle_is_incomplete_not_successful(self):
        bridge = menu(press=Press({"pressed": True}))
        bridge.open_menu("Filters")
        with pytest.raises(BridgeUnavailable) as caught:
            bridge.press_row((14, 40))
        assert caught.value.reason == "bridge_menu_press_handle_missing"

    def test_closing_clears_what_was_opened(self):
        bridge = menu()
        bridge.open_menu("Filters")
        bridge.close_menu()
        with pytest.raises(BridgeRefused):
            bridge.press_row((14, 40))


class TestTheTableLoadsWithAMenuBlock:
    def test_a_table_with_the_menu_block_loads(self, tmp_path, monkeypatch):
        path = tmp_path / "operations.json"
        path.write_text(json.dumps(table_dict(menu=menu_block())), encoding="utf-8")
        monkeypatch.setenv("UDV_BRIDGE_TABLE", str(path))

        table = load_table()
        assert table.menu is not None
        assert table.menu.enter == ENTER
        assert table.menu.indices["Filters"] == 6

    def test_a_table_without_the_menu_block_still_loads(self, tmp_path, monkeypatch):
        path = tmp_path / "operations.json"
        path.write_text(json.dumps(table_dict()), encoding="utf-8")
        monkeypatch.setenv("UDV_BRIDGE_TABLE", str(path))

        assert load_table().menu is None

    def test_an_unknown_key_in_the_menu_block_is_refused(self, tmp_path, monkeypatch):
        path = tmp_path / "operations.json"
        path.write_text(
            json.dumps(table_dict(menu=menu_block(frobnicate=1))), encoding="utf-8"
        )
        monkeypatch.setenv("UDV_BRIDGE_TABLE", str(path))
        with pytest.raises(BridgeUnavailable) as caught:
            load_table()
        assert "bridge_table_invalid" in caught.value.reason
