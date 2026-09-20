# Existing mixer sweep analysis — work plan

> **Status:** executable work plan. This plan gates the candidate matrix in
> [`sparse-parameter-set.md`](sparse-parameter-set.md): its candidate levels are hypotheses until the
> existing 40 velocity recordings have been analysed. No new instrument acquisition belongs to this
> plan until the existing-data decision table is complete.
>
> **State — review corrections required before merge.** At PR #24 head `59c852a`, the setting-based
> grouping, full fingerprint, PSD integration, timestamp evidence and first WP1/WP2 regeneration have
> landed. They do not complete steps 3 or 5: generated provenance still gives the screening threshold a
> stale “bound / not distinguishable” role, and several generators still claim one recording per level or
> setting despite the shared two-realization anchor. Those contradictions must be corrected before the
> R7/R8 resolution pass and the WP3/WP4 redesign. No new acquisition belongs to this PR.
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
| resolution | retain the coarsest pitch that preserves structure beyond the sole-pair observed-discrepancy screening threshold; decide whether 0.247 mm adds information over 0.617 mm |
| burst length | locate the empirical transition and decide 18 versus 20 cycles |
| PRF | measure velocity and temporal-bandwidth headroom; acquire 250 µs only if the committed 400-µs rung is inadequate — 400 µs is an existing rung of the committed PRF ladder, not the reference, which stays 600 µs |
| emissions/profile | establish that the axis is absent from the old sweep; 8/20/64 is only the initial bracket, and the corrected decision layer must either add a high-intermediate successive-increment point before deciding on 128 or make 128 an ordinary sparse point |
| sensitivity | decide whether one high-sensitivity diagnostic is needed before a wider ladder |
| TGC and power | decide what velocity-only data can screen and what still requires echo/energy acquisition |

The output is not a significance-ranked collection of individual gates. It is an effect-size and
information-value decision, constrained by the only repeated setting in the dataset.

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
- `prf/600.BDD` (in the `prf` folder) and `res/1-8.BDD` (in the `res` folder) carry the same decoded
  scientific fingerprint — resolution 1.850 mm, PRF 600 µs, burst 10 cycles, TGC ≈19.9216 dB uniform start,
  emitting power medium — and differ only in duration. Every axis analysed here selects recordings by that
  decoded fingerprint and treats all recordings carrying the same relevant fingerprint as realizations of
  one decoded level, irrespective of the folder they sit in. They are the only same-settings pair; their
  difference is the sole-pair observed-discrepancy screening threshold — one observed realization of
  repeatability plus uncontrolled drift, not a bound on either;
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

The `prf/600` ↔ `res/1-8` difference is the sole-pair observed-discrepancy screening threshold; duration
and unknown acquisition time also differ, so it does not bound repeatability or drift (an explicit negation,
not a positive bound claim). Within-record block
bootstrap intervals may describe conditional uncertainty, with block length based on measured autocorrelation
and no shorter than a nominal mixer revolution. They do not turn one acquisition into independent run-level
replication.

No gate-wise p-value family is a primary endpoint. Report effect sizes relative to the
sole-pair observed-discrepancy screening threshold, saying only whether they fall above or below it; neither
outcome proves an axis effect or bounds possible drift.

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

### WP1 — Record the sole-pair observed-discrepancy screening threshold

Deliver:

- `reference-repeat.csv`: depth-resolved mean, median, robust spread, RMS and zero fraction for both
  same-settings recordings and their difference;
- one figure showing both profiles, their difference and the declared sole-pair observed-discrepancy screening threshold;
- temporal autocorrelation and PSD comparison on the identical 50-gate grid.

Gate: every later axis verdict states whether its effect falls above or below this sole-pair observed-discrepancy screening threshold and where
in depth, without interpreting either outcome as proof of an axis effect or a bound on drift.

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
- effect relative to the sole-pair observed-discrepancy screening threshold;
- scientific information gained;
- automation needed;
- verdict: `keep`, `defer`, `replace`, or `requires diagnostic`;
- the measurement that would overturn the verdict.

