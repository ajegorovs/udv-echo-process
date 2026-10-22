"""The guarded top-row channel selection: offline, real workflow, Win32 double only.

The popup shape is the same projected, de-identified 8-band settings shape the read-only
reader's replay and the two numeric writers use (handles renumbered, translated): no capture is
read and no instrument is touched. The double replaces only the Win32 layer and counts every
press, so "one press" and "zero presses" are measurements rather than claims.

What these tests hold:

1. the target is the **top radio row's** cell for the ordinal, never the lower ``Use channels``
   tick row's cell at the same ordinal, and never a coordinate — including at the action
   boundary, which re-reads the bound popup through the reader instead of trusting ancestry,
   panel class or a ten-cell count (the tick row has all three);
2. a strip set that cannot separate the two rows (missing, partial, duplicated or shared
   handles) refuses with zero presses;
3. malformed channels, a wrong declared start channel, a missing mode declaration and an
   existing record refuse with zero presses;
4. exactly one press, on the cell's own handle, with a fresh preflight before it;
5. the selection stays ``UNKNOWN`` and ``native_proof`` is ``False``; an operator's visual
   observation is recorded separately and never becomes the command's evidence;
6. the obligation exists on disk **before** the press, and it names the declared original;
7. an expected post-press profile change is reported as a moved fact, not an error, and is
   never repaired or retried;
8. a declaration that already names the target presses nothing and writes no record.
9. the reported evidence claims no more than the run established: the owed restoration names the
   gesture and its possible takers (a second supervised invocation took it live), and
   ``press_evidence`` describes an attempt while ``posted`` stays ``unknown``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from udv_echo_process.acquire import channels_read, channels_select
from udv_echo_process.acquire.actuator import StripState, WindowTarget
from udv_echo_process.acquire.channels_select import (
    SELECTABLE_CHANNELS,
    SelectStage,
    acquire_select_channel,
)
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.cli import acquire_main

WINDOW = 9000

#: The settings popup — the same projected shape the repeat/profiles tests use. Two ten-cell
#: strips: 1029 (beside the ``Use only channel`` toggle at 1003, its cells 1030..1039 — the radio
#: row this command presses) and 1006 (the standalone ``Use channels`` tick row, cells 1007..1016).
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

#: The **top radio row** (panel 1029, the strip beside the ``Use only channel`` toggle), left →
#: right. The reader's ``use_only_channel`` attribution is the authority here, not the y order a
#: test author might guess: this is the row the command presses.
TOP_ROW_BY_ORDINAL = {1: 1039, 2: 1038, 3: 1037, 10: 1030}
#: The lower ``Use channels`` tick row (panel 1006) — a different control, never the target.
LOWER_ROW_BY_ORDINAL = {1: 1016, 2: 1015, 3: 1014, 10: 1007}
START_EDIT = 1022
PROFILES_EDIT = 1027

#: The same popup **clipped to one entry** while the multiplexer is on: the panel holds one row,
#: and the two strip panels and the value button are reported hidden — the reader's
#: ``MULTIPLEXER_ON_ENTRY`` surface, where no channel row is bound at all.
MPX_ROWS: tuple[tuple, ...] = tuple(
    (
        hwnd,
        parent,
        cls,
        (0, 0, 158, 43) if hwnd == 1000 else rect,
        text,
        hwnd not in {1028, 1029},
    )
    for hwnd, parent, cls, rect, text in SETTINGS_ROWS
)


def _roles(rows: tuple[tuple, ...], texts: dict[int, str]) -> dict:
    raw: list[dict] = []
    parent_of: dict[int, int] = {}
    for row in rows:
        hwnd, parent, cls, rect, text = row[:5]
        visible = row[5] if len(row) > 5 else True
        left, top, right, bottom = rect
        raw.append(
            {
                "hwnd": hwnd,
                "cls": cls,
                "text": texts.get(hwnd, text),
                "rect": (left, top, right, bottom),
                "left": left,
                "top": top,
                "w": right - left,
                "h": bottom - top,
                "id": hwnd % 977,
                "visible": visible,
            }
        )
        parent_of[hwnd] = parent
    panels = tuple(
        row
        for row in raw
        if row["cls"] in {"TSp_Panel", "TPanel"} and parent_of[row["hwnd"]] == WINDOW
    )
    return {
        "window": WINDOW,
        "raw": raw,
        "parent_of": parent_of,
        "panels": panels,
        "value_dialogs": (),
    }


class FakeSelectActuator:
    """The Win32 surface only: a role map, a text reader, a strip reading, and one press."""

    def __init__(
        self,
        *,
        rows: tuple[tuple, ...] | None = SETTINGS_ROWS,
        texts: dict[int, str] | None = None,
        strip: StripState | None = None,
        overlay=None,
        on_press=None,
        press_error: Exception | None = None,
        close_after_press: bool = False,
    ) -> None:
        self.rows = rows
        self.texts = dict(texts or {})
        self.strip = strip or StripState(button_count=3)
        self.overlay = overlay
        self.on_press = on_press
        self.press_error = press_error
        self.close_after_press = close_after_press
        self.binds = 0
        self.reads = 0
        self.presses: list[int] = []
        self.warnings: list[str] = []
        self._target: WindowTarget | None = None

    def bind_target(self, hwnd: int) -> WindowTarget:
        self.binds += 1
        self._target = WindowTarget(
            hwnd=int(hwnd), thread_id=11, process_id=22, class_name="TMain_Scr"
        )
        return self._target

    def verify_bound_target(self, target: WindowTarget) -> WindowTarget:
        assert self._target == target, "the workflow rebound or lost its target"
        return target

    def screen_fingerprint(self) -> SimpleNamespace:
        return SimpleNamespace(hwnd=WINDOW)

    @property
    def last_roles(self) -> dict:
        self.reads += 1
        if self.rows is None:
            return _roles((), self.texts)
        return _roles(self.rows, self.texts)

    def _get_text(self, hwnd: int) -> str:
        row = next(
            row
            for row in _roles(self.rows or (), self.texts)["raw"]
            if row["hwnd"] == hwnd
        )
        return row["text"]

    def window_caption(self) -> str:
        return "UDOP DOP3010.43"

    def peek_overlay(self):
        return self.overlay

    def strip_state(self) -> StripState:
        return self.strip

    def press_channel_cell(
        self,
        *,
        target: WindowTarget,
        popup_hwnd: int,
        row_hwnd: int,
        cell_hwnd: int,
        ordinal: int,
    ) -> None:
        assert self._target == target, (
            "the press was asked for a window this surface lost"
        )
        assert popup_hwnd == 1000 and row_hwnd == 1029
        assert ordinal in {1, 2, 3, 10}
        if self.on_press is not None:
            self.on_press(self)
        if self.press_error is not None:
            raise self.press_error
        self.presses.append(int(cell_hwnd))
        if self.close_after_press:
            self.rows = None

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"the select command reached {name!r}: it presses one radio cell and "
            "touches nothing else"
        )


@pytest.fixture(autouse=True)
def one_window(monkeypatch):
    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: (WINDOW,))
    monkeypatch.setattr(
        channels_select, "visible_main_windows", lambda *args: (WINDOW,)
    )


def _run(tmp_path, actuator=None, **kwargs):
    params = {
        "expect_channel": 1,
        "channel": 2,
        "expect_start_channel": 1,
        "mpx_disabled": True,
        "trial_record": tmp_path / "trial.json",
        "actuator": actuator or FakeSelectActuator(),
        "restore_channel": 1,
        "enumerate_windows": lambda: (WINDOW,),
    }
    params.update(kwargs)
    return acquire_select_channel(**params)


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# 1-2. the top row, and only the top row
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("channel", [1, 2, 10])
def test_press_lands_on_the_top_radio_row_cell_for_the_ordinal(tmp_path, channel):
    live = FakeSelectActuator()
    result = _run(
        tmp_path,
        live,
        channel=channel,
        expect_channel=1 if channel != 1 else 10,
    )
    assert result.presses == 1
    assert live.presses == [TOP_ROW_BY_ORDINAL[channel]]
    assert result.target_strip == "use_only_channel"
    assert result.target_ordinal == channel
    assert TOP_ROW_BY_ORDINAL[channel] != LOWER_ROW_BY_ORDINAL[channel]
    assert "Use only channel" in result.target_attribution


def test_a_missing_top_row_refuses_before_any_ordinal_is_interpreted(tmp_path):
    """Without the radio row the band signature is not the measured one — refuse, don't guess."""
    rows = tuple(row for row in SETTINGS_ROWS if row[1] != 1029)
    live = FakeSelectActuator(rows=rows)
    with pytest.raises(AcquisitionError, match="settings surface|strips"):
        _run(tmp_path, live)
    assert live.presses == []


