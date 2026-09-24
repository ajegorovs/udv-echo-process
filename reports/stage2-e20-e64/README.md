# The Stage-2 paired analysis — the four E64 - E20 contrasts, and the floor this campaign measured for itself

**Status:** the analysis section 4b of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md)
names, implemented as a slice beside WP0-WP5. It reads the eight committed recordings of
[`data/stage2-e20-e64/`](../../data/stage2-e20-e64/README.md) — the counterbalanced campaign the
frozen decision table recommended and the compiled run plan executed on 2026-09-21 — through the
frozen WP0 ingest's own binding, decoding and refusals.

This analysis slice did not change acquisition, the frozen ingest, or the earlier decision
table. A subsequent reviewed slice updated the E64-vs-E20 row in
[`../sparse-mixer-live-1/decision-table.md`](../sparse-mixer-live-1/decision-table.md).

| artefact | what it is |
|---|---|
| [`pairs.csv`](pairs.csv) | the eight runs, the four contrasts (oriented, plus their raw acquisition-order difference) and the two level floors, one row per published number |
| [`pairs.json`](pairs.json) | every published number's definition, the gate checks, the floor provenance and the table's SHA-256 |
| [`pairs.md`](pairs.md) | the report itself: the design, the four contrasts, the floor, the outcome, and what it does to the frozen table |
| [`first-run-sensitivity.md`](first-run-sensitivity.md) | explicitly post-hoc three-pair reading without the first pair; it does not change the primary verdict |
| [`figures/pairs.png`](figures/pairs.png) | the eight runs individually, and the four contrasts against the depth-resolved floor band |

## Reproduce

The generator for the current artefacts is the revision recorded in `pairs.json`
(`analysis_commit`). To reproduce the committed files byte for byte, pass that revision:

```bash
uv run python -m udv_echo_process.cli sparse-stage2-pairs --analysis-commit 6253a1d
```

The bare command records the **current HEAD** instead, which changes `analysis_commit` and
therefore the document's bytes — pass the recorded **generator** revision to reproduce the
committed files exactly.
`tests/test_sparse_stage2_pairs.py::test_the_committed_report_is_reproducible_with_the_recorded_revision`
runs that comparison, LF-normalized so a checkout's `core.autocrlf` cannot decide it.

## What the committed bytes say

| | value |
|---|---|
| runs | **8**, four pairs of one run of each level, in the frozen order `e20-a e64-a e64-b e20-b e20-c e64-c e64-d e20-d` |
| stored word 14 | **20 64 64 20 20 64 64 20** — each run's own declaration, 8/8 |
| frame | identical across all eight in **21 decoded settings**; emissions is the only one that moves |
| shared views | the designed **12.0 s = 100 revolutions**, and the common support **10.138 - 100.788 mm**, which covers **all 50 gates** of the declared 1.850 mm x 50 reference window |
| the four contrasts, oriented E64 - E20 | **A +7.2256, B -1.5733, C +0.3448, D +1.3418 mm/s** |
| their acquisition orientations | A 20 -> 64, B 64 -> 20, C 20 -> 64, D 64 -> 20 (the counterbalance) |
| depth-resolved floor | **28.5481 mm/s** at 15.688 mm (from E20) |
| depth-averaged floor (the screen) | **9.4044 mm/s** (from E20; the E64 level's own floor is 1.3449 mm/s) |
| outcome | **unresolved overlap** — depth-averaged: *not detected*; depth-resolved: *not detected*, 0.0 % of gates resolved |

## The two lines this artifact exists to keep straight

- **Orientation.** Each pair is read **E64 - E20** whatever order it was acquired in, and the
  acquisition orientation is published beside the contrast. On a `64 -> 20` pair the raw
  acquisition-order difference has the opposite sign to the published contrast — pairs B and D
  above. A counterbalance read without the orientation is a sign error on half the contrasts.
- **Provenance of the screen.** The floor is **this campaign's own** run-to-run variation —
  the largest absolute window-mean difference over each level's six unique run pairs, the
  endpoint WP2 used on the reference runs — taken as the larger of the two levels'. The earlier
  pass's **4.235 / 14.603 mm/s** (`sparse-mixer-live-1`) are quoted as context only and screen
  nothing here: the earlier mixer-enabled pass measured four E20 references and one E64
  observation in the same campaign, but its floor covers the E20 runs alone. An E64-only
  top-up compared with those earlier E20 runs *would* have crossed campaigns.

## The outcome, and how it was reached

The criterion was stated in advance and has exactly two allowed outcomes: a **resolved
difference** (the four contrasts consistently larger than the contemporaneous variation, in a
consistent direction) or an **unresolved overlap** (the separation comparable to or smaller than
that variation, which is itself the answer). The rule is implemented once, in
`decide()`, and pinned by table-driven tests on synthetic input so the vocabulary cannot drift
from the criterion.

Here the four contrasts span 0.3448 - 7.2256 mm/s in absolute value, **none** exceeds the
9.4044 mm/s screen, and their directions are not consistent (A and C positive, B negative, D
positive) — an unresolved overlap. Inside that, the kind is **not detected**: the largest
contrast is still inside the campaign's own variation. The depth-resolved reading agrees: no
gate has all four pairs above the depth-resolved floor in one direction.

**How the screen is composed is part of the finding.** Both floors are *maxima* over the six
unique run pairs of one level — deliberately conservative, and the endpoint the earlier pass's
floor used — so one run that departs from the other three of its level sets the screen for the
whole campaign. That is what happened: the emissions-20 runs are +22.6053, +32.0097, +30.3335,
+29.8341 mm/s (spread **9.4044**), the campaign's first job `e20-a` being the low one, while the
emissions-64 runs are +29.8310, +30.4364, +30.6783, +31.1759 mm/s (spread **1.3449**). The
report names that run rather than excluding or smoothing it: dropping a run *after* seeing the
contrasts would be a choice made by the result. Whether the campaign should be read again
against another endpoint — or whether `e20-a` belongs in this campaign's population at all — is
a decision for review, not for this generator. A separate, explicitly post-hoc
[first-run sensitivity reading](first-run-sensitivity.md) omits the whole first pair;
it leaves the primary verdict unchanged and does not establish that the run was invalid.

## What this does to the frozen decision table

**Subsequent decision update.** This Stage-2 generator did not rewrite
`reports/sparse-mixer-live-1/decision-table.md`. Its E64-vs-E20 row originally read
`defer` / not resolvable with that pass's design; a separate reviewed slice has since
updated it to `replace` / not detected against this campaign's floor. The Stage-2
measurement and the later decision remain distinct artefacts.

## What is deliberately not here

- **No re-screening against a kinder endpoint.** The frozen endpoint is the maximum; the
  per-level spreads are published so a reader can see what a different one would give, but no
  verdict above uses one.
- **No comparison with the earlier pass's residuals** beyond its two floors, quoted and named.
- **No acquisition change**, and no re-running of the campaign: the artefact states what this
  sitting measured.
- **No new decision row.** The outcome was published here; the existing E64-vs-E20 row
  was updated in a separate reviewed decision slice, not by this analysis.
