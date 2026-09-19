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
| `prf-levels.csv` | WP2 | one row per decoded PRF period: velocity load, wrap-like counts, matched-segment temporal metrics |
| `prf-pairs.csv` | WP2 | every level pair on the shared knots and bands, against the WP1 envelope |
| `prf-ladder.provenance.json` | WP2 | binding, definitions, both views, the key's scaled velocity range and findings |
| `figures/prf-ladder.*` | WP2 | reviewer-visible velocity-headroom and usable-bandwidth decision figure |
| `gain-power-levels.csv` | WP2 | one row per screened TGC/emitting-power level: key, common window and support, dropout/spread screening |
| `gain-power-pairs.csv` | WP2 | every within-axis pair on common knots, against the WP1 envelope, with the depth ranges where it clears |
| `gain-power-depths.csv` | WP2 | one row per level per supported gate: zero fraction, robust spread, mean and std by depth |
| `gain-power-screen.provenance.json` | WP2 | binding, definitions, both axes' views, the TGC representation and the velocity-only findings |
| `figures/gain-power-screen.*` | WP2 | reviewer-visible dropout-by-depth and focus-pair-against-envelope decision figure |
| `figures/energy-*` | WP2 | not produced here: the higher-sensitivity/echo-energy diagnostic this screen asks for |
| `decision-table.md` | WP3 | candidate-level keep/defer/replace/diagnostic verdicts |

### Delivery status

| Work package | State | Where |
|---|---|---|
| WP0 — inventory and reader surface | delivered | `manifest.csv`, `qc-summary.json` |
| WP1 — the reference-repeatability bound | delivered | `reference-repeat.csv`, `reference-repeat.provenance.json`, `figures/reference-repeat.png` |
| WP2 — resolution, burst, PRF, TGC and emitting power | delivered, all four axes | the `resolution-*`, `burst-*`, `prf-*` and `gain-power-*` rows above |
| WP3 — the decision table | delivered | [`decision-table.md`](decision-table.md) — hand-written (nothing regenerates it), bound by SHA-256 to the 22 artifacts above and to the source hashes of `manifest.csv` |
| WP4 — the first measured augmentation | delivered as design, no acquisition executed | [`docs/dop3000/sparse-parameter-set.md`](../../docs/dop3000/sparse-parameter-set.md) §3 — 7 unique new conditions (8 with the conditional one) and 3 reference repeats per run, no Cartesian product |
| `figures/energy-*` | not produced here | the higher-sensitivity/echo-energy diagnostic the gain/power screen asks for: no committed file carries an echo or energy channel, so there is nothing to plot yet |

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

The artefacts are line-ending-pinned: the repository-root `.gitattributes` sets `text eol=lf` on this
directory's `*.csv` and `*.json` files (and `binary` on `figures/*.png`), so the committed bytes
— and with them the `manifest.csv` SHA-256 that every axis re-checks (`064a289b…`) — survive a
fresh clone on a host with `core.autocrlf=true`. Without the pin a Windows checkout rewrites
`manifest.csv` with CRLF, its hash becomes `2ff7c3f7…`, and WP1, resolution, burst and PRF all
refuse to run.

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

## WP2 — the PRF axis

The `prf` folder is a five-point ladder of **decoded pulse-repetition periods** over the same window
on the same 1.85 mm gate grid — 400 µs (`prf/400.BDD`) to 800 µs (`prf/800.BDD`) — and it carries
the plan's third question: *does the committed 400-µs setting have inadequate velocity or
temporal-bandwidth headroom, and is a 250-µs acquisition therefore justified?* The artefacts are:

| Path | What it is |
|---|---|
| `prf-levels.csv` | 5 rows, one per decoded period: common-duration mean, robust spread, RMS, zero fraction, native-grid gradient and correlation length, the actual profile rate from the timestamps, the `|v| / Vmax` load with its warning fractions, the wrap-like discontinuity count and step scale, and the matched-segment temporal metrics (segment length, resolution, usable bandwidth, ACF e-folding lag, share of in-band power below the 8.33 Hz marker) |
| `prf-pairs.csv` | 10 rows, every unordered pair: the signed `faster - slower` per-gate mean difference at the shared knots, the knots that clear the WP1 envelope and the depth ranges where they do, the load/wrap/zero-fraction change, and the band-mean spectral level difference on the shared comparison bands |
| `prf-ladder.provenance.json` | the binding (manifest hash, all 5 source hashes, the WP1 envelope's path and hash, generator commit), the audit of the key's scaled velocity range, the metric definitions, both views, the decision findings and the figure caption |
| `figures/prf-ladder.png` | two panels, the minimum the decision needs: the peak load of each level against the unambiguous limit with the samples beyond it and the wrap-like steps, and each level's ensemble PSD against the frequencies it supports |

They are written by:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli prf-ladder
```

The command selects **every `prf` row of `manifest.csv`** (never a filename list), orders the ladder
by decoded PRF period, re-checks all five source SHA-256 values against the bytes together with
every decoded setting, the gate grid *and the two cells the key derives* (`prf_hz` and
`velo_max_ms`), reads the decision threshold and the temporal floor from the committed WP1
provenance, and refuses to run when that artefact was generated against another manifest. It also
refuses a ladder in which a decoded setting other than the key moved (plan §2's clean-OFAT
requirement) and a ladder whose velocity scale did **not** move with the key: `velo_max_ms` is the
reader's ±Nyquist velocity, so `velo_max_ms × prf_period_us` must be invariant, and here it is
constant to 4.3e-12 relative. A malformed, duplicated, undecodable, stale, coupled or unscaled
inventory exits 1 with a named reason and writes nothing. As with WP0/WP1/resolution/burst, the bare
command records the current HEAD; the committed artefacts are reproduced byte for byte only by
passing the commit the committed provenance already records:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli prf-ladder \
    --analysis-commit <the analysis_commit recorded in prf-ladder.provenance.json>
```

Definitions the tables cannot be read without, all restated in the provenance document:

- **common-duration view** — the largest integer number of nominal 500-RPM revolutions (0.12 s each)
  fitting *every* PRF recording: 67 revolutions = 8.04 s, truncated per file by the recorded
  timestamps (537/431/360/309/270 profiles), because the profile rate differs across the ladder and
  the profile *count* therefore cannot be the common quantity.
- **common physical support** — the intersection of the five decoded depth ranges,
  10.1626666667-100.812666667 mm, which *contains* the plan's declared ~10.163-96.743 mm window.
- **`Vmax` (the `velo_max_mm_s` column)** — the reader's ±Nyquist velocity, the velocity at
  full-scale count. It is the only physically distinguished scale the files carry, and every load
  fraction is normalised by *that file's own* value: 231.206375266 mm/s at 400 µs falling to
  115.603187633 mm/s at 800 µs, with `Vmax × prf_period` constant.
- **load and warning fractions** — the share of windowed, supported samples at or above 0.5, 0.75,
  0.9 and 1.0 of that file's `Vmax`. `1.0` is the unambiguous limit; the inner three are declared
  margins below it, not instrument flags — these files carry no warning channel and the decoded
  array is not clamped, so a sample beyond `Vmax` is either a wrapped estimate or an estimator
  excursion past full scale and this report does not separate the two.
- **wrap-like discontinuity** — a consecutive-profile change at one gate of at least `Vmax` in
  magnitude *with a sign reversal*: a wrap moves the estimate across the whole ±`Vmax` span in one
  profile interval, about 2 `Vmax`, so the criterion is the conservative half-span. The largest
  observed step in units of `Vmax` is published beside the count.
- **matched temporal view** — the files do **not** share a profile rate (66.72 Hz at 400 µs down to
  33.57 Hz at 800 µs), so a profile count would give five different durations. The shared quantity
  is the *physical* segment duration: the largest 0.1 s multiple that fits five whole segments in
  the shortest record (8.1535 s) is **1.6 s**, and each file takes the whole number of profiles
  inside it — 106/85/71/61/53 profiles, spans 1.5737-1.5490 s (1.6 % apart), frequency resolutions
  0.6284-0.6334 Hz against a stated nominal 0.625 Hz, 5-10 segments each.
- **usable bandwidth** — the highest frequency a file's matched segment supports, half its profile
  rate: 33.360/26.439/22.018/18.851/16.468 Hz. The full-record Nyquist limit is published beside it
  and is *not* used for the comparison.
- **comparison bands** — identical bands from the nominal resolution up to the narrowest usable
  bandwidth in the ladder (0.625-16.25 Hz, 25 bands); a level's density is its band power over the
  band width, so no spectrum is compared where another has no support. Only band-integrated
  densities are differenced: the frequency grids themselves are not identical, because the sample
  rates are not.
- **mixer marker** — 500 RPM = 8.333 Hz is a marker only. There is no tachometer in these files, so
  it is never a phase reference, and no spectral peak is attributed to it or to a harmonic; its
  second multiple (16.67 Hz) lies above the shared comparison band in any case.
- **repeatability envelope** — the committed WP1 value, 19.37008103465545 mm/s
  (`max_gate_abs_mean_difference_mm_s`), read from `reference-repeat.provenance.json` and bound to
  this manifest's hash. It is a bound on repeatability *plus* uncontrolled drift, and it is the
  threshold every mean-profile effect here is compared to.
- **temporal repeat floor** — the same-settings WP1 pair (`prf/600.BDD` vs `res/1-8.BDD`) through
  its committed curves, resummarised in the bands this ladder shares: their band-mean spectral
  levels differ by up to 3.532 dB and their share of in-band power below the 8.333 Hz marker by
  0.01806, so a cross-level spectral difference smaller than that is not separable either.

### What the committed files measure

Every number below is copied from the artefacts above (the same values are restated in the
provenance's `findings` block, and each pair row carries its own):

- **The 400-µs setting has the *most* velocity headroom of the five, not the least.** In its
  common window and support the largest `|v|` is **167.99 mm/s = 0.7266 of the 231.206 mm/s**
  unambiguous limit, **0** samples are at or beyond the limit and **0** consecutive-profile step is
  a wrap-like discontinuity (the largest step anywhere in that file is 0.6953 `Vmax`). The load
  grows as the period lengthens: 0.9219 at 600 µs, **1.0625** at 500 µs, **1.2109** at 800 µs, where
  the recording also carries 1 sample beyond the limit, 3 wrap-like steps and a largest step of
  1.4531 `Vmax`. The pressure on the velocity scale is therefore a *long-period* problem, and it is
  visible as a diagnostic load in this ladder, not as a proven alias of a particular sample.
- **The 400-µs setting also has the widest usable temporal bandwidth of the five.** Its profile rate
  is 66.72 Hz and its matched-segment usable bandwidth 33.36 Hz, against 16.47 Hz at 800 µs; the
  spectra of all five are compared only inside the 0.625-16.25 Hz band every recording supports,
  with the 8.333 Hz marker inside it (0.8355-0.8959 of each level's in-band power lies below the
  marker). The ACF e-folding lag takes only 0.0783-0.1119 s across the ladder — one lag step is
  0.015-0.030 s — so nothing about the fluctuation time scale separates the levels either.
- **A 250-µs acquisition is not justified by this evidence.** Both counts the plan names are
  answered the same way at 400 µs: peak load 0.7266 with no sample at the limit, and the widest
  usable bandwidth in the ladder. A 250-µs setting would move the unambiguous limit to
  ~369.93 mm/s, which nothing in this dataset needs: the largest `|v|` seen in *any* of the five
  recordings is 196.53 mm/s (`prf/500.BDD`), still 0.85 of the 400-µs limit. Unidentifiable here: a
  wrap that leaves no step of half the span (a slowly drifting alias), the peak velocity of a flow
  whose setpoint differs from this 500-RPM one, and the profile rate a future 250-µs setting would
  actually run at — these files cannot fix it, because their own rate is not an exact multiple of
  the PRF (its ratio varies by 0.00625 relative across the ladder).
- **Eight of the ten pairs clear the WP1 envelope somewhere, and the clearances are local.** The
  largest absolute per-knot mean-profile difference is **37.5148 mm/s** (`prf/400.BDD` vs
  `prf/500.BDD` at 13.8627 mm) = **1.937** of the 19.37 mm/s envelope, over 7 knots in three runs
  (10.1627, 13.8627-15.7127, 34.2127-39.7627 mm). The other clearances sit at 1-8 knots: 400 vs 600
  (2 knots, 13.86-15.71 mm), 400 vs 700 (1 knot), 400 vs 800 (2 knots), 500 vs 600 (3 knots),
  500 vs 800 (5 knots), 600 vs 700 (2), 600 vs 800 (8, in three runs out to 71.21 mm). Only
  `prf/500.BDD` vs `prf/700.BDD` and `prf/700.BDD` vs `prf/800.BDD` are inside the bound at every
  knot. None of these runs spans the support, so the evidence is a *localised* signal (near-field and
  a few mid/minor-depth knots), not a global velocity bias — and with one recording per level and no
  acquisition order, that localised signal cannot be separated from drift.
- **The spectra themselves are not separable at this resolution either.** Band-mean spectral level
  differences between levels run 1.22-3.46 dB in magnitude, while the same-settings WP1 pair differs
  by 3.532 dB in the same resummarisation; the direction (the shorter period's density slightly
  below the longer's in 8 of 10 pairs) is not larger than the floor, and with 5-10 segments per level
  a band level is a coarse magnitude.

Reviewer path: `prf-levels.csv` for the per-level load, warning fractions, wrap-like counts, profile
rate and usable bandwidth, `prf-pairs.csv` for the envelope comparison and the band level
differences, `figures/prf-ladder.png` for the headroom and bandwidth decision panels, then the
`findings`, `views`, `definitions` and `derived_scale` blocks of `prf-ladder.provenance.json` for
the binding, the matched-physical-duration rule, the key's scaled velocity range and the
limitations.

## WP2 — the TGC and emitting-power axes (velocity-only)

`.venv/Scripts/python.exe -m udv_echo_process.cli gain-power-screen`

Both axes are screened in one command and one evidence set, from the WP0 manifest and never from a
filename list: `tgc` (8 levels, `tgc/0.BDD` … `tgc/40.BDD`, keyed by the decoded TGC start in dB) and
`em_pow` (2 levels, `em_pow/low.BDD` and `em_pow/high.BDD`, keyed by the instrument's own
`low` < `medium` < `high` steps). Each level's hash, every shared decoded cell and the two TGC cells
are re-checked, each axis is required to be a clean one-factor-at-a-time ladder on its own key
(coupled settings refused separately per axis), and both are measured against the committed WP1
envelope of **19.37 mm/s**.

Two facts about the sweep decide how far this can reach:

- **TGC is screened through the committed representation, not a gain ladder.** Op word 23 stays `0`
  and the reader labels that mode `uniform`; word 25 stays `255` and decodes to a fixed 40 dB end;
  only word 24 / `tgc_start_db` moves. That is the representation this screen is ordered by and
  refuses when it moves — it is **not** a validated scalar gain set point, and no wider TGC ladder
  should be designed on such a reading. The invariant is asserted from the raw words of all 10 files
  (8 distinct word-24 values on the TGC axis, one shared value on the power axis).
- **Sensitivity is fixed at `medium` in all 40 manifest rows and neither axis varies it.** The axis
  is absent from the sweep, so its effect is unidentifiable from it; no amplitude-to-velocity
  conversion of any kind is available here.

Per-axis common views are recomputed inside each axis, not shared across them: `tgc` runs 77
nominal 500-RPM revolutions = **9.24 s** (413 profiles per file) and `em_pow` 96 = **11.52 s**
(515 profiles), both on the common support of **10.1627-100.8127 mm** (50 gates per file), which
contains the plan's 10.163-96.743 mm window. Both axes bracket the base state rather than sampling
it: the other rows carry TGC start 19.92 dB / emitting power `medium`, and neither is a level of its
axis, so each axis's focus pair is the two levels that straddle it.

What the velocity-only screen found:

- **Two of the ten levels are flagged, both on the TGC axis.** `tgc/0.BDD` is dropout-limited:
  0.2437 of its window samples are exactly 0.0 at 10 of 50 gates, covering 84.16-100.81 mm, up to
  **0.8111** blank at one gate. `tgc/40.BDD` is dropout- **and** spread-limited: 0.0388 overall (1
  majority-blank gate at 69.36 mm) and a largest per-gate robust spread of **148.12 mm/s** at
  73.06 mm — **4.97×** the axis's median per-gate spread. Both are single-segment facts: one
  recording per setting, no acquisition order, and no way here to tell the gain from the flow, from
  drift or from one bad recording.
- **The power axis is unremarkable in velocity.** `em_pow/low.BDD` vs `high.BDD` differ by at most
  **10.41 mm/s** at 47.16 mm = **0.537** of the envelope, with **0** of 50 knots above it; neither
  level carries a majority-blank gate or a disproportionate per-gate spread.
- **14 of the 28 TGC pairs clear the envelope somewhere, locally.** The largest absolute per-knot
  mean-profile difference in the screen is **47.10 mm/s** (`tgc/30.BDD` vs `tgc/40.BDD` at 73.06 mm)
  = **2.432** of the envelope, over 2 knots in one run (73.06-74.91 mm). Most clearances are 1-3
  knots and none spans the support, so this is a localised mid/near-depth signal against a
  single-recording, orderless ladder — not a global velocity bias.
- **The base state's own bracketing pair is inside the bound.** `tgc/15.BDD` vs `tgc/25.BDD`
  (carrying 14.90 dB and 24.94 dB around the 19.92 dB base state) differ by at most **11.69 mm/s**
  at 63.81 mm = **0.604** of the envelope over 0 of 50 knots. The `em_pow` focus pair is the whole
  power ladder, at **0.537** of the envelope.

Not measured, and not inferred: **echo SNR, receiver saturation, a safe plateau and acoustic
energy are absent from these files.** Only one axial-velocity channel exists per recording, so this
screen reports depth-resolved dropout (the share of window samples exactly 0.0 per gate), bias (the
signed `low - high` per-gate mean difference per knot) and variance/robust spread (per-gate IQR and
standard deviation by level and depth) — and stops there. A blank or erratic gate is a property of
the recorded velocity array, not evidence that a gain, a power or the receiver saturated. No
p-values are produced (one recording per setting, no replicates, no acquisition order).

**Diagnostic conclusion.** The velocity-only evidence justifies exactly **one**
higher-sensitivity/echo-energy diagnostic before any wider TGC, power *or* sensitivity ladder — and
no wider ladder first — because two of ten levels already fail the dropout/spread screen for reasons
this data cannot attribute, and because a fixed sensitivity is the axis that an echo/energy
measurement is the only way to make identifiable at all. This module does not predict that
diagnostic's outcome, and `findings.diagnostic` records the verdict as
`justified: true, wider_ladder_justified: false, outcome_claimed: false`. The resolution, burst and
PRF verdicts are not revisited here; they belong to their own modules.

Reviewer path: `gain-power-levels.csv` for the per-level key, window, support and screening flags,
`gain-power-depths.csv` for the per-gate dropout and spread by depth, `gain-power-pairs.csv` for
every within-axis pair against the envelope and the depth ranges where it clears,
`figures/gain-power-screen.png` for the dropout-by-depth screen and the focus-pair panel, then the
`findings`, `definitions`, `axis_blocks` and `tables` blocks of
`gain-power-screen.provenance.json` for the binding, the representation, the views and the
limitations. Regenerate byte for byte with:

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli gain-power-screen \
    --analysis-commit <the analysis_commit recorded in gain-power-screen.provenance.json>
```