def test_a_partial_top_row_refuses_with_zero_presses(tmp_path):
    rows = tuple(row for row in SETTINGS_ROWS if row[0] != 1031)
    live = FakeSelectActuator(rows=rows)
    with pytest.raises(AcquisitionError, match="settings surface|strips|ordinals"):
        _run(tmp_path, live)
    assert live.presses == []


# ---------------------------------------------------------------------------------------------
# 3. refusals, all with zero presses
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, 3, 11, True, "2"])
def test_an_unsupported_or_malformed_channel_refuses(tmp_path, bad):
    live = FakeSelectActuator()
    with pytest.raises(AcquisitionError):
        _run(tmp_path, live, channel=bad)
    assert live.presses == []
    assert not (tmp_path / "trial.json").exists()


def test_a_wrong_declared_start_channel_refuses(tmp_path):
    live = FakeSelectActuator()
    with pytest.raises(AcquisitionError, match="start channel"):
        _run(tmp_path, live, expect_start_channel=2)
    assert live.presses == []


def test_a_missing_multiplexer_declaration_refuses(tmp_path):
    live = FakeSelectActuator()
    with pytest.raises(AcquisitionError, match="mpx-disabled"):
        _run(tmp_path, live, mpx_disabled=False)
    assert live.presses == []


def test_an_existing_trial_record_is_never_overwritten(tmp_path):
    (tmp_path / "trial.json").write_text("{}", encoding="utf-8")
    live = FakeSelectActuator()
    with pytest.raises(AcquisitionError, match="already exists"):
        _run(tmp_path, live)
    assert live.presses == []


