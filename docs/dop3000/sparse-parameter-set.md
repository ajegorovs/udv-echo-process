# The first sparse measurement set — the evidence-gated first augmentation

> **Status:** design, gated by measurement. This document is no longer a proposal: its candidate
> list has been decided by the committed velocity arrays through
> [`reports/mixer-sensitivity-analysis/decision-table.md`](../../reports/mixer-sensitivity-analysis/decision-table.md)
> (WP3 of [`existing-sweep-analysis-plan.md`](existing-sweep-analysis-plan.md)) and the set below is the WP4
> augmentation that table justifies. Nothing here is acquired yet, and nothing here re-reads the old data:
> every verdict behind it, with the artifact and SHA-256 it comes from, is in the decision table.
>
> **What it answers.** [`acquisition-closeout-plan.md`](acquisition-closeout-plan.md) §4 makes the matrix
> question the gate for the next stretch: *is `experiment_data\mixer\sensitivity-analysis\4MHz\0500RPM\001`
> the experiment this work is for?* This document answers **yes at the axis level** and names the small
> explicit set the first measured pass consists of, so §4's dependent decisions (which writers are funded,
> whether the application's own `Sweep PRF` search is an axis) settle against the measured decisions rather
> than against a principle.
>
> **Grounded in:** the DOP3000/3010 manual (`manual-reference/`, cited as *Ch. N* through
> [`parameter-sweep-matrix.md`](parameter-sweep-matrix.md)); the 40 committed `.BDD` recordings of the 4 MHz
> 500-RPM reference run and the corrected grouped WP0-WP2 reports regenerated from them; the relations of
> [`parameter-sweep-matrix.md`](parameter-sweep-matrix.md) §2-§3 and its §9 reader coverage; the write
> surface of [`src/udv_echo_process/acquire/`](../../src/udv_echo_process/acquire/); and the WP3 decision
> table named above.

## 1. The reference condition — fixed facts of the whole augmentation

The instrument's own decoded values for the reference recording (`res/1-8.BDD` / `prf/600.BDD`), which every
new condition holds unless its row says otherwise. The stored `.BDD` file remains the authority for the
achieved values, and nothing below is assumed where the file can be read.

| Parameter | Value | Evidence |
|---|---:|---|
| emitting frequency | 4 MHz | 40/40 manifest rows (`emit_freq_khz` 4000) |
| PRF period | 600 µs | `prf/600.BDD`; the period the entire augmentation holds |
| sound speed | measured/read-back (≈1480 m/s in the committed set) | `sound_speed_ms` 1480 in all 40 rows |
| Doppler angle | 0 | all 40 rows |
| first gate | ≈10.163 mm | 10.1626666667 mm in all 40 rows |
| observation window | ≈10.163-96.743 mm, held while pitch changes and gates compensate | plan §2; `resolution-levels.csv` common support |
| resolution | 1.850 mm, gates 50 | `res/1-8.BDD` |
| burst length | 10 cycles | reference; the committed `burst_len` folder has no 10-cycle file |
| emissions/profile | 20 | word 14 in all 40 rows, corroborated by the time base |
| emitting power | medium | all 40 rows |
| TGC | ≈20 dB uniform: word 23 = 0 (`uniform`), word 25 = 255 (fixed 40 dB end), word 24 start 19.9216 dB | matrix §8; `gain-power-screen.provenance.json` `definitions.tgc_representation` |
| sensitivity | medium, except the one blocked D1 diagnostic at `high` (§3.1) | all 40 rows; the axis is absent from the committed sweep |
| velocity scale | 1 | plan; fixed unless quantisation becomes a question |
| assisted mode / filtering during acquisition / alias auto-correction | OFF | the run's own recorded state |
| skipped profiles | 0 | word 84 = 0 in all 40 rows |
| sampling volume | read back only — word 27 is the instrument's bandwidth-list index (4), not a length, so `sampling_volume_mm` stays unset | plan §2; matrix §9 |

