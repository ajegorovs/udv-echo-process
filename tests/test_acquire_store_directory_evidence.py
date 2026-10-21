"""The Store dialog's ``Working directory`` as a fact, and the store-only report that consumes it.

These cases pin the ownership the store-only command used to lack: the read-compare-write-readback
of the dialog's ``Working directory`` belongs to :class:`...udop.store.StoreSurface`, and its
outcome is the typed :class:`...udop.store.StoreDirectoryVerification` (``before``, ``after``,
``changed``). :meth:`StoreSurface.assert_working_directory` keeps its ``-> str`` contract by
returning the model's ``after``, so no existing caller changes.

The workflow cases then show what the store-only report does with that model: it reports the texts
the driver actually saw and refuses a driver that cannot provide structured evidence. Nothing here
reads the wording of a note — the case that used to be decided
by a note prefix now hands in a structured result *and* a note that says the opposite, and the
structured result wins.

No instrument, no window, no file is touched outside ``tmp_path``.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire.actuator import (
    OverlayKind,
    StripControl,
    StripState,
    WindowTarget,
)
from udv_echo_process.acquire.store_completed import (
    CompletedBlockDeclaration,
    StoreAttempt,
    store_completed,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop import store as store_surface
from udv_echo_process.acquire.udop.store import StoreDirectoryVerification
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.models.base import ValueModel

# ------------------------------------------- the owner: read, compare, write, read back


class FieldSurface(store_surface.StoreSurface):
    """The Store dialog reduced to the one field the verification reads and writes."""

    def __init__(self, shown: str, *, ignore_writes: bool = False) -> None:
        self.shown = shown
        self.ignore_writes = ignore_writes
        self.writes: list[tuple[int, str]] = []
        self.warnings: list[str] = []

    # the dialog's structure is not what this file tests: two edits, one of them a path
    def _require_store_dialog(self):
        return {"hwnd": 1}, []

    def _store_edits(self, panel, kids):
        return {"hwnd": 2}, {"hwnd": 3}

    def _get_text(self, hwnd: int) -> str:
        return self.shown

    def _set_text_commit(self, hwnd: int, text: str, panel_hwnd: int) -> None:
        self.writes.append((hwnd, text))
        if not self.ignore_writes:
            self.shown = text

    def _note(self, message: str) -> None:
        self.warnings.append(message)


def test_the_model_is_a_frozen_value_model_not_a_dataclass() -> None:
    """The shared convention holds: frozen, no extra fields, JSON round-trippable."""
    verification = StoreDirectoryVerification(
        before="C:\\elsewhere", after="C:\\capture", changed=True
    )
    assert isinstance(verification, ValueModel)
    assert not dataclasses.is_dataclass(verification)
    assert verification.model_dump(mode="json") == {
        "before": "C:\\elsewhere",
        "after": "C:\\capture",
        "changed": True,
    }
    with pytest.raises(ValidationError):
        verification.after = "C:\\other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        StoreDirectoryVerification(
            before="a",
            after="a",
            changed=False,
            note="extra",  # type: ignore[call-arg]
        )


def test_a_field_that_already_holds_the_directory_is_reported_unchanged(
    tmp_path: Path,
) -> None:
    """Read and compared, nothing written: ``changed`` is false and both texts are the read one.

    The application renders its own path (a trailing separator here), so ``after`` is the field's
    text, never this command's normalized path — the same value the ``-> str`` name returns.
    """
    directory = tmp_path / "capture"
    shown = f"{directory}{os.sep}"
    surface = FieldSurface(shown)

    verification = surface.verify_working_directory(directory)

    assert verification == StoreDirectoryVerification(
        before=shown, after=shown, changed=False
    )
    assert surface.writes == []
    assert surface.warnings == []


def test_a_different_field_is_written_and_the_model_states_both_texts(
    tmp_path: Path,
) -> None:
    """The write path: before is what the dialog showed, after is the read-back, changed is true."""
    directory = tmp_path / "capture"
    surface = FieldSurface("C:\\elsewhere")

    verification = surface.verify_working_directory(directory)

    assert verification.before == "C:\\elsewhere"
    assert verification.after == str(directory)
    assert verification.changed is True
    assert surface.writes == [(3, str(directory))]
    # The note is still written, unchanged: it stays provenance for a human reader, and nothing in
    # the report is derived from it any more.
    assert len(surface.warnings) == 1
    assert surface.warnings[0].startswith(
        "the Store dialog's Working directory was 'C:\\\\elsewhere'; wrote "
    )
    assert repr(str(directory)) in surface.warnings[0]


def test_a_write_that_did_not_commit_refuses_and_names_both_paths(
    tmp_path: Path,
) -> None:
    """An uncommitted write fails the point: no model, and the refusal carries both paths."""
    directory = tmp_path / "capture"
    surface = FieldSurface("C:\\elsewhere", ignore_writes=True)

    with pytest.raises(AcquisitionError) as raised:
        surface.verify_working_directory(directory)

    message = str(raised.value)
    assert "C:\\elsewhere" in message and str(directory) in message
    assert surface.writes == [(3, str(directory))]


def test_the_string_name_returns_the_structured_after_from_one_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``assert_working_directory`` delegates: one body, one place it can be wrong."""
    surface = FieldSurface("C:\\elsewhere")
    calls: list[Path] = []
    given = StoreDirectoryVerification(
        before="C:\\elsewhere", after="C:\\capture", changed=True
    )

    def recorded(directory: Path) -> StoreDirectoryVerification:
        calls.append(directory)
        return given

    monkeypatch.setattr(surface, "verify_working_directory", recorded)

    assert surface.assert_working_directory(tmp_path) == "C:\\capture"
    assert calls == [tmp_path]
    # The delegating name performs no write of its own.
    assert surface.writes == []


