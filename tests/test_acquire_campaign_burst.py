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
  which order, and what the application answered.

Everything here is headless: the run drives the runner's own in-memory fake (imported, not
re-implemented), whose burst transition is scriptable so every refusal the boundary has an
answer for can be exercised without an instrument.
"""

from __future__ import annotations

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
from test_acquire_runner import (
    BURST_LENGTH,
    PRF_US,
    expected_snapshot,
)

from udv_echo_process.acquire import campaign
from udv_echo_process.acquire.actuator import (
    BurstState,
    BurstWriteResult,
    ComboReading,
    DialogField,
    ProcessMode,
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
    resume over one proceeds with an empty carried history rather than refusing.
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
    # The instrument is at the burst the first run wrote, so the resume spends no write and the
    # history it carries is the empty one the legacy manifest states.
    resumed = run_job(job, resume=True)
    assert resumed.burst_transitions == ()


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
