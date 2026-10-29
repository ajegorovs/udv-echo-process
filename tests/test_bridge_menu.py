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


ROWS = {
    "filters.moving_average": {
        "menu": "Filters", "offset": [14, 40], "component": "Btn_MoveAver", "effect": "filter",
    },
    "display.vertical_grids": {
        "menu": "Display", "offset": [10, 5], "component": "Btn_Vert_grids", "effect": "display",
    },
    "preferences.assisted_mode": {
        "menu": "Preferences", "offset": [17, 18], "component": "Btn_Assisted_Mode", "effect": "preset",
    },
    "preferences.record_options": {"menu": "Preferences", "offset": [16, 50], "effect": "dialog"},
    "preferences.unclassified": {"menu": "Preferences", "offset": [16, 87]},
}


def table_dict(*, menu: dict | None = None, rows: dict | None = None) -> dict:
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
    if rows is not None:
        table["rows"] = rows
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


def menu(table_dict_overrides: dict | None = None, *, rows: dict | None = ROWS, **kwargs) -> BridgeMenu:
    table = BridgeTable.model_validate(
        table_dict(menu=menu_block(**(table_dict_overrides or {})), rows=ROWS if rows is None else rows)
    )
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


class TestPressingByName:
    def test_a_named_row_presses_its_offset(self):
        press = Press()
        bridge = menu(press=press)
        bridge.open_menu("Filters")
        evidence = bridge.press("filters.moving_average")

        assert press.offsets == [(14, 40)]
        assert evidence.offset == (14, 40)

    def test_a_name_that_is_not_in_the_table_is_refused_by_name(self):
        bridge = menu()
        bridge.open_menu("Filters")
        with pytest.raises(BridgeUnavailable) as caught:
            bridge.press("filters.median")
        assert caught.value.reason == "bridge_menu_row:filters.median"

    def test_a_row_from_another_overlay_is_refused(self):
        press = Press()
        bridge = menu(press=press)
        bridge.open_menu("Filters")
        with pytest.raises(BridgeRefused) as caught:
            bridge.press("display.vertical_grids")
        assert "bridge_menu_row_other_menu:Display" in str(caught.value)
        assert press.offsets == []

    def test_a_named_press_still_needs_an_open_overlay(self):
        bridge = menu()
        with pytest.raises(BridgeRefused):
            bridge.press("filters.moving_average")

    def test_the_row_model_keeps_the_component_for_the_record(self):
        assert menu().row("filters.moving_average").component == "Btn_MoveAver"

    def test_rows_are_optional_and_a_table_without_them_refuses(self):
        bridge = menu(rows={})
        bridge.open_menu("Filters")
        with pytest.raises(BridgeUnavailable):
            bridge.press("filters.moving_average")

    def test_an_unknown_key_in_a_row_is_refused(self, tmp_path, monkeypatch):
        path = tmp_path / "operations.json"
        payload = table_dict(
            menu=menu_block(), rows={"filters.moving_average": {"menu": "Filters", "offset": [14, 40], "x": 1}}
        )
        path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setenv("UDV_BRIDGE_TABLE", str(path))
        with pytest.raises(BridgeUnavailable) as caught:
            load_table()
        assert "bridge_table_invalid" in caught.value.reason


