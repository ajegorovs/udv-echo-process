# The first sparse measurement set — the evidence-gated first augmentation

> **Status:** design, gated by measurement. This document is no longer a proposal: its Stage-1 candidate
> list has been decided by the committed velocity arrays through
> [`reports/mixer-sensitivity-analysis/decision-table.md`](../../reports/mixer-sensitivity-analysis/decision-table.md)
> (WP3 of [`existing-sweep-analysis-plan.md`](existing-sweep-analysis-plan.md)) and the set below is the WP4
> augmentation that table justifies. Nothing here is acquired yet, and nothing here re-reads the old data:
> every verdict behind it, with the artifact and SHA-256 it comes from, is in the decision table.
>
> **What it answers.** [`acquisition-closeout-plan.md`](acquisition-closeout-plan.md) §4 makes the matrix
> question the gate for the next stretch: *is `experiment_data\mixer\sensitivity-analysis\4MHz\0500RPM\001`
> the experiment this work is for?* This document answers **yes at the axis level** and now names the small
> explicit set the first measured pass consists of, so §4's dependent decisions (which writers are funded,
> whether the application's own `Sweep PRF` search is an axis) settle against the measured decisions rather
> than against a principle.
>
> **Grounded in:** the DOP3000/3010 manual (`manual-reference/`, cited as *Ch. N* through
> [`parameter-sweep-matrix.md`](parameter-sweep-matrix.md)); the 40 committed `.BDD` recordings of the 4 MHz
> 500-RPM reference run and the WP0-WP2 reports regenerated from them; the relations of
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
| sensitivity | medium | all 40 rows; the axis is absent from the committed sweep |
| velocity scale | 1 | plan; fixed unless quantisation becomes a question |
| assisted mode / filtering during acquisition / alias auto-correction | OFF | the run's own recorded state |
| skipped profiles | 0 | word 84 = 0 in all 40 rows |
| sampling volume | read back only — word 27 is the instrument's bandwidth-list index (4), not a length, so `sampling_volume_mm` stays unset | plan §2; matrix §9 |

## 2. What the committed evidence settles — the design rules this set obeys

1. **Do not reacquire 0.247 mm merely for finer pitch.** No measured resolution effect ever cleared the
   sole-pair observed-discrepancy screening threshold: the focus pair `res/0-2.BDD` vs `res/0-6.BDD` differs by at most 6.1136 mm/s =
   **0.3156** of the 19.3701 mm/s screening threshold on 141 knots with **0** above it, the extra gates carry
   **0.0722 %** of the spatial variance, and **not one of the 78 pairs** puts a knot above the screening threshold. The
   coarsest measured pitch, 2.960 mm, still samples the measured structure **4** times per correlation
   length. So only the resolution settings needed as reference/interaction corners are retained — **0.617 mm**
   and **2.960 mm**, crossed against burst corners (rule 6, §3.1) — and 1.233 mm is deferred rather than
   reacquired.
2. **18 versus 20 cycles is unresolvable, and no monotonic knee exists.** The focus pair differs by
   **0.6067** of the screening threshold with **0 of 50** knots above it, the whole 16-20-cycle region is inside the
   bound (16-18 = 0.6504, 16-20 = 0.2560, 0 clearing), and no metric along the 2-32-cycle ladder falls
   monotonically — the largest dropout and gradient steps land on **28** cycles and the largest spread step
   is a *rise* at 4, each from a single recording. The augmentation therefore carries **18 cycles**, chosen
   on cost and contrast alone (shorter pulse, equal measured information, two-sided spacing around the
   reference with 4 cycles) — an explicit information/cost rationale, **not** a claimed effect.
3. **Do not add PRF 250 µs.** The measured 400 µs point has adequate headroom and the widest bandwidth:
   peak load **0.7266** of the 231.2064 mm/s unambiguous limit, **0** samples at or beyond it, **0** wrap-like
   steps, usable bandwidth **33.3599 Hz** — the widest of the five, against 16.4678 Hz at 800 µs. A 250 µs
   setting would move the limit to 369.9302 mm/s, which nothing in this dataset asks for (the largest
   absolute velocity anywhere is 196.53 mm/s).
