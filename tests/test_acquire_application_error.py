"""An application error box is a refusal, and it outranks every overlay.

Measured 2026-10-26: a Delphi access-violation box sat in front of the application while every menu call reported
``executed: 0`` after its full timeout and every run refused with a reason about the foreground. The box is a *top-level*
window, so no child census could see it; the runner now asks for it before it answers any overlay.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_acquire_runner import (
    DURATION_S,
    FakeActuator,
    make_runner,
    point_for,
)


class CrashBoxActuator(FakeActuator):
    """An actuator whose application is showing a modal error box."""

    message = "Violation d'acces a l'adresse 007262A6 dans le module 'Udop607_4.exe'. Lecture de l'adresse 1004FFF8."

    def application_error(self) -> str | None:
        return self.message


def test_a_point_is_aborted_when_the_application_shows_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake, engine, _log_path, _ = make_runner(tmp_path, monkeypatch, fake_class=CrashBoxActuator)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "showing an error" in (outcome.reason or ""), outcome.reason
    assert "007262A6" in (outcome.reason or ""), "the box's own text is carried, so a reader sees what happened"
    # Nothing was pressed and nothing was recorded: the box outranks the overlay handling that would press.
    assert [call for call in fake.calls if call[0] in ("press", "write_parameter")] == [], fake.calls


def test_an_actuator_without_the_check_is_not_refused_for_that(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check is a capability of the Windows actuator; its absence is not an error state."""

    _fake, engine, _log_path, _ = make_runner(tmp_path, monkeypatch)
    assert not hasattr(FakeActuator, "application_error")

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
