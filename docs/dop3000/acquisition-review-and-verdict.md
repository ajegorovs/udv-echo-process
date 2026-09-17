# DOP3010 acquisition — external review and stabilization verdict

**Status (2026-09-18):** the review's findings 1–8 are **verified** against this
checkout; its direction is **accepted**, its roadmap is **accepted only in part**
— the P0 correctness slice, the canonical operation model (under the existing
decoded-metadata gate), the campaign-compiled-against-live-state step and the
acquisition certificate are taken; the `driver.py` decomposition, the explicit
state machine and the protocol replacement are **deferred behind a trigger**
(§6). One defect the review did not see is recorded in §5 and blocks its own
Phase 0 premise.

## 1. What this document is, and how it relates to the other docs

**What this document is.** A decision record with two halves: the review exactly
as it was submitted (§2), and the verdict on it — what is true, what is
over-stated, what is missing — with the evidence each claim was checked against
(§3–§5), the per-phase decision (§6), the first implementation slice (§7) and
how to re-check any of it (§8).

**Authority relationship.** [`handoff-dop3010-acquisition.md`](handoff-dop3010-acquisition.md)
stays the state-of-the-work handoff and the measurement record;
[`udop-automation.md`](udop-automation.md) stays the verified UI rule set; the
actionable backlog lives in [`../agenda.md`](../agenda.md). This file is the
*decision* record — read it before re-proposing the same review, and before
splitting `acquire/driver.py`.

---

## 2. The review (as received)

> Reproduced from the session message. Only the extraction's intra-word
> whitespace artifacts are normalized (`pres erve` → `preserve`, `app lication` →
> `application`, `fingerpr inting` → `fingerprinting`); the ASCII diagrams are
> re-drawn because the box-drawing characters did not survive extraction.
> Wording, structure and every number are unchanged.

A repository-wide pass focused on how the newly merged DOP3010 acquisition code
fits into the older signal-processing architecture, rather than reviewing only
`driver.py`. Conclusion: the acquisition implementation contains a lot of
valuable, experimentally validated knowledge, but it should now be **stabilized
and decomposed before substantially extending its parameter-sweep capabilities**.

The main goal of the refactor should not be to make the Win32 code prettier. It
should be:

> preserve the live-proven DOP3010 interaction recipes exactly, while separating
> **instrument semantics**, **Windows/UI mechanics**, **experiment
> specification**, **execution state**, and **scientific verification** so each
> can be tested independently.

That distinction matters because several of the risks found are not GUI bugs at
all — they are cross-layer consistency problems.

### What the repository has become

Before the acquisition merge, `udv-echo-process` had a fairly coherent
architecture built around two data-processing paths: the legacy `.ADD` path and
the typed/provenance-aware `.BDD` artifact pipeline. `docs/architecture.md` still
describes exactly those two pipelines and its package map does not include
acquisition.

But PR #1 added something qualitatively different: a **live instrument-control
subsystem** with planning, UI automation, execution, campaign management,
logging, binary verification, live commands and Windows-session dispatch. The
merge itself documents successful live runs — screen fingerprinting, preflight, a
six-point campaign, and resume behavior — and also explicitly notes that there is
currently no CI.

So the correct conceptual architecture is now three major domains:

```text
                        udv-echo-process

   Data processing      DOP format/model       Acquisition
   + analysis           semantics              + experiment control

     .ADD / .BDD        operation blocks,       plan → preflight →
     transforms,        ChannelConfig,          configure → acquire →
     RPM, profiles      timestamps, etc.        store → verify → log

                    shared scientific models
```

The existing README and contributor guide have not caught up with that. The
README still advertises parsing, visualization and RPM but not `udv-acquire`,
despite that executable now being installed by the package. `AGENTS.md` likewise
defines the repository primarily as a signal-processing toolkit and its
architecture tree omits `acquire/`.

That documentation drift is not merely cosmetic. It is contributing to
architectural drift.

### What is already strong and should be preserved

The most important design decision is that the **stored `.BDD` artifact is
treated as the authority**, rather than trusting that a GUI field displayed what
was typed. The live work discovered several failure modes where GUI readback or
apparent application state was insufficient, and the code correctly reflects
that.

