# Mixer sensitivity analysis reports

This directory is the reviewer-visible output contract for
[`docs/dop3000/existing-sweep-analysis-plan.md`](../../docs/dop3000/existing-sweep-analysis-plan.md).
It begins with the contract rather than hand-produced results: generated artefacts land here only when
the command that regenerates them and their acceptance tests land in the same commit.

Expected outputs, in work-plan order:

| Path | Owner | Purpose |
|---|---|---|
| `manifest.csv` | WP0 | one authoritative row per committed BDD |
| `qc-summary.json` | WP0 | file counts, invariants and decode/timestamp/data-quality checks |
| `reference-repeat.csv` | WP1 | same-settings repeatability/drift bound versus depth |
| `figures/reference-repeat.*` | WP1 | reviewer-visible repeat comparison |
| `resolution-levels.csv` | WP2 | one row per decoded pitch, on its own native gate grid |
| `resolution-pairs.csv` | WP2 | every level pair on common knots, against the WP1 envelope |
| `resolution-ladder.provenance.json` | WP2 | binding, definitions, views, alignment and findings |
| `figures/resolution-ladder.*` | WP2 | reviewer-visible resolution decision figure |
| `burst-levels.csv` | WP2 | one row per decoded burst length, native-grid and temporal metrics |
| `burst-pairs.csv` | WP2 | every level pair on the shared knots, against the WP1 envelope |
| `burst-ladder.provenance.json` | WP2 | binding, definitions, both views, temporal floor and findings |
| `figures/burst-ladder.*` | WP2 | reviewer-visible burst dropout/variance and 18-vs-20 decision figure |
| `figures/prf-*` | WP2 | alias margin and temporal-bandwidth evidence |
| `figures/energy-*` | WP2 | velocity-only TGC/power diagnostics and their limits |
| `decision-table.md` | WP3 | candidate-level keep/defer/replace/diagnostic verdicts |

The WP0 artefacts are regenerated with the committed reader and nothing else:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli sweep-inventory
```

It writes `manifest.csv` and `qc-summary.json` in this directory from
`data/mixer-sensitivity-analysis/4MHz/0500RPM/001` (both overridable with
`--dataset-root` / `--report-dir`). Manifest paths are dataset-relative, both files use LF endings and
one trailing newline, and floats carry 12 significant digits, so a regeneration from the same revision
is byte-identical. `qc-summary.json` records the revision it was generated against and the manifest's
own SHA-256, and the command exits non-zero when any WP0 gate check fails.

**Provenance: which revision a run records.** The bare command above records the
**current HEAD** of the checkout it runs in, so running it on a later commit
regenerates the two files with a different `analysis_commit` and therefore
*different bytes* — that field is a provenance statement about the run, not a
constant. The committed `manifest.csv` and `qc-summary.json` are reproduced byte
for byte only by passing the generator commit that the committed
`qc-summary.json` already records:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli sweep-inventory \
    --analysis-commit <the analysis_commit recorded in the committed qc-summary.json>
```

`--analysis-commit` therefore has two legitimate uses: reproduce a committed
artefact exactly (pass its recorded commit), or label a fresh run with the
revision whose reader produced it (pass that revision). The equivalent
`analysis.sweep_inventory.write_sweep_inventory(..., analysis_commit=...)`
keyword does the same for callers.

Every generated table or figure must carry or sit beside:

- the analysis git commit;
- the input content hashes (directly or through `manifest.csv`);
- the exact regeneration command;
- units and the selected time/depth view;
- an explicit distinction between observed data, derived metric and decision threshold.

Large caches, temporary arrays and exploratory notebook state do not belong here. If a result cannot be
regenerated from the committed BDD files, it is not an accepted report artefact.

## WP1 — the reference-repeatability bound

The only same-settings repeat in the committed set is `prf/600.BDD` against `res/1-8.BDD`: identical
operating parameters, different durations (14.956 s / 11.5529 s, 669 / 517 profiles). Their difference
is an **upper bound** on same-setting repeatability, because duration and unknown acquisition time also
differ — the files carry no acquisition order, so drift can be bounded but never reconstructed. The
WP1 artefacts are:

