# Multiplexer control semantics and the live gate

These are bounded findings for the selected
[finite recording effort](../plans/background-multiplex-recording.md), not a working-control inventory.
The capability register remains [message-route port](../plans/message-route-port.md).

## Distinguish the two channel rows

The Channels surface (caption oracle **UI-MENU-10** in the
[UI index](ui-element-index.md)) has separate selected-channel radios and participation ticks.
Static form nesting, recovered component names, event ownership and the current control geometry
all agree: `Btn_Select_CHn` belongs to the upper radio row; `Btn_Mpx_Channel_Usen` belongs to the
lower participation row. A flat list or a suggestive field name is insufficient to bind either.

Participation handlers are model toggles, not absolute setters: compare the requested participation
with the model before invoking one, invoke once, then read back. Selecting or removing a participant
can also route the current channel and load its parameters. The selected-channel handler can persist
the outgoing configuration. Preserve the complete affected parameter images, not only the visible
frequency or the participation mask, before composing these operations.

## Boolean polarity is control-specific

In the inspected build, the native roll-over handler copies its state byte into model bit 0. The
widget/model association, manual and owner’s operating knowledge identify bit 0 set with finite-stop
rather than roll-over. The earlier claim that a particular executable counter-wrap branch consumed
this bit is withdrawn: follow-up register-flow analysis did not establish it. Model bit 1 is the
software multiplex-mode flag, not an independent measurement of relay motion or finite completion.
A green glyph does not license treating a raw state byte as a Python boolean.
The original private map's opposite polarity and stale-widget explanation were rejected.

The control's state setter and its event notification are separate operations. The setter can call
another virtual method; knowing its field assignment and ABI does not prove it callable in a live
context. A press is a toggle, not an idempotent assignment. An enable command starts the acquisition
path; disable and selected-channel commands have configuration effects and are not harmless cleanup.

The native parameter writer includes the mux word and sequence count. The inspected parameter reader
is asymmetric: its complete instruction listing directly reads the per-channel acquisition amount
but does not directly reload those two fields. Do not infer a reload merely because a stored image
contains them. Native flags and stored-file decoder semantics must be reconciled with discriminating
recordings before changing the BDD reader; no reader or scientific-model change is selected here.

## What the bounded trial established

On 2026-10-27 the disabled-mode flag trial faulted on its **first** logical native operation with a
null-access exception. Completion was unknown; the planned restoration call did not run. Instrumentation
reported hook removal and exited, and independent after-reads matched the original mode, column and all
ten complete parameter images. That establishes an unchanged measured baseline, **not successful native
restoration**. No retry or multiplexed acquisition followed at that pause.

The [derived failure summary](evidence/finite-multiplex-blocked-20261027.json) records the counts,
comparison digests and software gate. It is explicitly not a raw capture: the private observations
contain runtime bindings, and a repository-only reader cannot remeasure those live facts.

The owner renewed bounded live tests on 2026-10-27, with no active multiplexed measurement left behind (relay-wear constraint). Non-rolling operation terminates automatically and successful recordings bring the device out of rolling mode, according to the owner; verify final disabled mode separately rather than inferring it from a file or Ready strip. Prefer short finite non-rolling tests, and establish an executable exit before enable.

The retained-stub candidate subsequently passed the real 32-bit owned-process fixture and the
original instance’s equal-state and flag change-and-restore calls. The latter had four native returns,
forward-state observations, disabled mode throughout the allowed operations, complete snapshot equality
and cleanup. The original probe’s named-event file collision made its aggregate result negative; the
complete send stream retained both operations, so a separate verifier adjudicated that specific report
limitation without altering the raw result or repeating the operation. The
[derived caller evidence](evidence/finite-flag-caller-20261027.json) states the private-capture limits.
Retention is a tested correction; no allocator/GC event was observed to prove the failure mechanism.

The unchanged original helper is not the accepted candidate. The 2026-10-28 measured configuration
transaction and finite-artifact/store-only demonstration below supersede the earlier open-data-path
checkpoint; a promoted one-command workflow and graceful producer shutdown remain open. In particular an offline actor
with a wrong stack contract or widget/Win32-handle confusion is rejected before live use, not excused
by passing tests of its own assumptions. Do not substitute a different control, disable a guard or
relabel a press as native-call acceptance. An executable verified finish/exit remains the enable gate.

## Finite completion can precede an explicit Record command

In the owner-authorized 2026-10-28 manual 1+2 trial, native Run queued command 5 and the
application set an additional **bit 21**. An exact-mode guard rejected that state before its planned
Record branch, but the application had already completed the requested finite block: STORE with two
buttons and a slider. The non-destructive public store-completed tail stored it once. The
[committed BDD and evidence](evidence/finite-multiplex-live-20261028.json) establish two sequential
velocity streams, five profiles × 80 gates each, without a separate Record or Stop from the adapter.
This is a bounded measured configuration, not a universal rule that Run always records.