The other particularly strong decisions are:

- reset the acquisition block before independent points because stale profiles
  can produce a structurally valid but scientifically wrong file;
- write resolution before gate count because the application silently
  recomputes/clamps gates;
- stop the run when application state is unverified rather than cascading the
  failure through the rest of the sweep;
- distinguish failures before a file exists from failures concerning an
  already-stored file;
- answer unknown modal situations conservatively instead of guessing;
- bind controls structurally rather than by unstable control IDs or captions;
- keep planning math independent of Windows;
- use a fake actuator extensively so most run logic can be tested without the
  DOP3010 computer;
- retain real `.BDD` fixtures alongside synthetic/byte-level tests.

Those rules came from real instrument failures and should be treated almost like
hardware-driver invariants. The refactor should **move them, not reinterpret
them**.

The dispatcher/session work should also stay conceptually separate from the
instrument library: the agent/service shell is in session 0 while UDOP lives in
the interactive session, and therefore a no-window scheduled task launches
acquisition commands in the correct desktop. That is deployment infrastructure,
not acquisition logic.

### Findings to address before the larger refactor

**1. Channel-aware decoding and channel-aware verification disagree.** The
clearest actual bug. The runner decodes the stored file using the configured
measurement channel (`_decode(path, self._channel_setting.channel)`) but then
`_verify_stored()` calls `verify_stored_point(path, parameters)` without
forwarding the channel; `verify_stored_point()` defaults to `channel=1`. So for a
manual-mode acquisition on channel 2/10, the canonical BDD decode uses channel 3
while the raw-word verification uses channel 1. The verify tests themselves do
exercise channel offsets, including channel 2, so the low-level implementation
supports it — the problem is specifically the subsystem integration. Fix
immediately, followed by a runner-level multi-channel regression test.

**2. Campaign specification currently contains facts that really belong to the
instrument.** The campaign model includes PRF, emissions/profile and burst
length, and every point carries sound speed and first gate. Planning treats those
as shared conditions. But the actual run does not first produce a strong live
configuration snapshot establishing that the DOP3010 currently has exactly those
settings. The CLI makes the issue more visible: it has reference-installation
defaults such as sound speed 1460, first gate 2, PRF 212 µs, emissions 150, burst
4, which are injected into a sweep unless the operator overrides them. That is
convenient during bring-up, but dangerous as a long-term scientific interface. A
campaign should ideally say *what I want to vary*, *what I require to stay fixed*,
*what tolerances I accept*, while the live instrument snapshot says *what the
DOP3010 is actually configured to do*. Then the two are reconciled before
recording begins. At the moment those concepts are partly merged.

**3. Stored-file covariates are deliberately not enforced.**
`verify_stored_point()` can verify sound speed, PRF, emissions and burst, but
`check_covariates=False` is the default. The historical reason is documented: an
earlier point had requested emissions=52 while the file said emissions=150, so
making the check mandatory would have invalidated a file whose gate/rung/depth
values otherwise matched. That discrepancy is exactly why the check should not
stay optional indefinitely — for sensitivity experiments, the parameters you
think are fixed are just as scientifically important as the parameter being
swept.

**4. Nominal recording duration is not the same thing as retained observation
duration.** The largest experiment-design concern. The campaign deliberately
allows a requested point even when the estimated profile count exceeds the
retained block; the planner emits a note instead of refusing it. The repo
documents the observed case: requested window ~12 s, retained profiles ~257,
retained interval ~8.4 s, because the application behaves as a ring buffer. That
may be acceptable for the experiment — but it needs to become explicit
experimental semantics. Distinguish at least `requested_duration_s`,
`recording_wall_time_s`, `stored_profile_count`, `stored_time_span_s`,
`retained_fraction`, `wrapped_block`. A point requested for 12 seconds but
containing 8.4 seconds of data should not simply be represented as a 12 s point.

**5. Timing is modeled but effectively not being recorded.** `SweepPointRecord`
already contains a `ProfileTiming` field, but the runner's `_record()` does not
populate it, so it falls back to its empty default. This conflicts with the
acquisition documentation, which correctly treats achieved timing as an important
certificate. Rather than improving the current theoretical period approximation,
derive actual retained timing from the `.BDD` profile timestamps after storage
wherever possible.