# --------------------------------------- the consumer: the store-only report


def declaration() -> CompletedBlockDeclaration:
    return CompletedBlockDeclaration(
        channels=(1, 2), profiles_per_channel=50, stated_by="operator"
    )


class Screen:
    """A driver-shaped double for the store-only workflow, recording every gesture."""

    caption = "UDOP DOP3010.43"

    def __init__(self) -> None:
        self.state = StripState(button_count=2, has_slider=True)
        self.warnings: list[str] = []
        self.presses: list[StripControl] = []
        self.store_names: list[str] = []
        self.directories: list[Path] = []
        self.commits = 0

    # --- identity -------------------------------------------------------
    def bind_target(self, hwnd: int) -> WindowTarget:
        return WindowTarget(
            hwnd=hwnd, thread_id=11, process_id=22, class_name=MAIN_CLASS
        )

    def window_caption(self) -> str:
        return self.caption

    def peek_overlay(self) -> OverlayKind | None:
        return OverlayKind.STORE_DIALOG if self.presses else None

    def answer_overlay(self) -> OverlayKind | None:
        return None

    # --- strip ----------------------------------------------------------
    def strip_state(self) -> StripState:
        return self.state

    def press(self, control: StripControl) -> None:
        self.presses.append(control)

    # --- Store dialog ---------------------------------------------------
    def set_store_name(self, name: str) -> None:
        self.store_names.append(name)

    def commit_store(self) -> None:
        self.commits += 1

    def wait_for_stored_file(self, directory: Path, *, known, timeout_s: float) -> Path:
        path = Path(directory) / f"{self.store_names[-1]}.BDD"
        path.write_bytes(b"BDD")
        return path


class StructuredScreen(Screen):
    """A driver that states the verification, and may also write a note about it."""

    def __init__(
        self,
        *,
        changed: bool,
        before: str = "C:\\elsewhere",
        note: str | None = None,
    ) -> None:
        super().__init__()
        self.changed = changed
        self.before = before
        self.note = note

    def verify_working_directory(self, directory: Path) -> StoreDirectoryVerification:
        self.directories.append(Path(directory))
        after = str(directory)
        if self.note is not None:
            self.warnings.append(self.note)
        return StoreDirectoryVerification(
            before=self.before if self.changed else after,
            after=after,
            changed=self.changed,
        )


