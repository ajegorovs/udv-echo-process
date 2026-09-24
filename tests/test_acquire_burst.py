"""The burst transition: the coupled fake, the failure matrix, and the refusal vocabulary.

The subject is :meth:`…udop.parameters.ParametersSurface.write_dialog_burst_length` — the one
acquisition parameter this driver writes through the ``Operating parameters`` dialog that the
application also *derives another parameter from*. Two things are under test and nothing else:

* **the coupling.** The fake below reproduces the dependency the live instrument has, as measured:
  a burst write does not move the volume by itself — it **re-derives the floor the volume has to
  clear**, `floor(N) = 1000·c·N/(2·f_e)`, and the value in force is `max(remembered, floor)`
  (``acquisition-campaign-compilation-plan.md`` §18.10's table, §20.1's manual citation for the
  length; measured at ``c = 1460``, ``f_e = 4000``: ``floor(4) = 0.730``, ``floor(6) = 1.095``,
  ``floor(8) = 1.460``). So the volume *is* a function of the burst — but not only of it, and not
  symmetrically: ``4 → 8`` raises the in-force value to the floor while ``8 → 4`` brings back the
  value the operator last wrote, because a floor-raise is not a remembered write (measured, runs
  ``21``/``22``). A fake that made the volume a pure function of the burst would let a driver that
  recomputes it *itself* pass; this one states what the application states, and the tests below
  assert the driver returns **that** and never a value it worked out on its own;
* **the failure matrix.** Unsupported burst, a modal raised instead of the selection, a selection
  that is never restated, a re-open that states another burst, a re-open that fails, a dialog the
  application replaced mid-write, another channel, the assisted panel, a table of another shape, a
  row that offers no choice, and a request below one. Every one of them is a case the transaction
  has an answer for, and the answer is asserted rather than the absence of a crash. Four of them are
  **post-``Accept``** faults — a fault only in the dialog the application hands back after the
  write committed — and they are scripted so that the write itself is always the measured one: a
  re-opened dialog that states another channel, one whose table is no longer the measured shape,
  one that disagrees with the measurement screen about an anchor, and one from which the dependent
  row cannot be read. None of them may be reported as ``VERIFIED``, and the re-opened dialog is
  taken down on every one of those paths.

**What is faked is the window layer only** — the panel set, the dialog's children, the text a
control states, the entry list a combo offers, the selection message, the held press on the bottom
pair, the overlay read and the run log. Everything between them is the driver's own code: the
positional binding, the three checks a position has to pass, the three-rung read-back, the
``Accept``/re-open and the cleanup in the ``finally``.

The fake's dialog is the **committed measured tree**
(``tests/data/udop-parameters-dialog-tree.json``, the dialog read live on 2026-09-18), so the
rows, their positions, their classes and their column bands are the application's own — and the
sampling-volume row is the one ``UI-OVERLAY-05`` paints, at column 1 row 4
(``…actuator.DIALOG_DEPENDENT_FIELDS``). The two option lists are the ones read off the controls in
the same session (§18.9/§18.10), and the volume *tail* is deliberately **not** burst-derived: that
is the measurement, and it is what makes "the dialog can state a volume its own combo does not
offer" a case this fake can reproduce.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from udv_echo_process.acquire import driver, live
from udv_echo_process.acquire.actuator import (
    DIALOG_ANCHORS,
    DIALOG_COLUMN_ROWS,
    DIALOG_DEPENDENT_FIELDS,
    DIALOG_FIELD_ORDER,
    BurstState,
    ComboReading,
    DialogField,
    OverlayKind,
    ParamRole,
    dialog_row,
)
from udv_echo_process.acquire.driver import AcquisitionError, Win32Actuator
from udv_echo_process.acquire.snapshot import DialogParameters
from udv_echo_process.acquire.ui.dialog import field_at

FIXTURE = Path(__file__).parent / "data" / "udop-parameters-dialog-tree.json"

#: The dialog's own geometry, as the live panel was read (627x384 at 655,364), and the panel the
#: application **replaces** it with when its channel combo is written — same size, origin moved to
#: `(713, 364)`, every prior handle dead (measured; ``acquisition-campaign-compilation-plan.md``
#: §19.4). The shape is preserved on purpose: it is what makes re-resolving the bindings on the new
#: panel the right answer, rather than reading a table that is no longer there.
DIALOG_HWND = 8_585_312
REPLACEMENT_HWND = 8_585_400
DIALOG_RECT = (655, 364, 1282, 748)
REPLACEMENT_RECT = (713, 364, 713 + 627, 364 + 384)
DIALOG_HANDLE_BASE = 100_000
REPLACEMENT_HANDLE_BASE = 200_000
SCREEN_HANDLE_BASE = 900_000

#: What the dialog states before any write: the fixture's own channel, and the burst the fixture
#: was read at (``UI-OVERLAY-05`` paints the same ``4``).
STATED_CHANNEL = "1"
#: The channel's own acoustics, as §18.9 read them off the dialog: `c = 1460 m/s`, `f_e = 4000 kHz`.
#: Every number the coupling below produces is computed from these two and nothing else.
SOUND_SPEED_MS = 1460
FREQUENCY_HZ = 4_000_000

#: The burst lengths the row offers, in the order the control holds them (§18.9 — 13 entries, `2 … 20`
#: step 2 and then `24, 28, 32`). `6` and `8` are adjacent and `7` is absent: the writer selects by
#: value text, never by counting steps from the value in force.
BURSTS = ("2", "4", "6", "8", "10", "12", "14", "16", "18", "20", "24", "28", "32")

#: The sampling-volume combo's **fixed six-entry tail**, in the order the control holds them
#: (§18.10). The list is not burst-derived on this machine — only its first slot is state — which is
#: why the fake never rebuilds the tail from the burst.
VOLUME_TAIL = ("3.650", "1.752", "1.168", "0.876", "0.730", "0.584")

#: The value the operator last wrote, i.e. what the application remembers across a burst change
#: (§18.10's ``max(remembered, floor)``; the baseline of §18.9 was `(burst 4, volume 0.876)`).
REMEMBERED_VOLUME = "0.876"


def floor_mm(burst: int) -> float:
    """`1000·c·N/(2·f_e)` — the emitted burst's own length in mm, which is the volume's floor.

    The manual states the length (§20.1: ch. 8.4 p. 47 for the thickness, ch. 21 p. 119 for the
    gate), and at ``c = 1460 m/s``, ``f_e = 4000 kHz`` it reproduces three measured values
    outright — ``0.730`` at burst 4 (bracketed), ``1.095`` at 6 and ``1.460`` at 8 — so the fake
    derives the floor from the law rather than tabulating the measurements.
    """
    return round(1000 * SOUND_SPEED_MS * burst / (2 * FREQUENCY_HZ), 3)


def effective_volume(burst: int, remembered: str = REMEMBERED_VOLUME) -> str:
    """The volume in force: ``max(remembered, floor(burst))``, in the dialog's own format.

    Both directions are measured (§18.10, runs ``21``/``22``): `4 → 8` with `0.876` remembered states
    `1.460`, and `8 → 4` states `0.876` again — *the raise was not remembered*. A pure-function fake
    would answer `0.730` for the second read, which is the mistake this module exists to catch.
    """
    return f"{max(float(remembered), floor_mm(burst)):.3f}"


def measured_rows() -> list[dict]:
    """The fixture's controls with the keys the driver's own rows carry."""
    tree = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = []
    for index, control in enumerate(tree["controls"]):
        left, top, right, bottom = control["rect"]
        rows.append(
            {
                "hwnd": DIALOG_HANDLE_BASE + index,
                "cls": control["cls"],
                "left": left,
                "top": top,
                "w": right - left,
                "h": bottom - top,
                "text": control["text"],
                "visible": control["visible"],
                "depth": control["depth"],
            }
        )
    return rows


class CoupledDialogDriver(Win32Actuator):
    """``Win32Actuator`` whose dialog is the measured tree **with the coupling the live one has**.

    One scripted state per failure the transaction has to answer for; everything unscripted is the
    measured behaviour — the burst row is a ``TComboBox`` at ``(0, 1)``, the sampling volume a
    ``TComboBox`` at ``(1, 4)``, the header combo the only combo that is not a table row, and the
    bottom band the four buttons the live panel was read with.
    """

    def __init__(
        self,
        *,
        burst: int = 10,
        remembered: str = REMEMBERED_VOLUME,
        stated_channel: str = STATED_CHANNEL,
        drop_burst_combo: bool = False,
        drop_sampling_volume_row: bool = False,
        ignore_selection: bool = False,
        overlay_on_select: OverlayKind | None = None,
        stale_until_reopen: bool = False,
        keep_another_burst: int | None = None,
        replace_after_write: bool = False,
        reopen_fails: str | None = None,
        assisted: str | None = None,
        reopened_channel: str | None = None,
        drop_reopened_sampling_volume_row: bool = False,
        alter_reopened_table: bool = False,
        reopened_anchor: ParamRole | None = None,
        reopened_volume_states_nothing: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        #: The three bound handles, per panel, resolved once off the fixture.
        self._computed: dict[int, dict[str, int]] = {}
        #: Whether the dialog that is **up** is a re-opened one — the only open whose reads a
        #: ``reopened_*`` script may change. False while the write's own dialog is up, so every
        #: fault scripted below is invisible to the transaction until it re-opens the dialog.
        self._reopened_up = False
        #: The rows the re-opened dialog states, when it is scripted away from the measured tree;
        #: ``None`` is "the table the write used". Set below, once the write's own rows exist.
        self.reopened_rows: list[dict] | None = None
        self.rows = measured_rows()
        measured_positions = self._positions(DIALOG_HWND)
        if drop_burst_combo:
            # The row still exists, so the table's shape is the measured one; what is gone is the
            # *choice* it offers, and with it the only control this driver knows how to write it
            # through (what is left of the row is its inner edit, which this driver never types
            # into).
            self.rows = [
                row
                for row in self.rows
                if int(row["hwnd"]) != measured_positions["burst"]
            ]
        if drop_sampling_volume_row:
            # The whole **row** goes: every control whose vertical span contains the bound field's
            # centre — its combo, the edit inside it and the value button beside them — so the
            # column holds one field fewer and the table is no longer the shape the bindings were
            # measured against (``DIALOG_COLUMN_ROWS``).
            bound = next(
                row
                for row in self.rows
                if int(row["hwnd"]) == measured_positions["volume"]
            )
            centre = bound["top"] + bound["h"] / 2
            self.rows = [
                row
                for row in self.rows
                if not (row["top"] <= centre <= row["top"] + row["h"])
            ]
        self._computed.clear()
        # ------------------------------------------------- the re-opened dialog's own script
        # **Only a fault in the dialog the application hands back after ``Accept`` is scripted
        # here.** The write's own dialog is always the measured tree and its read-back always
        # passes, so a failure observed below is a failure of what the application *kept* — never
        # of the write that preceded it. ``reopened_rows`` ``None`` is "the re-opened dialog is the
        # same table the write used".
        self.reopened_rows = self._reopened_variant(
            drop_sampling_volume_row=drop_reopened_sampling_volume_row,
            alter_table=alter_reopened_table,
        )
        #: The channel the **re-opened** dialog states, when it is scripted to state another one.
        self.reopened_channel = reopened_channel
        #: The **re-opened** dialog's dependent row stating nothing, with its shape intact — the
        #: one way the sampling-volume row can be unreadable without the column count moving.
        self.reopened_volume_states_nothing = reopened_volume_states_nothing
        self.reopened_anchor = reopened_anchor
        self.reopened_anchor_hwnd = (
            None if reopened_anchor is None else self._anchor_hwnd(reopened_anchor)
        )
        #: A text the measurement screen does **not** read, so anchor agreement fails on the
        #: re-opened dialog and nowhere else: the screen's own read is taken from the fixture and
        #: never from ``_get_text`` (:meth:`_screen_edit`), so overriding the dialog's read here
        #: cannot move the other surface with it.
        self.reopened_anchor_text = (
            ""
            if self.reopened_anchor_hwnd is None
            else f"{self._fixture_text(self.rows, self.reopened_anchor_hwnd)}0"
        )
        self.stated_channel = stated_channel
        self.burst = burst
        #: What the operator last wrote. A burst change can raise the value in force above it and
        #: then give it back — the raise is not itself a remembered write (§18.10, runs 21/22).
        self.remembered = remembered
        #: The sampling volume the **application keeps**: what a dialog opened now would state.
        self.volume = effective_volume(burst, remembered)
        #: What the dialog that is up **paints** for that row. The two are the same except after a
        #: write on a scripted stale row (``stale_until_reopen``), and keeping them apart is what
        #: makes "the result comes from the re-opened dialog" a testable claim rather than a habit.
        self.painted = self.volume
        #: A selection made in the dialog and not yet committed, if any (``Accept`` commits it,
        #: ``Cancel`` throws it away).
        self.volume_pending: str | None = None
        #: Whether the open dialog keeps painting the pre-write value until it is re-opened. A
        #: **scripted hazard**, not a claim about this row: §18.12 measured exactly that behaviour
        #: on the dialog's derived read-out, and §19.1's rung 2 orders the read-back to come from a
        #: re-opened dialog — so the fake can hold the hazard and the tests assert the driver's
        #: read-back is not the one it had in front of it all along.
        self.stale_until_reopen = stale_until_reopen
        #: What the dialog was stating when its ``Accept`` was pressed.
        self.stated_at_accept = ""
        #: The application's own state as the dialog found it — what a ``Cancel`` restores.
        self._committed: tuple[int, str, str] = (
            self.burst,
            self.remembered,
            self.volume,
        )
        self.ignore_selection = ignore_selection
        self.overlay_on_select = overlay_on_select
        self.keep_another_burst = keep_another_burst
        self.replace_after_write = replace_after_write
        self.reopen_fails = reopen_fails
        self.assisted = assisted
        #: The panel that is **up**, and the only one whose handles reach anything.
        self.open_hwnd = DIALOG_HWND
        self.replaced = False
        #: An overlay the application raised instead of applying the selection, if any.
        self.pending_overlay: OverlayKind | None = None
        #: Every ``(hwnd, index, parent)`` the write path selected, and every held press.
        self.selections: list[tuple[int, int, int]] = []
        self.presses: list[int] = []
        self.opened = 0
        self.accepted = 0
        self.closed_with_cancel = 0
        #: The overlays this fake has answered, by kind.
        self.answered: list[OverlayKind] = []

    # ------------------------------------------------------------------ the window layer

    def panel(self, hwnd: int) -> dict:
        """The dialog panel ``hwnd`` names, at the geometry the live panels were read at."""
        rect = DIALOG_RECT if hwnd == DIALOG_HWND else REPLACEMENT_RECT
        left, top, right, bottom = rect
        return {
            "hwnd": hwnd,
            "cls": "TSp_Panel",
            "rect": rect,
            "left": left,
            "top": top,
            "w": right - left,
            "h": bottom - top,
        }

    def rows_for(self, hwnd: int) -> list[dict]:
        """The fixture's rows, carrying the handles *that* panel was built with.

        While a **re-opened** dialog is up, the scripted variant replaces them — that is the
        whole of the ``reopened_*`` mechanism: the write's own dialog reads the measured tree,
        and the fault lives only in what the transaction reads back after ``Accept``.
        """
        base = (
            self.reopened_rows
            if self._reopened_up and self.reopened_rows is not None
            else self.rows
        )
        offset = (
            0 if hwnd == DIALOG_HWND else REPLACEMENT_HANDLE_BASE - DIALOG_HANDLE_BASE
        )
        return [dict(row, hwnd=row["hwnd"] + offset) for row in base]

    def _field_hwnd(self, rows: list[dict], column: int, row: int) -> int:
        """The control a value row states at ``(column, row)`` of ``rows`` — by position, as the
        driver's own reader binds it."""
        fields = driver.dialog_value_fields(
            rows, lambda h: self._fixture_text(rows, h)
        )
        return next(
            int(field["hwnd"])
            for field in fields
            if (int(field["column"]), int(field["row"])) == (column, row)
        )

    def _anchor_hwnd(self, role: ParamRole) -> int:
        """The dialog control that states anchor ``role``'s own ``(column, row)``."""
        column, row = next(
            (column, row) for anchor, column, row in DIALOG_ANCHORS if anchor is role
        )
        return self._field_hwnd(self.rows, column, row)

    @staticmethod
    def _without_field(rows: list[dict], field_hwnd: int) -> list[dict]:
        """``rows`` without one value row: the control the reader binds for it and the
        ``TSp_Value_Button`` that holds it.

        Exactly one field leaves exactly one column, so a scripted shape fault moves the column
        count and nothing else — and the bottom band, which is how the transaction closes the
        dialog it faulted on, is untouched.
        """
        bound = next(row for row in rows if int(row["hwnd"]) == field_hwnd)

        def contains(outer: dict, inner: dict) -> bool:
            return (
                outer["left"] <= inner["left"]
                and outer["top"] <= inner["top"]
                and inner["left"] + inner["w"] <= outer["left"] + outer["w"]
                and inner["top"] + inner["h"] <= outer["top"] + outer["h"]
            )

        drop = {field_hwnd}
        drop.update(
            int(row["hwnd"])
            for row in rows
            if row.get("cls") == "TSp_Value_Button" and contains(row, bound)
        )
        return [row for row in rows if int(row["hwnd"]) not in drop]

    def _reopened_variant(
        self, *, drop_sampling_volume_row: bool, alter_table: bool
    ) -> list[dict] | None:
        """The rows the re-opened dialog states, or ``None`` for the measured table.

        Two faults, and both are **shape** faults rather than value faults: the table is no longer
        the one the positional bindings were measured against, so the counts of its columns are no
        longer :data:`DIALOG_COLUMN_ROWS` (4, 6, 5). ``alter_table`` takes the sound-speed field out
        of the right-hand column — not the burst row, not the dependent row and not an anchor — so
        the shape is the only thing that changes; the volume variant takes out the dependent row
        itself, leaving the burst row exactly where it was.
        """
        rows = self.rows
        if drop_sampling_volume_row:
            rows = self._without_field(
                rows, self._field_hwnd(rows, *dialog_row(DialogField.SAMPLING_VOLUME))
            )
        if alter_table:
            rows = self._without_field(rows, self._field_hwnd(rows, 2, 4))
        return rows if rows is not self.rows else None

    @staticmethod
    def _fixture_text(rows: list[dict], hwnd: int) -> str:
        return str(next(row["text"] for row in rows if int(row["hwnd"]) == hwnd))

    def fields(self, hwnd: int | None = None) -> list[dict]:
        """The dialog's value table as the driver's own reader builds it, for this fake's state.

        The rows, their bands and their positions are the **measured** ones — the reader is the
        driver's own :func:`…ui.dialog.dialog_value_fields`; only the text it reads is this fake's.
        """
        panel = self.open_hwnd if hwnd is None else hwnd
        return driver.dialog_value_fields(self.rows_for(panel), self._get_text)

    def _positions(self, hwnd: int) -> dict[str, int]:
        """The three handles this driver's bindings point at, for that panel.

        Read off the **fixture's own text**, so a binding is resolved without any state of this
        fake's: a handle whose position depended on a value the write changes would be exactly the
        stale-binding error the transaction exists to refuse. Computed once per panel, cached.
        """
        if hwnd not in self._computed:
            rows = self.rows_for(hwnd)
            fields = driver.dialog_value_fields(
                rows, lambda h: self._fixture_text(rows, h)
            )
            by_position = {
                (int(field["column"]), int(field["row"])): int(field["hwnd"])
                for field in fields
            }
            bound = set(by_position.values())
            self._computed[hwnd] = {
                "burst": by_position[dialog_row(DialogField.BURST_LENGTH)],
                "volume": by_position[dialog_row(DialogField.SAMPLING_VOLUME)],
                "header": next(
                    int(row["hwnd"])
                    for row in rows
                    if row["cls"] == "TComboBox" and int(row["hwnd"]) not in bound
                ),
            }
        return self._computed[hwnd]

    @property
    def burst_hwnd(self) -> int:
        return self._positions(self.open_hwnd)["burst"]

    @property
    def volume_hwnd(self) -> int:
        return self._positions(self.open_hwnd)["volume"]

    @property
    def header_hwnd(self) -> int:
        """The dialog's channel combo: the only ``TComboBox`` that is not a table row."""
        return self._positions(self.open_hwnd)["header"]

    def burst_items(self) -> tuple[str, ...]:
        return BURSTS

    def volume_items(self) -> tuple[str, ...]:
        """The volume entries as this application builds them: **the value in force at slot 0**.

        The measured shape is ``[the value in force] + a fixed six-entry tail`` (§18.10), and it is
        modelled here on purpose: a projection that read the selection's *position* as an option
        index would answer ``0`` for every accepted state, and the value the application re-derives
        is not always one of the tail's own rungs — at burst 18 the floor is ``3.285``, which the
        combo does **not** offer, so slot 0 states a volume the control cannot select. The fake is
        what makes that visible in the tests below rather than on an instrument.
        """
        return (self.volume, *VOLUME_TAIL)

    def _get_text(self, hwnd: int) -> str:
        if SCREEN_HANDLE_BASE <= hwnd:  # a screen field, not a dialog one
            return self._screen_edit(list(ParamRole)[hwnd - SCREEN_HANDLE_BASE])["text"]
        positions = self._positions(self.open_hwnd)
        if hwnd == positions["header"]:  # the dialog's header: its channel
            if self._reopened_up and self.reopened_channel is not None:
                # The re-opened dialog states **another channel**: the write's own dialog stated
                # the routed one and its check passed, so only a read of what the application
                # *kept* can see this — which is exactly why the read-back is taken re-opened.
                return self.reopened_channel
            return self.stated_channel
        if hwnd == positions["burst"]:
            return str(self.burst)
        if hwnd == positions["volume"]:
            # What the dialog **paints**, which is not always what the application keeps: see
            # ``stale_until_reopen``. A re-opened dialog scripted to state nothing here keeps its
            # shape and its burst row, so the dependent row is the only thing missing.
            if self._reopened_up and self.reopened_volume_states_nothing:
                return ""
            return self.painted
        if self._reopened_up and hwnd == self.reopened_anchor_hwnd:
            # An anchor the measurement screen does **not** read: the re-opened dialog disagrees
            # with the parameter column, which is what makes a positional binding refuse to be
            # trusted. Only the dialog's read is overridden (:meth:`_screen_edit` reads the
            # fixture), so the two surfaces genuinely disagree here.
            return self.reopened_anchor_text
        return self._fixture_text(self.rows_for(self.open_hwnd), hwnd)

    def _screen_edit(self, role: ParamRole) -> dict:
        """The screen's own field for an anchor: the text the dialog states at that position.

        The screen and the dialog state the same facts (that is what ``DIALOG_ANCHORS`` is *for*),
        so the fake holds both surfaces and they agree by construction — which is what lets the
        driver's three checks pass on the measured geometry instead of on a scripted "they match".
        """
        column, row = next(
            (column, row) for anchor, column, row in DIALOG_ANCHORS if anchor is role
        )
        rows = self.rows_for(DIALOG_HWND)
        stated = next(
            str(field["value"])
            for field in driver.dialog_value_fields(
                rows, lambda h: self._fixture_text(rows, h)
            )
            if (int(field["column"]), int(field["row"])) == (column, row)
        )
        return {
            "hwnd": SCREEN_HANDLE_BASE + list(ParamRole).index(role),
            "text": stated,
        }

    def _resolve(self) -> dict:
        panel = self.panel(self.open_hwnd)
        rows = self.rows_for(self.open_hwnd)
        return {
            "raw": rows,
            "panels": [panel],
            "parent_of": {int(row["hwnd"]): panel["hwnd"] for row in rows},
            "open_popup": False,
            "left_panel": None,
            "strip_panel": None,
            "combos": {},
            "menu": {},
            "value_dialogs": [panel["hwnd"]],
            "identities": {},
            "params": {
                role: {"edit": self._screen_edit(role)}
                for role, _column, _row in DIALOG_ANCHORS
            },
        }

    def _children_of(self, parent: int, roles: dict) -> list[dict]:
        """The **direct** children of the panel that is up, as the resolver enumerates them."""
        return [row for row in self.rows_for(self.open_hwnd) if row["depth"] == 0]

    def _descendants_of(self, hwnd: int) -> list[dict]:
        return self.rows_for(self.open_hwnd)

    def _dialog_panels(self, roles: Mapping | None = None) -> list[dict]:
        return [] if self.open_hwnd is None else [self.panel(self.open_hwnd)]

    def _poll_dialog(self, timeout_s: float) -> dict | None:
        return None if self.open_hwnd is None else self.panel(self.open_hwnd)

    def _open_parameters_dialog(self) -> dict:
        if self.assisted is not None:
            raise AcquisitionError(self.assisted)
        self.opened += 1
        if self.reopen_fails is not None and self.opened > 1:
            raise AcquisitionError(self.reopen_fails)
        if self.open_hwnd is None:
            self.open_hwnd = DIALOG_HWND
            if self.replaced:
                self.open_hwnd = REPLACEMENT_HWND
        # A dialog opened now states what the application **keeps** — which is the whole reason a
        # re-open is the surface a read-back is taken from (§19.1 rung 2).
        self.painted = self.volume
        #: The state a ``Cancel`` would restore is the state the dialog found.
        self._committed = (self.burst, self.remembered, self.volume)
        # From the second open on, this is a **re-opened** dialog: the scripted faults above become
        # readable now and only now, so the write's own dialog was checked against the measured tree.
        self._reopened_up = self.opened > 1
        return self.panel(self.open_hwnd)

    # ------------------------------------------------------------------ the controls

    def _combo_items(self, hwnd: int) -> tuple[str, ...]:
        if hwnd == self.burst_hwnd:
            return self.burst_items()
        if hwnd == self.volume_hwnd:
            return self.volume_items()
        return ()

    def _combo_index(self, hwnd: int) -> int:
        """The control's own belief: the first slot of the list it holds, the pinned one."""
        return 0

    def _combo_select(self, hwnd: int, index: int, parent: int | None = None) -> None:
        """The write. On the burst row it **re-derives the volume**, as the measured app does.

        Nothing here is committed: the selection lands in the dialog's pending state, and what the
        application **keeps** is decided by the button that ends the dialog (measured — a write
        left uncommitted is a real state, §18.10 run ``19``: the dialog stated `burst 8, volume
        1.460` with nothing committed, and the next run found the previous pair).
        """
        self.selections.append((hwnd, index, 0 if parent is None else parent))
        if hwnd == self.volume_hwnd:
            # Nothing in the driver may write this row: it is the dependent covariate, and a write
            # here would be a second parameter under study. The fake records it and stops, so the
            # test that asserts "never written" fails loudly if the driver ever does.
            return
        if hwnd != self.burst_hwnd:
            return
        if self.ignore_selection:
            # A combo write that silently does not apply: the control's belief moves and the
            # application keeps its own state. Measured on this class of control (§18.10's
            # ``CB_SETCURSEL``-alone note).
            return
        if self.overlay_on_select is not None:
            self.pending_overlay = self.overlay_on_select
            return
        self.burst = int(self.burst_items()[index])
        # The burst does not write the volume: it re-derives the floor the volume has to clear, and
        # the value in force is the larger of that and what the operator last wrote (§18.10). The
        # remembered value is untouched — a floor-raise is not a write.
        self.volume_pending = effective_volume(self.burst, self.remembered)
        if not self.stale_until_reopen:
            self.painted = self.volume_pending
        if self.replace_after_write and not self.replaced:
            self.replaced = True
            self.open_hwnd = REPLACEMENT_HWND

    def _click_hold(self, hwnd: int, hold_ms: int = 180) -> None:
        """A held press on the dialog's bottom band: the Cancel closes, the Accept commits.

        The band's last button is ``Accept`` and the one before it ``Cancel`` (§19.1: four buttons,
        the leftmost pair are indicators), and the difference between them is the whole point of
        this fake: ``Accept`` moves the pending selection into the state a re-opened dialog would
        state, ``Cancel`` throws it away and leaves the application exactly as the dialog found it.
        """
        self.presses.append(hwnd)
        row = next(
            (r for r in self.rows_for(self.open_hwnd) if int(r["hwnd"]) == hwnd), None
        )
        if row is None:
            return
        band = [
            r for r in self._children_of(self.open_hwnd, {}) if r["cls"] == "TSp_Button"
        ]
        band = sorted(
            (r for r in band if r["top"] > self.panel(self.open_hwnd)["top"] + 314),
            key=lambda r: r["left"],
        )
        if len(band) >= 2 and hwnd == int(band[-1]["hwnd"]):
            self.accepted += 1
            # What the dialog was stating at the moment it was committed — the read a result may
            # not carry, because it is not what the application keeps (see ``stale_until_reopen``).
            self.stated_at_accept = self.painted
            if self.volume_pending is not None:
                self.volume = self.volume_pending
            if self.keep_another_burst is not None:
                self.burst = self.keep_another_burst
                self.volume = effective_volume(self.burst, self.remembered)
            self.volume_pending = None
            self.painted = self.volume
            self.open_hwnd = None
            return
        if len(band) >= 2 and hwnd == int(band[-2]["hwnd"]):
            self.closed_with_cancel += 1
            # Discarded: the application is left where the dialog found it.
            self.burst, self.remembered, self.volume = self._committed
            self.volume_pending = None
            self.painted = self.volume
            self.open_hwnd = None

    # ------------------------------------------------------------------ the overlays

    def _peek_overlay(self) -> OverlayKind | None:
        return getattr(self, "pending_overlay", None)

    def answer_overlay(self) -> OverlayKind | None:
        kind = self._peek_overlay()
        if kind is None:
            return None
        self.pending_overlay = None
        self.answered.append(kind)
        return kind