**6. Verification is duplicated outside the canonical BDD decoder.** The
acquisition verifier has its own byte-offset implementation for the DOP operation
block, while the canonical BDD reader already knows that operation block,
including the same base offset, 1024-byte channel stride and many of the same
words. The duplication exists because `ChannelConfig` doesn't expose several
acquisition-critical facts, especially emissions/profile and the raw resolution
rung. So the same operation block has two decoders, two models, two possible
futures — an architectural warning sign.

**7. The runner can mark a point OK without word-level verification.** If
`verify_stored_point` is unavailable, `_verify_stored()` marks the point `OK` and
places a warning in the reason saying only the size signature supports it. Now
that `verify.py` is part of the same installed package, there is no strong reason
for this defensive optional import. For scientific acquisition, prefer fail-closed
semantics: stored + canonical decode + required verification, otherwise INVALID —
not "verifier unavailable → size approximately plausible → OK with warning".

**8. The size check has become more important than it should be.**
`SizeSignature` is intentionally loose — roughly 1.7 bytes/gate/profile with a
factor-of-two acceptance band. That was an excellent early guard against the
10/60 stale-buffer failures. It should remain as a **gross corruption detector**,
but no longer carry the burden of determining how much valid observation time
exists. The `.BDD` parser already has profile timestamps; that is stronger
evidence.

### The refactor the review recommends

An incremental migration, not a rewrite. The rule throughout:

> First preserve behavior behind narrower interfaces. Only after the instrument
> tests still pass should implementation logic be changed.

1. **Phase 0 — stabilize master before structural changes.** Fix the
   channel-verification bug first; add runner-level tests for channels other
   than 1; make the verifier mandatory; decide how critical covariates are
   verified; populate timing/retained-span information; and remove or clearly
   mark reference-machine defaults from normal production commands. Add CI for
   all platform-neutral tests and Ruff. This phase should change almost no
   architecture; its purpose is to make today's behavior trustworthy enough to
   refactor.
2. **Phase 1 — one canonical DOP3010 operation-block model.** Extract the
   operation-parameter decoding currently embedded in `io/dop/bdd.py` into
   something like `io/dop/operation.py`, producing a frozen Pydantic
   `DopOperationBlock` carrying the facts the file actually proves: channel, PRF
   period, burst, first gate, resolution index, gate count, emissions/profile,
   sound speed, possibly assisted-mode flag, multiplexer bits and other settled
   fields. `bdd.py` consumes this decoder to construct `ChannelConfig`;
   acquisition verification consumes the exact same object.
3. **Phase 2 — separate request, live instrument state and acquired evidence.**
   `PointRequest` (what the experiment asks for), `InstrumentSnapshot` (what
   UDOP reports before recording), `AcquisitionCertificate` (what the artifact
   proves after). No field may mean both requested and observed; a campaign
   compiles against an `InstrumentSnapshot`, not against the assumption that the
   JSON definition describes the machine.
4. **Phase 3 — refactor `driver.py` by extraction, not redesign.** At ~150 kB it
   handles Win32 calls, cursor handling, window enumeration, semantic control
   resolution, menu/dialog recognition, DOP-specific rules, diagnostics and
   whole-cycle orchestration: split into `win32_transport.py`, `ui_snapshot.py`,
   `bindings.py`, `gestures.py`, `udop_session.py`. First pass moves the existing
   algorithms verbatim — do **not** improve menu hover, button hold, popup
   ordering, `ClipCursor` behavior or dialog rules during this phase.
5. **Phase 4 — an explicit UDOP application state model.** The code already
   implements a state machine implicitly through `StripView`, overlay checks and
   runner logic; make it explicit (`READY`, `RECORDING`, `STORE_VIEW`,
   `STORE_DIALOG`, `PARAMETERS_MANUAL`, `PARAMETERS_ASSISTED`, `WARNING`,
   `UNKNOWN`, plus transitions). A high-level operation declares its legal
   source/target states instead of the runner reasoning indirectly through
   several low-level calls.
