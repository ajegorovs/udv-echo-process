# Existing mixer sweep analysis — work plan

> **Status:** executable work plan. This plan gates the candidate matrix in
> [`sparse-parameter-set.md`](sparse-parameter-set.md): its candidate levels are hypotheses until the
> existing 40 velocity recordings have been analysed. No new instrument acquisition belongs to this
> plan until the existing-data decision table is complete.
>
> **State — analysis corrections landed; WP4 reopened by review of `8ef9b63`.** Steps 1-8 of §8.3 have
> landed: the baseline freeze (`7c4c187`), the setting-based fingerprint and level-group model
> (`c128b34`), the screening-reference semantics (`91e6036`, prose contract `3b7d7b0`), the PSD
> integration and timestamp accounting (`3205625`), the grouped-realization evidence (`1c5ed0c`), the
> corrected resolution interpretations (`f5fbc5b`) and the rebuilt decision layer (`b3f2ae0`). Every
> generated artifact now carries grouped counts and screening-reference-only prose, and the decision
> table is rebuilt from those bytes and the final rebinding landed at `8ef9b63`. The subsequent narrow
> review found two acquisition-design blockers and one residual R2 wording issue: the six-job schedule
> cannot place a true burst-10/emissions-20 reference inside five jobs whose burst or emissions value is
> run-wide; D1 is encoded at the reference sensitivity rather than one step higher; and resolution still
> describes the sole-pair screening reference as a detection limit. Section 9 is now the authority. No
> acquisition or implementation starts until its plan-only correction is reviewed.
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
| emissions/profile | establish that the axis is absent from the old sweep; 8/20/64 is only the initial bracket, and the corrected decision layer must either add a high-intermediate successive-increment point before deciding on 128 or make 128 an ordinary sparse point — **decided by step 7 (`b3f2ae0`): E128 is an ordinary sparse point** (`decision-table.md` §3) |
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

**Accepted by step 7 (`b3f2ae0`).** `reports/mixer-sensitivity-analysis/decision-table.md`
exists, with seven columns exactly as named above, one row per candidate condition of the sparse-set draft
plus explicit rows for the four introduced pitch × burst corner conditions, the one reference condition
(realized by the within-run reference controls) and the draft's two excluded axes. It is hand-written and
pinned by SHA-256 to the 22 committed artifacts it reads, and `tools/validate_decision_layer.py` derives
every condition/control/job count from its rows. Its earlier claim to meet the gate through
`sparse-parameter-set.md` §2-§3 — the 17-condition candidate list replaced by 7 unique new conditions, no
level retained for feasibility reasons — is superseded: the corrected table carries **eight unconditional
new conditions** (CC1-CC4, E8, E64, E128, D1) and **26 first-pass recordings**, with E128 an ordinary sparse
point. The job split and the control construction that produced that total were reopened by §9: the executable
schedule is **five scientific jobs** each repeating its own anchor as block-local controls, plus **four separate
common-reference jobs**, so the corrected total is **nine executable jobs** and the 26 survives only as a newly
derived coincidence (§9.2).

### WP4 — Design only the missing measurements

The provisional augmentation, subject to WP3, is:

- the reference condition, realized as within-run reference controls at the beginning, middle and end of each randomized/blocked run;
- pitch × burst corners at 0.617 and 2.960 mm crossed with 4 and 18 cycles;
- emissions/profile 8 and 64 around the existing 20 as the initial bracket; the corrected decision layer must
  either add a high-intermediate point and judge successive high-end increments before 128, or include 128 as
  an ordinary sparse point — **decided by step 7: 128 is an ordinary sparse point** (`decision-table.md` §3);
- one higher-sensitivity diagnostic, extending lower only if it changes validity or distribution;
- an echo/energy diagnostic before declaring the TGC/power dynamic-range window safe;
- PRF 250 µs only if the committed 400-µs rung shows inadequate headroom (600 µs remains the shared reference period).

Gate: every new acquisition closes a named information gap; no Cartesian product.

