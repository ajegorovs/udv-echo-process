# WP0–WP5 — the second mixer sitting through the frozen sparse stack

**Status:** the frozen analysis of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md)
applied, with no change to its decision logic, to
[`data/sparse-mixer-live-2/`](../../data/sparse-mixer-live-2/README.md) — the **second**
mixer-enabled realization of the frozen nine-job design. Same ingest, same four measurement
slices, same synthesis; every gate holds.

Two of the five slices needed a fix before they could run a second pass at all, and it was a
defect in them rather than in this pass: WP3 and WP4 carried the *first* sitting's measured
floors as module constants, so they screened every pass against the first sitting's campaign —
and published those numbers as the second's screening guards — while refusing their own gate.
Both now read the floors from the pass's own WP1 and WP2 documents beside their own artefacts
and refuse by name when those documents are absent or belong to another pass. The
[plan's status block](../../docs/dop3000/sparse-pass-analysis-plan.md) records the amendment,
and `reports/sparse-mixer-live-1/` regenerates byte for byte unchanged.

**This report is not a comparison.** Every floor in it is this sitting's own, and it states what
*this* pass measured. Reading it against the first sitting's report is a separate slice with its
own rules, and it is not made here.

## The artefacts

| artefact | what it is |
|---|---|
| [`points.csv`](points.csv) | one row per committed recording: identity, order, condition, requested and stored window, decoded settings, the achieved timing measured from the stored timestamps, the retention the file covers, the signal statistics of the common window on the common support, and the provenance that ties the row to the bytes, the log, the manifest and the plan |
| [`qc-summary.json`](qc-summary.json) | the pass-level assertions, the two views, the metric definitions, the gate verdict, and the SHA-256 of `points.csv`'s own bytes |
| [`anchor-floor.{csv,json,md}`](anchor-floor.md) | WP1 — each scientific job's own block-local anchor drift (B→M→E, signed) and spread, with a figure per job under `figures/anchor-<job>.png` |
| [`reference-floor.{csv,json,md}`](reference-floor.md) | WP2 — the between-run reference floor at 1.85 mm: the four reference runs published individually, their six ordered pairs, and the two endpoints |
| [`pitch-burst.{csv,json,md}`](pitch-burst.md) | WP3 — the 2×2 pitch × burst interaction on the common knots, with its own figure |
| [`emissions-ladder.{csv,json,md}`](emissions-ladder.md) | WP4 — the four emission levels' velocity stability and their temporal cost, with two figures |
| [`decision-table.{csv,json,md}`](decision-table.md) | WP5 — the seven-row decision built on the five slices above, plus the Stage-2 campaign's own pairs as a sixth evidence source |

## Reproduce

The generator is `8626de9` — the first revision on which the stack can run a second pass at all.
Each slice records that revision in its own document, and each reads the two floor documents
beside it, so the six commands run **in order into one directory**:

```bash
R=reports/sparse-mixer-live-2
D=data/sparse-mixer-live-2
P=examples/sparse-mixer-live-2/run-plan.json
C=8626de9

.venv/Scripts/python.exe -m udv_echo_process.cli sparse-inventory        --dataset-root $D --plan $P        --report-dir $R --analysis-commit $C
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-anchor-floor     --dataset-root $D --plan $P        --report-dir $R --analysis-commit $C
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-reference-floor  --dataset-root $D --plan $P        --report-dir $R --analysis-commit $C
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-pitch-burst      --dataset-root $D --plan-path $P   --report-dir $R --analysis-commit $C
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-emissions-ladder --dataset-root $D --plan-path $P   --report-dir $R --analysis-commit $C
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-decision         --report-dir $R --output-dir $R --plan-path $P --analysis-commit $C
```

A bare command records the **current HEAD** instead, which changes the `analysis_commit` field
and therefore the document's bytes — pass the recorded revision to reproduce the committed
files exactly. `tests/test_sparse_report_live2.py::test_the_whole_report_regenerates_byte_for_byte_at_the_recorded_revision`
runs all six into a temporary directory and compares every file, figures included.

## The two views

The design is the frozen one, and this pass realized it: the **primary window** is the declared
12.0 s (100 nominal 500-RPM revolutions = 12.0 s, a nominal-duration equivalence and not a
measured rotor speed), cut in each recording by its own stored timestamps, and the **common
physical support** is the intersection of every recording's decoded depth range —
**10.138 – 98.938 mm**. Metrics are computed on each recording's own native gate grid inside the
support: no interpolation, no resampling. Each file retains more than the designed window, and
that surplus belongs to the full-record view, not to the analysed exposure.

## What the committed bytes say

Every number below is read back from the committed files by the project's own reader.

| | value |
|---|---|
| recordings | **26** (nine jobs: 5 + 1 + 5 + 1 + 4 + 1 + 4 + 1 + 4) |
| decode failures / NaN cells / non-monotone files / non-live files | 0 / 0 / 0 / 0 |
| common support / primary window | 10.138 – 98.938 mm / 100 rev = the designed 12.0 s |
| achieved period from the stored timestamps | worst departure from the planner's law 0.0002234 s |
| stored words (14 / 27 / 84) | each point's own emissions request / **1** / 0 in all 26 — word 27 is the instrument's option-list *index*, not a length, and not the historical sweep's 4 |
| plan fingerprint | `f9de5b803921b62e788572ef5209a779d05638f1f7da4933384a743c02b6b7ef` |
| `points.csv` | `sha256:13c1ba0a6106e82fdb73b0bab1ddde69272eb52ed3e1d7d6475209af736988d1` |

**WP1 — each job's own anchors** (mean statistic; `anchor-floor.json`):

| job | drift M−B | drift E−M | spread (max − min over the three anchors) |
|---|---|---|---|
| burst-4 | −5.352 | +8.194 | **8.194** |
| burst-18 | −1.996 | +1.568 | **1.996** |
| emissions-8 | +4.455 | −1.853 | **4.455** |
| emissions-64 | +0.634 | −0.373 | **0.634** |
| emissions-128 | −1.340 | −0.250 | **1.590** |

**WP2 — the between-run reference floor**, from the four reference runs at burst 10 / emissions
20 / 1.85 mm:

| endpoint | value | pair |
|---|---|---|
| depth-resolved | **14.201 mm/s at 24.938 mm** | cr2 − cr4 |
| depth-averaged | **2.344 mm/s** | cr1 − cr2 |

The six ordered pairs, each oriented earlier-to-later: cr1−cr2 −2.344 (max 9.562 at 82.29 mm),
cr1−cr3 −1.578 (12.141 at 45.29 mm), cr1−cr4 −0.249 (10.233 at 32.34 mm), cr2−cr3 +0.766
(11.074 at 45.29 mm), cr2−cr4 +2.094 (**14.201 at 24.94 mm**), cr3−cr4 +1.328 (8.998 at
28.64 mm). The floor is the worst of them, in the direction the endpoint is screened on.

**WP3 — the pitch × burst interaction** on 31 common knots: `I(z)` ranges −11.709 mm/s at
42.698 mm to +15.506 mm/s at 84.138 mm, and its depth-averaged reduction is **+1.083 mm/s** over
those 31 knots. The two anchor guards this pass's own jobs set are **1.996 mm/s** (burst 18) and
**8.194 mm/s** (burst 4); 1 knot exceeds WP2's depth-resolved floor, 7 exceed burst-4's guard and
25 exceed burst-18's. The alignment check holds: the largest corner offset is 0.246667 mm of the
1.4800 mm half-pitch limit.

**WP4 — the emissions ladder**: the four levels measured against this pass's own floors —
published 14.201 / 2.344 / 4.455 / 0.634 / 1.590 mm/s, each reproduced by the slice's own
rebuild from these recordings to within the 1e-3 mm/s published tolerance. E128 against its
bracketing anchors: mean −1.507 / −0.167 mm/s, extreme 6.571 mm/s at 48.988 mm, 15 of 49 knots
of one sign.

**WP5 — the decision**: seven rows, one per question the plan's gate asks, with the verdicts
this sitting supports — `pitch_x_burst_interaction` **defer**, `e8_versus_e20` **keep**,
`e64_versus_e20` **replace**, `e128_versus_e64` **replace**, `prf` **keep**,
`dense_second_pass` **defer**, `sensitivity_d1` **requires diagnostic**. The synthesis's own
closing line is *nothing recommended*: no acquisition follows from this pass.

## Whose floors these are

Every floor in this report is **this pass's own**, read from the WP1 and WP2 documents that sit
beside it in this directory, and each of those documents is accepted only if it passed its own
gate, states this pass's plan fingerprint `f9de5b80…`, and publishes the digest of the table it
was reduced from. A document measured for the other sitting (`65529803…`) is refused by name, so
no number of another campaign's can decide this one's outcome — the defect that stopped this
report being writable at all, and the reason the first sitting's report is untouched.

## What is deliberately not here

- **Any comparison with the first sitting.** Each report stands on its own floors; two sittings
  permit a *reproducibility* check, not a population claim, and that check is a later slice.
- **The signal analysis this campaign was run for.** The ~1 s oscillation hypothesis, the
  sampling-aware spectra, the depth traces and the cross-sitting contrast belong to
  [`docs/dop3000/sparse-signal-analysis-plan.md`](../../docs/dop3000/sparse-signal-analysis-plan.md),
  whose SA0 checkpoint binds this pass through the same ingest.
- **Anything the files cannot state.** No tachometer, echo or energy channel is present in these
  velocity recordings, so measured mixer speed, SNRs and receiver saturation are not inferred
  here.
