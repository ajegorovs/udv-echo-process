"""The guarded per-channel profiles write: offline, real workflow, Win32 double only.

The popup shape is the same projected, de-identified 8-band settings shape the read-only
reader's replay uses (handles renumbered, translated): no capture file is read and no instrument
is touched. The double replaces only the Win32 layer — the workflow, the shared reader and the
CLI are the real ones — and it counts every commit, so "zero writes" is a measurement rather
than a claim.

What these tests hold:

1. one commit, on the profiles field's own edit, whose owner is the value button the reading
   named, and nothing else is written;
2. an expected-count mismatch, a changed popup shape, a wrong declared channel, an extra window
   and a malformed argument all refuse with **zero** writes;
3. the operator's channel is a declaration, not proof: it is recorded, checked against the
   painted channels, and ``channel_verified`` stays ``False``;
4. the coupled ``seconds`` amount may legitimately move (reported, still exit 0), while a
   ``repeat`` movement is reported and exits 1, and an invalid fresh seconds amount is an
   unverified write;
5. a closed popup after the commit and a failed record update are reported honestly — one
   commit, no retry, the obligation still open, and the CLI exits 1 on the record failure;
6. the trial's original ``--baseline`` is separate from ``--expect``: a two-step forward/restore
   pair records the same baseline and never names the run's own start as the baseline.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from udv_echo_process.acquire import channels_profiles, channels_read
from udv_echo_process.acquire.actuator import StripState, WindowTarget
from udv_echo_process.acquire.channels_profiles import (
    PROFILES_TRIAL_FILE_NAME,
    ProfilesWriteStage,
    acquire_profiles,
)
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.cli import acquire_main

#: The main window of the projected shape — a synthetic handle, not a measured one.
WINDOW = 9000

#: The settings popup: (hwnd, parent, class, rect, text). The same measured shape as the
#: read-only reader's replay and the repeat writer's fixture.
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

#: The profiles slot: its own edit (1027) owned by the value button (1026).
PROFILES_EDIT = 1027
PROFILES_OWNER = 1026
#: The neighbouring coupled amount and its owner.
SECONDS_EDIT = 1025
SECONDS_OWNER = 1024
REPEAT_EDIT = 1018


def _roles(rows: tuple[tuple, ...], texts: dict[int, str]) -> dict:
    """One driver-shaped role map: ``raw`` rows, ``parent_of`` links, the window, the dialogs."""
    raw: list[dict] = []
    parent_of: dict[int, int] = {}
    for hwnd, parent, cls, rect, text in rows:
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
                "visible": True,
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


class FakePopupActuator:
    """The Win32 surface only: a role map, one text reader, one commit, one strip reading."""

    def __init__(
        self,
        *,
        rows: tuple[tuple, ...] | None = SETTINGS_ROWS,
        texts: dict[int, str] | None = None,
        strip: StripState | None = None,
        caption: str = "UDOP DOP3010.43",
        on_read=None,
        on_commit=None,
        on_caption=None,
        commit_error: Exception | None = None,
        close_after_commit: bool = False,
    ) -> None:
        self.rows = rows
        self.texts = dict(texts or {})
        self.strip = strip or StripState(button_count=3)
        self.caption = caption
        self.on_read = on_read
        self.on_commit = on_commit
        self.on_caption = on_caption
        self.commit_error = commit_error
        self.close_after_commit = close_after_commit
        self.binds = 0
        self.reads = 0
        self.captions = 0
        self.commits: list[tuple[int, str, int | None]] = []
        self.warnings: list[str] = []
        self._target: WindowTarget | None = None

    # --- binding -------------------------------------------------------------------
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

    # --- the screen ----------------------------------------------------------------
    @property
    def last_roles(self) -> dict:
        self.reads += 1
        if self.on_read is not None:
            self.on_read(self)
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
        self.captions += 1
        if self.on_caption is not None:
            self.on_caption(self)
        return self.caption

    def peek_overlay(self):
        return None

    def strip_state(self) -> StripState:
        return self.strip

    # --- the one write -------------------------------------------------------------
    def _set_text_commit(self, hwnd: int, text: str, parent: int | None = None) -> None:
        self.commits.append((hwnd, text, parent))
        if self.on_commit is not None:
            self.on_commit(self)
        if self.commit_error is not None:
            raise self.commit_error
        self.texts[hwnd] = text
        if self.close_after_commit:
            self.rows = None

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"the profiles writer reached {name!r}: it presses, hovers, toggles and records "
            "nothing"
        )


@pytest.fixture(autouse=True)
def one_window(monkeypatch):
    """Both enumerations the workflow can use see exactly the projected window."""
    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: (WINDOW,))
    monkeypatch.setattr(
        channels_profiles, "visible_main_windows", lambda *args: (WINDOW,)
    )


def _run(tmp_path, actuator=None, **kwargs):
    params = {
        "expect": 7,
        "value": 8,
        "operator_channel": 1,
        "mpx_disabled": True,
        "trial_record": tmp_path / "trial",
        "actuator": actuator or FakePopupActuator(),
        "enumerate_windows": lambda: (WINDOW,),
    }
    params.update(kwargs)
    return acquire_profiles(**params)


def _record(tmp_path, name: str = "trial") -> dict:
    return json.loads((tmp_path / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# the one write
# ---------------------------------------------------------------------------------------------


def test_writes_the_field_once_on_the_exact_edit_and_owner(tmp_path) -> None:
    actuator = FakePopupActuator()
    result = _run(tmp_path, actuator, trial_record=tmp_path)

    assert actuator.commits == [(PROFILES_EDIT, "8", PROFILES_OWNER)]
    assert result.writes == 1
    assert result.stage is ProfilesWriteStage.WRITTEN
    assert (result.old_text, result.new_text) == ("7", "8")
    assert result.new_value == 8
    assert result.other_changes == ()
    assert result.bound_target.hwnd == WINDOW
    assert result.persisted == "unknown"
    assert result.obligation_open is True
    # The record is claimed under the profiles writer's own name, never the repeat writer's.
    assert result.trial_record is not None
    assert result.trial_record.name == PROFILES_TRIAL_FILE_NAME


def test_the_operator_channel_is_a_declaration_never_a_verified_channel(
    tmp_path,
) -> None:
    result = _run(tmp_path, FakePopupActuator(), operator_channel=2)

    assert result.operator_channel == 2
    assert result.channel_verified is False
    record = _record(tmp_path)
    assert record["operator_channel"] == 2
    assert record["channel_verified"] is False
    assert "declaration, not a reading" in record["operator_channel_declaration"]
    assert "never fills per_channel.channel" in record["operator_channel_declaration"]


def test_the_seconds_amount_is_reported_and_its_recomputation_is_legitimate(
    tmp_path, monkeypatch, capsys
) -> None:
    def recompute(actuator: FakePopupActuator) -> None:
        # The application's own coupling: a new profile count comes with a new duration.
        actuator.texts[SECONDS_EDIT] = "0.32"

    actuator = FakePopupActuator(on_commit=recompute)
    monkeypatch.setattr(channels_profiles, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-profiles",
                "--expect",
                "7",
                "--value",
                "8",
                "--operator-channel",
                "1",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )
    assert exit_info.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stage"] == "written_seconds_recomputed"
    assert report["seconds_recomputed"] is True
    assert (report["old_seconds_text"], report["new_seconds_text"]) == ("0.28", "0.32")
    assert report["other_changes"] == []
    assert report["new_value"] == 8
    assert report["obligation_open"] is True
    on_disk = _record(tmp_path, PROFILES_TRIAL_FILE_NAME)
    assert (on_disk["old_seconds_text"], on_disk["new_seconds_text"]) == (
        "0.28",
        "0.32",
    )
    assert on_disk["seconds_recomputed"] is True
    assert "owed:" not in capsys.readouterr().err


def test_the_trial_obligation_exists_before_the_commit(tmp_path) -> None:
    seen: dict = {}

    def peek(_self) -> None:
        seen.update(_record(tmp_path))

    result = _run(tmp_path, FakePopupActuator(on_commit=peek), baseline=7)

    assert seen["phase"] == "obligation"
    assert (seen["expect"], seen["value"], seen["baseline"]) == (7, 8, 7)
    assert seen["restore_to"] == 7
    assert seen["edit_hwnd"] == PROFILES_EDIT
    assert seen["owner_hwnd"] == PROFILES_OWNER
    assert seen["other_facts"] == {
        "repeat": "1",
        "start_channel": "1",
        "apply_from": "1",
    }
    assert (seen["old_seconds_text"], seen["old_seconds"]) == ("0.28", 0.28)
    assert "no recording" in seen["identity_limitation"]
    after = _record(tmp_path)
    assert (after["phase"], after["stage"], after["writes"]) == ("after", "written", 1)
    assert result.trial_record_phase == "after"


# ---------------------------------------------------------------------------------------------
# no write at all
# ---------------------------------------------------------------------------------------------


def test_same_count_is_read_and_not_written(tmp_path) -> None:
    actuator = FakePopupActuator()
    result = _run(tmp_path, actuator, expect=7, value=7)

    assert actuator.commits == []
    assert result.writes == 0
    assert result.stage is ProfilesWriteStage.UNCHANGED
    assert result.persisted == "not_written"
    assert result.obligation_open is False
    assert result.restoration_owed == ()
    assert not (tmp_path / PROFILES_TRIAL_FILE_NAME).exists()


def test_an_expected_mismatch_refuses_with_zero_writes(tmp_path) -> None:
    actuator = FakePopupActuator()
    with pytest.raises(AcquisitionError, match="nothing was written"):
        _run(tmp_path, actuator, expect=8, value=9)
    assert actuator.commits == []
    assert not (tmp_path / PROFILES_TRIAL_FILE_NAME).exists()


@pytest.mark.parametrize("field, bad", [("expect", 0), ("value", -1), ("value", True)])
def test_a_bad_shape_refuses_with_zero_writes(tmp_path, field, bad) -> None:
    actuator = FakePopupActuator()
    with pytest.raises(AcquisitionError, match="positive integer"):
        _run(tmp_path, actuator, **{field: bad})
    assert (actuator.commits, actuator.reads) == ([], 0)


def test_a_wrong_operator_channel_refuses_with_zero_writes(tmp_path) -> None:
    actuator = FakePopupActuator()
    with pytest.raises(AcquisitionError, match="paints"):
        _run(tmp_path, actuator, operator_channel=11)
    assert actuator.commits == []


def test_a_class_drift_in_the_group_box_refuses_with_zero_writes(tmp_path) -> None:
    # The profiles owner stops being a value button: the measured group shape is gone, so
    # nothing is bound and no caption is trusted for another structure.
    rows = tuple(
        (row[0], row[1], "TSp_Button", *row[3:]) if row[0] == PROFILES_OWNER else row
        for row in SETTINGS_ROWS
    )
    actuator = FakePopupActuator(rows=rows)
    with pytest.raises(AcquisitionError, match="nothing was written"):
        _run(tmp_path, actuator)
    assert actuator.commits == []


def test_another_visible_window_refuses_with_zero_writes(tmp_path) -> None:
    actuator = FakePopupActuator()
    with pytest.raises(AcquisitionError, match="exactly one"):
        _run(tmp_path, actuator, enumerate_windows=lambda: (WINDOW, WINDOW + 1))
    assert actuator.commits == []


def test_a_missing_mode_declaration_refuses_before_any_enumeration(tmp_path) -> None:
    def forbidden() -> tuple[int, ...]:
        raise AssertionError(
            "the window must not be enumerated without the declaration"
        )

    with pytest.raises(AcquisitionError, match="mpx-disabled"):
        _run(tmp_path, mpx_disabled=False, enumerate_windows=forbidden)


def test_a_changed_owner_before_the_commit_refuses_with_zero_writes(tmp_path) -> None:
    def swap_owner(actuator: FakePopupActuator) -> None:
        if actuator.reads == 2:
            actuator.rows = tuple(
                row if row[0] != PROFILES_OWNER else (row[0], WINDOW, *row[2:])
                for row in SETTINGS_ROWS
            )

    actuator = FakePopupActuator(on_read=swap_owner)
    with pytest.raises(AcquisitionError, match="tree changed|nothing was written"):
        _run(tmp_path, actuator)
    assert actuator.commits == []


# ---------------------------------------------------------------------------------------------
# after the commit: observed, unknown, and no retry
# ---------------------------------------------------------------------------------------------


def test_a_popup_that_closed_after_the_write_reports_unknown_without_a_retry(
    tmp_path,
) -> None:
    actuator = FakePopupActuator(close_after_commit=True)
    result = _run(tmp_path, actuator)

    assert actuator.commits == [(PROFILES_EDIT, "8", PROFILES_OWNER)]
    assert result.stage is ProfilesWriteStage.WRITE_UNVERIFIED
    assert result.persisted == "unknown"
    assert result.writes == 1
    assert result.new_text is None
    assert "nothing was retried" in result.error
    assert result.obligation_open is True
    assert any("restore" in owed for owed in result.restoration_owed)


def test_a_commit_that_raised_is_not_reported_as_nothing_changed(tmp_path) -> None:
    actuator = FakePopupActuator(commit_error=RuntimeError("post failed"))
    result = _run(tmp_path, actuator)

    assert result.stage is ProfilesWriteStage.COMMIT_RAISED
    assert result.writes == 1
    assert result.persisted == "unknown"
    assert "not a report that nothing changed" in result.error
    assert any("may have landed" in owed for owed in result.restoration_owed)
    assert _record(tmp_path)["stage"] == "commit_raised"


def test_an_invalid_fresh_seconds_amount_is_an_unverified_write(tmp_path) -> None:
    def break_seconds(actuator: FakePopupActuator) -> None:
        actuator.texts[SECONDS_EDIT] = "0.00"

    actuator = FakePopupActuator(on_commit=break_seconds)
    result = _run(tmp_path, actuator)

    assert result.stage is ProfilesWriteStage.WRITE_UNVERIFIED
    assert result.writes == 1
    assert "valid positive amount" in result.error
    assert len(actuator.commits) == 1


def test_a_preserved_fact_that_moved_is_reported_not_repaired(tmp_path) -> None:
    def move_repeat(actuator: FakePopupActuator) -> None:
        actuator.texts[REPEAT_EDIT] = "2"

    actuator = FakePopupActuator(on_commit=move_repeat)
    result = _run(tmp_path, actuator)

    assert result.stage is ProfilesWriteStage.WRITTEN_OTHER_FACTS_CHANGED
    assert result.other_changes == ("repeat: '1' -> '2'",)
    assert result.persisted == "unknown"
    assert len(actuator.commits) == 1


# ---------------------------------------------------------------------------------------------
# the trial baseline, as two records of one trial
# ---------------------------------------------------------------------------------------------


def test_forward_and_restore_are_two_records_naming_the_same_original_baseline(
    tmp_path,
) -> None:
    forward = _run(
        tmp_path,
        FakePopupActuator(),
        expect=7,
        value=8,
        baseline=7,
        trial_record=tmp_path / "forward.json",
    )
    assert forward.stage is ProfilesWriteStage.WRITTEN
    assert forward.restored_baseline is False
    assert forward.obligation_open is True
    assert any(
        "restore the trial baseline profiles == 7" in owed
        for owed in forward.restoration_owed
    )
    before_restore = _record(tmp_path, "forward.json")
    assert (before_restore["baseline"], before_restore["restore_to"]) == (7, 7)
    assert before_restore["restore_to_source"] == "declared-trial-baseline"

    restore_actuator = FakePopupActuator(texts={PROFILES_EDIT: "8"})
    restore = _run(
        tmp_path,
        restore_actuator,
        expect=8,
        value=7,
        baseline=7,
        trial_record=tmp_path / "restore.json",
    )
    assert restore_actuator.commits == [(PROFILES_EDIT, "7", PROFILES_OWNER)]
    assert restore.stage is ProfilesWriteStage.WRITTEN
    assert restore.restored_baseline is True
    # A restore run never records its own start as the baseline, and never owes "restore 8".
    assert restore.baseline == 7
    assert restore.restore_to == 7
    assert restore.obligation_open is True
    for text in (restore.summary(), *restore.restoration_owed):
        assert "restore profiles == 8" not in text
    after_restore = _record(tmp_path, "restore.json")
    assert (after_restore["expect"], after_restore["value"]) == (8, 7)
    assert after_restore["restore_to"] == 7
    assert after_restore["restore_to_source"] == "declared-trial-baseline"
    assert after_restore["restored_baseline"] is True
    # The obligation is the operator's reopened read: this command never closes it.
    assert after_restore["obligation_open"] is True
    assert "only that read closes the obligation" in after_restore["owed_after"]


def test_an_undeclared_baseline_is_recorded_as_none_never_as_expect(tmp_path) -> None:
    result = _run(tmp_path, FakePopupActuator(), expect=7, value=8)

    record = _record(tmp_path)
    assert record["baseline"] is None
    assert record["restore_to"] == 7
    assert record["restore_to_source"] == "this-invocation"
    assert "no trial baseline was declared" in record["owed_after"]
    assert result.baseline is None
    assert result.restore_to == 7


# ---------------------------------------------------------------------------------------------
# the CLI, the record failure, and the no-real-input build
# ---------------------------------------------------------------------------------------------


def test_the_cli_exits_one_when_the_outcome_never_reached_the_trial_record(
    tmp_path, monkeypatch, capsys
) -> None:
    def fail_update(_file, _payload) -> str:
        return "the trial record could not be updated: disk full"

    monkeypatch.setattr(channels_profiles, "update_trial_record", fail_update)
    actuator = FakePopupActuator()
    monkeypatch.setattr(channels_profiles, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-profiles",
                "--expect",
                "7",
                "--value",
                "8",
                "--operator-channel",
                "1",
                "--baseline",
                "7",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert (report["stage"], report["writes"]) == ("written", 1)
    assert report["trial_record_phase"] == "obligation"
    assert "disk full" in report["trial_record_error"]
    assert "udv-acquire: owed:" in captured.err
    assert "restore the trial baseline profiles == 7" in captured.err
    assert actuator.commits == [(PROFILES_EDIT, "8", PROFILES_OWNER)]
    on_disk = _record(tmp_path, PROFILES_TRIAL_FILE_NAME)
    assert on_disk["phase"] == "obligation"


def test_the_cli_exits_two_on_a_wrong_operator_channel(
    tmp_path, monkeypatch, capsys
) -> None:
    actuator = FakePopupActuator()
    monkeypatch.setattr(channels_profiles, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-profiles",
                "--expect",
                "7",
                "--value",
                "8",
                "--operator-channel",
                "0",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )
    assert exit_info.value.code == 2
    assert actuator.commits == []
    assert "positive integer" in capsys.readouterr().err


def test_the_writer_builds_its_actuator_without_real_input_and_still_commits_once(
    tmp_path, monkeypatch
) -> None:
    captured: dict = {}
    actuator = FakePopupActuator()

    def build(**kwargs):
        captured.update(kwargs)
        return actuator

    monkeypatch.setattr(channels_profiles, "Win32Actuator", build)
    result = acquire_profiles(
        expect=7,
        value=8,
        operator_channel=1,
        mpx_disabled=True,
        trial_record=tmp_path / "trial",
        enumerate_windows=lambda: (WINDOW,),
    )

    assert captured["allow_real_input"] is False
    assert actuator.commits == [(PROFILES_EDIT, "8", PROFILES_OWNER)]
    assert result.stage is ProfilesWriteStage.WRITTEN
    assert result.writes == 1


# ---------------------------------------------------------------------------------------------
# the post-write report survives a partial reading, and the moved fact is named
# ---------------------------------------------------------------------------------------------


def test_a_post_count_that_does_not_parse_keeps_its_raw_text_and_the_facts_it_did_state(
    tmp_path,
) -> None:
    """The regression: an unreadable *count* used to discard the whole post-write reading.

    The popup is still the settings popup and still states every other amount; only the profiles
    widget states something that is not an integer. Reporting that as "no reading" lost the raw
    text the operator needs (``'8x'`` is on the screen) and every preserved fact the same read
    did state — which read as "they all held" in ``other_changes == ()``.
    """

    def garble(actuator: FakePopupActuator) -> None:
        # The third reading is the post-write one: the field states something the reader cannot
        # parse, which is the reading that used to be thrown away whole.
        if actuator.reads == 3:
            actuator.texts[PROFILES_EDIT] = "8x"

    actuator = FakePopupActuator(on_read=garble)
    result = _run(tmp_path, actuator)

    assert result.stage is ProfilesWriteStage.WRITE_UNVERIFIED
    assert result.writes == 1
    assert result.new_text == "8x"
    assert result.new_value is None
    assert result.other_facts_after == {
        "repeat": "1",
        "start_channel": "1",
        "apply_from": "1",
    }
    assert result.other_changes == ()
    assert result.other_facts_unreadable == ()
    assert "8x" in result.error
    on_disk = _record(tmp_path)
    assert (on_disk["new_text"], on_disk["new_value"]) == ("8x", None)
    assert on_disk["other_facts_after"] == {
        "repeat": "1",
        "start_channel": "1",
        "apply_from": "1",
    }


def test_a_group_box_that_stops_resolving_keeps_the_facts_the_read_still_states(
    tmp_path,
) -> None:
    """``per_channel is None`` is not "no reading": repeat/start/apply were read and are kept."""

    def break_group(actuator: FakePopupActuator) -> None:
        # One of the group's two action buttons disappears, so the group box's measured band
        # signature no longer holds and none of its amounts is bound. The rest of the popup —
        # repeat and the start channel — is unaffected and still readable.
        if actuator.reads == 3:
            actuator.rows = tuple(row for row in SETTINGS_ROWS if row[0] != 1023)

    actuator = FakePopupActuator(on_read=break_group)
    result = _run(tmp_path, actuator)

    assert result.stage is ProfilesWriteStage.WRITE_UNVERIFIED
    assert result.writes == 1
    assert result.other_facts_after == {"repeat": "1", "start_channel": "1"}
    assert result.other_changes == ()
    # The group box owns apply_from too, so its loss is unknown — not a movement.
    assert result.other_facts_unreadable == ("apply_from: '1' -> unread",)
    assert "no per-channel profiles amount" in result.error
    on_disk = _record(tmp_path)
    assert on_disk["other_facts_after"]["repeat"] == "1"


def test_a_post_surface_that_states_none_of_the_facts_claims_no_movement(
    tmp_path,
) -> None:
    """A closed popup states nothing: that is unknown, never every fact vanishing."""

    actuator = FakePopupActuator(close_after_commit=True)
    result = _run(tmp_path, actuator)

    assert result.stage is ProfilesWriteStage.WRITE_UNVERIFIED
    assert result.other_facts_after == {}
    assert result.other_changes == ()
    assert result.other_facts_unreadable == ()


def test_the_moved_fact_is_named_in_the_summary(tmp_path) -> None:
    def move_repeat(actuator: FakePopupActuator) -> None:
        actuator.texts[REPEAT_EDIT] = "2"

    result = _run(tmp_path, FakePopupActuator(on_commit=move_repeat))

    assert result.stage is ProfilesWriteStage.WRITTEN_OTHER_FACTS_CHANGED
    assert result.other_changes == ("repeat: '1' -> '2'",)
    assert "other facts moved: repeat: '1' -> '2'" in result.summary()


def test_the_cli_names_the_moved_fact_on_stderr_and_exits_one(
    tmp_path, monkeypatch, capsys
) -> None:
    def move_repeat(actuator: FakePopupActuator) -> None:
        actuator.texts[REPEAT_EDIT] = "2"

    actuator = FakePopupActuator(on_commit=move_repeat)
    monkeypatch.setattr(channels_profiles, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-profiles",
                "--expect",
                "7",
                "--value",
                "8",
                "--operator-channel",
                "1",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["stage"] == "written_other_facts_changed"
    assert report["other_changes"] == ["repeat: '1' -> '2'"]
    assert "udv-acquire: other fact moved: repeat: '1' -> '2'" in captured.err


# ---------------------------------------------------------------------------------------------
# the caption/overlay/ready clauses are asked again immediately before the commit
# ---------------------------------------------------------------------------------------------


def test_a_process_mode_that_changes_after_the_preflight_refuses_before_the_commit(
    tmp_path,
) -> None:
    """The mode is read from the caption at the commit, never assumed from the binding."""

    def drift(actuator: FakePopupActuator) -> None:
        if actuator.captions == 2:
            actuator.caption = "UDOP Simul"

    actuator = FakePopupActuator(on_caption=drift)
    with pytest.raises(AcquisitionError, match="immediately before the commit"):
        _run(tmp_path, actuator)

    assert actuator.commits == []
    assert not (tmp_path / PROFILES_TRIAL_FILE_NAME).exists()