The reference condition is **one** condition. In the committed sweep it is realized by the two reference
recordings (`prf/600.BDD` and `res/1-8.BDD`); on every axis that analyses it the two are two named
realizations of one setting, and **one duplicated setting is not replicated axis coverage**: it repeats one
condition, it does not replicate a level, so no committed verdict is replicated axis evidence.

## 2. What the corrected evidence settles — the design rules this set obeys

1. **Do not reacquire 0.247 mm merely for finer pitch.** The corrected grouped resolution ladder puts **0 of
   the 78 pairs** above the sole-pair observed-discrepancy screening threshold: the focus pair
   `res/0-2.BDD` vs `res/0-6.BDD` differs by at most 6.1136 mm/s = **0.3156** of the 19.3701 mm/s screening
   threshold on 141 knots with 0 above it, the normalized reconstruction-residual variance is **0.000722**
   (0.0722 %), and the largest pair of the whole ladder is 17.368 mm/s = 0.8966 (1-2 vs 1-6). So only the
   resolution settings needed as reference/interaction corners are retained — **0.617 mm** and **2.960 mm**,
   crossed against burst corners (rule 6, §3.1) — and 1.233 mm is deferred rather than reacquired.
2. **The 18-versus-20 effect is not demonstrated, and no monotonic knee exists.** The corrected grouped burst ladder
   has 78 pairs, **22 of the 78** clear the screening threshold somewhere and 17 of those involve the two
   longest bursts, yet the focus pair `burst_len/18.BDD` vs `burst_len/20.BDD` differs by **0.6067** of the
   screening threshold with 0 of 50 knots above it, and the whole 16-20-cycle region remains below that
   screening reference (3 pairs,
   0 clearing, largest 0.6504). No metric along the 2-32-cycle ladder falls monotonically. The augmentation
   therefore carries **18 cycles**, chosen on cost and contrast alone (shorter pulse, equal measured
   information, two-sided spacing around the reference with 4 cycles) — an explicit information/cost
   rationale, **not** a claimed effect.
3. **Do not add PRF 250 µs.** The measured 400 µs point has adequate headroom and the widest bandwidth:
   peak load **0.7266** of the 231.2064 mm/s unambiguous limit, 0 samples at or beyond it, 0 wrap-like
   steps, usable bandwidth **33.3599 Hz** — the widest of the five, against 16.4678 Hz at 800 µs. A 250 µs
   setting would move the limit to 369.9302 mm/s, which nothing in this dataset asks for (the largest
   absolute velocity anywhere is 196.53 mm/s at `prf/500.BDD`).
4. **Emissions/profile is absent, so acquire E8, E64 and E128 as one unconditional series around the
   reference E20.** No committed recording varies the axis (all 40 rows carry 20), so its effect is
   unidentifiable today. The design takes the second allowed alternative of plan §8.2 R3: **E128 is an
   ordinary sparse point**, not an extension acquired on a trigger. See §3.4.
5. **Sensitivity is absent too, and velocity-only TGC/power data cannot establish SNR or saturation.**
   Request exactly **one** higher-sensitivity condition, recorded **with an echo/energy channel**, before
   any wider sensitivity, TGC or power ladder — the corrected screen flags 2 of the 12 screened levels for a
   dropout/spread it cannot attribute, and echo SNR, receiver saturation, a safe plateau and acoustic energy
   are not measurable in the committed files at all.
6. **Block-local controls at the beginning, middle and end of each scientific run, four separate
   common-reference jobs intended to run between the five scientific jobs, and no Cartesian product.** The only
   committed same-settings repeat is one pair, which is why every verdict in the decision table is screened
   rather than replicated. The crossing below is **2 pitches x 2 burst levels = 4 cells**; no other axis
   moves in any condition.

## 3. The first measured augmentation

### 3.1 Complete new conditions — the machine-readable rows