def test_a_missing_popup_refuses_with_zero_presses(tmp_path):
    live = FakeSelectActuator(rows=None)
    with pytest.raises(AcquisitionError):
        _run(tmp_path, live)
    assert live.presses == []


# ---------------------------------------------------------------------------------------------
# 4-6. one press, no proof of a selection, the obligation first
# ---------------------------------------------------------------------------------------------


def test_the_obligation_is_on_disk_before_the_press_and_names_the_original(tmp_path):
    seen: list[dict] = []
    trial = tmp_path / "trial.json"

    def before_press(_live):
        seen.append(json.loads(trial.read_text(encoding="utf-8")))

    result = _run(
        tmp_path,
        FakeSelectActuator(on_press=before_press),
        expect_channel=1,
        channel=2,
    )
    assert seen and seen[0]["phase"] == "obligation"
    assert seen[0]["restore_to"] == 1
    assert seen[0]["presses"] == 0
    record = _record(tmp_path)
    assert record["phase"] == "after"
    assert record["restore_to"] == 1
    assert record["selection"] == "UNKNOWN"
    assert result.restoration_owed  # the declared original is owed back


def test_the_owed_restoration_names_the_gesture_and_never_an_executor(tmp_path):
    """E: the automation itself can take the restore — the accepted 1 -> 2 -> 1 trial did."""
    result = _run(tmp_path, FakeSelectActuator())
    (owed,) = result.restoration_owed
    assert owed.startswith("select channel 1 again on the top radio row")
    # The trial's restore was a second supervised invocation, not a hand gesture.
    assert "by hand" not in owed
    assert "supervised invocation" in owed
    assert result.restoration_owed == tuple(_record(tmp_path)["restoration_owed"])


