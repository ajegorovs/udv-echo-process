"""The ``Operating parameters`` dialog's pure interpreter: its table, its facts, its refusals.

Layer 2 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5), moved out of
:mod:`udv_echo_process.acquire.driver` by Patch 2's widget slice. Nothing here enumerates a window,
sends a message, moves a cursor or presses anything: every function answers from already-resolved
rows and the text a reader states for them.

**What this module is the authority for**

- the dialog's **value table** and its widget-aware extraction (:func:`dialog_value_fields`) — the
  values are read by *position* (column band + row), and a row that offers a choice is read from
  the choice: a combo's own selection/text is the value, and an ``TSp_Edit`` inside or beside that
  row is **never** a fallback for it. The two state different physical quantities (measured: the
  burst row's combo states ``4`` while the ``TSp_Edit`` in the same row states ``89``, the
  sampling volume at 1460 m/s), so a fallback would hand a pre-run check a wrong measurement under
  the parameter's name and say nothing about it (ledger B09);
- the **dialog-panel predicate** (:func:`_is_dialog_panel`) and the geometry the two bindings are
  written in (:func:`bottom_row` — the bottom button band, addressed from the right — with
  :func:`_contains`, :func:`_column_bands`, :data:`DIALOG_COLUMN_GAP`, :data:`_DIALOG_MIN_W`,
  :data:`_DIALOG_MIN_CHILDREN`, :data:`_DIALOG_INPUT_CLASSES`);
- the **dialog-only facts** (:func:`dialog_fact`, :func:`dialog_only_reason`) — a fact is on the
  authority of a dialog *read*, never of this module;
- the three checks a reading must pass before any value is believed (:func:`dialog_channel_text`,
  :func:`dialog_refusal`) and the **channel comparison** (:func:`channel_mismatch`): the dialog
  states whose parameters it shows, and a dialog on another channel would attach that channel's
  burst, sound speed and first gate to this reading — invisibly, since every value is a plausible
  number (ledger B17).

**What belongs elsewhere**

- the walk into the dialog (``driver._descendants_of``) and every text read (``WM_GETTEXT``):
  Win32 reads, Patch 3's business;
- the gesture that opens and closes the dialog (``Win32Actuator._open_parameters_dialog`` /
  ``_close_parameters_dialog``) and the menu it is reached through
  (:mod:`udv_echo_process.acquire.ui.menu`);
- the write recipes for a field (``NUMERIC_WRITE_RECIPE``, ``driver._set_text_commit``), which are
  messages and stay in ``actuator``/``driver``.

Nothing here claims a value is what the *application* kept: a dialog can state a stale table until
it is re-opened (ledger B16), and the stored ``.BDD`` is the final authority — both are the read
recipes' business (``docs/dop3000/udop-automation.md``, ``acquire/verify.py``), not this module's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise

from udv_echo_process.acquire.actuator import (
    DIALOG_ANCHORS,
    DIALOG_COLUMN_ROWS,
    DialogField,
    ParamRole,
)
from udv_echo_process.acquire.snapshot import (
    DialogParameters,
    FactSource,
    InstrumentFact,
    unreadable,
)
from udv_echo_process.acquire.ui.menu import PARAMETERS_ENTRY

__all__ = [
    "DIALOG_COLUMN_GAP",
    "bottom_row",
    "channel_mismatch",
    "dialog_channel_text",
    "dialog_fact",
    "dialog_only_reason",
    "dialog_refusal",
    "dialog_value_fields",
    "text_at",
]

#: How wide a gap between two value fields' left edges makes them different **columns** of the
#: dialog's table. Measured 2026-09-18: fields inside one column sit within 5 px of each other
#: (786/783/788) while the columns are 200 px apart (786 → 987 → 1187), so anything from ~50 to
#: ~190 px separates them and the middle of that range is not a magic number but a margin.
DIALOG_COLUMN_GAP = 100

#: How a **dialog** is identified, from the reference's own predicate
#: (``recon/41_burst_sampling_volume.py``, ``find_dialog``): a panel that is not part of
#: the measurement layout, is wider than :data:`_DIALOG_MIN_W`, and is full of controls —
#: at least :data:`_DIALOG_MIN_CHILDREN` direct children, or holding a ``TSp_Browse``.
#: The measured operating dialog (627x384, read live) also holds input controls of its
#: own directly — a header combo and seven ``TSp_Value_Button`` fields — which is the same
#: kind of structural evidence and is accepted by the same predicate, so a dialog the
#: reference would have found is never rejected here.
_DIALOG_MIN_W, _DIALOG_MIN_CHILDREN = 400, 15

#: The classes that make a panel an *input* panel rather than a strip or a warning row.
_DIALOG_INPUT_CLASSES = ("TEdit", "TSp_Edit", "TComboBox", "TSp_Value_Button")


def _contains(outer: Mapping, inner: Mapping) -> bool:
    """True when ``inner``'s rect lies inside ``outer``'s, as the application lays them out."""
    return (
        outer["left"] <= inner["left"]
        and outer["top"] <= inner["top"]
        and inner["left"] + inner["w"] <= outer["left"] + outer["w"]
        and inner["top"] + inner["h"] <= outer["top"] + outer["h"]
    )


def _column_bands(lefts: Sequence[int]) -> list[int]:
    """Column index per left edge, splitting where the gap is wider than :data:`DIALOG_COLUMN_GAP`.

    The bands are derived rather than hard-coded so that the *rule* is evidence — the columns of
    this table are 200 px apart while fields inside one are within a few px (measured) — and the
    shape that comes out of it is then checked against :data:`DIALOG_COLUMN_ROWS`.
    """
    if not lefts:
        return []
    order = sorted(set(lefts))
    band = {order[0]: 0}
    for previous, current in pairwise(order):
        band[current] = band[previous] + (1 if current - previous > DIALOG_COLUMN_GAP else 0)
    return [band[left] for left in lefts]


def _is_dialog_panel(panel: dict, kids: Sequence[dict]) -> bool:
    """True when ``panel`` is one of this application's modal dialogs.

    The reference's own predicate, kept: a panel is a dialog when it is full of controls —
    at least :data:`_DIALOG_MIN_CHILDREN` direct children, or a ``TSp_Browse`` among them
    — and is wider than :data:`_DIALOG_MIN_W` (``recon/41_burst_sampling_volume.py``:
    ``len(kids) >= 15 or any(k["cls"] == "TSp_Browse" for k in kids)``, then
    ``dlg["w"] > 400``). The measured operating dialog (627x384) holds a header combo and
    seven value buttons *directly*, so holding input controls of its own
    (:data:`_DIALOG_INPUT_CLASSES`) is the same kind of evidence and is accepted here too:
    a dialog the reference would have found is never rejected by this driver.
    """
    if panel["w"] <= _DIALOG_MIN_W:
        return False
    if len(kids) >= _DIALOG_MIN_CHILDREN:
        return True
    if any(k["cls"] == "TSp_Browse" for k in kids):
        return True
    return any(k["cls"] in _DIALOG_INPUT_CLASSES for k in kids)


def bottom_row(panel: dict, kids: Sequence[dict], margin: int = 70) -> list[dict]:
    """The panel's own bottom button band, left -> right.

    A dialog's button pair is identified by sitting in the panel's last ``margin``
    pixels — never by title and never by a rect stated in logic (``recon/41``, which
    used 60 px; the band is a *band*, so it also holds whatever else this application
    paints low and wide in a dialog, e.g. the operating dialog's two indicator buttons
    "No emission on Probe In/Out" and "Use US coupling parameters"). The pair is
    therefore addressed from the **right** (:meth:`…Win32Actuator._dialog_button`), never
    by taking the leftmost entry as "the first button".
    """
    floor = panel["top"] + panel["h"] - margin
    return sorted(
        (k for k in kids if k["cls"] == "TSp_Button" and k["top"] > floor),
        key=lambda k: k["left"],
    )


def dialog_value_fields(
    children: Sequence[Mapping], read_text
) -> list[dict[str, object]]:
    """The dialog's value table as ``(column, row)`` fields, with the text each one states.

    A field is one row of that table: the ``TComboBox`` a row offers when it has one — a parameter
    chosen from a list, which is what the burst length, the sensitivity and the sampling volume
    are — and otherwise the ``TSp_Edit`` beside it. That rule is *measured* rather than preferred:
    at ``burst = 4`` the row reads a combo ``'4'`` with an inner ``'4'`` **and** a ``TSp_Edit``
    ``'89'``, and the ``89`` is the value beside it rather than the parameter (the corpus' sampling
    volume at 1460 m/s is 0.876 mm, and the campaign declares the ``4``). Rows are the
    ``TSp_Value_Button`` widgets, and a field's identity is its **position**: the column is the
    band its left edge falls in — the measured bands are the value edits' lefts, 786 / 987 / 1187 px
    in a dialog at 655,364 — and inside a column, top to bottom. Never an id, never a caption:
    every one of these widgets is caption-less (measured through ``WM_GETTEXT`` as well as
    ``GetWindowText``, 2026-09-18) and control ids change on every launch.

    **When a row offers a choice, the choice is the row's value — and the edit beside it is never a
    fallback for it.** The two controls state *different physical quantities*: measured, at the
    burst row the combo states ``4`` while the ``TSp_Edit`` inside the same row states ``89``, the
    sampling volume at 1460 m/s (the corpus' own number for the campaign's declared burst). A reader
    that fell back to the edit on an attempt where the choice could not be read would hand a pre-run
    check a different measurement under the parameter's name with nothing in the reading to say so —
    and it would say it confidently: measured against this tree with the choice blanked, the fallback
    answers ``TSp_Edit '89'`` for the burst, and :meth:`DialogParameters.readable` comes back
    ``True`` because all three facts are "present". So a choice that states nothing leaves the row
    stating nothing: the fact built from it is unreadable and the reading does not claim it.

    Only controls **inside** a value button count, which is what keeps the channel field out of
    the table: the dialog's header combo sits above every button (measured ``top`` 373 against the
    table's 443), and reading it as a field would put the channel in the middle of the parameter
    order.

    An empty table is answered with an empty list and not an error: a dialog that has not built its
    value buttons yet is a state this read has to *report* (measured on the running application: the
    first open after a restart can come back with no table at all), and a crash inside the reader
    would take the whole snapshot down over a fact that is merely unread.
    """
    buttons = sorted(
        (row for row in children if row.get("cls") == "TSp_Value_Button"),
        key=lambda row: (row["left"], row["top"]),
    )
    fields: list[dict[str, object]] = []
    for button in buttons:
        inside = [
            row
            for row in children
            if row.get("cls") in ("TSp_Edit", "TComboBox") and _contains(button, row)
        ]
        if not inside:
            continue
        combo = next((row for row in inside if row.get("cls") == "TComboBox"), None)
        field = combo if combo is not None else inside[0]
        fields.append(
            {
                "left": field["left"],
                "top": button["top"],
                "cls": field["cls"],
                "hwnd": field["hwnd"],
                "value": read_text(field["hwnd"]),
            }
        )
    columns = _column_bands([int(row["left"]) for row in fields])
    for row, column in zip(fields, columns, strict=True):
        row["column"] = column
    ordered: list[dict[str, object]] = []
    for column in sorted(set(columns)):
        band = sorted(
            (row for row in fields if row["column"] == column), key=lambda row: row["top"]
        )
        for index, row in enumerate(band):
            ordered.append({**row, "row": index})
    return ordered


def text_at(
    fields: Sequence[Mapping], column: int, row: int, read_text: Callable[[int], str]
) -> str:
    """The text stated at ``(column, row)`` of the dialog's table, or ``""``."""
    for field in fields:
        if int(field["column"]) == column and int(field["row"]) == row:
            return read_text(int(field["hwnd"]))
    return ""