Observe the actual completed/held state before dispatching Record. A negative post-Run wrapper result
is not proof that acquisition never happened; preserve the original result and adjudicate its complete
stream plus the live state. Never replay acquisition to improve report collation. Default one-command
composition is not credited while its normal entry still refuses that valid application-set state.

The external-trigger control's own handler sets/clears **bit 1 of Trigger_Mode**. The measured word
was **4**, with that enable bit clear; do not require the whole word to be zero or infer external-trigger
absence from the unrelated bit-6 guard. Preserve the complete trigger word.

## Capture all images, but separate settings from proven recording-cache writes

The native parameter writer stores global `Mpx_Mode` in word **52**, sequence count in **53**, and
`Current_Channel` in **83**. The finite recording updated these fields across **all ten** cached images,
including non-participants. All other words and all ten separate TGC tables matched the pre-acquisition
capture. After restoration the global activity flag was clear and the user controls matched their
original values, but the application retained bit 21 and cached-image byte equality was false.

**Owner-selected restoration rule (2026-10-28).** Restore original user/acquisition settings and all ten TGC tables; allow only enumerated runtime cache differences grounded in the native writer and the observed operation. Raw byte equality is not an acceptance requirement. The delivered finite trial satisfies this rule; unknown changes and the older channel-4/channel-10 repair debt remain failures/obligations, not permitted exceptions.

Keep the before/after images, enumerate every changed index, and justify any excluded field through
its actual writer. Do not call an unknown change bookkeeping, do not manufacture raw equality, and do
not silently retire a strict byte-restoration criterion. Configuration-only round trips can still
require full image equality. The application uses a **separate TGC array** with **2048 bytes per
channel**; operation parameters occupy **256 32-bit words per channel**. The copy-from-channel handler
copies the TGC block and calls the parameter reader/writer; equality of two parameter images does not
prove that their TGC blocks are equal or that copy/refresh restores assisted settings unchanged.

Capture TGC before any proposed copy. Validate every planned operation's own class-specific reader
shape before the first mutation: the observer exposes a disabled byte for `TSp_Button`, not for
`TSp_Value_Button`. A green test of participant-only bindings does not preflight a later numeric phase.

**Test the actual observer boundary, not only a port double.** The legacy observer reports a strip view, not measured button/slider structure, and its parameter-column read may be unavailable while a block is held. Fresh native pending/assisted pointers, actual strip/error/overlay reads, ten parameter images and ten TGC tables must be explicit; neither missing data nor a failed fresh read may become a cached clean state. Preserve the complete capture used for admission. A fake carrying invented fields or widget visibility proves neither the real schema nor reachability.

**Cached bindings must not carry dynamic control truth.** The operator sitting stored and closed cleanly, then restoration refused before its first write: the baseline catalog still held repeat-count `int_cache = 10`, while the fresh model was 1. A catalog may retain expected object/class/name/event/owner identity, not current numeric value, state or enabledness. Read each dynamic field from the actual control at the point of use and compare with the fresh model; never assign one from the other merely to satisfy agreement. Refreshing the actual control catalog let the restoration-only tail complete without replaying acquisition.

**A valid producer path is not a complete producer dependency check.** Before setup or Run, resolve the real JavaScript input layout and keep the readiness payload inside the host's strict descriptor schema. The sitting's first two Store starts refused on split source-file lookup and an extra `detach_receipt` field. Fix those producers, not the guards: cleanup evidence belongs in its own receipt, not an undeclared bootstrap field. The same held block was preserved until Store succeeded once.

**Assisted mode and TGC Auto are separate observations.** The operator checked channel 10 with Assisted mode off and TGC Auto selected, matching its saved manual flag and TGC mode 2. Both original and current captures already had Auto selected. The manual §8.11 links automatic TGC to Assisted-mode information, but no transition or cause was traced in this sitting. The owner accepted retained channel-4 Assisted settings and channel-10 Auto/current gain; that closes the old discrepancy by decision, not by restoring historical values.

**First channel is not current channel or combo visibility.** The native `Mpx_Mode` encodes the selected first channel in bits 16–19; its handler replaces that nibble with `ItemIndex + 1`. This is the native control word, not the BDD reader's acquisition-mode enum. The measured first-channel combo is hidden even when its text is `1`; requiring it to be visible rejects the real application. Decode the native field and compare it with the declaration rather than adopting `Current_Channel` or fabricating a visible widget.

