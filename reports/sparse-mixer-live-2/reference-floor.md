# WP2 — the between-run reference floor

**Status:** WP2 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md).
Generated against the revision `8626de9` — the generator this pass's whole report records, and
the revision `reference-floor.json` records — for the pass whose plan fingerprint is
`f9de5b803921b62e788572ef5209a779d05638f1f7da4933384a743c02b6b7ef`. Regenerate with

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-reference-floor \
    --dataset-root data/sparse-mixer-live-2 \
    --plan examples/sparse-mixer-live-2/run-plan.json \
    --report-dir reports/sparse-mixer-live-2 \
    --analysis-commit 8626de9
```

A bare command records the current HEAD instead, which changes the `analysis_commit` field and
therefore the document's bytes; pass the recorded revision to reproduce the committed files
exactly.

**What it measures.** Four recordings — `cr1`–`cr4`, one per reference job — repeat
**one** decoded condition across four distinct runs of the pass: burst 10, emissions 20,
50 gates at 1.85 mm. That condition is the only one this pass observes in more than one
run, so these four are the only reference realizations in the dataset and they are what
says how much of any cross-job difference can plausibly be *time*. Their jobs' manifest
start timestamps lie 3.3 to 14.4 minutes apart (the job-start separation of the pairs
table below).

**Four measurements kept four.** The four runs are published individually, in campaign
order, with their depth-resolved window-mean profiles and all six pairwise
depth-resolved differences. **Nothing is averaged into a synthetic reference**: that
average is exactly the information this floor exists to estimate, so the module
computes none, the figure draws none, and the gate carries the fact
(`no_synthetic_reference`).

## The four runs

Depth-averaged window means on the primary 12 s window and the common support
(49 of the 50 gates), in mm/s; `iqr` is the same reduction of the per-gate robust
spread, so it is a within-window width, not a between-run one.

| run | job (step) | started | mean | median | iqr | rms | zero fraction |
|---|---|---|---|---|---|---|---|
| cr1 | common-reference-1 (2) | 17:20:29 | 21.019 | 20.926 | 26.972 | 34.658 | 0.0090 |
| cr2 | common-reference-2 (4) | 17:24:16 | 23.363 | 23.482 | 25.620 | 35.283 | 0.0085 |
| cr3 | common-reference-3 (6) | 17:31:37 | 22.597 | 22.106 | 24.348 | 34.689 | 0.0077 |
| cr4 | common-reference-4 (8) | 17:34:55 | 21.268 | 20.398 | 29.693 | 36.175 | 0.0094 |

The depth-averaged level moves by 2.344 mm/s across the campaign, and it does **not**
move monotonically: cr2 (the second run of the four) is the highest of the four, at
23.363 mm/s, cr1 (the first) the lowest at 21.019, and the level rises then falls back —
cr3 (sixth job) 22.597 and cr4 (eighth, the last) 21.268, so the run that closes the
four is only 0.249 mm/s above the run that opens them. The within-window widths move by
more than the level does, not less: `iqr` spans 24.348–29.693 mm/s
(5.345 mm/s, widest at cr4 and narrowest at cr3) and the zero fractions span
0.0077–0.0094, with the same ordering of the four runs (cr3 < cr2 < cr1 < cr4) — the
width is not the quiet quantity here. What both readings share is scale: even the
narrowest run's own interquartile range over 12 s (24.348 mm/s) is wider than the
largest between-run per-depth difference anywhere in the six pairs (14.201 mm/s), so no
between-run number below is visible against a single gate's own spread.

## The six pairs, and the floor

| pair | job-start separation | mean difference | rms difference | max abs per-depth difference | at depth |
|---|---|---|---|---|---|
| cr1–cr2 | 3.8 min | **−2.344** | 3.974 | 9.562 | 82.29 mm |
| cr1–cr3 | 11.1 min | −1.578 | 5.163 | 12.141 | 45.29 mm |
| cr1–cr4 | 14.4 min | −0.249 | 5.337 | 10.233 | 32.34 mm |
| cr2–cr3 | 7.4 min | +0.766 | 5.433 | 11.074 | 45.29 mm |
| cr2–cr4 | 10.7 min | +2.094 | 6.557 | **14.201** | 24.94 mm |
| cr3–cr4 | 3.3 min | +1.328 | 4.747 | 8.998 | 28.64 mm |

*Job-start separation* is the difference between the two runs' **jobs'** manifest start
timestamps (`job_start_separation_min` in the table and the document). It is **not** a
recording-to-recording interval and not an elapsed time between two measurements: the
pass carries no per-recording clock (a file name's `YYYYMMDDTHHMMSS` segment is the job's
`sweep_id`, identical for every point of that job), so a recording cannot be placed at an
instant. It is enough to order the four runs — and it is what the "not a rate" reading
below rests on — but it must not be read as time between measurements.

Two endpoints, because two kinds of comparison are screened against different numbers
and only the second is like for like with WP1's per-job anchor floors:

- **depth-resolved floor — 14.201 mm/s at 24.938 mm**, pair `cr2`–`cr4`, from *the
  largest absolute per-depth window-mean difference over the common support, over all
  six unique run pairs, each oriented earlier-to-later by campaign order* — with four
  runs there are six combinations, not twelve orderings. Any depth-resolved comparison of
  two jobs is screened against
  this number.
- **depth-averaged floor — 2.344 mm/s**, pair `cr1`–`cr2`, from *the largest absolute
  difference between the four runs' depth-averaged window means, over the same six
  unique run pairs*. That is the same reduction WP1's floors use, so 2.344 mm/s is the
  number that compares directly with 8.194 / 1.996 (the burst jobs' anchor spread) and
  4.455 / 0.634 / 1.590 (the emissions jobs'). It is also, by construction, exactly the
  largest of the six pairs' own mean differences — the depth-averaged endpoint is that
  column's worst entry — while the depth-resolved endpoint is 6.06× it; the gate checks
  the two are distinct quantities and recomputable.

Both endpoints are observed differences between four recordings and four runs: not a
confidence interval, not a separability criterion, and neither proves an axis effect.
The four are four **repeated observations of the common-reference condition across four
distinct runs** — four runs, not four replicates of one run — and what they do *not*
provide is independent replication of the pitch, burst or emissions treatment levels:
each of those stays a single realization per level, and no count of profiles or gates
changes that.

Three readings follow, and they are the ones WP3 and WP4 must carry:

1. **The between-run floor is not the largest of the pass's floors, nor the smallest —
   and it does not line up with either axis.** At 2.344 mm/s it is above the
   emissions-64 and emissions-128 jobs' own anchor spreads (0.634 and 1.590 mm/s) and
   above burst-18's (1.996 mm/s), and below emissions-8's (4.455 mm/s) and burst-4's
   (8.194 mm/s). So an emissions-64-versus-emissions-128 contrast is screened against
   more variation than either of those jobs' anchors shows, while burst-4's anchors
   already move nearly 3.5× further than the campaign's own reference drift — and
   burst-18's move *less* than it. So the floor does not sort the pass into "the
   emissions jobs below it, the burst jobs above it"; it sits between the two burst jobs
   and above two of the three emissions jobs. The whole ordering this pass shows is
   0.634 (emissions-64) < 1.590 (emissions-128) < 1.996 (burst-18) < **2.344** (the
   floor) < 4.455 (emissions-8) < 8.194 (burst-4) mm/s, with the floor fourth of the six.
2. **The ordering by time is not the ordering by difference, on either reduction.** The
   largest depth-averaged difference is `cr1`–`cr2` (2.344 mm/s) — the *second-closest*
   pair of jobs, 3.8 minutes apart — while the widest job-start separation, `cr1`–`cr4`
   at 14.4 minutes, is the *smallest* depth-averaged difference of the six
   (−0.249 mm/s) and only fourth of six on the per-depth reduction. The largest
   per-depth difference, `cr2`–`cr4` at 14.201 mm/s, sits third of six by separation
   (10.7 minutes). The floor is therefore not a drift term to be extrapolated with
   elapsed time; it is an observed spread over four runs, and WP3/WP4 may not reduce it
   to "per minute".
3. **The largest per-depth differences sit in the mid field, not the near field.** No
   pair of the six reaches its largest per-depth difference in the shallow part of the
   support: three land between 24.94 and 32.34 mm (`cr2`–`cr4` at 24.94 mm — the largest
   of the six — `cr3`–`cr4` at 28.64 mm, `cr1`–`cr4` at 32.34 mm), two at the same depth
   45.29 mm (`cr1`–`cr3` at 12.141 and `cr2`–`cr3` at 11.074 mm/s), and one at 82.29 mm
   (`cr1`–`cr2`, which is also the smallest of the six at 9.562 mm/s). Depth-resolved
   screening is therefore not optional, and a near-field-only comparison would not
   merely understate a pair — it would miss the largest difference of all.

## Artefacts

| file | what it is |
|---|---|
| [`reference-floor.csv`](reference-floor.csv) | the four runs with their five statistics each, then the six pairs with their four reductions |
| [`reference-floor.json`](reference-floor.json) | the four runs and their windows, the six pairs, both floor endpoints with their reductions, the four profiles and six differences depth-resolved, the statistics' definitions, the pair columns' definitions (including what the job-start separation is), the gate, and the SHA-256 of the table's own bytes |
| `figures/reference-floor.png` | the four runs drawn individually against depth — no averaged profile is drawn — and below them all six differences with the floor's own pair marked |
| this document | the reading of the numbers, including the two-endpoint decision and the three consequences |

## What is checked before the floor is published

The command refuses (non-zero exit, named reason, nothing written) when the frozen WP0
ingest refuses, when the pass does not hold exactly four reference recordings, when the
four do not share one decoded condition — the pass's declared burst 10 / emissions 20 /
50 gates at 1.85 mm — or when their native depth grids differ. The gate then holds only
when all ten structural checks pass: four runs over the four reference jobs with four
distinct labels, one condition, campaign order increasing, one supported-gate count, six
unique run pairs oriented in campaign order, every pair separated by its job starts, the floor
equal to the
worst pair, the two endpoints distinct and recomputable, no synthetic reference, and the
primary window and support the WP0 ones.

## What is deliberately not here

- **No parameter effect.** These four runs vary nothing but time and the jobs around
  them; an effect of a pitch, a burst or an emissions level is WP3's and WP4's.
- **No comparison against WP1's anchors.** The anchors belong to other conditions; only
  the *reduction* is shared, which is why the depth-averaged endpoint is published.
- **No time-extrapolation.** The floor is an observed spread over four runs at four
  points of one campaign whose job starts are at most 14.4 minutes apart, not a rate.
- **No change to the frozen WP0 or WP1 artefacts.** This slice adds documents beside
  them and reads the recordings through the same loader.