Gate: update `sparse-parameter-set.md` from this table. Do not retain a level merely because the
instrument accepts it.

**Provisional — not accepted and not delivered.** `reports/mixer-sensitivity-analysis/decision-table.md`
exists, with seven columns exactly as named above, one row per candidate condition of the sparse-set draft
plus explicit rows for the four introduced pitch × burst corner conditions and the one reference condition
(realized by the three within-run reference controls). It is hand-written and pinned by SHA-256 to the 22
committed artifacts it reads. Its earlier claim to meet the gate through `sparse-parameter-set.md` §2-§3 —
the 17-condition candidate list replaced by 7 unique new conditions, no level retained for feasibility
reasons — is reopened by §8.3 step 7 and is not an accepted result.

### WP4 — Design only the missing measurements

The provisional augmentation, subject to WP3, is:

- the reference condition, realized as within-run reference controls at the beginning, middle and end of each randomized/blocked run;
- pitch × burst corners at 0.617 and 2.960 mm crossed with 4 and 18 cycles;
- emissions/profile 8 and 64 around the existing 20 as the initial bracket; the corrected decision layer must
  either add a high-intermediate point and judge successive high-end increments before 128, or include 128 as
  an ordinary sparse point;
- one higher-sensitivity diagnostic, extending lower only if it changes validity or distribution;
- an echo/energy diagnostic before declaring the TGC/power dynamic-range window safe;
- PRF 250 µs only if the committed 400-µs rung shows inadequate headroom (600 µs remains the shared reference period).

Gate: every new acquisition closes a named information gap; no Cartesian product.

**Provisional — not accepted.** It was recorded as a draft design in `sparse-parameter-set.md` §3; no WP3 or
WP4 artifact is delivered by this plan yet. Its four crossing corners, 8/64 bracket, higher-sensitivity
diagnostic, within-run reference controls and PRF decision remain inputs to review, but the exact set and
count are reopened by §8—especially E128, whose old E64-versus-E20 trigger does not test plateau. Nothing in
this paragraph freezes those conditions ahead of corrected WP1/WP2 evidence and step 7.

## 5. Implementation order and commits

Use vertical, reviewable commits:

1. `docs(analysis): gate the sparse matrix on the existing sweep`
2. `feat(bdd): expose sweep metadata required by the manifest`
3. `feat(analysis): inventory the committed mixer sweep`
4. `feat(analysis): quantify the reference-repeat bound` — **historical commit subject, not a live term.**
   This subject shipped as commit `2c70976`; the retired word “bound” is preserved here only as commit
   history, and the quantity it names is the sole-pair observed-discrepancy screening threshold.
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
- the next campaign contains only the within-run reference controls for the one reference condition, plus the
  missing-information measurements justified by the decision table.

**Where each condition stood before review.** The 22 generated artifacts plus the hand-written decision table and
report README remain the 24-item report baseline that §8.3 item 1 must record, not accepted final evidence.
The prior sparse set contained 7 unique
conditions (8 with conditional E128) and 3 within-run reference controls per run for the single reference
condition; those numbers are reopened. Step 7 owns updating
this §7 status, §1's emissions decision, WP4 above, `decision-table.md` and `sparse-parameter-set.md` together,
and its validator must derive all condition/control/job counts from their rows rather than preserve these old
numbers.

## 8. Review round — required completion of PR #24

### 8.1 Ruling and scope

The external scientific review is accepted with one qualification: the missing `df` in the PRF band-density
calculation is physically wrong, but the committed FFT resolutions span only about 0.6284–0.6334 Hz, so its
largest grid-only bias is about 0.035 dB. It still must be fixed before the affected artifacts are relied on.
The other findings stand. This is a correction of the existing analysis and decision record, not authority to
acquire data or widen the campaign.

WP0's inventory, source hashes and reader additions may remain. The data-model and numerical parts of WP1/WP2
at `59c852a` are accepted as the new base, but their scientific prose/provenance remain reopened where listed
below. WP3 and WP4 are provisional until corrected WP1/WP2 artifacts have been regenerated and the decision
table has been rebuilt from them. The old `CC1–CC4 + E8 + E64 + D1` set is not frozen while that work is open.