Eight unique conditions — sparse points, not a factorial design. Every condition is **unconditional**: there
is no trigger and no gated condition anywhere in the set. This is one **row set**, carried identically by
[`reports/mixer-sensitivity-analysis/decision-table.md`](../../reports/mixer-sensitivity-analysis/decision-table.md)
§8.2 and checked by `tools/validate_decision_layer.py`, which refuses the two documents if their rows differ.
Every column is machine-readable:

- `block` — the scientific block the row belongs to, or `common-reference` for the between-job checks;
- `job` — the run the row is recorded in. `CampaignDefinition` fixes `burst_length` and
  `emissions_per_profile` once for a whole campaign (`acquire/campaign.py`), so a job is a set of rows that
  agree on both, and `none` marks the one row that belongs to no executable job;
- `control_kind` — `block-local`, `common-reference`, or `none` for a scientific condition;
- `executable` — whether today's writer surface can record the row at all;
- `recordings` — the number of recordings the row contributes to its job.

| ID | kind | block | job | control_kind | resolution_mm | gates | burst_cycles | emissions_per_profile | sensitivity | conditional | executable | recordings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CC1 | unique-condition | burst-4 | burst-4 | none | 0.617 | 145 | 4 | 20 | medium | no | yes | 1 |
| CC3 | unique-condition | burst-4 | burst-4 | none | 2.960 | 31 | 4 | 20 | medium | no | yes | 1 |
| burst-4-CTRL | block-local-control | burst-4 | burst-4 | block-local | 1.850 | 50 | 4 | 20 | medium | no | yes | 3 |
| CR1 | common-reference | common-reference | common-reference-1 | common-reference | 1.850 | 50 | 10 | 20 | medium | no | yes | 1 |
| CC2 | unique-condition | burst-18 | burst-18 | none | 0.617 | 145 | 18 | 20 | medium | no | yes | 1 |
| CC4 | unique-condition | burst-18 | burst-18 | none | 2.960 | 31 | 18 | 20 | medium | no | yes | 1 |
| burst-18-CTRL | block-local-control | burst-18 | burst-18 | block-local | 1.850 | 50 | 18 | 20 | medium | no | yes | 3 |
| CR2 | common-reference | common-reference | common-reference-2 | common-reference | 1.850 | 50 | 10 | 20 | medium | no | yes | 1 |
| E8 | unique-condition | emissions-8 | emissions-8 | none | 1.850 | 50 | 10 | 8 | medium | no | yes | 1 |
| emissions-8-CTRL | block-local-control | emissions-8 | emissions-8 | block-local | 1.850 | 50 | 10 | 8 | medium | no | yes | 3 |
| CR3 | common-reference | common-reference | common-reference-3 | common-reference | 1.850 | 50 | 10 | 20 | medium | no | yes | 1 |
| E64 | unique-condition | emissions-64 | emissions-64 | none | 1.850 | 50 | 10 | 64 | medium | no | yes | 1 |
| emissions-64-CTRL | block-local-control | emissions-64 | emissions-64 | block-local | 1.850 | 50 | 10 | 64 | medium | no | yes | 3 |
| CR4 | common-reference | common-reference | common-reference-4 | common-reference | 1.850 | 50 | 10 | 20 | medium | no | yes | 1 |
| E128 | unique-condition | emissions-128 | emissions-128 | none | 1.850 | 50 | 10 | 128 | medium | no | yes | 1 |
| emissions-128-CTRL | block-local-control | emissions-128 | emissions-128 | block-local | 1.850 | 50 | 10 | 128 | medium | no | yes | 3 |
| D1 | unique-condition | sensitivity-diagnostic | none | none | 1.850 | 50 | 10 | 20 | high | no | no | 1 |

The fixed facts of §1 hold in every row; only the columns shown move. "§1" means every fixed fact of §1.

**These rows encode membership, run-wide compatibility, control type and counts — not execution sequence.** The
intended within-job order is a block-local control at the beginning of the run, the block's scientific points, a
block-local control around the middle and one at the end; the intended cross-job order places one
common-reference job between consecutive scientific jobs. Neither is proved by this table: the campaign runs a
definition's point order literally, and a cross-job order cannot be expressed by a single definition at all, so
the campaign-definition/run-plan PR must encode and test both (§6, §9).