6. **Phase 5 — narrow the interface used by the runner.** `Actuator` exposes
   low-level concepts (`press`, `answer_overlay`, `set_store_name`,
   `wait_for_view`, `commit_store`) while the runner casts it to a richer
   `SweepActuator`. Replace with a high-level instrument/session port closer to
   `snapshot()`, `reset_acquisition_buffer()`, `apply_window(request)`,
   `acquire(duration)`, `store(name, directory)`.
7. **Phase 6 — compile campaigns against actual instrument state.**
   `JSON → plan → run` becomes `JSON → static plan → live preflight/snapshot →
   compiled executable plan → run`, the compiled plan carrying the fixed
   instrument configuration and the actual channel mode. A campaign requiring a
   manual channel when channel 3 is assisted should fail before the first
   recording; a campaign declaring PRF=212 µs against a snapshot saying 169 µs
   should fail or require an explicit policy.
8. **Phase 7 — make scientific QC a first-class result.** Replace the
   `OK / FAILED / INVALID` decision spread across runner checks with a structured
   certificate retaining requested parameters, pre-record readback, stored
   operation block, profile count, actual stored time span, size ratio,
   block-wrap status, configuration mismatches and verification verdict; `OK`
   is derived from explicit acceptance rules.
9. **Phase 8 — upgrade the campaign/job log.** Keep the append-only JSONL
   principle, but version the schema and make the manifest authoritative about
   job identity: campaign definition hash, git commit/package version, channel,
   UDOP/instrument fingerprint, preflight snapshot, fixed configuration,
   start/end timestamps, acceptance policy. A resume should confirm the old
   record belongs to the same campaign fingerprint and a compatible
   instrument/configuration, not merely find `prefix-label` in a log.
10. **Phase 9 — recorded UI snapshots and hardware-in-the-loop regression
    gates.** Keep `FakeUdopApp`; supplement it with serialized control-tree
    snapshots captured from the real application (manual-ready, assisted-ready,
    recording, store view, store dialog, parameters menu, manual parameters
    dialog, assisted parameters dialog, warning) so binding/resolver tests run
    without Windows. Separately, define a short real-machine acceptance sequence:
    status → parameter-dialog read/cancel → preflight → one short stored point →
    canonical decode → certificate verification → clean READY state.
11. **Phase 10 — reconcile repository architecture and contributor rules.**
    Update `README.md`, `docs/architecture.md`, `AGENTS.md`, `docs/agenda.md` and
    `acquire/__init__.py` together (the latter still describes acquisition as
    four concerns). Also decide whether the repository really forbids
    dataclasses: `AGENTS.md` says it does, while acquisition introduced
    `PointOutcome`, `_Attempt`, `WordFacts` and `VerificationResult` as
    dataclasses.

### Target package structure

```text
src/udv_echo_process/
├── models/
│   └── channel_config.py
├── io/dop/
│   ├── bdd.py
│   ├── operation.py          # canonical DOP operation-block decode
│   └── models.py             # DopOperationBlock / raw proven facts
├── acquire/
│   ├── models.py             # request / snapshot / certificate / verdict
│   ├── plan.py               # pure experiment planning
│   ├── campaign.py           # definitions + compilation + resume semantics
│   ├── runner.py             # experiment orchestration only
│   ├── log.py                # versioned durable run records
│   ├── instrument.py         # high-level InstrumentSession Protocol
│   └── udop/
│       ├── session.py        # DOP3010 implementation of InstrumentSession
│       ├── state.py          # explicit UDOP application state machine
│       ├── bindings.py       # control-tree semantic roles
│       ├── gestures.py       # proven application gestures
│       ├── snapshot.py       # control-tree/window snapshot models
│       ├── win32.py          # Windows transport + cursor/foreground
│       └── profile.py        # version/install-specific UI expectations
├── process/  provenance/  storage/  analysis/
```

`acquire/udop/win32.py` knows nothing about gates, PRF or DOP physics;
`acquire/plan.py` knows nothing about HWNDs or `WM_LBUTTONDOWN`.

### Desired execution flow

