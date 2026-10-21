"""The read-only ``Channels`` popup reading: replay, refusals, and no gesture at all.

Every fixture here is a **projected, de-identified shape** of a retained capture: the rows the
live enumeration would report (class, rect, text, parent link) with the handles renumbered and
the whole popup translated, so nothing absolute is left in the repository and no ignored capture
file is read. Two shapes are carried:

* the operator-opened settings popup (8 bands, from ``channels-inspection-20261020T195526-72bf1c``);
* the same panel **clipped** to its one multiplexer-on entry
  (from ``multiplexer-ready-capture-20261020T201133-6804d5``), which keeps the settings furniture
  in the tree outside its own rect — the reason no amount is read from it.

What the tests hold:

1. the stated amounts are the widget's own exact text (``1``/``1``/``1``/``7``/``0.28``), never a
   synthesis, and both strings and parses are reported;
2. every tick, toggle and per-channel amount's *channel* is ``UNKNOWN``/``None`` — the type has no
   boolean and no ``checked`` field, so "empty text ⇒ unticked" cannot be written;
3. absent / ambiguous / clipped / behind-a-dialog / re-ordered / empty values fail closed with a
   named refusal, and a hidden control is not a control;
4. a successful inspection is never a verified setup (``setup_verified`` is ``False``);
5. the public CLI reads through a double that raises on *any* attribute it did not explicitly
   allow, so a press, hover or commit on this path would fail the test rather than pass unnoticed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from udv_echo_process.acquire import channels_read
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.ui.channels import (
    SETTINGS_SIGNATURE,
    ChannelsSurface,
    resolve_channels,
)
from udv_echo_process.acquire.ui.layout import observation_of
from udv_echo_process.cli import acquire_main

#: The main window of the projected shape — a synthetic handle, not a measured one.
WINDOW = 9000

#: The settings popup: (hwnd, parent, class, rect, text[, visible]). Translated by
#: ``(-526, -55)`` and renumbered from the retained capture's ``controls`` rows.
SETTINGS_ROWS: tuple[tuple, ...] = (
    (1000, WINDOW, "TSp_Panel", (0, 0, 393, 426), ""),
    (1001, 1000, "TSp_Button", (24, 212, 344, 244), ""),
    (1002, 1000, "TSp_Button", (213, 76, 367, 94), ""),
    (1003, 1000, "TSp_Button", (10, 3, 132, 33), ""),
    (1004, 1000, "TComboBox", (255, 189, 300, 210), "1"),
    (1005, 1004, "Edit", (258, 192, 280, 207), "1"),
    (1006, 1000, "TPanel", (159, 110, 382, 149), ""),
    (1007, 1006, "TSp_Button", (354, 113, 369, 146), ""),
    (1008, 1006, "TSp_Button", (335, 113, 350, 146), ""),
    (1009, 1006, "TSp_Button", (314, 113, 329, 146), ""),
    (1010, 1006, "TSp_Button", (293, 113, 308, 146), ""),
    (1011, 1006, "TSp_Button", (271, 113, 286, 146), ""),
    (1012, 1006, "TSp_Button", (250, 113, 265, 146), ""),
    (1013, 1006, "TSp_Button", (230, 113, 245, 146), ""),
    (1014, 1006, "TSp_Button", (208, 113, 223, 146), ""),
    (1015, 1006, "TSp_Button", (187, 113, 202, 146), ""),
    (1016, 1006, "TSp_Button", (167, 113, 182, 146), ""),
    (1017, 1000, "TSp_Value_Button", (254, 155, 360, 179), ""),
    (1018, 1017, "TSp_Edit", (258, 159, 318, 175), "1"),
    (1019, 1000, "TSp_Panel", (11, 281, 383, 416), ""),
    (1020, 1019, "TSp_Button", (208, 332, 358, 352), ""),
    (1021, 1019, "TComboBox", (256, 294, 306, 315), "1"),
    (1022, 1021, "Edit", (259, 297, 286, 312), "1"),
    (1023, 1019, "TSp_Button", (40, 332, 190, 352), ""),
    (1024, 1019, "TSp_Value_Button", (260, 384, 366, 408), ""),
    (1025, 1024, "TSp_Edit", (264, 388, 304, 404), "0.28"),
    (1026, 1019, "TSp_Value_Button", (89, 381, 246, 405), ""),
    (1027, 1026, "TSp_Edit", (93, 385, 133, 401), "7"),
    (1028, 1000, "TSp_Button", (9, 36, 138, 68), ""),
    (1029, 1000, "TPanel", (154, 7, 377, 47), ""),
    (1030, 1029, "TSp_Button", (351, 10, 366, 43), ""),
    (1031, 1029, "TSp_Button", (330, 10, 345, 43), ""),
    (1032, 1029, "TSp_Button", (308, 10, 323, 43), ""),
    (1033, 1029, "TSp_Button", (288, 10, 303, 43), ""),
    (1034, 1029, "TSp_Button", (266, 10, 281, 43), ""),
    (1035, 1029, "TSp_Button", (244, 10, 259, 43), ""),
    (1036, 1029, "TSp_Button", (224, 10, 239, 43), ""),
    (1037, 1029, "TSp_Button", (203, 10, 218, 43), ""),
    (1038, 1029, "TSp_Button", (182, 10, 197, 43), ""),
    (1039, 1029, "TSp_Button", (161, 10, 176, 43), ""),
)

#: The multiplexer-on shape: the same panel clipped to ``(0, 0, 158, 43)`` with one entry inside
#: it, its settings furniture still declared outside, and two rows the window reports as hidden.
ENTRY_ROWS: tuple[tuple, ...] = (
    (1000, WINDOW, "TSp_Panel", (0, 0, 158, 43), ""),
    (1001, 1000, "TSp_Button", (24, 212, 344, 244), ""),
    (1002, 1000, "TSp_Button", (213, 76, 367, 94), ""),
    (1003, 1000, "TSp_Button", (10, 3, 148, 33), ""),
    (1004, 1000, "TComboBox", (255, 189, 300, 210), "1"),
    (1005, 1004, "Edit", (258, 192, 280, 207), "1"),
    (1006, 1000, "TPanel", (159, 110, 382, 149), ""),
    (1007, 1006, "TSp_Button", (354, 113, 369, 146), ""),
    (1008, 1006, "TSp_Button", (335, 113, 350, 146), ""),
    (1009, 1006, "TSp_Button", (314, 113, 329, 146), ""),
    (1010, 1006, "TSp_Button", (293, 113, 308, 146), ""),
    (1011, 1006, "TSp_Button", (271, 113, 286, 146), ""),
    (1012, 1006, "TSp_Button", (250, 113, 265, 146), ""),
    (1013, 1006, "TSp_Button", (230, 113, 245, 146), ""),
    (1014, 1006, "TSp_Button", (208, 113, 223, 146), ""),
    (1015, 1006, "TSp_Button", (187, 113, 202, 146), ""),
    (1016, 1006, "TSp_Button", (167, 113, 182, 146), ""),
    (1017, 1000, "TSp_Value_Button", (254, 155, 360, 179), ""),
    (1018, 1017, "TSp_Edit", (258, 159, 318, 175), "1"),
    (1019, 1000, "TSp_Panel", (11, 281, 383, 416), ""),
    (1020, 1019, "TSp_Button", (208, 332, 358, 352), ""),
    (1021, 1019, "TComboBox", (256, 294, 306, 315), "1"),
    (1022, 1021, "Edit", (259, 297, 286, 312), "1"),
    (1023, 1019, "TSp_Button", (40, 332, 190, 352), ""),
    (1024, 1019, "TSp_Value_Button", (260, 384, 366, 408), ""),
    (1025, 1024, "TSp_Edit", (264, 388, 304, 404), "0.20"),
    (1026, 1019, "TSp_Value_Button", (89, 381, 246, 405), ""),
    (1027, 1026, "TSp_Edit", (93, 385, 133, 401), "5"),
    # reported by the window as hidden while the panel is clipped: presence is not visibility
    (1028, 1000, "TSp_Button", (9, 36, 138, 68), "", False),
    (1029, 1000, "TPanel", (154, 7, 377, 47), "", False),
)


def _roles(
    rows: tuple[tuple, ...],
    *,
    offset: tuple[int, int] = (0, 0),
    texts: dict[int, str] | None = None,
    hidden: tuple[int, ...] = (),
    value_dialogs: tuple[int, ...] = (),
) -> dict:
    """One driver-shaped role map: ``raw`` rows, ``parent_of`` links, the window, the dialogs."""
    dx, dy = offset
    raw: list[dict] = []
    parent_of: dict[int, int] = {}
    for row in rows:
        hwnd, parent, cls, rect, text = row[:5]
        visible = row[5] if len(row) > 5 else True
        if hwnd in hidden:
            visible = False
        left, top, right, bottom = rect
        placed = (left + dx, top + dy, right + dx, bottom + dy)
        if texts and hwnd in texts:
            text = texts[hwnd]
        raw.append(
            {
                "hwnd": hwnd,
                "cls": cls,
                "text": text,
                "rect": placed,
                "left": placed[0],
                "top": placed[1],
                "w": placed[2] - placed[0],
                "h": placed[3] - placed[1],
                "id": hwnd % 977,
                "visible": visible,
            }
        )
        parent_of[hwnd] = parent
    panels = tuple(
        row
        for row in raw
        if row["cls"] in {"TSp_Panel", "TPanel"}
        and row["top"] >= 0
        and parent_of[row["hwnd"]] == WINDOW
    )
    return {
        "window": WINDOW,
        "raw": raw,
        "parent_of": parent_of,
        "panels": panels,
        "value_dialogs": value_dialogs,
    }


def _read(rows: tuple[tuple, ...], **kwargs) -> object:
    return resolve_channels(observation_of(_roles(rows, **kwargs)))


# ---------------------------------------------------------------------------------------------
# the settings popup: exact texts, explicit unknowns
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("left", [20, 370])
def test_extra_amount_box_refuses_instead_of_shifting_field_owners(left):
    rows = SETTINGS_ROWS + (
        (1050, 1019, "TSp_Value_Button", (left, 380, left + 60, 406), ""),
        (1051, 1050, "TSp_Edit", (left + 4, 384, left + 50, 402), "3"),
    )
    report = _read(rows)
    assert not report.readable
    assert any("group box's bands" in refusal for refusal in report.refusals)
    assert report.per_channel is None


@pytest.mark.parametrize("replacement", ["TSp_Value_Button", "Edit", "TPanel"])
def test_changed_toggle_class_refuses_instead_of_shifting_captions(replacement):
    rows = tuple(
        (*row[:2], replacement, *row[3:]) if row[0] == 1003 else row
        for row in SETTINGS_ROWS
    )
    report = _read(rows)
    assert report.surface is ChannelsSurface.CHANGED_STRUCTURE
    assert not report.readable
    assert report.refusals
    assert report.toggles == ()


def test_settings_popup_reads_the_exact_stated_texts() -> None:
    report = _read(SETTINGS_ROWS)
    assert report.surface is ChannelsSurface.SETTINGS_POPUP
    assert report.readable is True
    assert report.refusals == ()
    assert report.signature == SETTINGS_SIGNATURE
    assert (report.repeat.text, report.repeat.value) == ("1", 1)
    assert (report.start_channel.text, report.start_channel.value) == ("1", 1)
    assert (report.apply_from.text, report.apply_from.value) == ("1", 1)
    assert (report.per_channel.profiles.text, report.per_channel.profiles.value) == (
        "7",
        7,
    )
    assert (report.per_channel.seconds.text, report.per_channel.seconds.value) == (
        "0.28",
        0.28,
    )


def test_no_tick_toggle_or_channel_state_is_ever_a_boolean() -> None:
    report = _read(SETTINGS_ROWS)
    assert report.setup_verified is False
    assert "checked" not in type(report.channel_ticks[0]).model_fields
    assert {cell.state for cell in report.channel_ticks} == {"UNKNOWN"}
    assert {toggle.state for toggle in report.toggles} == {"UNKNOWN"}
    # two ten-cell rows, named apart: the ``Use only channel`` radio row and the tick row
    assert {cell.strip for cell in report.channel_ticks} == {
        "use_only_channel",
        "use_channels",
    }
    assert len(report.channel_ticks) == 20
    assert len(report.toggles) == 4
    assert report.per_channel.channel == "UNKNOWN"
    assert "channel" in report.per_channel.channel_unknown
    for dump in (
        report.model_dump(mode="json"),
        json.dumps(report.model_dump(mode="json")),
    ):
        assert "unchecked" not in str(dump)
        assert "checked" not in str(dump)


def test_the_amounts_channel_is_caption_only() -> None:
    report = _read(SETTINGS_ROWS)
    assert report.per_channel.channel == "UNKNOWN"
    assert any("caption-only" in note for note in report.uncertainties)
    assert any("not a verified setup" in note for note in report.uncertainties)


def test_a_translated_popup_reads_identically() -> None:
    moved = _read(SETTINGS_ROWS, offset=(213, -47))
    assert moved.readable is True
    assert moved.signature == SETTINGS_SIGNATURE
    assert moved.per_channel.profiles.text == "7"
    assert moved.per_channel.seconds.value == 0.28


def test_captions_carry_their_own_provenance() -> None:
    report = _read(SETTINGS_ROWS)
    assert report.repeat.attribution.caption == "Repeat the acquisition sequence"
    assert "caption-less" in report.repeat.attribution.provenance
    assert report.caption_source.startswith("attributed:")


# ---------------------------------------------------------------------------------------------
# empty values, absent, ambiguous, wrong surface, changed order — all fail closed
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("hwnd", [1025, 1027])
def test_an_empty_amount_is_a_refusal_and_never_zero(hwnd: int) -> None:
    report = _read(SETTINGS_ROWS, texts={hwnd: ""})
    assert report.readable is False
    assert report.refusals and "nothing is assumed" in report.refusals[0]
    slot = report.per_channel.seconds if hwnd == 1025 else report.per_channel.profiles
    assert slot.value is None
    assert slot.text == ""
    assert slot.unknown is not None


@pytest.mark.parametrize("text", ["nan", "inf", "-inf"])
def test_nonfinite_seconds_remain_unknown(text):
    report = _read(SETTINGS_ROWS, texts={1025: text})
    assert not report.readable
    assert report.per_channel.seconds.text == text
    assert report.per_channel.seconds.value is None
    assert report.per_channel.seconds.unknown is not None


@pytest.mark.parametrize("text", ["--1", "²"])
def test_malformed_integer_is_a_named_refusal(text):
    report = _read(SETTINGS_ROWS, texts={1018: text})
    assert not report.readable
    assert report.repeat.text == text
    assert report.repeat.value is None


def test_an_unparseable_amount_is_a_refusal() -> None:
    report = _read(SETTINGS_ROWS, texts={1018: "many"})
    assert report.readable is False
    assert report.repeat.value is None
    assert any("repeat" in refusal for refusal in report.refusals)


def test_no_popup_is_absent_and_the_command_never_opens_one() -> None:
    band = (
        (2000, WINDOW, "TSp_Panel", (0, 0, 900, 24), ""),
        (2001, 2000, "TSp_Button", (0, 0, 60, 24), ""),
    )
    report = _read(band)
    assert report.surface is ChannelsSurface.ABSENT
    assert report.readable is False
    assert any("never opens one" in refusal for refusal in report.refusals)
    assert report.repeat is None and report.per_channel is None


def test_a_hidden_popup_panel_is_not_a_popup() -> None:
    # presence is not visibility: the panel is in the tree and shows nothing
    report = _read(SETTINGS_ROWS, hidden=(1000,))
    assert report.surface is ChannelsSurface.ABSENT


def test_a_hidden_strip_cell_is_not_a_cell() -> None:
    report = _read(SETTINGS_ROWS, hidden=(1030,))
    assert report.surface is ChannelsSurface.CHANGED_STRUCTURE
    assert report.readable is False
    assert "measured settings popup" in report.refusals[0]


def test_two_popups_are_ambiguous_and_nothing_is_picked() -> None:
    duplicate = tuple(
        (hwnd + 500, WINDOW if parent == WINDOW else parent + 500, cls, rect, text)
        for hwnd, parent, cls, rect, text in SETTINGS_ROWS
    )
    report = _read(SETTINGS_ROWS + duplicate)
    assert report.surface is ChannelsSurface.AMBIGUOUS
    assert report.readable is False
    assert "a pick would be a guess" in report.refusals[0]


def test_a_dialog_in_front_is_the_wrong_surface() -> None:
    report = _read(SETTINGS_ROWS, value_dialogs=(1000,))
    assert report.surface is ChannelsSurface.WRONG_SURFACE
    assert report.readable is False
    assert "cannot be read over it" in report.refusals[0]


def test_a_changed_band_order_is_refused_by_signature() -> None:
    reordered = tuple(
        (hwnd, parent, cls, (0, 100, 106, 124) if hwnd == 1017 else rect, text)
        if hwnd == 1017
        else (hwnd, parent, cls, rect, text)
        for hwnd, parent, cls, rect, text in SETTINGS_ROWS
    )
    report = _read(reordered)
    assert report.surface is ChannelsSurface.CHANGED_STRUCTURE
    assert report.signature != SETTINGS_SIGNATURE
    assert report.repeat is None and report.per_channel is None


# ---------------------------------------------------------------------------------------------
# the multiplexer-on entry: read, distinguished, and bound to nothing
# ---------------------------------------------------------------------------------------------


def test_the_clipped_popup_reads_as_one_entry_and_binds_no_action() -> None:
    report = _read(ENTRY_ROWS)
    assert report.surface is ChannelsSurface.MULTIPLEXER_ON_ENTRY
    assert report.readable is True
    assert report.refusals == ()
    assert report.entry.action_bound is False
    assert report.entry.state == "UNKNOWN"
    # the furniture is declared in the tree but clipped out of the panel: nothing is read from it
    assert report.repeat is None
    assert report.per_channel is None
    assert report.channel_ticks == ()
    assert any("not shown" in note for note in report.uncertainties)


def test_the_settings_reader_is_not_used_for_the_entry_surface() -> None:
    entry = _read(ENTRY_ROWS)
    settings = _read(SETTINGS_ROWS)
    assert entry.signature != settings.signature
    assert entry.surface is not settings.surface


# ---------------------------------------------------------------------------------------------
# the public CLI: one read, and no gesture surface at all
# ---------------------------------------------------------------------------------------------


class NoGestureActuator:
    """A double whose only reachable members are the read and the map that read published.

    Every other attribute — ``press``, ``hover``, ``commit``, ``_set_text_commit``,
    ``_move_real_cursor`` and anything not invented yet — raises on access, so the test fails on
    the *attempt* rather than on an effect nobody can see. ``kwargs`` is kept so a test can prove
    the real constructor was asked to refuse real input.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.args = args

    def bind_target(self, hwnd):
        assert hwnd == WINDOW
        return WindowTarget(
            hwnd=WINDOW, thread_id=12, process_id=34, class_name="TMain_Scr"
        )

    def verify_bound_target(self, target):
        assert target.hwnd == WINDOW
        return target

    def _get_text(self, hwnd):
        row = next(row for row in _roles(SETTINGS_ROWS)["raw"] if row["hwnd"] == hwnd)
        assert row["cls"] in {"Edit", "TSp_Edit"}
        return row["text"]

    def screen_fingerprint(self) -> SimpleNamespace:
        return SimpleNamespace(hwnd=WINDOW)

    @property
    def last_roles(self) -> dict:
        return _roles(SETTINGS_ROWS)

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"the read path reached {name!r} on the actuator; channels-read has no gesture"
        )