**Accepted by step 7 (`b3f2ae0`).** The design is recorded in `sparse-parameter-set.md` §3 and
`decision-table.md` §6-§8: the four crossing corners, the emissions series E8/E20/E64/E128 all
unconditional, the one higher-sensitivity + echo/energy diagnostic, the within-run reference controls and
the PRF deferral. The exact set and count are fixed by those two documents and their shared validator
(`tools/validate_decision_layer.py`), not by this paragraph, and nothing here freezes a condition ahead of
the corrected WP1/WP2 evidence.

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

**Where each condition stands after review.** The 22 generated artifacts plus the hand-written decision table and
report README remain the 24-item report baseline that §8.3 item 1 recorded; step 8 rebinds it rather than
replacing it. The corrected design carries **eight unconditional new conditions** — seven of them executable in
**five scientific jobs**, each with **3 block-local control recordings** at that job's own run-wide values, plus
**four separate common-reference jobs** with one recording each, and the blocked D1 diagnostic — **nine executable
jobs** and **26 first-pass recordings**, counts derived from the condition rows by
`tools/validate_decision_layer.py`. The superseded 7-unique-condition (8 with the conditional E128) draft numbers
are not preserved by construction, and neither is the superseded six-job schedule that reached 26 by placing
three reference-condition recordings inside every run (§9.2).

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
3. **Complete WP1 screening semantics (R2) — LANDED (`91e6036`; prose contract `3b7d7b0`).** Replace `ScreeningThresholdBinding.role` with a screening-reference-only statement and apply it to spatial and temporal uses. Extend the checker with regression cases matching the retired phrases “smaller than this bound is not distinguishable”, “below the threshold cannot be distinguished from drift”, and “inside the threshold means indistinguishable”. Done when the checker scans every emitted role/caption/finding (including generated JSON or their source fields), rejects those formulations, and every screening outcome says only that an effect is or is not demonstrated relative to the observed-discrepancy screening threshold.
4. **Correct temporal calculations (R5, R6) — LANDED (`3205625`).** Actual frequency-cell widths are integrated and each temporal artifact records the timestamp statistics, quantitative criterion and estimator decision. The semantic cleanup owed for temporal “floor / inseparable” language belonged to step 3 (`91e6036`), not to the numerical method.
5. **Complete grouped-realization evidence (R1, R4) — LANDED (`1c5ed0c`; grouped bytes regenerated at `59c852a`).** Keep the grouped bytes and counts, but make every definition, limitation, module description and caption agree with them: most non-reference levels have one recording; the shared reference level has two realizations; this is one duplicated setting, not replicated coverage of an axis. Add a shared validator that rejects “one recording per setting/level”, “each level is one recording”, and “no level is replicated” whenever `multi_realization_levels` is non-empty. Regenerate each affected axis with its owning generator. Done when provenance lists both named reference paths at all five shared levels, the validator covers source and emitted prose, and no generated or hand-written evidence contradicts the grouped model.
6. **Correct resolution interpretations (R7, R8) — LANDED (`f5fbc5b`).** Rename the residual metric throughout code, tables, provenance, captions and decisions; demote the correlation scale. Done when neither quantity is used as a variance partition or primary physical-resolution argument.
7. **Redesign the decision layer (R3, R9) — LANDED (`b3f2ae0`).** Rebuild `decision-table.md` and `sparse-parameter-set.md` only from the corrected artifacts, choose and justify either a high-intermediate successive-increment design or an unconditional E128 point, and describe controls as correlated drift diagnostics. Done when every retained/new condition cites corrected evidence, the selected emissions design has an explicit rationale, and all condition/control/job counts agree programmatically.
8. **Rebind and verify everything — LANDED locally (rebinding commit; the PR body and push are coordinator-owned).** In a dedicated documentation/data-binding commit after the generator and decision commits, update only the hand-written decision table's artifact hashes, the report README's binding list, provenance references and the PR body. Generated captions and figure bytes must already have been regenerated by their owning generator step and `data(analysis)` commit; step 8 never hand-edits them. Done when `.venv/Scripts/python.exe tools/validate_analysis_review_baseline.py --check-final` maps every changed hash to R1–R9 and its replacement, regeneration is byte-identical from the recorded revisions, links resolve, the tree is clean, and focused plus full gates pass.

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

### 8.8 Step 8 rebinding map (correction → baseline items)

