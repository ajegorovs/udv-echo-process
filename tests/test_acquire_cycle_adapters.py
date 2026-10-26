"""The `StoreDialog` seam :class:`~udv_echo_process.acquire.cycle.RoutineCycle` declares, over the
measured store surface.

The guarded cycle commits a store by calling ``dialog.commit(name) -> bool``. Nothing in the package
implemented that protocol, so the host integration had no way to name and accept a store without
re-implementing the recipe. :class:`~udv_echo_process.acquire.udop.store.StoreDialogCommit` is that
adapter, and this file pins what it may and may not claim: it names the file and presses the
dialog's own accept, and its ``True`` means *dispatched*, never *stored* — the cycle's own artifact
check is the acceptance.

The directory belongs to the invocation, not to the factory: the cycle is built once per command and
a sweep runs several points, each with its own directory, so the adapter is *bound* on every
invocation and an unbound commit refuses. And it reads the dialog's directory and refuses a
disagreement rather than writing that field: a write would owe a verified restoration the dialog's
own lifetime does not allow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.store import StoreDialogCommit


class Surface:
    """The store-surface members the adapter is allowed to reach, recording every call in order."""

    def __init__(
        self,
        *,
        dialog_up: bool = True,
        shows: Path | str | None = None,
        has_path_field: bool = True,
    ) -> None:
        self.calls: list[tuple] = []
        self.dialog_up = dialog_up
        self.shows = shows
        self.has_path_field = has_path_field

    def _require_store_dialog(self):
        if not self.dialog_up:
            raise AcquisitionError("the Store dialog is not up")
        return {"hwnd": 1}, []

    def read_working_directory(self):
        self.calls.append(("read_working_directory",))
        if not self.has_path_field:
            return None
        return None if self.shows is None else str(self.shows)

    def set_store_name(self, name: str) -> None:
        self.calls.append(("set_store_name", name))

    def commit_store(self) -> None:
        self.calls.append(("commit_store",))


def adapter(surface: Surface, directory: Path | None, **kwargs) -> StoreDialogCommit:
    kwargs.setdefault("sleep", lambda _seconds: None)
    return StoreDialogCommit(surface, directory=directory, **kwargs)


class TestTheMeasuredOrder:
    def test_the_directory_is_compared_then_the_name_then_the_accept(self, tmp_path):
        surface = Surface(shows=tmp_path)
        ok = adapter(surface, tmp_path, dialog_timeout_s=0.0).commit("point-01")
        assert ok is True
        assert surface.calls == [
            ("read_working_directory",),
            ("set_store_name", "point-01"),
            ("commit_store",),
        ]

    def test_the_working_directory_is_never_written(self, tmp_path):
        """The press route sets that field; this route must not owe a restoration it cannot make."""
        surface = Surface(shows=tmp_path)
        surface.assert_working_directory = lambda *_a: pytest.fail(
            "the adapter wrote the field"
        )
        assert adapter(surface, tmp_path).commit("point-01") is True

    def test_a_true_answer_means_dispatched_not_stored(self, tmp_path):
        """The adapter cannot see a file: crediting a store stays with the cycle's artifact check."""
        surface = Surface(shows=tmp_path)
        dialog = adapter(surface, tmp_path)
        assert dialog.commit("point-01") is True
        assert dialog.original_directory == str(tmp_path)
        assert not hasattr(surface, "stored")

    def test_each_invocation_binds_its_own_directory(self, tmp_path):
        first, second = tmp_path / "one", tmp_path / "two"
        surface = Surface(shows=first)
        dialog = adapter(surface, first)
        assert dialog.commit("point-01") is True
        surface.shows = second
        dialog.bind_directory(second)
        assert dialog.directory == second
        assert dialog.commit("point-02") is True
        assert surface.calls == [
            ("read_working_directory",),
            ("set_store_name", "point-01"),
            ("commit_store",),
            ("read_working_directory",),
            ("set_store_name", "point-02"),
            ("commit_store",),
        ]


class TestRefusals:
    def test_an_unbound_commit_refuses_before_reading_the_dialog(self, tmp_path):
        surface = Surface(shows=tmp_path)
        dialog = adapter(surface, None)
        with pytest.raises(AcquisitionError, match="store_directory_unbound"):
            dialog.commit("point-01")
        assert surface.calls == []

    def test_a_dialog_pointing_elsewhere_refuses_before_the_name(self, tmp_path):
        elsewhere = tmp_path / "somewhere-else"
        surface = Surface(shows=elsewhere)
        dialog = adapter(surface, tmp_path)
        with pytest.raises(AcquisitionError, match="store_directory_mismatch"):
            dialog.commit("point-01")
        assert surface.calls == [("read_working_directory",)]
        assert dialog.original_directory == str(elsewhere)
        assert dialog.last_refusal == "store_directory_mismatch"

    def test_a_dialog_with_no_path_field_is_a_mismatch(self, tmp_path):
        surface = Surface(has_path_field=False)
        with pytest.raises(AcquisitionError, match="store_directory_mismatch"):
            adapter(surface, tmp_path).commit("point-01")
        assert surface.calls == [("read_working_directory",)]

    def test_a_missing_dialog_raises_the_packages_refusal(self, tmp_path):
        surface = Surface(dialog_up=False, shows=tmp_path)
        with pytest.raises(AcquisitionError, match="Store dialog"):
            adapter(surface, tmp_path, dialog_timeout_s=0.0).commit("point-01")
        assert surface.calls == []  # nothing read, nothing named, nothing pressed

    def test_a_dialog_that_arrives_late_is_accepted_within_the_bound(self, tmp_path):
        surface = Surface(dialog_up=False, shows=tmp_path)
        dialog = adapter(surface, tmp_path, dialog_timeout_s=1.0, poll_s=0.25)
        original = surface._require_store_dialog
        # The surface comes up on the third poll: the bound is real, not decorative.
        state = {"polls": 0}

        def require():
            state["polls"] += 1
            surface.dialog_up = state["polls"] >= 3
            return original()

        surface._require_store_dialog = require  # type: ignore[method-assign]
        assert dialog.commit("point-01") is True
        assert state["polls"] == 3