def test_the_press_evidence_never_claims_a_post(tmp_path):
    """E: ``posted`` is unknown, so no evidence field may state that a message was delivered."""
    result = _run(tmp_path, FakeSelectActuator())
    assert result.press == "attempted"
    assert result.posted == "unknown"
    assert "one posted held press" not in result.press_evidence
    assert "unknown" in result.press_evidence
    assert _record(tmp_path)["press_evidence"] == result.press_evidence


def test_an_explicit_restore_target_is_the_trial_original(tmp_path):
    result = _run(
        tmp_path,
        FakeSelectActuator(),
        expect_channel=10,
        channel=1,
        restore_channel=10,
    )
    assert result.restore_to == 10
    assert _record(tmp_path)["restore_to"] == 10


def test_the_selection_stays_unknown_and_visual_corroboration_is_not_proof(tmp_path):
    result = _run(
        tmp_path,
        FakeSelectActuator(),
        visual_corroboration="operator: channel 2 is circled",
    )
    assert result.selection == "UNKNOWN"
    assert result.native_proof is False
    assert result.persisted == "unknown"
    assert result.visual_corroboration == "operator: channel 2 is circled"
    assert "paint" in result.selection_evidence


def test_exactly_one_press_on_a_raising_primitive_is_reported_not_retried(tmp_path):
    live = FakeSelectActuator(press_error=OSError("post refused"))
    result = _run(tmp_path, live)
    assert result.presses == 1
    assert live.presses == []  # the double raised before recording; nothing was retried
    assert result.selection == "UNKNOWN"
    assert any("press raised" in note for note in result.notes)


# ---------------------------------------------------------------------------------------------
# 7-8. expected post-state change, and the declared no-op
# ---------------------------------------------------------------------------------------------


def test_a_channel_profile_change_after_the_press_is_a_fact_not_an_error(tmp_path):
    live = FakeSelectActuator()

    def change_profiles(_live):
        live.texts[PROFILES_EDIT] = "50"  # the new channel's own profile count

    live.on_press = change_profiles
    result = _run(tmp_path, live)
    assert result.stage is SelectStage.PRESSED
    assert result.presses == 1
    assert any("profiles" in move for move in result.facts_moved)
    assert _record(tmp_path)["facts_after"]["profiles"] == "50"


def test_a_declaration_already_on_the_target_presses_nothing(tmp_path):
    result = _run(tmp_path, FakeSelectActuator(), expect_channel=2, channel=2)
    assert result.stage is SelectStage.NO_OP
    assert result.presses == 0
    assert result.persisted == "not_pressed"
    assert not (tmp_path / "trial.json").exists()


def test_the_cli_refuses_and_exits_nonzero_without_pressing(tmp_path):
    with pytest.raises(SystemExit) as caught:
        acquire_main(
            [
                "channels-select",
                "--expect-channel",
                "1",
                "--channel",
                "3",
                "--expect-start-channel",
                "1",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path / "trial.json"),
            ]
        )
    assert caught.value.code != 0
    assert not (tmp_path / "trial.json").exists()


def test_the_supported_channels_are_the_measured_subset():
    assert SELECTABLE_CHANNELS == (1, 2, 10)


# ---------------------------------------------------------------------------------------------
# regressions for the review blockers
# ---------------------------------------------------------------------------------------------


def test_the_recording_surface_states_no_bare_press_handle_facade():
    """B1: no public "press any HWND" entry point — only the target-bound cell helper."""
    from udv_echo_process.acquire.udop.recording import RecordingSurface

    assert not hasattr(RecordingSurface, "press_cell")
    assert hasattr(RecordingSurface, "press_channel_cell")


