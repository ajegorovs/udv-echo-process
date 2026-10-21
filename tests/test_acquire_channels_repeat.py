"""The guarded single-field repeat write: offline, real workflow, Win32 double only.

The popup shape is the same **projected, de-identified** 8-band settings shape the read-only
reader's replay uses (handles renumbered, translated): no capture file is read and no instrument
is touched. The double replaces only the Win32 layer — the workflow, the shared reader and the
CLI are the real ones — and it counts every commit, so "zero writes" is a measurement rather
than a claim.

What these tests hold:

1. one commit, on the field's own edit, whose owner is the value button the reading named;
2. the value already being the target is read and **not** written;
3. an expected mismatch, a malformed argument, a missing mode declaration, a changed root and a
   changed field all refuse with **zero** writes;
4. the trial obligation exists on disk *before* the commit, and an existing record is never
   overwritten;
5. a post-write read proves the field, never persistence: ``persisted="unknown"`` and the
   restoration the operator owes;
6. a popup that closed after the write, and a commit that raised, are reported as unknown —
   never as "nothing changed", and never retried;
7. another readable fact that moved is reported, and the fields that must stay put are checked;
8. the reader's older call shape still works, and a caller's binding is verified, not replaced;
9. the trial's **original baseline** is separate from this invocation's ``--expect``: a restore
   run records that it returned to the baseline and owes no restore, an undeclared baseline is
   recorded as ``None`` rather than guessed, and the unknown-failure paths keep the same target;
10. a record update that fails leaves the file **and** the result at phase ``obligation``, with
    the failure reported and owed, still exactly one commit and no retry, and the CLI exits 1
    rather than 0 — a written field whose outcome never reached the record is not a finished run;
11. the persisted stamps are timezone-aware ISO 8601 wall-clock values, not a monotonic counter;
12. an unknown or wrong post-write value asks the operator to read what the field *actually*
    states and then restore, instead of confirming a value the reading just contradicted;
13. the writer builds its actuator with ``allow_real_input=False`` and still commits once.
"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from udv_echo_process.acquire import channels_read, channels_repeat
from udv_echo_process.acquire.actuator import StripState, StripView, WindowTarget
from udv_echo_process.acquire.channels_repeat import (
    RepeatWriteStage,
    acquire_repeat,
)
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.acquire.ui.channels import Attribution, ValueSlot
from udv_echo_process.cli import acquire_main

#: The main window of the projected shape — a synthetic handle, not a measured one.
WINDOW = 9000

#: The settings popup: (hwnd, parent, class, rect, text). Copied from the read-only reader's
#: replay fixture so both surfaces are the same measured shape.
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

#: The repeat slot: its own edit (1018) owned by the value button (1017).
REPEAT_EDIT = 1018
REPEAT_OWNER = 1017


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
        caption: str = "UDOP DOP3010.43",
        strip: StripState | None = None,
        overlay=None,
        on_read=None,
        on_commit=None,
        commit_error: Exception | None = None,
        close_after_commit: bool = False,
    ) -> None:
        self.rows = rows
        self.texts = dict(texts or {})
        self.caption = caption
        self.strip = strip or StripState(button_count=3)
        self.overlay = overlay
        self.on_read = on_read
        self.on_commit = on_commit
        self.commit_error = commit_error
        self.close_after_commit = close_after_commit
        self.binds = 0
        self.reads = 0
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
        return self.caption

    def peek_overlay(self):
        return self.overlay

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
            f"the repeat writer reached {name!r}: it presses, hovers, toggles and records nothing"
        )


@pytest.fixture(autouse=True)
def one_window(monkeypatch):
    """Both enumerations the workflow can use see exactly the projected window."""
    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: (WINDOW,))
    monkeypatch.setattr(
        channels_repeat, "visible_main_windows", lambda *args: (WINDOW,)
    )


def _run(tmp_path, actuator=None, **kwargs):
    params = {
        "expect": 1,
        "value": 2,
        "mpx_disabled": True,
        "trial_record": tmp_path / "trial",
        "actuator": actuator or FakePopupActuator(),
        "enumerate_windows": lambda: (WINDOW,),
    }
    params.update(kwargs)
    return acquire_repeat(**params)


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "trial").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# the one write
# ---------------------------------------------------------------------------------------------


def test_writes_the_field_once_on_the_exact_edit_and_owner(tmp_path) -> None:
    actuator = FakePopupActuator()
    result = _run(tmp_path, actuator, expect=1, value=2)

    assert actuator.commits == [(REPEAT_EDIT, "2", REPEAT_OWNER)]
    assert result.writes == 1
    assert result.stage is RepeatWriteStage.WRITTEN
    assert (result.old_text, result.new_text) == ("1", "2")
    assert result.new_value == 2
    assert result.other_changes == ()
    assert result.bound_target.hwnd == WINDOW


def test_the_field_reading_is_not_persistence_proof(tmp_path) -> None:
    result = _run(tmp_path, FakePopupActuator(), expect=1, value=2)

    assert result.persisted == "unknown"
    assert any("reopen" in owed for owed in result.restoration_owed)
    assert any(
        "not that the application kept it" in owed for owed in result.restoration_owed
    )


def test_the_trial_obligation_exists_before_the_commit_and_is_read_back_after(
    tmp_path,
) -> None:
    seen: dict = {}

    def peek(_self) -> None:
        on_disk = _record(tmp_path)
        seen.update(on_disk)

    actuator = FakePopupActuator(on_commit=peek)
    result = _run(tmp_path, actuator, expect=1, value=2)

    # Inside the commit the record already carried the obligation and the restoration.
    assert seen["phase"] == "obligation"
    assert seen["expect"] == 1
    assert seen["value"] == 2
    assert seen["restore_to"] == 1
    assert seen["edit_hwnd"] == REPEAT_EDIT
    assert seen["other_facts"] == {
        "start_channel": "1",
        "apply_from": "1",
        "profiles": "7",
        "seconds": "0.28",
    }
    # Afterwards the same file carries the outcome.
    after = _record(tmp_path)
    assert after["phase"] == "after"
    assert after["stage"] == "written"
    assert after["writes"] == 1
    assert after["persisted"] == "unknown"
    assert result.trial_record_phase == "after"


def test_an_existing_trial_record_is_never_overwritten(tmp_path) -> None:
    (tmp_path / "trial").mkdir()
    existing = tmp_path / "trial" / "channels-repeat-trial.json"
    existing.write_text('{"phase": "obligation", "expect": 9}', encoding="utf-8")
    actuator = FakePopupActuator()

    with pytest.raises(AcquisitionError, match="refusing to overwrite"):
        _run(tmp_path, actuator)
    assert actuator.commits == []
    assert json.loads(existing.read_text(encoding="utf-8"))["expect"] == 9


# ---------------------------------------------------------------------------------------------
# no write at all
# ---------------------------------------------------------------------------------------------


def test_same_value_is_read_and_not_written(tmp_path) -> None:
    actuator = FakePopupActuator()
    result = _run(tmp_path, actuator, expect=1, value=1)

    assert actuator.commits == []
    assert actuator.binds == 1
    assert result.writes == 0
    assert result.stage is RepeatWriteStage.UNCHANGED
    assert result.persisted == "not_written"
    assert result.restoration_owed == ()
    assert not (tmp_path / "trial").exists()


def test_an_expected_mismatch_refuses_with_zero_writes(tmp_path) -> None:
    actuator = FakePopupActuator()
    with pytest.raises(AcquisitionError, match="nothing was written"):
        _run(tmp_path, actuator, expect=2, value=3)
    assert actuator.commits == []
    assert not (tmp_path / "trial").exists()


@pytest.mark.parametrize("field, bad", [("expect", 0), ("value", -1), ("value", True)])
def test_a_bad_shape_refuses_with_zero_writes(tmp_path, field, bad) -> None:
    actuator = FakePopupActuator()
    with pytest.raises(AcquisitionError, match="positive integer"):
        _run(tmp_path, actuator, **{field: bad})
    assert actuator.commits == []
    assert actuator.reads == 0


def test_a_missing_mode_declaration_refuses_before_any_enumeration(tmp_path) -> None:
    def forbidden() -> tuple[int, ...]:
        raise AssertionError(
            "the window must not be enumerated without the declaration"
        )

    with pytest.raises(AcquisitionError, match="mpx-disabled"):
        _run(tmp_path, mpx_disabled=False, enumerate_windows=forbidden)


def test_a_changed_field_before_the_commit_refuses_with_zero_writes(tmp_path) -> None:
    def swap_owner(actuator: FakePopupActuator) -> None:
        if actuator.reads == 2:
            # The tree re-resolves the repeat edit under a different owner: the exact pair the
            # reading named is gone, so the write must not happen.
            actuator.rows = tuple(
                row if row[0] != REPEAT_OWNER else (row[0], WINDOW, *row[2:])
                for row in SETTINGS_ROWS
            )

    actuator = FakePopupActuator(on_read=swap_owner)
    with pytest.raises(AcquisitionError, match="tree changed|nothing was written"):
        _run(tmp_path, actuator, expect=1, value=2)
    assert actuator.commits == []


def test_a_value_that_moves_between_the_reads_refuses_with_zero_writes(
    tmp_path,
) -> None:
    def bump(actuator: FakePopupActuator) -> None:
        if actuator.reads == 2:
            actuator.texts[REPEAT_EDIT] = "5"

    actuator = FakePopupActuator(on_read=bump)
    with pytest.raises(AcquisitionError, match="changed under the read"):
        _run(tmp_path, actuator, expect=1, value=2)
    assert actuator.commits == []


def test_a_recording_strip_refuses_with_zero_writes(tmp_path) -> None:
    actuator = FakePopupActuator(strip=StripState(button_count=1, has_slider=False))
    assert StripState(button_count=1).view is not StripView.READY
    with pytest.raises(AcquisitionError, match="ready"):
        _run(tmp_path, actuator)
    assert actuator.commits == []


def test_an_overlay_refuses_with_zero_writes(tmp_path) -> None:
    from udv_echo_process.acquire.actuator import OverlayKind

    actuator = FakePopupActuator(overlay=OverlayKind.STORE_DIALOG)
    with pytest.raises(AcquisitionError, match="overlay"):
        _run(tmp_path, actuator)
    assert actuator.commits == []


def test_a_changed_popup_shape_refuses_with_zero_writes(tmp_path) -> None:
    rows = tuple(row for row in SETTINGS_ROWS if row[0] != REPEAT_EDIT)
    actuator = FakePopupActuator(rows=rows)
    with pytest.raises(AcquisitionError, match="nothing was written"):
        _run(tmp_path, actuator)
    assert actuator.commits == []


# ---------------------------------------------------------------------------------------------
# after the commit: unknown, and no retry
# ---------------------------------------------------------------------------------------------


def test_a_popup_that_closed_after_the_write_reports_unknown_without_a_retry(
    tmp_path,
) -> None:
    actuator = FakePopupActuator(close_after_commit=True)
    result = _run(tmp_path, actuator, expect=1, value=2)

    assert actuator.commits == [(REPEAT_EDIT, "2", REPEAT_OWNER)]
    assert result.stage is RepeatWriteStage.WRITE_UNVERIFIED
    assert result.persisted == "unknown"
    assert result.writes == 1
    assert result.new_text is None
    assert "nothing was retried" in result.error
    assert any("restore" in owed for owed in result.restoration_owed)


def test_a_commit_that_raised_is_not_reported_as_nothing_changed(tmp_path) -> None:
    actuator = FakePopupActuator(commit_error=RuntimeError("post failed"))
    result = _run(tmp_path, actuator, expect=1, value=2)

    assert result.stage is RepeatWriteStage.COMMIT_RAISED
    assert result.writes == 1
    assert result.persisted == "unknown"
    assert "not a report that nothing changed" in result.error
    assert any("may have landed" in owed for owed in result.restoration_owed)
    record = _record(tmp_path)
    assert record["phase"] == "after"
    assert record["stage"] == "commit_raised"


def test_another_readable_fact_that_moved_is_reported_not_repaired(tmp_path) -> None:
    def move_profiles(actuator: FakePopupActuator) -> None:
        actuator.texts[1027] = "8"

    actuator = FakePopupActuator(on_commit=move_profiles)
    result = _run(tmp_path, actuator, expect=1, value=2)

    assert result.stage is RepeatWriteStage.WRITTEN_OTHER_FACTS_CHANGED
    assert result.other_changes == ("profiles: '7' -> '8'",)
    assert result.persisted == "unknown"
    assert len(actuator.commits) == 1


# ---------------------------------------------------------------------------------------------
# the trial baseline is not this invocation's expect
# ---------------------------------------------------------------------------------------------


def test_an_outward_write_records_the_declared_baseline_and_owes_it(
    tmp_path,
) -> None:
    actuator = FakePopupActuator()
    result = _run(tmp_path, actuator, expect=1, value=2, baseline=1)

    assert result.stage is RepeatWriteStage.WRITTEN
    assert result.baseline == 1
    assert result.restore_to == 1
    assert result.restored_baseline is False
    record = _record(tmp_path)
    assert (record["expect"], record["value"], record["baseline"]) == (1, 2, 1)
    assert record["restore_to"] == 1
    assert record["restore_to_source"] == "declared-trial-baseline"
    assert record["restores_baseline"] is False
    assert "restore the trial baseline repeat == 1" in record["owed_after"]
    assert any(
        "restore the trial baseline repeat == 1" in owed
        for owed in result.restoration_owed
    )


def test_the_restore_run_owes_nothing_and_never_names_its_own_start_as_baseline(
    tmp_path,
) -> None:
    actuator = FakePopupActuator(texts={REPEAT_EDIT: "2"})
    result = _run(tmp_path, actuator, expect=2, value=1, baseline=1)

    assert actuator.commits == [(REPEAT_EDIT, "1", REPEAT_OWNER)]
    assert result.stage is RepeatWriteStage.WRITTEN
    assert (result.old_text, result.new_text) == ("2", "1")
    assert result.baseline == 1
    assert result.restore_to == 1
    assert result.restored_baseline is True
    record = _record(tmp_path)
    assert (record["expect"], record["value"], record["baseline"]) == (2, 1, 1)
    assert record["restore_to"] == 1
    assert record["restore_to_source"] == "declared-trial-baseline"
    assert record["restores_baseline"] is True
    assert record["restored_baseline"] is True
    assert "no further restoration is owed" in record["owed_after"]
    # The defect this test locks out: the restore run must never demand a restore back to 2.
    for text in (record["owed_after"], *result.restoration_owed, record["owed"][0]):
        assert "restore repeat == 2" not in text
        assert "trial baseline repeat == 2" not in text
    assert any(
        "no further restoration is owed" in owed for owed in result.restoration_owed
    )
    # Only the persistence caveat remains alongside the confirmation instruction.
    assert len(result.restoration_owed) == 2
    assert "trial baseline 1" in result.summary()
    assert "restore repeat == 2" not in result.summary()


def test_an_undeclared_baseline_is_recorded_as_none_never_as_expect(tmp_path) -> None:
    actuator = FakePopupActuator(texts={REPEAT_EDIT: "2"})
    result = _run(tmp_path, actuator, expect=2, value=1)

    record = _record(tmp_path)
    assert record["baseline"] is None
    assert record["restore_to"] == 2
    assert record["restore_to_source"] == "this-invocation"
    assert record["restores_baseline"] is False
    assert "no trial baseline was declared" in record["owed_after"]
    assert result.baseline is None
    assert result.restore_to == 2
    assert any(
        "no trial baseline was declared" in owed for owed in result.restoration_owed
    )


def test_a_bad_baseline_refuses_with_zero_writes_and_zero_reads(tmp_path) -> None:
    actuator = FakePopupActuator()
    with pytest.raises(AcquisitionError, match="positive integer"):
        _run(tmp_path, actuator, baseline=0)
    assert (actuator.commits, actuator.reads) == ([], 0)


def test_the_unchanged_path_carries_the_baseline_without_a_record(tmp_path) -> None:
    actuator = FakePopupActuator(texts={REPEAT_EDIT: "2"})
    result = _run(tmp_path, actuator, expect=2, value=2, baseline=1)

    assert actuator.commits == []
    assert result.stage is RepeatWriteStage.UNCHANGED
    assert (result.baseline, result.restore_to) == (1, 1)
    assert result.restored_baseline is False
    assert result.restoration_owed == ()
    assert not (tmp_path / "trial").exists()


@pytest.mark.parametrize("failure", ["commit_raised", "closed_popup", "wrong_value"])
def test_unknown_failure_paths_keep_the_baseline_as_the_restore_target(
    tmp_path, failure
) -> None:
    kwargs: dict = {"texts": {REPEAT_EDIT: "2"}}
    if failure == "commit_raised":
        kwargs["commit_error"] = RuntimeError("post failed")
    elif failure == "closed_popup":
        kwargs["close_after_commit"] = True
    else:
        # The commit returns but the post-write reading states something else: the value never
        # landed. (The third read is the one taken after the commit.)
        def wrong_value(actuator: FakePopupActuator) -> None:
            if actuator.reads == 3:
                actuator.texts[REPEAT_EDIT] = "7"

        kwargs["on_read"] = wrong_value
    actuator = FakePopupActuator(**kwargs)
    result = _run(tmp_path, actuator, expect=2, value=1, baseline=1)

    assert result.writes == 1
    assert result.persisted == "unknown"
    assert result.baseline == 1
    assert result.restore_to == 1
    # None of these outcomes saw the field state the baseline, so none claims it was restored.
    assert result.restored_baseline is False
    if failure == "wrong_value":
        assert result.stage is RepeatWriteStage.WRITE_UNVERIFIED
    record = _record(tmp_path)
    assert record["baseline"] == 1
    assert record["restore_to"] == 1
    assert record["restored_baseline"] is False
    assert "no further restoration is owed" not in record["owed_after"]
    owed = result.restoration_owed
    assert any("restore the trial baseline repeat == 1" in text for text in owed)
    assert any("may have landed" in text for text in owed)
    assert any("read the repeat as it actually states" in text for text in owed)
    # N3: the field did not state the committed value, so no instruction may ask the operator
    # to "confirm" it — they must read what it actually says, then restore.
    assert not any("confirm repeat" in text for text in owed)
    assert "confirm repeat" not in record["owed_after"]
    assert not any("restore repeat == 2" in text for text in owed)


def test_a_failed_record_update_leaves_the_file_and_the_result_at_obligation(
    tmp_path, monkeypatch
) -> None:
    """B1: a failed outcome write must not report ``after``; the obligation is what remains."""

    def fail_update(_file, _payload) -> str:
        return "the trial record could not be updated: disk full"

    monkeypatch.setattr(channels_repeat, "update_trial_record", fail_update)
    actuator = FakePopupActuator()
    result = _run(tmp_path, actuator, expect=1, value=2, baseline=1)

    # Exactly one commit, on the exact field, and nothing was retried or re-read for a write.
    assert actuator.commits == [(REPEAT_EDIT, "2", REPEAT_OWNER)]
    assert result.writes == 1
    # The file still holds the pre-write obligation, so the next run reads a blocking record.
    on_disk = _record(tmp_path)
    assert on_disk["phase"] == "obligation"
    assert (on_disk["expect"], on_disk["value"], on_disk["restore_to"]) == (1, 2, 1)
    # And the result says the same phase instead of claiming the outcome reached disk.
    assert result.trial_record_phase == "obligation"
    assert "disk full" in result.trial_record_error
    # The write itself raised nothing: the failure is the record update, and the stale
    # obligation on disk still names the restoration the trial owes.
    assert result.error == ""
    assert "restore the trial baseline repeat == 1" in on_disk["owed_after"]
    assert result.stage is RepeatWriteStage.WRITTEN
    assert result.persisted == "unknown"
    # The failure is owed to the operator, next to the trial's own restoration obligation.
    assert any("disk full" in owed for owed in result.restoration_owed)
    assert any(
        "restore the trial baseline repeat == 1" in owed
        for owed in result.restoration_owed
    )


def test_the_record_stamps_are_timezone_aware_wall_clock_iso(tmp_path) -> None:
    """N1: persisted stamps are ISO wall-clock values with an offset, never monotonic floats."""
    _run(tmp_path, FakePopupActuator(), expect=1, value=2)
    record = _record(tmp_path)

    for field in ("written_at", "completed_at"):
        stamp = record[field]
        assert isinstance(stamp, str), (
            f"{field} is {stamp!r}: a timestamp, not a counter"
        )
        parsed = datetime.fromisoformat(stamp)
        assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    # The injection point stays: a caller (or a test) can pin a stamp and it is what is written.
    injected = "2026-10-21T09:30:00+00:00"
    pinned_dir = tmp_path / "pinned"
    pinned_dir.mkdir()
    pinned = _run(
        pinned_dir,
        FakePopupActuator(),
        expect=1,
        value=2,
        trial_record=pinned_dir / "trial",
        stamp=lambda: injected,
    )
    pinned_record = json.loads((pinned_dir / "trial").read_text(encoding="utf-8"))
    assert (pinned_record["written_at"], pinned_record["completed_at"]) == (
        injected,
        injected,
    )
    assert pinned.trial_record_phase == "after"


# ---------------------------------------------------------------------------------------------
# the CLI and the reader's older shape
# ---------------------------------------------------------------------------------------------


def test_the_cli_writes_once_and_reports_through_json(
    tmp_path, monkeypatch, capsys
) -> None:
    actuator = FakePopupActuator()
    monkeypatch.setattr(channels_repeat, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-repeat",
                "--expect",
                "1",
                "--value",
                "2",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )
    assert exit_info.value.code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stage"] == "written"
    assert report["writes"] == 1
    assert report["persisted"] == "unknown"
    assert report["new_value"] == 2
    assert report["restoration_owed"]


def test_the_cli_exits_two_on_an_expected_mismatch(
    tmp_path, monkeypatch, capsys
) -> None:
    actuator = FakePopupActuator()
    monkeypatch.setattr(channels_repeat, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-repeat",
                "--expect",
                "3",
                "--value",
                "2",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )
    assert exit_info.value.code == 2
    assert actuator.commits == []
    assert "--expect 3" in capsys.readouterr().err


def test_the_cli_restore_run_reports_the_trial_baseline_not_its_own_start(
    tmp_path, monkeypatch, capsys
) -> None:
    actuator = FakePopupActuator(texts={REPEAT_EDIT: "2"})
    monkeypatch.setattr(channels_repeat, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-repeat",
                "--expect",
                "2",
                "--value",
                "1",
                "--baseline",
                "1",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )
    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert (report["expect"], report["value"], report["baseline"]) == (2, 1, 1)
    assert report["restore_to"] == 1
    assert report["restored_baseline"] is True
    assert "restore repeat == 2" not in captured.out
    assert "owed:" not in captured.err
    record = json.loads(
        (tmp_path / channels_repeat.TRIAL_FILE_NAME).read_text(encoding="utf-8")
    )
    assert record["restore_to_source"] == "declared-trial-baseline"
    assert record["restore_to"] == 1


def test_the_cli_exits_one_when_the_outcome_never_reached_the_trial_record(
    tmp_path, monkeypatch, capsys
) -> None:
    """B1 through the real CLI: a written field plus a stale record is a failed run, not exit 0."""

    def fail_update(_file, _payload) -> str:
        return "the trial record could not be updated: disk full"

    monkeypatch.setattr(channels_repeat, "update_trial_record", fail_update)
    actuator = FakePopupActuator()
    monkeypatch.setattr(channels_repeat, "Win32Actuator", lambda **kwargs: actuator)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "channels-repeat",
                "--expect",
                "1",
                "--value",
                "2",
                "--baseline",
                "1",
                "--mpx-disabled",
                "--trial-record",
                str(tmp_path),
                "--json",
            ]
        )
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    # The write itself did land and is still reported as such; the exit code carries the rest.
    report = json.loads(captured.out)
    assert report["stage"] == "written"
    assert report["writes"] == 1
    assert report["trial_record_phase"] == "obligation"
    assert "disk full" in report["trial_record_error"]
    # The failure and the restoration the trial still owes are on stderr, one line each.
    assert "udv-acquire: owed:" in captured.err
    assert "disk full" in captured.err
    assert "restore the trial baseline repeat == 1" in captured.err
    # Exactly one commit, and the file the next run reads is still the pre-write obligation.
    assert actuator.commits == [(REPEAT_EDIT, "2", REPEAT_OWNER)]
    on_disk = json.loads(
        (tmp_path / channels_repeat.TRIAL_FILE_NAME).read_text(encoding="utf-8")
    )
    assert on_disk["phase"] == "obligation"


def test_the_writer_builds_its_actuator_without_real_input_and_still_commits_once(
    tmp_path, monkeypatch
) -> None:
    """N4: the cursor-driven menubar step is off; the posted commit is unaffected."""
    captured: dict = {}
    actuator = FakePopupActuator()

    def build(**kwargs):
        captured.update(kwargs)
        return actuator

    monkeypatch.setattr(channels_repeat, "Win32Actuator", build)
    result = acquire_repeat(
        expect=1,
        value=2,
        mpx_disabled=True,
        trial_record=tmp_path / "trial",
        enumerate_windows=lambda: (WINDOW,),
    )

    assert captured["allow_real_input"] is False
    assert actuator.commits == [(REPEAT_EDIT, "2", REPEAT_OWNER)]
    assert result.stage is RepeatWriteStage.WRITTEN
    assert result.writes == 1


def test_the_reader_still_works_without_a_target_and_does_not_rebind_with_one(
    tmp_path, monkeypatch
) -> None:
    # The older call shape: no target, so the one visible window is bound here.
    old = FakePopupActuator()
    assert channels_read.read_channels(old).surface.value == "settings_popup"
    assert old.binds == 1

    # The writer's shape: the caller's binding is verified, never replaced.
    bound = FakePopupActuator()
    target = bound.bind_target(WINDOW)
    channels_read.read_channels(bound, target=target)
    assert bound.binds == 1

    # The slot type keeps its old field set: handles are optional references.
    slot = ValueSlot(
        slot="repeat", attribution=Attribution(caption="x"), text="1", value=1
    )
    assert (slot.hwnd, slot.owner_hwnd) == (None, None)
