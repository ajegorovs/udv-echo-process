"""B5 — the job-level burst transition at :func:`run_campaign`'s boundary.

``test_acquire_burst.py`` pins the *transaction* (``write_dialog_burst_length``: the dialog
write, the read-back on a re-opened dialog, the dependent sampling-volume row and the failure
matrix). This module pins the layer that spends a job on it: :func:`campaign.run_campaign`
compares the instrument's current dialog burst with the **job definition's** burst, performs
the verified transition when they differ, and keeps the existing compilation check as an
independent second opinion — ``write → verify → compile → record``
(``docs/dop3000/burst-length-control-plan.md`` §B5).

Three things are under test and nothing else:

* **the transition happens at the boundary, in the right order** — after the channel is
  established and before the compile, so a job that cannot be transitioned costs no recording;
* **a refusal is a refusal** — a transition the driver classifies as anything but ``VERIFIED``,
  one whose re-opened burst is not the request, or one with no readable sampling-volume
  statement stops the job before anything is stored. The instrument's state is then unknown, and
  a recording taken on it would pin a burst nobody read back;
* **the evidence is on the record** — a verified transition is persisted on the job manifest as
  the ordered history ``JobManifest.burst_transitions`` (oldest first, accumulated across every
  invocation of the job), so a pass reconstructed offline says which bursts the run wrote, in
  which order, and what the application answered;
* **and the transition survives an invocation that refused after it** — the write is real the
  moment the application accepts it, while the manifest is written only at the end of an
  invocation, so a compile refusal or a resume-identity refusal used to lose the record of a
  mutation that happened. The verified transition is appended to the job's own log at the
  boundary instead (``docs/dop3000/failed-invocation-provenance.md`` §O4), the next invocation
  folds it into the history, and an append that *cannot* be written aborts the invocation rather
  than recording points under a provenance contract that was not met.

Everything here is headless: the run drives the runner's own in-memory fake (imported, not
re-implemented), whose burst transition is scriptable so every refusal the boundary has an
answer for can be exercised without an instrument.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_acquire_campaign import (
    CAMPAIGN_DURATION_S,
    Job,
    campaign_file,
    campaign_job,
    campaign_payload,
    legacy_manifest,
    run_job,
)
from test_acquire_run_plan import (
    burst_transition_result,
    committed_run,
    job_manifest_for,
)
from test_acquire_runner import (
    BURST_LENGTH,
    PRF_US,
    expected_snapshot,
)

from udv_echo_process.acquire import campaign, run_plan
from udv_echo_process.acquire.actuator import (
    BurstState,
    BurstWriteResult,
    ComboReading,
    DialogField,
    ProcessMode,
)
from udv_echo_process.acquire.log import (
    SweepBurstMutation,
    append_entry,
    burst_mutations,
    point_names,
    read_entries,
)
from udv_echo_process.acquire.snapshot import FactSource, InstrumentFact

#: A burst the row offers (``…actuator``'s measured list, ``acquisition-campaign-compilation-plan.md``
#: §18.9) and that the fixture campaign does not declare: the instrument is at :data:`BURST_LENGTH`
#: (4) and the job asks for 18.
BURST_REQUESTED = 18


def test_a_job_whose_burst_differs_transitions_the_dialog_before_the_compile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The instrument sits at another burst, so the boundary writes it — before the compile.

    The order is the whole reason the transition is here: the channel is established first (the
    dialog write is identified by the channel it states), the reading the *pure* refusals judge is
    taken next, the burst is transitioned, and the compile that reconciles the definition with the
    instrument runs *after* it — so the reading the compile sees is the state the write established,
    and a job whose burst cannot be established costs no recording.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)

    manifest = run_job(job)

    assert job.fake.burst_writes == [(BURST_REQUESTED, 1)], (
        "the boundary has to hand the job's burst and the channel it routed to the transition"
    )
    calls = [call[0] for call in job.fake.calls]
    # The instrument is read once before the write (the reading the pure refusals judge) and once
    # after it (the reading the compile reconciles), so the ordering contract is against the
    # *last* reading: the write precedes the reading the compile is reconciled against.
    last_snapshot = len(calls) - 1 - calls[::-1].index("instrument_snapshot")
    assert calls.index("write_dialog_burst_length") < last_snapshot
    # The application's dialog now states the job's burst: the compile after the write reconciles
    # the *new* state, which is what makes the transition the first half of one transaction.
    assert job.fake.burst_length == BURST_REQUESTED
    assert [transition.verified_burst for transition in manifest.burst_transitions] == [
        BURST_REQUESTED
    ]


def test_the_reading_the_compile_sees_is_the_one_the_write_established(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dialog is read again after a transition, and that reading is what the compile reconciles.

    Without the re-read the compile would reconcile the definition against the **pre-write** state and
    refuse — which is the failure this ordering exists to prevent. The recorded identity is the
    proof: the job's own compiled burst is the one the write established, not the one the instrument
    happened to state a moment earlier.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)

    manifest = run_job(job)

    # One read before the write (to compare), one after (to compile against).
    assert len(job.fake.dialog_readings) == 2
    assert job.fake.dialog_readings[0].value(DialogField.BURST_LENGTH.value) == str(
        BURST_LENGTH
    )
    assert job.fake.dialog_readings[1].value(DialogField.BURST_LENGTH.value) == str(
        BURST_REQUESTED
    )
    assert manifest.compilation_identity is not None
    assert manifest.compilation_identity.burst_length.value == str(BURST_REQUESTED)
    # ... and the reading the snapshot was *handed* is the fresh one, not only one that exists.
    handed = job.fake.snapshot_dialogs[-1]
    assert handed is not None
    assert handed.value(DialogField.BURST_LENGTH.value) == str(BURST_REQUESTED)
    assert manifest.failed_count == 0
    assert not manifest.aborted


# --------------------------------------------------- 2. no write is spent when none is needed


def test_an_instrument_already_at_the_jobs_burst_is_not_written_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal burst: the boundary compares, finds nothing to do, and leaves the dialog alone.

    The write is not a formality — it presses the operator's dialog, and the application's dependent
    sampling volume is *not* a pure function of the burst (``max(remembered, floor)``, plan §3), so
    re-selecting a burst the instrument already records at could move a value the job never asked to
    move. Nothing is attempted, and the record says so with a ``None``.
    """
    job = campaign_job(
        tmp_path, monkeypatch
    )  # the fixture declares BURST_LENGTH; the fake is at it

    manifest = run_job(job)

    assert job.fake.burst_writes == []
    assert "write_dialog_burst_length" not in [call[0] for call in job.fake.calls]
    assert job.fake.burst_length == BURST_LENGTH
    assert manifest.burst_transitions == ()
    assert manifest.failed_count == 0