4. **Emissions/profile is absent, so begin at 8 and 64 around the reference 20, and make 128 conditional
   on 64.** No committed recording varies the axis (all 40 rows carry 20), so its effect is unidentifiable
   today; 128 is acquired only if 64 has not plateaued (§3.4).
5. **Sensitivity is absent too, and velocity-only TGC/power data cannot establish SNR or saturation.**
   Request exactly **one** higher-sensitivity condition, recorded **with an echo/energy channel**, before any
   wider sensitivity, TGC or power ladder — the committed screen flags 2 of 10 levels for a dropout/spread it
   cannot attribute, and echo SNR, receiver saturation, a safe plateau and acoustic energy are not measurable
   in the committed files at all.
6. **Within-run reference controls at the beginning, middle and end of each randomized or blocked run, and
   no Cartesian product.** The only committed same-settings repeat is one pair, which is why every verdict in
   the decision table is screened rather than replicated. The crossing below is **2 pitches x 2 burst levels =
   4 cells**; no other axis moves in any condition.

## 3. The first measured augmentation

### 3.1 Complete new conditions

Seven unique conditions — sparse points, not a factorial design. "§1" means every fixed fact of §1.

| ID | resolution | gates | burst | emissions/profile | sensitivity | other |
|---|---:|---:|---:|---:|---|---|
| CC1 | 0.617 mm | 145 | 4 cycles | 20 | medium | §1 |
| CC2 | 0.617 mm | 145 | 18 cycles | 20 | medium | §1 |
| CC3 | 2.960 mm | 31 | 4 cycles | 20 | medium | §1 |
| CC4 | 2.960 mm | 31 | 18 cycles | 20 | medium | §1 |
| E8 | 1.850 mm | 50 | 10 cycles | 8 | medium | §1 |
| E64 | 1.850 mm | 50 | 10 cycles | 64 | medium | §1 |
| D1 | 1.850 mm | 50 | 10 cycles | 20 | one step above medium | §1 + an echo/energy channel in the recording |

**Why the crossing exists.** The resolution and burst ladders intersect **only at the reference**, so the
pitch x burst interaction is not estimable from the committed set at all. CC1-CC4 are the four corners that
make it estimable: each one completes a 2x2 whose other three corners are already committed
(`res/0-6.BDD`, `res/3-0.BDD` at burst 10; `burst_len/4.BDD`, `burst_len/18.BDD` at 1.850 mm; the reference).
Two pitches and two burst lengths only — this is a corner set, never a product of the design's axes.

**Requested in mm, read back from the file.** The rung labels are the instrument's and a rung's mm value is
`c`-dependent, so every condition must be *requested* in mm and *read back* from word 10.
Nothing in this set may be identified by a folder name or a label.

**`E128` — the one conditional condition** (emissions/profile 128, everything else as E8/E64). See §3.4.

### 3.2 Within-run reference controls

Three recordings of the **reference condition** (§1) at the **beginning, middle and end of each
randomized or blocked run**. They are repeats of one condition, not new conditions, and are counted
separately everywhere. They are the design's own answer to the single committed repeat: three same-settings
recordings in one run form one minimum within-run drift diagnostic with two adjacent, correlated differences instead of one, and they are
the direct check that the committed 19.3701 mm/s sole-pair observed-discrepancy screening threshold transfers to the new run.

### 3.3 Already satisfied by existing data vs what actually needs acquisition

| Already measured — no instrument time | Needs acquisition |
|---|---|
| 0.617 mm x 145 gates (`res/0-6.BDD`) | CC1, CC2 — 0.617 mm with burst 4 and 18 cycles |
| 2.960 mm x 31 gates (`res/3-0.BDD`) | CC3, CC4 — 2.960 mm with burst 4 and 18 cycles |
| 1.850 mm x 50 gates (`res/1-8.BDD`) and PRF 600 µs (`prf/600.BDD`) | E8, E64 — the emissions axis's first measured points |
| PRF 400 µs and 800 µs (both measured; 250 µs deferred, not acquired) | D1 — one higher-sensitivity + echo/energy diagnostic |
| burst 4, 18, 20, 28, 32 cycles at the reference pitch | REF-CTRL — 3 reference repeats per run |
| all 8 TGC levels, both emitting-power levels, emissions 20 | (E128 — only on the §3.4 trigger) |