### 8.2 Verified defects that the completion work owns

| ID | Ruling | Current evidence | Required result |
|---|---|---|---|
| R1 | setting-based anchors and evidence semantics | the grouping now correctly admits both reference files at resolution 1.850 mm, PRF 600 µs, burst 10, TGC ≈19.9216 dB and medium power, but live generator prose still says “each level is one recording”, “one recording per setting” or “no level is replicated” | retain setting-based grouping and describe it exactly: most non-reference levels have one recording; the shared reference level has two realizations; one duplicated setting is not replicated coverage of an axis. No source, caption, finding, definition or report may assert singular coverage when `multi_realization_levels` is non-empty |
| R2 | nuisance threshold | **marked defect-history quotation:** the sole same-settings difference was repeatedly called an upper bound; at `59c852a`, `ScreeningThresholdBinding.role` still says “smaller than this bound is not distinguishable”, and that stale inference is serialized into regenerated provenance | name the quantity, everywhere, exactly **sole-pair observed-discrepancy screening threshold**; its role is screening reference only. A screening outcome states magnitude relative to the sole observed discrepancy; it does not establish distinguishability or causality and is not a statistical floor or bound on repeatability/drift. Apply the same rule to spatial and temporal derived quantities |
| R3 | emissions extension | `sparse-parameter-set.md` §3.4 triggers E128 when E64 differs from E20 | either add a high-intermediate point and use successive high-end increments, or make E128 an ordinary sparse point; no E20→E64 displacement may be called a plateau test |
| R4 | complete OFAT identity | `_native_grid.DECODED_CELLS` omits decoded covariates including emitting frequency, Doppler angle, numeric TGC endpoints, sampling-volume index and skipped profiles | define one full scientific-settings fingerprint and an explicit per-axis allowlist of fields that may vary or are derived from the varied field |
| R5 | PSD integration | `prf_ladder._band_density()` sums PSD-density bins and divides by band width without integrating over frequency | integrate on the actual frequency grid, test unequal grids, and regenerate PRF temporal outputs |
| R6 | timestamp jitter | `reference_repeat.temporal_series()` consumes one scalar profile period rather than the recorded timestamps | publish median Δt, IQR, RMS deviation and maximum deviation per file; retain the uniform method only if a stated measured tolerance supports it, otherwise resample or use an irregular-time method |
| R7 | residual variance | resolution detail is `var(fine - nearest-coarse reconstruction) / var(fine)` | call it normalized reconstruction-residual variance; do not describe it as an orthogonal share of spatial variance |
| R8 | spatial scale | correlation length is the autocorrelation of one mean-removed depth profile | retain it only as a descriptive profile scale, not a physical turbulence scale or principal resolution criterion |
| R9 | controls | beginning→middle and middle→end share the middle observation | call the beginning/middle/end controls **within-run reference controls** forming one minimum within-run drift diagnostic for the single reference condition; never call them “independent references”, and do not call adjacent differences independent |

### 8.3 Corrected implementation order

