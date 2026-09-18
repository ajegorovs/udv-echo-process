"""The dialog read path: where the three dialog-only fixed facts come from, and what stops a wrong read.

The tree under test is **measured**, not invented: ``tests/data/udop-parameters-dialog-tree.json``
is the ``Operating parameters`` dialog as it stood on the running application on 2026-09-18, read
by ``tools/live/probes/w1_fixed_facts.py``. Three of the six fixed facts have no
parameter-column field at all — the sound speed, the first gate and the burst length are stated
only in this dialog — so the binding that finds them is a *position*
(``actuator.DIALOG_FIELD_ORDER``), and a position that is not checked is a plausible wrong fact
handed to a pre-run check. These tests are that check, in the order the reader applies it: the
measured table binds where it says it does, the anchors make it evidence, and every way of
disagreeing with the screen ends in an unreadable reading rather than a value.

Handles are synthesized here on purpose. The fixture carries the geometry and the text each
control stated; it carries no handle, because handles are volatile — control ids change on every
launch (43/43 classes at the same positions, 1/43 ids in common) — and a binding that depended on
one would be testing the launch instead of the layout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from udv_echo_process.acquire import actuator as actuator_module
from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import (
    DIALOG_ANCHORS,
    DIALOG_COLUMN_ROWS,
    DIALOG_FIELD_ORDER,
    DialogField,
    ParamRole,
    ScreenFingerprint,
)
from udv_echo_process.acquire.snapshot import DialogParameters, FactSource

FIXTURE = Path(__file__).parent / "data" / "udop-parameters-dialog-tree.json"
DIALOG_HWND = 395058
#: The measured dialog's controls get handles above this, and the fake screen's fields a band
#: below it, so that the two surfaces can be told apart by handle in the fakes.
DIALOG_HANDLE_BASE = 900000
SCREEN_HANDLE_BASE = 800000

#: What the dialog stated, by class and text — the values the campaign's own definition declares
#: (``sound speed 1460``, ``first gate 2``, ``burst 4``), which is what makes them identifiable.
BURST = 4
FIRST_GATE = 2
SOUND_SPEED = 1460


def measured_controls() -> list[dict]:
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


def text_of(rows: list[dict], cls: str, text: str) -> int:
    """The handle of the one row of ``cls`` stating ``text`` — the fixture's own addressing."""
    matches = [row for row in rows if row["cls"] == cls and row["text"] == text]
    assert len(matches) == 1, f"{cls} {text!r} is not unique in the measured dialog"
    return int(matches[0]["hwnd"])


def read_text_for(rows: list[dict], overrides: dict[int, str] | None = None):
    """A reader over the measured tree, with the given handles re-stated."""
    stated = {row["hwnd"]: row["text"] for row in rows}
    stated.update(overrides or {})
    return lambda hwnd: stated.get(hwnd, "")


