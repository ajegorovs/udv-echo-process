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
finite-sequence branch tests that bit when the next channel wraps to the first and the programmed
sequence count has been reached: **bit 0 set requests Stop**, not roll-over. Model bit 1 is the
multiplexer-active flag. A green glyph does not license treating a raw state byte as a Python boolean.
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
restoration**. No retry or multiplexed acquisition followed.

The [derived failure summary](evidence/finite-multiplex-blocked-20261027.json) records the counts,
comparison digests and software gate. It is explicitly not a raw capture: the private observations
contain runtime bindings, and a repository-only reader cannot remeasure those live facts.

Further target mutation is paused. Reproduce and diagnose the exact calling adapter on a source-owned
fixture, review its failure/cleanup behavior, and obtain the owner's resume decision before another
live trial. Do not substitute a different control, disable a guard or relabel a press as native-call
acceptance to cross this gate.
