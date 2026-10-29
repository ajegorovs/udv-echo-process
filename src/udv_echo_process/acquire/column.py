"""Which entries a point may ask for in the parameter column's dropdowns, and the report of one change.

The two column combos are not ``ParamRole`` values: they are chosen from a list, they are per-channel state
rather than a measurement window, and a ``ParameterSet`` deliberately carries neither (a campaign file that
names a sensitivity is refused by the models).  So they get their own small vocabulary here instead of being
smuggled into the parameter set, and their own report, which is the evidence a caller keeps.

``COLUMN_COMBOS`` is the app's own order, top to bottom, and it is the order a write runs in — the TGC mode is
**not** in it: that one lives in a dialog, and changing it resets the receiver settings below it in the
column (measured 2026-10-23), so it is a separate step that goes first.
"""

from __future__ import annotations

from pydantic import Field

from udv_echo_process.models.base import ValueModel

__all__ = ["COLUMN_COMBOS", "REQUESTABLE_COMBOS", "ColumnChange", "ColumnReport"]

#: The column's dropdowns in the order the application draws them.
COLUMN_COMBOS: tuple[str, ...] = ("Sensitivity", "Emitting power")

#: The subset a command may set by name.  Kept separate so the tuple above stays a statement about the
#: layout and this one about the interface: adding a widget to the column must not silently become an
#: argument somebody can pass.
REQUESTABLE_COMBOS: tuple[str, ...] = ("Sensitivity", "Emitting power")


class ColumnChange(ValueModel):
    """One dropdown's transition, and the vocabulary it was found in.

    ``before`` and ``readback`` are both read from the widget, so a caller can tell a change that happened
    from one that was already in place.  ``entries`` is what the walk discovered, kept because it is the only
    record of a list the application cannot be asked to enumerate.
    """

    combo: str = Field(min_length=1)
    requested: str = Field(min_length=1)
    before: str = ""
    readback: str = ""
    index: int = Field(ge=0)
    entries: tuple[str, ...] = ()
    changed: bool = False


class ColumnReport(ValueModel):
    """What one ``column`` command carried back: per-dropdown transitions and whether all of them held."""

    channel: int | None = None
    changes: tuple[ColumnChange, ...] = ()
    verified: bool = False

    @property
    def settled(self) -> tuple[str, ...]:
        """The combos whose read-back is the requested text."""
        return tuple(change.combo for change in self.changes if change.readback == change.requested)
