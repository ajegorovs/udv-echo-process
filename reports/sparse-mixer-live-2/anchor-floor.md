# WP1 — the per-job anchor floors

**Status:** WP1 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md).
Generated against the revision `8626de9` — the commit before these artefacts, and the
revision `anchor-floor.json` records. Regenerate with

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-anchor-floor \
    --dataset-root data/sparse-mixer-live-2 \
    --plan examples/sparse-mixer-live-2/run-plan.json \
    --report-dir reports/sparse-mixer-live-2 \
    --analysis-commit 8626de9
```

**What it measures.** Each scientific job is bracketed by three *block-local anchor
controls* — `ctrl-begin`, `ctrl-mid`, `ctrl-end` — which record the **reference spatial
window** (50 gates x 1.85 mm) at *that job's own* condition. This document turns them
into one floor per job, and it keeps the two quantities apart:

- **drift** — the signed differences over the job's acquisition order, `M - B`,
  `E - M`, `E - B`. Order is not assumed: the pass's own record and log make it
  recoverable, and the three anchors are in it.
- **spread** — `max - min` over `{B, M, E}`, whatever the order.

The two are not interchangeable, and this pass carries both cases. `emissions-128` is the
monotone one: its anchors fall 1.340 mm/s from `begin` to `mid` and 0.250 further to
`end`, so its whole-job drift `E - B = -1.590` is the same number as its spread, 1.590.
`burst-4` is the opposite: it falls 5.352 from `begin` to `mid` and rises 8.194 to
`end`, so its whole-job drift is **+2.842** while its spread is **8.194** — 2.88x the
number a single scalar would have reported for it. A monotone slide and three anchors
that turn inside the job are not the same evidence; the table carries both, and
`burst-4` against `emissions-128` below is exactly that contrast.

The two quantities are observed differences over three recordings, not a confidence
interval, and they neither prove an axis effect nor bound drift. Three anchors are three
recordings; no count of profiles or gates makes them independent replicates, and an
anchor floor belongs to *its* job's condition — it is not the reference condition (that is
CR1–CR4's, WP2) and it is not pooled across jobs.

## What this pass's anchors say

Supported-window values, in mm/s except `zero_fraction` (dimensionless), on the primary
12 s window and the common support 10.138–98.938 mm (49 of the reference window's 50
gates). `spread` and `drift` here are the `mean` statistic; the table carries all five
statistics (`mean`, `median`, `iqr`, `rms`, `zero_fraction`) and all four quantities.

| job | condition (burst / emissions) | B | M | E | drift M−B | drift E−M | spread |
|---|---|---|---|---|---|---|---|
| burst-4 | 4 / 20 | 21.334 | 15.982 | 24.176 | −5.352 | **+8.194** | **8.194** |
| burst-18 | 18 / 20 | 24.323 | 22.327 | 23.895 | −1.996 | +1.568 | 1.996 |
| emissions-8 | 10 / 8 | 18.613 | 23.068 | 21.215 | **+4.455** | −1.853 | **4.455** |
| emissions-64 | 10 / 64 | 24.760 | 25.394 | 25.021 | +0.634 | −0.373 | 0.634 |
| emissions-128 | 10 / 128 | 26.445 | 25.105 | 24.855 | −1.340 | −0.250 | 1.590 |

Four things follow, and they are what WP3 and WP4 must screen against:

1. **The five floors do not sort by job kind, and they overlap.** Largest to smallest the
   `mean` floors run `burst-4` **8.194** > `emissions-8` **4.455** > `burst-18` 1.996 >
   `emissions-128` 1.590 > `emissions-64` 0.634 — a 12.9x span end to end — but the two
   kinds are interleaved rather than separated. `burst-4`'s floor is 4.11x `burst-18`'s,
   and `emissions-8`'s is 2.23x `burst-18`'s, so the smallest burst floor (1.996) sits
   2.23x below the largest emissions floor (4.455). Only `burst-4` (8.194) sits
   above every emissions job, at 1.84x `emissions-8` and 5.15x `emissions-128`. A
   contrast measured inside `burst-4` is therefore screened against ~8.2 mm/s of its own
   anchor movement, but one inside `burst-18` is screened against ~2.0 mm/s — less than
   `emissions-8`'s 4.5 — so the floors have to be applied per job, not per kind. The
   emissions ladder is not ordered by its emission count either: 4.455 at emissions 8,
   0.634 at 64, 1.590 at 128.
2. **One job's spread is its whole-job drift; four turn at `mid`.** Only `emissions-128`
   is monotone in the `mean` — both signed steps are negative (−1.340, then −0.250) — so
   its spread 1.590 *is* its whole-job drift `E - B = -1.590`. In the other four the
   anchors turn inside the job and the spread is one single leg, not the distance the job
   travelled: `burst-4` spreads 8.194 on its `E - M` leg while `E - B = +2.842`;
   `burst-18` spreads 1.996 on `M - B` while `E - B = -0.428`; `emissions-8` spreads
   4.455 on `M - B` while `E - B = +2.602`; `emissions-64` spreads 0.634 on `M - B`
   while `E - B = +0.262`. In each of those four the spread exceeds the whole-job drift —
   2.88x, 4.66x, 1.71x and 2.42x — so reading a floor off `E - B` alone would report
   `burst-18` at 0.428 when its three anchors span 1.996, and `burst-4` at 2.842 when
   they span 8.194.
3. **The ordering of the five floors depends on which statistic is used, and the level
   does not dominate the robust spread in every job.** `median` reproduces the `mean`
   order; `iqr` moves `emissions-64` from last to third (4.958, above `burst-18`'s 1.395)
   and leaves `emissions-128` last (1.259); `rms` puts `emissions-128` first (3.109),
   above both burst jobs; `zero_fraction` puts `burst-18` first (0.002665) and `burst-4`
   last (0.000609). The floors' own dynamic range moves with it — 12.9x (`mean`), 8.6x
   (`median`), 4.2x (`iqr`), 2.1x (`rms`), 4.4x (`zero_fraction`) largest to smallest.
   And the width does not track the level: in two of the five jobs the within-window
   width moves further than the level does — `emissions-64`'s `iqr` floor is 7.81x its
   `mean` floor (4.958 against 0.634), and `emissions-8`'s exceeds its own (5.142 against
   4.455). On scale: a single gate's `iqr` over the 12 s window runs 23.242–34.172 mm/s
   across the fifteen anchors (`emissions-128`'s `end` to `emissions-8`'s `begin`), far
   wider than any of the differences above — these floors compare gate *means*, and no
   distributional claim may be read off them. `zero_fraction` never leaves 0.0058–0.0104
   (0.58–1.04 %), so every anchor's payload is live and the floors above are not a
   drop-out artifact.
4. **The fifteen anchor means span more than any one job's floor, and the per-job level
   bands do not all overlap.** Read as levels, the `mean` runs from 15.982 (`burst-4`
   `mid`) to 26.445 (`emissions-128` `begin`) — 10.463 mm/s over the fifteen anchors,
   wider than the largest floor of the pass (8.194, `burst-4`). The two
   highest-condition jobs' bands (`emissions-64` 24.760–25.394; `emissions-128`
   24.855–26.445) lie wholly above `burst-4`'s (15.982–24.176), and `emissions-8`'s
   (18.613–23.068) lies below `emissions-64`'s. These are three recordings at each job's
   own condition and the pass makes no parameter claim from the differences, but they are
   the concrete reason the five floors are not pooled into one number and why none of
   them is a statement about the reference condition. Nor is quiet a property of the
   emissions kind: its three floors span 0.634 to 4.455 mm/s (7.02x), with `emissions-8`
   the second-largest floor of all five jobs and `emissions-64` the smallest.

## The scientific rows inside their anchors

The pass carries **no per-recording clock**: the `YYYYMMDDTHHMMSS` segment of a file
name is the job's `sweep_id` — the same string for every point of that job, as its own
log entries spell it — so a row cannot be placed at an interpolated instant between its
two anchors. This deliverable therefore reports, for every scientific row whose gates
are the anchors' gates, the residual against the *left* anchor and against the *right*
one: those two are the extremes of every linear interpolation, so the pair spans the
bracket without inventing a weight. Each job also publishes its own manifest window
beside the summed duration of its recordings, so the handling time between recordings is
an observed quantity:

| job | wall clock (manifest) | summed recording spans | handling time | per recording |
|---|---|---|---|---|
| burst-4 | 92.95 s | 62.69 s | 30.26 s | 6.05 s |
| burst-18 | 92.86 s | 62.65 s | 30.21 s | 6.04 s |
| emissions-8 | 76.82 s | 50.17 s | 26.66 s | 6.66 s |
| emissions-64 | 76.81 s | 50.06 s | 26.74 s | 6.69 s |
| emissions-128 | 76.77 s | 50.05 s | 26.72 s | 6.68 s |

`per recording` is the handling time divided by the job's own recording count — five for
a burst job (`B`, `CC1`/`CC2`, `M`, `CC3`/`CC4`, `E`) and four for an emissions job
(`B`, `E8`/`E64`/`E128`, `M`, `E`) — and the kind shows up there: 6.04–6.05 s against
6.66–6.69 s, i.e. ~0.63 s more handling per recording on an emissions job. The summed
recording spans are 62.6455–62.6901 s over the burst jobs' five recordings each and
50.0492–50.1685 s over the emissions jobs' four each: an average of 12.51–12.54 s per
recording, the designed 12 s plus a retained surplus that is not part of the analysed
exposure.

The bracketed rows, with their residuals against each bracketing anchor (`mean`
statistic, per gate, then the unweighted mean over the 49 supported gates). The `worst
gate` column is the largest per-gate |residual| of the row against either bracketing
anchor, named with the anchor it belongs to:

| job | row | bracket | vs left (mm/s) | vs right (mm/s) | worst gate |
|---|---|---|---|---|---|
| burst-4 | cc1 | begin → mid | not computed: another pitch (WP3) | — | — |
| burst-4 | cc3 | mid → end | not computed: another pitch (WP3) | — | — |
| burst-18 | cc2 | begin → mid | not computed: another pitch (WP3) | — | — |
| burst-18 | cc4 | mid → end | not computed: another pitch (WP3) | — | — |
| emissions-8 | e8 | begin → mid | **+7.429** | +2.974 | 21.997 @ 54.54 mm (vs left) |
| emissions-64 | e64 | begin → mid | −1.437 | −2.072 | 12.042 @ 71.19 mm (vs right) |
| emissions-128 | e128 | begin → mid | −1.507 | −0.167 | 9.573 @ 45.29 mm (vs right) |

Two cautions this table exists to make visible, checked against this pass's numbers.
First, the depth-averaged residual is small while the *largest per-gate* residual is not:
the three emissions rows' depth-averaged residuals lie between −2.072 and +7.429 mm/s
while their largest per-gate |residual| is 6.571–21.997 mm/s, which is 2.96x (`e8`),
5.81x (`e64`) and 6.35x (`e128`) the row's own largest depth-averaged |residual| — and
the worst gates do not sit where the depth averages do (54.54 mm, 71.19 mm, 45.29 mm). A
depth-averaged comparison hides local structure, and WP4 must report depth-resolved
differences beside its scalars. Second, the "positive against both anchors" pattern is
present here, on a different row than a reader of the first sitting's document would
expect: `e8` is above **both** of its anchors (+7.429 against `ctrl-begin`, +2.974
against `ctrl-mid`), so it sits above its whole bracket rather than inside it, while
`e64` (−1.437, −2.072) and `e128` (−1.507, −0.167) are the mirror case, each below both
of its own anchors. All three emissions rows are thus consistently on one side of the
level interval their two bracketing anchors span — recorded as an observation, not as an
emissions effect, and exactly the kind of statement WP4's screening must make before
claiming the axis moved.

The burst jobs' `cc1`/`cc2`/`cc3`/`cc4` rows are reported with their bracket, their
acquisition order and their gate count (145 gates for `cc1`/`cc2`, 31 for `cc3`/`cc4`)
but **no residual**: they are recorded at another pitch, so their gates are not the
anchors' gates, and the comparison belongs to WP3's cross-pitch alignment on common knots
no finer than 2.96 mm.

## Artefacts

| file | what it is |
|---|---|
| [`anchor-floor.csv`](anchor-floor.csv) | 100 rows: one per job x statistic (5) x quantity (4), each carrying the three anchor values and the derived value |
| [`anchor-floor.json`](anchor-floor.json) | the definitions of every statistic and quantity, the anchor labels and their `sweep_id`s, the per-job drift/spread and depth-resolved levels and drifts, the bracketed rows, the job-time accounting, the scope caveats and the gate |
| `figures/anchor-<job>.png` | one figure per job: the three anchor `mean` profiles against depth, and below them the two signed drifts with the spread beside them |
| this document | the reading of the numbers, including the four consequences and the two cautions above |

The slice directory also holds the other WPs' artefacts — `points.csv`,
`qc-summary.json`, `reference-floor.{csv,json}`, `pitch-burst.{csv,json,md}`,
`emissions-ladder.{csv,json,md}`, `decision-table.{csv,json,md}` and `README.md`. This
document reads none of them and makes no claim from them; every number above is
`anchor-floor.json`'s (or `anchor-floor.csv`'s).

## What is checked before a floor is published

The command refuses (non-zero exit, named reason, nothing written) when the frozen WP0
ingest refuses — a point the table rejected is never measured — and when a job carries no
committed recording or not exactly one recording under each of `ctrl-begin`, `ctrl-mid`
and `ctrl-end`; when the anchors of one job sit on different native depth grids; when an
anchor's decoded condition is not its job's, or its window is not the reference 50 gates
at 1.85 mm; when a derived drift or spread is not finite; when a scientific row is not
bracketed by an anchor on each side, or does not share the store id of both of them; and
when there is no generator revision to record. The gate then holds only when all
**fourteen** structural checks pass: five jobs, three anchors each, the reference window,
`B ... E` bracketing, one sweep per job, agreeing grids within a job, one shared
supported-gate count across all five (49 here), drift and spread distinct and
recomputable, a complete derived table (100 rows), complete brackets (7 bracketed rows
against 7 scientific labels), both residual extremes present where the grid matches (3
rows) and absent where it does not (4 rows), the job-time accounting non-negative, and
the primary window and support the WP0 ones. `anchor-floor.json` publishes all fourteen
in `checks` and their conjunction in `ok`, which is `true` for this pass.

## What is deliberately not here

- **No reference-condition statement.** The anchors are not reference realizations; the
  between-run reference floor is WP2's, from CR1–CR4.
- **No interaction and no axis effect.** The pitch x burst interaction is WP3's, using
  these floors; the emissions ladder is WP4's, using these floors plus WP2's. No
  difference in this document is a parameter effect.
- **No temporal spectra.** The 12 s primary window is the exposure here; the retained
  surplus and the achieved timestamps are WP4's business.
- **No cross-sitting reading.** Every floor above is this sitting's own; two sittings
  permit a reproducibility check, not a population claim, and that check is a separate
  slice with its own rules.
- **No change to the frozen WP0 artefacts.** This slice adds documents beside them and
  reads the recordings through the same loader, so window, support and per-gate
  statistics are the table's own.
