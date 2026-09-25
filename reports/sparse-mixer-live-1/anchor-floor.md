# WP1 — the per-job anchor floors

**Status:** WP1 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md).
Generated against the revision `31bb8ab` — the commit before these artefacts, and the
revision `anchor-floor.json` records. Regenerate with

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-anchor-floor \
    --analysis-commit <generator>
```

**What it measures.** Each scientific job is bracketed by three *block-local anchor
controls* — `ctrl-begin`, `ctrl-mid`, `ctrl-end` — which record the **reference spatial
window** (50 gates x 1.85 mm) at *that job's own* condition. This document turns them
into one floor per job, and it keeps the two quantities apart:

- **drift** — the signed differences over the job's acquisition order, `M - B`,
  `E - M`, `E - B`. Order is not assumed: the pass's own record and log make it
  recoverable, and the three anchors are in it.
- **spread** — `max - min` over `{B, M, E}`, whatever the order.

A monotone 9.6 mm/s slide and three anchors scattered over a 9.6 mm/s range have the
same spread and are **not** the same evidence; the table carries both, and `burst-4`
against `burst-18` below is exactly that contrast.

Drift and spread are observed differences over three recordings, not a confidence
interval, and they neither prove an axis effect nor bound drift. Three anchors are three
recordings; no count of profiles or gates makes them independent replicates, and an
anchor floor belongs to *its* job's condition — it is not the reference condition (that is CR1–CR4's, WP2) and
it is not pooled across jobs.

## What this pass's anchors say

Supported-window values, in mm/s except `zero_fraction` (dimensionless), on the primary
12 s window and the common support 10.138–98.938 mm (49 of the reference window's 50
gates). `spread` and `drift` here are the `mean` statistic; the table carries all five
statistics (`mean`, `median`, `iqr`, `rms`, `zero_fraction`) and all four quantities.

| job | condition (burst / emissions) | B | M | E | drift M−B | drift E−M | spread |
|---|---|---|---|---|---|---|---|
| burst-4 | 4 / 20 | 29.666 | 28.432 | 20.020 | −1.234 | **−8.412** | 9.646 |
| burst-18 | 18 / 20 | 27.636 | 35.126 | 23.146 | **+7.491** | **−11.980** | 11.980 |
| emissions-8 | 10 / 8 | 29.180 | 27.659 | 28.068 | −1.521 | +0.409 | 1.521 |
| emissions-64 | 10 / 64 | 31.018 | 32.504 | 29.675 | +1.486 | −2.829 | 2.829 |
| emissions-128 | 10 / 128 | 30.001 | 28.632 | 31.937 | −1.369 | +3.304 | 3.304 |

Four things follow, and they are what WP3 and WP4 must screen against:

1. **The two job kinds carry floors several-fold apart — 2.9× to 7.9×.** The burst jobs'
   anchor spread is 9.6 and 12.0 mm/s; the emissions jobs' is 1.5, 2.8 and 3.3 mm/s.
   The smallest burst floor (9.646, `burst-4`) is 2.9× the largest emissions floor
   (3.304, `emissions-128`), and the largest burst floor (11.980, `burst-18`) is 7.9×
   the smallest emissions floor (1.521, `emissions-8`). Any contrast measured inside a
   burst job is therefore screened against roughly 10 mm/s of its own anchor movement
   before a pitch or burst effect may be claimed, while the emissions ladder is compared
   against ~1.5–3.3 mm/s.
2. **`burst-4` and `burst-18` differ in kind, not only in size.** `burst-4`'s anchors
   fall monotonically: `E - B = -9.646` and the spread is the same 9.646, i.e. the
   whole range is the drift. `burst-18`'s rise then fall (+7.491, then −11.980), so its
   spread (11.980) *is not* its whole-job drift (−4.490): it turns inside the job. A
   single scalar would have reported both jobs as "about 10 mm/s of movement".
3. **The level moves far more than the robust spread does.** The mean drifts above are
   mirrored by `rms` (9.63 and 10.79 mm/s of range) but not by `iqr`, whose range is
   4.17 and 1.41 mm/s, and `zero_fraction` moves by at most 0.0034 (0.34 %). The rig's
   *velocity level* is what drifts between these recordings; the within-window width
   and the payload's liveness barely move. Note also the scale: a single gate's
   interquartile range over a 12 s window is ~24–29 mm/s, much wider than any of the
   differences above — these floors compare gate *means*, and no distributional claim
   may be read off them.
4. **The emissions jobs are quiet but not identical**, and their `end` anchor is not a
   symmetric bracket: in each of them the designated measurement sits between `begin`
   and `mid`, and `end` reports the drift afterwards. `emissions-64` and
   `emissions-128` show the largest `iqr` movement of the five jobs (2.19 and
   4.81 mm/s), so the emissions slice must report the spread statistic it uses.

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
| burst-4 | 93.21 s | 62.69 s | 30.52 s | 6.10 s |
| burst-18 | 93.26 s | 62.71 s | 30.55 s | 6.11 s |
| emissions-8 | 77.24 s | 50.21 s | 27.03 s | 6.76 s |
| emissions-64 | 77.18 s | 50.16 s | 27.02 s | 6.76 s |
| emissions-128 | 77.06 s | 50.05 s | 27.02 s | 6.76 s |

The bracketed rows, with their residuals against each bracketing anchor (`mean`
statistic, per gate, then the unweighted mean over the 49 supported gates):

| job | row | bracket | vs left (mm/s) | vs right (mm/s) | worst gate |
|---|---|---|---|---|---|
| burst-4 | cc1 | begin → mid | not computed: another pitch (WP3) | — | — |
| burst-4 | cc3 | mid → end | not computed: another pitch (WP3) | — | — |
| burst-18 | cc2 | begin → mid | not computed: another pitch (WP3) | — | — |
| burst-18 | cc4 | mid → end | not computed: another pitch (WP3) | — | — |
| emissions-8 | e8 | begin → mid | −2.213 | −0.691 | 18.063 @ 61.94 mm |
| emissions-64 | e64 | begin → mid | −0.055 | −1.540 | 9.227 @ 82.29 mm |
| emissions-128 | e128 | begin → mid | **+3.327** | **+4.696** | 14.642 @ 76.74 mm |

Two cautions this table exists to make visible. First, the depth-averaged residual is
small (−2.2 to +4.7 mm/s) while the *largest per-gate* residual is 9.2–18.1 mm/s: a
depth-averaged comparison hides local structure, and WP4 must report depth-resolved
differences beside its scalars. Second, `e128`'s residual is positive against **both**
anchors, i.e. the row is above the whole bracket, not inside it — recorded as an
observation, not as an emissions effect, and exactly the kind of statement WP4's
screening must make before claiming the axis moved.

The burst jobs' `cc1`/`cc2`/`cc3`/`cc4` rows are reported with their bracket and their
own scalars but **no residual**: they are recorded at another pitch, so their gates are
not the anchors' gates, and the comparison belongs to WP3's cross-pitch alignment on
common knots no finer than 2.96 mm.

## Artefacts

| file | what it is |
|---|---|
| [`anchor-floor.csv`](anchor-floor.csv) | 100 rows: one per job x statistic (5) x quantity (4), each carrying the three anchor values and the derived value |
| [`anchor-floor.json`](anchor-floor.json) | the definitions of every statistic and quantity, the anchor labels and their `sweep_id`s, the per-job drift/spread and depth-resolved levels and drifts, the bracketed rows, the job-time accounting, the scope caveats and the gate |
| `figures/anchor-<job>.png` | one figure per job: the three anchor `mean` profiles against depth, and below them the two signed drifts with the spread beside them |
| this document | the reading of the numbers, including the four consequences and the two cautions above |

## What is checked before a floor is published

The command refuses (non-zero exit, named reason, nothing written) when the frozen WP0
ingest refuses — a point the table rejected is never measured — and when a job does not
carry exactly three anchors on one native grid, an anchor is not the reference window,
an anchor's decoded condition is not its job's, a scientific row has no anchor pair
bracketing it, or the anchors' `sweep_id`s differ. The gate then holds only when all
fourteen structural checks pass: five jobs, three anchors each, the reference window,
`B ... E` bracketing, one sweep per job, agreeing grids, one shared supported-gate
count, drift and spread distinct and recomputable, a complete derived table, complete
brackets, both residual extremes present where the grid matches and absent where it does
not, the cross-pitch rows carrying no residual, the job-time accounting non-negative, and
the primary window and support the WP0 ones.

## What is deliberately not here

- **No reference-condition statement.** The anchors are not reference realizations; the
  between-run reference floor is WP2's, from CR1–CR4.
- **No interaction and no axis effect.** The pitch x burst interaction is WP3's, using
  these floors; the emissions ladder is WP4's, using these floors plus WP2's.
- **No temporal spectra.** The 12 s primary window is the exposure here; the retained
  surplus and the achieved timestamps are WP4's business.
- **No change to the frozen WP0 artefacts.** This slice adds documents beside them and
  reads the recordings through the same loader, so window, support and per-gate
  statistics are the table's own.