Step 8 binds each changed baseline item to **exactly one primary correction** — the §8.2 ruling whose landing
dominates that item's bytes. The mapping lives in
`reports/mixer-sensitivity-analysis/review-correction-baseline.json` (`corrections[].mapped_items`), beside
the preserved freeze (`sha256`, `generator_revision`, `generator_command`) and the `replacement_sha256` of the
current bytes; `tools/validate_analysis_review_baseline.py --check-final` refuses a changed item without a
mapping, a recorded correction without a mapped item, and a replacement that is not the tree's bytes.

| Correction | Ruling (§8.2) | Primary items |
|---|---|---|
| R1 | setting-based anchors and grouped realizations | `resolution-levels.csv`, `burst-levels.csv`, `burst-pairs.csv`, `prf-levels.csv`, `gain-power-levels.csv`, `gain-power-pairs.csv`, `gain-power-depths.csv`, `figures/prf-ladder.png`, `figures/gain-power-screen.png` |
| R2 | sole-pair observed-discrepancy screening semantics | `figures/reference-repeat.png`, `figures/burst-ladder.png` |
| R3 | emissions extension (unconditional series) | `README.md` |
| R4 | complete OFAT identity / fingerprint | `burst-ladder.provenance.json`, `gain-power-screen.provenance.json` |
| R5 | PSD integration | `prf-pairs.csv`, `prf-ladder.provenance.json` |
| R6 | timestamp jitter | `reference-repeat.provenance.json` |
| R7 | residual variance naming | `resolution-pairs.csv` |
| R8 | spatial scale demotion | `resolution-ladder.provenance.json`, `figures/resolution-ladder.png` |
| R9 | within-run reference controls | `decision-table.md` |

The three artifacts that did not move (`manifest.csv`, `qc-summary.json`, `reference-repeat.csv`) carry
neither a correction nor a replacement, and a replacement recorded for an unchanged artifact is itself a
failure. Both hand-written documents carry a binding list that names every generated item at the bytes now on
disk, and `--check-final` re-checks them, so the record and the documents cannot disagree about the tree.

## 9. Review of `8ef9b63` — WP4 schedule correction plan

This section records the next review round as a plan only. It deliberately changes no generator, validator,
decision row, sparse-set row, count, report artifact or acquisition code. The eight-condition scientific set
remains provisional while its executable schedule is redesigned.

### 9.1 Adjudication

| Finding | Verdict | Repository evidence | Plan consequence |
|---|---|---|---|
| A true reference condition cannot occur inside five run-wide jobs | **Confirmed blocker.** `CampaignDefinition` carries `emissions_per_profile` and `burst_length` once for the whole campaign, and its contract says every point records with those values (`acquire/campaign.py::CampaignDefinition`). The point writer changes resolution and gates, not those run-wide fields. A burst-4/18 or emissions-8/64/128 job therefore cannot also contain burst-10/emissions-20 REF-CTRL points. | `src/udv_echo_process/acquire/campaign.py` lines 232-263; `actuator.PARAMETER_WRITE_ORDER`; the rows in both WP3/WP4 documents. | Reopen WP4's job/control schedule and every derived count. Do not call a block-local repeated condition a common reference control. Do not claim 26 recordings are executable. |
| D1 is encoded at `sensitivity = medium` | **Confirmed blocker.** Both machine-readable tables encode D1 with the same sensitivity as REF-CTRL while their prose asks for one step higher. No repository evidence establishes the application's canonical next label or value. | D1 and REF-CTRL rows in `decision-table.md` and `sparse-parameter-set.md`; `tools/validate_decision_layer.py::REFERENCE_PARAMETERS`. | Read the exact next value from the application's sensitivity dialog before editing the rows. D1 must differ from the reference and equal that approved value; a prose placeholder is not a machine-readable condition. |
| Resolution still says smaller effects are invisible / cannot be resolved | **Confirmed semantic overstatement.** `_FOCUS_VERDICT` and `_COARSEST_VERDICT` still turn one observed same-settings discrepancy into a detection limit. | `src/udv_echo_process/analysis/resolution_ladder.py` `_FOCUS_VERDICT`, `_COARSEST_VERDICT`. | Replace only the inference: the current single-repeat evidence does not support distinguishing the difference from the observed same-settings discrepancy. Regenerate the owning resolution artifacts and add exact regression cases for `invisible` and `cannot resolve`. |

