# The sparse pass analysis — work plan

> **Status:** WP0, WP1 and WP2 are **implemented and committed**
> (`analysis/sparse-pass-ingest`); WP3–WP5 are planned here and not started. WP0 was
> reviewed and frozen, with WP1 and WP2 cleared to run in parallel and both landed:
> `<report>/anchor-floor.{csv,json,md}` with a figure per job, and
> `<report>/reference-floor.{csv,json,md}` with its figure. This document stays the
> authority for what the analysis of the mixer-enabled sparse pass measures, in what
> order, and what each step has to establish before the next one may rely on it. It adds no acquisition work: the
> acquisition phase is closed, and it re-opens only if this analysis exposes a real
> problem (`acquisition-closeout-plan.md` §"What runs next", item 4).
>
> **What it reads.** [`../../data/sparse-mixer-live-1/`](../../data/sparse-mixer-live-1/README.md)
> — the mixer-enabled realization of the frozen nine-job design: 26 recordings, nine jobs,
> 16 min 43 s, every point carrying signal — through the WP0 table it produces. The
> zero-signal first pass stays acquisition-qualification evidence and is not analysed here.
>
> **What it produces.** One ingest table, four measurement slices, one decision table. The
> last of them is the Stage-2 recommendation: which axes can be fixed, which interactions
> matter, which levels are redundant, and whether a denser second acquisition is justified
> at all — and if it is, exactly which small set of conditions buys the most information.

## 1. Question this work must answer

The pass was designed to make four things measurable that the historical sweep could not
answer, and to answer them from *this* pass's own evidence rather than from cross-dataset
analogy (the older sweep's
[`decision-table.md`](../../reports/mixer-sensitivity-analysis/decision-table.md) carries
seven `Acquire` rows that this pass now feeds):

| Question | What answers it | Verdict vocabulary |
|---|---|---|
| How much of a difference is *time* rather than the parameter? | the block-local controls (15 recordings) and CR1–CR4 (4 runs of one condition) | a measured floor, stated as an interval, not a p-value |
| Is the pitch × burst interaction real, and how large? | CC1–CC4: 0.617 / 2.96 mm crossed with 4 / 18 cycles, each bracketed by its own controls | `keep` / `defer` / `replace` / `requires diagnostic` |
| What does emissions per profile buy, and at what bandwidth cost? | E8 / E20 (the reference level) / E64 / E128 at the reference window | the same four words |
| Does a denser second pass exist that is worth its instrument time? | all of the above, turned into candidate rows | a named small set, or `no second pass` |

The output is not a ranking of settings. It is an effect-size decision against a measured
floor, plus the statement of which effects the pass *cannot* resolve.

**The floors WP1 and WP2 have now measured**, in the reduction the two share (the
unweighted mean over the common support of the per-gate window mean), so that WP3 and
WP4 screen like for like:

| floor | value | from |
|---|---|---|
| burst-4 anchors | 9.646 mm/s | WP1, drift `E - B` = −9.646, spread 9.646 (monotone) |
| burst-18 anchors | 11.980 mm/s | WP1, spread 11.980; its drift *turns* (+7.491 then −11.980) |
| emissions-8 / 64 / 128 anchors | 1.521 / 2.829 / 3.304 mm/s | WP1, per-job |
| between-run reference | 4.235 mm/s | WP2, `cr3`–`cr4`, depth-averaged endpoint |
| between-run reference, depth-resolved | 14.603 mm/s at 21.238 mm | WP2, the same pair |

Two facts about them that bind the later packages: the burst jobs' own anchor floors are
*larger* than the campaign's between-run reference drift, so a burst contrast smaller
than ~10 mm/s cannot be separated from its own controls; and the between-run floor is not
ordered by elapsed time (the two runs 5.3 minutes apart differ most), so it may not be
read as a rate.

## 2. Facts the implementation must preserve

These are verified properties of this pass's committed bytes
([`reports/sparse-mixer-live-1/`](../../reports/sparse-mixer-live-1/README.md) reproduces
each), not conclusions about the flow:

- all 26 recordings decode as one axial-velocity channel in `mm/s`; no echo or energy
  profile is present, so **no SNR, saturation or receiver-gain statement is available** —
  that is D1's separate capability project;
- the pass's three windows are **co-located**: one physical interval, 10.138 – 98.938 mm,
  sampled at 0.6167 / 1.85 / 2.96 mm. The 1.85 mm window reaches 100.788 mm, so its last
  gate falls outside the common support and 49 of its 50 gates are compared. Cross-window
  comparisons therefore need the support cut, not a re-registration;