def dialog_channel_text(
    kids: Sequence[Mapping], fields: Sequence[Mapping], read_text: Callable[[int], str]
) -> str:
    """The channel the dialog is showing, read from its header combo.

    The header is the combo that is **not** a table row (measured: it sits at the dialog's top,
    ``top`` 373 against the table's 443). It is read because the dialog — not the caller — is
    the surface that decides whose parameters are shown: a reading that did not carry it would
    let a compile compare one channel's sound speed against another channel's run, which is the
    channel trap this driver already refuses to make when it stores a block (docs/16 §12).
    """
    rows = {field["hwnd"] for field in fields}
    headers = [
        row
        for row in kids
        if row.get("cls") == "TComboBox" and row.get("hwnd") not in rows
    ]
    if not headers:
        return ""
    top = min(headers, key=lambda row: row["top"])
    return read_text(int(top["hwnd"]))


def dialog_only_reason(name: str) -> str:
    """Why a fact that lives in the ``Operating parameters`` dialog has no screen read path.

    ``first_gate_depth``, ``burst_length``, ``sound_speed`` and ``sampling_volume`` have no
    parameter-column field at all (:data:`…actuator.DIALOG_ONLY_PARAMETERS`): the column is the
    surface a *point* writes, and a point never writes these — they are read once per channel, from
    the dialog. The reason is written out rather than summarised, because it lands in a run record
    read by someone who has no instrument in front of them.
    """
    return (
        f"{name!r} has no parameter-column field: it is set in the {PARAMETERS_ENTRY!r} "
        "dialog only, so nothing on the measurement screen states it"
    )