**Why the crossing exists.** The resolution and burst ladders intersect **only at the reference**, so the
pitch x burst interaction is not estimable from the committed set at all. CC1-CC4 are the four corners that
make it estimable: each one completes a 2x2 whose other three corners are already committed
(`res/0-6.BDD`, `res/3-0.BDD` at burst 10; `burst_len/4.BDD`, `burst_len/18.BDD` at 1.850 mm; the
reference). Two pitches and two burst lengths only — this is a corner set, never a product of the design's
axes.

**Requested in mm, read back from the file.** The rung labels are the instrument's and a rung's mm value is
`c`-dependent, so every condition must be *requested* in mm and *read back* from word 10.
Nothing in this set may be identified by a folder name or a label.

**D1 is the one condition no writer can execute today.** Its sensitivity is `high` — the exact canonical
option immediately above `medium` in the application's own sidebar sensitivity dropdown, read from that
dialog and then restored without recording (plan §9.3) — and its echo/energy channel does not exist in the
recording surface yet (§6). It is therefore marked `executable = no`, carries the `none` job marker, belongs
to no executable job and enters no executable total. It is scientifically selected, not acquired.

### 3.2 Block-local controls and common-reference checks

The single committed repeat is why every verdict in the decision table is a screening comparison, and the
schedule answers it with two different things that have to stay different in names, rows and analysis:

- **Block-local controls** repeat each scientific job's **own anchor** at that job's run-wide burst and
  emissions values: three recordings at the beginning, middle and end of the run. For the two burst blocks the
  anchor is the reference spatial window (1.850 mm, 50 gates) held at burst 4 or 18 — the conditions the
  committed sweep already holds as `burst_len/4.BDD` and `burst_len/18.BDD` — so those controls are **not**
  duplicates of CC1-CC4, which move resolution and gate count: they are new realizations of an already-measured
  condition, acquired inside the new run. For a one-condition emissions block the three repeats carry **exactly
  the same settings as that block's designated scientific row**, so E8, E64 and E128 are each acquired **four
  times inside one run** (1 designated scientific acquisition + 3 block-local acquisitions). That is within-run
  repeated measurement of each level, never independent run-level replication of the emissions axis, because
  each level is confined to its own run. They diagnose within-block drift only, and **none of them is the common
  reference condition**: they are never
  screened as if every one were burst 10 / emissions 20. Their two **adjacent** differences (beginning→middle
  and middle→end) share the middle recording and are **correlated**, so neither is a separate observation of
  an anchor level. The only condition the first pass observes in more than one distinct run is the common
  reference itself: the four reference-only jobs carry one acquisition each, and §1's two committed
  realizations are the same condition.
- **Common-reference checks** are the true reference condition (§1) recorded **once** in each of four
  separate reference-only jobs whose intended execution placement is between consecutive scientific jobs — an
  ordering requirement the rows do not encode (§3.1). They are between-job checks of the
  one common condition, not beginning/middle/end controls inside another run, and §3.1's `common-reference`
  block, job and control kind say so in machine-readable form.

The name **within-run reference controls** is **no longer** used in this document: it called both types one
thing, and a job whose run-wide burst or emissions value is not the reference cannot hold reference-condition
recordings at all (`acquire/campaign.py::CampaignDefinition`). The replacement is exactly the pair of names
used above — block-local controls for a job's own anchor, common-reference checks for the true common
condition.

### 3.3 Counts, derived from the rows

The counts below are the counts of the §3.1 rows, not a preserved number: the validator
(`tools/validate_decision_layer.py`) recomputes every one of them from the table and refuses a document
whose declared value disagrees.

