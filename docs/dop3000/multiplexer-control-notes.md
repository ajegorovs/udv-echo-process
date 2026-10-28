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

The unchanged original helper is not the accepted candidate. Participant/numeric/first-channel
composition, finite acquisition and live storage acceptance remain open. In particular an offline actor
with a wrong stack contract or widget/Win32-handle confusion is rejected before live use, not excused
by passing tests of its own assumptions. Do not substitute a different control, disable a guard or
relabel a press as native-call acceptance. An executable verified finish/exit remains the enable gate.

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
