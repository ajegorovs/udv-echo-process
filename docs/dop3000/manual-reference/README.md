# DOP3000/3010 Users Manual — extracted reference text (UNPROOFREAD)

Reference copy of the machine-extracted text of the *DOP3000/3010 Users Manual*
(software v6.6, manual v6.6.1, Signal Processing S.A.), persisted here so the
DOP device docs have *some* quotable source material.

> **⚠️ Status: raw machine extraction — NOT proofread.**
> This text came straight out of two PDF-extraction pipelines and was never
> given a systematic fix pass. Prose is generally reliable; **formulas
> (ch 14/16), spec tables (ch 10/21/22) and page furniture are damaged**.
> Treat it as a searchable reference + quotation source, cross-check anything
> numeric against the manual PDF or `.BDD` metadata before relying on it.
> Full quality audit (incl. why the Neo4j stage did not fix the text):
> [`EXTRACTION-QUALITY-AUDIT.md`](EXTRACTION-QUALITY-AUDIT.md).

## Layout

```
manual-reference/
├── README.md                       ← this file
├── mineru-chapters-split/          ← canonical base: MinerU 2.5-Pro extraction,
│   │                                 split into 24 standalone chapter files
│   │                                 (ch 01–22 + 10b + INDEX_MINERU_SPLIT.md)
│   └── 01-…22-*.md
└── chapters-extra/                 ← 2 files from the older PyMuPDF-style
    │                                 extraction, kept because they contain text
    │                                 the MinerU copy lost:
    ├── 10-storing-and-reading-measures.md   (ASCII file-format examples,
    │                                          "TBD [ms] No block Channel" figures)
    └── 20-ultrasonic-data.md                 (merged ch 20–22 spec rows, cleaner
                                               table rendering than mineru HTML)
```

## Provenance & why two corpora

| Corpus | Origin | When | Notes |
|--------|--------|------|-------|
| `mineru-chapters-split/` | MinerU 2.5-Pro (llama.cpp) | 2026-07-16 | Better formulas (LaTeX), structure, tables. **Base of record.** Lost some ASCII examples (ch 10) and truncates long spec-table lines (ch 22). |
| `chapters-extra/` | PyMuPDF-style extraction | 2026-07-16 | Flatter text; every chapter file ends with the next chapter's running header (boundary bleed). Kept only for the 2 files that add content MinerU dropped. |

Both extractions were produced the same day and never edited afterwards;
identical garbles in both indicate damage that lives in the source PDF's text
layer, not a one-off OCR slip.

## What is usable, chapter by chapter

| Chapters | Use for | Watch out for |
|----------|---------|---------------|
| 1, 2, 14–16, 18 (physics, theory) | measurement principle, PRF limits, Doppler equation, sample volume | ch 14 spectral equations and ch 16 estimator equations are mangled in **both** corpora → reconstruct, do not quote verbatim |
| 4, 5, 6, 8, 9 (operation, profiles, filters, parameters) | burst, gates, emissions/profile, time-between-profiles, aliasing | good prose; occasional OCR word splits ("t / he", Greek-letter "where") |
| 10, 10b (storage, file formats) | `.ADD`/`.BDD`/`_stat` layout, block/sequence semantics | mineru copy lost the ASCII examples → see `chapters-extra/10…` |
| 11, 12, 13, 22 (multiplexer, 2D/3D, DOP3010) | channels, per-channel params, block=sequence | manual body often writes "DOP3000" for DOP3010 features; number conflicts kept (switch time 0.5 vs 0.1 ms) |
| 17, 19, 20, 21 (transducers, refs, ultrasonic data, specs) | material sound speeds; DOP3000 specs | 21's mineru tables are one-line HTML cells → prefer `chapters-extra/20…` for the merged spec rows |

Known manual-internal oddities preserved in the text (not extraction errors):
"Corse" (Coarse), "bi -directionnal", "235 x 98 x 347 cm" (units), "109 cycles"
(lost superscript — 10⁹), duplicated "its own its own".

## Licensing note

The manual is a copyrighted vendor document (Signal Processing S.A.). This
folder exists as a private working reference; confirm you are entitled to keep
and (if ever) publish it before committing to the public repo. If in doubt,
keep `manual-reference/` out of git (`git rm --cached -r docs/dop3000/manual-reference`)
and rely on the distilled explainer in
[`../measurements-and-recordings.md`](../measurements-and-recordings.md).