class TestWhatAPressIsAllowedToDo:
    """One measured press of `assisted_mode` rewrote five acquisition parameters, so the row says so."""

    def test_a_display_row_needs_no_consent(self):
        bridge = menu()
        bridge.open_menu("Display")
        bridge.press("display.vertical_grids")  # does not raise

    def test_a_filter_row_needs_no_consent(self):
        bridge = menu()
        bridge.open_menu("Filters")
        bridge.press("filters.moving_average")

    def test_a_preset_row_is_refused_until_it_is_allowed(self):
        press = Press()
        bridge = menu(press=press)
        bridge.open_menu("Preferences")
        with pytest.raises(BridgeRefused) as caught:
            bridge.press("preferences.assisted_mode")
        assert str(caught.value).endswith(":preset")
        assert press.offsets == []

    def test_a_preset_row_is_pressed_when_allowed(self):
        press = Press()
        bridge = menu(press=press)
        bridge.open_menu("Preferences")
        bridge.press("preferences.assisted_mode", allow=("preset",))
        assert press.offsets == [(17, 18)]

    def test_a_dialog_row_needs_consent_too(self):
        bridge = menu()
        bridge.open_menu("Preferences")
        with pytest.raises(BridgeRefused) as caught:
            bridge.press("preferences.record_options")
        assert str(caught.value).endswith(":dialog")

    def test_an_unclassified_row_is_unavailable_not_pressed(self):
        bridge = menu()
        bridge.open_menu("Preferences")
        with pytest.raises(BridgeUnavailable) as caught:
            bridge.press("preferences.unclassified", allow=("preset", "dialog", "mode"))
        assert caught.value.reason == "bridge_menu_row_effect_unknown:preferences.unclassified"

    def test_the_effect_is_named_by_value_in_the_refusal(self):
        # A (str, Enum) member formats as its qualified name on this interpreter, so the message must
        # interpolate the value or a reader is told `MenuRowEffect.PRESET`.
        bridge = menu()
        bridge.open_menu("Preferences")
        with pytest.raises(BridgeRefused) as caught:
            bridge.press("preferences.assisted_mode")
        assert "MenuRowEffect" not in str(caught.value)

    def test_an_unknown_effect_in_the_table_is_refused(self, tmp_path, monkeypatch):
        path = tmp_path / "operations.json"
        rows = {"x.y": {"menu": "Filters", "offset": [1, 2], "effect": "sideways"}}
        path.write_text(json.dumps(table_dict(menu=menu_block(), rows=rows)), encoding="utf-8")
        monkeypatch.setenv("UDV_BRIDGE_TABLE", str(path))
        with pytest.raises(BridgeUnavailable) as caught:
            load_table()
        assert "bridge_table_invalid" in caught.value.reason


class Census:
    """A scriptable census: the surfaces it reports, and what it reports after the next call."""

    def __init__(self, surfaces=(), then=None) -> None:
        self.surfaces = list(surfaces)
        self.then = then
        self.calls = 0

    def __call__(self):
        self.calls += 1
        # `then` is the state the *open* leaves behind; later reads return whatever the test set, so a
        # press can be given a screen of its own.
        if self.calls == 2 and self.then is not None:
            self.surfaces = list(self.then)
        return {"surfaces": list(self.surfaces)}


def guarded(press=None, census=None, rows=None) -> BridgeMenu:
    table = BridgeTable.model_validate(table_dict(menu=menu_block(), rows=ROWS if rows is None else rows))
    return BridgeMenu(table, Dispatch(), press or Press(), census)