def _boundary(
    recording,
    target,
    *,
    rows=SETTINGS_ROWS,
    classes=None,
    parents=None,
    texts=None,
    verify=None,
):
    """Call the real action boundary with the Win32 mechanics stubbed out.

    The boundary asks the **reader** which strip a panel is, so the double publishes the same
    driver-shaped role map a live screen does: ``last_roles`` and a fingerprint that agree on the
    window, and the production resolver runs underneath. Only the raw class/parent lookups and
    ``GetWindowText`` are stood in for — nothing about either strip is re-described here.
    """
    texts = dict(texts or {})
    roles = _roles(rows, texts)
    class_map = {row[0]: row[2] for row in rows}
    parent_map = {**roles["parent_of"], **(parents or {})}
    class_map.update(classes or {})
    recording._class_of = lambda hwnd: class_map.get(hwnd, "")
    recording._parent_of = lambda hwnd: parent_map.get(hwnd)
    by_hwnd = {row["hwnd"]: row["text"] for row in roles["raw"]}

    class Surface:
        _target = target
        pressed: ClassVar[list[int]] = []
        verify_calls = 0

        @property
        def last_roles(self):
            return roles

        def screen_fingerprint(self):
            return SimpleNamespace(hwnd=WINDOW)

        def verify_bound_target(self, asked):
            assert asked == target, "the workflow rebound or lost its target"
            Surface.verify_calls += 1
            if verify is not None:
                verify(Surface.verify_calls)
            return asked

        def _get_text(self, hwnd):
            return texts.get(hwnd, by_hwnd.get(hwnd, ""))

        def _main_hwnd(self):
            return target.hwnd

        def _click_hold(self, hwnd):
            self.pressed.append(hwnd)

    return Surface()


def test_the_action_boundary_refuses_a_foreign_popup_row_or_cell(monkeypatch):
    """B1: descent, class, owning popup and ordinal are re-established at the press."""
    from udv_echo_process.acquire import udop as udop_pkg
    from udv_echo_process.acquire.udop import recording

    target = WindowTarget(
        hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr"
    )
    base: dict = {}

    # the accepted path: one held press on the top radio row's cell
    surface = _boundary(recording, target, **base)
    assert isinstance(udop_pkg.AcquisitionError, type)
    recording.RecordingSurface.press_channel_cell(
        surface,
        target=target,
        popup_hwnd=1000,
        row_hwnd=1029,
        cell_hwnd=1039,
        ordinal=1,
    )
    assert surface.pressed == [1039]
    # the binding was verified around the reader's queries, before and after them
    assert surface.verify_calls == 2

    # a cell that does not hang off the row
    surface = _boundary(recording, target, parents={1039: 1000})
    with pytest.raises(AcquisitionError, match="does not hang off the row"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=1039,
            ordinal=1,
        )
    assert surface.pressed == []

    # a popup that is not this window's child
    surface = _boundary(recording, target, parents={1029: 4242})
    with pytest.raises(AcquisitionError, match="does not hang off the popup"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=1039,
            ordinal=1,
        )
    assert surface.pressed == []

    # a handle of the wrong class
    surface = _boundary(recording, target, classes={1039: "Edit"})
    with pytest.raises(AcquisitionError, match="not a TSp_Button cell"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=1039,
            ordinal=1,
        )
    assert surface.pressed == []

    # an ordinal the reader no longer places this cell at
    surface = _boundary(recording, target)
    with pytest.raises(AcquisitionError, match="ordinal"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=1039,
            ordinal=10,
        )
    assert surface.pressed == []