def test_a_definition_that_declares_no_burst_spends_no_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``burst_length`` is optional: with nothing requested there is nothing to transition to."""
    job = campaign_job(tmp_path, monkeypatch, burst_length=None)

    manifest = run_job(job)

    assert job.fake.burst_writes == []
    assert manifest.burst_transitions == ()


def test_a_no_snapshot_run_neither_reads_nor_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``no_snapshot`` skips the reading *and* the compile, so it cannot know what to transition."""
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)

    manifest = run_job(job, no_snapshot=True)

    assert job.fake.burst_writes == []
    assert job.fake.dialog_checks == 0
    assert manifest.declared_only
    assert manifest.burst_transitions == ()


# ---------------------------------------------------------------- 3. a refusal refuses


def job_with_transition(job: Job, result: BurstWriteResult) -> None:
    """Script the fake's burst transition to answer ``result`` instead of applying the write."""
    job.fake.burst_write_result = result


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (BurstState.UNCHANGED, "the burst row does not offer 18: nothing was sent"),
        (
            BurstState.UNVERIFIED,
            "the burst row did not restate the selection: the dialog was cancelled",
        ),
    ],
)
def test_a_transition_that_did_not_verify_stops_the_job_before_a_recording(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: BurstState,
    reason: str,
) -> None:
    """``UNCHANGED`` and ``UNVERIFIED`` are refusals, and a refusal is what the boundary reports.

    The driver classifies a pre-``Accept`` refusal rather than raising, so the boundary has to read
    the classification: a job that recorded on an unestablished burst would pin a configuration
    nobody read back — the exact thing the transition exists to prevent.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job_with_transition(
        job,
        BurstWriteResult(
            requested_burst=BURST_REQUESTED,
            state=state,
            channel="1",
            discarded=True,
            reason=reason,
        ),
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    message = str(excinfo.value)
    assert state.value in message
    assert reason in message
    assert str(BURST_REQUESTED) in message
    assert_no_recording(job)


def test_a_transition_that_states_another_burst_stops_the_job_before_a_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VERIFIED`` is a classification; the number it is a classification *of* is what is recorded.

    A result that reports the request but carries a re-opened row stating something else is the
    contradiction the second demand exists for — and the job must not proceed on it.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job_with_transition(
        job,
        BurstWriteResult(
            requested_burst=BURST_REQUESTED,
            state=BurstState.VERIFIED,
            channel="1",
            before_burst=ComboReading(text=str(BURST_LENGTH)),
            after_burst=ComboReading(text="10"),
            after_sampling_volume=ComboReading(text="1.460"),
        ),
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    assert "10" in str(excinfo.value)
    assert str(BURST_REQUESTED) in str(excinfo.value)
    assert_no_recording(job)


def test_a_transition_without_a_readable_sampling_volume_stops_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dependent row is the evidence the write was applied — unreadable means unestablished.

    The application re-selects that row from the burst, so a transition that cannot state it leaves
    the state the instrument accepted unproven. Its *value* is never judged (no mm law is applied
    here) — only its readability is demanded.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job_with_transition(
        job,
        BurstWriteResult(
            requested_burst=BURST_REQUESTED,
            state=BurstState.VERIFIED,
            channel="1",
            before_burst=ComboReading(text=str(BURST_LENGTH)),
            after_burst=ComboReading(text=str(BURST_REQUESTED)),
            after_sampling_volume=None,
        ),
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    assert "sampling-volume" in str(excinfo.value) or "sampling volume" in str(
        excinfo.value
    )
    assert_no_recording(job)


def assert_no_recording(job: Job) -> None:
    """Nothing was spent: no file stored, no log written, no point applied.

    The boundary refuses *before* the runner exists, so the strong statement is available: the
    recording cycle was never reached at all.
    """
    assert job.fake.stored == []
    assert not job.log_path.is_file()
    assert "apply_point" not in [call[0] for call in job.fake.calls]


# ----------------------------------------------------- 4. the evidence lands on the record


def test_a_verified_transition_is_persisted_on_the_job_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest is what a pass reconstructed offline reads: it says what was written.

    The evidence is the driver's own :class:`BurstWriteResult` — the state, both rows on both sides
    and the dependent sampling-volume statement — not a boolean, so a later reader can say *what* the
    instrument answered rather than only that something happened.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)

    manifest = run_job(job)

    transitions = manifest.burst_transitions
    assert len(transitions) == 1
    transition = transitions[0]
    assert transition.requested_burst == BURST_REQUESTED
    assert transition.verified
    assert transition.verified_burst == BURST_REQUESTED
    assert transition.verified_sampling_volume is not None
    assert transition.before_burst is not None
    assert transition.before_burst.text == str(BURST_LENGTH)

    # It survives a round trip through the manifest file the run wrote: the evidence is persisted,
    # not only held in memory.
    written = campaign.read_manifest(campaign.manifest_path_for(job.log_path))
    assert len(written.burst_transitions) == 1
    assert written.burst_transitions[0].verified_burst == BURST_REQUESTED


def test_a_resumed_job_transitions_the_burst_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``resume`` is about which points still run; the boundary's transition is unchanged by it.

    A resumed job whose instrument has moved (or whose definition asks for a burst the instrument is
    not at) has to establish the burst exactly as a fresh one does — the resume drops *points* the log
    already holds, never the instrument state the remaining points need.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)

    manifest = run_job(job, resume=True)

    assert job.fake.burst_writes == [(BURST_REQUESTED, 1)]
    assert [transition.verified_burst for transition in manifest.burst_transitions] == [
        BURST_REQUESTED
    ]


# -------------------------------------- 5. the order: pure refusals precede the write


def test_a_run_declared_against_the_other_process_costs_no_burst_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mode rung is a *pure* refusal — it reads the caption and presses nothing.

    It therefore has to sit **before** the boundary's burst write: a run that is about to be refused
    for declaring the wrong process must not first spend a write on the operator's dialog. The order
    is the safety argument — the reading the rung judges is read-only, so nothing it decides needs
    the write to have happened, and the instrument stays exactly where the operator left it.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job, expected_mode=ProcessMode.SIMULATION)

    assert "UDOP DOP3010.43" in str(excinfo.value)  # the caption the rung read
    assert job.fake.burst_writes == [], (
        "the mode rung is pure and precedes the boundary's write: a run refused on its declared "
        "process must not have written a burst first"
    )
    assert job.fake.burst_length == BURST_LENGTH
    assert job.fake.stored == []


def test_a_resume_refused_for_a_changed_definition_costs_no_burst_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A changed definition is a different job — a pure identity question, known before any gesture.

    The fingerprint comes from the definition file and the previous manifest, so the refusal needs no
    instrument state and must precede the burst write. The case is built so a write *would* be spent:
    the instrument sits at the first run's burst while the changed job declares another, so the
    boundary is one comparison away from writing — and must not.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_LENGTH)
    first = run_job(job)
    changed = campaign.load_campaign(
        campaign_file(
            tmp_path,
            campaign_payload(
                duration_s=CAMPAIGN_DURATION_S + 1.0, burst_length=BURST_REQUESTED
            ),
            "changed.json",
        )
    )
    assert campaign.campaign_fingerprint(changed) != first.fingerprint

    with pytest.raises(campaign.CampaignError) as excinfo:
        campaign.run_campaign(
            changed,
            job.fake,
            store_dir=job.directory,
            log_path=job.log_path,
            resume=True,
            resume_declaration_only=True,
            expected_mode=ProcessMode.INSTRUMENT,
        )

    assert "different job" in str(excinfo.value)
    assert job.fake.burst_writes == [], (
        "a changed definition is a different job: the refusal is known before the instrument is "
        "touched, so the boundary must not spend a burst write on it"
    )
    assert job.fake.burst_length == BURST_LENGTH


# -------------------------------------- 6. the evidence has to be about *this* write


def test_a_transition_whose_evidence_names_another_channel_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VERIFIED`` classifies a *dialog*; the dialog has to be the one this run routed.

    The driver checks its own preconditions, but the boundary compares the evidence against the facts
    it established: a result whose re-opened dialog states another channel is evidence about another
    channel's dialog, and a burst read off it is a burst this job did not read back.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_write_result = BurstWriteResult(
        requested_burst=BURST_REQUESTED,
        state=BurstState.VERIFIED,
        channel="2",
        before_burst=ComboReading(text=str(BURST_LENGTH)),
        after_burst=ComboReading(text=str(BURST_REQUESTED)),
        after_sampling_volume=ComboReading(text="1.460"),
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    message = str(excinfo.value)
    assert "channel '2'" in message and "routed channel 1" in message, message
    assert_no_recording(job)


def test_a_transition_whose_before_row_states_another_burst_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row the write started from is the row this run compared against — or the evidence lies.

    The boundary read the dialog and decided to write because it stated another burst. A result
    whose ``before_burst`` states a third value describes a dialog this run never saw: the instrument
    moved under it, and no burst can be read off the result.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_write_result = BurstWriteResult(
        requested_burst=BURST_REQUESTED,
        state=BurstState.VERIFIED,
        channel="1",
        before_burst=ComboReading(text="8"),
        after_burst=ComboReading(text=str(BURST_REQUESTED)),
        after_sampling_volume=ComboReading(text="1.460"),
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    message = str(excinfo.value)
    assert "started from '8'" in message and "read '4' from the dialog" in message, message
    assert_no_recording(job)


# ------------------------------------- 7. the refusal tells the truth about the write


def test_a_compile_refusal_after_a_transition_does_not_claim_the_application_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boundary may have written before the compile refuses, so the compile must not lie.

    The burst transition is a write to the operator's dialog and sits *before* the compile — the
    compile is the transition's second opinion and reconciles the state the write established. A
    compile that refuses on some *other* fact therefore does so after a write has been spent, and its
    refusal must say exactly what it did (nothing stored, no point recorded) rather than claim the
    whole application untouched.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    reading = expected_snapshot(routed_channel=1, burst=BURST_REQUESTED)
    job.fake.scripted_snapshot = reading.model_copy(
        update={
            "prf_us": InstrumentFact(
                value=str(PRF_US + 10), source=FactSource.READ
            )
        }
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    message = str(excinfo.value)
    assert "prf_us" in message, message
    assert job.fake.burst_writes == [(BURST_REQUESTED, 1)], (
        "the premise: the boundary spent the burst write, then the compile refused on another fact"
    )
    assert "untouched" not in message, (
        "a write was spent on the operator's dialog, so the refusal must not claim the application "
        "is untouched"
    )


def test_a_resume_identity_refusal_after_a_transition_scopes_its_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resume refusal after a transition may not say the whole run did nothing.

    The identity comparison needs the compile, which needs the post-write state, so a resume can be
    refused on its identity only *after* the boundary has transitioned the burst. The refusal may
    then say that no *point* ran and nothing was stored — it may not say the run did nothing, because
    it wrote the operator's dialog.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_LENGTH)
    first = run_job(job)
    campaign.write_manifest(
        campaign.manifest_path_for(job.log_path), legacy_manifest(first)
    )
    # The operator moved the dialog between the runs: the boundary has to bring it back, so a write
    # is spent before the identity is checked.
    job.fake.burst_length = BURST_REQUESTED

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job, resume=True)

    message = str(excinfo.value)
    assert "compilation identity" in message, message
    assert job.fake.burst_writes == [(BURST_LENGTH, 1)], (
        "the identity is checked after the compile, so the transition was spent first"
    )
    assert "Nothing was run" not in message, (
        "the run wrote the operator's dialog, so a refusal must not claim it ran nothing"
    )


# ------------------------ 8. the history accumulates across a job's invocations


def before_texts(manifest: campaign.JobManifest) -> list[str]:
    """The burst each recorded transition started from, oldest first."""
    return [
        "?" if transition.before_burst is None else transition.before_burst.text
        for transition in manifest.burst_transitions
    ]


def test_a_resume_already_at_the_burst_keeps_the_earlier_invocations_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first run writes 10 -> 18; a resume that finds 18 already keeps that record.

    This is the reviewer's first variant, and the bug it pins: a resumed run rewrites the manifest
    beside the log, so a scalar ``burst_transition`` was **replaced** by the resume's own (``None``
    here) and the earlier write vanished from the record. The history is a job-level fact — it
    outlives the invocation that performed it.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    first = run_job(job)
    assert before_texts(first) == ["10"]
    writes_after_first = list(job.fake.burst_writes)
    assert writes_after_first == [(BURST_REQUESTED, 1)]

    # The instrument is still at the burst the first run wrote, so the resume spends no write.
    resumed = run_job(job, resume=True)

    assert job.fake.burst_writes == writes_after_first, (
        "the resume found the instrument already at the job's burst, so it must not write again"
    )
    assert before_texts(resumed) == ["10"], (
        "the resume performed no write, so the earlier invocation's transition is the whole history"
    )
    # ... and it is the *persisted* history that survives, not only the in-memory one.
    written = campaign.read_manifest(campaign.manifest_path_for(job.log_path))
    assert before_texts(written) == ["10"]


def test_a_resume_that_writes_again_holds_both_transitions_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewer's second variant: 10 -> 18 then a resume from 4 -> 18 holds both, in order.

    The instrument moved between the two invocations (the operator put the dialog back to 4), so the
    resumed boundary spends its own verified write. The history has to read oldest first — the
    earlier invocation's transition, then this one's — because the order is the only thing that says
    which state the dialog was moved *out of* when.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    first = run_job(job)
    assert before_texts(first) == ["10"]

    # The operator moved the dialog back to the smaller burst between the two runs.
    job.fake.burst_length = BURST_LENGTH
    notes: list[str] = []
    resumed = run_job(job, resume=True, notes=notes)

    assert job.fake.burst_writes == [(BURST_REQUESTED, 1), (BURST_REQUESTED, 1)], (
        "the resume's write is the second one this job spent"
    )
    assert before_texts(resumed) == ["10", "4"], (
        "both transitions are held, oldest first: the first invocation's, then the resume's"
    )
    assert [transition.verified_burst for transition in resumed.burst_transitions] == [
        BURST_REQUESTED,
        BURST_REQUESTED,
    ]
    written = campaign.read_manifest(campaign.manifest_path_for(job.log_path))
    assert before_texts(written) == ["10", "4"]


def test_a_manifest_without_the_history_field_reads_as_an_empty_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every manifest written before the history existed carries no field, and must still load.

    A reader that refused such a manifest would make every committed job's record unreadable; one
    that *required* the field would do the same. So it is defaulted to the empty tuple — and a
    resume over one proceeds rather than refusing. What it *carries* is no longer only what the
    field says: the job's own log records the transitions the boundary spent, so the resume starts
    from the log's history instead of from nothing.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    first = run_job(job)
    assert before_texts(first) == ["10"]

    payload = first.model_dump(mode="json")
    payload.pop("burst_transitions")
    legacy = campaign.JobManifest.model_validate(payload)
    assert legacy.burst_transitions == ()

    campaign.write_manifest(campaign.manifest_path_for(job.log_path), legacy)
    # The instrument is at the burst the first run wrote, so the resume spends no write. The
    # manifest it reads carries no history at all — and the job's own **log** does, so the
    # transition the first invocation performed is recovered from there rather than lost with the
    # field (§O4). Losing the field on a manifest is not losing the occurrence.
    resumed = run_job(job, resume=True)
    assert before_texts(resumed) == ["10"], (
        "the history a manifest without the field cannot carry is still the job's, and the log is "
        "where it survives"
    )


def test_the_notes_separate_the_accumulated_history_from_this_invocations_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resume's notes have to say which transitions it inherited and which it performed itself.

    The manifest's ``burst_transitions`` is a *history*, not a report of the current invocation, so
    a reader of the run's own notes must be able to tell the two apart. The distinction is stated
    where the run knows it: how many transitions were carried from the previous manifest, and what
    this invocation did with them.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    run_job(job)
    job.fake.burst_length = BURST_LENGTH
    notes: list[str] = []
    resumed = run_job(job, resume=True, notes=notes)

    text = " ".join(notes)
    assert "carried from the previous manifest" in text, notes
    assert "this invocation" in text, notes
    assert "2 transition(s)" in text, notes
    assert before_texts(resumed) == ["10", "4"]


def test_a_resume_that_wrote_nothing_says_so_and_still_carries_the_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No write in this invocation is a fact the notes state, not a gap in the record."""
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    run_job(job)
    notes: list[str] = []
    resumed = run_job(job, resume=True, notes=notes)

    text = " ".join(notes)
    assert "no burst write" in text, notes
    assert before_texts(resumed) == ["10"]