class TestTheScreenGuard:
    """What a press did is only knowable from the screen; these pin what the class does with it."""

    def test_opening_on_a_dirty_screen_is_refused(self):
        census = Census(["TSp_Panel:406,55,658,215"])
        bridge = guarded(census=census)
        with pytest.raises(BridgeRefused) as caught:
            bridge.open_menu("Filters")
        assert str(caught.value).startswith("bridge_menu_surface_already_painted:")
        assert bridge.open_index is None

    def test_opening_records_what_it_painted(self):
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(census=census)
        evidence = bridge.open_menu("Filters")
        assert evidence.painted is True
        assert evidence.surfaces == ("TSp_Panel:406,55,658,215",)

    def test_closing_that_leaves_the_panel_painted_is_refused(self):
        # The stuck overlay: `leave` returns a clean report and the panel is still there.
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(census=census)
        bridge.open_menu("Filters")
        with pytest.raises(BridgeRefused) as caught:
            bridge.close_menu()
        assert str(caught.value).startswith("bridge_menu_still_painted:")
        assert bridge.open_index == 6, "a menu that did not close is still open"

    def test_closing_that_clears_the_screen_is_accepted(self):
        census = Census([], then=[])
        bridge = guarded(census=census)
        bridge.open_menu("Filters")
        evidence = bridge.close_menu()
        assert evidence.painted is False
        assert bridge.open_index is None

    def test_a_press_that_raises_a_prompt_is_refused(self):
        # Measured: the assisted-mode row raises a Warning that decides whether the change is kept.
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(press=Press({"pressed": True, "handle": 4242}), census=census)
        bridge.open_menu("Filters")
        census.surfaces = ["TSp_Panel:406,55,658,215", "#32770:772,505,1164,637"]
        with pytest.raises(BridgeRefused) as caught:
            bridge.press_row((14, 40))
        assert str(caught.value).startswith("bridge_menu_press_raised_surface:")

    def test_a_declared_prompt_is_accepted(self):
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(press=Press({"pressed": True, "handle": 4242}), census=census)
        bridge.open_menu("Filters")
        census.surfaces = ["TSp_Panel:406,55,658,215", "TSp_Panel:391,160,841,280"]
        evidence = bridge.press_row((14, 40), allow=("dialog",))
        assert evidence.handle == 4242

    def test_a_press_whose_handler_closes_the_panel_is_fine(self):
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(press=Press({"pressed": True, "handle": 4242}), census=census)
        bridge.open_menu("Filters")
        census.surfaces = []  # the handler called Leave itself
        assert bridge.press_row((14, 40)).handle == 4242

    def test_the_named_press_forwards_the_allowance(self):
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(press=Press({"pressed": True, "handle": 4242}), census=census)
        bridge.open_menu("Preferences")
        census.surfaces = ["TSp_Panel:526,55,919,481", "TSp_Panel:537,336,909,471"]
        with pytest.raises(BridgeRefused):
            bridge.press("preferences.record_options")
        evidence = bridge.press("preferences.record_options", allow=("dialog",))
        assert evidence.offset == (16, 50)

    def test_without_a_census_nothing_is_guarded(self):
        # Documented default: enumerating surfaces is the host's business, and a host that supplies none
        # gets no guard rather than a silent success it did not measure.
        bridge = menu()
        bridge.open_menu("Filters")
        bridge.close_menu()
        assert bridge.open_index is None

    def test_a_census_that_returns_nonsense_is_a_refusal(self):
        bridge = BridgeMenu(
            BridgeTable.model_validate(table_dict(menu=menu_block(), rows=ROWS)),
            Dispatch(),
            Press(),
            lambda: "TSp_Panel",
        )
        with pytest.raises(BridgeUnavailable) as caught:
            bridge.open_menu("Filters")
        assert caught.value.reason == "bridge_menu_census_report_invalid"


class TestReopeningTheMenuItAlreadyHas:
    def test_reopening_the_same_menu_is_a_no_op(self):
        # Measured: `Apply moving average filter` toggles its state and leaves the dropdown painted.
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        dispatch = Dispatch()
        bridge = BridgeMenu(
            BridgeTable.model_validate(table_dict(menu=menu_block(), rows=ROWS)), dispatch, Press(), census
        )
        bridge.open_menu("Filters")
        calls_after_open = len(dispatch.calls)
        again = bridge.open_menu("Filters")
        assert again.raw == {"already_open": True}
        assert len(dispatch.calls) == calls_after_open, "no second enter was dispatched"
        assert bridge.open_index == 6

    def test_a_foreign_surface_is_still_refused(self):
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(census=census)
        bridge.open_menu("Filters")
        census.surfaces = ["TSp_Panel:406,55,658,215", "TSp_Panel:526,55,919,481"]
        with pytest.raises(BridgeRefused):
            bridge.open_menu("Filters")

    def test_reopening_a_different_menu_over_a_painted_one_is_refused(self):
        census = Census([], then=["TSp_Panel:406,55,658,215"])
        bridge = guarded(census=census)
        bridge.open_menu("Filters")
        with pytest.raises(BridgeRefused):
            bridge.open_menu("Display")