| Path | What it is |
|---|---|
| `reference-repeat.csv` | 50 rows, one per gate: mean, median, robust spread (IQR), RMS and zero fraction for each recording and for their signed difference |
| `reference-repeat.provenance.json` | the binding (manifest hash, both source hashes, generator commit), the metric definitions, both time views, the temporal parameters with the full ACF/PSD curves, the declared envelope and the figure caption |
| `figures/reference-repeat.png` | four panels: the two depth profiles, the signed difference against the declared envelope, the ensemble autocorrelation and the ensemble PSD on the identical 50-gate grid |

They are written by:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli reference-repeat
```

The command selects the pair **from `manifest.csv`** (never from a hand-maintained filename list),
re-checks both source SHA-256 values against the bytes and every re-checked manifest cell against the
decoded recording, and refuses to produce anything when a selection, hash or setting disagrees
(exit 1, named reason, no half-written artefact). As with WP0, the bare command records the current
HEAD; the committed artefacts are reproduced byte for byte only by passing the commit the committed
`reference-repeat.provenance.json` already records:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli reference-repeat \
    --analysis-commit <the analysis_commit recorded in reference-repeat.provenance.json>
```

Definitions the table cannot be read without, all restated in the provenance document:

- **common-duration view** — the largest integer number of nominal 500-RPM revolutions (0.12 s each)
  that fits both recordings: 96 revolutions = 11.52 s, truncated per file by the recorded timestamps
  (515 profiles of each). Every distributional metric uses that window and nothing else.
- **robust spread** — the interquartile range `p75 - p25`, linear-interpolated percentiles.
- **RMS** — root mean square about zero, so a mean offset raises it: it is not a standard deviation.
- **zero fraction** — the share of samples exactly equal to `0.0`.
- **difference** — signed, `prf/600.BDD - res/1-8.BDD`, field by field; a negative value means
  `res/1-8` is faster at that gate.
- **repeatability envelope** — the largest absolute per-gate mean difference over depth, with the gate
  and depth where it occurs. It is a bound on repeatability *plus* uncontrolled drift, not a
  repeatability estimate on its own, and it is the number every WP2/WP3 verdict must be compared to.
- **temporal view** — each full record in non-overlapping segments of 86 profiles (1.9031 s,
  15.9 revolutions), identical for both files, on one shared profile rate; frequency resolution
  0.5194 Hz at a 22.33 Hz Nyquist limit.
- **500 RPM = 8.33 Hz is a marker only** — there is no tachometer in these files, so the setpoint is
  never a phase reference, and neither gates nor profiles are independent experimental replicates.

## WP2 — the resolution axis

The `res` folder is a 13-point ladder of **decoded gate pitches** over the same window — 0.247 mm
(`res/0-2.BDD`, 365 gates) to 2.96 mm (`res/3-0.BDD`, 31 gates) — and it carries the plan's first
question: *does 0.247 mm add information over 0.617 mm, and which measured pitch is the coarsest that
preserves structure beyond the repeatability floor?* The resolution artefacts are:

| Path | What it is |
|---|---|
| `resolution-levels.csv` | 13 rows, one per decoded pitch: common-duration mean, robust spread (IQR), RMS, zero fraction and gate-level temporal IQR inside the common support, plus the native-grid gradient spread and the native spatial correlation length |
| `resolution-pairs.csv` | 78 rows, every unordered pair of levels: the signed `fine - coarse` per-gate mean difference on the coarser grid's own knots, the knots that clear the WP1 envelope and the depth ranges where they do, and the drift-free detail the finer pitch adds below the coarse knot spacing |
| `resolution-ladder.provenance.json` | the binding (manifest hash, all 13 source hashes, the WP1 envelope's path and hash, generator commit), the metric definitions, both views, the alignment rule, the findings and the figure caption |
| `figures/resolution-ladder.png` | two panels, the minimum the decision needs: native correlation length versus pitch, and the plan's pair with its difference against the envelope band (the gradient spread stays in `resolution-levels.csv`) |

They are written by:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli resolution-ladder
```

The command selects **every `res` row of `manifest.csv`** (never a filename list), orders the ladder by
decoded pitch, re-checks all 13 source SHA-256 values against the bytes together with the decoded
settings and grid of each recording, reads the decision threshold from the committed WP1 provenance and
refuses to run when that artefact was generated against another manifest. A malformed, duplicated,
undecodable or stale inventory exits 1 with a named reason and writes nothing. As with WP0/WP1, the bare
command records the current HEAD; the committed artefacts are reproduced byte for byte only by passing
the commit the committed provenance already records:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli resolution-ladder \
    --analysis-commit <the analysis_commit recorded in resolution-ladder.provenance.json>
```

Definitions the tables cannot be read without, all restated in the provenance document:

- **common-duration view** — the largest integer number of nominal 500-RPM revolutions (0.12 s each)
  fitting *every* resolution recording: 93 revolutions = 11.16 s, truncated per file by the recorded
  timestamps (493–499 profiles each). Every distributional metric uses that window and nothing else.
- **common physical support** — the intersection of the 13 decoded depth ranges,
  10.1626666667–96.7426666667 mm; every cross-level summary uses it, and the provenance records that it
  matches the plan's "approximately 10.163–96.743 mm". The coarse levels' own windows extend past it
  and are not compared there.
- **pitch** — the mean step of a level's decoded gate depths, re-checked against the manifest's
  `resolution_mm` cell: the realised pitch, not the requested rung label.
- **native grid** — every level keeps its own decoded gates. The gradient (`|mean[k+1] - mean[k]| /
  pitch`, attributed to the interval midpoint) and the correlation length (first lag where the
  normalized biased autocovariance of the mean-removed profile drops below 1/e, capped at half the
  profile) are computed per level *before* any alignment, and no level is resampled to produce them.
- **common knots** — a pair's knots are the *coarser* participant's native gate depths inside the common
  support, so the knot spacing is the coarser pitch and never finer than the coarsest participating
  pitch. The finer profile is sampled at those knots by its nearest native gate (offset at most half its
  own pitch): no interpolation, no upsampling, and no claim about structure between the knots.
- **repeatability envelope** — the committed WP1 value, 19.37008103465545 mm/s
  (`max_gate_abs_mean_difference_mm_s`), read from `reference-repeat.provenance.json` and bound to this
  manifest's hash. It is a bound on repeatability *plus* uncontrolled drift, and it is the threshold
  every resolution effect is compared to.
- **detail below the coarse knots** — measured inside the finer recording *alone*, so no drift enters
  it: its supported native mean profile minus that same profile sampled at the coarse knots. It is the
  spatial variance the finer pitch adds, and so the honest ceiling on the information a finer pitch can
  carry here.

### What the committed files measure

Every number below is copied from the artefacts above (the same values are restated in the provenance's
`findings` block, and each pair row carries its own):

- **No measured level differs from any other by more than the envelope.** Across all 78 unordered pairs
  the largest absolute per-knot mean-profile difference is **17.37 mm/s** (`res/1-2.BDD` vs
  `res/1-6.BDD` at 43.83 mm), **0.897** of the 19.37 mm/s envelope, and **not one of the 78 pairs puts a
  single knot above the envelope** anywhere in the common support.
- **0.247 mm adds no demonstrated information over 0.617 mm.** `res/0-2.BDD` vs `res/0-6.BDD` on 141
  knots spaced 0.6167 mm: mean `|diff|` **1.974 mm/s**, max `|diff|` **6.114 mm/s** at 44.70 mm (0.316
  of the envelope), 0 knots above the envelope. The coarse knots retain **99.15 %** of the finer
  profile's spatial variance, and the structure below them carries **0.0722 %** of it (RMS
  **0.5814 mm/s**, peak **2.738 mm/s**). The evidence therefore cannot support a claim that 0.247 mm
  adds information — and it equally cannot exclude a real effect smaller than the repeat-plus-drift
  bound, which one same-settings repeat cannot resolve.
- **The coarsest measured pitch preserves the structure the finer pitches show.** The native
  correlation length of the depth-resolved mean profile is **9.62–18.99 mm** at every level (4–41 gate
  pitches), so the structure lives on a scale of order tens of millimetres. `res/3-0.BDD` at 2.96 mm
  (30 supported gates) still samples it **4** times per correlation length, and differs from every other
  level by at most **10.43 mm/s** (0.539 of the envelope). That is a statement about the 13 recorded
  pitches only: nothing finer than 0.247 mm or coarser than 2.96 mm was measured, and an effect smaller
  than the drift-inclusive envelope would be invisible in this dataset.