- word 14 (emissions) is each job's own; **word 27 is 1 and word 84 is 0 in all 26**; PRF is
  600 µs and sound speed 1480 m/s in all 26; the stored pitch is the ladder's snap of the
  request (0.617 → 0.6166666666666667, the other two exact);
- word 27 is the instrument's option-list **index**, not a length: the index → mm relation
  is medium- and burst-dependent and was only ever measured at one sound speed, so the
  index states no acoustic averaging length — and the **historical sweep's files store 4**
  where this pass's store 1. The two are not the same measurement of a shared setting, and
  no analysis may read them as one. (This pass never swept or set the sampling volume; the
  parameter set lists it as read-back-only, and the index is the only form the instrument
  publishes. `qc-summary.json` `observed_words` is the machine-readable authority for the
  three stored words, with the same caveat in its `note`;)
- the **retained span** is 12.4686 – 12.5888 s for a 12 s request: every recording covers
  the designed exposure **and overruns it**, by 0.47 – 0.59 s. The primary distributional
  window is the **designed** interval — the declared 12 s, 100 nominal 500-RPM revolutions
  — and *not* the 103 revolutions = 12.36 s the files' surplus happens to support: the
  surplus is the acquisition's own stopping latency, and letting it set the analysed
  interval would silently widen the exposure past the design and make this pass's
  distributional numbers incomparable with the declared one. The surplus is kept for the
  full-record view (spectra, autocorrelation), which is where extra duration is an asset
  rather than a change of exposure. `common_window_s()` **refuses** a dataset whose
  shortest recording cannot cover the design, rather than narrowing to a shorter window;
- the achieved period is `emissions × PRF + ~10.37 ms`, measured from the stored
  timestamps. The logs' `timing.target_s` records the **retired** `emissions × PRF + 1 ms`
  expectation the planner used on the day; it is provenance, it is not rewritten, and no
  analysis may take a period from it;
- the planner's own law is 0.21 – 0.22 ms *above* the measured period at every level of
  this pass and in one direction: its transfer term measures ~0.77 ms here, not the 1 ms
  it carries. This moves no recording and is recorded, not corrected;
