# Finite background multiplexed recording

**Task plan.** Written 2026-10-27. **State:** blocked.

**Live-mutation lock:** the first native flag operation faulted; do not retry, prime or enable. Baseline readbacks match. The offline continuation and owner-resume boundary are below.

## Destination

**Purpose.** Make the existing background recorder useful for a finite two-channel multiplexed acquisition. This bounded effort owns execution; the [message-route port](message-route-port.md) remains the capability register and historical evidence source.

**Observable outcome / acceptance criteria.**

1. Capture the current target identity, selected channel, multiplexer state and every setting to be changed before mutation. Preserve existing channel configurations, including any retained 10 MHz setup; prefer an already compatible same-frequency pair over rewriting frequencies.
2. Reusable controls can read/select participants, first channel, per-channel acquisition amount, sequence count, roll-over and enable/disable. Each write has an observed effect on the original instance; no guessed control, unchecked toggle or assumed state.
3. Execute one finite two-channel sequence with roll-over off and no external-trigger dependency, with per-channel dwell respecting the manual's 100 ms minimum recommendation. Establish enable/start/completion semantics before composition; enabling must not unexpectedly start an unbounded acquisition.
4. Store a uniquely named file while another application can remain foreground, decode the complete requested channel/quantity set and compare each participant's configuration and profile counts with the request. Do not invent visit identities the format does not prove.
5. Restore and read back the original selected channel, mode and every changed setting, with no popup, active sequence or unaccounted held block left behind. Preserve any acquisition already present when the sitting begins.
6. Focused offline tests, independent review and the coordinator's acquisition/bridge gate back the implementation. Portable evidence records the actual request, artifact identity, observed outcome and restoration; sensorless automation evidence is not a flow measurement.

**Non-goals.** Mixed-frequency enablement or bypassing compatibility checks; external triggering; continuous/roll-over acquisition; a general campaign framework; full application reconstruction; generic bridge hardening; changes to scientific models or synchronization semantics.

**Authorization boundaries.** Owner selected this work with “Plan and drive the work” on 2026-10-27. The 2026-10-26 grant permits bounded unattended live integration, local adapter/binding updates, reversible setup changes with verified restoration and unique test recordings. No application restart, overwrite of existing recordings, validation bypass, secrets changes or push. Local commits remain authorized. The coordinator alone owns live application access; workers are offline unless given an explicit narrower live task. Permission does not supply a missing restoration primitive: no enable until an executable safe exit is established.

**Baseline.** Git `0edcc03`, branch `feat/application-backed-bridge`; only unrelated untracked `.worktrees/` present at entry. Prior regular recording: two instrument-mode guarded CLI points stored and decoded on 2026-10-26. Their per-instance binding is historical, not current authorization. The owner's last physical setup report was all transducers disconnected; do not infer present or historical signal validity from it. That entry checkpoint had no fresh live observation; the measured state and mutation lock are recorded below.

## Patterns this work follows

Repository `AGENTS.md`, the selected P1 records convention and [plan template](TEMPLATE.md); the repository-owned acquisition skill; [multiplexer manual](../dop3000/manual-reference/11-using-the-multiplexer.md); [UI-MENU-10](../dop3000/ui-element-index.md); existing backend/CLI layering. No tracker migration is selected. Machine bindings and raw live reports stay local; reusable semantics and checkable evidence have a portable home.

## Current checkpoint

**Established.** Fresh read-only inspection on 2026-10-27 found the same build/process instance, instrument-mode Ready, no error/overlay or held block, selected channel 1 and multiplexing disabled. The Channels menu opened and closed through the existing native menu route with settings, identity and cursor/clip unchanged. Its visible baseline is participants 1/2/10, first channel 1, repeat count 10, roll-over marked on and current-channel amount 5 profiles / displayed 0.20 s. Passive reads retained all ten complete parameter images; channels 4 and 5 are identical across all 256 words, including 4 MHz and 100 profiles per visit. They are the candidate pair, not yet an acquisition result.

**Implementation versus verification.** The non-destructive store-completed entry point and closed store-only host sequence are implemented and tested offline. Static activation failures now block producer creation, wrong-entry refusals get fresh reports, and both cycle entries reject escaping/invalid filename stems before path lookup or dispatch. The coordinator’s acquisition/bridge gate ran 1,541 tests: 1,536 passed, five failed with exactly the prior baseline IDs. Scoped Ruff and whitespace checks passed. Independent final review approved the offline storage-only scope; synthetic bindings/row fixtures do not prove a live producer or dialog transition. Earlier press-route row evidence is not acceptance of this new store-only route. No live store-only acceptance occurred.