def test_the_action_boundary_tells_the_two_ten_cell_rows_apart(monkeypatch):
    """The lower ``Use channels`` row has the *same* ancestry and ten cells of its own.

    Ancestry, panel class and cell class are therefore not row identity: the boundary re-reads
    the bound popup through the owning resolver and requires the panel the reader attributes to
    ``use_only_channel`` — the row beside the ``Use only channel`` toggle — plus that row's own
    ordinal. Handed the tick row and one of its cells, it posts nothing.
    """
    from udv_echo_process.acquire.udop import recording

    target = WindowTarget(
        hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr"
    )

    # the lower row, passed directly: every structural check above passes, the reader's answer
    # does not — and nothing is posted
    surface = _boundary(recording, target)
    with pytest.raises(AcquisitionError, match="use_only_channel"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1006,
            cell_hwnd=LOWER_ROW_BY_ORDINAL[2],
            ordinal=2,
        )
    assert surface.pressed == []

    # the top row, same call shape: one held press on the cell the reader places there
    surface = _boundary(recording, target)
    recording.RecordingSurface.press_channel_cell(
        surface,
        target=target,
        popup_hwnd=1000,
        row_hwnd=1029,
        cell_hwnd=TOP_ROW_BY_ORDINAL[2],
        ordinal=2,
    )
    assert surface.pressed == [TOP_ROW_BY_ORDINAL[2]]

    # the top row with a cell of the tick row: refused on descent, still zero presses
    surface = _boundary(recording, target)
    with pytest.raises(AcquisitionError, match="does not hang off the row"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=LOWER_ROW_BY_ORDINAL[2],
            ordinal=2,
        )
    assert surface.pressed == []

    # the multiplexer-on, one-entry surface: no radio row is bound there at all
    surface = _boundary(recording, target, rows=MPX_ROWS)
    with pytest.raises(AcquisitionError, match="full settings surface"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=1039,
            ordinal=1,
        )
    assert surface.pressed == []

    # the binding is re-verified around the reader's queries: a window that moved between them
    # refuses, and no message is posted
    def moved(calls: int) -> None:
        if calls == 2:
            raise AcquisitionError("the bound window moved under the read")

    surface = _boundary(recording, target, verify=moved)
    with pytest.raises(AcquisitionError, match="moved under the read"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=target,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=1039,
            ordinal=1,
        )
    assert surface.pressed == []


def test_the_bound_target_must_be_the_surfaces_own_binding():
    from udv_echo_process.acquire.udop import recording

    bound = WindowTarget(
        hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr"
    )
    other = WindowTarget(hwnd=4242, thread_id=11, process_id=22, class_name="TMain_Scr")
    surface = _boundary_for_binding(recording, bound)
    with pytest.raises(AcquisitionError, match="not bound to"):
        recording.RecordingSurface.press_channel_cell(
            surface,
            target=other,
            popup_hwnd=1000,
            row_hwnd=1029,
            cell_hwnd=1039,
            ordinal=10,
        )
    assert surface.pressed == []


def _boundary_for_binding(recording, target):
    class Surface:
        _target = target
        pressed: ClassVar[list[int]] = []

        def _main_hwnd(self):
            return target.hwnd

        def _click_hold(self, hwnd):
            self.pressed.append(hwnd)

    return Surface()


@pytest.mark.parametrize(
    "defect",
    ["split_row", "duplicate_left", "overlap", "cell_without_handle"],
)
def test_a_strip_whose_geometry_is_not_one_row_is_refused_with_zero_presses(
    tmp_path, defect
):
    """Medium: the reader owns the row's band/geometry, and a defect is not a row."""
    rows = list(SETTINGS_ROWS)
    if defect == "split_row":
        rows = [
            (h, p_, c, (r[0], r[1] + 60, r[2], r[3] + 60), t)
            if h == 1035
            else (h, p_, c, r, t)
            for (h, p_, c, r, t) in rows
        ]
    elif defect == "duplicate_left":
        rows = [
            (h, p_, c, (r[0] + 19, r[1], r[2] + 19, r[3]), t)
            if h == 1034
            else (h, p_, c, r, t)
            for (h, p_, c, r, t) in rows
        ]
    elif defect == "overlap":
        rows = [
            (h, p_, c, (r[0] + 14, r[1], r[2] + 14, r[3]), t)
            if h == 1034
            else (h, p_, c, r, t)
            for (h, p_, c, r, t) in rows
        ]
    else:
        rows = [(h, None if h == 1035 else p_, c, r, t) for (h, p_, c, r, t) in rows]
    live = FakeSelectActuator(rows=tuple(rows))
    with pytest.raises(AcquisitionError):
        _run(tmp_path, live)
    assert live.presses == []
    assert not (tmp_path / "trial.json").exists()


