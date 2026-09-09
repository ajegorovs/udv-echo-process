# Assessment — progress on "fixing manual extraction mistakes" (stage 2)

> **Note on provenance (2026-09-09):** this audit was written while the full
> extraction project (both corpora, the original PDF, `archive/`,
> `CHAPTER-EXTRACTIONS/`, `neo4j-backup/`) lived in a *temporary* folder that
> has since been removed. Path references below refer to that original layout.
> Of it, the retained subset is: **`mineru-chapters-split/`** (same folder name
> here) and **`chapters-extra/`** (the two fallback files kept from the old
> `source/chapters/` corpus). The rest (`archive/`, `CHAPTER-EXTRACTIONS/`,
> `neo4j-backup/`, the PDF) is no longer stored with this repo — see
> [`README.md`](README.md) for the condensed, current version of these findings.

**Date:** 2026-09-09 (audit of the manual-extraction project snapshot)
**Scope:** pipeline stage 2 — *"a pass over the OCR output to fix mistakes and augment data"*;
plus (per follow-up request, §6) a check of whether the Neo4j stage did any text cleaning.
**Out of scope:** stage 1 (OCR/extraction itself) and stage 3 (chunking, embeddings into Neo4j, relationship building) — the latter only insofar as §6 audits it for text cleaning.
**Method:** audit of folder artifacts (docs, file mtimes, corpus diffs, Neo4j store probing) + content verification runs over the chapter text (three independent read-only passes on the physics, burst/profile and multiplexer/storage chapters, cross-checked between the two corpora).

---

## 1. What the folder contains (stage-1/2 artifacts only)

| Artifact | mtime | What it is | Role |
|----------|-------|-----------|------|
| `source/dop3000-users-manual-v6-6-1.pdf` | – | Original manual (130 pp.) | ground truth |
| `source/chapters/` — 19 `.md` | 2026-07-16 13:11–13:12 | PyMuPDF-style text extraction, one file per chapter **as merged by the extractor** | stage-1 output (A) |
| `source/mineru-chapters-split/` — 24 `.md` (ch 01–22 + 10b + `INDEX_MINERU_SPLIT.md`) | 2026-07-16 15:24–16:24 | MinerU 2.5-Pro extraction, re-split into standalone chapter files | stage-1 output (B), **partially restructured** |
| `archive/planning/INDEX.md`, `INDEX_MINERU.md`, `MINERU_COMPARISON.md`, `NEO4J-GRAPHRAG-GAP-ANALYSIS.md`, etc. | 2026-07-16 | Mapping/index/benchmark docs for both corpora | provenance |
| `CHAPTER-EXTRACTIONS/` (ch 04, 05, 08 templates) | 2026-07-24 | Entity/relationship **extraction templates for stage 3**, not fixed text | not stage 2 |
| Everything else (JOURNAL, audits, bug reports, tooling under `archive/`) | 2026-07-19 → 07-29 | Graph build / Neo4j embedding effort | stage 3 |

There is **no folder, file set, log, or doc dedicated to a text-level fix/proofread pass** in this snapshot, and **no chapter `.md` has an mtime after 2026-07-16** — i.e. the corpus in this folder was never touched again after both extractions were produced.

## 2. What stage-2-like work *was* done (structural only)