The review's positive findings are accepted without reopening them: grouped realizations, R7/R8 metric meaning,
PSD integration, timestamp accounting, unconditional E128 and the R1-R9 historical replacement record remain
the basis of the correction. The defect is concentrated in the executable WP4 schedule plus the two escaped
R2 sentences.

### 9.2 Schedule decision

The correction will **not** implement per-point burst or emissions writers merely to preserve the old control
count. The design must first describe what today's writer surface can execute:

| Block | Scientific rows | Run-wide value |
|---|---|---|
| `burst-4` | CC1, CC3 | burst = 4; emissions = 20 |
| `burst-18` | CC2, CC4 | burst = 18; emissions = 20 |
| `emissions-8` | E8 | burst = 10; emissions = 8 |
| `emissions-64` | E64 | burst = 10; emissions = 64 |
| `emissions-128` | E128 | burst = 10; emissions = 128 |
| D1 | not executable: scientifically selected at the operator-approved `high` (§9.3) and blocked until the sensitivity write/read path and the echo/energy surface exist; belongs to no executable job | reference burst/emissions; sensitivity `high`, intentionally non-reference |

Two different controls must remain different in names, rows and analysis:

1. **Block-local controls** hold each block's run-wide burst/emissions value and repeat the block's chosen anchor.
   They diagnose within-block drift only. For burst blocks the anchor is the reference spatial window
   (1.850 mm, 50 gates) at burst 4 or 18; for a one-condition emissions block the repeats are repetitions of
   that emissions condition itself. They are not the common reference condition and must not be screened as
   if all were burst 10 / emissions 20.
2. **Common-reference checks** use the true reference condition (1.850 mm, 50 gates, burst 10,
   emissions/profile 20, sensitivity medium) in separate reference-only jobs, intended to be executed between
   consecutive scientific jobs. They are between-job checks, not beginning/middle/end controls inside another
   run. Their count and job identity must be explicit machine-readable rows before a recording total is declared;
   the intended execution placement is a run-plan requirement that the row table does not encode, and it belongs
   to the campaign-definition/run-plan PR (see §10).

Neither order is expressed by the rows, and the two are different problems. **Within-job** placement — a
block-local control at the beginning, one around the middle and one at the end of a run — is a
definition-authoring rule, because `CampaignDefinition` executes its point order literally. **Cross-job**
placement spans several jobs, so no single definition can carry it: the run-plan PR must add an explicit
run-level ordering mechanism (a run plan, a job-sequence manifest or an orchestration document consumed by the
runner or the operator workflow) and test it.

The committed 19.3701 mm/s quantity remains a historical sole-pair observed-discrepancy screening reference.
It is not automatically a pass/fail threshold for block-local controls taken at different burst or emissions
settings. The redesigned analysis must report block-local observed discrepancies directly, use common-reference
checks only for the true common condition, and avoid claiming either control type estimates drift statistically.

All totals are reopened. `unique_new_conditions`, executable versus blocked conditions, block-local control
recordings, common-reference checks, jobs and first-pass recordings must be derived from the revised rows. The
validator must reject the old `REF-CTRL | every-run` representation and any prose-only total.

### 9.3 D1 value-discovery gate — closed by the operator's own observation

**The gate is closed, and not by a guessed code value.** The operator read the sensitivity choices from the
application's own sidebar sensitivity dropdown and recorded the exact canonical option immediately above
`medium` as **`high`**; the dialog was then restored and **no data was recorded**. That is an observation of the
application's own vocabulary — not an invented enum, index or constant, and not an acquisition — and the
repository itself still establishes only `medium`.

`high` is therefore the machine-readable D1 value in both documents, and the decision-layer validator asserts all
of the following:

- `D1.sensitivity != <reference sensitivity>` (the reference condition stays `medium`);
- `D1.sensitivity == 'high'` — the operator-approved value may be written no other way, so an unapproved value is
  refused rather than silently accepted;
- every non-D1 scientific condition retains `medium`;
- D1 is counted as scientifically selected but **not executable** (`executable = no`, no executable job, no
  executable total) until both the sensitivity write/read path and the echo/energy recording surface exist.

### 9.4 Corrected implementation order

