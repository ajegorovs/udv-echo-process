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
| `figures/burst-*` | WP2 | burst transition and smoothing evidence |
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
