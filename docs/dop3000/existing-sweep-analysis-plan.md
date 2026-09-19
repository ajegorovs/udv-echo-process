# Existing mixer sweep analysis — work plan

> **Status:** executable work plan. This plan gates the candidate matrix in
> [`sparse-parameter-set.md`](sparse-parameter-set.md): its candidate levels are hypotheses until the
> existing 40 velocity recordings have been analysed. No new instrument acquisition belongs to this
> plan until the existing-data decision table is complete.
>
> **State — WP0, WP1, WP2, WP3 and WP4 are delivered.** The inventory, the repeatability bound, the four
> axis analyses, the decision table
> ([`reports/mixer-sensitivity-analysis/decision-table.md`](../../reports/mixer-sensitivity-analysis/decision-table.md))
> and the evidence-gated first augmentation (`sparse-parameter-set.md` §2-§3) all sit in this PR, which
> runs no new acquisition: the augmentation is a design, and the limitations §7 lists still hold.
>
> **Dataset:**
> [`data/mixer-sensitivity-analysis/4MHz/0500RPM/001/`](../../data/mixer-sensitivity-analysis/4MHz/0500RPM/001/)
> — 40 committed `.BDD` files: resolution 13, burst length 12, PRF 5, TGC 8 and
> emitting power 2, all around the reference recorded in `prf/600.BDD`.
>
> **Reviewable outputs:** every result named below lands under
> [`reports/mixer-sensitivity-analysis/`](../../reports/mixer-sensitivity-analysis/README.md). A
> reviewer must be able to regenerate the tables and plots from the committed BDD files; local scratch
> paths and notebook-only state are not evidence.

## 1. Question this work must answer

Use the measured velocity arrays to decide which candidate levels deserve new instrument time, which
old ladders are already sufficient, and which questions the old OFAT design cannot answer.

The work ends with an explicit verdict for each candidate in the sparse-set PR:

| Axis | Decision required |
|---|---|
| resolution | retain the coarsest pitch that preserves structure beyond the repeatability floor; decide whether 0.247 mm adds information over 0.617 mm |
| burst length | locate the empirical transition and decide 18 versus 20 cycles |
| PRF | measure velocity and temporal-bandwidth headroom; acquire 250 µs only if 400 µs is inadequate |
| emissions/profile | establish that the axis is absent from the old sweep; begin with 8/20/64 and add 128 only if 64 has not plateaued |
| sensitivity | decide whether one high-sensitivity diagnostic is needed before a wider ladder |
| TGC and power | decide what velocity-only data can screen and what still requires echo/energy acquisition |

The output is not a significance-ranked collection of individual gates. It is an effect-size and
information-value decision, bounded by the only repeated setting in the dataset.

## 2. Facts the implementation must preserve

These are verified properties of the committed payload, not conclusions about the flow:

- all 40 files decode as one axial-velocity channel in `mm/s`; no echo or energy profile is present;
- profile arrays range from 418–669 profiles and 31–365 gates; durations range from 8.15–16.03 s;
- physical windows share a first gate near 10.163 mm, but the resolution ladder ends between
  96.743 and 100.813 mm;
- operation word 14 is `20`, word 27 is `4`, and word 84 is `0` in every file; the public reader
  publishes all three as the **stored integers** `ChannelConfig.emissions_per_profile` (20),
  `sampling_volume_index` (4) and `skipped_profiles` (0), while `sampling_volume_mm` stays unset —
  word 27 is the instrument's bandwidth-list index, not a length;
- TGC word 23 is `0`, word 25 is fixed at `255`, and only word 24 moves in the TGC folder. The
  reader currently labels word 23 value `0` as `uniform`; do not reinterpret this ladder as a simple
  scalar gain until the representation has been settled;
- `prf/600.BDD` and `res/1-8.BDD` have the same operating-parameter signature but different durations.
  They are the only same-settings repeat and bound repeatability plus uncontrolled drift;
- file metadata does not recover acquisition order. Do not estimate time drift from folder or filename
  order;