class FakeDialogDriver(driver.Win32Actuator):
    """``Win32Actuator`` whose dialog is the measured tree and whose screen is the fixture's anchors.

    What is faked is the window layer only: the resolution of the screen's column, the children of
    the open dialog, the text a control states, the gesture that opens and closes it, and the run
    log. What is under test is everything between them — the binding, the three checks and the
    close in the ``finally``.
    """

    def __init__(
        self,
        rows: list[dict] | None = None,
        *,
        screen_overrides: dict[ParamRole, str] | None = None,
        dialog_overrides: dict[int, str] | None = None,
        channel: str = "1",
        fill_after: int = 0,
        open_raises: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.rows = measured_controls() if rows is None else rows
        self.screen_overrides = screen_overrides or {}
        self.dialog_overrides = dialog_overrides or {}
        self.stated_channel = channel
        self.fill_after = fill_after
        self.open_raises = open_raises
        self.reads = 0
        self.closed = 0
        #: How often the reading's *screen* half was asked for. Kept because a reading that
        #: refuses on the dialog's channel refuses before it reads the screen at all, and that
        #: is observable here and nowhere else.
        self.screen_reads = 0
        self.notes: list[str] = []

    # ------------------------------------------------------------------ the window layer

    def _resolve(self) -> dict:
        roles: dict = {
            "raw": self.rows,
            "params": {role: {"edit": self._screen_edit(role)} for role, _c, _r in DIALOG_ANCHORS},
        }
        return roles

    def _screen_edit(self, role: ParamRole) -> dict:
        """The screen's own field for an anchor: the same text, unless the test says otherwise.

        The screen and the dialog state the same seven facts, which is what lets the binding be
        checked at all — so the fake has to hold both surfaces, and a test that wants them to
        disagree changes one of them here.
        """
        column, row = next(
            (column, row) for anchor, column, row in DIALOG_ANCHORS if anchor is role
        )
        stated = self.screen_overrides.get(role)
        if stated is None:
            fields = driver.dialog_value_fields(self.rows, read_text_for(self.rows))
            stated = next(
                str(field["value"]) for field in fields if (field["column"], field["row"]) == (column, row)
            )
        return {"hwnd": SCREEN_HANDLE_BASE + list(ParamRole).index(role), "text": stated}

    def _children_of(self, parent: int, roles: dict) -> list[dict]:
        """The dialog's **direct** children, as the resolver enumerates them: buttons and the header.

        No value is stated at this level — that is the measurement, and a fake that returned the
        whole tree here would hide the very defect this models (the live read failed on exactly it).
        """
        return [row for row in self.rows if row["depth"] == 0]

    def _descendants_of(self, hwnd: int) -> list[dict]:
        """The dialog walked whole, which is where its values are — and counted, for the fill."""
        self.reads += 1
        return self.rows

    @property
    def filled(self) -> bool:
        """Whether the application has built its table yet — the one thing ``fill_after`` scripts."""
        return self.reads > self.fill_after

    def _get_text(self, hwnd: int) -> str:
        if SCREEN_HANDLE_BASE <= hwnd < DIALOG_HANDLE_BASE:  # a screen field, not a dialog one
            return next(
                self._screen_edit(role)["text"]
                for role in ParamRole
                if SCREEN_HANDLE_BASE + list(ParamRole).index(role) == hwnd
            )
        if hwnd == text_of(self.rows, "TComboBox", "1"):  # the dialog's header: its channel
            return self.stated_channel
        if not self.filled:
            # An unbuilt table states nothing — which is the measurement this whole check is for.
            return ""
        return read_text_for(self.rows, self.dialog_overrides)(hwnd)

    def _open_parameters_dialog(self) -> dict:
        if self.open_raises:
            raise driver.AcquisitionError(self.open_raises)
        return {"hwnd": DIALOG_HWND, "cls": "TSp_Panel", "left": 655, "top": 364, "w": 627, "h": 384}

    def _close_parameters_dialog(self, panel: dict) -> None:
        self.closed += 1

    def _note(self, message: str) -> None:
        self.notes.append(message)

    def screen_fingerprint(self) -> ScreenFingerprint:
        """The reading's **screen** half, stated rather than read — and counted.

        ``instrument_snapshot`` reads the screen and then the dialog-only facts, and the second
        is this module's subject: the screen's own resolution walk belongs to the window-tree
        fake (``test_acquire_driver.FakeUdopWindow``), and a second window model here would be a
        copy of it that could drift. What the cases below need from this half is that it *is*
        there — and that a reading refused on the dialog's channel never asked for it, which is
        why the count is kept.
        """
        self.screen_reads += 1
        return ScreenFingerprint(
            class_name="TMain_Scr",
            hwnd=DIALOG_HWND,
            rect=(-8, -8, 1928, 1058),
            maximized=True,
            screen=(1920, 1080),
            panels=4,
            visible_controls=43,  # the clean measurement screen's own counts, measured
            strip={"button_count": 3, "has_slider": False, "slider_max": None},
        )


# ------------------------------------------------------------------ the measured binding


def test_the_measured_dialog_binds_the_three_dialog_only_facts_where_the_table_says():
    """The binding is the measurement: each fact sits in the column and row it was read at."""
    fields = driver.dialog_value_fields(measured_controls(), read_text_for(measured_controls()))
    by_position = {(field["column"], field["row"]): field for field in fields}

    assert len(fields) == sum(DIALOG_COLUMN_ROWS)
    for field, column, row in DIALOG_FIELD_ORDER:
        stated = by_position[(column, row)]
        expected = {
            DialogField.BURST_LENGTH: str(BURST),
            DialogField.FIRST_GATE_MM: str(FIRST_GATE),
            DialogField.SOUND_SPEED_MS: str(SOUND_SPEED),
        }[field]
        assert stated["value"] == expected, f"{field.value} is not at ({column}, {row})"


def test_the_column_counts_are_the_measured_ones():
    """The shape check has something to check: four, six and five fields, left to right."""
    fields = driver.dialog_value_fields(measured_controls(), read_text_for(measured_controls()))
    counts = tuple(
        sum(1 for field in fields if field["column"] == column)
        for column in sorted({field["column"] for field in fields})
    )
    assert counts == DIALOG_COLUMN_ROWS


def test_every_anchor_reads_the_same_fact_the_screen_states():
    """The seven anchors are the facts both surfaces state — that is what makes them evidence."""
    rows = measured_controls()
    fields = driver.dialog_value_fields(rows, read_text_for(rows))
    by_position = {(field["column"], field["row"]): field for field in fields}

    screen = FakeDialogDriver()
    for role, column, row in DIALOG_ANCHORS:
        # The dialog's field at the anchor's position states what the column states for that role.
        assert by_position[(column, row)]["value"] == screen._screen_edit(role)["text"]


def test_a_row_that_offers_a_choice_reads_the_choice_not_the_read_out_beside_it():
    """``burst = 4`` is the combo; the ``89`` beside it is the sampling volume the corpus states.

    Both orders are tried because the rule has to survive the one the application actually uses:
    controls come back in *creation* order, which is not the layout's order, so a rule that took
    "the first control in this row" would read the read-out on a day the combo is created second.
    """
    layout = measured_controls()
    for rows in (layout, list(reversed(layout))):
        fields = driver.dialog_value_fields(rows, read_text_for(layout))
        burst = next(field for field in fields if (field["column"], field["row"]) == (0, 1))
        assert burst["cls"] == "TComboBox"
        assert burst["value"] == str(BURST)


def test_a_row_whose_choice_states_nothing_is_unreadable_rather_than_the_read_out_beside_it():
    """The choice *is* the row's value; the edit beside it is a different quantity, never a fallback.

    Measured: in the burst row the combo states ``4`` while the ``TSp_Edit`` inside the same row
    states ``89`` — the sampling volume at 1460 m/s. A reader that fell back to the edit on an
    attempt where the choice could not be read would hand a pre-run check a *different measurement*
    under the burst parameter's name, and nothing in the reading would say so. So the row comes back
    stating nothing, still the choice, and the fact built from it is unreadable.
    """
    layout = measured_controls()
    combo = text_of(layout, "TComboBox", str(BURST))
    fields = driver.dialog_value_fields(layout, read_text_for(layout, {combo: ""}))
    burst = next(field for field in fields if (field["column"], field["row"]) == (0, 1))

    assert burst["cls"] == "TComboBox", "the row is still the choice, not the read-out beside it"
    assert burst["value"] == ""


def test_a_choice_that_states_nothing_leaves_the_reading_a_fact_short_and_never_borrows_the_neighbour():
    """A blank choice costs the reading *that* fact, and never hands it the read-out beside it.

    The burst is dialog-only, so a blank choice is not an anchor disagreement — the read stands and
    simply does not carry the burst, which is what :meth:`DialogParameters.readable` reports (``False``
    with no reason, measured) while the sound speed and the first gate it did establish stay readable.
    Both wrong answers are named here: borrowing the neighbour (the assertion above — ``89`` is the
    sampling volume, a different measurement) and *claiming* the fact. One fact short is exactly the
    state a campaign must refuse on rather than run through, and that rule is the campaign's.
    """
    layout = measured_controls()
    combo = text_of(layout, "TComboBox", str(BURST))
    reading = FakeDialogDriver(dialog_overrides={combo: ""}).read_dialog_parameters()

    assert reading.value(DialogField.BURST_LENGTH.value) is None
    assert not reading.readable(), "one fact short is not a reading of all three"
    assert reading.value(DialogField.SOUND_SPEED_MS.value) == str(SOUND_SPEED)
    assert reading.value(DialogField.FIRST_GATE_MM.value) == str(FIRST_GATE)


def test_the_read_walks_into_the_value_buttons_where_the_values_actually_are():
    """The values live inside the value buttons, so a read over the panel's *children* sees none.

    This is the defect the live application found (measured 2026-09-18: the dialog's 21 direct
    children are buttons and a header, and not one of them states a value), and the fake keeps it
    findable: a reader that walked the resolver's children instead of the dialog would come back
    with no table at all.
    """
    class PanelChildrenOnly(FakeDialogDriver):
        def _descendants_of(self, hwnd: int) -> list[dict]:
            return self._children_of(hwnd, {})

    reading = PanelChildrenOnly().read_dialog_parameters()
    assert not reading.readable()
    assert "built no value buttons at all" in reading.reason

    reading = FakeDialogDriver().read_dialog_parameters()
    assert reading.readable()
    assert reading.value(DialogField.BURST_LENGTH.value) == str(BURST)


def test_the_channel_field_is_not_part_of_the_value_table():
    """The header combo sits above the table; reading it as a field would misplace every position."""
    rows = measured_controls()
    fields = driver.dialog_value_fields(rows, read_text_for(rows))
    header = text_of(rows, "TComboBox", "1")
    assert header not in {field["hwnd"] for field in fields}

    fake = FakeDialogDriver()
    assert fake._dialog_channel_text(rows, fields) == "1"


# ------------------------------------------------------------------ the three checks


def test_a_dialog_with_no_value_table_at_all_is_a_refusal_and_not_a_crash():
    """Measured live: the first open after a restart can come back with no table to bind at all."""
    stated_everywhere = {role: "1" for role, _column, _row in DIALOG_ANCHORS}
    reading = FakeDialogDriver(rows=[], screen_overrides=stated_everywhere).read_dialog_parameters()

    assert not reading.readable()
    assert "built no value buttons at all" in reading.reason
    assert driver.dialog_value_fields([], lambda hwnd: "") == []


def test_a_dialog_that_has_not_filled_is_unreadable_rather_than_read(monkeypatch):
    """The first open on a freshly started application states nothing (measured); it is not a value."""
    monkeypatch.setattr(driver, "DIALOG_FILL_TIMEOUT_S", 0.0)
    reading = FakeDialogDriver(fill_after=10**6).read_dialog_parameters()

    assert isinstance(reading, DialogParameters)
    assert not reading.readable()
    assert "stated nothing in them" in reading.reason
    assert reading.value(DialogField.SOUND_SPEED_MS.value) is None


def test_the_read_waits_for_a_table_that_fills_after_the_dialog_appears(monkeypatch):
    """The table that fills a moment late is a read, not a refusal: the poll is the difference."""
    monkeypatch.setattr(driver, "_POLL_S", 0.01)
    reading = FakeDialogDriver(fill_after=2).read_dialog_parameters()

    assert reading.readable()
    assert reading.value(DialogField.SOUND_SPEED_MS.value) == str(SOUND_SPEED)
    assert reading.value(DialogField.FIRST_GATE_MM.value) == str(FIRST_GATE)
    assert reading.value(DialogField.BURST_LENGTH.value) == str(BURST)


def test_a_table_that_is_not_the_measured_shape_is_refused_rather_than_read():
    """These fields are read by position, so a different table is not the one they were bound in."""
    rows = [row for row in measured_controls() if row["text"] != str(SOUND_SPEED)]
    reading = FakeDialogDriver(rows).read_dialog_parameters()

    assert not reading.readable()
    assert "value fields per column" in reading.reason
    assert reading.value(DialogField.SOUND_SPEED_MS.value) is None


def test_an_anchor_that_disagrees_with_the_screen_stops_the_whole_read():
    """A dialog state that contradicts the column is a stale binding, not a value to believe."""
    rows = measured_controls()
    prf = text_of(rows, "TSp_Edit", "212")
    reading = FakeDialogDriver(rows, dialog_overrides={prf: "999"}).read_dialog_parameters()

    assert not reading.readable()
    assert "disagrees with the measurement screen" in reading.reason
    assert ParamRole.PRF.value in reading.reason
    assert "999" in reading.reason
    assert reading.value(DialogField.BURST_LENGTH.value) is None


def test_an_anchor_the_screen_does_not_state_at_all_is_a_refusal():
    """In assisted mode the column is absent, so nothing can confirm where the facts sit."""
    reading = FakeDialogDriver(screen_overrides={ParamRole.GATES: ""}).read_dialog_parameters()
    assert not reading.readable()
    assert "could not be checked against the screen" in reading.reason


def test_a_dialog_that_states_no_channel_is_a_refusal():
    """A read that cannot say whose parameters these are is not a read a compile may compare."""
    reading = FakeDialogDriver(channel="").read_dialog_parameters()
    assert not reading.readable()
    assert "stated no channel" in reading.reason


# ------------------------------------------------------------------ the gesture


def test_a_read_dialog_returns_the_three_facts_and_which_channel_they_belong_to():
    """The happy path: three read facts, the channel they were read for, and the dialog closed."""
    fake = FakeDialogDriver()
    reading = fake.read_dialog_parameters()

    assert reading.readable()
    assert reading.channel == "1"
    assert reading.value(DialogField.SOUND_SPEED_MS.value) == str(SOUND_SPEED)
    assert fake.closed == 1


def test_the_dialog_is_closed_when_the_read_refuses_too():
    """An open dialog confines the cursor and Escape closes nothing here, so the close is in a finally."""
    fake = FakeDialogDriver(screen_overrides={ParamRole.PRF: "999"})
    assert not fake.read_dialog_parameters().readable()

    assert fake.closed == 1


def test_a_gesture_that_cannot_open_the_dialog_returns_an_unreadable_reading_and_notes_it():
    """Not being able to open it is a fact about the run, not an exception for the caller to eat."""
    fake = FakeDialogDriver(open_raises="a menu popup is already open")
    reading = fake.read_dialog_parameters()

    assert not reading.readable()
    assert "could not be opened" in reading.reason
    assert fake.notes and "could not be opened" in fake.notes[0]
    assert fake.closed == 0


# ------------------------------------------------------------------ the snapshot's side


def test_a_snapshot_without_a_dialog_reading_carries_the_facts_as_unread():
    """The hand-over rule: this reading may not claim what no step established."""
    fact = driver._dialog_fact(None, DialogField.SOUND_SPEED_MS)

    assert fact.source is FactSource.UNREADABLE
    assert fact.value is None
    assert "Operating parameters" in fact.reason
    assert "no read of that dialog was handed" in fact.reason


def test_a_snapshot_handed_a_reading_carries_the_facts_as_read():
    """And with one, the fact is what the dialog stated — on the reading's authority, named."""
    reading = FakeDialogDriver().read_dialog_parameters()
    fact = driver._dialog_fact(reading, DialogField.SOUND_SPEED_MS)

    assert fact.source is FactSource.READ
    assert fact.value == str(SOUND_SPEED)


def test_a_snapshot_handed_a_refused_reading_carries_the_refusal_itself():
    """The reason travels with the fact, so a record says why it is unread, not just that it is."""
    reading = FakeDialogDriver(open_raises="nothing was up to read").read_dialog_parameters()
    fact = driver._dialog_fact(reading, DialogField.FIRST_GATE_MM)

    assert fact.source is FactSource.UNREADABLE
    assert "nothing was up to read" in fact.reason


def test_the_port_grew_no_primitive_for_the_dialog_read():
    """The reader is composed from the port's existing pieces, like every other read here."""
    assert not hasattr(actuator_module.Actuator, "read_dialog_parameters")
    assert not hasattr(actuator_module.Actuator, "instrument_snapshot")


# ------------------- the dialog's channel, against the channel the run routed (plan §16.1)


def test_a_dialog_stating_another_channel_refuses_the_reading_before_anything_is_read():
    """The wrong-channel trap, closed where the two channels meet and nowhere else.

    The dialog-only facts belong to the channel the *dialog* shows; the recording lands on the
    channel the run routed. Attributing channel 2's burst, sound speed and first gate to a
    channel-1 reading is invisible downstream — every value is a plausible number — so the
    mismatch is refused here, naming both channels, and it is refused *before the screen is
    read*: a reading that stops here attributes nothing at all (``screen_reads`` stays zero),
    which is what makes the refusal a refusal rather than a reading with a footnote.
    """
    fake = FakeDialogDriver(channel="2")
    reading = fake.read_dialog_parameters()
    assert reading.channel == "2"

    with pytest.raises(driver.AcquisitionError) as excinfo:
        fake.instrument_snapshot(routed_channel=1, dialog_parameters=reading)

    message = str(excinfo.value)
    assert "channel 2" in message, message
    assert "channel 1" in message, message
    assert fake.screen_reads == 0  # nothing was read, so nothing was attributed


def test_a_dialog_on_the_routed_channel_is_accepted_and_the_facts_carry_that_channel():
    """The mirror case, and the one the live instrument is in: agreement is never refused.

    The measured dialog is on the channel the run routed, so a check that refused this would
    refuse every real run — the three dialog-only facts have to come back as *reads*, and the
    channel the reading carries is the routed one, which is the channel the dialog itself
    stated. Both halves are asserted together because that is the whole claim: the dialog's
    channel and the run's are the same one, and the facts belong to it.
    """
    fake = FakeDialogDriver(channel="2")
    reading = fake.read_dialog_parameters()

    snapshot = fake.instrument_snapshot(routed_channel=2, dialog_parameters=reading)

    assert snapshot.channel.value == "2"
    assert snapshot.channel.source is FactSource.ROUTED
    assert snapshot.burst_length.value == str(BURST)
    assert snapshot.sound_speed_ms.value == str(SOUND_SPEED)
    assert snapshot.first_gate_mm.value == str(FIRST_GATE)
    assert fake.closed == 1  # and the dialog was closed behind the read


def test_a_refused_reading_keeps_the_readers_own_reason_not_an_attribution_error():
    """A refused read is carried with the diagnostic the reader wrote, never re-cast as a mismatch.

    This reading states channel 2 *and* refuses — its PRF anchor disagrees with the screen — so
    both refusals are available and only one of them may be reported. The campaign turns an
    unreadable fact into its own refusal in the reader's own words (``_refuse_failed_reads``),
    and a vaguer "these are another channel's parameters" would replace a precise diagnostic with
    one this reading cannot substantiate: it never established the facts at all. So the reading
    stands, no value is claimed, and the reason that travels with each fact is the reader's.
    """
    rows = measured_controls()
    prf = text_of(rows, "TSp_Edit", "212")
    fake = FakeDialogDriver(rows, channel="2", dialog_overrides={prf: "999"})
    reading = fake.read_dialog_parameters()
    assert reading.channel == "2"
    assert not reading.readable()

    snapshot = fake.instrument_snapshot(routed_channel=1, dialog_parameters=reading)

    assert snapshot.channel.value == "1"  # the routed channel still stands
    for fact in (snapshot.burst_length, snapshot.sound_speed_ms, snapshot.first_gate_mm):
        assert fact.source is FactSource.UNREADABLE
        assert fact.value is None
        assert "disagrees with the measurement screen" in (fact.reason or "")
