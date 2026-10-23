"""Selecting a dropdown entry by its **text**, and proving it took.

A column combo is a Delphi ``TComboBox``: it answers ``CB_SETCURSEL`` + ``CBN_SELCHANGE`` (measured
2026-10-23 — see the project skill's pitfalls), but it answers no ``CB_GETCOUNT``/``CB_GETLBTEXT``, so its
entries cannot be listed before they are visited.  Opening the list is worse than unnecessary: every pointer
route to it failed while the widget stayed selectable.

So the vocabulary is discovered by **stepping** — select index 0, read the text, index 1, read, and so on until
the text repeats, because these controls clamp at the last entry and a clamped step reports the same text
again.  The wanted entry is then chosen by its text, never by counting steps: the project's rule for combos is
that the text is the authority, and a build whose list is one entry longer or shorter must not move the value.

This module is pure: it is given a ``select`` and a ``read`` and settles between them.  Nothing here sends a
message or knows what a handle is.

**What it refuses**

- an entry the control never shows (``combo_entry_absent:<text>``) — after a bounded walk, never a guess;
- a selection whose read-back is not the wanted text (``combo_selection_did_not_take:<text>:<found>``):
  measured in one sitting, a write reported its new value immediately and a different one minutes later, so the
  read-back happens after a settle and a mismatch is a failure rather than a success.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from udv_echo_process.acquire.udop import AcquisitionError

__all__ = [
    "BOUNDED_WALK",
    "ComboSelection",
    "entry_index",
    "select_by_text",
    "vocabulary",
]

#: How many indices a walk may visit before it declares the list unbounded and stops.  A column combo has at
#: most a handful of entries; the bound exists so a control that never clamps is a refusal, not a hang.
BOUNDED_WALK = 32


@dataclass(frozen=True)
class ComboSelection:
    """What a selection is allowed to mean: the index chosen, the text, and the vocabulary it was found in."""

    text: str
    index: int
    entries: tuple[str, ...]
    readback: str
    steps: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def vocabulary(
    read: Callable[[], str],
    select: Callable[[int], None],
    settle: Callable[[], None],
    *,
    limit: int = BOUNDED_WALK,
) -> tuple[str, ...]:
    """Every entry the control shows, in index order, discovered by stepping it.

    A step whose text equals the previous one is the control's clamp: that index is the last entry, and the
    walk stops there.  Two identical neighbours in the *middle* of a list would be indistinguishable from a
    clamp, so a duplicated entry shortens the vocabulary rather than looping — the alternative is a control
    that can walk forever, which is the worse failure.
    """
    entries: list[str] = []
    previous: str | None = None
    for index in range(limit):
        select(index)
        settle()
        value = read()
        if index and value == previous:
            break
        entries.append(value)
        previous = value
    return tuple(entries)


def entry_index(entries: Sequence[str], text: str) -> int | None:
    """The index whose entry is exactly ``text``, or ``None``.

    Exact, never a prefix: the application's own combos filter by typed prefix, so a prefix match here would
    silently select a different entry whose name happens to start the same way.
    """
    for index, entry in enumerate(entries):
        if entry == text:
            return index
    return None


def select_by_text(
    text: str,
    *,
    read: Callable[[], str],
    select: Callable[[int], None],
    settle: Callable[[], None],
    limit: int = BOUNDED_WALK,
) -> ComboSelection:
    """Select the entry called ``text``, and prove it by reading the control back after a settle."""
    entries = vocabulary(read, select, settle, limit=limit)
    index = entry_index(entries, text)
    if index is None:
        raise AcquisitionError(f"combo_entry_absent:{text}")

    select(index)
    settle()
    readback = read()
    if readback != text:
        raise AcquisitionError(f"combo_selection_did_not_take:{text}:{readback}")

    return ComboSelection(text=text, index=index, entries=entries, readback=readback)