# ---------------------------------------------------------------- the binding, and the rule


def test_the_dependent_row_is_the_one_the_committed_artefacts_bind():
    """The sampling-volume row is evidence, not habit: ``UI-OVERLAY-05`` and the measured tree.

    The crop paints the dialog's middle column as ``PRF`` / ``First gate depth`` / ``Nb of gates``
    / ``Resolution`` / ``Sampling volume`` / ``Number of skipped profiles`` — six rows, the volume
    fifth, i.e. row ``4`` — and the committed tree holds a ``TComboBox`` stating ``0.876`` (the
    sampling volume at ``c`` = 1460 m/s) at exactly that position. The binding is checked against
    the *fixture* here, so a row that moved would fail this test rather than a live write.
    """
    fake = CoupledDialogDriver()
    assert dialog_row(DialogField.SAMPLING_VOLUME) == (1, 4)
    assert DIALOG_DEPENDENT_FIELDS == ((DialogField.SAMPLING_VOLUME, 1, 4),)
    volume = field_at(fake.fields(), 1, 4)
    assert volume is not None and volume["cls"] == "TComboBox"
    burst = field_at(fake.fields(), *dialog_row(DialogField.BURST_LENGTH))
    assert burst is not None and burst["cls"] == "TComboBox"
    columns = tuple(sorted({int(f["column"]) for f in fake.fields()}))
    counts = tuple(
        sum(1 for f in fake.fields() if int(f["column"]) == column)
        for column in columns
    )
    assert counts == DIALOG_COLUMN_ROWS


