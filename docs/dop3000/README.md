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
