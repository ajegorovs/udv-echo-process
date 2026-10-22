"""Offline: the shared ``Channels`` anchor proof and the opener's one comparison, on projected bars.

No window, no cursor, no popup, no application: every case is a :class:`ScreenObservation`
projected from a synthesised menubar, which is the same type a captured tree is projected onto.
The point of the file is the *refusals*: a bar of another length, a differently-captioned binding,
a missing rect and two candidate anchors all stop the probe before its hover, and none of them
falls back to "seventh button".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "live" / "probes"))

from udv_echo_process.acquire import (
    driver as _driver,  # noqa: F401  (breaks ui.channels cycle)
)
from udv_echo_process.acquire.udop.parameters import DismissalOutcome
from udv_echo_process.acquire.ui.channels import (
    SETTINGS_SIGNATURE,
    ChannelsSurface,
)
from udv_echo_process.acquire.ui.menu import (
    MEASURED_BAR,
    MENU_ORDER,
    channels_anchor_clause,
)
from udv_echo_process.acquire.ui.menu import (
    channels_anchor as menu_channels_anchor,
)
from udv_echo_process.acquire.ui.model import (
    MenuObservation,
    Rect,
    ScreenObservation,
    UiNode,
)

_SPEC = importlib.util.spec_from_file_location(
    "channels_opener", REPO / "tools" / "live" / "probes" / "channels_opener.py"
)
opener = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["channels_opener"] = opener
_SPEC.loader.exec_module(opener)


def _button(left: int, hwnd: int) -> UiNode:
    return UiNode(
        cls="TSp_Button",
        rect=Rect(left=left, top=20, right=left + 50, bottom=44),
        hwnd=hwnd,
    )


def _bar(names: tuple[str, ...], *, bind: tuple[str, ...] | None = None, lefts=None):
    """A projection of a ``names``-shaped bar; ``bind`` names the entries the resolver proved."""
    lefts = lefts or [100 + 60 * index for index in range(len(names))]
    buttons = tuple(_button(left, 1000 + index) for index, left in enumerate(lefts))
    named = ()
    if bind:
        named = tuple((name, buttons[names.index(name)]) for name in bind)
    return ScreenObservation(
        menu=MenuObservation(
            band=UiNode(
                cls="TSp_Panel",
                rect=Rect(left=90, top=18, right=1200, bottom=48),
                hwnd=9,
            ),
            buttons=buttons,
            named=named,
        )
    )


def test_measured_ten_entry_bar_binds_channels_at_the_measured_ordinal():
    observation = _bar(MEASURED_BAR)
    assert channels_anchor_clause(observation) is None
    anchor = menu_channels_anchor(observation)
    assert anchor is not None and anchor.hwnd == 1000 + MEASURED_BAR.index("Channels")


def test_eleven_name_vocabulary_bar_is_refused_with_no_ordinal_fallback():
    observation = _bar(MENU_ORDER)
    clause = channels_anchor_clause(observation)
    assert clause is not None
    assert "paints 11 button(s)" in clause
    assert "nothing is hovered" in clause
    assert menu_channels_anchor(observation) is None


@pytest.mark.parametrize("names", [MEASURED_BAR[:-1], MEASURED_BAR + ("Extra",)])
def test_a_bar_of_another_length_is_refused(names):
    clause = channels_anchor_clause(_bar(names))
    assert clause is not None and "measured bar" in clause


def test_two_buttons_at_one_left_are_ambiguous():
    lefts = [100 + 60 * index for index in range(len(MEASURED_BAR))]
    lefts[7] = lefts[6]
    clause = channels_anchor_clause(_bar(MEASURED_BAR, lefts=lefts))
    assert clause is not None and "ambiguous" in clause


def test_a_missing_rect_refuses_rather_than_assuming_a_point():
    observation = _bar(MEASURED_BAR)
    broken = list(observation.menu.buttons)
    broken[7] = broken[7].model_copy(update={"rect": None})
    observation = observation.model_copy(
        update={"menu": observation.menu.model_copy(update={"buttons": tuple(broken)})}
    )
    clause = channels_anchor_clause(observation)
    assert clause is not None and "no measurable rect" in clause


def test_a_different_caption_is_unknown_never_another_entry():
    wrong = tuple("Channel" if name == "Channels" else name for name in MEASURED_BAR)
    clause = channels_anchor_clause(_bar(wrong, bind=("Parameters", "Channel")))
    assert clause is not None and "UNKNOWN" in clause


def test_consistent_binding_at_the_measured_entry_passes():
    anchor = menu_channels_anchor(_bar(MEASURED_BAR, bind=("Parameters", "Channels")))
    assert anchor is not None and anchor.hwnd == 1000 + 7


def test_a_binding_that_contradicts_the_bar_is_refused():
    observation = _bar(MEASURED_BAR, bind=("Parameters", "Channels"))
    buttons = observation.menu.buttons
    observation = observation.model_copy(
        update={
            "menu": observation.menu.model_copy(
                update={"named": (("Parameters", buttons[2]), ("Channels", buttons[6]))}
            )
        }
    )
    clause = channels_anchor_clause(observation)
    assert clause is not None and "contradicts the bar" in clause


def test_more_than_one_binding_per_name_is_ambiguous():
    observation = _bar(MEASURED_BAR, bind=("Parameters", "Channels"))
    buttons = observation.menu.buttons
    observation = observation.model_copy(
        update={
            "menu": observation.menu.model_copy(
                update={"named": (("Channels", buttons[7]), ("Channels", buttons[8]))}
            )
        }
    )
    clause = channels_anchor_clause(observation)
    assert clause is not None and "ambiguous" in clause


def _slot(text, value=None, hwnd=2000, owner_hwnd=3000):
    return SimpleNamespace(
        text=text,
        value=int(text) if value is None and text.isdigit() else value,
        hwnd=hwnd,
        owner_hwnd=owner_hwnd,
    )


def _read(
    surface,
    signature,
    entry,
    repeat="2",
    start="1",
    apply_from="1",
    profiles="50",
    seconds="2.01",
    mark=None,
):
    return SimpleNamespace(
        surface=surface,
        signature=signature,
        readable=True,
        entry=entry,
        refusals=(),
        repeat=None if repeat is None else _slot(repeat),
        start_channel=None if start is None else _slot(start),
        apply_from=None if apply_from is None else _slot(apply_from),
        per_channel=SimpleNamespace(
            profiles=None if profiles is None else _slot(profiles),
            seconds=None if seconds is None else _slot(seconds),
        ),
        capture=None if mark is None else SimpleNamespace(visual_mode_mark=mark),
    )


class _Entry:
    def model_dump(self, mode="json"):
        return {"band": [30, 14, 148, 27]}


def _resolved(rows):
    """The real reader's answer for a carried capture shape — not a hand-built popup."""
    from test_acquire_channels_read import _roles

    from udv_echo_process.acquire.ui.channels import resolve_channels
    from udv_echo_process.acquire.ui.layout import observation_of

    return resolve_channels(observation_of(_roles(rows)))