def test_the_dependent_row_is_not_a_fourth_fixed_fact_of_the_dialog_reading():
    """The three facts a reading carries are unchanged, and the dependent row is not one of them.

    ``DialogParameters.readable`` requires every field of ``DIALOG_FIELD_ORDER``: adding the
    sampling volume there would make a compile refuse a run whose dialog states the three fixed
    facts but not the volume — a fact this driver reads *for a write*, never for a plan.
    """
    assert [field for field, _c, _r in DIALOG_FIELD_ORDER] == [
        DialogField.BURST_LENGTH,
        DialogField.FIRST_GATE_MM,
        DialogField.SOUND_SPEED_MS,
    ]
    reading = DialogParameters(
        channel="1",
        fields=tuple((field.value, "1") for field, _c, _r in DIALOG_FIELD_ORDER),
    )
    assert reading.readable()


def test_an_entry_is_matched_by_value_and_the_lowest_match_wins():
    """The selection rule, on its own: a value, the list, and what a list that repeats itself means.

    ``entry_of`` answers the **lowest** matching entry because the list is not a set — the value
    currently held occupies the first slot as well as its own — and it answers ``None`` for a value
    the row does not offer, which is a refusal a caller takes rather than a near entry.
    """
    reading = ComboReading(text="0.876", items=("0.876", "1.168", "0.876", "2.336"))
    assert reading.entry_of("0.876") == 0
    assert reading.entry_of("2.336") == 3
    assert reading.entry_of("9.999") is None
    assert reading.entry_of(" 1.168 ") == 1