- the resolution and burst ladders intersect only at the reference, so pitch × burst interaction is not
  estimable from this dataset.

If an implementation contradicts one of these facts, stop and resolve the decoder or fixture before
producing scientific output.

## 3. Analysis contract

### 3.1 Two time views

Produce both:

1. a **common-duration view**, truncated to an integer number of nominal 500-RPM rotations that fits
   every file, for directly comparable distributional summaries; and
2. a **full-record view** for autocorrelation and spectra, with identical segment duration and reported
   frequency resolution across files.

The mixer setpoint supplies a nominal 8.33-Hz marker, not a phase reference: there is no tachometer in
these BDD files. Estimate dependence from each signal's autocorrelation and never count profiles as
independent experimental replicates.

### 3.2 Depth views

- Cross-level profiles use only the common physical support, approximately 10.163–96.743 mm.
- Between-resolution comparisons use common depth knots no finer than the coarsest participating pitch.
- Spatial gradients and correlation lengths are first calculated on each native gate grid. Do not
  upsample coarse data and call the interpolated samples resolved structure.
- Record every interpolation/smoothing choice in the manifest and figure caption.

### 3.3 Uncertainty

The `prf/600` ↔ `res/1-8` difference is an upper bound on same-setting repeatability, because duration
and unknown acquisition time also differ. Within-record block bootstrap intervals may describe
conditional uncertainty, with block length based on measured autocorrelation and no shorter than a
nominal mixer revolution. They do not turn one acquisition into independent run-level replication.

No gate-wise p-value family is a primary endpoint. Report effect sizes versus the repeatability bound.

## 4. Work packages and acceptance gates

### WP0 — Freeze the inventory and reader surface

Deliver:

- `manifest.csv`: one row per BDD with path, axis, requested label, decoded settings, relevant raw
  operation words, shape, duration, timing, depth range, velocity range, zero fraction and source hash;
- `qc-summary.json`: expected file/axis counts, decode failures, NaN/timestamp checks and invariant-word
  checks;
- the public reader fields for word 14 (emissions/profile), word 27 (sampling-volume **index**) and
  word 84 (skipped profiles), each fixture-tested before the manifest relies on it — delivered as the
  stored integers `emissions_per_profile` / `sampling_volume_index` / `skipped_profiles`; word 27 is an
  index into the instrument's bandwidth list, so `sampling_volume_mm` stays unset.

Gate:

- exactly 40 SHA-identified files and axis counts `13/12/8/5/2`;
- zero decode failures, zero NaNs and monotone timestamps;
- manifest values reproduce the dataset README where fields overlap;
- tests fail first for each newly exposed reader field, then pass.

### WP1 — Establish the repeatability bound

Deliver:

- `reference-repeat.csv`: depth-resolved mean, median, robust spread, RMS and zero fraction for both
  same-settings recordings and their difference;
- one figure showing both profiles, their difference and the declared repeatability envelope;
- temporal autocorrelation and PSD comparison on the identical 50-gate grid.

Gate: every later axis verdict states whether its effect exceeds this bound and where in depth it does.

### WP2 — Analyse existing ladders

Deliver a common metric table and the minimum figures needed for decisions:

- **resolution:** mean/spread/zero fraction, native-grid gradient and spatial-correlation behaviour,
  with scale-matched comparisons on common depth knots;
- **burst:** the same velocity metrics versus cycle count, highlighting the 16–20-cycle region and
  spatial-smoothing changes;
- **PRF:** `|v|/Vmax` distributions, warning fractions, wrap-like discontinuities, actual profile rate,
  PSD and comparable mixer harmonics below each recording's usable bandwidth;
- **TGC/power:** depth-resolved dropout, bias and variance only. Mark saturation/SNR as unresolved
  because the files contain no echo/energy signal.

Gate: plots are generated from the manifest-selected files, not from hand-maintained filename lists.

### WP3 — Convert evidence into matrix decisions

Deliver `decision-table.md`, one row per candidate condition, with:

