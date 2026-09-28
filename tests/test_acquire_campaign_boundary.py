"""C4 — the boundary's **order**: two job-level parameters, one durable history, no second source.

``docs/dop3000/emissions-control-plan.md`` §2, accepted with the review's decision 4. The burst
transition was the boundary's only write (``test_acquire_campaign_burst.py``); the emissions per
profile arrives as the *second* independently owned instrument mutation, and this module pins what
that changes at :func:`campaign.run_campaign`'s boundary:

* **the order is data, not code** — :data:`actuator.BOUNDARY_WRITE_ORDER` is the pin, and it is not
  the order this code tests the parameters in, not the enum's order and not the column order. The
  column write goes first (``DIALOG_ANCHORS`` makes the dialog transaction re-verify column ↔ dialog
  agreement) and the write with the strongest verification goes last;
* **one history, in that order** — ``JobManifest.parameter_mutations`` carries both parameters'
  events oldest-first; each event keeps its own typed evidence (``BurstWriteResult`` with its
  sampling-volume row, ``ColumnWriteResult`` with the boundary's own post-write read) and its own
  occurrence identity;
* **a partial failure leaves exactly what verified** — emissions written and verified, then the
  burst refusing, leaves one durable event and no manifest and no recording; an append that fails
  aborts *before* the next parameter is touched, because a write nobody can record must not be
  compounded by a second one;
* **equal is not an event** — a parameter the instrument already states costs no write and appends
  nothing, which is the ``emissions-64 → emissions-64`` boundary the live sitting exercises.

Headless, against the runner's own fake (imported, not re-implemented): its parameter column is a
single text state that ``write_parameter`` moves and ``read_parameter`` states, so "the write layer
answered but the column kept the old value" is a state a case can hand it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_acquire_campaign import campaign_job, run_job
from test_acquire_campaign_burst import BURST_REQUESTED, mutation_records
from test_acquire_runner import BURST_LENGTH, EMISSIONS_PER_PROFILE

from udv_echo_process.acquire import campaign
from udv_echo_process.acquire.actuator import (
    BOUNDARY_WRITE_ORDER,
    BurstState,
    BurstWriteResult,
    ComboReading,
    WriteState,
)
from udv_echo_process.acquire.snapshot import FIXED_FACT_FIELDS

#: The emissions per profile this module's jobs ask for: the fixture's instrument is at
#: :data:`EMISSIONS_PER_PROFILE` (52) and the job asks for 64, so a transition is a real move.
EMISSIONS_REQUESTED = 64


def writing_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: object):
    """The fixture job, as one that **requests** its emissions per profile.

    ``write_emissions_per_profile`` is what makes the declaration a request rather than the derived
    value (``campaign.CampaignDefinition``), and it is the only switch this module needs: everything
    else about the job is the campaign suite's own fixture.
    """
    fields: dict[str, object] = {
        "emissions_per_profile": EMISSIONS_REQUESTED,
        "write_emissions_per_profile": True,
    }
    fields.update(overrides)
    return campaign_job(tmp_path, monkeypatch, **fields)


# ------------------------------------------------- 1. the pin itself


def test_the_boundary_order_is_its_own_data_and_not_the_code_order() -> None:
    """The pin is a closed set of two fact names, and it is deliberately not sorted.

    Sorting it or reading it off an enum/dict would make the order a property of the *names*; the
    order is a property of the two verifications (see the constant's own docstring), which is why
    the pair is written down and asserted here rather than derived.
    """
    assert BOUNDARY_WRITE_ORDER == ("emissions_per_profile", "burst_length")
    assert BOUNDARY_WRITE_ORDER != tuple(sorted(BOUNDARY_WRITE_ORDER)), (
        "the pin is not alphabetical, so a refactor that sorts it fails here"
    )
    assert all(name in FIXED_FACT_FIELDS for name in BOUNDARY_WRITE_ORDER), (
        "both entries are instrument facts, which is what a mutation is tagged with"
    )


def test_a_boundary_order_naming_a_parameter_nobody_writes_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown name is a programming error, and it refuses rather than being skipped.

    The alternative — ignoring it — is exactly the failure this whole slice exists to avoid: a
    boundary that silently performs no transition for a parameter it does not recognise would
    record points under a value nobody established.
    """
    job = writing_job(tmp_path, monkeypatch)
    monkeypatch.setattr(
        campaign, "BOUNDARY_WRITE_ORDER", ("emissions_per_profile", "gate_depth")
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    assert "gate_depth" in str(excinfo.value), excinfo.value


# ------------------------------------------------- 2. the four combinations


def test_a_job_that_requests_only_the_emissions_writes_only_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Emissions only: the burst is not declared, so the boundary has one parameter to establish."""
    job = writing_job(tmp_path, monkeypatch)

    run_job(job)

    records = mutation_records(job)
    assert [record.parameter for record in records] == ["emissions_per_profile"]
    assert job.fake.emissions_column == str(EMISSIONS_REQUESTED)
    assert ("write_parameter", "emissions_per_profile", str(EMISSIONS_REQUESTED)) in (
        job.fake.calls
    )
    assert job.fake.burst_writes == [], "the burst was not declared, so nothing was written for it"


def test_a_job_that_requests_only_the_burst_writes_only_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-existing shape, unchanged: one dialog write, no column write."""
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10

    run_job(job)

    records = mutation_records(job)
    assert [record.parameter for record in records] == ["burst_length"]
    assert job.fake.burst_writes == [(BURST_REQUESTED, 1)]
    assert ("write_parameter", "emissions_per_profile", str(EMISSIONS_REQUESTED)) not in (
        job.fake.calls
    )


def test_a_job_that_requests_both_writes_them_in_the_pinned_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both parameters move, and the history says so in the pinned order — oldest first."""
    job = campaign_job(
        tmp_path,
        monkeypatch,
        burst_length=BURST_REQUESTED,
        emissions_per_profile=EMISSIONS_REQUESTED,
        write_emissions_per_profile=True,
    )
    job.fake.burst_length = 10

    run_job(job)

    records = mutation_records(job)
    assert [record.parameter for record in records] == list(BOUNDARY_WRITE_ORDER)
    boundary_writes = [
        index
        for index, call in enumerate(job.fake.calls)
        if call[0] == "write_dialog_burst_length"
        or call[:2] == ("write_parameter", "emissions_per_profile")
    ]
    assert [job.fake.calls[index][0] for index in boundary_writes] == [
        "write_parameter",
        "write_dialog_burst_length",
    ], "the column write precedes the dialog write, as the pin says"
    points = [index for index, call in enumerate(job.fake.calls) if call[0] == "apply_point"]
    assert min(points) > max(boundary_writes), (
        "both boundary writes precede the first point's own writes"
    )


def test_a_job_that_requests_neither_transitions_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither: no boundary write at all, so no event and no history."""
    job = campaign_job(tmp_path, monkeypatch)

    run_job(job)

    assert mutation_records(job) == ()
    assert job.fake.burst_writes == []


# ------------------------------------------------- 3. equal is not an event


def test_a_parameter_the_instrument_already_states_costs_no_write_and_no_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal on the **emissions** side: the instrument states the request, so nothing moves.

    This is the boundary the live sitting spends a job on (``emissions-64 → emissions-64``): the
    transition is not "skipped for now", it does not exist — there is no write and no mutation, and
    the run's own notes say why rather than leaving a reader to infer it from silence.
    """
    job = writing_job(tmp_path, monkeypatch, emissions_per_profile=EMISSIONS_PER_PROFILE)
    notes: list[str] = []

    run_job(job, notes=notes)

    assert mutation_records(job) == ()
    assert ("write_parameter", "emissions_per_profile", str(EMISSIONS_PER_PROFILE)) not in (
        job.fake.calls
    )
    assert any("already states" in note for note in notes)


def test_an_equal_burst_costs_no_write_and_no_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule on the dialog side, which is where it was already true."""
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_LENGTH)

    run_job(job)

    assert mutation_records(job) == ()
    assert job.fake.burst_writes == []


# ------------------------------------------------- 4. partial failure


def test_an_emissions_event_survives_a_burst_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exactly one durable emissions event, no manifest, no recording.

    The emissions write is real the moment the application accepts it; the burst then refuses. The
    event was appended when it verified — before the refusal — so a reader of the job's own log keeps
    the one mutation that happened and gains no claim about the one that did not.
    """
    job = campaign_job(
        tmp_path,
        monkeypatch,
        burst_length=BURST_REQUESTED,
        emissions_per_profile=EMISSIONS_REQUESTED,
        write_emissions_per_profile=True,
    )
    job.fake.burst_length = 10
    job.fake.burst_write_result = BurstWriteResult(
        requested_burst=BURST_REQUESTED,
        state=BurstState.UNVERIFIED,
        dialog_mode="manual",
        channel="1",
        before_burst=ComboReading(text="10"),
        after_burst=ComboReading(text="10"),
        reason="the dialog did not accept the value",
    )

    with pytest.raises(campaign.CampaignError):
        run_job(job)

    records = mutation_records(job)
    assert [record.parameter for record in records] == ["emissions_per_profile"], (
        "the event of the transition that verified, and nothing else"
    )
    assert isinstance(records[0].evidence, campaign.ColumnWriteResult)
    assert job.fake.emissions_column == str(EMISSIONS_REQUESTED)
    assert job.fake.stored == [], "nothing was recorded"
    assert not campaign.manifest_path_for(job.log_path).is_file(), "no manifest was written"


def test_an_uncommitted_emissions_write_refuses_before_anything_else_happens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write layer answered, the column kept the old value: the job refuses at the column.

    The reviewed decision 4 in one case — the return value of ``write_parameter`` is not the
    verification — and, because the column write is *first* in the pin, the burst is never reached:
    no dialog write, no compile, no recording.
    """
    job = writing_job(tmp_path, monkeypatch)
    job.fake.emissions_kept = str(EMISSIONS_PER_PROFILE)

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    assert "reads it again" in str(excinfo.value), excinfo.value
    assert mutation_records(job) == (), "nothing verified, so nothing was recorded as durable"
    assert job.fake.burst_writes == []
    assert job.fake.stored == []
    assert not campaign.manifest_path_for(job.log_path).is_file()


def test_an_append_failure_aborts_before_the_second_parameter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write nobody can record is not compounded by a second one.

    The emissions transition is verified and its append fails, so the invocation aborts right there:
    the burst write never happens, nothing is compiled and nothing is stored. That is the *only*
    sequence that satisfies both invariants at once — never record points under a provenance
    contract that was not met, and never spend a further instrument mutation after a write whose
    record is lost.
    """
    job = campaign_job(
        tmp_path,
        monkeypatch,
        burst_length=BURST_REQUESTED,
        emissions_per_profile=EMISSIONS_REQUESTED,
        write_emissions_per_profile=True,
    )
    job.fake.burst_length = 10
    appends: list[Path] = []

    def refuse_the_append(path: Path, entry: object) -> None:
        appends.append(Path(path))
        raise OSError("the disk is full")

    monkeypatch.setattr(campaign, "append_entry", refuse_the_append)

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    assert "disk is full" in str(excinfo.value), excinfo.value
    assert appends == [job.log_path], "exactly one append was attempted"
    assert job.fake.burst_writes == [], "the burst was never written"
    assert job.fake.stored == []
    assert not campaign.manifest_path_for(job.log_path).is_file()


# ------------------------------------------------- 5. occurrences and history


def test_two_identical_emissions_transitions_are_two_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ordered history of occurrences, not a set of distinct state changes.

    The operator restores the instrument's value by hand between two invocations of the *same* job,
    so the same ``52 → 64`` transition happens twice. Both events stay, with distinct identities:
    a record keyed on its own content would collapse them and lose an instrument mutation from the
    history (``docs/dop3000/failed-invocation-provenance.md`` §5.3).
    """
    job = writing_job(tmp_path, monkeypatch)

    run_job(job)
    first = mutation_records(job)
    job.fake.emissions_column = str(EMISSIONS_PER_PROFILE)  # the operator restored it by hand
    run_job(job, resume=True)
    both = mutation_records(job)

    assert len(first) == 1
    assert [record.parameter for record in both] == ["emissions_per_profile"] * 2
    assert both[0].mutation_id != both[1].mutation_id, "two occurrences, two identities"
    assert both[0].requested == both[1].requested == str(EMISSIONS_REQUESTED)


def test_a_resumed_invocation_carries_the_mixed_history_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resume that writes nothing still carries both parameters' events, oldest first.

    The second invocation finds the instrument at both values, so it spends no write — and the
    record it rewrites must still carry the emission event and the burst event the first one made,
    in the pinned order. A history that only reported this invocation's writes would lose them.
    """
    job = campaign_job(
        tmp_path,
        monkeypatch,
        burst_length=BURST_REQUESTED,
        emissions_per_profile=EMISSIONS_REQUESTED,
        write_emissions_per_profile=True,
    )
    job.fake.burst_length = 10

    run_job(job)
    written = mutation_records(job)
    notes: list[str] = []
    manifest = run_job(job, resume=True, notes=notes)

    assert [entry.parameter for entry in manifest.parameter_mutations] == [
        "emissions_per_profile",
        "burst_length",
    ]
    assert manifest.parameter_mutations == written, (
        "the resume rewrote the same two occurrences, not a fresh pair"
    )
    assert [entry.requested_burst for entry in manifest.burst_transitions] == [BURST_REQUESTED], (
        "the burst-shaped view of the one history returns the driver's own evidence"
    )
    assert any("performed no boundary write" in note for note in notes)


def test_the_boundary_records_both_evidences_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One history, two payloads, both still typed — the burst is never reduced to text.

    ``MutationDependent`` is the generic half of the dependent evidence: the burst's sampling-volume
    row survives as a row, and the column's absence of one is a ``None`` that says so rather than an
    empty string that pretends it was read.
    """
    job = campaign_job(
        tmp_path,
        monkeypatch,
        burst_length=BURST_REQUESTED,
        emissions_per_profile=EMISSIONS_REQUESTED,
        write_emissions_per_profile=True,
    )
    job.fake.burst_length = 10

    run_job(job)

    emissions, burst = mutation_records(job)
    assert isinstance(emissions.evidence, campaign.ColumnWriteResult)
    assert emissions.state is WriteState.VERIFIED
    assert emissions.evidence.before == str(EMISSIONS_PER_PROFILE)
    assert emissions.evidence.after == str(EMISSIONS_REQUESTED)
    assert emissions.dependent is None, "a column write has no dependent row"
    assert isinstance(burst.evidence, BurstWriteResult)
    assert burst.dependent is not None, "the burst's sampling volume is kept as a row"
    assert burst.dependent.after == job.fake.sampling_volume_text


def test_the_stored_file_is_the_authority_for_both_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compile reconciles the **post-write** reading, and both facts are in it.

    A boundary that wrote the instrument and then compiled against the reading it took *before* the
    write would refuse its own job. The reading below is the one the fake hands the compile, and it
    states both written values because the fake *is* the instrument.
    """
    job = campaign_job(
        tmp_path,
        monkeypatch,
        burst_length=BURST_REQUESTED,
        emissions_per_profile=EMISSIONS_REQUESTED,
        write_emissions_per_profile=True,
    )
    job.fake.burst_length = 10
    snapshots: list[object] = []
    real_compile = campaign.compile_campaign

    def watching_compile(definition: object, snapshot: object, **kwargs: object) -> object:
        snapshots.append(snapshot)
        return real_compile(definition, snapshot, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(campaign, "compile_campaign", watching_compile)

    run_job(job)

    assert snapshots, "the compile ran"
    final = snapshots[-1]
    assert final.emissions_per_profile.value == str(EMISSIONS_REQUESTED)
    assert final.burst_length.value == str(BURST_REQUESTED)
    assert job.fake.stored, "the points were recorded against the post-write state"
