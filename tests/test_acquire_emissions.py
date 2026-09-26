"""The emissions-per-profile transition — the boundary's column write (plan §2, review decision 4).

``docs/dop3000/emissions-control-plan.md`` §2 fixes the transaction as
``read → write → fresh read → classify``, and the review fixed the part that decides it: a write is
**VERIFIED only if a separate post-write read states the requested value**, so the column's own
write layer never gets to establish the instrument's state — its read-back is carried as evidence
and nothing more.

This module pins the transaction itself, on a column small enough to read in one screen: four
answers (not requested / nothing to compare / already equal / written), and the refusal shapes. The
*boundary integration* that calls it — the order across parameters, the partial-failure shapes, the
resume history — is a different question and lives in ``test_acquire_campaign_burst.py`` and
``test_acquire_campaign.py``.

Nothing here touches an instrument or a window: the actuator is a fake with two methods, and the
readings are the compile suite's own expected snapshot with single fields replaced.
"""

from __future__ import annotations

import pytest
from test_acquire_compile import definition, read, reading

from udv_echo_process.acquire import campaign
from udv_echo_process.acquire.actuator import ParamRole, WriteState
from udv_echo_process.acquire.snapshot import FactSource, InstrumentFact, unreadable
from udv_echo_process.acquire.udop import AcquisitionError

#: The value the fixture campaign declares — the request every case below is about.
REQUESTED = 64


class FakeColumn:
    """The parameter column, as much of one as the transaction touches.

    ``write_parameter`` answers with the **write layer's** read-back (that is what the driver
    returns) and ``read_parameter`` is the *separate* read the boundary takes afterwards.
    ``accepted`` scripts what the write layer reports when it differs from what was sent, and
    ``kept`` scripts what the column actually states when the fresh read happens — the two are
    different questions, which is the whole point of the transaction.
    """

    def __init__(self, *, accepted: str | None = None, kept: str | None = None) -> None:
        self.accepted = accepted
        self.kept = kept
        self.writes: list[tuple[str, str]] = []
        self.reads = 0

    def write_parameter(self, role: ParamRole, value: str) -> str:
        self.writes.append((role.value, value))
        return value if self.accepted is None else self.accepted

    def read_parameter(self, role: ParamRole) -> str:
        self.reads += 1
        if self.kept is not None:
            return self.kept
        return self.writes[-1][1] if self.writes else ""


def transit(
    column: FakeColumn, *, before: str = "20", notes: list[str] | None = None, **overrides: object
) -> campaign.ColumnWriteResult | None:
    """Run the transaction over one reading of the column, with the fixture job's frame.

    The job **requests** the value by default — that is the case the transaction exists for — and a
    case that wants the inherited path passes ``write_emissions_per_profile=False``.
    """
    fields: dict[str, object] = {
        "emissions_per_profile": REQUESTED,
        "write_emissions_per_profile": True,
    }
    fields.update(overrides)
    return campaign._transit_emissions_per_profile(
        column,
        definition(**fields),
        reading=reading(emissions_per_profile=read(before)),
        routed=1,
        notes=notes,
    )


def test_a_job_that_does_not_request_it_writes_nothing() -> None:
    """The inherited value is not a request, so the boundary has nothing to establish.

    This is the read-only half of the acceptance change: such a job's emissions value stays a
    declaration the compile reconciles as an advisory, and nothing here touches the column.
    """
    column = FakeColumn()

    assert transit(column, write_emissions_per_profile=False) is None
    assert column.writes == []
    assert column.reads == 0, "not even a read: the transaction did not run at all"


def test_a_reading_that_states_no_value_attempts_nothing() -> None:
    """A write aimed at a state nothing stated is a write spent on a guess.

    The job's own reading is the only thing that can say what the column is at, and a fact that
    produced no value is exactly the case the compile refuses by name (``emissions_per_profile``
    has a reader, so "no value" is not "agreed").
    """
    column = FakeColumn()
    requested_job = definition(emissions_per_profile=REQUESTED, write_emissions_per_profile=True)

    result = campaign._transit_emissions_per_profile(
        column,
        requested_job,
        reading=reading(emissions_per_profile=unreadable("the column did not resolve")),
        routed=1,
        notes=None,
    )

    assert result is None
    assert column.writes == []
    assert column.reads == 0