1. **Freeze the original evidence as the comparison baseline — LANDED (`7c4c187`).** The frozen record is historical after the first correction changes bytes: ordinary tests validate hashes from the captured revision, while `--check-current` is an intentional movement diagnostic and is no longer a completion gate after step 2 starts.
2. **Define the scientific fingerprint and level-group model (R1, R4) — LANDED (`c128b34`).** The two reference files are represented as two realizations of the same anchor on every eligible axis and every non-allowlisted scientific field participates in identity.
3. **Complete WP1 screening semantics (R2) — REOPENED.** Replace `ScreeningThresholdBinding.role` with a screening-reference-only statement and apply it to spatial and temporal uses. Extend the checker with regression cases matching the retired phrases “smaller than this bound is not distinguishable”, “below the threshold cannot be distinguished from drift”, and “inside the threshold means indistinguishable”. Done when the checker scans every emitted role/caption/finding (including generated JSON or their source fields), rejects those formulations, and every screening outcome says only that an effect is or is not demonstrated relative to the observed-discrepancy screening threshold.
4. **Correct temporal calculations (R5, R6) — LANDED (`3205625`).** Actual frequency-cell widths are integrated and each temporal artifact records the timestamp statistics, quantitative criterion and estimator decision. The semantic cleanup still owed for temporal “floor / inseparable” language belongs to reopened step 3, not to the numerical method.
5. **Complete grouped-realization evidence (R1, R4) — REOPENED after first regeneration (`59c852a`).** Keep the grouped bytes and counts, but make every definition, limitation, module description and caption agree with them: most non-reference levels have one recording; the shared reference level has two realizations; this is one duplicated setting, not replicated coverage of an axis. Add a shared validator that rejects “one recording per setting/level”, “each level is one recording”, and “no level is replicated” whenever `multi_realization_levels` is non-empty. Regenerate each affected axis with its owning generator. Done when provenance lists both named reference paths at all five shared levels, the validator covers source and emitted prose, and no generated or hand-written evidence contradicts the grouped model.
6. **Correct resolution interpretations (R7, R8).** Rename the residual metric throughout code, tables, provenance, captions and decisions; demote the correlation scale. Done when neither quantity is used as a variance partition or primary physical-resolution argument.
7. **Redesign the decision layer (R3, R9).** Rebuild `decision-table.md` and `sparse-parameter-set.md` only from the corrected artifacts, choose and justify either a high-intermediate successive-increment design or an unconditional E128 point, and describe controls as correlated drift diagnostics. Done when every retained/new condition cites corrected evidence, the selected emissions design has an explicit rationale, and all condition/control/job counts agree programmatically.
8. **Rebind and verify everything.** In a dedicated documentation/data-binding commit after the generator and decision commits, update only the hand-written decision table's artifact hashes, the report README's binding list, provenance references and the PR body. Generated captions and figure bytes must already have been regenerated by their owning generator step and `data(analysis)` commit; step 8 never hand-edits them. Done when `.venv/Scripts/python.exe tools/validate_analysis_review_baseline.py --check-final` maps every changed hash to R1–R9 and its replacement, regeneration is byte-identical from the recorded revisions, links resolve, the tree is clean, and focused plus full gates pass.

### 8.4 Acceptance tests

The correction is complete only when all of the following are executable tests or mechanically checked records:

- `tests/test_burst_ladder.py`, `tests/test_gain_power_screen.py`, `tests/test_resolution_ladder.py` and `tests/test_prf_ladder.py`: adding a same-settings file under a different folder cannot exclude it from an eligible axis, and two files at one decoded level remain two named realizations rather than triggering the old duplicate-key refusal — exercised for every axis, with `prf/600.BDD` and `res/1-8.BDD` admitted as two realizations of the resolution-1.850 mm / PRF-600 µs / burst-10 / TGC-≈19.9216 dB / medium-power fingerprint where an axis analyses it;
- focused shared-input tests: perturbing each fingerprint field either changes identity or is explicitly allowlisted for that axis;
- mechanical text check over `src/`, `docs/` and `reports/`, including serialized role/finding/caption fields: no positive assertion uses `is an upper bound`, `as an upper bound`, `inside the bound`, `repeatability bound`, `repeatability envelope`, “smaller than this bound is not distinguishable”, “below the threshold cannot be distinguished from drift”, “inside the threshold means indistinguishable”, or the superseded name `observed discrepancy from the sole same-settings pair`; the canonical name is the only live name; §8.2's marked defect quotation and §5's labelled historical commit subject are exempt, and every screening outcome states that it neither establishes distinguishability, proves an axis effect nor bounds drift;
- grouped-realization prose validation: when an axis publishes a non-empty `multi_realization_levels`, its source and emitted definitions/findings/captions cannot say “one recording per setting/level”, “each level is one recording” or “no level is replicated”; each affected artifact instead distinguishes the one duplicated reference setting from replicated coverage of the axis;
- `tests/test_prf_ladder.py`: band integration agrees for equivalent spectra represented on unequal frequency grids;
- provenance-schema tests: `reference-repeat`, burst and PRF temporal artifacts each carry median Δt, Δt IQR, RMS deviation, maximum deviation, the quantitative criterion and the estimator decision;
- resolution tests and repository text check: the residual is named as a normalized reconstruction residual and correlation length as descriptive only;
- decision-table validation: the selected emissions design is exactly one of the two allowed alternatives, contains its rationale, never infers plateau from E64 versus E20 alone, and its counts agree with the condition rows;
- R9 text check over `docs/`, `src/` and `reports/`: the beginning/middle/end controls are named `within-run reference controls` for the single reference condition, and no live text calls them or their differences “independent references” or independent observations; the decision table and sparse set describe adjacent control differences as correlated (the retired phrases are quoted here, not used);
- the baseline/rebinding validator: regenerated artifact hashes, row counts, generator revisions, correction IDs and decision-table bindings agree programmatically.