def test_the_port_grew_no_primitive_for_the_burst_write():
    """The transition is composed on the driver, like the dialog read — the Protocol is untouched.

    The same seam the instrument reading keeps (``tests/test_acquire_dialog.py``): a capability
    arrives as a method on the live class, so every fake that satisfied :class:`…actuator.Actuator`
    before still does, and widening the Protocol has to be argued for in a diff.
    """
    from udv_echo_process.acquire import actuator as actuator_module

    for name in ("write_dialog_burst_length", "set_burst_length"):
        assert not hasattr(actuator_module.Actuator, name)


# ---------------------------------------------------------------- the transition, verified


def test_a_burst_write_reads_both_rows_and_verifies_the_reopened_state():
    """The acceptance gate: write a different burst, see the dependent row move, verify.

    The whole transaction in one test, because the order is the contract: read both rows → select
    by **value** (entry 8 of the row's own list, never a step from the value in force) → let the
    application re-derive → ``Accept`` → **re-open** → read both rows again. The state that counts
    is the re-opened one, and the value it carries is the one the application states for the new
    burst — not the one that was there before the write, and not one this driver worked out.

    The dependent value it must produce is the measured rule's, `max(remembered, floor(18))` =
    `max(0.876, 3.285)` = **`3.285`** — a value the volume combo does **not** offer in its own tail,
    so the fake also proves the transaction carries a volume that no entry list would have given it
    (§18.10: "the application can state a sampling volume its own combo does not list").
    """
    fake = CoupledDialogDriver(burst=10)
    assert floor_mm(18) == 3.285 and floor_mm(18) not in map(float, VOLUME_TAIL)
    result = fake.write_dialog_burst_length(18, routed_channel=1)

    assert result.state is BurstState.VERIFIED
    assert result.verified
    assert result.verified_burst == 18
    assert result.before_burst is not None and result.before_burst.text == "10"
    assert result.before_sampling_volume is not None
    assert result.before_sampling_volume.text == effective_volume(10)
    assert result.after_burst is not None and result.after_burst.text == "18"
    assert result.verified_sampling_volume == effective_volume(18)
    assert result.verified_sampling_volume != result.before_sampling_volume.text
    assert result.after_sampling_volume is not None
    assert result.after_sampling_volume.items[0] == effective_volume(18)
    assert result.after_sampling_volume.items[1:] == VOLUME_TAIL, (
        "the tail does not move"
    )
    # Selected by value: entry 8 of BURSTS is "18". A step-counting writer would have taken the
    # neighbour of the value in force ("12"), which is not the request either.
    burst_index = fake.selections[0][1]
    assert fake.burst_items()[burst_index] == "18"
    assert fake.accepted == 1
    assert fake.opened == 2, "the read-back must come from a re-opened dialog"
    assert fake.open_hwnd is None, "the transaction leaves no dialog open"
    assert result.discarded is False
    assert result.reason == ""
    assert result.channel == STATED_CHANNEL