**Established control semantics.** Independent form/instruction review plus recovered component names, event ownership and actual geometry corrected the initial row attribution and polarity. The upper radios select the current channel; lower ticks control participation. The finite-completion branch uses model bit 0 set to request Stop at the last sequence wrap; it is not a roll-over-enabled bit. [Durable control notes](../dop3000/multiplexer-control-notes.md) own these semantics and the limits of the static evidence.

**Blocking live result (2026-10-27).** One disabled-mode flag round trip was attempted, not an acquisition. The first logical native operation reported an access violation at null; completion was unknown and the planned restoration call never ran. Hook removal and instrumentation exit were observed. After-reads matched the original mode, column, identity and all ten complete parameter images; Ready and no application error/overlay were observed. Baseline equality is not successful restoration. No retry, enable, channel selection, recording or Store followed. The [derived failure summary](../dop3000/evidence/finite-multiplex-blocked-20261027.json) separates planned, attempted and confirmed counts and explains the limits of the private raw captures.

**Not established.** A callable native flag setter in this context, the fault’s root cause, safe enable/disable/restoration, finite lifecycle, assembled background multiplexed recording and live store-only operation. A statically plausible setter is not a working control. Full compatibility logic and any frequency restriction remain unestablished.

**Relevant revision / artifacts / live target.** Code checkpoint `4093bba` (baseline `0edcc03`); code and records remain local until separately authorized for publication. Private observations include the failed invocation’s executed source, binding, trace, sampler and complete before/after parameter images. Public evidence is explicitly derived, not a fabricated raw capture. The binding was revalidated on the same process, not proved across a restart.

**Working state / recovery needs.** **Target mutation is paused; no automatic retry or priming.** The measured configuration matches baseline, with no configured-setting restoration owed by those readbacks; the native invocation nevertheless remains unsuccessful/unknown. Preserve `.worktrees/` and all failed-run evidence. Do not attach simply to manufacture a newer final-status reading. Resume needs the owner’s decision after the calling-adapter failure is understood and the exact path is reviewed.

## Remaining work

**Selected next (offline).** Reproduce/diagnose the exact native calling adapter on a source-owned fixture; distinguish its ABI/lifetime/context behavior from the vendor setter’s body, and review failure/cleanup before proposing a new bounded live trial. This serves the original finite-recording objective, not a new orchestration or hardening framework. The matched pair needs no acoustic-parameter copying. The live acceptance and all requested controls remain incomplete.

**Blocked.** Any further live control trial, enable/disable and the finite recording. Missing capability: a state-setting call that demonstrably completes and has an executable verified exit/restoration path. The storage-only backend does not provide that missing control. Do not substitute a guessed press, remove validation, reinterpret the fault as a harmless refusal or silently downgrade the route.

**Unselected findings / open questions.** Exact sampling-volume comparison and mixed 4 MHz/10 MHz admissibility; batch operation; repeated multiplexed sequences; the conflict between the native low-bit meanings and the BDD reader/manual labels (needs discriminating decoded evidence before a reader change).

**Tooling scope finding (unselected).** Worker-end skill reviews updated profile skills outside their dispatched file ownership despite explicit restrictions. The coordinator corrected misleading stale-widget/static-proof claims; a broader audit is not established. No agent configuration was changed. Diagnosing or changing that updater is a separate owner decision, not permission to expand this instrument task.

**Deferred or excluded.** Full control mapping and reconstruction follow useful recording capabilities, not this slice. The existing five session-0/fake-driver test failures remain an attributed baseline, not selected cleanup.

## Decisions and evidence

- 2026-10-27: owner selected planning and execution after the finite two-channel proposal. Same-frequency first; mixed-frequency work remains lower priority.
- Manual: configure participating channels before enabling; parameters cannot be changed while multiplexing is enabled; roll-over replaces earlier data. Enable, Record, completion and Store are distinct facts to establish, not interchangeable labels.
- Correction carried forward: previous prose saying the multiplexer never checks frequency or cannot reflect a hardware constraint was unsupported by the string-reference analysis. Neither claim is a design premise.

## Next session

**Objective (agreed).** Deliver the finite same-frequency two-channel workflow without adding unrelated infrastructure.

**First action (proposed offline continuation).** Read this lock, the control notes and failed-run evidence; reconcile Git, then build the source-owned calling-adapter reproduction. Do not start with a live status/attachment, and never replay a held recording merely because software expects READY.

**Stopping condition.** The present pause is the concrete native-call blocker, not a completed acquisition. Offline continuation stops at a reproducible diagnosis and reviewed candidate, or a named limitation; the owner decides whether to resume live work. Eventual completion still requires the verified two-channel file plus verified restoration.