```text
CampaignDefinition
  → static validation
  → UDOP session preflight   (UI/application fingerprint, selected channel +
                              manual/assisted mode, actual fixed parameters)
  → InstrumentSnapshot
  → compile campaign         (requested variable(s), verified fixed covariates,
                              depth/rung/gate constraints, retention policy,
                              per-point expectations)
  → ExecutableCampaign
      for each point:
        reset buffer → apply request → pre-record readback → acquire → store
        → canonical BDD decode (operation block, actual channel, profile
          timestamps/count, actual config)
        → AcquisitionCertificate
        → accept / invalidate point → append durable record
```

The GUI becomes one implementation detail in the middle — which also permits a
second `InstrumentSession` implementation (DLL, serial command path, vendor
protocol, config file) without rewriting planning, QC, logging or campaign
semantics.

### The sensitivity-study requirement

A sensitivity campaign should express experimental intent rather than a list of
GUI actions:

```text
fixed:    channel = 1, sound_speed = observed baseline, first_gate = observed
          baseline, duration = 12 s requested, minimum retained duration = 10 s,
          mode = manual
vary:     resolution rung = [1, 2, 4, 8]
derived:  gates = maintain ~99 mm measurement window
accept:   exact resolution rung, exact requested gate count or explicit
          tolerance, fixed PRF, fixed emissions/profile, fixed burst,
          retained duration >= threshold, no buffer contamination
```

Later sweeps of emissions/profile, burst length, PRF, sensitivity and emitting
power can then distinguish *independent factor*, *coupled derived parameter*,
*fixed covariate*, *nuisance observable* and *QC criterion*.

### Refactoring priority

Do not start by splitting `driver.py`. Start with:

```text
P0 correctness fixes
  → canonical DOP operation model
  → instrument snapshot + acquisition certificate
  → campaign compiled against live state
  → high-level instrument/session protocol
  → driver extraction
  → state-machine cleanup
  → logging/resume/schema hardening
```

If `driver.py` is split first, you mostly redistribute 150 kB of code while
leaving the semantic duplication intact; if the models and interfaces come first,
the decomposition has obvious destinations.

### Acceptance criteria

A campaign can be reviewed offline and the resulting job can later answer,
without reference to the GUI session: what did we ask the DOP3010 to do; what was
it configured to do before the point; what did the GUI read back before
acquisition; which channel and mode were actually active; what did the resulting
BDD say the settings really were; how many profiles were retained; what time span
did they cover; did the ring buffer wrap; did the fixed covariates remain fixed;
why exactly is this point accepted or rejected; which software/version/
configuration produced it; can this exact job safely resume.

Today the repository can answer a good fraction of those, but the answers are
distributed across the campaign definition, runner, GUI observations, JSONL
record, verifier and BDD parser. The refactor should make **one acquisition
certificate per point** the place where those facts converge.

### Immediate next implementation slice

**Acquisition correctness baseline before architectural refactor**: the
channel-forwarding fix, a channel-2 runner regression test, mandatory canonical
verification, proper population of actual timing/profile-span evidence, and tests
demonstrating what happens when fixed campaign covariates disagree with the
stored operation block. It should avoid reorganizing the Win32 driver. After that
lands, a second PR can introduce the canonical `DopOperationBlock` and remove the
duplicated word decoder.

The strongest overall impression: the project does **not** need to throw away the
current automation. The difficult experimental reconnaissance has already
produced valuable, defensible rules. The opportunity is to turn those hard-won
rules into a smaller number of explicit contracts, so that the next person adding
a sweep parameter does not need to understand a 150 kB Windows driver, two BDD
decoders, the runner's implicit state machine, and the history of every live
failure before they can safely make a change.

---

## 3. Verdict — findings verified, roadmap accepted in part