def test_the_reader_refuses_a_handle_shared_between_the_two_strips():
    """Medium: the alias clause is the reader's, so no consumer has to re-derive it."""
    from udv_echo_process.acquire.ui import channels as ui_channels
    from udv_echo_process.acquire.ui.model import UiNode

    def node(hwnd, cls, rect):
        left, top, right, bottom = rect
        return UiNode.from_row(
            {
                "hwnd": hwnd,
                "cls": cls,
                "text": "",
                "rect": (left, top, right, bottom),
                "left": left,
                "top": top,
                "w": right - left,
                "h": bottom - top,
                "id": hwnd % 977,
                "visible": True,
            }
        )

    top_rows = [row for row in SETTINGS_ROWS if row[1] == 1029]
    lower_rows = [row for row in SETTINGS_ROWS if row[1] == 1006]
    # One handle sits in **both** rows: the radio cell 1039 is also a tick-row cell.
    shared = [
        (1039 if hwnd == 1007 else hwnd, cls, rect)
        for hwnd, _p, cls, rect, _t in lower_rows
    ]

    popup = node(1000, "TSp_Panel", (0, 0, 393, 426))
    top = node(1029, "TPanel", (154, 7, 377, 47))
    lower = node(1006, "TPanel", (159, 110, 382, 149))
    toggle = node(1003, "TSp_Button", (10, 3, 132, 33))

    class Tree:
        def children(self, panel):
            if panel.hwnd == 1029:
                return tuple(node(h, c, r) for h, _p, c, r, _t in top_rows)
            if panel.hwnd == 1006:
                return tuple(node(h, c, r) for h, c, r in shared)
            return (toggle, top, lower)

    report = ui_channels._settings(
        Tree(), popup, (toggle, top, lower), ui_channels.SETTINGS_SIGNATURE
    )
    assert report.readable is False
    assert any("share handles" in refusal for refusal in report.refusals)


def test_a_raising_press_is_an_attempt_never_a_post_and_the_cli_exits_nonzero(tmp_path):
    live = FakeSelectActuator(press_error=OSError("post refused"))
    result = _run(tmp_path, live)
    assert result.stage is SelectStage.PRESS_RAISED
    assert result.presses == 1
    assert result.press == "attempted"
    assert result.posted == "unknown"
    assert result.selection == "UNKNOWN"
    record = _record(tmp_path)
    assert record["stage"] == "press_raised"
    assert record["posted"] == "unknown"
    assert record["press"] == "attempted"

    (tmp_path / "trial.json").unlink()
    with pytest.raises(SystemExit) as caught:
        acquire_main(
            [
                "channels-select",
                "--expect-channel",
                "1",
                "--channel",
                "2",
                "--expect-start-channel",
                "1",
                "--restore-channel",
                "1",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path / "cli-trial.json"),
            ]
        )
    assert caught.value.code != 0


def test_the_obligation_records_the_whole_target_and_is_claimed_last(tmp_path):
    """B2: full target/popup/row/cell/ordinal + before facts; no record on a pre-action refusal."""
    seen: list[dict] = []
    trial = tmp_path / "trial.json"

    def before_press(_live):
        seen.append(json.loads(trial.read_text(encoding="utf-8")))

    _run(tmp_path, FakeSelectActuator(on_press=before_press))
    assert seen
    obligation = seen[0]
    assert obligation["bound_target"]["hwnd"] == WINDOW
    assert obligation["bound_target"]["class_name"] == "TMain_Scr"
    assert obligation["popup_hwnd"] == 1000
    assert obligation["row_hwnd"] == 1029
    assert obligation["cell_hwnd"] == 1038
    assert obligation["target_ordinal"] == 2
    assert obligation["facts_before"]["profiles"] == "7"
    assert obligation["presses"] == 0
    assert obligation["posted"] == "not_attempted"
    record = _record(tmp_path)
    assert record["facts_unreadable"] == []
    assert record["facts_after"]["profiles"] == "7"


def test_a_refusal_between_the_read_and_the_press_leaves_no_obligation(tmp_path):
    """B2: the record is claimed after the fresh preflight, so a refusal wrote nothing."""
    trial = tmp_path / "trial.json"

    class VanishingLive(FakeSelectActuator):
        reads = 0

        @property
        def last_roles(self):
            self.reads += 1
            if self.reads > 1:
                return _roles((), self.texts)  # the popup closed under the read
            return _roles(self.rows, self.texts)

    live = VanishingLive()
    with pytest.raises(AcquisitionError):
        _run(tmp_path, live)
    assert live.presses == []
    assert not trial.exists()