Reviewer path: `resolution-pairs.csv` (the focus-pair row `res/0-2.BDD` → `res/0-6.BDD`, and the
`knots_above_envelope` / `depth_ranges_above_envelope_mm` columns), then `resolution-levels.csv` for the
per-pitch distributional and spatial numbers, then `figures/resolution-ladder.png`, then the `findings`
and `definitions` blocks of `resolution-ladder.provenance.json` for the binding, the alignment rule and
the limitations.

## WP2 — the burst-length axis

The `burst_len` folder is a 12-point ladder of **decoded cycle counts** over the same window on the
same 1.85 mm gate grid — 2 (`burst_len/2.BDD`) to 32 (`burst_len/32.BDD`) — and it carries the plan's
second question: *where is the empirical transition, and can 18 be separated from 20 cycles?* The
artefacts are:

| Path | What it is |
|---|---|
| `burst-levels.csv` | 12 rows, one per decoded cycle count: common-duration mean, robust spread (IQR), RMS, zero fraction (dropout), native-grid gradient and correlation length, and the matched full-record temporal metrics (ACF e-folding lag, in-band power share above 10 Hz, spectral centroid, RMS bandwidth) |
| `burst-pairs.csv` | 66 rows, every unordered pair: the signed `short - long` per-gate mean difference at the shared knots, the knots that clear the WP1 envelope and the depth ranges where they do, and the short-to-long change of the dropout, variance, smoothing and bandwidth metrics |
| `burst-ladder.provenance.json` | the binding (manifest hash, all 12 source hashes, the WP1 envelope's path and hash, generator commit), the metric definitions, both views, the temporal floor, the findings and the figure caption |
| `figures/burst-ladder.png` | two panels, the minimum the decisions need: dropout and variance versus cycle count with the 16-20-cycle region shaded, and the plan's 18-versus-20 difference at the shared knots against the envelope band |

They are written by:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli burst-ladder
```

The command selects **every `burst_len` row of `manifest.csv`** (never a filename list), orders the
ladder by decoded cycle count, re-checks all 12 source SHA-256 values against the bytes together with
every decoded setting and the gate grid of each recording, reads the decision threshold and the
temporal repeat floor from the committed WP1 provenance and refuses to run when that artefact was
generated against another manifest. It also refuses a ladder in which any setting other than the
burst length moved (plan section 2's clean-OFAT requirement). A malformed, duplicated, undecodable,
coupled or stale inventory exits 1 with a named reason and writes nothing. As with WP0/WP1/resolution,
the bare command records the current HEAD; the committed artefacts are reproduced byte for byte only
by passing the commit the committed provenance already records:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli burst-ladder \
    --analysis-commit <the analysis_commit recorded in burst-ladder.provenance.json>
```

Definitions the tables cannot be read without, all restated in the provenance document:

- **common-duration view** — the largest integer number of nominal 500-RPM revolutions (0.12 s each)
  fitting *every* burst recording: 92 revolutions = 11.04 s, truncated per file by the recorded
  timestamps (494 profiles of each). Every distributional metric uses that window and nothing else.
- **common physical support** — the intersection of the 12 decoded depth ranges,
  10.1626666667-100.812666667 mm. All 12 files carry the identical 50-gate 1.85 mm grid, so this
  support is that whole grid; it *contains* the plan's declared ~10.163-96.743 mm window, and the
  provenance records both.
- **native grid** — every level keeps its own decoded gates. The gradient (`|mean[k+1] - mean[k]| /
  pitch`, attributed to the interval midpoint) and the correlation length (first lag where the
  normalized biased autocovariance of the mean-removed profile drops below 1/e) are computed per level
  *before* any alignment, and no level is resampled.
- **shared knots** — a pair's knots are the *longer* pulse's native gate depths inside the common
  support, so the knot spacing is never finer than the smoother participant's own grid. Here both grids
  are identical, so the nearest-native-gate offset is exactly `0` and no interpolation or resampling
  occurs anywhere in this report.
- **matched temporal view** — every file's full record in non-overlapping segments of the same 86
  profiles on one shared profile period (0.02238922387935217 s, the mean of the 12 implied periods,
  which agree to 1.7e-5 relative): frequency resolution 0.5194 Hz at a 22.33 Hz Nyquist limit, 5-6
  segments per level. Each level's ensemble PSD inside 0.5-20 Hz gives the in-band power share above
  10 Hz, the power-weighted spectral centroid and the RMS bandwidth; its ensemble autocorrelation gives
  the e-folding lag.
- **temporal repeat floor** — the same metrics for the two committed WP1 same-settings recordings,
  computed from the ACF/PSD curves `reference-repeat.provenance.json` already records. Their difference
  is an upper bound on repeatability plus uncontrolled drift for the temporal metrics, exactly as the
  19.37008103465545 mm/s mean-profile envelope is for the depth profiles.
- **repeatability envelope** — the committed WP1 value, 19.37008103465545 mm/s
  (`max_gate_abs_mean_difference_mm_s`), read from `reference-repeat.provenance.json` and bound to this
  manifest's hash. It is a bound on repeatability *plus* uncontrolled drift, and it is the threshold
  every mean-profile effect here is compared to.
- **knee** — the largest one-step change of a metric along the cycle ladder, with the cycle count it
  reaches, the value there, the net change and whether the sequence falls monotonically. No smoothing
  is applied and no plateau is claimed that the numbers do not show.

### What the committed files measure

Every number below is copied from the artefacts above (the same values are restated in the provenance's
`findings` block, and each pair row carries its own):

- **18 cycles cannot be separated from 20.** `burst_len/18.BDD` vs `burst_len/20.BDD`: max `|diff|`
  **11.7519 mm/s** at 91.563 mm = **0.607** of the 19.37 mm/s envelope, **0 of 50** knots above it.
  The whole 16-20-cycle region is inside the bound: 16 vs 18 = **0.650**, 16 vs 20 = **0.256**, and all
  three unordered pairs have **zero** knots above the envelope. The verdict recorded in the provenance
  is therefore that this evidence cannot choose between 18 and 20; what remains unidentifiable is any
  burst effect smaller than the envelope, and the pitch x burst interaction (the two ladders meet only
  at the reference).
- **Most of the ladder is inside the bound, but it is not empty.** Across all 66 pairs the largest
  absolute per-knot mean-profile difference is **44.0313 mm/s** (`burst_len/4.BDD` vs
  `burst_len/28.BDD`, at the first gate, 10.163 mm) = **2.273** of the envelope. **21 of 66** pairs put
  at least one knot above the envelope, always at a handful of gates (never more than 5) and never
  across the support; **16** of those 21 involve the two longest bursts (28, 32).
- **The dropout and variance "knees" are one recording, not a trend.** No metric falls monotonically
  along the ladder. `burst_len/28.BDD` carries the largest single step in dropout (**+0.0109**,
  reaching **0.02117**, 2.3x the ladder median of 0.00913) and in the worst native gradient (**+9.51**,
  reaching **16.14 mm/s per mm**, 1.8x the next worst level); the largest variance step is the *rise*
  at `burst_len/4.BDD` (+12.88 in robust spread). Whether that is a property of 28 cycles, of that one
  recording, or drift cannot be separated from a single recording per level.
- **The longer pulse is not shown to smooth the profile or to narrow the band.** The native correlation
  length stays **11.1-14.8 mm** (6-8 gate pitches) over the whole ladder, so the structure lives on a
  scale of order tens of millimetres. In the temporal view the in-band power share above 10 Hz ranges
  **0.0787-0.1235** (spread 0.0448) and the RMS bandwidth **3.952-4.639 Hz**, while the two committed
  same-settings recordings differ by **0.0279** in the same share and **0.446 Hz** in the bandwidth —
  the ladder's spread is only ~1.6x that floor. The direction is the one a longer pulse predicts (the
  shortest bursts carry the largest share), but the magnitude is not separable from repeat-plus-drift.
  The ACF e-folding lag takes only the two values the WP1 pair shows (0.08956 s at 11 levels,
  0.11195 s at `burst_len/32.BDD`), and that pair's own lag difference is exactly one profile period
  (0.02239 s), so a one-lag change is inside the floor by construction.

Reviewer path: `burst-pairs.csv` (the focus-pair row `burst_len/18.BDD` -> `burst_len/20.BDD` with
`knots_above_envelope` = 0, and the `max_abs_difference_over_envelope` column throughout), then
`burst-levels.csv` for the per-level distributional, spatial and temporal numbers, then
`figures/burst-ladder.png`, then the `findings`, `definitions` and `views` blocks of
`burst-ladder.provenance.json` for the binding, the temporal floor and the limitations.