def test_hover_outcome_accepts_the_resolved_full_popup_which_states_no_entry():
    """The regression the live probe hit: a real full popup is ``entry is None`` and still OK.

    ``resolve_channels`` states an entry only on the multiplexer-on clip, so requiring one on the
    full surface rejected the real reading (``channels-opener-live-01.log``, exit 4).
    """
    from test_acquire_channels_read import SETTINGS_ROWS

    before = _read(ChannelsSurface.ABSENT, (), None)
    after = _resolved(SETTINGS_ROWS)
    assert after.surface is ChannelsSurface.SETTINGS_POPUP
    assert after.signature == SETTINGS_SIGNATURE
    assert after.readable is True
    assert after.refusals == ()
    assert after.entry is None
    outcome = opener.hover_outcome(before, after)
    assert outcome["ok"] is True
    assert outcome["problems"] == []
    assert outcome["entry"] is None
    assert outcome["numeric_texts"] == {
        "repeat": "1",
        "start_channel": "1",
        "apply_from": "1",
        "profiles": "7",
        "seconds": "0.28",
    }
    assert "no prior baseline" in outcome["settings_unchanged"]


def test_hover_outcome_rejects_the_clipped_multiplexer_on_entry_even_though_it_has_an_entry():
    """The inverted claim: the one-entry clip is the multiplexer-ON surface and is not the full one."""
    from test_acquire_channels_read import ENTRY_ROWS

    before = _read(ChannelsSurface.ABSENT, (), None)
    clipped = _resolved(ENTRY_ROWS)
    assert clipped.surface is ChannelsSurface.MULTIPLEXER_ON_ENTRY
    assert clipped.entry is not None
    outcome = opener.hover_outcome(before, clipped)
    assert outcome["ok"] is False
    assert any(
        "not the full 'settings_popup'" in problem for problem in outcome["problems"]
    )