- existing evidence;
- effect relative to the repeatability bound;
- scientific information gained;
- automation needed;
- verdict: `keep`, `defer`, `replace`, or `requires diagnostic`;
- the measurement that would overturn the verdict.

Gate: update `sparse-parameter-set.md` from this table. Do not retain a level merely because the
instrument accepts it.

**Delivered.** `reports/mixer-sensitivity-analysis/decision-table.md` — seven columns exactly as named
above, one row per candidate condition of the sparse-set draft plus explicit rows for the four introduced
pitch x burst corner conditions and the reference control. It is hand-written and bound by SHA-256 to the 22
committed artifacts it reads. The gate is met by `sparse-parameter-set.md` §2-§3: the 17-condition candidate
list is replaced by 7 unique new conditions, and no level is retained for feasibility reasons.

### WP4 — Design only the missing measurements

The provisional augmentation, subject to WP3, is:

- reference controls at the beginning, middle and end of each randomized/blocked run;
- pitch × burst corners at 0.617 and 2.960 mm crossed with 4 and 18 cycles;
- emissions/profile 8 and 64 around the existing 20, with 128 conditional on the 64 result;
- one higher-sensitivity diagnostic, extending lower only if it changes validity or distribution;
- an echo/energy diagnostic before declaring the TGC/power envelope safe;
- PRF 250 µs only if the committed 400-µs data show inadequate headroom.

Gate: every new acquisition closes a named information gap; no Cartesian product.

**Delivered as design** in `sparse-parameter-set.md` §3, with the provisional list decided condition by
condition: the four crossing corners are kept (the interaction is not estimable from the committed set), 8 and
64 are kept with 128 conditional on a named measured trigger, the one higher-sensitivity diagnostic is
requested together with the echo/energy channel and is the only condition no writer can execute today, the
controls are three per run, and **PRF 250 µs is not acquired** — measured, at 400 µs, as inadequate on
neither count. Burst 18 cycles replaces 20 on an explicit cost rationale, not a claimed effect.

## 5. Implementation order and commits

Use vertical, reviewable commits:

1. `docs(analysis): gate the sparse matrix on the existing sweep`
2. `feat(bdd): expose sweep metadata required by the manifest`
3. `feat(analysis): inventory the committed mixer sweep`
4. `feat(analysis): quantify the reference-repeat bound`
5. one commit per existing axis analysis (`resolution`, `burst`, `prf`, `energy`)
6. `docs(matrix): decide the first measured augmentation`

Production behaviour follows test-driven development: one failing test, the minimum implementation,
then the focused and full gates. Generated reports must identify the source hashes and analysis commit.

## 6. Verification commands

The implementation PR records raw results for:

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check src tests tools
.venv/Scripts/python.exe -m udv_echo_process.cli <analysis-command> ...
```

The final command spelling is introduced with WP0; this plan does not reserve a CLI name before its
interface is tested.

## 7. Done

This plan is complete when:

- the report directory contains the manifest, QC summary, repeatability result, axis figures and decision
  table, all reproducible from committed inputs;
- PR #23's candidate levels and wording match the measured decisions;
- limitations remain explicit: one same-settings repeat, unknown acquisition order, velocity-only data,
  and no pitch × burst interaction in the old set;
- the next campaign contains only the independent references and missing-information measurements
  justified by the decision table.

**Where each condition stands.** The 22 generated artifacts are committed and reproduce byte for byte from
the commands their provenance records (hash list and commands in the report README); the decision table is
hand-written, so it is bound to those artifacts by SHA-256 rather than regenerated, and the table's own
Binding section carries both. PR #23's 17-condition Stage-1 list and its ten review questions are replaced by
`sparse-parameter-set.md` §2-§3: 7 unique new conditions (8 with the conditional `E128`), 3 reference repeats
per run, and the automation list §6 — every one of them traced to a row of the decision table. The limitations
above are not resolved by this work and are not claimed to be: they are the reason the augmentation exists and
they are restated in the decision table's closing section, in `sparse-parameter-set.md` §8 and in each axis
module's own `findings.limitations`.