Cached image word 53 is a saved copy, **not the live global** `Mpx_Nb_Sequences`. The completed held-block capture states global count **1**, command identifier **0**, current channel **2** and mode **2162739**. Comparing that global count to the one-sequence request is required; a cached copy changing during later restoration does not justify dropping the global guard. `Execution_Code` is one identifier (Run **5**, Record **28**, Off/refresh **2**, idle **0**), never a queue depth or decrementing counter.

## Exit and helper-lifecycle claims have distinct boundaries

The command-2 dispatcher return is not the end of its effect: `GoMesure` uses that return to re-enter
`Update_And_Restart`, whose body initializes/programs the device. The earlier universal claim that Off
has no reachable device exit was false; an interior address was also mistaken for the
`End_And_Close` entry. This source correction is not a measured active-hardware abort. The completed
trial's disabled state was read independently after Store.

The private producer source waits only **3 s** before forcibly terminating its helper, while the helper service owns a **55 s** instrumentation lifetime and the old host grants only **5 s** for producer close. This is a concrete budget mismatch consistent with the observed exit 1 / empty provider envelope, not a retained historical termination receipt. Do not shorten instrumentation to an unmeasured duration merely to make cleanup pass. A candidate preserves 55 s, requests/acknowledges hook cleanup and budgets **6 s** for that receipt plus **59 s** for natural helper exit, inside a **70 s** host close bound. Owned process and mocked-script tests establish that contract, not live instrument cleanup. Public host code now preserves nonzero process exit and channel close failures; activation exposes `session_close_problem` and refuses readiness on failure. The older `session_closed` flag still means called, not clean.

The store host reported its session closed, but its helper exited **1** and no explicit injected-script
detach receipt survived. Keep successful file storage separate from graceful instrumentation shutdown;
the latter is not accepted by this demonstration. Do not infer cleanup from a file or a closed flag.

## Assisted state loads per channel; refresh write-back must be accounted for

`Read_Para_Fct` loads the selected image’s **word 1**, compares it with zero and stores that byte
through the slot resolving to `@Udop_data@Assisted_Mode`. It is therefore a per-image flag,
not a global setting. The inspected images store 1 for channels 4–9 and 0 for 1, 2, 3 and 10.

The primary refresh body calls `Compute_Para` and later `Write_Para_Fct_And_Tgc`; the dispatcher’s
command-2 branch returns 2 rather than calling the writer directly. Assisted recomputation and refresh
write-back explain the observed channel-4 changes (PRF 200 / gates 100 / emissions 100 to 169 / 378 /
150), but the full executed call chain was not captured: this remains a source-supported causal
inference, not a traced effect. Channel 10’s changed word 93 is overall gain; its exact writer was not
traced either. Capture complete images before any routing action, avoid assisted channels in the first
finite trial, and never infer image preservation from mask equality or an available parameter column.

The selected-channel row is a standing hazard for the same reason — its handler saves the outgoing
channel before switching — so returning the current channel must avoid that handler. Restoring
`Current_Channel` to its original value through the display-selection call and the Off handler was
measured to leave all ten images byte-identical.

## Participation is not a mask-only operation

The later worker continuation’s participation/restore trial returned the membership mask but not the
whole configuration: current channel remained 10 instead of 1, channel 4’s saved acoustic settings
changed, and channel 10’s overall-gain word changed. Routing was subsequently restored through the
reviewed display-selection/Off candidate without changing any of the ten images; the acoustic/gain
restoration debt remains open in the selected plan.
Do not count mask equality, an available parameter column or `result.ok` as restored channel images.
Resolve the pending-command storage through its actual live pointer, not an assumed address. A failed
fresh observation must refuse, not fall back to an older baseline to admit a live mutation.

## Numeric control contract and bounded live proof

`TSp_Value_Button.SetBtn_Value(double)` takes an eight-byte stack argument and returns with stack
cleanup; it validates/clamps, updates the numeric caches and invalidates the control. It does not
notify the value event. `NewValue()` takes only Self and returns without a stack argument; it invokes
the value control’s own callback with its stored owner and Sender. Do not pass the double to both or
invoke the form callback a second time. Value and state controls have different event-record layouts.
The selected actor must verify the model’s sequence count, not merely the numeric cache.

A private candidate subsequently demonstrated 10→1→10 in both the control and global sequence count.
The exact-text first-channel candidate demonstrated 1→4→1 in the combo and model. Both restored all ten
complete channel images and the complete captured snapshot, with disabled mode, Ready, hook removal and
instrumenter exit separately checked. The [derived configuration evidence](evidence/finite-config-controls-20261027.json)
contains the bounded checks; this does not credit a generic actor, participant transaction or recording.
