"""The ``column`` command: the two dropdowns by value text, their report, and the CLI's forwarding.

The dropdowns are not ``ParamRole`` values, so they carry their own vocabulary and their own report. What is
pinned here is the small set of promises a caller relies on: the order the writes run in, that a combo the
column does not have is refused by name, that a request for nothing is refused, and that the command forwards
exactly the arguments it was given.
"""

from __future__ import annotations

import json

import pytest

from udv_echo_process.acquire import live
from udv_echo_process.acquire.column import COLUMN_COMBOS, ColumnChange, ColumnReport
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.ui.combo import ComboSelection
from udv_echo_process.cli import acquire_main


class FakeCombo:
    """One widget: its text, and the entries a selection may land on."""

    def __init__(self, text: str, entries: tuple[str, ...]) -> None:
        self.text = text
        self.entries = entries
        self.hwnd = id(self)

    def selection(self, wanted: str) -> ComboSelection:
        index = self.entries.index(wanted)
        self.text = wanted
        return ComboSelection(text=wanted, index=index, entries=self.entries, readback=wanted)


class FakeActuator:
    """The two calls ``set_column`` makes, over widgets that behave.

    ``_resolve()`` answers the shape the real resolver answers — combos as mappings with an ``hwnd`` — because
    a fake that answers something else hides exactly the mistake it is meant to catch.
    """

    def __init__(self, sensitivity: str = "high", power: str = "Low") -> None:
        self.widgets = {
            "Sensitivity": FakeCombo(sensitivity, ("very high", "high", "medium", "low", "very low")),
            "Emitting power": FakeCombo(power, ("Low", "Medium", "High")),
        }
        self.selected: list[tuple[str, str]] = []

    def _resolve(self) -> dict:
        return {"combos": {name: {"hwnd": widget.hwnd, "left": 12, "top": 0}
                           for name, widget in self.widgets.items()}}

    def _get_text(self, hwnd: int) -> str:
        for widget in self.widgets.values():
            if widget.hwnd == hwnd:
                return widget.text
        raise AssertionError("unknown handle")

    def select_combo_by_text(self, name: str, text: str) -> ComboSelection:
        widget = self.widgets[name]
        if text not in widget.entries:
            raise AcquisitionError(f"combo_entry_absent:{text}")
        self.selected.append((name, text))
        return widget.selection(text)


@pytest.fixture
def actuator(monkeypatch) -> FakeActuator:
    fake = FakeActuator()
    monkeypatch.setattr(live, "live_actuator", lambda channel=None, notes=None: fake)
    return fake


class TestTheReport:
    def test_a_report_is_frozen(self):
        from pydantic import ValidationError

        report = ColumnReport(changes=(ColumnChange(combo="Sensitivity", requested="high", index=1),))
        with pytest.raises(ValidationError):
            report.verified = True  # type: ignore[misc]

    def test_settled_names_only_the_combos_that_read_back_as_requested(self):
        report = ColumnReport(
            changes=(
                ColumnChange(combo="Sensitivity", requested="high", readback="high", index=1),
                ColumnChange(combo="Emitting power", requested="High", readback="Medium", index=2),
            )
        )
        assert report.settled == ("Sensitivity",)

    def test_the_vocabulary_is_the_applications_order(self):
        assert COLUMN_COMBOS == ("Sensitivity", "Emitting power")


class TestSettingTheColumn:
    def test_one_combo_is_set_and_read_back(self, actuator):
        report = live.set_column(sensitivity="medium")
        assert report.verified is True
        assert actuator.selected == [("Sensitivity", "medium")]
        change = report.changes[0]
        assert (change.combo, change.before, change.readback) == ("Sensitivity", "high", "medium")
        assert change.changed is True
        assert change.entries == ("very high", "high", "medium", "low", "very low")

    def test_both_are_set_in_the_columns_own_order(self, actuator):
        live.set_column(sensitivity="low", emitting_power="High")
        assert actuator.selected == [("Sensitivity", "low"), ("Emitting power", "High")]

    def test_setting_the_value_it_already_has_is_not_a_change(self, actuator):
        report = live.set_column(sensitivity="high")
        assert report.verified is True
        assert report.changes[0].changed is False

    def test_a_missing_entry_is_refused_with_the_widgets_words(self, actuator):
        with pytest.raises(AcquisitionError) as caught:
            live.set_column(sensitivity="Very high")
        assert str(caught.value) == "combo_entry_absent:Very high"

    def test_a_request_for_nothing_is_refused(self, actuator):
        with pytest.raises(AcquisitionError) as caught:
            live.set_column()
        assert "nothing to set" in str(caught.value)

    def test_a_combo_the_column_does_not_have_is_refused_by_name(self, actuator):
        del actuator.widgets["Emitting power"]
        with pytest.raises(AcquisitionError) as caught:
            live.set_column(emitting_power="High")
        assert str(caught.value) == "no 'Emitting power' combo in the parameter column"

    def test_the_notes_state_before_and_after(self, actuator):
        notes: list[str] = []
        live.set_column(sensitivity="medium", notes=notes)
        assert any("Sensitivity: 'high' -> 'medium'" in note for note in notes)


class TestTheCommand:
    def test_the_cli_forwards_what_it_was_given(self, monkeypatch, capsys):
        calls: list[dict] = []

        def fake_set_column(**kwargs):
            calls.append(kwargs)
            return ColumnReport(
                changes=(ColumnChange(combo="Sensitivity", requested="medium", before="high",
                                      readback="medium", index=2,
                                      entries=("very high", "high", "medium")),),
                verified=True,
            )

        monkeypatch.setattr(live, "set_column", fake_set_column)
        with pytest.raises(SystemExit) as exit_info:
            acquire_main(["column", "--sensitivity", "medium", "--channel", "1", "--json"])
        assert exit_info.value.code == 0
        captured = capsys.readouterr()
        assert calls and calls[0]["sensitivity"] == "medium"
        assert calls[0]["emitting_power"] is None
        assert calls[0]["channel"] == 1
        payload = json.loads(captured.out)
        assert payload["verified"] is True

    def test_a_refusal_leaves_the_exit_code_non_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(
            live,
            "set_column",
            lambda **kwargs: ColumnReport(
                changes=(ColumnChange(combo="Sensitivity", requested="High", readback="Medium", index=1),),
                verified=False,
            ),
        )
        with pytest.raises(SystemExit) as exit_info:
            acquire_main(["column", "--emitting-power", "High"])
        assert exit_info.value.code == 1
        captured = capsys.readouterr()
        assert "refused" in captured.err