def dialog_fact(parameters: DialogParameters | None, field: DialogField) -> InstrumentFact:
    """One dialog-only fact, on the authority of a dialog *read* — or of nothing at all.

    The same rule the channel is held to (:meth:`Win32Actuator._channel_fact`): the reader that
    opened the dialog is a *step*, and this reading cannot claim what no step established. A
    snapshot taken without one carries the fact as ``unreadable``, which is a true statement about
    the run — the alternative, reading the dialog here, would make this method press things, and a
    reading that presses is no longer something an instrument somebody else is using can be read
    with.
    """
    if parameters is None:
        return unreadable(
            f"{dialog_only_reason(field.value)} — and no read of that dialog was handed to this "
            "snapshot, so nothing established it (read_dialog_parameters reads it, and a caller "
            "that wants this fact has to have paid for that step)"
        )
    value = parameters.value(field.value)
    if value is None:
        return unreadable(
            parameters.reason
            or f"the {PARAMETERS_ENTRY!r} dialog stated no {field.value!r}, so there is nothing "
            "to compare it with"
        )
    return InstrumentFact(value=value, source=FactSource.READ, reason=parameters.reason or None)


def dialog_refusal(
    fields: Sequence[Mapping],
    channel: str,
    *,
    read_text: Callable[[int], str],
    screen_text: Callable[[ParamRole], str],
    timeout_s: float,
) -> str:
    """Why no dialog-only fact may be believed, or ``""`` when the reading may be trusted.

    Every refusal is written out in full rather than summarised: the reason lands in a run
    record read by someone with no instrument in front of them, and "the dialog did not read"
    would leave them unable to tell a stale binding from an application that was busy.

    ``read_text`` states a *dialog* control's text and ``screen_text`` the measurement screen's
    own text for an anchor role, so this rule holds for the live driver and for a captured tree
    alike — the two reads are the only things that need a window. ``timeout_s`` is the wait the
    caller actually gave the table (``driver.DIALOG_FILL_TIMEOUT_S``), *passed in* rather than
    imported so the reason a reading gives always matches the wait a run performed.
    """
    if not any(field["value"] for field in fields):
        built = (
            "built no value buttons at all"
            if not fields
            else "built its value buttons but stated nothing in them"
        )
        return (
            f"the {PARAMETERS_ENTRY!r} dialog {built} within {timeout_s:g} s of "
            "being opened, so there is no table to bind: a freshly started application builds "
            "this table empty (or not at all) the first time it is opened (measured), and an "
            "empty field is not a value"
        )
    columns = tuple(sorted({int(field["column"]) for field in fields}))
    counts = tuple(
        sum(1 for field in fields if int(field["column"]) == column) for column in columns
    )
    if counts != DIALOG_COLUMN_ROWS:
        return (
            f"the {PARAMETERS_ENTRY!r} dialog built {counts} value fields per column where "
            f"this driver's bindings were measured against {DIALOG_COLUMN_ROWS}: these fields "
            "are read by position, so a different shape is not the table they were bound in, "
            "and nothing in it is read"
        )
    if not channel:
        return (
            f"the {PARAMETERS_ENTRY!r} dialog stated no channel, so a read of it could not say "
            "which channel's parameters these are"
        )
    for role, column, row in DIALOG_ANCHORS:
        dialog_text = text_at(fields, column, row, read_text)
        screen_state = screen_text(role)
        if not dialog_text or not screen_state:
            return (
                f"the {PARAMETERS_ENTRY!r} dialog could not be checked against the screen: "
                f"{role.value!r} is the anchor at column {column}, row {row}, and it is not "
                "stated on both surfaces, so the positions the dialog-only facts are read at "
                "could not be confirmed"
            )
        if dialog_text != screen_state:
            return (
                f"the {PARAMETERS_ENTRY!r} dialog disagrees with the measurement screen about "
                f"{role.value!r}: the dialog reads {dialog_text!r} where the column reads "
                f"{screen_state!r}, so this dialog is not the table these bindings were "
                "measured against and nothing in it is read"
            )
    return ""


