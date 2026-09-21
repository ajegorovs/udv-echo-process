# WP2 — the between-run reference floor

**Status:** WP2 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md).
Generated against the revision `0bef557` — the commit before these artefacts, and the
revision `reference-floor.json` records. Regenerate with

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-reference-floor \
    --analysis-commit <generator>
```

**What it measures.** Four recordings — `cr1`–`cr4`, one per reference job — repeat
**one** decoded condition across four distinct runs of the pass: burst 10, emissions 20,
50 gates at 1.85 mm. That condition is the only one this pass observes in more than one
run, so these four are the only reference realizations in the dataset and they are what
says how much of any cross-job difference can plausibly be *time*.

**Four measurements kept four.** The four runs are published individually, in campaign
order, with their depth-resolved window-mean profiles and all six pairwise
depth-resolved differences. **Nothing is averaged into a synthetic reference**: that
average is exactly the information this floor exists to estimate, so the module
computes none, and the gate carries the fact (`no_synthetic_reference`).

## The four runs

Depth-averaged window means on the primary 12 s window and the common support
(49 of the 50 gates), in mm/s; `iqr` is the same reduction of the per-gate robust
spread, so it is a within-window width, not a between-run one.

| run | job (step) | started | mean | median | iqr | rms | zero fraction |
|---|---|---|---|---|---|---|---|
| cr1 | common-reference-1 (2) | 12:35:05 | 27.681 | 27.328 | 26.597 | 39.421 | 0.0097 |
| cr2 | common-reference-2 (4) | 12:38:27 | 26.426 | 26.320 | 27.654 | 37.918 | 0.0106 |
| cr3 | common-reference-3 (6) | 12:41:38 | 28.794 | 28.016 | 27.561 | 39.597 | 0.0101 |
| cr4 | common-reference-4 (8) | 12:46:57 | 24.559 | 24.158 | 26.253 | 35.726 | 0.0107 |

The depth-averaged level moves by 4.235 mm/s across the campaign, and it does **not**
move monotonically: cr3 (sixth job) is the highest of the four and cr4 (eighth, the
last) the lowest, while cr1 and cr2 sit between them. The within-window widths and the
zero fractions barely move (26.25–27.65 mm/s and 0.0097–0.0107), so the between-run
variation is in the *level*, as in WP1 — and, as in WP1, a single gate's interquartile
range over 12 s (~26 mm/s) is far wider than any of these differences.

## The six pairs, and the floor

| pair | job-start separation | mean difference | rms difference | max abs per-depth difference | at depth |
|---|---|---|---|---|---|
| cr1–cr2 | 3.4 min | +1.255 | 3.397 | 7.843 | 10.14 mm |
| cr1–cr3 | 6.6 min | −1.112 | 2.411 | 6.389 | 89.69 mm |
| cr1–cr4 | 11.9 min | +3.122 | 5.959 | 13.170 | 19.39 mm |
| cr2–cr3 | 3.2 min | −2.367 | 3.832 | 8.611 | 11.99 mm |
| cr2–cr4 | 8.5 min | +1.868 | 4.957 | 10.027 | 21.24 mm |
| cr3–cr4 | 5.3 min | **+4.235** | 6.440 | **14.603** | 21.24 mm |

*Job-start separation* is the difference between the two runs' **jobs'** manifest start
timestamps (`job_start_separation_min` in the table and the document). It is **not** a
recording-to-recording interval and not an elapsed time between two measurements: the
pass carries no per-recording clock (a file name's `YYYYMMDDTHHMMSS` segment is the job's
`sweep_id`, identical for every point of that job), so a recording cannot be placed at an
instant. It is enough to order the four runs — and it is what the "not a rate" reading
below rests on — but it must not be read as time between measurements.

Two endpoints, because two kinds of comparison are screened against different numbers
and only the second is like for like with WP1's per-job anchor floors:

- **depth-resolved floor — 14.603 mm/s at 21.238 mm**, pair `cr3`–`cr4`, from *the
  largest absolute per-depth window-mean difference over the common support, over all
  six unique run pairs, each oriented earlier-to-later by campaign order* — with four
  runs there are six combinations, not twelve orderings. Any depth-resolved comparison of
  two jobs is screened against
  this number.
- **depth-averaged floor — 4.235 mm/s**, pair `cr3`–`cr4`, from *the largest absolute
  difference between the four runs' depth-averaged window means, over all six ordered
  pairs*. That is the same reduction WP1's floors use, so 4.235 mm/s is the number that
  compares directly with 9.646 / 11.980 (the burst jobs' anchor spread) and
  1.521 / 2.829 / 3.304 (the emissions jobs').

Both endpoints are observed differences between four recordings and four runs: not a
confidence interval, not a separability criterion, and neither proves an axis effect.
The four are four **repeated observations of the common-reference condition across four
distinct runs** — four runs, not four replicates of one run — and what they do *not*
provide is independent replication of the pitch, burst or emissions treatment levels:
each of those stays a single realization per level, and no count of profiles or gates
changes that.

Three readings follow, and they are the ones WP3 and WP4 must carry:

1. **The between-run floor is not the largest of the pass's floors, nor the smallest.**
   At 4.235 mm/s it is above every emissions job's own anchor spread (1.5–3.3 mm/s) and
   below both burst jobs' (9.6 and 12.0 mm/s). So a cross-job contrast among the
   emissions jobs is screened against more variation than their own anchors show, while
   the burst jobs' anchors already move further than the campaign's own reference drift.
2. **The ordering by time is not the ordering by difference.** The largest difference is
   between the two runs whose jobs start only 5.3 minutes apart (`cr3`–`cr4`), while the
   widest job-start separation (11.9 minutes, `cr1`–`cr4`) is not the largest. The floor
   is therefore not a drift term to be extrapolated with elapsed time; it is an observed
   spread over four runs, and WP3/WP4 may not reduce it to "per minute".
3. **The near field carries most of it, but not all of it.** Four of the six pairs reach
   their largest per-depth difference between 10 and 22 mm; `cr1`–`cr3` reaches its
   largest at 89.69 mm instead. Depth-resolved screening is therefore not optional, and
   a near-field-only comparison would understate one pair and misplace another.

## Artefacts

| file | what it is |
|---|---|
| [`reference-floor.csv`](reference-floor.csv) | the four runs with their five statistics each, then the six pairs with their four reductions |
| [`reference-floor.json`](reference-floor.json) | the four runs and their windows, the six pairs, both floor endpoints with their reductions, the four profiles and six differences depth-resolved, the statistics' definitions, the pair columns' definitions (including what the job-start separation is) and the gate |
| `figures/reference-floor.png` | the four runs drawn individually against depth, and below them all six differences with the floor's own pair marked |
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
  points of a 16 min 43 s campaign, not a rate.
- **No change to the frozen WP0 or WP1 artefacts.** This slice adds documents beside
  them and reads the recordings through the same loader.