1. **Standalone chapters recovered.** The first extraction merged chapters
   12/13 into `11-using-the-multiplexer.md` and 21/22 into `20-ultrasonic-data.md`
   (flagged as CRITICAL issues in the older extraction review, "missing
   standalone chapters"). The MinerU corpus was re-split into one file per
   chapter — 12, 13, 21, 22 (and 10b) now exist separately
   (`source/mineru-chapters-split/`), with `INDEX_MINERU_SPLIT.md` describing
   the split. A content check confirms the split did **not** lose chapter-11
   multiplexer text (the old merged file only *additionally* contains ch 12/13,
   which now live in their own files).
2. **Engine selection / benchmark.** `archive/planning/MINERU_COMPARISON.md`
   documents why MinerU output was preferred (formulas, tables, structure) and
   it became the corpus of record for chapters 12–22.
3. **Index.** A split index was written.

That is the entire documented "fixing" effort for the corpus: **restructuring
and corpus choice, done 2026-07-16, ~1–3 h after the raw extraction.** No
further corpus work appears anywhere in the later journal/audit trail, which is
entirely about stage-3 graph mistakes.

## 3. What stage 2 did *not* do (text-level mistakes remain)

Evidence collected in this audit:

| Mistake class | Status in `source/chapters/` | Status in `source/mineru-chapters-split/` |
|---|---|---|
| **Chapter-boundary bleed** (next chapter's header at EOF; old review CRITICAL) | ❌ still present — every file ends with the next chapter's running header + "Signal Processing S.A. … user's manual" | ⚠️ different form: running titles & page marks ("8 - 1", "Signal Processing S.A. …") inline in body (12 occurrences in ch 08 alone) |
| **OCR/text garble** (tokenised words, Greek-letter OCR of "where", "t / he" line splits, "cste") | ❌ present | ❌ present (often byte-identical to the other corpus) |
| **Formula damage** (ch 14 spectra, ch 16 estimator, stray `\|`, bold-COS/greek-ν, dropped indices) | ❌ equations mostly token soup | ⚠️ better (LaTeX) but ch 14/16 equations still mangled **in both corpora identically** → damage predates both extractions (PDF text layer / scan) |
| **Spec-table integrity** (ch 21/22 + ch 10 tables) | ⚠️ flattened rows, captions reordered/duplicated ("Table 2/3", body text interleaved in cells) | ⚠️ one-line HTML cells, some **truncated at the 2000-char line cap** (ch 22 spec ends mid-cell "Configuration parame…") |
| **Known numeric conflicts** (switching time 0.5 vs 0.1 ms; memory 32 000 vs 64 000 vs 2 097 152 profiles; "235 x 98 x 347 cm" units; "109 cycles" lost superscript) | ❌ kept as-is | ❌ kept as-is (these look like manual-internal errors, but nothing was reconciled) |
| **Typo repair** ("recommeded", "Standart deviation", "its own its own", "Corse", "bi -directionnal") | ❌ | ❌ |
| **Index accuracy** | — | ⚠️ `INDEX_MINERU_SPLIT.md` page ranges internally inconsistent (ch 10 & 11 both "81–86"; ch 19 "129–130" vs real 115–116) |
| **"Augment data"** (enrichment: annotations, links, verified values, added structure) | none | none at text level (augmentation exists only as stage-3 graph templates in `CHAPTER-EXTRACTIONS/`) |

**Conclusion on stage 2:** in this snapshot the *text-level* "fix mistakes and
augment" pass is essentially **not started** — roughly **5–10 % done** if we
count the structural split + corpus choice, and **0 %** of the proofreading/
repair work (garble, formulas, tables, page furniture, numeric reconciliation,
augmentation) is done or even logged as a plan.

## 4. How good is the corpus *as a source* anyway (for the new explainer doc)

Per-chapter reliability after three independent verification passes
(cross-corpus + cross-checked against physics/domain knowledge):

| Chapter cluster | Verdict for prose | Verdict for numbers | Verdict for formulas/tables |
|---|---|---|---|
| 1, 2, 14, 15, 16, 18 (physics/architecture) | ✅ reliable, near-identical in both corpora | ✅ Doppler eq, v_max, d_max, PRF trade-offs mutually consistent | ⚠️ ch 14 spectra & ch 16 estimator mangled in both corpora → reconstruct, don't quote |
| 5, 6, 8, 9 (profiles, filters, parameters, aliasing) | ✅ reliable | ✅ all checked numbers agree across corpora (burst 2–32 cycles, gates 4–1000, emissions/profile 1024–8, N_Stb=16, sample-volume mm list) | ⚠️ minor (line-wrap splits, HTML cells) |
| 10, 10b (data storage, file ops) | ✅ reliable | ✅ .ADD/.BDD/_stat semantics consistent; TBD never expanded in manual | ⚠️ ch 10 ASCII examples present only in the old corpus (MinerU dropped them); old-corpus tables messy |
| 11, 12, 13, 22 (multiplexer, 2D/3D, DOP3010) | ✅ reliable (ch 11 split clean) | ⚠️ manual-internal conflicts kept (switching time, memory limits); DOP3000 vs DOP3010 naming mixed | ⚠️ ch 22 spec table truncated in MinerU; readable rows only in old corpus |
| 21 (DOP3000 specs) | ✅ | ✅ (cross-checked) | ⚠️ one-line HTML cells, run-together words |
| 19 (references) | — | — | — |

Prose-level facts used for documentation are trustworthy; **do not quote
formula-heavy passages from ch 14/16 or single spec-table cells** without
reconstructing them first.

## 5. Recommendation (for the "migrate fixed OCR into docs" plan)

1. **Do not migrate the corpora as-is.** Neither corpus is stage-2 finished;
   both carry page furniture, table/formula damage and un-reconciled numbers.
2. **Prefer `source/mineru-chapters-split/` as the base** whenever prose/LaTeX
   is needed, and fall back to `source/chapters/` for (a) ASCII example figures
   dropped by MinerU (ch 10) and (b) spec-table rows truncated in MinerU
   (ch 22) — then re-verify numbers.
3. A real stage-2 pass still needs, per migrated chapter:
   - strip running titles/page marks/footers and phantom next-chapter headers;
   - repair OCR token garble (`where`, `cste`, split words, Greek letters);
   - reconstruct ch 14/16 equations from the PDF or standard Doppler theory;
   - convert ch 21/22/10 HTML/flattened tables to clean markdown tables;
   - reconcile or annotate known number conflicts (switching time, memory
     limits, physical units);
   - add a provenance header + "checked against PDF §…" per file.
4. For now, the explainer document (`docs/dop3000/measurements-and-recordings.md`,
   repo side) was written from the corpus at general-idea level with
   cross-checks; treat it as the reviewed summary, and keep the raw chapters
   out of the public repo until the pass above is done.

---

## 6. Follow-up audit — did the Neo4j stage do any *text* cleaning?

**Asked:** "look into the neo4j work — maybe we have done cleaning in that stage?"

### 6.1 Cleaning that the Neo4j stage DID do (graph-level, not text-level)

Documented across JOURNAL.md / audits / bug reports (2026-07-19 → 07-29), all
operating on **nodes/relationships**, never on the chapter text:

- **Entity deduplication** — 9 merges (Mode: "Assisted Mode"→"Assisted mode",
  "External trigger mode"→"Trigger mode", "Multiplexing mode"→"Multiplexer
  mode", …; Parameter/Mode near-dupes pending); expected 105 → 96 entities.
- **Noise/test-artifact deletion** — ModificationLog nodes (164 + 410 + ~236
  across sessions), orphan Chunk nodes (3 on 07-26, 81 empty-shell chunks on
  07-28), test artifacts ("TestMergeParam", "Event Mode"), isolated Parameters
  that were never connected ("Burst length" deleted 07-26, later re-created).
- **Chunk re-ingestion** (2026-07-28) — 15 chapters re-ingested from the same
  chapter files after empty shells were removed (chunks 71 with text).
- **MENTIONS completion** (2026-07-29) — 53 orphan chunks linked; latest claim:
  174/174 chunks with MENTIONS, 0 isolated nodes, quality score 98.0.
- **Relationship misclassification fixes** — 2 confirmed AFFECTS→RESOLVES
  corrections (velocity scale factor→Aliasing, TGC→Saturation).
- **Embedding implementation** (2026-07-23) — 768-dim vectors (nomic-embed-text)
  on Chunk nodes; see `neo4j-backup/EMBEDDING-IMPLEMENTATION-REPORT.md`.

### 6.2 Evidence that the Neo4j stage did NOT clean the manual text

The graph's Chunk nodes store the chapter text verbatim. Direct probe of the
Neo4j string stores in the two surviving DB tarballs
(`neo4j-backup/neo4j-scientific-20260728-1339-pre-cleanup.tar.gz` and
`-1429-full-reingest.tar.gz`) finds the same OCR/extraction garble as the
corpus files:

| Marker (from corpus) | pre-cleanup tar | full-reingest tar |
|---|---|---|
| "Signal Processing S.A." (page furniture) | 93 | 134 |
| "its own its own" (ch 2 duplicate) | 1 | 1 |
| "Standart deviation" (ch 10 typo) | 0* | 1 |
| "Corse" (spec-table typo) | 2 | 2 |
| "Mean Values based on" (ch 10 stat example) | – | 1 |

\* the pre-cleanup snapshot predates the ch 10 re-ingest that carries it.

Chapters 1–10 were ingested from `source/chapters/` and 12–22 from
`source/mineru-chapters-split/` (JOURNAL/checklist) — i.e. the unproofread
corpora, without a text-fix step in between. The only *textual augmentation*
found in the DB are agent-authored `description` properties on entities and
Documents (e.g. Chapter 16's Document description) — useful metadata, but not a
correction of the chapter text.

### 6.3 Reliability caveat for the graph-state numbers

The journal's graph-state numbers are internally contradictory even within one
day (07-28: "312 nodes/486 rels" vs "294/463" vs "648/435"; 07-29 latest:
566 nodes / 956 rels / quality 98.0; while `TOOL-BUG-REPORT-neo4j.md`
(2026-07-29) describes re-testing tools against a DB with **0 chunks**).
The quality-98 end-state is therefore a *claim*, not a verified measurement in
this snapshot, and the DB may have been reset again afterwards.

### 6.4 Conclusion

Cleaning in the Neo4j stage was **structural and semantic only** (dedup,
orphan/test cleanup, MENTIONS coverage, relationship typing). It did **not**
fix OCR/extraction mistakes in the manual text — so it does not substitute for
the missing stage-2 pass, and it cannot be mined as a source of cleaned
chapters. What it *could* contribute to reference material is the curated
**entity glossary** (Parameter/Hardware/Mode names + agent-authored
descriptions + relationship evidence), which lives only inside the DB dumps and
would need a Neo4j instance to export.