def test_hover_outcome_rejects_an_unreadable_reading_and_names_its_refusals():
    from test_acquire_channels_read import SETTINGS_ROWS

    # A changed toggle class: the real reader refuses and names why.
    changed_rows = tuple(
        (*row[:2], "TSp_Value_Button", *row[3:]) if row[0] == 1003 else row
        for row in SETTINGS_ROWS
    )
    after = _resolved(changed_rows)
    assert after.readable is False
    assert after.refusals
    outcome = opener.hover_outcome(_read(ChannelsSurface.ABSENT, (), None), after)
    assert outcome["ok"] is False
    assert any("not readable" in problem for problem in outcome["problems"])
    assert any("named refusal" in problem for problem in outcome["problems"])


def test_hover_outcome_refuses_a_changed_band_signature():
    before = _read(ChannelsSurface.ABSENT, (), None)
    changed = _read(ChannelsSurface.SETTINGS_POPUP, ("toggle", "toggle"), _Entry())
    problems = opener.hover_outcome(before, changed)["problems"]
    assert any("changed structure" in problem for problem in problems)


def test_hover_outcome_reports_a_number_difference_against_a_baseline():
    before = _read(ChannelsSurface.ABSENT, (), None)
    after = _read(
        ChannelsSurface.SETTINGS_POPUP, SETTINGS_SIGNATURE, _Entry(), repeat="3"
    )
    outcome = opener.hover_outcome(before, after, {"numeric_texts": {"repeat": "2"}})
    assert outcome["baseline_differences"] == ["repeat: '2' -> '3'"]


def test_reopen_comparison_compares_all_five_amounts_and_names_a_drift():
    before = _read(ChannelsSurface.SETTINGS_POPUP, SETTINGS_SIGNATURE, None)
    after = _read(
        ChannelsSurface.SETTINGS_POPUP, SETTINGS_SIGNATURE, None, seconds="2.10"
    )
    comparison = opener.reopen_comparison(before, after)
    assert comparison["compared"] == list(opener.NUMERIC_FACTS)
    assert comparison["unreadable"] == []
    assert comparison["differences"] == ["seconds: '2.01' -> '2.10'"]
    assert comparison["ok"] is False
    assert comparison["mode_before"]["available"] is False
    assert "no fresh capture" in comparison["mode_note"]


def test_reopen_comparison_reports_an_unreadable_amount_as_unknown_never_equal():
    before = _read(ChannelsSurface.SETTINGS_POPUP, SETTINGS_SIGNATURE, None)
    after = _read(
        ChannelsSurface.SETTINGS_POPUP, SETTINGS_SIGNATURE, None, profiles=None
    )
    comparison = opener.reopen_comparison(before, after)
    assert "profiles" in comparison["unreadable"]
    assert comparison["ok"] is False
    assert comparison["differences"] == []


def test_reopen_comparison_uses_the_visual_mode_marks_when_both_captures_state_them():
    mark = SimpleNamespace(mode="VISUAL_DISABLED", rolling="OFF_PROVEN")
    before = _read(ChannelsSurface.SETTINGS_POPUP, SETTINGS_SIGNATURE, None, mark=mark)
    after = _read(ChannelsSurface.SETTINGS_POPUP, SETTINGS_SIGNATURE, None, mark=mark)
    comparison = opener.reopen_comparison(before, after)
    assert comparison["mode_before"]["available"] is True
    assert comparison["mode_differences"] == []
    assert comparison["ok"] is True
    assert "agree" in comparison["mode_note"]


def test_reopen_is_licensed_only_by_an_observed_absent_surface():
    opener.reopen_licence(
        SimpleNamespace(
            outcome=DismissalOutcome.ABSENT,
            surface_after="absent",
            clause=None,
        )
    )
    with pytest.raises(opener.ReopenRefused) as refused:
        opener.reopen_licence(
            SimpleNamespace(
                outcome=DismissalOutcome.UNKNOWN,
                surface_after="settings_popup",
                clause="still visible",
            )
        )
    assert "no second path" in str(refused.value)