| count | value |
|---|---|
| unique_new_conditions | 8 |
| blocked_conditions | 1 |
| executable_scientific_recordings | 7 |
| block_local_control_recordings | 15 |
| common_reference_recordings | 4 |
| executable_jobs | 9 |
| recordings_first_pass | 26 |

Nine executable jobs under today's writers: the five scientific jobs (`burst-4`, `burst-18`,
`emissions-8`, `emissions-64`, `emissions-128`, one per distinct run-wide value) and the four
common-reference jobs whose intended placement is between consecutive scientific jobs. The first pass is
**26 recordings** — 7 executable scientific
recordings (CC1-CC4, E8, E64, E128), 15 block-local controls (3 per scientific job) and 4
common-reference checks (one per common-reference job) — and that 26 is a coincidence of this derivation,
never a preserved construction: the superseded six-job schedule reached the same number by placing three
reference-condition recordings inside every run, which today's writers cannot execute. Nine of the 15
block-local recordings re-acquire the same condition as their own block's designated scientific row (3 each in
the E8, E64 and E128 jobs); the other six re-acquire the already-committed burst-4 and burst-18 anchors at the
reference spatial window. D1 is the eighth
unique condition and the one blocked condition: it is counted as scientifically selected and in no
executable total.

### 3.4 The emissions design — one unconditional series, no plateau test

The emissions/profile axis is absent from the committed sweep, so it has no measured variation to decide
against. The design therefore acquires **E8, E64 and E128 as one unconditional series** around the reference
E20, in the order **E8, E20 (reference), E64, E128** — the second of the two alternatives plan §8.2 R3
allows. E128 is an ordinary sparse point of the same series, acquired with E8 and E64; the design makes every
condition unconditional.

**No E20-to-E64 displacement is called a plateau test.** Each emissions level is confined to one run, so level
and run are confounded: the within-run repeats of §3.2 characterize within-run variability at each level and are
not independent run-level replication of the emissions-axis contrast, so a displacement between two levels cannot
be separated from the difference between the two runs that carry them. The corrected grouped evidence shows no
committed variation of this axis at all, so the design does not attempt a plateau test. What the four points do
give is a four-level series whose shape is read only relative to the within-run variation each block's own
controls measure: for E8, E64 and E128 those controls are additional realizations of that same emissions
condition (four same-setting acquisitions inside one run each), which sharpens each level's own within-run
measurement without making the level contrast run-independent.

### 3.5 Already satisfied by existing data vs what actually needs acquisition

| Already measured — no instrument time | Needs acquisition |
|---|---|
| 0.617 mm x 145 gates (`res/0-6.BDD`) | CC1, CC2 — 0.617 mm with burst 4 and 18 cycles |
| 2.960 mm x 31 gates (`res/3-0.BDD`) | CC3, CC4 — 2.960 mm with burst 4 and 18 cycles |
| 1.850 mm x 50 gates (`res/1-8.BDD`) and PRF 600 µs (`prf/600.BDD`) | E8, E64, E128 — the emissions axis's first measured points |
| PRF 400 µs and 800 µs (both measured; 250 µs deferred, not acquired) | D1 — one higher-sensitivity + echo/energy diagnostic, blocked today |
| burst 4, 18, 20, 28, 32 cycles at the reference pitch | block-local controls — 3 recordings per scientific job, at that job's own run-wide values |
| all 8 TGC levels, both emitting-power levels, emissions 20 | common-reference checks — 1 recording in each of the 4 reference-only jobs |

## 4. Protocol assumptions the evidence cannot settle

Stated as the smallest defensible assumption with the condition that would revise it, because no committed
artifact fixes either number:

- **Fixed duration.** Committed durations span 8.1535-16.0267 s and the reports' comparison windows span
  8.04-11.52 s. Assumption: **every job records one fixed window of at least 11.52 s** — WP1's 96 nominal
  500-RPM revolutions — so every new record can be truncated to the same common-duration window as its
  comparand. Revised by: a temporal view needing more than the window provides (WP1's needs 6-7 whole 1.9031 s
  segments; the PRF ladder needed 8.1535 s for five whole 1.6 s segments), or a control spread above the
  screening threshold.
