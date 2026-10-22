"""Offline: ``ParametersSurface.open_channels_popup`` — adoption, the one measured hover, and UNKNOWN.

No desktop. The surface's binding, foreground, hover and geometry seams are recorded fakes, so the
assertions are about the **sequence**: an already-readable popup is adopted with no cursor move, an
absent screen is hovered exactly once on the measured ``Channels`` entry, and a poll that never sees
a readable popup answers the typed ``UNKNOWN`` with the last surface named — never a retry.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from udv_echo_process.acquire import driver as _driver  # noqa: F401  (cycle break)
from udv_echo_process.acquire.udop import parameters
from udv_echo_process.acquire.ui.channels import ChannelsSurface
from udv_echo_process.acquire.ui.menu import MEASURED_BAR
from udv_echo_process.acquire.ui.model import Rect

BAND = Rect(left=0, top=18, right=1200, bottom=48)


def _row(cls: str, rect: Rect, hwnd: int) -> dict:
    return {
        "cls": cls,
        "left": rect.left,
        "top": rect.top,
        "w": rect.width,
        "h": rect.height,
        "hwnd": hwnd,
    }


def _roles() -> dict:
    return {
        "window": 4242,
        "client": (1280, 1000),
        "origin": (0, 0),
        "class_name": "TSp_FormFrm",
        "raw": [],
        "panels": [],
        "parent_of": {},
        "menu_band": _row("TSp_Panel", BAND, 9),
        "menu": {},
        "menu_buttons": [
            _row(
                "TSp_Button",
                Rect(left=60 + 55 * i, top=20, right=60 + 55 * i + 45, bottom=44),
                1000 + i,
            )
            for i in range(len(MEASURED_BAR))
        ],
    }


def _read(surface: ChannelsSurface, *, readable: bool = True):
    return SimpleNamespace(surface=surface, readable=readable, popup=None, refusals=())


class _Surface(parameters.ParametersSurface):
    def __init__(self) -> None:
        self.roles = _roles()
        self.hovers: list[int] = []
        self.notes: list[str] = []

    def verify_bound_target(self, expected):
        return expected

    def _require_foreground(self, hwnd: int) -> None:
        return None

    def _resolve(self) -> dict:
        return self.roles

    def _hover_centre(self, hwnd: int, **kwargs):
        self.hovers.append(hwnd)
        return (575, 32)

    def _note(self, message: str) -> None:
        self.notes.append(message)

    def _post(self, *args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("opening the popup must not post a message")


def _sequence(reads):
    iterator = iter(reads)
    calls: list[int] = []

    def read():
        calls.append(1)
        return next(iterator)

    return read, calls


def test_an_already_readable_popup_is_adopted_without_a_hover():
    surface = _Surface()
    read, calls = _sequence([_read(ChannelsSurface.SETTINGS_POPUP)])
    result = surface.open_channels_popup(
        target=SimpleNamespace(hwnd=4242), read=read, timeout_s=0.0
    )
    assert result.outcome is parameters.PopupOutcome.OPEN
    assert result.adopted is True
    assert result.point is None
    assert result.readable is True
    assert surface.hovers == []
    assert len(calls) == 1


def test_an_absent_screen_is_hovered_once_on_the_measured_entry_and_read_back():
    surface = _Surface()
    read, calls = _sequence(
        [_read(ChannelsSurface.ABSENT), _read(ChannelsSurface.SETTINGS_POPUP)]
    )
    result = surface.open_channels_popup(
        target=SimpleNamespace(hwnd=4242), read=read, timeout_s=1.0
    )
    assert result.outcome is parameters.PopupOutcome.OPEN
    assert result.adopted is False
    assert result.point == (575, 32)
    assert surface.hovers == [1000 + MEASURED_BAR.index("Channels")]
    assert result.anchor is not None
    assert result.anchor["ordinal"] == MEASURED_BAR.index("Channels")
    assert len(calls) == 2


def test_a_poll_that_never_reads_a_popup_is_typed_unknown_and_not_retried():
    surface = _Surface()
    read, calls = _sequence(
        [
            _read(ChannelsSurface.ABSENT),
            _read(ChannelsSurface.ABSENT),
            _read(ChannelsSurface.ABSENT),
        ]
    )
    result = surface.open_channels_popup(
        target=SimpleNamespace(hwnd=4242), read=read, timeout_s=0.0
    )
    assert result.outcome is parameters.PopupOutcome.UNKNOWN
    assert result.clause is not None and "UNKNOWN" in result.clause
    assert surface.hovers == [
        1000 + MEASURED_BAR.index("Channels")
    ]  # one hover, no retry
    assert len(calls) == 2


def test_a_surface_that_is_neither_absent_nor_a_popup_is_refused_before_any_hover():
    surface = _Surface()
    read, _calls = _sequence([_read(ChannelsSurface.AMBIGUOUS)])
    with pytest.raises(Exception) as refused:
        surface.open_channels_popup(
            target=SimpleNamespace(hwnd=4242), read=read, timeout_s=0.0
        )
    assert "refusing to open" in str(refused.value)
    assert surface.hovers == []
