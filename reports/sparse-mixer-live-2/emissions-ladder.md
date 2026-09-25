# WP4 — the emissions ladder, and its temporal cost

**Status:** WP4 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md)
§4. Generated against the revision `8626de9`, the revision
`emissions-ladder.json` records. Regenerate with

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-emissions-ladder \
    --analysis-commit 8626de9
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
| E8 | 8 | e8 | emissions-8 | 1 | 4.455 | within-job anchor spread over the job's three block-local anchors |
| E20 | 20 | cr1, cr2, cr3, cr4 | common-reference-1, common-reference-2, common-reference-3, common-reference-4 | 4 | 2.344 | between-run spread over the level's four runs |
| E64 | 64 | e64 | emissions-64 | 1 | 0.634 | within-job anchor spread over the job's three block-local anchors |
| E128 | 128 | e128 | emissions-128 | 1 | 1.590 | within-job anchor spread over the job's three block-local anchors |

E20 is the only level this pass observes in **more than one run**: it is the four
common-reference recordings (`cr1`..`cr4`, decoded burst 10 / emissions 20, one per reference
job), and its stated variation is the **spread of those four runs** — between-run variation,
which is WP2's own data. E8, E64 and E128 are **one scientific recording each** (`e8`, `e64`,
`e128`) inside their own job's three **block-local anchor controls**, and their stated
variation is that job's own anchor spread: a within-job bracketing context, not replication
of the level. No averaged E20 profile exists anywhere in this slice: four runs are four, and
pooling them would destroy exactly the variation this slice has to state.

