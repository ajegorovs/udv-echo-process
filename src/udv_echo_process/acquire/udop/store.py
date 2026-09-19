"""The Store dialog: the name, the working directory, the accept, and the stored file.

Split out of the flat :mod:`udv_echo_process.acquire.driver` by Patch 4 — **verbatim**. This
surface holds the Store dialog's structural identification, the name write, the
``Working directory`` assertion (read, compared, written and read **back**: the field decides
where the point lands), the accept, and the wait for a file that was not in the directory
before — including the overwrite-warning retry that never replaces an existing file. No
decision, message, order, timeout or refusal changed: this is a move, not a rewrite.

**Nothing here is proven on an instrument.** The dialog's behaviour and the retry are
*device-pending* (``docs/dop3000/device-verification.md``, V5/V6), and the cloud-only validation
contract (``docs/dop3000/acquisition-architecture.md`` §8) forbids claiming otherwise.

**It is a mixin**: the bodies are the ones ``Win32Actuator`` had, they reach their collaborators
through ``self`` (the overlay detector and the warning answer are the recording surface's, the
transport is the facade's), and ``acquire/driver.py`` composes this piece into the one live class
(``udop/session.py`` is that facade's compatibility name). The poll cadence
(:data:`...recording._POLL_S`) is the recording surface's, imported here rather than repeated — so
a test that shortens the wait for the stored file patches **this** module's binding of it.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from pathlib import Path

from udv_echo_process.acquire.actuator import (
    STORE_TIMEOUT_S,
    DialogControl,
    OverlayKind,
)
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.recording import _POLL_S
from udv_echo_process.acquire.ui.layout import same_directory


class StoreSurface:
    """The Store dialog workflow of :class:`~udv_echo_process.acquire.udop.session.Win32Actuator`.

    The Store dialog surface of the live actuator: the dialog's own fields, the name and the
    working directory the caller will watch, the accept, and the wait for the stored file.
    Moved out of the flat actuator verbatim by Patch 4; see this module's docstring for what is
    and is not claimed.
    """

    def _require_store_dialog(self) -> tuple[dict, list[dict]]:
        """The Store dialog panel and its children, or a failure."""
        found = self._find_overlay()
        if found is None or found[0] is not OverlayKind.STORE_DIALOG:
            raise AcquisitionError("the Store dialog is not up")
        return found[1], self._children_of(found[1]["hwnd"], self._resolve())

    def set_store_name(self, name: str) -> None:
        """Write the Store dialog's file-name field with the commit recipe.

        The name field is the edit that does *not* hold a path; the path field is
        recognised by its separator, never by its position.
        """
        panel, kids = self._require_store_dialog()
        self._set_text_commit(
            self._store_name_field(panel, kids)["hwnd"], name, panel["hwnd"]
        )

    def assert_working_directory(self, directory: Path) -> str:
        """Assert the Store dialog's ``Working directory``, and set it when it differs.

        The field decides where the point lands, so it is never assumed: it is read,
        compared with ``directory`` (the path the caller will watch), written with the
        numeric/text commit recipe when it differs, and read **back** — because a write
        that did not commit leaves the application storing somewhere else while the
        control paints the new value (docs/16 §12a, §12b). Returns the verified text.

        An unresolved mismatch raises :class:`AcquisitionError` **naming both paths**,
        which fails the point: watching a folder the application is not writing to
        surfaces only as a false "no file appeared", minutes later, with nothing in it
        pointing at the real cause.
        """
        panel, kids = self._require_store_dialog()
        path_edit = self._store_edits(panel, kids)[1]
        if path_edit is None:
            edits = [
                self._get_text(k["hwnd"])
                for k in kids
                if k["cls"] in ("TEdit", "TSp_Edit")
            ]
            raise AcquisitionError(
                "the Store dialog shows no path-looking field, so its Working directory "
                f"cannot be asserted against '{directory}' (the dialog's edits are {edits})"
            )
        shown = self._get_text(path_edit["hwnd"])
        if same_directory(shown, directory):
            return shown
        self._set_text_commit(path_edit["hwnd"], str(directory), panel["hwnd"])
        readback = self._get_text(path_edit["hwnd"])
        if not same_directory(readback, directory):
            raise AcquisitionError(
                f"the Store dialog's Working directory is '{readback}' where '{directory}' "
                f"is expected (it showed '{shown}' before the write): the point would land "
                "outside the directory the caller watches, so it is refused rather than "
                "stored and waited for in the wrong folder"
            )
        self._note(
            f"the Store dialog's Working directory was {shown!r}; wrote {readback!r}"
        )
        return readback

    def commit_store(self) -> None:
        """Press the Store dialog's rightmost bottom button (``Do store``)."""
        panel, kids = self._require_store_dialog()
        self._dialog_button(panel, kids, DialogControl.CONFIRM)

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        """Wait for a file that was not in ``directory`` before, and return it.

        The *new name* is detected, never the arrival of any file. An overwrite warning
        means the name was taken and the store was refused, so this raises instead of
        returning a path — the caller retries under a fresh name.
        """
        path, kind = self._poll_new_file(directory, frozenset(known), timeout_s)
        if path is not None:
            return path
        if kind is OverlayKind.WARNING:
            self.answer_overlay()
            raise AcquisitionError(
                "the Store dialog raised its overwrite warning (the name is taken); answered "
                "with its safe button — retry under a fresh name"
            )
        raise AcquisitionError(
            f"no new file appeared in {directory} within {timeout_s:.0f} s of Do store"
        )

    def _await_store_dialog(self, timeout_s: float) -> tuple[dict, list[dict]]:
        """Wait for the Store dialog, answering warnings that come up first."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            kind = self._peek_overlay()
            if kind is OverlayKind.STORE_DIALOG:
                return self._require_store_dialog()
            if kind is OverlayKind.WARNING:
                self._note("answered a warning before the Store dialog appeared")
                self.answer_overlay()
            time.sleep(_POLL_S)
        raise AcquisitionError("the Store dialog did not open after Do store")

    def _store_edits(self, panel: dict, kids: Sequence[dict]) -> tuple[dict, dict | None]:
        """The Store dialog's ``(name edit, path edit)``, top to bottom.

        The path field is recognised by its **separator** (``:`` or ``\\``), never by
        its position: which of the two edits is on top is not a fact this driver may
        assume. ``path`` is ``None`` when neither edit holds a path — a dialog that has
        never stored anything — which the caller reports rather than guesses around.
        """
        edits = sorted(
            (k for k in kids if k["cls"] in ("TEdit", "TSp_Edit")),
            key=lambda k: k["top"],
        )
        if len(edits) < 2:
            raise AcquisitionError(
                "the Store dialog does not show both a path and a name field"
            )

        def looks_like_a_path(k: dict) -> bool:
            text = self._get_text(k["hwnd"])
            return ":" in text or "\\" in text

        path_edit = next((k for k in edits if looks_like_a_path(k)), None)
        name_edit = next((k for k in edits if k is not path_edit), None)
        if name_edit is None:
            raise AcquisitionError("could not identify the Store dialog's name field")
        return name_edit, path_edit

    def _store_name_field(self, panel: dict, kids: Sequence[dict]) -> dict:
        """The Store dialog's file-name edit: the one whose text is not a path."""
        return self._store_edits(panel, kids)[0]

    @staticmethod
    def _names_in(directory: Path) -> frozenset[str]:
        """The directory's current entry names (empty when it does not exist yet)."""
        if not directory.is_dir():
            return frozenset()
        return frozenset(p.name for p in directory.glob("*"))

    def _poll_new_file(
        self, directory: Path, known: frozenset[str], timeout_s: float
    ) -> tuple[Path | None, OverlayKind | None]:
        """Poll for a name that was not in ``known``; report a warning instead of waiting."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            new = sorted(self._names_in(directory) - known)
            if new:
                return directory / new[0], None
            kind = self._peek_overlay()
            if kind is OverlayKind.WARNING:
                return None, kind
            if time.monotonic() >= deadline:
                return None, None
            time.sleep(_POLL_S)

    def _store_until_file(
        self, name: str, directory: Path, known: frozenset[str], timeout_s: float
    ) -> Path:
        """Wait for the file; on the overwrite warning answer ``No`` and retry once.

        The retry is the contract: the warning means the name was taken, and answering it
        with the LEFT button keeps the existing file — the point is stored again under a
        suffixed name, never over the old one (docs/16 §12b).
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        attempt = name
        retried = False
        while time.monotonic() < deadline:
            remaining = min(1.0, max(0.1, deadline - time.monotonic()))
            path, kind = self._poll_new_file(directory, known, remaining)
            if path is not None:
                return path
            if kind is not OverlayKind.WARNING:
                continue
            self.answer_overlay()  # LEFT button = No: never replace an existing file
            if retried:
                raise AcquisitionError(
                    "the store was refused twice by the overwrite warning; the name still collides"
                )
            retried = True
            attempt = f"{name}b"
            self._note(f"the name {name!r} was taken; retrying as {attempt!r}")
            self.set_store_name(attempt)
            self.commit_store()
        raise AcquisitionError(
            f"no file appeared in {directory} within {timeout_s:.0f} s of Do store"
        )