Every load-bearing claim was checked against this checkout rather than accepted
on reading. All eight findings are real.

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | Verify reads the wrong channel | **True — reproduced** | `runner.py:526` decodes with `self._channel_setting.channel`; `runner.py:589` calls `verify_stored_point(path, parameters)` with no channel; the signature is `verify_stored_point(path, requested_parameters, channel: int = 1, *)` (`verify.py:349`). Channel offsets are supported and tested at the unit level (`tests/test_acquire_verify.py:394`), so the gap is integration only. |
| 2 | Campaign carries instrument facts | **True** | `campaign.py:229-232` requires `prf_us` / `emissions_per_profile` / `burst_length`; `live.py:45-56` `DEFAULT_MEASUREMENT` feeds the `udv-acquire sweep` argument defaults. No pre-record read of those words exists to confirm them. |
| 3 | Covariates not enforced | **True** | `check_covariates: bool = False` (`verify.py:353`); the reason is documented at `verify.py:360-370`. |
| 4 | Cap stated, not refused | **True** | `campaign.py:572-588` builds a `note` and appends the point anyway; the comment states a sweep would raise (`plan.assert_window_fits`). |
| 5 | Timing never populated | **True** | `log.py:221` `timing: ProfileTiming = Field(default_factory=ProfileTiming)`; `runner.py:746-759` never passes `timing`. Confirmed against the live job logs: **all 9 records** in the gitignored `outputs/live/*.jsonl` (`campaign-bringup`, `ladder`, `sweep`) carry `{'target_s': None, 'achieved_s': None}`. |
| 6 | Duplicated operation-block decode | **True** | `io/dop/bdd.py:141-142` (`_OPER_BASE_OFFSET = 548`, `_OPER_BLOCK_BYTES = 1024`) and `acquire/verify.py:7-11` — same table, two readers. |
| 7 | Optional verifier can pass a point | **True** | `runner.py:118-123` defensive import; `runner.py:579-587` sets `PointStatus.OK` with a warning reason. |
| 8 | Size check over-weighted | **True** | `log.py:148-149`: `bytes_per_gate_profile=1.7`, `factor=2.0`. |
| — | No CI | **True** | no `.github/` in the checkout. |
| — | Documentation drift | **True** | `README.md` has no acquisition mention; `architecture.md`'s package map has no `acquire/`; `acquire/__init__.py:3` still says "Four concerns, one module each" while `driver`, `runner`, `campaign`, `live` and `verify` exist. |

### The direction is right

The separation the review argues for — instrument semantics vs. Windows/UI
mechanics vs. experiment specification vs. execution state vs. scientific
verification — is the correct axis, and it matches what this repository already
does elsewhere: `models/` imports nothing from `process/`/`provenance/`/
`storage/`/`io/`; transforms are bundle-closed; specs are discriminated unions.
The review's conclusion that the automation should be **stabilized, not
discarded**, is also correct: the interaction recipes were paid for with live
slots and must move verbatim, not be re-derived.

## 4. Where the review is wrong or over-stated

- **"a requested 1015 second point" does not exist in this repository.** No file
  contains `1015`. The measured case is 12 s requested → ~257 profiles kept
  (~8.4 s), recorded in `campaign.py:576-578` and handoff §4. The number is a
  transcription error; the finding stands without it.
- **Findings 4 and 5 are not new.** The empty timing field is already on the
  record (commit `b2a0d08`, *"the log's timing field is empty"*), and the
  ring/retained-window behaviour is measured and written up in the handoff §4.
  They are known-open items, not discoveries. What is new and worth taking is the
  *remedy*: derive the retained span from the stored profile timestamps instead
  of the theoretical period.
