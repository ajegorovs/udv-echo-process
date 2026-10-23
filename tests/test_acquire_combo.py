"""Selecting a dropdown entry by its text: the vocabulary walk, the match, and the read-back.

A column combo answers no item-list message, so the list is discovered by stepping it until it clamps. These
tests pin that walk, the exact-text match, and the refusal that makes a selection a claim rather than a hope.
"""

from __future__ import annotations

import pytest

from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.ui.combo import (
    BOUNDED_WALK,
    ComboSelection,
    entry_index,
    select_by_text,
    vocabulary,
)


class Combo:
    """A scripted combo: a list of entries, a clamp at the end, and the text it currently shows."""

    def __init__(self, entries: list[str], *, current: str | None = None, sticks: bool = True) -> None:
        self.entries = entries
        self.index = 0 if current is None else entries.index(current)
        self.text = self.entries[self.index]
        self.sticks = sticks
        self.selects: list[int] = []
        self.settles = 0

    def select(self, index: int) -> None:
        self.selects.append(index)
        landed = min(index, len(self.entries) - 1)  # the control clamps at its last entry
        self.index = landed
        if self.sticks:
            self.text = self.entries[landed]

    def read(self) -> str:
        return self.text

    def settle(self) -> None:
        self.settles += 1


class TestTheVocabulary:
    def test_the_walk_reports_every_entry_in_order(self):
        combo = Combo(["very high", "high", "medium", "low", "very low"])
        assert vocabulary(combo.read, combo.select, combo.settle) == (
            "very high", "high", "medium", "low", "very low",
        )

    def test_the_walk_stops_at_the_clamp(self):
        combo = Combo(["Low", "Medium", "High"])
        entries = vocabulary(combo.read, combo.select, combo.settle)
        assert entries == ("Low", "Medium", "High")
        # five steps at most: three entries and one clamped repeat
        assert len(combo.selects) <= 4

    def test_a_single_entry_list_is_still_a_list(self):
        combo = Combo(["only"])
        assert vocabulary(combo.read, combo.select, combo.settle) == ("only",)

    def test_an_unbounded_control_is_bounded_by_the_walk(self):
        # A control whose text changes on every index never clamps: the walk must end at the bound.
        counter = {"n": 0}
        text = {"value": ""}

        def select(index: int) -> None:
            counter["n"] = index
            text["value"] = f"entry {index}"

        entries = vocabulary(lambda: text["value"], select, lambda: None)
        assert len(entries) == BOUNDED_WALK
        assert counter["n"] == BOUNDED_WALK - 1

    def test_a_vocabulary_does_not_need_the_current_value_to_be_an_entry(self):
        # The text may hold something the list does not (a typed prefix), and the walk still works.
        combo = Combo(["Low", "Medium", "High"], current="Medium")
        combo.text = "Me"
        assert vocabulary(combo.read, combo.select, combo.settle)[0] == "Low"


class TestTheMatch:
    def test_an_exact_text_finds_its_index(self):
        assert entry_index(("very high", "high", "medium"), "medium") == 2

    def test_the_match_is_exact_not_a_prefix(self):
        # 'L' is a prefix of 'Low' — and the application's own filtering must not become ours.
        assert entry_index(("Low", "Medium", "High"), "L") is None

    def test_the_match_respects_case(self):
        assert entry_index(("Low", "Medium", "High"), "low") is None

    def test_an_absent_entry_has_no_index(self):
        assert entry_index(("Low", "Medium", "High"), "Very high") is None


class TestSelecting:
    def test_selecting_the_wanted_entry_returns_the_evidence(self):
        combo = Combo(["Low", "Medium", "High"], current="Low")
        selection = select_by_text("High", read=combo.read, select=combo.select, settle=combo.settle)
        assert isinstance(selection, ComboSelection)
        assert selection.index == 2
        assert selection.readback == "High"
        assert selection.entries == ("Low", "Medium", "High")
        assert combo.text == "High"

    def test_an_absent_entry_is_refused_by_name(self):
        combo = Combo(["Low", "Medium", "High"])
        with pytest.raises(AcquisitionError) as caught:
            select_by_text("Very high", read=combo.read, select=combo.select, settle=combo.settle)
        assert str(caught.value) == "combo_entry_absent:Very high"

    def test_a_selection_that_does_not_take_is_a_failure(self):
        # The walk reads a real three-entry list; after it, the control keeps showing its old entry no matter
        # what is selected. That is a refusal naming what was actually found, not a success.
        entries = ["Low", "Medium", "High"]
        state = {"index": 0, "reads": 0}

        def select(index: int) -> None:
            if state["reads"] <= 4:  # during the walk only
                state["index"] = min(index, len(entries) - 1)

        def read() -> str:
            state["reads"] += 1
            return entries[state["index"]] if state["reads"] <= 4 else entries[0]

        with pytest.raises(AcquisitionError) as caught:
            select_by_text("High", read=read, select=select, settle=lambda: None)
        assert str(caught.value) == "combo_selection_did_not_take:High:Low"

    def test_every_read_is_preceded_by_a_settle(self):
        combo = Combo(["Low", "Medium", "High"], current="Low")
        select_by_text("Medium", read=combo.read, select=combo.select, settle=combo.settle)
        # one settle per select: the walk settles after each step and the selection settles before its
        # read-back, so there is no read without a settle in front of it
        assert combo.settles == len(combo.selects)

    def test_selecting_the_current_entry_is_allowed_and_harmless(self):
        combo = Combo(["Low", "Medium", "High"], current="Medium")
        selection = select_by_text("Medium", read=combo.read, select=combo.select, settle=combo.settle)
        assert selection.index == 1
        assert combo.text == "Medium"

    def test_a_value_that_drifts_after_the_settle_is_caught_by_the_next_read(self):
        # Measured once: the immediate read said High and the column later read Medium.  The guard here is the
        # read-back itself; this test pins that a control reporting a wrong text at read time is refused.
        combo = Combo(["Low", "Medium", "High"], current="Low")

        def read() -> str:
            return "Medium" if combo.text == "High" else combo.text

        with pytest.raises(AcquisitionError):
            select_by_text("High", read=read, select=combo.select, settle=combo.settle)