- **Control replication count.** Assumption: **3 block-local controls per scientific job**
  (beginning/middle/end), which is the smallest count that gives a within-run drift difference — one minimum
  diagnostic whose adjacent differences are correlated. Revised by: a control set whose per-gate mean
  difference falls above the screening threshold (**19.3701 mm/s**) at any gate, which raises the count (a
  control at every block boundary, or a repeated run) and is checked before any scientific verdict from the
  run is read.

Both are properties of the run, not of the physics, and neither is a substitute for the replication the
dataset lacks: every new condition is acquired inside a single run, and the only condition the first pass
observes in more than one distinct run is the common reference itself.

## 5. Parameters deliberately excluded from this augmentation

- **Emitting frequency** — fixed at 4 MHz. It changes wavelength, Doppler conversion, attenuation, beam
  field, acoustic resolution and transducer response at once; it belongs to a separate probe/frequency
  campaign.
- **Sound speed** — measured/read back and recorded, never assumed; it scales both distance and velocity.
- **Doppler angle** — fixed; a geometric conversion parameter, not an instrument-sensitivity axis.
- **Velocity scale factor** — fixed at 1 unless a later experiment studies quantisation explicitly.
- **First gate / measurement window** — fixed at ≈10.163-96.743 mm; a near-field/dead-zone experiment is a
  separate design.
- **Skipped profiles** — deferred until acquisition parameters are settled; it changes temporal subsampling
  of the stored series, and word 84's semantics are still unconfirmed (matrix §9).
- **PRF beyond 600 µs** — the whole augmentation holds 600 µs. 250 µs is deferred (rule 3), and 400/800 µs
  are already measured.
- **Dense TGC and emitting-power sweeps** — not reacquired. Both axes are already screened from the committed
  levels: 17 of the 39 pairs across the two screened axes clear the screening threshold locally and 2 of the
  12 screened levels fail the dropout/spread screen (unattributable without echo/energy), while the power
  axis sits at 0.691 of the screening threshold with no flagged level. A wider TGC ladder is **not**
  justified before the echo/energy diagnostic, and the TGC representation itself is unsettled — word 23
  stays 0 (`uniform`), word 25 stays 255 and only word 24 moves, so the axis is not a validated scalar gain
  set point and nothing here is designed on such a reading.

## 6. Automation writers needed before this set can run unattended

The measurement set is ahead of the per-point writer surface, and the gaps are specific:

| Needed for | Gap today |
|---|---|
| CC1-CC4 in **one** randomized run | `burst_length` is dialog-only (`acquire/actuator.py::DIALOG_ONLY_PARAMETERS`, `DialogField.BURST_LENGTH`) and run-wide (`campaign.CampaignDefinition.burst_length`); no per-point write exists. Without it the crossing runs as one job per burst length, each holding that block's three points plus its three block-local controls, and that arrangement is executable today. |
| E8, E64, E128 in one run | `emissions_per_profile` is run-wide (`campaign.CampaignDefinition.emissions_per_profile`; a point may not disagree) and absent from `PARAMETER_WRITE_ORDER` = `(RESOLUTION, GATES)`, although `ParamRole.EMISSIONS_PER_PROFILE` exists. One job per level needs no new writer. The runner's stored-size guard already derives from the definition's emissions, so it needs no change either. |
| D1 | No `sensitivity` reader or writer: the operating-parameters dialog carries it as a combo row (`acquire/ui/dialog.py::dialog_value_fields`), but `DialogField` names only sound speed, first gate and burst length. |
| D1's echo/energy channel | Not a parameter write at all: the stored `.BDD` carries one axial-velocity channel and no echo or energy profile exists in any committed file. The recording surface has to carry the second channel before D1 can be recorded — it is the one condition here that **no** writer can execute today. |
| already covered | Resolution and gates are per-point writes; `prf_us` is a run-wide field and stays at 600 µs; TGC, emitting power, sound speed, first gate and sampling volume are not varied; the campaign runs the definition's point order literally, so the beginning/middle/end placement of a job's block-local controls is a definition-authoring rule rather than code. |