def test_a_no_snapshot_resume_retains_the_history_and_records_no_new_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--no-snapshot`` reads nothing, so it transitions nothing — but it loses no history.

    The flag is the explicit bypass: the boundary cannot know what to write without the reading it
    skips, so the burst the earlier invocation wrote is **retained** on the record while this
    invocation's contribution is explicitly none.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    first = run_job(job)
    assert before_texts(first) == ["10"]
    writes_after_first = list(job.fake.burst_writes)

    notes: list[str] = []
    resumed = run_job(
        job,
        resume=True,
        no_snapshot=True,
        resume_declaration_only=True,
        notes=notes,
    )

    assert resumed.declared_only
    assert job.fake.burst_writes == writes_after_first, (
        "no-snapshot performs no transition, so it spends no write"
    )
    assert before_texts(resumed) == ["10"], (
        "the history the earlier invocation wrote is retained, not dropped by the bypass"
    )
    text = " ".join(notes)
    assert "no burst write" in text, notes


# -------- 9. a refusal after a verified write keeps the record of it in the job's own log
#
# The gap this closes (docs/dop3000/failed-invocation-provenance.md §1): the write is real the
# moment the application accepts it, while the job manifest — its only durable record until now —
# is written at the *end* of the invocation. A compile refusal or a resume-identity refusal in
# between therefore left the instrument moved and no artifact saying so. The verified transition
# is appended to the job's own log at the boundary, before the compile and before the identity
# comparison, and the next invocation folds it into the accumulated history.