The ladder reads, in the reduction the floors are stated in
(depth-averaged window mean, then each level's own variation): E8 (4.455 mm/s within-job anchor spread) -> E20 (2.344 mm/s between-run spread) -> E64 (0.634 mm/s within-job anchor spread) -> E128 (1.590 mm/s within-job anchor spread).

## View 1 — the velocity estimate on the primary window

Depth-averaged statistics of the 12 s primary window on the common support,
in mm/s except `zero_fraction` (dimensionless), one row per record:

| level | record | mean | median | iqr | rms | zero_fraction |
|---|---|---|---|---|---|---|
| E8 | e8 | 26.042 | 25.706 | 28.262 | 40.341 | 0.0085 |
| E20 | cr1 | 21.019 | 20.926 | 26.972 | 34.658 | 0.0090 |
| E20 | cr2 | 23.363 | 23.482 | 25.620 | 35.283 | 0.0085 |
| E20 | cr3 | 22.597 | 22.106 | 24.348 | 34.689 | 0.0077 |
| E20 | cr4 | 21.268 | 20.398 | 29.693 | 36.175 | 0.0094 |
| E64 | e64 | 23.322 | 22.659 | 26.111 | 33.957 | 0.0100 |
| E128 | e128 | 24.938 | 24.612 | 23.679 | 36.187 | 0.0083 |

The within-window width (`iqr`) and the payload's liveness (`zero_fraction`) move far less
than the level does, and the robust width is smallest at E64 and E128
(26.111 and 23.679 mm/s) against
E20's 24.348-
29.693 mm/s: a
5-10 % narrower per-gate spread at the two highest levels, beside a depth-averaged level that
moved by +2.304 to
+2.054 mm/s (E64 against the
four E20 runs). One recording per level is one realization: the narrowing is an observed
difference between these recordings and is not resolved as an emissions effect.

### The consecutive-level differences, depth-resolved

Every difference is a signed per-gate difference of window-mean profiles on the common
support, one row per pair of records — so a step with E20 in it carries **four** rows, one
per reference run, and no averaged E20 profile:

| step | left | right | mean [mm/s] | extreme signed | extreme abs | at depth [mm] | knots positive |
|---|---|---|---|---|---|---|---|
| E8->E20 | e8 | cr1 | +5.023 | +28.837 | 28.837 | 45.288 | 26/49 |
| E8->E20 | e8 | cr2 | +2.679 | +30.433 | 30.433 | 48.988 | 27/49 |
| E8->E20 | e8 | cr3 | +3.445 | +25.360 | 25.360 | 63.788 | 28/49 |
| E8->E20 | e8 | cr4 | +4.774 | +26.104 | 26.104 | 48.988 | 28/49 |
| E20->E64 | cr1 | e64 | -2.304 | -10.186 | 10.186 | 89.688 | 18/49 |
| E20->E64 | cr2 | e64 | +0.040 | -7.518 | 7.518 | 93.388 | 30/49 |
| E20->E64 | cr3 | e64 | -0.726 | -9.570 | 9.570 | 17.538 | 21/49 |
| E20->E64 | cr4 | e64 | -2.054 | -11.482 | 11.482 | 17.538 | 19/49 |
| E64->E128 | e64 | e128 | -1.615 | -10.748 | 10.748 | 78.588 | 12/49 |

Each step's own reduction, its extreme taken over every difference that realizes it:

| step | differences | mean range [mm/s] | extreme signed | extreme abs | at depth [mm] | realized by |
|---|---|---|---|---|---|---|
| E8->E20 | 4 | +2.679 .. +5.023 | +30.433 | 30.433 | 48.988 | e8 - cr2 |
| E20->E64 | 4 | -2.304 .. +0.040 | -11.482 | 11.482 | 17.538 | cr4 - e64 |
| E64->E128 | 1 | -1.615 .. -1.615 | -10.748 | 10.748 | 78.588 | e64 - e128 |

Two readings follow, and they are the ones the numbers support:

1. **The depth-averaged steps, each read against the campaign's own between-run endpoint.**
   The reference endpoint is 2.344 mm/s, and the three steps do
   not sit with it in the same way:
   - *E8->E20*: the step's means span +2.679 to
     +5.023 mm/s (spread
     2.344 mm/s, which is
     the E20 level's own run-to-run spread, because a constant offset cannot change a spread),
     so **E8 sits inside the spread the four E20 runs show between themselves**.
   - *E20->E64*: the step's means span -2.304 to
     +0.040 mm/s. That span straddles the
     2.344 mm/s reference floor, so **some of the four E20
     realizations put the difference above it and some below it**: which realization E20 is taken
     as decides the answer. E64 therefore reads as *suggestive against E20 and unresolved by this
     pass*, not as sitting inside the pass's baseline variation.
   - *E64->E128*: -1.615 mm/s, which lies **within** the
     2.344 mm/s reference floor.
   Screening outcomes, not proofs of an axis effect.
2. **The per-gate extremes are the larger numbers, and they are what the depth-resolved
   endpoint screens.** The depth-resolved endpoint is
   14.201 mm/s at 24.938 mm; the
   step extremes reach 30.433,
   11.482 and 10.748 mm/s. A
   depth-averaged comparison hides local structure, which is why both views are published.

### The scientific rows inside their anchors

Each single-recording level against **each** of its two bracketing anchors
(`ctrl-begin`, `ctrl-mid`; `ctrl-end` reports the drift that follows the row and does not
bracket it symmetrically). The pass carries no per-recording clock, so a row is reported
against each bracketing anchor rather than at an invented instant — those two residuals
span every linear interpolation over the bracket:

| level | record | anchor | residual mean [mm/s] | extreme signed | extreme abs | at depth [mm] | job's own anchor floor |
|---|---|---|---|---|---|---|---|
| E8 | e8 | ctrl-begin | +7.429 | +21.997 | 21.997 | 54.538 | 4.455 |
| E8 | e8 | ctrl-mid | +2.974 | +21.714 | 21.714 | 48.988 | 4.455 |
| E64 | e64 | ctrl-begin | -1.437 | -11.092 | 11.092 | 32.338 | 0.634 |
| E64 | e64 | ctrl-mid | -2.072 | -12.042 | 12.042 | 71.188 | 0.634 |
| E128 | e128 | ctrl-begin | -1.507 | -6.571 | 6.571 | 48.988 | 1.590 |
| E128 | e128 | ctrl-mid | -0.167 | +9.573 | 9.573 | 45.288 | 1.590 |

## The `e128` observation, examined depth-resolved

WP1 reported that `e128` sits larger than both of its bracketing anchors in the
depth-averaged mean. Recomputed here: -1.507 mm/s against
`ctrl-begin` and -0.167 mm/s against `ctrl-mid`, with the
largest per-gate residual -6.571 mm/s at
48.988 mm (against `ctrl-begin`) and
+9.573 mm/s at 45.288 mm (against
`ctrl-mid`). Depth-resolved, it is 15 of 49 knots with
the same sign against `ctrl-begin` and 21 of 49 against
`ctrl-mid`; the longest contiguous same-sign run is
7 knots spanning
54.538-65.638 mm
against `ctrl-begin` and 20 knots spanning
34.188-69.338 mm
against `ctrl-mid`; the same-sign region around the extreme is
10.138-
52.688 mm, and the three largest knots carry
12.6 % of the summed absolute residual. So
the sign is carried over a substantial contiguous depth region rather than by one gate, and
it is that region - not a single knot - that raises the depth-averaged mean.

**It is not evidence that E128 caused a change.** The residual is a difference between
**one** realization and **two** anchors; it is of the same size as the floors this pass owns
rather than far outside them (0.948 and
0.105 of the emissions-128 job's own anchor spread of
1.590 mm/s, and 0.463 and
0.674 of WP2's depth-resolved endpoint of
14.201 mm/s); and the emissions axis is one realization per
level except at E20, so no count of profiles or gates makes the comparison replicated. It is
an observation to carry forward, not a level effect.

## View 2 — the temporal cost of each level

Every number below is measured on the **full retained record** from that file's own stored
per-profile time array. The achieved period is the median of the successive differences of
that array; the mean is published beside it:

| level | record | profiles | record [s] | median period [ms] | mean period [ms] | rate [Hz] | Nyquist [Hz] | resolution [Hz] | fixed overhead [ms] | internal emission [ms] | transfer [ms] | blocks | profiles/block | range |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E8 | e8 | 826 | 12.5346 | 15.200 | 15.193 | 65.789 | 32.895 | 0.0798 | 10.400 | 9.600 | 0.800 | 6 | 132 | 131-132 |
| E20 | cr1 | 560 | 12.5179 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0799 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
| E20 | cr2 | 562 | 12.5627 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0796 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
| E20 | cr3 | 561 | 12.5403 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0797 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
| E20 | cr4 | 560 | 12.5179 | 22.400 | 22.393 | 44.643 | 22.321 | 0.0799 | 10.400 | 9.600 | 0.800 | 6 | 89 | 89-90 |
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
(0.0798 to
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
| e8 | E8 | 21.238 | 0.857 | 7 | 0.106 | 36.902 | 23.794 |
| e8 | E8 | 48.988 | 0.747 | 4 | 0.061 | 59.569 | 19.451 |
| e8 | E8 | 76.738 | 0.651 | 8 | 0.122 | 7.699 | 25.053 |
| cr1 | E20 | 21.238 | 0.799 | 3 | 0.067 | 45.783 | 23.194 |
| cr1 | E20 | 48.988 | 0.874 | 5 | 0.112 | 31.361 | 23.339 |
| cr1 | E20 | 76.738 | 0.699 | 4 | 0.090 | 19.151 | 16.773 |
| cr2 | E20 | 21.238 | 0.729 | 3 | 0.067 | 51.436 | 20.764 |
| cr2 | E20 | 48.988 | 0.865 | 6 | 0.134 | 30.902 | 22.947 |
| cr2 | E20 | 76.738 | 0.659 | 3 | 0.067 | 24.626 | 13.984 |
| cr3 | E20 | 21.238 | 0.794 | 3 | 0.067 | 43.963 | 20.093 |
| cr3 | E20 | 48.988 | 0.866 | 5 | 0.112 | 40.013 | 21.309 |
| cr3 | E20 | 76.738 | 0.676 | 4 | 0.090 | 20.325 | 15.825 |
| cr4 | E20 | 21.238 | 0.786 | 4 | 0.090 | 39.111 | 21.904 |
| cr4 | E20 | 48.988 | 0.899 | 6 | 0.134 | 34.287 | 27.901 |
| cr4 | E20 | 76.738 | 0.808 | 12 | 0.269 | 18.910 | 23.444 |
| e64 | E64 | 21.238 | 0.577 | 2 | 0.098 | 48.585 | 19.333 |
| e64 | E64 | 48.988 | 0.801 | 4 | 0.195 | 34.074 | 20.671 |
| e64 | E64 | 76.738 | 0.781 | 4 | 0.195 | 18.742 | 14.210 |
| e128 | E128 | 21.238 | 0.497 | 1 | 0.087 | 48.151 | 18.872 |
| e128 | E128 | 48.988 | 0.593 | 2 | 0.174 | 35.561 | 20.276 |
| e128 | E128 | 76.738 | 0.483 | 1 | 0.087 | 28.353 | 12.650 |

Two readings, reported independently because they answer different questions. *In physical
time*, the correlation at these gates survives **longer** at the higher levels than at the
lowest: the first lag below half is
0.106 s at e8
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
7 profiles at
e8 against
1 at e128, i.e. fewer
profiles when each profile covers more time. The two are consequences of the same grid
difference read in two different units, and are published as two readings rather than as one
ordering that "reverses". Both are one record per series (E20's four runs are the only level
with repeats) at the three stated gates, so neither is a replication statement.

## The floors, and which endpoint applies where

| floor | published [mm/s] | recomputed [mm/s] | at depth [mm] | endpoint | applies to |
|---|---|---|---|---|---|
| reference_depth_resolved | 14.201 | 14.201 | 24.938 | depth-resolved: one per-gate difference array, or its extreme | every depth-resolved comparison on the common support - each per-gate difference and each per-gate extreme of this slice |
| reference_depth_averaged | 2.344 | 2.344 | - | depth-averaged: one unweighted mean over the supported gates - the same reduction WP1's per-job floors use | every depth-averaged comparison between two levels - the three ladder steps' mean differences - and the only endpoint like for like with WP1's per-job anchor floors |
| job_anchors_e8 | 4.455 | 4.455 | - | depth-averaged spread: max - min over the job's three block-local anchors of the unweighted mean over the supported gates | the residual of 'e8' against each of its two bracketing anchors, which is a comparison inside one job |
| job_anchors_e64 | 0.634 | 0.634 | - | depth-averaged spread: max - min over the job's three block-local anchors of the unweighted mean over the supported gates | the residual of 'e64' against each of its two bracketing anchors, which is a comparison inside one job |
| job_anchors_e128 | 1.590 | 1.590 | - | depth-averaged spread: max - min over the job's three block-local anchors of the unweighted mean over the supported gates | the residual of 'e128' against each of its two bracketing anchors, which is a comparison inside one job |

The published values are WP1's and WP2's; the recomputed ones are the same reductions
rebuilt here from the recordings, and the two agree within the three decimals the earlier
slices published
(tolerance 0.001 mm/s). Three rules, never mixed:

- a **per-gate difference array or its extreme** is screened against the depth-resolved
  endpoint, 14.201 mm/s at
  24.938 mm;
- a **depth-averaged difference** (one unweighted mean over the supported gates) is screened
  against the depth-averaged endpoint, 2.344 mm/s, which is
  the only endpoint like for like with WP1's per-job floors;
- a **residual inside one job** is screened against that job's own anchor spread:
  1.590 mm/s (emissions-128) / 0.634 mm/s (emissions-64) / 4.455 mm/s (emissions-8).

All five are observed differences over a handful of recordings: they screen, they do not
bound drift, and they are not confidence intervals.

## What the WP4 gate asks, and what the evidence answers

1. **Do E64/E128 materially improve the velocity estimate over E20?** The depth-averaged
   differences are -2.304 to
   +0.040 mm/s across the four E20 runs, and the E64->E128
   difference is -1.615 mm/s; the per-gate iqr is 5-10 %
   narrower at E64/E128. Both are of the order of the campaign's own four-run spread, and
   each level is one recording: the pass does not resolve a material improvement, and this
   slice says so rather than naming a winner.
2. **Does E8 lose useful estimator stability?** It has the smallest within-job anchor spread
   of the ladder (4.455 mm/s), the highest profile rate
   (65.789 Hz) and, at the gates measured, the shortest
   physical correlation time of the four levels
   (0.106 s, i.e. its series decorrelates fastest in seconds and slowest in profiles); nothing measured here shows E8's estimate degrading against E20's.
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