### 8.5 Delegation and integration design

The coordinator first freezes the branch revision and lands the shared contracts: the expanded R2 terminology
checker and the grouped-realization prose validator. No delegated worker may edit, switch branches, commit or
regenerate while those contracts are moving. After that serial prerequisite, use four non-overlapping axis
workstreams:

| Workstream | Owned source/test files | Owned generated outputs |
|---|---|---|
| resolution | `resolution_ladder.py`, `tests/test_resolution_ladder.py` | resolution levels/pairs/provenance/figure |
| PRF | `prf_ladder.py`, `tests/test_prf_ladder.py` | PRF levels/pairs/provenance/figure |
| burst | `burst_ladder.py`, `tests/test_burst_ladder.py` | burst levels/pairs/provenance/figure |
| TGC/power | `gain_power_screen.py`, `tests/test_gain_power_screen.py` | gain/power depths/levels/pairs/provenance/figure |

Each delegated worker receives the frozen revision, exact file set, required red-first cases and recorded
generator command; it may edit only its source/test pair and must report stale statements elsewhere rather than
touch them. Generated outputs are never hand-edited and are not produced concurrently in a shared worktree:
after reviewing each worker's source/test patch, the coordinator integrates the four patches serially, reruns
focused tests, then runs each owning generator serially and commits that axis's generated bytes separately.

`_native_grid.py`, `tools/check_screening_terms.py`, the baseline validator/record, this plan,
`decision-table.md`, `sparse-parameter-set.md`, the report README and the PR body are single-writer coordinator
files. Step 6 starts only after the step-3/5 integration gate is green; step 7 starts only after all corrected
WP1/WP2 artifacts exist. The coordinator re-runs every child-reported test, checks the changed-file set, scans
the generated provenance itself, and alone performs commits, pushes and PR edits.

### 8.6 Commit boundaries

Keep the review legible: one commit for the durable ruling (this section), then one tested commit for each
numbered implementation step above. Generated artifacts follow their generator correction in a separate
`data(analysis): ...` commit. Corrected evidence lands before WP3/WP4 decisions. Step 8 then gets its own scoped
`docs(analysis): rebind corrected evidence` commit, which may change only binding hashes/revisions and links in
the hand-written decision table and report README plus the PR body; generated captions and figures belong to
their generator's `data(analysis)` commit. Any scientific verdict change belongs to step 7, not rebinding.

### 8.7 Picking this up cold

```text
git switch analysis/existing-sweep-plan
git status --short --branch
git pull --ff-only
```

Read this section first, then `_native_grid.py` selection/fingerprint code, the affected axis module and its
tests, and finally the current report artifact that module generates. Start at §8.3 item 3 and stop at the
first item whose done condition is not met. Before each commit run its focused tests; before rebinding
artifacts run:

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check src tests tools
.venv/Scripts/python.exe tools/check_screening_terms.py
.venv/Scripts/python.exe tools/validate_analysis_review_baseline.py --check-final
```

Do not start acquisition, encode the provisional sparse set as a campaign, or merge PR #24 until §8.4 is
fully satisfied. If a correction changes the proposed condition set, update the decision table first and let
`sparse-parameter-set.md` follow it; never preserve the old count by construction.