- the acquisition order is **recoverable** (the plan's step order and each job's key
  order, with the jobs' own wall-clock windows beside them) — unlike the historical
  sweep, where file metadata could not recover order and drift could only be bounded;
- the noise is not white and no profile is an independent replicate: the rig is a mixer,
  the nominal 500-RPM marker (8.33 Hz, one revolution = 0.12 s) is a marker only — these
  files carry no tachometer — and every interval and floor below is a *within-run*
  statement unless it is drawn from separate jobs.

If an implementation contradicts one of these facts, stop and resolve the ingest or the
fixture before producing any scientific output.

## 3. Analysis contract

### 3.1 Two views, and which one each metric uses

1. **Common-duration view** — the WP0 primary window: the pass's **designed exposure**,
   the declared 12 s = 100 nominal 500-RPM revolutions, cut in each recording by its own
   stored timestamps. Every distributional comparison uses it. It is the interval the
   pass asked for; the 0.47 – 0.59 s of retained surplus is not part of it (§2), so a
   later work package that wants the surplus must say so, name the view it is using and
   keep it out of the distributional tables.
2. **Full-record view** — for autocorrelation and spectra. Segments must have one shared
   *duration*, not one shared profile count: the emission levels differ by a factor of
   5.7 in profile rate, so a fixed segment length in profiles would compare 15 ms of one
   file with 87 ms of another. Frequency resolution, Nyquist and the analysed band are
   reported per level, and each level's own achieved timestamps set its grid.

### 3.2 Depth views

- Cross-condition profiles are compared **on the common support** (10.138 – 98.938 mm)
  and on **common depth knots no finer than the coarsest participating pitch** (2.96 mm
  for the pitch axis, 1.85 mm for the burst, emissions and reference axes).
- A finer profile is *sampled* at the coarser knots by its nearest native gate — the
  existing `_native_grid.align_on_knots` discipline. No interpolation, no upsampling:
  resampled coarse data does not become resolved structure.
- Spatial gradients and correlation lengths are computed on each recording's **native**
  grid first, and only then compared.
- Every interpolation/aggregation choice is recorded in the figure caption and the
  artefact's provenance document.

### 3.3 Uncertainty and the replication vocabulary

This pass generates its own floors, and they are of **two different kinds**. Neither is a
confidence interval, and neither is created by counting profiles or gates:

- **Within-job floor** — a scientific job's three **block-local anchor controls**
  (`ctrl-begin`, `ctrl-mid`, `ctrl-end`) record the **reference spatial window** at their
  own job's **anchor condition**: a burst-4 job's controls are burst 4, an emissions-128
  job's are emissions 128, and none of them is a realization of the reference condition.
  They sit at the job's beginning, middle and end with its scientific rows between them,
  so their spread is *short-timescale drift plus measurement repeatability* for that job,
  and it is the floor that job's own contrasts are screened against: a difference measured
  **inside** the job is compared with its own controls' spread, and neither outcome proves
  the parameter caused it. Vocabulary: **anchor** is the controls' own condition,
  **reference** is reserved for the one condition CR1–CR4 record (the recordings
  themselves are what the historical sweep's vocabulary calls the within-run reference
  controls; what is corrected here is calling their condition the reference one).
- **Between-run floor** — CR1–CR4 are four recordings of the one condition observed in
  four distinct runs (burst 10 / emissions 20 / 1.85 mm), spread over the campaign's
  16 min 43 s. Their spread is the *between-run* baseline drift, and it is the floor
  every **cross-job** comparison is screened against.
- An emissions job's four points are repeated measurements **within one run**, not
  run-level replicates: E8's and E64's levels are each one recording per level in one
  job, and the controls around them measure the drift that shares their run.
- Block-bootstrap intervals may describe within-record conditional uncertainty, with a
  block length no shorter than a nominal revolution; they do not create replication.
- Effect sizes are reported relative to the applicable floor, saying only whether they
  fall above or below it. Neither outcome proves causation, and no gate-wise p-value
  family is a primary endpoint.

## 4. Work packages and acceptance gates

### WP0 — the ingest table and the two shared views (implemented, reviewed, frozen)

Deliver: [`reports/sparse-mixer-live-1/points.csv`](../../reports/sparse-mixer-live-1/points.csv)
(one row per recording: identity, order, condition, requested and stored window, decoded
settings, achieved timing from the stored timestamps, retention, signal statistics, and
the provenance of both sides) plus `qc-summary.json`, and the CLI verb that regenerates
both.

Gate (all twelve QC checks hold, and they do on the committed pair): 26 recordings, the
nine jobs' counts, zero decode failures, zero NaNs, monotone timestamps, a live payload
in every recording, retention of the **designed** exposure, a primary window and a common
support, the achieved period inside the planner's law, the retired target present in
every log, and a recorded generator revision.

**The reviewer's steps 1 and 2 are one package here** because the common-support
discipline is a property of the table rather than a later pass over it: the window and
the support are both fixed in the ingest, and every supported metric is computed inside
them on the recording's own native gate grid. They differ in one respect and the
difference is deliberate: the **support is derived** (the intersection of the decoded
depth ranges, which only the files can state), while the **window is declared** (the
pass's designed exposure, which every recording merely has to cover). What remains for
WP3 is the cross-pitch *alignment* (knots at 2.96 mm), which only the pitch axis needs.

### WP1 — within-job drift and measurement repeatability (implemented)

Deliver, per scientific job: the three **block-local anchor controls'** own metrics
(mean/median/IQR/RMS/zero fraction on the primary window and support), their pairwise
differences, the job's scientific rows against the controls that bracket them, and one
figure per job. The floor they produce is *that job's*: a burst-18 job's anchor floor
says nothing about a burst-4 job's, and no anchor floor is a reference-condition result.

Gate: every later contrast states which floor it was screened against (the job's own
control spread for a within-job contrast, the CR floor for a cross-job one) and where in
depth the effect falls, without interpreting either outcome as proof of an axis effect.
Report the controls' **drift** (begin → mid → end) separately from their **spread**: a
monotone drift across a job is a different statement from a scatter, and the pass's
design places the scientific rows between the controls precisely so the two can be told
apart.

### WP2 — the CR1–CR4 reference drift across runs (implemented)

Deliver: CR1–CR4 as four named realizations of one decoded condition — their metrics,
their pairwise depth-resolved differences, their spread and their drift over the campaign
order, with the job windows beside them — plus the **between-run floor** every cross-job
comparison uses, stated with its endpoint and reduction.

Gate: the floor is derived from the four recorded runs only, is stated as an interval
with the reduction that produced it (for example the largest absolute per-depth mean
difference over the common support), and is compared like-for-like with the within-job
floor of WP1 — a comparison the anchor controls' *extra* condition spread must not be
allowed to blur, which is why the two floors are reported side by side rather than
pooled. Report the depth ranges where the four differ most. Do not pool CR1–CR4 into one
"reference" row: the point of four runs is that they are four, and here — and only here —
does the pass observe the reference condition.

### WP3 — the pitch × burst interaction

Deliver: the crossed cells the pass actually recorded — pitch 0.617 / 1.85 / 2.96 mm at
burst 4 and at burst 18, where 1.85 mm comes from each job's own controls and the two
other pitches from CC1/CC3 (burst 4) and CC2/CC4 (burst 18) — each cell's metrics on
common knots, the marginal pitch and burst effects, and the interaction as the
difference-of-differences with a depth-resolved profile of it.

Gate: every cell is screened against the floors of WP1/WP2 before any interaction is
claimed; the interaction's size is reported as an effect, never as a significance test;
the historical burst-10 and reference-pitch evidence is quoted as context only and never
substituted for a crossed cell. If the interaction falls below both floors, say so — that
is the finding, and it is the one that allows the axes to be fixed independently.

### WP4 — emissions per profile: 8, 20, 64, 128

Deliver, per level: mean-profile shape stability, variance/noise reduction, the temporal
bandwidth cost (each level's own grid and analysed band, with the profile rate, Nyquist
and frequency resolution stated), the within-run repeatability (controls), and the
velocity estimate's stability, taking E20 as the reference level.

Gate: every temporal statement uses each file's **achieved timestamps**; the axes are
evaluated on a shared segment *duration*; and the verdict answers the three questions
directly — whether E64/E128 materially improve the velocity estimate over E20, whether E8
loses useful estimator stability, and what the bandwidth cost of each level is. "Material"
means above the applicable floor, and is stated in the axis's own units.

### WP5 — the Stage-2 recommendation

Deliver `reports/sparse-mixer-live-1/decision-table.md`: one row per candidate condition
with existing evidence, the floor it was screened against, the information gained, the
automation needed, a verdict (`keep` / `defer` / `replace` / `requires diagnostic`), and
the measurement that would overturn it — the same seven columns the historical sweep's
table uses, so the two are comparable.

Gate: the table answers, in this order, (1) which axes can be collapsed or fixed, (2)
which interactions matter, (3) which levels are redundant, (4) whether a denser second
acquisition is justified at all, and (5) if it is, the small set of new conditions and
what each one buys. A row may not be retained because the instrument accepts it. D1 stays
outside the table as its own capability project.

## 5. Implementation order and commits

One work package per reviewable slice, and every commit green:

1. **WP0** — `analysis(sparse)` the module and the CLI verb; `data(sparse)` the artefacts
   and the report README, generated against the module commit; `test(sparse)` the tests
   that pin the contract, the two provenance rules and the refusals; `docs(sparse)` this
   plan and the state updates.
2. **WP1, WP2** — the drift slice, then the reference slice. Each is one module, one
   provenance document, one table, one figure, and its own tests. The reference slice
   reads the ingest, not the drift slice, so the two can be reviewed independently.
3. **WP3, WP4** — the interaction and the emissions slices, in that order: the interaction
   needs the floors both earlier slices state, and the emissions slice needs the shared
   segment-duration discipline WP3 does not use.
4. **WP5** — the hand-written decision table, pinned by SHA-256 to the artefacts it reads,
   exactly as the historical sweep's table is.

## 6. Verification commands

```bash
# the ingest and its gate (no instrument needed)
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-inventory --analysis-commit <generator>

# the ingest's own contract, the provenance rules and the refusals
uv run --extra dev pytest -q tests/test_sparse_inventory.py

# the whole suite, the lint and the format, before any slice is offered for review
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
uv run --extra dev ruff format --check src tests
```

## 7. What is deliberately not here

- **D1** — the higher-sensitivity condition with echo/energy information — is a separate
  capability project (a sensitivity write/read path plus an echo recording surface). It
  blocks nothing above, and nothing above may claim an SNR or saturation result without
  it.
- **No acquisition change.** Nothing in this plan re-opens the sweep, the run plan, the
  verifier or the driver. The one acquisition-side number this analysis measures — the
  planner's transfer term on this pass — is recorded in the report README as a
  measurement; acting on it would be an acquisition change with its own justification.
- **No second acquisition** is designed here. WP5 either names the small set that is
  worth acquiring or says that none is.
- The historical sweep's artefacts are **not** regenerated or compared field by field:
  they answer a different design's question, and the only values quoted across the two are
  the floors, each named with the dataset it came from.