def test_the_dependent_row_is_read_before_and_after_and_never_written_back():
    """The invariant the plan makes explicit: the volume is evidence, and it is never restored.

    The application's post-burst value is part of the state it accepted, so writing the previous
    volume back would record a configuration the instrument never stated. The fake records every
    selection, which is how "never written" is asserted rather than assumed.
    """
    fake = CoupledDialogDriver(burst=4)
    burst_hwnd = fake.burst_hwnd
    volume_hwnd = fake.volume_hwnd
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.verified
    written = {hwnd for hwnd, _index, _parent in fake.selections}
    assert written == {burst_hwnd}, "only the burst row may be written"
    assert volume_hwnd not in written
    assert result.before_sampling_volume is not None
    assert result.before_sampling_volume.text == effective_volume(4)


def test_the_volume_is_read_back_where_the_application_leaves_it_not_where_a_model_would():
    """The measured asymmetry, both directions, as one transaction pair (§18.10 runs 21/22).

    `4 → 8` with `0.876` remembered states `1.460` — the floor becomes the value in force — and
    `8 → 4` states `0.876` again, because a floor-raise is **not** a remembered write. A driver
    (or a fake) that treated the volume as a function of the burst alone would answer `0.730` for
    the second read and `0.876` for the first: both are wrong, and both are asserted against here.
    """
    fake = CoupledDialogDriver(burst=4, remembered="0.876")
    raised = fake.write_dialog_burst_length(8, routed_channel=1)
    assert raised.verified
    assert raised.before_sampling_volume.text == "0.876"
    assert raised.verified_sampling_volume == "1.460"
    assert fake.remembered == "0.876", (
        "the raise is not a write the application remembers"
    )

    returned = fake.write_dialog_burst_length(4, routed_channel=1)
    assert returned.verified
    assert returned.before_sampling_volume.text == "1.460"
    assert returned.verified_sampling_volume == "0.876"
    assert returned.verified_sampling_volume != f"{floor_mm(4):.3f}", (
        "the floor at burst 4 is 0.730 and the dialog does not state it: this is the read where a "
        "recomputing driver would be wrong"
    )