def refuse_the_compile(job: Job) -> None:
    """Script the reading the *post-write* compile reconciles, with a fact that disagrees.

    By the time the compile runs, the boundary has already written and verified the burst — which
    is exactly the shape this slice exists for: a real instrument mutation followed by a refusal
    that used to lose the record of it.
    """
    reading = expected_snapshot(routed_channel=1, burst=BURST_REQUESTED)
    job.fake.scripted_snapshot = reading.model_copy(
        update={"prf_us": InstrumentFact(value=str(PRF_US + 10), source=FactSource.READ)}
    )


def mutation_records(job: Job) -> tuple[SweepBurstMutation, ...]:
    """Every burst-mutation record the job's log holds, in order; none when there is no log."""
    if not job.log_path.is_file():
        return ()
    return burst_mutations(read_entries(job.log_path))


def test_a_compile_refusal_after_a_verified_transition_keeps_the_mutation_in_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The instrument moved, no manifest was written, and the log is the record of the move.

    The record is the driver's own evidence (request, state, both rows on both sides, the
    dependent sampling-volume statement) attributed to the job and the definition it ran, and it
    carries an occurrence identity — so a later reader can say *what* was written and can tell
    two identical writes apart.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    refuse_the_compile(job)

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    assert "prf_us" in str(excinfo.value), excinfo.value
    assert job.fake.burst_writes == [(BURST_REQUESTED, 1)], (
        "the premise: the boundary spent a verified write before the compile refused"
    )
    records = mutation_records(job)
    assert len(records) == 1, records
    record = records[0]
    assert record.mutation_id, "an occurrence identity, so the event is identifiable as itself"
    assert record.occurred_at is not None
    assert record.job == job.definition.job
    assert record.fingerprint == campaign.campaign_fingerprint(job.definition)
    assert record.routed_channel == 1
    assert record.transition.state is BurstState.VERIFIED
    assert record.transition.verified_burst == BURST_REQUESTED
    assert record.transition.before_burst is not None
    assert record.transition.before_burst.text == "10"
    assert record.transition.verified_sampling_volume is not None
    # Nothing was stored, no point was recorded, and no manifest pretends the job ran: the log
    # entry is the whole durable record of this invocation.
    assert job.fake.stored == []
    assert "apply_point" not in [call[0] for call in job.fake.calls]
    assert not campaign.manifest_path_for(job.log_path).is_file()