def test_a_closed_popup_after_the_press_is_reported_and_the_facts_are_unknown(tmp_path):
    live = FakeSelectActuator(close_after_press=True)
    result = _run(tmp_path, live)
    assert result.stage is SelectStage.PRESSED
    assert result.presses == 1
    assert result.post_error
    assert result.new_facts == {}
    assert (
        result.facts_unreadable
    )  # what the earlier read stated is unknown, never "gone"
    record = _record(tmp_path)
    assert record["post_error"]
    assert record["facts_after"] == {}
    assert record["facts_unreadable"]


def test_a_declaration_may_name_any_channel_but_the_press_target_may_not(tmp_path):
    """B4: declarations are 1..10; only 1, 2 and 10 are pressable."""
    live = FakeSelectActuator()
    result = _run(tmp_path, live, expect_channel=3, channel=2, restore_channel=3)
    assert result.expect_channel == 3
    assert result.restore_to == 3
    assert result.presses == 1

    for bad in (0, 11, True, "2"):
        live = FakeSelectActuator()
        with pytest.raises(AcquisitionError):
            _run(tmp_path, live, channel=bad, trial_record=tmp_path / f"bad-{bad}.json")
        assert live.presses == []


def test_a_restore_target_is_always_the_declared_original(tmp_path):
    """B4: 2 -> 1 with the trial's original declared as 1 owes nothing back."""
    result = _run(
        tmp_path, FakeSelectActuator(), expect_channel=2, channel=1, restore_channel=1
    )
    assert result.restore_to == 1
    assert result.restore_source == "declared"
    assert result.restoration_owed == ()
    assert _record(tmp_path)["restore_to"] == 1
    assert _record(tmp_path)["restore_source"] == "declared"


def test_every_record_persists_the_before_and_after_facts(tmp_path):
    result = _run(
        tmp_path,
        FakeSelectActuator(),
        visual_corroboration="operator: channel 2 circled",
    )
    record = _record(tmp_path)
    assert record["facts_before"]["repeat"] == "1"
    assert record["facts_after"]["repeat"] == "1"
    assert record["visual_corroboration"] == "operator: channel 2 circled"
    assert result.visual_corroboration == "operator: channel 2 circled"
    assert record["obligation_open"] is True


@pytest.mark.parametrize(
    "defect", ["split_row", "duplicate_left", "overlap", "repeated_handle"]
)
def test_the_strip_owner_refuses_one_row_that_is_not_one_row(defect):
    """Medium: `strip_cells` owns the band/geometry/order rules; each defect is not a row."""
    from udv_echo_process.acquire.ui import channels as ui_channels
    from udv_echo_process.acquire.ui.model import UiNode

    def node(hwnd, rect, cls="TSp_Button"):
        left, top, right, bottom = rect
        return UiNode.from_row(
            {
                "hwnd": hwnd,
                "cls": cls,
                "text": "",
                "rect": (left, top, right, bottom),
                "left": left,
                "top": top,
                "w": right - left,
                "h": bottom - top,
                "id": hwnd % 977,
                "visible": True,
            }
        )

    base_rects = [(100 + 20 * index, 10, 115 + 20 * index, 43) for index in range(10)]
    rects = list(base_rects)
    hwnds = [2000 + index for index in range(10)]
    if defect == "split_row":
        rects[5] = (rects[5][0], 70, rects[5][2], 103)
    elif defect == "duplicate_left":
        rects[4] = (rects[3][0] + 2, 10, rects[3][0] + 17, 43)
    elif defect == "overlap":
        rects[4] = (rects[3][0] + 12, 10, rects[3][0] + 27, 43)
    else:
        hwnds[4] = hwnds[3]

    cells = tuple(node(hwnd, rect) for hwnd, rect in zip(hwnds, rects, strict=True))
    assert ui_channels.strip_cells(cells) == ()
    healthy = tuple(node(2000 + index, rect) for index, rect in enumerate(base_rects))
    assert (
        len(ui_channels.strip_cells(healthy)) == 10
    )  # the same shape, undamaged, is a row