- **Finding 6 is structurally right but under-informed.** `io/dop/bdd.py:73-98`
  already reconciles the two decoders word by word ("**No word decodes
  differently in value**") and lists exactly which words stay undecoded — 14
  (emissions/profile), 27 (sampling volume), 3, 42, 84 — and why. And the fix is
  already on the agenda, under an explicit gate: `docs/agenda.md` §"Visualization
  and acquisition support" asks for word 14 and word 27 to be decoded *"only when
  byte-level evidence, a destination domain field, propagation rules, and storage
  implications are all specified."* The review never mentions that gate; its
  Phase 1 must pass it.
- **The CLI-default claim is misframed.** The values are not buried in `cli.py`:
  they are `live.DEFAULT_MEASUREMENT`, documented at `live.py:45-47` as
  "defaults for an argument, never a fallback the caller cannot see". The
  scientific point (fixed conditions must be confirmed against the instrument)
  stands; the imputation of hiddenness does not.
- **Phases 2 and 5 are partly already built.** `ScreenFingerprint`
  (`actuator.py:306`) and `PreflightReport` (`actuator.py:336`) *are* the
  pre-record snapshot, and `Actuator` + `live.py` already provide the session
  seam. Phase 2 is therefore a binding job, not an invention — and Phase 5's
  "replace the Actuator surface" is a rename across live-proven code, which this
  repository's own rule forbids ("the proven probe script is the spec: port it
  verbatim, and never re-derive a gesture").

## 5. What the review missed

**5a. Master's test gate is red on Windows, and it is a platform defect, not
noise.** `uv run --extra dev pytest -q` on this checkout gives **18 failed, 17
errors, 1510 passed** — all of it in `tests/test_storage_npy.py` plus
`test_io_bdd_artifacts.py::test_canonical_depth_ids_round_trip_through_storage`.
The cause is `storage/npy.py:278`: `_fsync_dir` does
`os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))`, and opening **any**
directory this way raises `PermissionError 13` on Windows (`os.O_DIRECTORY` does
not even exist there — hence the `getattr`). Reproduced on two unrelated
directories, `~/Repos/udv-echo-process` and `%LOCALAPPDATA%\Temp`:

```python
import os
os.open("<any directory>", os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
# PermissionError: [Errno 13] Permission denied
```

The handoff §1 writes these off as "pre-existing failures unrelated to this
work". They are not environmental: on Windows `store_bundle` cannot complete at
all. This matters twice over — the review's Phase 0 premise ("make today's
behavior trustworthy enough to refactor") has this as a hidden prerequisite, and
a Linux CI would pass these tests and *mask* the defect, so CI alone is not the
gate the review thinks it is.

**5b. The dataclass question has a better answer than "document the exception".**
`AGENTS.md` says "Do not add dataclasses"; `acquire/` has four
(`runner.py:195`, `runner.py:220`, `verify.py:123`, `verify.py:143`). But they are
not one category: `PointOutcome`, `VerificationResult` and `WordFacts` cross a
module boundary and land in logs (durable → `ValueModel`), while `_Attempt` is
per-attempt scratch state (ephemeral → a dataclass is the right call, and the
rule should say so).

**5c. Two of the repository's own rules constrain the roadmap.** The
decoded-metadata gate above (§4), and the verbatim-port rule from the
GUI-automation skill that governs `tools/live/` and `acquire/`: a proven gesture
is moved, never re-derived, and a fake written from a spec "encodes your
assumptions as passing tests" — which is exactly why Phase 9 is valuable and why
Phase 3/5 must be mechanical moves.

## 6. Decision, by phase

| Review item | Decision |
|---|---|
| Findings 1–8 | **Accepted.** All verified; the evidence lines are in §3. |
| Phase 0 (correctness baseline, CI) | **Accepted, with the §5a prerequisite added** and the covariate sub-decision sharpened (§7). |
| Phase 1 (canonical operation model) | **Accepted, under the existing decoded-metadata gate** — evidence, destination field, propagation, storage implications first. |
| Phase 2 (request / snapshot / certificate) | **Accepted in reduced form**: `ScreenFingerprint`/`PreflightReport` already exist, so this is binding them into the campaign compile, not a new layer. |
| Phase 3 (split `driver.py`) | **Deferred behind a trigger**: split when a second sweep parameter forces a real edit to the driver, and then as a mechanical move. A 149 kB file whose every gesture was paid for live is not the first thing to touch. |
| Phase 4 (explicit state machine) | **Deferred in code, accepted as documentation + tests** over the existing `StripView`/overlay logic; extract the enum/transitions when Phase 3 opens the file. |
| Phase 5 (instrument/session protocol) | **Modified**: add `InstrumentSession` as a **facade over `Actuator`**, not a replacement of it. |
| Phase 6 (compile against live state) | **Accepted** — this is the real scientific fix; it belongs in the first slice, not after the driver split. |
| Phase 7 (certificate as first-class QC) | **Accepted**, and it is where findings 4 and 5 land, so they become one change. |
| Phase 8 (log/resume) | **Split**: resume fingerprinting accepted; schema versioning deferred until a second consumer exists. |
| Phase 9 (recorded UI snapshots + HIL gate) | **Accepted**, scoped honestly — snapshots pin resolution, never gestures, and do not replace the real-machine acceptance sequence. |
| Phase 10 (docs + contributor rules) | **Accepted**, with §5b as the resolution of the dataclass question. |
| Target package structure | **Accepted as a destination**, with `acquire/udop/` created only when Phase 3 runs. |

## 7. First slice — acquisition correctness baseline

One PR-sized change, no Win32 reorganization:

1. **Forward the channel into verification.** `runner.py:589` →
   `verify_stored_point(path, parameters, self._channel_setting.channel)`, plus a
   **runner-level** channel-2 regression test (the existing channel-2 coverage is
   `verify.py`-level and cannot catch an integration gap).
2. **Make verification mandatory.** Drop the defensive import at
   `runner.py:118-123`; a missing sibling module is a broken install, not a
   verdict. Verification that cannot run means `INVALID`.
3. **Enforce the covariates whose identity is settled.** Read all four words,
   enforce sound speed (19), PRF (5) and burst (8) when the request carries them;
   keep word 14 (emissions/profile) **recorded but unenforced** until the
   committed 52-vs-150 case is explained, and put the discrepancy in the
   certificate either way.
4. **Derive retained time from the file.** Populate `ProfileTiming` and add
   `stored_profile_count` / `stored_time_span_s` / `retained_fraction` /
   `wrapped_block` to the record, read from the stored profile timestamps —
   making the ring-buffer behaviour explicit experimental semantics instead of a
   plan note (`campaign.py:572-588`) and taking the load off `SizeSignature`.
5. **Bring acquired evidence and the live snapshot together.** Carry
   `ScreenFingerprint`/`PreflightReport` into the run record and fail a point
   whose stored words disagree with the snapshot's fixed configuration (Phase 6's
   minimum viable form).