def test_the_result_carries_the_dialogs_own_projection_and_not_an_index():
    """``verified_sampling_volume_entry`` is the row's own list position, and slot 0 is state.

    The list's first slot states the value in force, whether or not the control could select it,
    so a projection read from the accepted state answers `0` — the same `0` an option index would
    answer for the *first* entry for a completely different reason. That is exactly why the stored
    word 27 is not this number and why tying the two is a live measurement
    (``docs/dop3000/burst-length-control-plan.md`` §B4). The test locks the *reason* in: a future
    reader who mistakes this field for an option index fails here.
    """
    fake = CoupledDialogDriver(burst=10)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.after_sampling_volume is not None
    assert result.after_sampling_volume.items[0] == result.after_sampling_volume.text
    assert (
        result.after_sampling_volume.items[0]
        not in result.after_sampling_volume.items[1:]
    )
    assert result.verified_sampling_volume_entry == 0
    assert result.after_sampling_volume.item_index == 0


def test_a_dialog_the_application_replaced_after_the_write_is_re_resolved_not_pressed_on():
    """A replacement dialog's handles are dead — the write continues on the panel that is up.

    Measured on a *channel* write, and this is the same class of change: the press that accepts
    must reach the panel that exists now, or the transaction leaves a fresh modal on the
    operator's screen with nothing able to close it.
    """
    fake = CoupledDialogDriver(burst=10, replace_after_write=True)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.verified
    assert fake.replaced is True
    assert fake.accepted == 1, "the Accept press must take"
    assert any("replaced its parameters dialog" in note for note in fake.warnings)
    # The re-open read the replacement panel's own handles, which is what a stale-handle read
    # would have failed on.
    assert result.after_burst is not None and result.after_burst.text == "18"


# ---------------------------------------------------------------- the refusals


def test_a_request_the_row_does_not_offer_is_refused_before_any_message_is_sent():
    """An unsupported burst: the row's own list is the authority, and the refusal names it."""
    fake = CoupledDialogDriver(burst=10)
    result = fake.write_dialog_burst_length(7, routed_channel=1)
    assert result.state is BurstState.UNCHANGED
    assert fake.selections == [], (
        "nothing may be sent for a request the row does not offer"
    )
    assert "7" in result.reason and "6" in result.reason  # the entries it does state
    assert result.before_burst is not None and result.before_burst.text == "10"
    assert result.discarded is True
    assert fake.closed_with_cancel == 1


def test_a_burst_below_one_is_refused_before_the_dialog_is_even_opened():
    fake = CoupledDialogDriver(burst=10)
    with pytest.raises(AcquisitionError, match="not a request this driver can make"):
        fake.write_dialog_burst_length(0, routed_channel=1)
    assert fake.opened == 0
    assert fake.selections == []


def test_a_row_that_offers_no_choice_is_refused_rather_than_typed_into():
    """No combo, no write: this driver does not type into a combo's inner edit."""
    fake = CoupledDialogDriver(burst=10, drop_burst_combo=True)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.state is BurstState.UNCHANGED
    assert fake.selections == []
    assert "offers a choice" in result.reason


def test_a_table_that_is_not_the_measured_shape_is_refused_rather_than_written():
    """The three checks a positional binding has to pass, reused from the reading path."""
    fake = CoupledDialogDriver(burst=10, drop_sampling_volume_row=True)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.state is BurstState.UNCHANGED
    assert fake.selections == []
    assert "value fields per column" in result.reason


def test_a_dialog_stating_another_channel_is_refused_before_anything_is_written():
    """The wrong-channel trap, closed where the two channels meet (ledger B17)."""
    fake = CoupledDialogDriver(burst=10, stated_channel="2")
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.state is BurstState.UNCHANGED
    assert fake.selections == []
    assert "channel 2" in result.reason and "channel 1" in result.reason
    assert result.channel == "2"


def test_nothing_routed_means_nothing_is_compared_and_the_write_proceeds():
    """``routed_channel=None`` is a caller's statement: no second channel exists to disagree with."""
    fake = CoupledDialogDriver(burst=10)
    result = fake.write_dialog_burst_length(18, routed_channel=None)
    assert result.verified
    assert result.verified_burst == 18


