# WP4 — the emissions ladder, and its temporal cost

**Status:** WP4 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md)
§4. Generated against the revision `28cd7e3`, the revision
`emissions-ladder.json` records. Regenerate with

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-emissions-ladder \
    --analysis-commit 28cd7e3
```

**What it measures.** Four emissions-per-profile levels — E8, E20, E64 and E128 — at the
**reference spatial window** (50 gates x 1.85 mm),
on the common physical support 10.138-98.938 mm, in two
views that are kept apart: the **velocity-estimate stability** on the pass's designed
primary window (12 s), and the **temporal cost** on the full retained record
from each file's achieved timestamps. The levels differ by a factor of 5.7 in profile rate,
so every temporal statement is drawn on each file's own grid, and every segment compared
between levels has one shared physical *duration*.

**The evidence is unequal, and the table below is that fact rather than a summary of it.**

| level | emissions | records | jobs | records | stated variation [mm/s] | variation from |
|---|---|---|---|---|---|---|
| E8 | 8 | e8 | emissions-8 | 1 | 1.521 | within-job anchor spread over the job's three block-local anchors |
| E20 | 20 | cr1, cr2, cr3, cr4 | common-reference-1, common-reference-2, common-reference-3, common-reference-4 | 4 | 4.235 | between-run spread over the level's four runs |
| E64 | 64 | e64 | emissions-64 | 1 | 2.829 | within-job anchor spread over the job's three block-local anchors |
| E128 | 128 | e128 | emissions-128 | 1 | 3.304 | within-job anchor spread over the job's three block-local anchors |

E20 is the only level this pass observes in **more than one run**: it is the four
common-reference recordings (`cr1`..`cr4`, decoded burst 10 / emissions 20, one per reference
job), and its stated variation is the **spread of those four runs** — between-run variation,
which is WP2's own data. E8, E64 and E128 are **one scientific recording each** (`e8`, `e64`,
`e128`) inside their own job's three **block-local anchor controls**, and their stated
variation is that job's own anchor spread: a within-job bracketing context, not replication
of the level. No averaged E20 profile exists anywhere in this slice: four runs are four, and
pooling them would destroy exactly the variation this slice has to state.

The ladder reads, in the reduction the floors are stated in
(depth-averaged window mean, then each level's own variation): E8 (1.521 mm/s within-job anchor spread) -> E20 (4.235 mm/s between-run spread) -> E64 (2.829 mm/s within-job anchor spread) -> E128 (3.304 mm/s within-job anchor spread).

## View 1 — the velocity estimate on the primary window

Depth-averaged statistics of the 12 s primary window on the common support,
in mm/s except `zero_fraction` (dimensionless), one row per record:

| level | record | mean | median | iqr | rms | zero_fraction |
|---|---|---|---|---|---|---|
| E8 | e8 | 26.967 | 26.210 | 26.480 | 38.002 | 0.0118 |
| E20 | cr1 | 27.681 | 27.328 | 26.597 | 39.421 | 0.0097 |
| E20 | cr2 | 26.426 | 26.320 | 27.654 | 37.918 | 0.0106 |
| E20 | cr3 | 28.794 | 28.016 | 27.561 | 39.597 | 0.0101 |
| E20 | cr4 | 24.559 | 24.158 | 26.253 | 35.726 | 0.0107 |
| E64 | e64 | 30.964 | 30.953 | 24.907 | 40.268 | 0.0061 |
| E128 | e128 | 33.328 | 33.165 | 25.116 | 42.463 | 0.0062 |

The within-window width (`iqr`) and the payload's liveness (`zero_fraction`) move far less
than the level does, and the robust width is smallest at E64 and E128
(24.907 and 25.116 mm/s) against
E20's 26.253-
27.654 mm/s: a
5-10 % narrower per-gate spread at the two highest levels, beside a depth-averaged level that
moved by +3.282 to
+6.405 mm/s (E64 against the
four E20 runs). One recording per level is one realization: the narrowing is an observed
difference between these recordings and is not resolved as an emissions effect.

### The consecutive-level differences, depth-resolved

Every difference is a signed per-gate difference of window-mean profiles on the common
support, one row per pair of records — so a step with E20 in it carries **four** rows, one
per reference run, and no averaged E20 profile:

| step | left | right | mean [mm/s] | extreme signed | extreme abs | at depth [mm] | knots positive |
|---|---|---|---|---|---|---|---|
| E8->E20 | e8 | cr1 | -0.714 | -10.148 | 10.148 | 65.638 | 23/49 |
| E8->E20 | e8 | cr2 | +0.541 | -12.778 | 12.778 | 65.638 | 30/49 |
| E8->E20 | e8 | cr3 | -1.827 | -9.949 | 9.949 | 63.788 | 17/49 |
| E8->E20 | e8 | cr4 | +2.408 | +16.179 | 16.179 | 21.238 | 32/49 |
| E20->E64 | cr1 | e64 | -3.282 | -14.837 | 14.837 | 82.288 | 17/49 |
| E20->E64 | cr2 | e64 | -4.537 | -16.969 | 16.969 | 82.288 | 8/49 |
| E20->E64 | cr3 | e64 | -2.170 | -14.861 | 14.861 | 82.288 | 17/49 |
| E20->E64 | cr4 | e64 | -6.405 | -17.504 | 17.504 | 19.388 | 8/49 |
| E64->E128 | e64 | e128 | -2.365 | -14.069 | 14.069 | 58.238 | 19/49 |

Each step's own reduction, its extreme taken over every difference that realizes it:

| step | differences | mean range [mm/s] | extreme signed | extreme abs | at depth [mm] | realized by |
|---|---|---|---|---|---|---|
| E8->E20 | 4 | -1.827 .. +2.408 | +16.179 | 16.179 | 21.238 | e8 - cr4 |
| E20->E64 | 4 | -6.405 .. -2.170 | -17.504 | 17.504 | 19.388 | cr4 - e64 |
| E64->E128 | 1 | -2.365 .. -2.365 | -14.069 | 14.069 | 58.238 | e64 - e128 |

Two readings follow, and they are the ones the numbers support:

1. **The depth-averaged steps, each read against the campaign's own between-run endpoint.**
   The reference endpoint is 4.235 mm/s, and the three steps do
   not sit with it in the same way:
   - *E8->E20*: the step's means span -1.827 to
     +2.408 mm/s (spread
     4.235 mm/s, which is
     the E20 level's own run-to-run spread, because a constant offset cannot change a spread),
     so **E8 sits inside the spread the four E20 runs show between themselves**.
   - *E20->E64*: the step's means span -6.405 to
     -2.170 mm/s. That span straddles the
     4.235 mm/s reference floor, so **some of the four E20
     realizations put the difference above it and some below it**: which realization E20 is taken
     as decides the answer. E64 therefore reads as *suggestive against E20 and unresolved by this
     pass*, not as sitting inside the pass's baseline variation.
   - *E64->E128*: -2.365 mm/s, which lies **within** the
     4.235 mm/s reference floor.
   Screening outcomes, not proofs of an axis effect.
2. **The per-gate extremes are the larger numbers, and they are what the depth-resolved
   endpoint screens.** The depth-resolved endpoint is
   14.603 mm/s at 21.238 mm; the
   step extremes reach 16.179,
   17.504 and 14.069 mm/s. A
   depth-averaged comparison hides local structure, which is why both views are published.

### The scientific rows inside their anchors

Each single-recording level against **each** of its two bracketing anchors
(`ctrl-begin`, `ctrl-mid`; `ctrl-end` reports the drift that follows the row and does not
bracket it symmetrically). The pass carries no per-recording clock, so a row is reported
against each bracketing anchor rather than at an invented instant — those two residuals
span every linear interpolation over the bracket:

| level | record | anchor | residual mean [mm/s] | extreme signed | extreme abs | at depth [mm] | job's own anchor floor |
|---|---|---|---|---|---|---|---|
| E8 | e8 | ctrl-begin | -2.213 | -18.063 | 18.063 | 61.938 | 1.521 |
| E8 | e8 | ctrl-mid | -0.691 | -10.981 | 10.981 | 63.788 | 1.521 |
| E64 | e64 | ctrl-begin | -0.055 | +9.227 | 9.227 | 82.288 | 2.829 |
| E64 | e64 | ctrl-mid | -1.540 | -7.000 | 7.000 | 52.688 | 2.829 |
| E128 | e128 | ctrl-begin | +3.327 | +14.642 | 14.642 | 76.738 | 3.304 |
| E128 | e128 | ctrl-mid | +4.696 | +14.372 | 14.372 | 52.688 | 3.304 |

## The `e128` observation, examined depth-resolved

WP1 reported that `e128` sits larger than both of its bracketing anchors in the
depth-averaged mean. Recomputed here: +3.327 mm/s against
`ctrl-begin` and +4.696 mm/s against `ctrl-mid`, with the
largest per-gate residual +14.642 mm/s at
76.738 mm (against `ctrl-begin`) and
+14.372 mm/s at 52.688 mm (against
`ctrl-mid`). Depth-resolved, it is 35 of 49 knots with
the same sign against `ctrl-begin` and 37 of 49 against
`ctrl-mid`; the longest contiguous same-sign run is
25 knots spanning
10.138-54.538 mm
against `ctrl-begin` and 30 knots spanning
13.838-67.488 mm
against `ctrl-mid`; the same-sign region around the extreme is
71.188-
85.988 mm, and the three largest knots carry
14.6 % of the summed absolute residual. So
the sign is carried over a substantial contiguous depth region rather than by one gate, and
it is that region - not a single knot - that raises the depth-averaged mean.

**It is not evidence that E128 caused a change.** The residual is a difference between
**one** realization and **two** anchors; it is of the same size as the floors this pass owns
rather than far outside them (1.007 and
1.421 of the emissions-128 job's own anchor spread of
3.304 mm/s, and 1.003 and
0.984 of WP2's depth-resolved endpoint of
14.603 mm/s); and the emissions axis is one realization per
level except at E20, so no count of profiles or gates makes the comparison replicated. It is
an observation to carry forward, not a level effect.

## View 2 — the temporal cost of each level

Every number below is measured on the **full retained record** from that file's own stored
per-profile time array. The achieved period is the median of the successive differences of
that array; the mean is published beside it:

| level | record | profiles | record [s] | median period [ms] | mean period [ms] | rate [Hz] | Nyquist [Hz] | resolution [Hz] | fixed overhead [ms] | internal emission [ms] | transfer [ms] | blocks | profiles/block | range |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E8 | e8 | 828 | 12.5648 | 15.200 | 15.193 | 65.789 | 32.895 | 0.0796 | 10.400 | 9.600 | 0.800 | 6 | 132 | 131-132 |
| E20 | cr1 | 561 | 12.5403 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0797 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
| E20 | cr2 | 562 | 12.5626 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0796 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
| E20 | cr3 | 561 | 12.5403 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0797 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
| E20 | cr4 | 561 | 12.5402 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0797 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
| E64 | e64 | 257 | 12.4911 | 48.800 | 48.793 | 20.492 | 10.246 | 0.0801 | 10.400 | 9.600 | 0.800 | 6 | 41 | 41-41 |
| E128 | e128 | 145 | 12.5559 | 87.200 | 87.194 | 11.468 | 5.734 | 0.0796 | 10.400 | 9.600 | 0.800 | 6 | 23 | 23-23 |

The four levels' achieved grids fall by a factor of 5.7 in rate from E8 to E128
(65.789 Hz against
11.468 Hz), so the Nyquist frequency falls with them
(32.895 Hz against
5.734 Hz) and the profiles in one
2 s block fall with them too
(132 at e8 against
23 at e128): that is the bandwidth price of higher
emissions, and it is a grid property rather than a change in the estimate. The frequency
resolution is essentially the same at every level
(0.0796 to
0.0801 Hz), because every record retains
about 12.5 s: the ladder's temporal cost lies in the *rate*, not in the resolution. The
**fixed profile overhead** (`achieved - emissions x PRF`, the *intercept* of the period and
not the transfer term) is 10.400 ms at every level,
composed of 9.600 ms of internal emission - the 16
PRF terms the manual's law carries, 16 x
600 us - and
0.800 ms of transfer term proper.

### The request's expected periods, beside this pass's measurements

| level | expected period [ms] | expected rate [Hz] | measured period [ms] | measured rate [Hz] | difference [ms] | difference [Hz] | agrees |
|---|---|---|---|---|---|---|---|
| E8 | 15.2 | 65.8 | 15.200 | 65.789 | +0.0000 | -0.011 | yes |
| E20 | 22.4 | 44.7 | 22.400 | 44.643 | -0.0000 | -0.057 | yes |
| E64 | 48.8 | 20.5 | 48.800 | 20.492 | -0.0000 | -0.008 | yes |
| E128 | 87.2 | 11.5 | 87.200 | 11.468 | +0.0000 | -0.032 | yes |

The expected numbers are the WP4 request's own, stated to three significant figures and
checked here within 0.05 ms and
0.1 Hz. They are checked rather than adopted: the measurement is
this pass's, taken from the stored timestamps, and a disagreement would be published as a
difference.

### The autocorrelation at the three stated depths

The biased normalized autocovariance of the **full** stored series at one native gate, the
same convention the spatial correlation length uses on a gate profile. The three depths are
two the earlier slices named (WP2's endpoint depth 21.238 mm, WP1's `e128` extreme 76.74 mm)
and one mid-support:

| record | level | depth [mm] | lag-1 | first lag below half | at [s] | series mean [mm/s] | series std [mm/s] |
|---|---|---|---|---|---|---|---|
| e8 | E8 | 21.238 | 0.727 | 3 | 0.046 | 59.599 | 20.671 |
| e8 | E8 | 48.988 | 0.680 | 3 | 0.046 | 50.502 | 22.194 |
| e8 | E8 | 76.738 | 0.179 | 1 | 0.015 | 11.678 | 13.386 |
| cr1 | E20 | 21.238 | 0.718 | 3 | 0.067 | 56.368 | 23.094 |
| cr1 | E20 | 48.988 | 0.789 | 3 | 0.067 | 49.681 | 21.286 |
| cr1 | E20 | 76.738 | 0.533 | 2 | 0.045 | 13.126 | 13.767 |
| cr2 | E20 | 21.238 | 0.808 | 3 | 0.067 | 54.234 | 24.361 |
| cr2 | E20 | 48.988 | 0.747 | 3 | 0.067 | 44.609 | 20.034 |
| cr2 | E20 | 76.738 | 0.517 | 2 | 0.045 | 11.620 | 14.439 |
| cr3 | E20 | 21.238 | 0.785 | 3 | 0.067 | 58.531 | 23.573 |
| cr3 | E20 | 48.988 | 0.802 | 4 | 0.090 | 51.905 | 21.996 |
| cr3 | E20 | 76.738 | 0.478 | 1 | 0.022 | 12.783 | 13.027 |
| cr4 | E20 | 21.238 | 0.836 | 5 | 0.112 | 44.137 | 26.522 |
| cr4 | E20 | 48.988 | 0.763 | 3 | 0.067 | 50.858 | 18.174 |
| cr4 | E20 | 76.738 | 0.542 | 2 | 0.045 | 13.334 | 15.505 |
| e64 | E64 | 21.238 | 0.558 | 2 | 0.098 | 60.463 | 19.815 |
| e64 | E64 | 48.988 | 0.590 | 2 | 0.098 | 50.473 | 19.141 |
| e64 | E64 | 76.738 | 0.551 | 2 | 0.098 | 26.043 | 12.449 |
| e128 | E128 | 21.238 | 0.478 | 1 | 0.087 | 57.719 | 20.586 |
| e128 | E128 | 48.988 | 0.549 | 2 | 0.174 | 57.685 | 20.586 |
| e128 | E128 | 76.738 | 0.572 | 2 | 0.174 | 24.607 | 15.617 |

Two readings, reported independently because they answer different questions. *In physical
time*, the correlation at these gates survives **longer** at the higher levels than at the
lowest: the first lag below half is
0.046 s at e8
against
0.087 s at e128, i.e. **slower**
decorrelation in seconds at the higher emissions level - which is what a longer per-profile
acoustic averaging interval predicts, since each E128 profile spans 87.2 ms
against 15.2 ms at E8, so the recorded series is the
smoother and lower-bandwidth one. It is not monotone across the ladder: at this gate E64's
first lag below half is
0.098 s,
**longer** in physical time than E128's
0.087 s, so the readings are
"longer at higher emissions than at the lowest" and not "longer at every step". *In profile lags*, the ordering runs the other way: 
3 profiles at
e8 against
1 at e128, i.e. fewer
profiles when each profile covers more time. The two are consequences of the same grid
difference read in two different units, and are published as two readings rather than as one
ordering that "reverses". Both are one record per series (E20's four runs are the only level
with repeats) at the three stated gates, so neither is a replication statement.

## The floors, and which endpoint applies where

| floor | published [mm/s] | recomputed [mm/s] | at depth [mm] | endpoint | applies to |
|---|---|---|---|---|---|
| reference_depth_resolved | 14.603 | 14.603 | 21.238 | depth-resolved: one per-gate difference array, or its extreme | every depth-resolved comparison on the common support - each per-gate difference and each per-gate extreme of this slice |
| reference_depth_averaged | 4.235 | 4.235 | - | depth-averaged: one unweighted mean over the supported gates - the same reduction WP1's per-job floors use | every depth-averaged comparison between two levels - the three ladder steps' mean differences - and the only endpoint like for like with WP1's per-job anchor floors |
| job_anchors_e8 | 1.521 | 1.521 | - | depth-averaged spread: max - min over the job's three block-local anchors of the unweighted mean over the supported gates | the residual of 'e8' against each of its two bracketing anchors, which is a comparison inside one job |
| job_anchors_e64 | 2.829 | 2.829 | - | depth-averaged spread: max - min over the job's three block-local anchors of the unweighted mean over the supported gates | the residual of 'e64' against each of its two bracketing anchors, which is a comparison inside one job |
| job_anchors_e128 | 3.304 | 3.304 | - | depth-averaged spread: max - min over the job's three block-local anchors of the unweighted mean over the supported gates | the residual of 'e128' against each of its two bracketing anchors, which is a comparison inside one job |

The published values are WP1's and WP2's; the recomputed ones are the same reductions
rebuilt here from the recordings, and the two agree within the three decimals the earlier
slices published
(tolerance 0.001 mm/s). Three rules, never mixed:

- a **per-gate difference array or its extreme** is screened against the depth-resolved
  endpoint, 14.603 mm/s at
  21.238 mm;
- a **depth-averaged difference** (one unweighted mean over the supported gates) is screened
  against the depth-averaged endpoint, 4.235 mm/s, which is
  the only endpoint like for like with WP1's per-job floors;
- a **residual inside one job** is screened against that job's own anchor spread:
  3.304 mm/s (emissions-128) / 2.829 mm/s (emissions-64) / 1.521 mm/s (emissions-8).

All five are observed differences over a handful of recordings: they screen, they do not
bound drift, and they are not confidence intervals.

## What the WP4 gate asks, and what the evidence answers

1. **Do E64/E128 materially improve the velocity estimate over E20?** The depth-averaged
   differences are -6.405 to
   -2.170 mm/s across the four E20 runs, and the E64->E128
   difference is -2.365 mm/s; the per-gate iqr is 5-10 %
   narrower at E64/E128. Both are of the order of the campaign's own four-run spread, and
   each level is one recording: the pass does not resolve a material improvement, and this
   slice says so rather than naming a winner.
2. **Does E8 lose useful estimator stability?** It has the smallest within-job anchor spread
   of the ladder (1.521 mm/s), the highest profile rate
   (65.789 Hz) and, at the gates measured, the shortest
   physical correlation time of the four levels
   (0.046 s, i.e. its series decorrelates fastest in seconds and slowest in profiles); nothing measured here shows E8's estimate degrading against E20's.
3. **What is the bandwidth cost of each level?** The achieved period and profile rate above,
   with the profiles per 2 s block as the concrete price:
   E8 132, E20 89, E64 41, E128 23
   profiles per block (taking one record per level), and the Nyquist frequency falling from
   32.895 Hz at E8 to 5.734 Hz at E128.

## Artefacts

| file | what it is |
|---|---|
| [`emissions-ladder.csv`](emissions-ladder.csv) | five blocks: the level statistics, the consecutive-level differences, the bracketing residuals, the temporal view, the autocorrelation at the stated depths |
| [`emissions-ladder.json`](emissions-ladder.json) | the levels and their evidence, both views depth-resolved, the floors with their endpoints, the request's expected periods beside the measurements, the `e128` observation, the definitions, the gate |
| `figures/emissions-ladder-stability.png` | the stability view: every record's window-mean profile, and every consecutive-level difference with each step's extreme marked and both reference endpoints drawn |
| `figures/emissions-ladder-temporal.png` | the temporal view: the achieved period per record with the expected periods marked, and the autocorrelation at the first stated depth |
| this document | the reading of the numbers, the floors and their endpoints, and the `e128` observation |

## What is checked before a level is published

The command refuses (non-zero exit, named reason, nothing written) when the frozen WP0
ingest refuses, when a level's recording is not the one the ladder declares or decodes to
another condition, window or native grid than its level's, when a record carries no usable
stored per-profile time array (the retired `timing.target_s` is never a substitute for one),
when a job's anchors do not bracket its scientific row, or when a recomputed floor does not
reproduce the published one. The gate then holds only when all 19
structural checks pass, including: four levels at their declared conditions, the declared
evidence counts
(4/1/1/1), E20 kept as four runs with no averaged profile, periods measured from the stored
timestamps and distinguishable from the retired planning law, the physical-duration
segmentation with its block boundaries, the spectral arithmetic, the request's expected
periods reproduced within tolerance, one shared native grid, complete differences and steps,
the bracketing recomputed per single level, and the floors stated with both endpoints. The
`ok` flag is the conjunction of the checks.

## What is deliberately not here

- No causality from single realizations: E8, E64 and E128 are one recording each, so any difference they show from E20 or from their own anchors is an observed difference between recordings, not evidence that the emissions setting caused it
- No plateau, optimum, threshold or separability claim: nothing here establishes that the velocity estimate stops improving at some level, and no comparison is a statistical distinguishability test
- No pooled E20 profile: the four reference runs are published individually and the level's variation is their spread. They are four runs of one condition, not a synthetic reference profile, and a mean of the four would destroy exactly the variation this slice exists to state, so the module computes none
- No new acquisition, no change to the run plan, and no change to the frozen WP0 artefacts, WP1's or WP2's: this slice adds documents beside them and reads every number through the shared loader
- No spectrum, no SNR and no saturation statement: these files carry one axial-velocity channel, so the power spectrum, the noise floor and the receiver gain are outside what this dataset can measure
- No interaction: the pitch x burst corner is WP3's, and its floors are not used here
- No rate of anything: the achieved periods are grid properties of the four levels, and no drift or change is expressed per unit time
