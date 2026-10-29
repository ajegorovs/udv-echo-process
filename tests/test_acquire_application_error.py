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


class RaisingCheckActuator(FakeActuator):
    """A capability that was offered and could not answer."""

    def application_error(self) -> str | None:
        raise RuntimeError("the window station refused the enumeration")


def test_a_check_that_raises_is_a_refusal_and_nothing_is_pressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unread error state is not a clean one — and the point never reaches the strip."""
    fake, engine, _log_path, _ = make_runner(tmp_path, monkeypatch, fake_class=RaisingCheckActuator)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "could not be read" in (outcome.reason or ""), outcome.reason
    assert "refused the enumeration" in (outcome.reason or ""), "the cause is carried, not replaced"
    assert [call for call in fake.calls if call[0] in ("press", "write_parameter")] == [], fake.calls


class NotCallableActuator(FakeActuator):
    """A malformed capability: the name exists and is not a check."""

    application_error = "not a check"  # type: ignore[assignment]


def test_a_check_that_is_not_callable_is_a_named_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An offered capability of the wrong shape must not silently mean "no error"."""
    fake, engine, _log_path, _ = make_runner(tmp_path, monkeypatch, fake_class=NotCallableActuator)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "not callable" in (outcome.reason or ""), outcome.reason
    assert [call for call in fake.calls if call[0] in ("press", "write_parameter")] == [], fake.calls


class MalformedAnswerActuator(FakeActuator):
    """A capability that answered something that is not a caption and not a clear screen."""

    def application_error(self) -> object:
        return 42


def test_an_answer_that_is_not_a_caption_is_not_a_clear_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, engine, _log_path, _ = make_runner(tmp_path, monkeypatch, fake_class=MalformedAnswerActuator)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "not a clear screen" in (outcome.reason or ""), outcome.reason
    assert [call for call in fake.calls if call[0] in ("press", "write_parameter")] == [], fake.calls


class BlankAnswerActuator(FakeActuator):
    """A capability that answered nothing at all — the shape that used to read as clear."""

    def application_error(self) -> str | None:
        return "  "


def test_a_blank_answer_is_not_a_clear_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reader never answers a blank string (it falls back to a truthful sentence), so a blank
    answer is a broken check rather than a screen with nothing on it."""
    fake, engine, _log_path, _ = make_runner(tmp_path, monkeypatch, fake_class=BlankAnswerActuator)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is False
    assert outcome.aborted is True, outcome.reason
    assert "empty" in (outcome.reason or ""), outcome.reason
    assert [call for call in fake.calls if call[0] in ("press", "write_parameter")] == [], fake.calls


class ClearAnswerActuator(FakeActuator):
    """A capability that answered the only clear screen there is."""

    def application_error(self) -> str | None:
        return None


def test_a_capability_that_answers_clear_lets_the_point_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Present-and-clear is not the same as absent, and neither is a refusal."""
    _fake, engine, _log_path, _ = make_runner(tmp_path, monkeypatch, fake_class=ClearAnswerActuator)

    outcome = engine.run_point(point_for(1), DURATION_S)

    assert outcome.ok is True, outcome.reason