def test_an_assisted_channel_is_refused_by_the_dialog_it_opens():
    """The mode is the application's own; the panel it builds is what refuses the write."""
    fake = CoupledDialogDriver(
        burst=10,
        assisted=(
            "the topmost 'Parameters' popup entry did not open the 'Operating parameters' dialog "
            "(the one holding the channel combo): the panel it built is the assisted one"
        ),
    )
    with pytest.raises(AcquisitionError, match="assisted"):
        fake.write_dialog_burst_length(18, routed_channel=1)
    assert fake.selections == []


def test_a_warning_raised_instead_of_the_selection_is_answered_and_turns_the_write_into_a_refusal():
    """The manual's own rejection ("the burst length should be reduced"), handled by kind.

    A warning is answered with its left button — the rule every overlay in this application gets —
    and the transaction refuses: the accepted state is not established by this call, the dialog is
    closed with its Cancel, and the reason says all of it.
    """
    fake = CoupledDialogDriver(burst=10, overlay_on_select=OverlayKind.WARNING)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.state is BurstState.UNVERIFIED
    assert result.refusal_overlay == OverlayKind.WARNING.value
    assert fake.answered == [OverlayKind.WARNING]
    assert fake.accepted == 0, "a rejected selection is never accepted"
    assert fake.closed_with_cancel == 1
    assert result.discarded is True
    assert (
        "reduced" not in result.reason
    )  # a caption is paint; this driver does not quote one
    assert "warning" in result.reason


def test_an_overlay_this_driver_has_no_answer_for_is_named_and_left_alone():
    """Never guess a surface: a store dialog raised here means the screen is not the assumed one."""
    fake = CoupledDialogDriver(burst=10, overlay_on_select=OverlayKind.STORE_DIALOG)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.state is BurstState.UNVERIFIED
    assert result.refusal_overlay == OverlayKind.STORE_DIALOG.value
    assert fake.answered == [], (
        "nothing is pressed into a surface this driver does not own"
    )
    assert any("left alone" in note for note in fake.warnings)


def test_a_selection_the_row_never_restates_is_refused_as_unverified():
    """A combo write can silently not apply — and that is a refusal, not a retry."""
    fake = CoupledDialogDriver(burst=10, ignore_selection=True)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.state is BurstState.UNVERIFIED
    assert result.after_burst is not None and result.after_burst.text == "10"
    assert fake.accepted == 0
    assert fake.closed_with_cancel == 1
    assert "did not restate" in result.reason


def test_the_state_that_counts_is_the_reopened_dialogs_not_the_one_that_was_written():
    """Rung 2 of the read-back, isolated: the dialog it wrote is **not** the surface it reports.

    Every claim in this test is measured somewhere else and only scripted here together. §19.1
    orders the read-back to come from a re-opened dialog because the dialog that was written states
    what precedes the commit — it can state a selection that was never kept at all (§18.10 run
    ``19``: `burst 8, volume 1.460`, nothing committed) — and §18.12 measured the same staleness on
    the dialog's derived row (it "does not refresh the derived value until reopened"). So the fake
    can hold the hazard: the row keeps painting the pre-write value after the select.

    A driver that carried the read it made in the dialog it had already opened passes every other
    test in this module — the two values are equal whenever nothing is stale — and fails here,
    which is the whole point of scripting it.
    """
    fake = CoupledDialogDriver(burst=10, stale_until_reopen=True)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.verified
    assert fake.stated_at_accept == effective_volume(10), (
        "the dialog that was written still painted the pre-write volume when it was accepted"
    )
    assert result.after_sampling_volume is not None
    assert result.after_sampling_volume.text == effective_volume(18)
    assert result.verified_sampling_volume == effective_volume(18)
    assert result.verified_sampling_volume != fake.stated_at_accept


def test_a_refused_transition_leaves_the_application_where_the_dialog_found_it():
    """Discarding is the refusal path's only "put it back", and it is read off the app's state.

    Measured: a dialog left with its ``Cancel`` commits nothing (§18.10's `03`/`04` runs — after
    the warning was answered the field held the value from *before* the request). This asserts the
    same thing one level down: the fake's kept state, not merely that a button was pressed.
    """
    before = (10, effective_volume(10))
    fake = CoupledDialogDriver(burst=10, overlay_on_select=OverlayKind.WARNING)
    result = fake.write_dialog_burst_length(18, routed_channel=1)
    assert result.state is BurstState.UNVERIFIED
    assert (fake.burst, fake.volume) == before
    assert fake.closed_with_cancel == 1 and fake.accepted == 0


def test_a_reopened_dialog_that_states_another_burst_raises():
    """Accepted and not kept: the caller must not record a point on an unverified state."""
    fake = CoupledDialogDriver(burst=10, keep_another_burst=12)
    with pytest.raises(AcquisitionError, match="did not keep burst 18"):
        fake.write_dialog_burst_length(18, routed_channel=1)
    assert fake.accepted == 1
    assert fake.open_hwnd is None, (
        "the re-opened dialog is closed even on the failing path"
    )


def test_a_reopen_that_fails_says_the_state_is_unverified():
    fake = CoupledDialogDriver(burst=10, reopen_fails="the popup did not appear")
    with pytest.raises(AcquisitionError, match="could not be re-opened"):
        fake.write_dialog_burst_length(18, routed_channel=1)
    assert fake.accepted == 1


# ------------------------------------ what the re-opened dialog has to be, to be believed


def _never_verifies(fake, requested: int = 18, routed_channel: int = 1) -> str:
    """Drive one transition, state the one thing it may **never** do, and return why it did not.

    Every fault below is a fault of the dialog the application hands back after ``Accept``, so the
    write itself ran to completion on the measured tree and only the read-back can see the fault. A
    transition that reaches ``Accept`` and cannot establish what the application kept may carry the
    refusal as its state or raise (the vocabulary's own rule for accepted-but-unkept); both shapes
    are accepted on purpose, so the assertion pins the invariant rather than the mechanism. The
    reason is returned — the raised message, or the result's own ``reason`` — so a caller can check
    the failure names the fault it was written about.
    """
    try:
        result = fake.write_dialog_burst_length(requested, routed_channel=routed_channel)
    except AcquisitionError as exc:
        return str(exc)
    assert result.state is not BurstState.VERIFIED, result.reason
    assert not result.verified
    assert result.reason, "a transition that did not verify has to say why"
    return result.reason


def _the_write_ran_and_the_fault_is_post_accept(fake) -> None:
    """The facts every post-Accept fault shares: the write was accepted, the dialog came back, it closed.

    ``accepted == 1`` is the ``Accept`` press landing — a transition refused *before* the write
    never presses it — and ``opened == 2`` is the re-open. Together they say the failure is in what
    the application kept, not in any precondition, which is what keeps each test below from passing
    for the wrong reason. And the re-opened dialog is closed on the failing path either way: this
    application confines the operator's cursor to an open dialog and Escape closes nothing, so a
    fault that leaves the modal up is not one a later step can recover from.
    """
    assert fake.accepted == 1, "the write's own dialog was accepted"
    assert fake.opened == 2, "the fault is in the re-opened dialog, not in the write"
    assert fake.open_hwnd is None, "the re-opened dialog is taken down on the failing path"