1. **Land this plan-only ruling.** Update the PR body to changes-requested/draft state; do not edit WP3/WP4 or
   analysis code in this commit.
2. **Close the residual R2 semantics.** Add red-first cases for `would be invisible` and `cannot resolve`, change
   the two resolution verdicts to screening-reference-only wording, run the resolution generator, and commit the
   source/tests/owned resolution artifacts together so byte-reproduction stays green.
3. **Record the real D1 sensitivity value.** This is an operator observation from the application dialog, not a
   guessed code value and not an acquisition. Stop if it is unavailable.
4. **Rebuild WP4 rows and schedule.** Replace `REF-CTRL | every-run` with explicit block-local and separate
   common-reference rows; mark D1 selected-but-blocked; derive every count and update both hand-written documents
   from the same row schema. This step changes no writer.
5. **Strengthen the decision validator.** Reject run-wide contradictions within a job, a common-reference row
   inside a non-reference block, D1 at reference sensitivity, unapproved D1 vocabulary, D1 in executable totals,
   and any declared count that differs from the rows. Require explicit control kind (`block-local` or
   `common-reference`) and block/run-wide values.
Steps 4 and 5 land in one schedule/validator commit (the row schema, both hand-written documents, the validator
and its focused tests); step 6's final rebinding and the PR body stay coordinator-owned, so no count in this plan
is authoritative ahead of the rows.

6. **Rebind and request the narrow final review.** Refresh only the affected hand-written hashes and generated
   resolution bindings, update the correction register without rewriting the frozen baseline, run every gate,
   then update the PR body with a finding-to-commit table.

### 9.5 Acceptance criteria

- a programmatic schedule check proves every row in a job agrees on run-wide `burst_cycles` and
  `emissions_per_profile`;
- no block-local row is named or analysed as the common reference condition;
- common-reference checks occur only in explicit reference-only jobs and are described as between-job checks;
- the old executable claims — six executable jobs, three true references inside every job, and 26 first-pass
  recordings — are absent unless newly derived rows genuinely reproduce them;
- D1 differs from medium by the operator-approved canonical next value and is excluded from executable totals
  while either prerequisite is missing;
- `resolution_ladder.py`, regenerated provenance/caption/figure text and hand-written consumers contain no live
  positive inference that a below-screening difference is `invisible`, `cannot resolve`, `indistinguishable` or
  `unresolvable`; negated defect history remains marked history;
- `.venv/Scripts/python.exe -m pytest -q`, Ruff, the screening checker, decision-layer validator and baseline
  `--check-final` all exit zero at a stationary HEAD;
- no acquisition runs as part of this remediation.

### 9.6 Delegation and commit boundaries

Keep the shared row schema, validator, plan, decision table, sparse set, README, correction register and PR body
single-writer. The resolution semantics slice owns `resolution_ladder.py`, its focused tests and its four generated
artifacts. The schedule slice starts only after the exact D1 value is recorded — now recorded as `high` (§9.3), and
the value stays coordinator-owned — owns only the two hand-written decision documents plus the validator and
its focused tests, and must not add writers. Final rebinding remains coordinator-owned.

Use one commit for this ruling, one atomic tested resolution source/test/artifact commit, one decision-layer
schedule/validator commit, and one final rebinding commit. The reviewed head `8ef9b63` remains the comparison
boundary; no implementation belongs in the ruling commit.

### 9.7 As landed after the review of `8ef9b63`

| Work | Commit | Result |
|---|---|---|
| residual R2 resolution semantics | `f103d8b` | source and provenance now use observation-only screening-reference wording; focused regressions cover generated and hand-written consumers |
| executable WP4 schedule and validator | `99e86c1` | D1 is `high` and blocked; five scientific jobs, fifteen block-local recordings and four separate common-reference jobs derive nine executable jobs and 26 first-pass recordings |
| adversarial findings and final rebinding | `626f165` | pins block identity, run-wide values, anchors, non-D1 sensitivity and D1's block; corrects README prose; refreshes the provenance and hand-written hashes |

No acquisition or writer change is part of these commits. At `626f165`, the full suite reports **2210 passed,
22 skipped**; Ruff, the screening checker, decision-layer validator and baseline `--check-final` all exit zero.
The implementation items in §9.4 are complete; the PR remains a draft only until the final narrow review is
requested.