**Counts.** Unique new conditions **7** (CC1-CC4, E8, E64, D1), or **8** with E128. Repeated controls **3 per
run**: 3 for a single run, 9 if today's run-wide emissions/burst surface forces the work into three jobs (one
per axis block). Recordings for the first pass: **10** (7 unique + 3 controls) if one run is possible, **16**
(7 unique + 9 controls) if it is not, **11** / **17** with E128. No Cartesian product anywhere.

### 3.4 The measurement that triggers the conditional extension

`E128` is acquired **only if E64 has not plateaued**, and plateauing is judged against the committed
observed same-settings temporal discrepancy resummarised in the same bands, not by inspection:

| Quantity, E64 against the reference | Observed same-settings discrepancy | Source |
|---|---|---|
| in-band power share above 10 Hz | 0.02789 | `burst-ladder.provenance.json` `findings.temporal_bandwidth` |
| RMS bandwidth | 0.4457 Hz | same key |
| band-mean spectral level | 3.5317 dB | `prf-ladder.provenance.json` `findings.temporal_bandwidth` |
| share of in-band power below the 8.333 Hz marker | 0.01806 | same key |
| stored profile period, per-gate zero fraction | the control repeats in the same run | §3.2 |

If E64's change from the reference exceeds its floor on **any** of those, the axis has not plateaued and E128
is acquired. If E64 sits at or below every floor, the axis has plateaued and E128 is **not** acquired. No
other condition here is conditional.

## 4. Protocol assumptions the evidence cannot settle

Stated as the smallest defensible assumption with the condition that would revise it, because no committed
artifact fixes either number:

- **Fixed duration.** Committed durations span 8.1535-16.0267 s and the reports' comparison windows span
  8.04-11.52 s. Assumption: **every job records one fixed window of at least 11.52 s** — WP1's 96 nominal
  500-RPM revolutions — so every new record can be truncated to the same common-duration window as its
  comparand. Revised by: a temporal view needing more than the window provides (WP1's needs 6-7 whole 1.9031 s
  segments; the PRF ladder needed 8.1535 s for five whole 1.6 s segments), or a control spread above the
  screening threshold.
- **Reference replication count.** Assumption: **3 controls per run** (beginning/middle/end), which is the
  smallest count that gives a within-run drift difference — one minimum diagnostic whose adjacent differences are correlated. Revised by: a control set whose per-gate
  mean difference falls above the screening threshold (**19.3701 mm/s**) at any gate, which raises the count (a control at every block
  boundary, or a repeated run) and is checked before any scientific verdict from the run is read.

Both are properties of the run, not of the physics, and neither is a substitute for the replication the
dataset lacks: the augmentation is still one recording per new condition.

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
  levels: 14 of 28 TGC pairs clear the screening threshold locally and 2 of 10 levels fail the dropout/spread screen
  (unattributable without echo/energy), while the whole power ladder sits at 0.5374 of the screening threshold with no
  flagged level. A wider TGC ladder is **not** justified before the echo/energy diagnostic, and the TGC
  representation itself is unsettled — word 23 stays 0 (`uniform`), word 25 stays 255 and only word 24 moves,
  so the axis is not a validated scalar gain set point and nothing here is designed on such a reading.

## 6. Automation writers needed before this set can run unattended

The measurement set is ahead of the per-point writer surface, and the gaps are specific:

