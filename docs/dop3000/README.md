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

| File | What it is |
|------|------------|
| [`udop-automation.md`](udop-automation.md) | **The mechanism**: how a sweep point is set, recorded, stored and validated with nobody at the console — the write recipes that commit, the order they must be written in, the strip's state machine, the store chain, and the failure modes that silently invalidate a point. |
| [`handoff-dop3010-acquisition.md`](handoff-dop3010-acquisition.md) | **State of the work** for a fresh session: what is proven, what is broken, what to do next, and the rules that were expensive to learn. |
| [`live-bringup.md`](live-bringup.md) | Proving the controls work on a machine that has **only this repository** — the staged bring-up with pass criteria, and what to declare open. |
| [`acquisition-review-and-verdict.md`](acquisition-review-and-verdict.md) | An external review of the acquisition subsystem, every finding verified with `file:line` evidence, where the review was over-stated or wrong, the per-phase decision, and the landed first slice. **The work list.** |
| [`acquisition-campaign-compilation-plan.md`](acquisition-campaign-compilation-plan.md) | The campaign plan and its running record (large; §11.1 is the live checkpoint, §26 the live findings). |
| [`ui-element-index.md`](ui-element-index.md) + [`ui-crops/`](ui-crops/) | The 45 hand-cut UI crops and their row-per-crop index — **the only oracle for the application's painted captions**. Checked by `tools/ui/crop_index.py`, read with `tools/ui/magnify.py` (see `tools/ui/README.md`). |
| [`recon-archive-retirement.md`](recon-archive-retirement.md) | Where the reconnaissance archive (`dop-control`) went, what was lifted into this repository, what was never ported, how to read a `recon/NN` citation now, and the Store directory that moved with it. |

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