## 10. Review of `2ddf672` — repeated-realization semantics and execution-order claims

The review of `2ddf672` (the five commits after `8ef9b63`) confirmed both earlier blockers as resolved and raised
two findings: the repeated-measurement semantics of the block-local controls contradict the rows, and the
validator's common-reference rules prove cardinality while the documents read as though placement were proven.
This section records the round's adjudication, its commits and the interpretation that survives it. No acquisition
runs, no writer surface changes, and no ordering implementation lands in any of these commits.

### 10.1 Adjudication

| Finding | Verdict | Repository evidence | Consequence |
|---|---|---|---|
| The emissions blocks' "block-local controls" are replicate measurements of E8/E64/E128, but the documents say they are not | **Confirmed, and half-diagnosed.** The rows give each emissions level four same-setting acquisitions inside one run, so the claim that "the axis stays one recording per level" and that those controls "do not replicate a condition" is false for it. The document contradicts *itself* rather than merely understating the design: §3.2 of the same document, decision-table §8.2 and §9.2 of this plan already called those repeats repetitions of that emissions condition. | the §3.1 / §8.2 rows in both documents; `sparse-parameter-set.md` §3.2 against §3.4, §4 and §8; `decision-table.md` §3 | Delete the false branch at all three sites and state the row-derived facts: four same-setting acquisitions per emissions level inside one run; within-run repeated measurement, not independent run-level replication; the burst controls are new realizations of the already-committed burst-4 and burst-18 conditions rather than duplicates of CC1-CC4; and the no-plateau-test verdict rests on level/run confounding instead of on a count of recordings. The validator derives the same-setting pairs from the rows and refuses singular-coverage prose while any exist. |
| The common-reference rules prove the intended jobs exist, but not their temporal ordering | **Confirmed, and narrower than stated.** Moving all four `CR*` rows to the bottom of both tables leaves the validator green (measured: exit 0, "the WP4 schedule is executable and its counts agree"), while collapsing their four job ids onto one makes it fail (measured: exit 1, 8 × `schedule-common-reference-block`). The rows never claimed to encode sequence — §6 already assigns point order to the definition — but §9.2's "placement … must be explicit machine-readable rows" was only half met. | `tools/validate_decision_layer.py::_schedule_rules`; both row tables; §6's `already covered` row | The validator's rule comments and messages state what they prove (four distinct reference-only jobs, one recording each); the documents state that the rows encode membership, run-wide compatibility, control type and counts but not execution sequence; within-job placement and cross-job placement are deferred to the campaign-definition/run-plan PR. No sequence column is added — the schema pins its columns and the acquisition order is a run-plan fact. |
| The two earlier blockers (`8ef9b63`) really are closed | **Confirmed.** D1 is `high`, `executable = no` and job `none`; a job whose rows disagree on run-wide `burst_cycles` or `emissions_per_profile` is refused; the counts are derived from the rows (7 scientific + 15 block-local + 4 common-reference = 26 recordings across 9 executable jobs). | `sparse-parameter-set.md` §3.1 row `D1`; `_schedule_rules`; §3.3 counts | None — recorded so a later round does not re-open them. |

### 10.2 As landed

| Work | Commit | Result |
|---|---|---|
| repeated-realization semantics and their validator rule | `82ae499` | both documents state the four same-setting acquisitions per emissions level, the burst anchors' re-acquisition of the committed conditions and the confounding justification of the no-plateau-test verdict; `repeated_realizations()` derives the pairs from the rows and `_repeated_realization_rules()` refuses singular-coverage prose while any exist |
| execution-order deferral | `7b70d9a` | the validator states that it proves four distinct reference-only jobs and one recording each; both documents state that the rows encode membership, settings and counts but not execution sequence; the within-job/cross-job distinction and the run-level ordering mechanism the next PR must add are recorded above |
| this record and the rebinding | this commit | the round is recorded here and `decision-table.md`'s replacement hash is refreshed in `review-correction-baseline.json` |

### 10.3 Interpretation that survives this round

- **Within-run repeated measurement is not independent run-level axis replication.** E8, E64 and E128 each
  receive four same-setting acquisitions inside one run, and every new level is confined to its own run, so level
  and run are confounded and no between-level displacement can be separated from the difference between the two
  runs that carry it. The repeats sharpen each level's own within-run measurement; they do not replicate the
  emissions axis.