| Needed for | Gap today |
|---|---|
| CC1-CC4 plus the reference controls in **one** randomized run | `burst_length` is dialog-only (`acquire/actuator.py::DIALOG_ONLY_PARAMETERS`, `DialogField.BURST_LENGTH`) and run-wide (`campaign.CampaignDefinition.burst_length`); no per-point write exists. Without it the crossing runs as one job per burst length (two jobs of three points each), which is executable today. |
| E8, E64 (and E128) in one run | `emissions_per_profile` is run-wide (`campaign.CampaignDefinition.emissions_per_profile`; a point may not disagree) and absent from `PARAMETER_WRITE_ORDER` = `(RESOLUTION, GATES)`, although `ParamRole.EMISSIONS_PER_PROFILE` exists. One job per level needs no new writer. The runner's stored-size guard already derives from the definition's emissions, so it needs no change either. |
| D1 | No `sensitivity` reader or writer: the operating-parameters dialog carries it as a combo row (`acquire/ui/dialog.py::dialog_value_fields`), but `DialogField` names only sound speed, first gate and burst length. |
| D1's echo/energy channel | Not a parameter write at all: the stored `.BDD` carries one axial-velocity channel and no echo or energy profile exists in any committed file. The recording surface has to carry the second channel before D1 can be recorded — it is the one condition here that **no** writer can execute today. |
| already covered | Resolution and gates are per-point writes; `prf_us` is a run-wide field and stays at 600 µs; TGC, emitting power, sound speed, first gate and sampling volume are not varied; the campaign runs the definition's point order literally, so the beginning/middle/end controls are a definition-authoring rule rather than code. |

Implementation work follows the accepted measured set rather than letting the present automation limit the
physics experiment; the two axes that can be run with today's writers (the crossing as one job per burst
length, and the emissions levels as one job each) are the natural first block.

## 7. Analysis the first block will be read with

The WP0-WP2 reports already satisfy most of what the earlier draft asked for, and the augmentation inherits
that method rather than inventing a new one:

| Question | Status before the new block |
|---|---|
| velocity bias and reference consistency | committed: WP1 `reference-repeat.csv` screening threshold **19.3701 mm/s**, the threshold every effect is compared to |
| velocity variance versus depth, zero/rejected fraction | committed: per-axis `*-levels.csv` and `gain-power-depths.csv` |
| aliasing margin, achieved profile interval and count | committed: `prf-levels.csv` (`load_max_over_velo_max`, warning fractions, wrap-like counts, profile rate) |
| temporal spectra / autocorrelation | committed: WP1 and the matched temporal view of the burst and PRF ladders, with their floors |
| spatial smoothness and resolved-gradient behaviour | committed: native-grid gradient and correlation length per level |
| sensitivity to reference-drift | committed as a screening threshold only; the new block's within-run reference controls are what turn it into a within-run measurement |
| echo amplitude / saturation | **not available**: no committed file carries an echo/energy channel; D1 is the measurement that would start it |
| pitch x burst interaction | **not estimable** before this block; CC1-CC4 are the four missing corners |

The second-stage dense sweep should be concentrated around transitions this analysis actually finds, not
around uniformly filling the parameter domain — and on this evidence there is no measured transition to
cluster on yet: no resolution effect cleared the bound, no burst metric fell monotonically, and no PRF level
was shown inadequate.

## 8. Limitations this design carries

One same-settings repeat only, so the committed screening threshold is one observed realization of repeatability *plus* uncontrolled drift and a
clearance can still be drift. No acquisition order, so no time drift is reconstructed from the old set. One
recording per level, so no old verdict is a replicated one and no p-value is produced. Velocity only: echo
SNR, receiver saturation, a safe plateau and acoustic energy are neither measured nor inferred. The TGC axis
is screened through an unsettled representation, not a validated gain ladder. The pitch x burst interaction is
not estimable from the committed set, which is exactly why CC1-CC4 are new measurements rather than a
re-reading. A new condition with one recording is still one recording: the within-run reference controls screen drift
within a run, they do not replicate a condition.

## 9. Intended outcome and next step

This document and the decision table are the merged artefacts of the gating work. The next PR encodes the set
in §3.1 in the campaign-definition format, adds only the writers §6 names, and records the reference controls
as points in the definition rather than as a convention — the crossing first, since it is the one that closes
a gap no existing recording can.
