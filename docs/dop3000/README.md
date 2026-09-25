# DOP3000 / DOP3010 device notes

Device-specific documentation for the **Signal Processing S.A. DOP3000/DOP3010**
ultrasonic Doppler velocimeters — the instruments that produce the `.ADD`/`.BDD`
recordings this repo parses.

## Contents

| File | What it is |
|------|------------|
| [`measurements-and-recordings.md`](measurements-and-recordings.md) | Explainer: how a DOP measures (basic physics), what a single-sensor recording contains (burst, emission, gate, profile, …), and how multiplexed recordings are organised (channels, sequences, blocks, TBD/block/channel columns). |
| [`parameter-sweep-matrix.md`](parameter-sweep-matrix.md) | Planning note for a sensitivity campaign: the 15 settable UDOP parameters, their governing relations (reach/velocity limits, gate geometry, timing), which are genuinely independent axes, which must be co-set, and which must never be swept. |
| [`manual-reference/`](manual-reference/) | Text-only, page-traceable transcription of the DOP3000/3010 User's Manual (software 6.6, revision 1), split into its front matter, 22 chapters, and index. |

### Driving the instrument (`acquire/`, `tools/live/`)

Read the first three rows before acting on anything in the rows below them: they are the
frozen authority for **architecture**, for **surfaces and bindings**, and for the
**verification procedure**. The other documents are the mechanism, the state of the work,
the bring-up path, the decision record, the caption oracle and the history.

| File | What it is |
|------|------------|
| [`acquisition-architecture.md`](acquisition-architecture.md) | **The architecture and its invariants.** The three evidence levels used across this set, the `OBSERVE → INTERPRET → ACT` layering, the module layout as measured at the freeze commit, the target layout with a *status: target / landed by patch N* marker per module, the phase plan, the invariants the refactor may not reinterpret, and the boundary of what a cloud-only refactor may claim. |
| [`acquisition-ui-model.md`](acquisition-ui-model.md) | **Surfaces, widgets, bindings, known unknowns.** The `MEASUREMENT / OVERLAY / REPLACEMENT / UNKNOWN` taxonomy, the measurement-screen predicate, every cropped surface with its crop id, the strip's views (including the unresolved four-button state), the widget and binding rules, the blind-spot ledger (B01..B20) with the status that may be asserted before the next device session, and how to read the crop oracle. |
| [`device-verification.md`](device-verification.md) | **The device verification procedure** for the refactor: preconditions, V0..V8 with pass criteria, the item → risk → committed-evidence map, the stop condition, and the promotion rules that move an item out of *device-pending*. |
| [`acquisition-closeout-plan.md`](acquisition-closeout-plan.md) | **The next work, and the order it is run in**: how the open stack lands (`#9` → `#8` → `#10`), the four device sittings that close the refactor's remaining items, and the one operator question that unblocks the matrix. Sequences the checklist above; does not restate it. |
| [`udop-automation.md`](udop-automation.md) | **The mechanism**: how a sweep point is set, recorded, stored and validated with nobody at the console — the write recipes that commit, the order they must be written in, the strip's state machine, the store chain, and the failure modes that silently invalidate a point. |
| [`handoff-dop3010-acquisition.md`](handoff-dop3010-acquisition.md) | **State of the work** for a fresh session: what is proven, what is broken, what to do next, and the rules that were expensive to learn. |
| [`live-bringup.md`](live-bringup.md) | Proving the controls work on a machine that has **only this repository** — the staged bring-up with pass criteria, and what to declare open. |
| [`acquisition-review-and-verdict.md`](acquisition-review-and-verdict.md) | An external review of the acquisition subsystem, every finding verified with `file:line` evidence, where the review was over-stated or wrong, the per-phase decision, and the landed first slice. **The work list.** |
| [`acquisition-campaign-compilation-plan.md`](acquisition-campaign-compilation-plan.md) | **Historical record** since the 2026-09-18 freeze: the campaign plan and its running chronology (§11.1 the live checkpoint as of that date, §26 the live findings that produced the layout gate). Retained for its evidence and its reasoning; not the current authority for architecture, surfaces or verification. |
| [`ui-element-index.md`](ui-element-index.md) + [`ui-crops/`](ui-crops/) | The 45 hand-cut UI crops and their row-per-crop index — **the only oracle for the application's painted captions**. Checked by `tools/ui/crop_index.py`, read with `tools/ui/magnify.py` (see `tools/ui/README.md`). |
| [`recon-archive-retirement.md`](recon-archive-retirement.md) | Where the reconnaissance archive (`dop-control`) went, what was lifted into this repository, what was never ported, how to read a `recon/NN` citation now, and the Store directory that moved with it. |

## One authoritative copy per fact

A fact lives in exactly one of these documents; the others link to it. Where a pointer
header at the top of a document names a new authority, that header is binding and the body
below it is retained as evidence, mechanism or history — not as a second source of the same
claim.

| fact | authority |
|---|---|
| architecture, layering, invariants, patch/phase order, evidence levels | [`acquisition-architecture.md`](acquisition-architecture.md) |
| surfaces, widgets, bindings, strip views, blind spots (B01..B20) | [`acquisition-ui-model.md`](acquisition-ui-model.md) |
| the device verification procedure | [`device-verification.md`](device-verification.md) |
| the next work and the order it is run in | [`acquisition-closeout-plan.md`](acquisition-closeout-plan.md) |
| write recipes, write order, strip state machine, store chain, failure modes | [`udop-automation.md`](udop-automation.md) |
| painted captions and values, and the state a crop was taken in | [`ui-element-index.md`](ui-element-index.md) + [`ui-crops/`](ui-crops/) |
| the actionable backlog and per-phase decisions | [`acquisition-review-and-verdict.md`](acquisition-review-and-verdict.md) |
| the campaign plan's reasoning and its live chronology | [`acquisition-campaign-compilation-plan.md`](acquisition-campaign-compilation-plan.md) (historical) |
| durable provenance for an instrument mutation in a refused invocation | [`failed-invocation-provenance.md`](failed-invocation-provenance.md) |
| the DOP3010 agent skill (`SKILL.md` + `references/`) | [`.agents/skills/udop-acquisition/`](../../.agents/skills/udop-acquisition/) |

## Manual reference

The reference corpus is the current enriched OCR transcription. Its Markdown
retains source-PDF page markers, checked equations, fixed-width representations
for complex tables, and clearly labeled editorial figure captions/context. Page
facsimiles and extracted figures are intentionally omitted so the corpus stays
text-only.

Related: `.BDD` binary-format reader notes live at
[`../doppy-analysis.md`](../doppy-analysis.md).

## Source / licensing

The source is the *DOP3000/3010 Users Manual* (software v6.6, manual v6.6.1,
Signal Processing S.A.). The source PDF and its images are not committed here;
the text-only transcription is retained for this project's technical reference.
Always re-check instrument-specific numbers against the manual or the `.BDD`
metadata for your exact device/software version.