class LegacyScreen(Screen):
    """A double that predates the model: it can only state the verified text."""

    def assert_working_directory(self, directory: Path) -> str:
        self.directories.append(Path(directory))
        return str(directory)


class BlindScreen(Screen):
    """A double that can state nothing about the field."""


def run(tmp_path: Path, screen: Screen):
    return store_completed(
        "block",
        tmp_path,
        declaration=declaration(),
        actuator=screen,
        enumerate_windows=lambda: (4711,),
    )


def test_a_reported_rewrite_is_reported_as_a_rewrite(tmp_path: Path) -> None:
    """The structured ``changed`` is what the report carries — no note is required to say it."""
    screen = StructuredScreen(changed=True)

    result = run(tmp_path, screen)

    store = result.store
    assert store.directory_verification == StoreDirectoryVerification(
        before="C:\\elsewhere", after=str(tmp_path), changed=True
    )
    assert store.directory_rewritten is True
    assert store.working_directory == str(tmp_path)
    assert "read 'C:\\\\elsewhere' and wrote" in store.summary()
    # The driver wrote no note at all: the fact came from the model.
    assert store.notes == ()


def test_a_note_that_claims_a_rewrite_does_not_make_one(tmp_path: Path) -> None:
    """The regression: a note's wording is no longer evidence, so a mismatch cannot invent a write.

    This is the exact shape the old note-prefix check misread: the field already held the caller's
    directory (``changed`` false) while a note with the legacy prefix was emitted for another
    reason. The report follows the structured fact.
    """
    screen = StructuredScreen(
        changed=False,
        note="the Store dialog's Working directory was 'C:\\\\elsewhere'; wrote something else",
    )

    result = run(tmp_path, screen)

    assert result.store.directory_verification is not None
    assert result.store.directory_verification.changed is False
    assert result.store.directory_rewritten is False
    assert "already held" in result.store.summary()
    assert "was rewritten" not in result.store.summary()


def test_a_driver_that_states_only_the_text_cannot_commit(tmp_path: Path) -> None:
    """Old string-returning callers remain supported, but this new workflow requires evidence."""
    screen = LegacyScreen()
    with pytest.raises(AcquisitionError, match="verify_working_directory is required"):
        run(tmp_path, screen)
    assert screen.directories == []
    assert screen.commits == 0


def test_malformed_structured_readback_cannot_commit(tmp_path: Path) -> None:
    screen = StructuredScreen(changed=False)
    screen.verify_working_directory = lambda directory: str(directory)
    with pytest.raises(AcquisitionError, match="no structured readback"):
        run(tmp_path, screen)
    assert screen.commits == 0


def test_a_driver_that_cannot_state_the_directory_commits_nothing(
    tmp_path: Path,
) -> None:
    """Neither contract: refused after the name write and before the one commit press."""
    screen = BlindScreen()

    with pytest.raises(AcquisitionError) as raised:
        run(tmp_path, screen)

    message = str(raised.value)
    assert "verify_working_directory" in message
    assert "assert_working_directory" in message
    assert screen.store_names == ["block"]
    assert screen.commits == 0
    assert not (tmp_path / "block.BDD").exists()


def test_the_summary_claims_no_uniqueness_it_did_not_observe() -> None:
    """The report states the stem match and the absence before the commit — nothing more.

    The new-entry wait returns the first new name it sees, so \"the only entry with this stem\" was
    never observed. The summary may claim only what was checked.
    """
    attempt = StoreAttempt(
        name="block",
        directory=Path("C:/store"),
        working_directory="C:/store",
        directory_rewritten=False,
        directory_verification=StoreDirectoryVerification(
            before="C:/store", after="C:/store", changed=False
        ),
        dialog_warnings_answered=0,
        waited_s=1.0,
        stored_path=Path("C:/store/block.BDD"),
        stored_name="block.BDD",
    )

    summary = attempt.summary()

    assert "only one" not in summary
    assert "block.BDD" in summary
    assert "was not in the directory before the commit" in summary
    assert "carries the requested stem 'block'" in summary