def test_an_equal_value_spends_no_write_and_records_no_mutation() -> None:
    """Nothing moved, so there is no event: an equal value is not a transition.

    The live commissioning exercises this boundary on purpose (``emissions-64 → emissions-64``),
    and the answer is a *statement* rather than silence — the run's own notes say the instrument was
    already there.
    """
    column = FakeColumn()
    notes: list[str] = []

    result = transit(column, before=str(REQUESTED), notes=notes)

    assert result is None
    assert column.writes == [], "no write is spent on a value the instrument already states"
    assert column.reads == 0
    assert notes and "already states" in notes[0], notes


def test_the_write_is_decided_by_the_boundarys_own_fresh_read() -> None:
    """The evidence carries the read, not the write: before, request, and what a new read stated."""
    column = FakeColumn()
    notes: list[str] = []

    result = transit(column, notes=notes)

    assert result is not None
    assert result.role is ParamRole.EMISSIONS_PER_PROFILE
    assert result.state is WriteState.VERIFIED
    assert result.before == "20"
    assert result.requested == str(REQUESTED)
    assert result.after == str(REQUESTED)
    assert result.write_readback == str(REQUESTED)
    assert column.writes == [(ParamRole.EMISSIONS_PER_PROFILE.value, str(REQUESTED))]
    assert column.reads == 1, "a separate read after the write is what classified it"
    assert notes and "fresh read" in notes[0], notes


def test_the_write_layers_readback_is_carried_but_never_judged() -> None:
    """What the write layer reports is evidence *about* the write; it does not decide anything.

    A read-back that differs from the request while the application states the request is the
    interesting shape: the record keeps both, and the state is still VERIFIED — because the state of
    the instrument is what a fresh read states, and the write layer's rendering is not it.
    """
    column = FakeColumn(accepted="065")

    result = transit(column)

    assert result is not None
    assert result.write_readback == "065", "the layer's own answer, verbatim"
    assert result.after == str(REQUESTED)
    assert result.state is WriteState.VERIFIED


def test_a_read_that_does_not_state_the_request_refuses() -> None:
    """The return value is not the verification — this is the case that proves it.

    The write layer answered the request and the column states something else when the boundary
    reads it again, so the instrument never reached the value this job records at. No point of the
    job may be recorded, and the refusal names both sides plus the write's own read-back so the
    operator can see which layer disagreed.
    """
    column = FakeColumn(kept="20")

    with pytest.raises(campaign.CampaignError) as caught:
        transit(column)

    message = str(caught.value)
    assert str(REQUESTED) in message
    assert "20" in message
    assert "'64'" in message, message
    assert "reads it again" in message, message


def test_a_blank_read_refuses_naming_the_row() -> None:
    """An empty row is not agreement either: the refusal says nothing was stated."""
    column = FakeColumn(kept="")

    with pytest.raises(campaign.CampaignError) as caught:
        transit(column)

    assert "nothing" in str(caught.value), caught.value


def test_a_driver_refusal_propagates_untouched() -> None:
    """The driver's own refusals already name what stopped the job: no second diagnosis."""

    class Refusing(FakeColumn):
        def write_parameter(self, role: ParamRole, value: str) -> str:
            raise AcquisitionError("no parameter column field for 'emissions_per_profile'")

    with pytest.raises(AcquisitionError) as caught:
        transit(Refusing())

    assert "no parameter column field" in str(caught.value), caught.value


def test_the_reading_is_the_parse_of_the_snapshot_not_a_second_read() -> None:
    """The before value comes from the job's own reading — the fact the compile will reconcile.

    Nothing is re-read to establish where the write started: the boundary already took that read,
    and re-reading it would let the "before" of the record and the "declared" of the compile drift
    apart when they are the same moment.
    """
    column = FakeColumn()
    result = transit(column, before="8")

    assert result is not None and result.before == "8"
    assert column.reads == 1, "exactly one read: the one taken after the write"


def test_a_fact_read_by_another_surface_is_not_a_value_this_run_compares() -> None:
    """Only the column's own answer counts as the state this transaction moves away from."""
    column = FakeColumn()
    wrong_source = InstrumentFact(value=str(REQUESTED), source=FactSource.DECLARED)

    result = campaign._transit_emissions_per_profile(
        column,
        definition(emissions_per_profile=REQUESTED, write_emissions_per_profile=True),
        reading=reading(emissions_per_profile=wrong_source),
        routed=1,
        notes=None,
    )

    assert result is None
    assert column.writes == []