@pytest.fixture(autouse=True)
def one_visible_window(monkeypatch):
    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: (WINDOW,))


def test_live_query_supplies_values_missing_from_cross_process_tree():
    class EmptyTextTree(NoGestureActuator):
        @property
        def last_roles(self):
            roles = _roles(SETTINGS_ROWS)
            roles["raw"] = [{**row, "text": ""} for row in roles["raw"]]
            return roles

    report = channels_read.read_channels(EmptyTextTree())
    assert report.readable
    assert report.repeat.text == "1"
    assert report.per_channel.profiles.text == "7"
    assert report.per_channel.seconds.text == "0.28"


@pytest.mark.parametrize("windows", [(), (WINDOW, WINDOW + 1)])
def test_window_count_refuses_before_constructing_a_driver(monkeypatch, windows):
    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: windows)

    def forbidden(**kwargs):
        raise AssertionError("driver must not be constructed")

    monkeypatch.setattr(channels_read, "Win32Actuator", forbidden)
    with pytest.raises(channels_read.ChannelsReadUnavailable, match="exactly one"):
        channels_read.read_channels()


def test_read_channels_constructs_the_driver_with_real_input_refused(
    monkeypatch,
) -> None:
    seen: dict = {}

    def factory(*args: object, **kwargs: object) -> NoGestureActuator:
        seen.update(kwargs)
        return NoGestureActuator(**kwargs)

    monkeypatch.setattr(channels_read, "Win32Actuator", factory)
    channels_read.read_channels()
    assert seen == {"allow_real_input": False}


def test_the_cli_reads_the_popup_through_json_and_touches_nothing(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(channels_read, "Win32Actuator", NoGestureActuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["channels-read", "--json"])
    assert exit_info.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["surface"] == "settings_popup"
    assert report["readable"] is True
    assert report["setup_verified"] is False
    assert report["refusals"] == []
    assert report["repeat"]["text"] == "1"
    assert report["per_channel"]["seconds"]["value"] == 0.28
    assert {cell["state"] for cell in report["channel_ticks"]} == {"UNKNOWN"}


def test_the_cli_exits_two_on_an_unreadable_screen_and_says_why(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(channels_read, "Win32Actuator", NoGestureActuator)
    monkeypatch.setattr(
        NoGestureActuator, "last_roles", property(lambda self: _roles(()))
    )
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["channels-read", "--json"])
    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["surface"] == "absent"
    assert "never opens one" in captured.err