- **The only condition the first pass observes in more than one distinct run is the common reference**: four
  reference-only jobs carrying one acquisition each, beside §1's two committed realizations of the same condition.
- **The burst block-local controls re-acquire already-committed conditions.** They repeat the reference spatial
  window at burst 4 and 18 — `burst_len/4.BDD` and `burst_len/18.BDD` — inside the new runs, and they are not
  duplicates of CC1-CC4, which move resolution and gate count.
- **Execution order is not encoded by the WP4 rows.** Within-job beginning/middle/end placement and the cross-job
  placement of the common-reference jobs are requirements the campaign-definition/run-plan PR must encode and
  test; the row table answers membership, run-wide compatibility, control type and count only.
- **The frozen record is a current-bytes binding, not a per-round audit.** `review-correction-baseline.json`
  admits only the correction ids R1-R9 of §8.2, so the one hand-written item whose bytes moved keeps the
  correction id it carries (`R9`) and only its `replacement_sha256` is refreshed. No generated artifact changed,
  so no `sha256`, `generator_revision` or `generator_command` in the record was touched.

### 10.4 Gates re-run for this round

    .venv/Scripts/python.exe -m pytest -q
    .venv/Scripts/python.exe tools/validate_decision_layer.py
    .venv/Scripts/python.exe tools/check_screening_terms.py
    .venv/Scripts/python.exe tools/validate_analysis_review_baseline.py --check-final
    ruff check .

measured at this commit: `.venv/Scripts/python.exe -m pytest -q` → **2216 passed, 22 skipped** in 173.06 s;
`tools/validate_decision_layer.py` → exit 0, "the WP4 schedule is executable and its counts agree";
`tools/check_screening_terms.py` → exit 0, "the text names the quantity and no live claim survives";
`tools/validate_analysis_review_baseline.py --check-final` → exit 0, "the tree is the frozen baseline";
`ruff check .` → all checks passed. Worktree clean, no generated artifact regenerated, no acquisition run.

### 10.5 Approval of `945464f` — the round's close

The review of `945464f` reports no remaining merge blocker and accepts the round's abstraction, its
interpretation and its scope (§10.1–§10.3 stand as written). It raises qualifications to carry forward rather
than to act on, and each has a disposition here so a later session does not re-open a settled question:

| Qualification | Disposition |
|---|---|
| The top-level validator docstring still read "the reference condition gets its own jobs, one between each pair of scientific jobs", against §10's clarification that placement is not encoded | **Corrected in this commit**, in the reviewer's own suggested form: four distinct reference-only jobs, whose intended placement between consecutive scientific jobs is a run-plan requirement the table does not encode |
| Violation granularity — one message per derived repeat per offending sentence (three for one claim on this schedule) | **Deliberate non-change.** The reviewer prefers the present behaviour because it names E8, E64, E128 and the control rows behind each. Revisit only if a much larger design makes the output noisy |
| `tools/validate_decision_layer.py` is no longer a standalone stdlib script, because it imports the shared `SINGULAR_REALIZATION_CLAIMS` | **Accepted.** The documented execution environment is the project `.venv`, and one canonical semantic vocabulary is worth more than two regex lists that can drift. If standalone operation is ever needed, the vocabulary moves to a dependency-light module — not a reason to delay this PR |
| Keeping the changed hand-written item under `R9` instead of introducing `R10` | **Confirmed by the reviewer**: the round refines the control and schedule semantics `R9` already governs, so §10 carries the round while the frozen `R1`–`R9` register stays intact |

The next PR is the campaign-definition/run-plan encoding and owns both orderings — the within-job
beginning/middle/end placement and the cross-job interleaving of the common-reference jobs — together with the
run-level mechanism §9.2 requires. This document's eight-condition scientific set is otherwise unchanged by
the round.

measured at this commit: `.venv/Scripts/python.exe -m pytest -q` → **2216 passed, 22 skipped**;
`tools/validate_decision_layer.py`, `tools/check_screening_terms.py` and
`tools/validate_analysis_review_baseline.py --check-final` → exit 0; `ruff check .` → clean.
