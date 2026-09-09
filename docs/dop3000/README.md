# DOP3000 / DOP3010 device notes

Device-specific documentation for the **Signal Processing S.A. DOP3000/DOP3010**
ultrasonic Doppler velocimeters — the instruments that produce the `.ADD`/`.BDD`
recordings this repo parses.

## Contents

| File | What it is |
|------|------------|
| [`measurements-and-recordings.md`](measurements-and-recordings.md) | Explainer: how a DOP measures (basic physics), what a single-sensor recording contains (burst, emission, gate, profile, …), and how multiplexed recordings are organised (channels, sequences, blocks, TBD/block/channel columns). |
| [`manual-reference/`](manual-reference/) | **Unproofread** machine-extracted text of the DOP3000/3010 Users Manual v6.6.1 (24 MinerU chapter files + 2 extra files) — raw reference corpus with provenance notes and per-chapter caveats. |

## Manual reference status

The manual chapter text is **not** yet through a fix/proofread pass: two machine
extractions exist (MinerU + an older one), produced 2026-07-16 and untouched
since; both still carry page-furniture leaks, formula damage (ch 14/16) and
table artifacts. The Neo4j graph work (kept elsewhere) cleaned graph structure,
**not** the manual text. See `manual-reference/README.md` for what is safe to
quote. A curated, cleaned copy may replace the raw corpus chapter by chapter
when the pass is done.

Related: `.BDD` binary-format reader notes live at
[`../doppy-analysis.md`](../doppy-analysis.md).

## Source / licensing

Facts below are distilled from the *DOP3000/3010 Users Manual* (software v6.6,
manual v6.6.1, Signal Processing S.A.). The manual itself (PDF) is not
committed here; only short paraphrases and definitions are reproduced. Always
re-check instrument-specific numbers against the manual or the `.BDD` metadata
for your exact device/software version.