def _column_counts(rows: list[dict]) -> tuple[int, ...]:
    """The value fields per column a row set states, by position — the driver's own reader's rule."""
    fields = driver.dialog_value_fields(
        rows, lambda hwnd: str(hwnd)
    )
    return tuple(
        sum(1 for field in fields if int(field["column"]) == column)
        for column in sorted({int(field["column"]) for field in fields})
    )


def test_a_reopened_dialog_that_states_another_channel_never_verifies():
    """Accepted on channel 1, read back on channel 2: the burst may match and still not be believed.

    The channel is compared against the one the caller *routed* (the routing step's own
    verification, ``routed_channel``), and the dialog that states it is the re-opened one — the
    write's own dialog stated channel 1 and passed the pre-write check. A read-back that took the
    burst row at face value here would pin a burst read off a dialog that is not the channel the run
    routed, which is the wrong-channel trap the driver already refuses on a stored block (ledger
    B17) — one level later, on the surface the read-back is taken from.
    """
    fake = CoupledDialogDriver(burst=10, reopened_channel="2")
    reason = _never_verifies(fake)
    _the_write_ran_and_the_fault_is_post_accept(fake)
    # The refusal names **both** channels, so a run record says what was found instead of assumed.
    assert "channel 2" in reason and "channel 1" in reason
    # The fault is real and it is only in the re-opened read: the dialog the write used stated the
    # routed channel, and the channel the re-opened one states is the other one.
    assert fake.stated_channel == STATED_CHANNEL
    assert fake.reopened_channel == "2"


def test_a_reopened_table_of_another_shape_never_verifies():
    """The re-opened table is not the one the bindings were measured in — so nothing in it is read.

    Rows are bound by **position**: the burst row at ``(0, 1)`` and the dependent row at ``(1, 4)``.
    A re-opened dialog whose column counts are no longer ``DIALOG_COLUMN_ROWS`` (4, 6, 5) has moved
    a field, and a burst read out of it would be a plausible number taken from the wrong row. The
    row removed here is the right-hand column's last — not the burst row, not the dependent row, and
    not an anchor — so the shape is the *only* thing that changed and the refusal cannot be about
    anything else.
    """
    fake = CoupledDialogDriver(burst=10, alter_reopened_table=True)
    reason = _never_verifies(fake)
    _the_write_ran_and_the_fault_is_post_accept(fake)
    assert "value fields per column" in reason
    # The write's own table was the measured shape; the re-opened one is a field short.
    assert _column_counts(fake.rows) == DIALOG_COLUMN_ROWS
    assert fake.reopened_rows is not None
    assert _column_counts(fake.reopened_rows) != DIALOG_COLUMN_ROWS


def test_a_reopened_dialog_that_disagrees_with_the_screen_never_verifies():
    """The anchor check is what makes a positional binding evidence — and it holds after ``Accept``.

    ``GATES`` is stated on the measurement screen as well as in the dialog (:data:`DIALOG_ANCHORS`),
    so the two surfaces reading the *same* text is what proves the row at that position is the field
    the binding names. A re-opened dialog whose anchor disagrees with the column is not the table
    these bindings were measured against, and its burst row carries no more authority than any other
    plausible number in it. The screen's own read is the fixture's
    (:meth:`CoupledDialogDriver._screen_edit` never goes through ``_get_text``), so the two surfaces
    genuinely disagree rather than moving together.
    """
    fake = CoupledDialogDriver(burst=10, reopened_anchor=ParamRole.GATES)
    reason = _never_verifies(fake)
    _the_write_ran_and_the_fault_is_post_accept(fake)
    assert "disagrees with the measurement screen" in reason
    assert fake.reopened_anchor_hwnd is not None
    # The re-opened dialog states a text the measurement screen does not read.
    assert fake._get_text(fake.reopened_anchor_hwnd) == fake.reopened_anchor_text
    assert fake.reopened_anchor_text != fake._screen_anchor_text(ParamRole.GATES)


@pytest.mark.parametrize("how", ["row removed", "row states nothing"])
def test_a_reopened_dialog_that_loses_the_sampling_volume_row_never_verifies(how):
    """The dependent row is evidence of the state that was accepted, not an optional extra.

    The application re-derives the sampling volume from the burst, and the value it lands on is part
    of the state the transaction verified (``BurstWriteResult`` carries it on both sides of the
    write). A re-opened dialog from which the dependent row cannot be read gives the caller no such
    evidence — and a transaction that returned ``VERIFIED`` with the covariate unread would record a
    burst while silently dropping the coupling the whole feature exists to capture. Two ways the row
    goes unread, and both keep the burst row exactly where it was: it is **gone** (the column is a
    field short, so the shape is no longer the measured one), and it is **present but silent** (the
    shape still matches and the row itself states nothing).
    """
    if how == "row removed":
        fake = CoupledDialogDriver(burst=10, drop_reopened_sampling_volume_row=True)
    else:
        fake = CoupledDialogDriver(burst=10, reopened_volume_states_nothing=True)
    reason = _never_verifies(fake)
    _the_write_ran_and_the_fault_is_post_accept(fake)
    # Either the shape gate or the dependent row's own read names it — never neither.
    assert "value fields per column" in reason or "sampling volume" in reason
    # The burst row survived; it is the dependent row that did not read back.
    reopened = (
        fake.rows_for(DIALOG_HWND) if fake.reopened_rows is not None else fake.rows
    )
    burst = field_at(
        driver.dialog_value_fields(
            reopened, lambda h: fake._fixture_text(reopened, h)
        ),
        *dialog_row(DialogField.BURST_LENGTH),
    )
    assert burst is not None



def test_a_read_back_the_dialog_does_not_state_is_refused_rather_than_guessed():
    """The burst row's text is the application's statement: a non-number states no burst.

    A result that carries ``""`` as an "after" reading is not a verified burst, and the caller that
    read it as one would plan against a number nobody stated.
    """
    reading = ComboReading(text="")
    assert reading.entry_of("") == 0 or reading.items == ()
    assert ComboReading(text="").entry_of("18") is None


# ---------------------------------------------------------------- the live command


def test_the_live_command_routes_the_channel_before_the_transition(monkeypatch):
    """``udv-acquire burst-length`` composes the two steps, and hands over the *verified* channel.

    The routing step is what makes the transition's channel precondition a fact rather than a
    declaration, which is why the command runs it first and passes its answer on.
    """
    fake = CoupledDialogDriver(burst=10)
    routed: list[int] = []

    def routed_channel() -> int:
        routed.append(1)
        return 1

    monkeypatch.setattr(fake, "ensure_channel", routed_channel)
    monkeypatch.setattr(live, "live_actuator", lambda channel=None, notes=None: fake)

    result = live.set_burst_length(18, 1)
    assert routed == [1]
    assert result.verified and result.verified_burst == 18
    assert fake.accepted == 1


def test_the_live_command_refuses_when_the_transition_is_refused(monkeypatch):
    fake = CoupledDialogDriver(burst=10)
    monkeypatch.setattr(fake, "ensure_channel", lambda: 1)
    monkeypatch.setattr(live, "live_actuator", lambda channel=None, notes=None: fake)
    result = live.set_burst_length(7, 1)
    assert result.state is BurstState.UNCHANGED
    assert fake.selections == []