Implementation work follows the accepted measured set rather than letting the present automation limit the
physics experiment; the axes that can be run with today's writers (the crossing as one job per burst length,
and the emissions levels as one job each) are the natural first block.

## 7. Analysis the first block will be read with

The corrected WP0-WP2 reports already satisfy most of what the earlier draft asked for, and the augmentation
inherits that method rather than inventing a new one:

| Question | Status before the new block |
|---|---|
| velocity bias and reference consistency | committed: WP1 `reference-repeat.csv` screening threshold **19.3701 mm/s**, the threshold every effect is compared to |
| velocity variance versus depth, zero/rejected fraction | committed: per-axis `*-levels.csv` and `gain-power-depths.csv` |
| aliasing margin, achieved profile interval and count | committed: `prf-levels.csv` (`load_max_over_velo_max`, warning fractions, wrap-like counts, profile rate) |
| temporal spectra / autocorrelation | committed: WP1 and the matched temporal view of the burst and PRF ladders, screened against the observed same-settings temporal discrepancy |
| spatial smoothness and resolved-gradient behaviour | committed: native-grid gradient and descriptive profile autocorrelation scale per level; the latter is not a physical scale or primary resolution criterion |
| sensitivity to reference-drift | committed as a screening threshold only; the new block's block-local controls measure drift inside a job and its common-reference checks test the true common condition between jobs |
| echo amplitude / saturation | **not available**: no committed file carries an echo/energy channel; D1 is the measurement that would start it |
| pitch x burst interaction | **not estimable** before this block; CC1-CC4 are the four missing corners |

The second-stage dense sweep should be concentrated around transitions this analysis actually finds, not
around uniformly filling the parameter domain — and on this evidence there is no measured transition to
cluster on yet: no resolution effect cleared the screening threshold, no burst metric fell monotonically, and
no PRF level was shown inadequate.

## 8. Limitations this design carries

One same-settings repeat only, so the committed screening threshold is one observed realization of
repeatability *plus* uncontrolled drift and a clearance can still be drift. No acquisition order, so no time
drift is reconstructed from the old set. Most levels have one recording and the shared reference level has
two realizations; **one duplicated setting is not replicated axis coverage**, so no old verdict is replicated
axis evidence and no p-value is produced. Velocity only: echo SNR, receiver saturation, a safe plateau and
acoustic energy are neither measured nor inferred. The TGC axis is screened through an unsettled
representation, not a validated gain ladder. The pitch x burst interaction is not estimable from the
committed set, which is exactly why CC1-CC4 are new measurements rather than a re-reading. A condition
acquired only inside its own run is not thereby replicated: a job's block-local controls stay inside that run —
for E8, E64 and E128 they are three further acquisitions of that same level (four same-setting acquisitions in
one run), and for the two burst jobs they are new realizations of the already-committed burst-4 and burst-18
conditions — so they measure within-run repeatability without giving any new level an independent run-level
realization. The common-reference jobs test the one common condition across separate runs rather than
replicating any new level.

## 9. Intended outcome and next step

This document and the decision table are the merged artefacts of the gating work. The next PR encodes the set
in §3.1 in the campaign-definition format, adds only the writers §6 names, and records the block-local
controls and the common-reference jobs as points in the definition rather than as a convention — the crossing
first, since it is the one that closes a gap no existing recording can.

**Landed.** The encoding is in `examples/sparse-mixer-first-pass/` — one run plan and one definition per job,
with the within-job control placement and the cross-job order the rows do not carry — and it needs **no** new
writer: the pass runs through the writer surface the six-point campaign was verified on. What it checks before
anything is recorded, what it leaves to the operator and how it is used are
[`sparse-run-plan.md`](sparse-run-plan.md).