def test_a_resume_identity_refusal_after_a_verified_transition_keeps_the_mutation_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other refusal that follows the write keeps it on the same terms.

    The identity comparison needs the compile, which needs the post-write reading, so a resume
    can be refused on its identity only *after* the boundary has transitioned the burst — and the
    transition has to be durable before the comparison is made.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_LENGTH)
    first = run_job(job)
    campaign.write_manifest(
        campaign.manifest_path_for(job.log_path), legacy_manifest(first)
    )
    # The operator moved the dialog between the runs: the boundary brings it back, so the refusal
    # follows a verified write.
    job.fake.burst_length = BURST_REQUESTED

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job, resume=True)

    assert "compilation identity" in str(excinfo.value), excinfo.value
    assert job.fake.burst_writes == [(BURST_LENGTH, 1)]
    records = mutation_records(job)
    assert len(records) == 1, records
    assert records[0].transition.requested_burst == BURST_LENGTH
    assert records[0].transition.before_burst is not None
    assert records[0].transition.before_burst.text == str(BURST_REQUESTED)
    # The manifest beside the log is still the one the first run wrote, and the refusal recorded
    # no point of its own.
    kept = campaign.read_manifest(campaign.manifest_path_for(job.log_path))
    assert kept.compilation_identity is None
    assert kept.burst_transitions == ()
    assert len(point_names(read_entries(job.log_path))) == 2


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (BurstState.UNCHANGED, "the burst row does not offer 18: nothing was sent"),
        (
            BurstState.UNVERIFIED,
            "the burst row did not restate the selection: the dialog was cancelled",
        ),
    ],
)
def test_a_transition_that_did_not_verify_is_never_recorded_as_a_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: BurstState,
    reason: str,
) -> None:
    """``UNCHANGED`` / ``UNVERIFIED`` kept nothing, so recording one as a mutation would be a lie.

    The doc's own scope: neither outcome is a mutation that needs a record, and the refusal that
    reports it already names the state and the reason.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job_with_transition(
        job,
        BurstWriteResult(
            requested_burst=BURST_REQUESTED,
            state=state,
            channel="1",
            discarded=True,
            reason=reason,
        ),
    )

    with pytest.raises(campaign.CampaignError):
        run_job(job)

    assert mutation_records(job) == ()
    assert_no_recording(job)


def test_a_run_that_needs_no_transition_records_no_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An instrument already at the job's burst sends nothing, so there is no event to record.

    The run's own log is a real point log — and holds no mutation, because no write was spent.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_LENGTH)

    manifest = run_job(job)

    assert manifest.burst_transitions == ()
    assert job.fake.burst_writes == []
    assert mutation_records(job) == ()
    assert len(point_names(read_entries(job.log_path))) == 2, (
        "the run's own records are still written: the mutation type is an addition, not a"
        " replacement"
    )


def test_the_next_invocation_folds_the_logs_record_into_the_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused invocation's transition is recovered by the next one — from the log alone.

    The refused invocation wrote no manifest, so the job's own log is the only source the
    accumulation can read for it; the recovered entry has to land on the rewritten manifest (and
    survive a round trip through the file), not only in the returning object.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = BURST_REQUESTED
    first = run_job(job)
    assert first.burst_transitions == (), "the premise: this invocation spent no write"

    job.fake.burst_length = 10
    refuse_the_compile(job)
    with pytest.raises(campaign.CampaignError):
        run_job(job, resume=True)
    refused = mutation_records(job)
    assert len(refused) == 1, refused

    # The reading is clean again, and the instrument is at the burst the refused invocation wrote.
    job.fake.scripted_snapshot = None
    notes: list[str] = []
    resumed = run_job(job, resume=True, notes=notes)

    assert job.fake.burst_writes == [(BURST_REQUESTED, 1)], (
        "the instrument is at the job's burst, so the resumed invocation spends no write of its"
        " own — the history it carries is recovered, not spent again"
    )
    assert resumed.burst_transitions == (refused[0].transition,), (
        "the recovered transition is the occurrence the log holds, by full result equality"
    )
    assert before_texts(resumed) == ["10"]
    written = campaign.read_manifest(campaign.manifest_path_for(job.log_path))
    assert before_texts(written) == ["10"], (
        "the recovered transition survives the manifest file, not only the returned object"
    )
    # The mutation record is not a point: the resume's own inputs still read the run's records.
    assert len(campaign.recorded_points(job.log_path)) == 2
    assert len(point_names(read_entries(job.log_path))) == 2


def test_an_occurrence_the_manifest_already_carries_is_not_folded_in_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transition has two records — the log entry and the manifest field — and they reconcile.

    Every verified write reaches the log *and*, when the invocation runs to its manifest, the
    manifest. The next invocation must not read the log as a second, unseen mutation: the
    occurrence is consumed once, and the history stays one event long.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    first = run_job(job)
    assert before_texts(first) == ["10"]
    assert len(mutation_records(job)) == 1, "the same occurrence is in the log and on the manifest"

    resumed = run_job(job, resume=True)

    assert job.fake.burst_writes == [(BURST_REQUESTED, 1)], (
        "the resume found the instrument at the job's burst and wrote nothing"
    )
    assert len(resumed.burst_transitions) == 1, (
        "the log entry and the manifest field are one occurrence, not two"
    )
    assert before_texts(resumed) == ["10"]


def test_two_identical_transitions_stay_two_ordered_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Occurrence-safety: ``10 -> 18``, back to ``10``, ``10 -> 18`` again is **two** events.

    A reconciliation keyed on the transition's *content* — request plus both rows plus the state —
    would fold the second write into the first: both are ``10 -> 18``. The history is an ordered
    history of occurrences, so each log entry is consumed once, in sequence, by full result
    equality, and the second write finds its own counterpart.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    first = run_job(job)
    assert before_texts(first) == ["10"]

    # The operator put the dialog back to 10: the resumed run has to write 10 -> 18 again.
    job.fake.burst_length = 10
    second = run_job(job, resume=True)

    assert before_texts(second) == ["10", "10"]
    assert second.burst_transitions[0] == second.burst_transitions[1], (
        "the premise: the two transitions are identical in content"
    )
    assert len(mutation_records(job)) == 2

    # A third invocation that writes nothing keeps both occurrences: neither collapses into the
    # other, and neither is dropped.
    notes: list[str] = []
    third = run_job(job, resume=True, notes=notes)

    assert job.fake.burst_writes == [(BURST_REQUESTED, 1), (BURST_REQUESTED, 1)]
    assert len(third.burst_transitions) == 2, (
        "two identical transitions are two occurrences and must never collapse into one"
    )
    assert before_texts(third) == ["10", "10"]
    written = campaign.read_manifest(campaign.manifest_path_for(job.log_path))
    assert before_texts(written) == ["10", "10"]


def test_an_append_failure_aborts_before_the_compile_and_before_any_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: a verified write with no durable record aborts the invocation right there.

    Nothing can make the already-performed mutation durable at that point, but it must not be
    *compounded* by recording points under a provenance contract that was not met. So the failure
    raises out of ``run_campaign`` naming the append (never routed through the runner's
    ``log_errors`` list, which only reaches a reader through a manifest a refused invocation never
    writes), and the compile, the points and the manifest are all never reached.
    """
    job = campaign_job(tmp_path, monkeypatch, burst_length=BURST_REQUESTED)
    job.fake.burst_length = 10
    appends: list[Path] = []
    compiles: list[object] = []
    real_compile = campaign.compile_campaign

    def refuse_the_append(path: Path, entry: object) -> None:
        appends.append(Path(path))
        raise OSError("the disk is full")

    def counting_compile(*args: object, **kwargs: object) -> object:
        compiles.append(args[0] if args else kwargs)
        return real_compile(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(campaign, "append_entry", refuse_the_append)
    monkeypatch.setattr(campaign, "compile_campaign", counting_compile)

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    message = str(excinfo.value)
    assert "disk is full" in message, message
    assert str(job.log_path) in message, message
    assert str(BURST_REQUESTED) in message, message
    assert appends == [job.log_path], "the boundary tried exactly one append"
    assert compiles == [], "the invocation aborts before the compile"
    assert job.fake.stored == [], "no point was stored"
    assert "apply_point" not in [call[0] for call in job.fake.calls]
    assert not campaign.manifest_path_for(job.log_path).is_file()
    assert mutation_records(job) == ()


# ------------ 10. the pass's row says where a recovered transition came from


def test_a_pass_row_names_the_job_log_for_a_recovered_transition(tmp_path: Path) -> None:
    """A row may now carry an entry no invocation of its own ever wrote, and must not claim it did.

    A refused invocation's transition reaches the job manifest only through the job's log, so when
    a pass's row is folded from such a manifest the entries beyond the row's own history are not
    necessarily "added by this recording" — the sentence names the log they were recovered from
    (``docs/dop3000/failed-invocation-provenance.md`` §5.3).
    """
    run = committed_run()
    job = run.jobs[0]
    manifest = run_plan.new_run_manifest(run, now=datetime(2026, 9, 20, 12, tzinfo=UTC))
    recovered = burst_transition_result(10)
    log_path = tmp_path / "job.jsonl"
    append_entry(
        log_path,
        SweepBurstMutation(
            mutation_id="b" * 32,
            # Before the invocation whose manifest is folded below: the transition was recorded by
            # an earlier one, which is what makes it *recovered* rather than this recording's own.
            occurred_at=datetime(2026, 9, 20, 11, 30, tzinfo=UTC),
            job=job.job,
            fingerprint=job.definition_fingerprint,
            routed_channel=run.channel,
            transition=recovered,
        ),
    )
    job_manifest = job_manifest_for(run, job).model_copy(
        update={"burst_transitions": (recovered,), "log_path": str(log_path)}
    )

    recorded = run_plan.record_job(manifest, run, job, job_manifest)

    note = recorded.jobs[0].note
    assert note is not None
    assert "job's log" in note, note
    assert "added by this recording" not in note, note
    assert [t.before_burst.text for t in recorded.jobs[0].burst_transitions] == ["10"]