def channel_mismatch(
    routed_channel: int | None, dialog_parameters: DialogParameters | None
) -> str | None:
    """The refusal for a dialog reading that describes a channel this reading was not routed to.

    The dialog-only facts are read *for the channel the dialog states* and the point is stored
    on the channel the run routed. The two values meet only here, so this is the one place the
    mismatch can be caught before anything is attributed — and the one place it would otherwise
    be invisible: a channel-2 burst, sound speed and first gate attached to a channel-1 reading
    read as channel 1's parameters, in the record and in everything downstream of it (ledger B17,
    the wrong-channel trap, plan §14).

    What is **not** compared matters as much as what is. Nothing is compared when nothing was
    routed — there is no second channel to disagree with — and nothing is compared against a
    *refused* reading: a dialog that could not be opened, or stated no channel, already carries
    the reason it establishes nothing, and the campaign turns that reason into its own refusal.
    This module returning instead of raising is the same rule: a reading that failed established no
    channel's facts, and a refusal this rule cannot substantiate would replace a precise reader
    diagnostic with a vaguer one (plan §16.1).
    """
    if routed_channel is None:
        return None
    if dialog_parameters is None or dialog_parameters.reason:
        return None
    stated = dialog_parameters.channel.strip()
    if not stated or stated == str(routed_channel):
        return None
    return (
        f"the {PARAMETERS_ENTRY!r} dialog states channel {stated} while this reading was "
        f"routed to channel {routed_channel}: the burst length, the sound speed and the first "
        f"gate it states are channel {stated}'s parameters, and attributing them to a "
        f"channel-{routed_channel} reading would record them as that channel's own — nothing "
        "after this reading can tell the two apart, so it is refused rather than attributed"
    )