6. **Fix `_fsync_dir` on Windows** (§5a). Independent, five lines, and nothing in
   the artifact-storage path works on this box without it.

## 8. Re-verification recipe

```bash
# the suite, and which failures are real
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests

# finding 1, end to end: a channel-2 point whose words are correct
# (build a two-channel file, then compare the two call shapes)
uv run python - <<'PY'
import struct, sys, tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, "src")
from udv_echo_process.acquire.verify import (
    CHANNEL_1_OFFSET_BYTES, CHANNEL_STRIDE_BYTES, verify_stored_point)

requested = SimpleNamespace(gates=403, resolution_mm=0.243333, first_gate_mm=2.0,
                            sound_speed_ms=1460.0, prf_us=212.0, burst_length=4,
                            emissions_per_profile=150)
buf = bytearray(CHANNEL_1_OFFSET_BYTES + 2 * CHANNEL_STRIDE_BYTES)
for word, value in {2: 100, 5: 212, 8: 4, 10: 1, 13: 403, 14: 150, 19: 1460}.items():
    at = CHANNEL_1_OFFSET_BYTES + CHANNEL_STRIDE_BYTES + word * 4
    buf[at:at + 4] = struct.pack("<I", value)
path = Path(tempfile.gettempdir()) / "channel2_point.BDD"
path.write_bytes(bytes(buf))
print("runner's call shape :", verify_stored_point(path, requested).ok)          # False
print("channel=2           :", verify_stored_point(path, requested, channel=2,
                                                    check_covariates=True).ok)   # True
PY

# finding 5: every record carries the empty timing default
# (reads the local live runs in the gitignored outputs/live/; silent when absent)
uv run python -c "
import glob, json
for path in sorted(glob.glob('**/*.jsonl', recursive=True)):
    for line in open(path, encoding='utf-8'):
        print(path, json.loads(line).get('timing'))
"
```

Measured on 2026-09-18: the runner's call shape returns `ok=False` with three
bogus mismatches (`gates: requested 403, found 0`), while `channel=2,
check_covariates=True` returns `ok=True`. The bug **fails closed** — it
invalidates a correct point (and therefore every point of a channel≠1 run) rather
than admitting a contaminated one, which is why it is urgent but not a
data-integrity emergency.
