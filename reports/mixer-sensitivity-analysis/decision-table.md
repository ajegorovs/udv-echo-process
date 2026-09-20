# The decision table — what the committed sweep decides about the sparse set

**Status:** WP3 deliverable of [`docs/dop3000/existing-sweep-analysis-plan.md`](../../docs/dop3000/existing-sweep-analysis-plan.md)
§4, and the evidence gate WP4 (§5) designs against. It converts the **corrected grouped** WP1/WP2 report
artifacts into one verdict per candidate condition of
[`docs/dop3000/sparse-parameter-set.md`](../../docs/dop3000/sparse-parameter-set.md), and it is what that
document's candidate list is replaced by.

This file is **written by hand** — no command regenerates it — so it makes no measurement of its own. Every
number in it is copied from the corrected artifacts listed under **Binding**, at the cells and provenance keys
named beside it. If a number here disagrees with those bytes, the bytes are right.

## How to read a row

- **Measured** conditions are the committed recordings or levels the committed ladders already carry; they
  need no new instrument time. **Acquire** marks a condition that does not exist in the dataset yet. The
  verdict cell carries that tag, so already-measured evidence is never counted as a new acquisition.
- **The sole-pair observed-discrepancy screening threshold** is the committed WP1 value, **19.37008103465545 mm/s**
  (`max_gate_abs_mean_difference_mm_s`, gate 39, 82.3127 mm) from `reference-repeat.provenance.json`. It screens
  same-settings repeatability **plus uncontrolled drift**: the only same-settings repeat in the set also differs
  in duration, and the files carry no acquisition order. Every "exceeds" cell is compared to *that* number.
- **Verdicts** use the plan's four words only: `keep`, `defer`, `replace`, `requires diagnostic`.
- **No cell is causal.** Where a pair clears the screening threshold, that is a fact about two recordings — not
  evidence that the parameter caused it. Where the corrected `findings.knees` blocks record a largest one-step
  change, this table does not turn it into a transition: no metric along the burst ladder falls monotonically,
  so **no knee is asserted here**.
- **Coverage is grouped, not singular.** The corrected ladders are setting-based selections: most non-reference
  levels carry one recording, and the shared reference level carries two named realizations (`prf/600.BDD` and
  `res/1-8.BDD`). **one duplicated setting is not replicated axis coverage** — it repeats one condition rather
  than replicating a level — so no verdict below is replicated axis evidence.
- `Above the screening threshold?` is `N/A` exactly where the committed set contains no measured variation of that axis.
  There is nothing to compare there, and that absence *is* the information gain being asked for.

## Binding

Every artifact this table reads, at the commit it cites (`a1e9045`, the head of PR #24's branch), with the
SHA-256 of the **corrected** committed bytes. The generator revision each provenance document records is
rebound in step 8, not here:

| Artifact (under `reports/mixer-sensitivity-analysis/`) | SHA-256 | What this table reads from it |
|---|---|---|
| `manifest.csv` | `064a289b7b9e8128766305ac047ca171355539d83461fc25a25dcec1cf4d7139` | the 40 rows, their decoded settings and their source hashes; every axis selects from it |
| `qc-summary.json` | `4e46582b6cfe1644cc3699a5134d8c02dcf9ad3e7568359a01a2f1c56fce463f` | axis counts 13/12/8/5/2, zero decode failures, monotone timestamps |
| `reference-repeat.csv` | `05f3495c98f6d58fd50cb447fbca4c8a1164aba178c6b53d0eefa34a58c4d9cb` | the 50-gate per-gate statistics of the only same-settings pair |
| `reference-repeat.provenance.json` | `b0c1b7cf9639f83fd63d8fb2c39414490bba98a1e7f846de94b8608527a0061b` | the sole-pair observed-discrepancy screening threshold, the metric definitions, both time views, the observed same-settings temporal-discrepancy curves |
| `resolution-levels.csv` | `9a538a2b83b3a2e7c4f969aa00c2b5feb1e907c3748eb2ccfc20f4e4b87a18eb` | per-pitch distributional and native-grid spatial metrics |
| `resolution-pairs.csv` | `0b75ef17cad20288d04fb6ace223f27a0b49691980d823a306254ca2efa330bb` | all 78 pairs: per-knot difference, knots above the screening threshold, depth ranges, sub-knot detail |
| `resolution-ladder.provenance.json` | `d257ab35d20083fd30abb82e64ecb5c1a0ec39cfb21f855860a0d52bd25a6247` | `findings.screening_threshold_gate`, `findings.information`, `findings.coarsest_pitch`, `findings.realizations`, `findings.limitations` |
| `burst-levels.csv` | `71312af10046eac5e4e2a2d55887414ea7cf2a87b311ae4513a3894acae1b19f` | per-cycle distributional, spatial and matched-temporal metrics |
| `burst-pairs.csv` | `6e0ba041355877245e34e10917bb5d6db40a7e8172101dc44fb214938969d720` | all 78 pairs at the shared 1.85 mm knots, including the 18-vs-20 row |
| `burst-ladder.provenance.json` | `f0e70fe4c70a953b39c61878ee4635b17d376a619cfbc6171441f6f76fb5612c` | `findings.focus_18_vs_20`, `findings.focus_window_16_20`, `findings.knees`, `findings.temporal_bandwidth`, `findings.realizations`, `findings.limitations` |
| `prf-levels.csv` | `adf8320336f6de4265df9c666c7a12515f22e1d552e50d07cbd48d69843fa997` | per-period load, warning fractions, wrap-like counts, profile rate, usable bandwidth |
| `prf-pairs.csv` | `b1e9399e7a96213dcec3abac585a7174bd65fc08815f641c3f4d19c5bf1220c3` | all 10 pairs: per-knot difference, knots above the screening threshold, band-level differences |
| `prf-ladder.provenance.json` | `da503728dee8d6c6a3de176c4d72d4b316b938be3b96f617e7ff8cf250ef94a3` | `findings.effect_gate`, `findings.velocity_headroom`, `findings.temporal_bandwidth`, `findings.focus_decision`, `findings.realizations`, `findings.limitations` |
| `gain-power-levels.csv` | `a1417023cee709d8a050a5d7fb90996bd660c4e4b90ef2eb800ddddb9c2df195` | per-level key, window, support and dropout/spread screen flags |
| `gain-power-pairs.csv` | `ee2fb3e1d0332c0b72110513df69b77a7d73563e2a0d3395da6ef20c46e19dbc` | all within-axis pairs against the screening threshold |
| `gain-power-depths.csv` | `d5e539420610e71c59272376bdcb30a27815bed0f11d43b823b4661b358bb335` | per-gate dropout, spread and std by level and depth |
| `gain-power-screen.provenance.json` | `2597de32623a58f6af3af3f9f25ca0c0c6d5ac631212f9d129d83c683a453301` | `findings.screen_summary`, `findings.sensitivity`, `findings.velocity_only`, `findings.diagnostic`, `findings.limitations` |
| `figures/reference-repeat.png` | `71bc162e4cd1b6589d0f60fa7a047e535cb057499f9e590cf2ac301c071a7237` | reviewer-visible repeat comparison |
| `figures/resolution-ladder.png` | `dfc8f545ec77e9f200872f52973a7a40682e7fb05e4c50334da66d8cebbd843f` | pitch decision figure |
| `figures/burst-ladder.png` | `0fb98cebeb0f19ac924ab5aa81638be740b308ec7660796b20cbe04435208afa` | burst dropout/variance and 18-vs-20 figure |
| `figures/prf-ladder.png` | `dccccebe47666f25abd6002df5a793862bea0b16134c79aa339283346b687a23` | velocity-headroom and bandwidth figure |
| `figures/gain-power-screen.png` | `eb5fd8a09a482841c7f037c038cfbdc8a05cb980362db282d67282fc92b21cd5` | dropout-by-depth and focus-pair figure |

Regenerate those bytes with the command each provenance records — the commit in the argument is the commit that
generated the artifact, so passing it reproduces the committed file exactly:

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sweep-inventory     --analysis-commit <qc-summary.json: analysis_commit>
.venv/Scripts/python.exe -m udv_echo_process.cli reference-repeat    --analysis-commit 2c70976
.venv/Scripts/python.exe -m udv_echo_process.cli resolution-ladder   --analysis-commit 3a4c55a
.venv/Scripts/python.exe -m udv_echo_process.cli burst-ladder        --analysis-commit 4cb2522
.venv/Scripts/python.exe -m udv_echo_process.cli prf-ladder          --analysis-commit 1de828e
.venv/Scripts/python.exe -m udv_echo_process.cli gain-power-screen   --analysis-commit 71b7906
```

`sha256sum reports/mixer-sensitivity-analysis/*.csv reports/mixer-sensitivity-analysis/*.json
reports/mixer-sensitivity-analysis/figures/*.png` re-checks the table above; `.gitattributes` pins `text eol=lf`
on this directory's `*.csv`/`*.json` and `binary` on `figures/*.png`, so the hashes survive a Windows checkout.

Two source hashes recur in the verdicts below and are cited from `manifest.csv`:

| Recording | SHA-256 | shape |
|---|---|---|
| `res/0-2.BDD` | `85dc6e5152914c33f336571303a29ba76d852768aa7fd08a0abc46702a2a28fd` | 540 profiles, 365 gates, 12.2105 s |
| `res/0-6.BDD` | `ada06d27f56acd5436ce23e77aa7525f60e422d18294fe3e19b68348eaef0e4d` | 548 profiles, 145 gates, 12.289 s |
| `res/3-0.BDD` | `46bbe2a82e6af90e6c1c47391029ab754c0dbef958dcfd00f3ccbd9e14349291` | 517 profiles, 31 gates, 11.5441 s |
| `burst_len/18.BDD` | `e1598263277fa58b4802dd3779ddb29ee6dc034e0cb0853083327ddb050e85dc` | 524 profiles, 50 gates, 11.7096 s |
| `burst_len/20.BDD` | `a7aa7814f5832d34a33538ad4745718bacca5c0af0d5ab8979094a8e23b48abd` | 518 profiles, 50 gates, 11.5752 s |
| `burst_len/32.BDD` | `a29e78dc6dcfc890d49e7c14d8f525675a67c19ae8f7b5f7f0aa68b66bdcf2fe` | 520 profiles, 50 gates, 11.62 s |
| `prf/400.BDD` | `2e1a0316b2be4c134512f7d15794d15b926002018a50f2e02cf49f5ed334718e` | 545 profiles, 50 gates, 8.1535 s |
| `tgc/0.BDD` | `4f936ff8751593313a621d0cbf4ea322ae7fb5e23e12ea7d109ce683a613b72e` | 516 profiles, 50 gates, 11.5275 s |
| `tgc/40.BDD` | `07c90296fdf8572599be1aedfbf715886fd952af52e35f77cb1764a3ca49dd64` | 492 profiles, 50 gates, 10.9928 s |

The columns below are, in this order and no other: **Candidate** · **Existing evidence** ·
**Above the screening threshold? (where/depth or N/A; screening only)** · **Information gained** · **Automation needed** · **Verdict** ·
**Measurement that overturns it**. Each axis gets its own table only so the rows stay readable; the column set
is identical in every one.

## 1. Spatial-sampling axis

The corrected grouped ladder selects **13 decoded pitches from 14 recordings**; 12 levels are a single
recording and the shared 1.850 mm reference level carries both reference recordings as two named realizations
(`findings.realizations`). Its corrected effect gate puts **0 of the 78 pairs** above the sole-pair observed-discrepancy screening threshold, the largest being 17.368 mm/s (1-2 vs 1-6 at 43.8327 mm) = 0.8966 (`findings.screening_threshold_gate`).

| Candidate | Existing evidence | Above the screening threshold? (where/depth or N/A; screening only) | Information gained | Automation needed | Verdict | Measurement that overturns it |
|---|---|---|---|---|---|---|
| **R1 — 0.247 mm x 365 gates** (`res/0-2.BDD`) | Measured. Against 0.617 mm on the coarser level's own 141 knots: mean abs diff **1.974 mm/s**, max **6.1136 mm/s** at 44.696 mm = **0.3156** of the screening threshold, **0 of 141** knots above it (`resolution-pairs.csv`, row `res/0-2.BDD - res/0-6.BDD`; `resolution-ladder.provenance.json` `findings.information`). The normalized reconstruction-residual variance is **0.000722** (sub-knot residual RMS 0.5814 mm/s, peak 2.7382 mm/s = 0.141 of the screening threshold); it is a stand-alone ratio of the finer profile's own variance, not an orthogonal partition of it. Its descriptive profile autocorrelation scale is 10.1133 mm (`resolution-levels.csv`). | **No.** 0 of 141 knots above the screening threshold; 0.3156 x it. The largest of all 78 pairs is **0.8966** (1-2 vs 1-6 at 43.8327 mm, 0 knots above). | None demonstrated for finer pitch. This is the plan's named question and the measured answer is "not demonstrated": the level difference and the normalized reconstruction residual are small relative to the screening threshold. | None — not acquired. | `replace` (measured; dropped) — the fine end of the first augmentation is **0.617 mm**. The instrument accepts the 0.247 mm rung; it is dropped for information, not for feasibility. | Replicated pitch comparisons that establish a finer-pitch effect, or a materially larger normalized reconstruction-residual variance. |
| **R2 — 0.617 mm x 145 gates** (`res/0-6.BDD`) | Measured. Member of the 78 pairs, none of which clears the screening threshold; its own mean 25.6882 mm/s, robust spread 31.4933 mm/s, zero fraction 0.009661, native correlation length 9.8667 mm (`resolution-levels.csv`). | **No.** No pair of the 78 puts a knot above the screening threshold. | Retained as the **fine pitch corner** of the pitch x burst crossing (§6, CC1/CC2): the interaction is not estimable from the committed set at all (`resolution-ladder.provenance.json` `findings.limitations`: the two ladders meet only at the reference). | Per-point resolution + gates writers already exist (`actuator.PARAMETER_WRITE_ORDER` is `(RESOLUTION, GATES)`); the crossing cells additionally need the burst field — see §6. | `keep` (measured at the reference burst; acquire only *inside* the crossing) | A replicated pitch effect at 0.617 mm against a coarser level, or a replicated loss of structure by 0.617 mm — either would move this corner. |
| **R3 — 1.233 mm x 74 gates** (`res/1-2.BDD`) | Measured. Participant in the largest pair of the ladder: 1-2 vs 1-6 = **17.368 mm/s** at 43.8327 mm = **0.8966** of the screening threshold, **0 knots above** (`resolution-ladder.provenance.json` `findings.screening_threshold_gate`); own descriptive correlation scale 12.3333 mm. | **No.** | None demonstrated beyond the retained corners: the intermediate rung's largest observed difference remains below the sole-pair screening threshold. That result does not establish equivalence or separability from drift. | None — not acquired. | `defer` (measured; not reacquired) — revisit only against a named scale threshold. | A replicated pitch effect localized between 0.617 and 2.960 mm (structure on a scale between the two corners) — that would put a rung back inside them. |
| **REF — 1.850 mm x 50 gates** (`res/1-8.BDD`) | Measured. One of the two realizations of the only same-settings level (`prf/600.BDD` vs `res/1-8.BDD`, 669 / 517 profiles, 14.956 / 11.5529 s), so it is the comparand the screening threshold is computed against. | **N/A** — it is the screening threshold's own comparand. | The anchor of every new condition, of each job's **block-local controls** and of the separate **common-reference checks** (§8.2). | None: the reference writes nothing but resolution and gates. | `keep` (measured; the controls are acquired) | A control set whose per-gate spread exceeds the committed screening threshold would say it is not transferable to the new run — see §6. |
| **R4 — 2.960 mm x 31 gates** (`res/3-0.BDD`) | Measured. The coarsest pitch in the set: 30 supported gates; its largest per-knot difference to any of the other 12 levels is **10.4324 mm/s = 0.5386** of the screening threshold (`resolution-ladder.provenance.json` `findings.coarsest_pitch`). Its 11.84 mm descriptive autocorrelation scale is a description of one profile, not a physical scale or adequacy criterion. | **No.** 0.5386 x the screening threshold; nothing coarser was measured. | Retained as the **coarse pitch corner** of the crossing (CC3/CC4) because its aligned differences remain small relative to the screening threshold, not because of a samples-per-correlation-length rule. | Same as R2: resolution + gates writers exist; the burst field is the gap. | `keep` (measured at the reference burst; acquire only *inside* the crossing) | A replicated difference to a finer level that establishes a pitch effect, or a named scientific requirement outside the measured 0.247-2.960 mm range. |

## 2. PRF axis

The corrected grouped ladder selects **5 decoded periods from 6 recordings**; the 600 µs level is realized by
both reference recordings (`findings.realizations`). Its corrected effect gate is **6 of the 10 pairs** above
the screening threshold, largest **38.14 mm/s** (400 vs 600 µs at 13.86 mm) = **1.969** x the screening
threshold (`findings.effect_gate`).

| Candidate | Existing evidence | Above the screening threshold? (where/depth or N/A; screening only) | Information gained | Automation needed | Verdict | Measurement that overturns it |
|---|---|---|---|---|---|---|
| **250 µs** (new) | Not measured. The committed low-period setting is 400 µs. The plan's two adequacy counts are answered at 400 µs: peak load as a fraction of the unambiguous limit = **0.7266** of 231.2064 mm/s, **0** samples at or beyond the limit, **0** wrap-like steps (largest consecutive step 0.6953 of `Vmax`), and the widest usable bandwidth in the ladder, **33.3599 Hz** of 16.4678-33.3599 (`prf-levels.csv`, row `prf/400.BDD`; `findings.velocity_headroom`, `findings.temporal_bandwidth`, `findings.focus_decision`). The largest absolute velocity in any of the 40 recordings is **196.53 mm/s** (`prf/500.BDD`); a 250 µs setting would move the limit to 369.9302 mm/s. | **N/A** — nothing needs the wider scale: no measured sample reaches the 400 µs limit, and the pressure on the velocity scale is a long-period problem (load 1.0625 at 500 µs, 1.2109 at 800 µs), not a short-period one. | None. A 250 µs acquisition would add scale no committed recording asks for, and its cost is that it would be the first setting whose rate is not an exact PRF multiple, which these files cannot fix (ratio spread 0.00625 relative). | Would need a new PRF write path if ever pursued; `prf_us` is a run-wide campaign field today. | `defer` (not acquired) — the plan's condition ("acquire 250 µs only if 400 µs is inadequate") is measured **false**. | A recording whose absolute velocity reaches the 400 µs unambiguous limit, or a stated scientific question needing temporal content above the 400 µs usable bandwidth (33.3599 Hz). |
| **400 µs** (`prf/400.BDD`) | Measured. 545 profiles, 8.1535 s, profile rate 66.7198 Hz, load 0.7266, 0 samples beyond the limit, 0 wrap-like steps. | **Yes** — as a pairwise fact only: 400 vs 600 puts knots above the screening threshold (max **38.14 mm/s** at 13.8627 mm = **1.969** x it); the 10-pair ladder clears in 6 pairs, all at a handful of knots. For attribution see the PRF limits below. | The known low-period anchor: the setting the plan's 250 µs question is decided against, and the only level that keeps margin at both the velocity limit and the bandwidth ceiling. | None — already measured; the first augmentation adds nothing at PRF. | `keep` (measured; no acquisition) | A replicated clearance that survives control-based drift screening, or a different setpoint at which this level's own load approaches its limit. |
| **600 µs** (`prf/600.BDD`) | Measured — the reference level, now a grouped mean of **two** realizations (`prf/600.BDD`, `res/1-8.BDD`): load 1.0586, **0.5** samples beyond the limit, **1** wrap-like step, usable bandwidth 22.0176 Hz, profile rate 44.6642 Hz; member of the WP1 pair. | **Yes** — as a pairwise fact only, through the pairs it forms with its neighbours; its own load exceeds 1.0 on the grouped mean. | It is the reference condition itself: the anchor every new condition is defined around, and the period the whole augmentation holds fixed. | None: `prf_us` is run-wide and the augmentation never moves it. | `keep` (measured; the reference) | A replicated PRF effect that separates a pair from drift, or a recorded wrap-like event at this period (measured today: 1 on the grouped mean). |
| **800 µs** (`prf/800.BDD`) | Measured. 539 profiles, 16.0267 s, load **1.2109**, **1** sample beyond the limit, **3** wrap-like steps (largest step 1.4531 `Vmax`), narrowest usable bandwidth 16.4678 Hz, rate 33.5690 Hz. | **Yes** — as a pairwise fact only: 800 vs 600 clears at knots; 800 vs 400 at knots; 800 vs 500 at knots; the level's own load is the ladder's largest. | None sought: the ladder's own load ordering says the long-period side is where the velocity scale is under pressure, and this is the level that shows it most. | None — not acquired. | `defer` (measured; not reacquired) | A stated question needing a longer period (e.g. a deeper window at a different setpoint), and then only with the echo/energy diagnostic in place — this is the one level whose measured load exceeds 1.0 by the widest margin. |

**What the PRF clearances are not.** **6 of the 10** grouped-level pairs clear the screening threshold; every
clearance is a handful of knots, none spans the support, and most levels have one recording while the 600 µs
reference level has two realizations. Without replicated axis coverage or acquisition order they do not
demonstrate a PRF effect relative to drift (`prf-ladder.provenance.json` `findings.limitations`). This table
therefore records them as pairwise facts that do not change any verdict above: no row here claims the PRF
*caused* a clearance.

## 3. Emissions/profile axis

Absent from the committed sweep: this is the one axis with **no measured variation at all**. All 40 manifest
rows carry `emissions_per_profile` = 20 (word 14), and the recorded time base independently gives
`dt / T_prf` = 37.3 on all forty points = `16 + N_PRF` with 0.6-1.0 ms of transit overhead
(`gain-power-screen.provenance.json` `findings.sensitivity`; `data/mixer-sensitivity-analysis/README.md`).

| Candidate | Existing evidence | Above the screening threshold? (where/depth or N/A; screening only) | Information gained | Automation needed | Verdict | Measurement that overturns it |
|---|---|---|---|---|---|---|
| **8** (new) | Not measured. No committed recording varies the axis; every file's word 14 is 20 and every file's time base agrees with it. | **N/A** — no measured variation exists to compare. | The low-averaging end, and the first point that would make the axis **readable from a file's own time base** rather than inferred: at ~15 ms per profile (matrix §9) the stored step itself states the setting. | `emissions_per_profile` is a **run-wide** campaign value today (`campaign.CampaignDefinition.emissions_per_profile`; points may not disagree) and is not in `actuator.PARAMETER_WRITE_ORDER` = `(RESOLUTION, GATES)`, although `ParamRole.EMISSIONS_PER_PROFILE` exists. One job per level needs no new writer; one run with per-point levels does. The runner's size guard already derives from the definition's emissions (`emissions x PRF + ~1 ms`), so it needs no change. | `keep` (acquire) | A control spread above the screening threshold inside the emissions jobs, or a refusal from the app's own period/size law at the shorter stored step — either says the condition cannot carry a bounded comparison yet. |
| **20** (reference) | Measured — it *is* the reference: 20 in all 40 rows, corroborated by the time base. | **N/A** | The axis's own reference: the comparand for 8, 64 and 128, and the value every common-reference check and every emissions block's own block-local controls carry. | None. | `keep` (measured; the controls are acquired) | A decoded word 14 that disagrees with the time-base recovery on a new file — that would mean one of the two paths is wrong and the axis is not readable the way this table assumes. |
| **64** (new) | Not measured, as above. | **N/A** | Moderate averaging: the third point of the four-level series, and the one that separates a low-averaging effect from a monotone one. | As for 8 (one job today, or a per-point writer for one run). | `keep` (acquire) | A control spread above the screening threshold inside the emissions jobs; or the axis proving unreadable (see 8). |
| **128** (new) | Not measured; same rationale. | **N/A** | The high-averaging end of the series, acquired as an **ordinary sparse point** — see §6 and the emissions design below. | As for 8: one job today, or a per-point writer for one run. | `keep` (acquire) | A control spread above the screening threshold inside the emissions jobs; or the axis proving unreadable (see 8). |

**The emissions design is one unconditional series.** The set is **E8, E20 (reference), E64, E128** — the second
of the two alternatives plan §8.2 R3 allows, with E128 an ordinary sparse point rather than a gated one.
**No E20-to-E64 displacement is called a plateau test**: each emissions level is confined to one run, so level and
run are confounded; the four same-setting acquisitions per level inside one run are within-run repeats and not
independent run-level replication of the axis; the design therefore does not attempt a plateau test. Every
condition in the set is unconditional.

## 4. Burst-length axis

The corrected grouped ladder is 13 levels (2-32 cycles) on the identical 50-gate 1.85 mm grid; the ladder's own
reference (10 cycles) is **not** in that folder — it is the reference condition (`res/1-8.BDD` / `prf/600.BDD`).
Its corrected effect gate is **22 of the 78 pairs** above the screening threshold, 17 of those involving the two
longest bursts, largest **44.03 mm/s** (4 vs 28 cycles) = **2.273** x it. No metric falls monotonically along
the ladder (`burst-ladder.provenance.json` `findings.knees`: every metric reports `monotone_decreasing: false`,
and the two largest one-step changes are the *rise* of robust spread at 4 cycles and the dropout/gradient step
at 28).

| Candidate | Existing evidence | Above the screening threshold? (where/depth or N/A; screening only) | Information gained | Automation needed | Verdict | Measurement that overturns it |
|---|---|---|---|---|---|---|
| **4 cycles** (`burst_len/4.BDD`) | Measured. 50 gates, 1.85 mm, mean 24.0755 mm/s, robust spread **34.3782 mm/s** (the ladder's largest one-step change, **+12.88**, and a *rise*), zero fraction 0.007692, descriptive correlation scale 12.95 mm (`burst-levels.csv`; `findings.knees.robust_spread_mm_s`). | **Yes**, as a pairwise fact: 4 vs 28 puts knots above the screening threshold (max **44.03 mm/s** at 10.1627 mm = **2.273** x it); 22 of the 78 pairs clear somewhere and 17 of those involve the two longest bursts. No pair in the 16-20-cycle region clears. | The short-burst corner of the crossing (CC1/CC3): half of the only design in which the pitch x burst interaction can be estimated at all. | `burst_length` is dialog-only and run-wide today (`actuator.DIALOG_ONLY_PARAMETERS`, `DialogField.BURST_LENGTH`; `campaign` carries it as a shared value). With today's writers the crossing runs as one job per burst length; a per-point burst write is needed for one randomized run. | `keep` (measured at the reference pitch; acquire only the crossing cells) | Two recordings at 4 cycles showing the spread rise is a property of the level rather than of one recording — or a replicated interaction contrast that makes the crossing's own cells redundant. |
| **10 cycles** (reference) | Measured — the reference condition (`res/1-8.BDD`, `prf/600.BDD`, burst 10, 1.85 mm). | **N/A** — it is the comparand of the screening threshold. | The anchor: every new condition, every block-local control and every common-reference check is defined by not moving it. | None. | `keep` (measured; the controls are acquired) | A control spread above the screening threshold inside the new run. |
| **20 cycles** (`burst_len/20.BDD`) | Measured. The plan's focus pair against 18 cycles: max abs diff **11.7519 mm/s** at 91.5627 mm = **0.6067** of the screening threshold, **0 of 50** knots above; the whole 16-20 region is below it (3 pairs, 0 clearing, largest 0.6504) (`burst-pairs.csv`; `findings.focus_18_vs_20`, `findings.focus_window_16_20`). | **No** against 18, and **No** anywhere in the 16-20 region. Against other levels it clears only in the long-burst pairs recorded on the 4-cycles and 32-cycles rows. | No 18-versus-20 effect is demonstrated relative to the observed-discrepancy screening threshold; the one observed step changes only below that reference (descriptive correlation scale +1.85 mm, median gradient -0.3215 mm/s/mm, robust spread +2.0610 mm/s, zero fraction -0.00081, >10 Hz share -0.00277, ACF lag 0). | None — not acquired. | `replace` (measured; dropped in favour of **18 cycles**) — chosen on cost, **not** on any claimed effect: see below. | Two recordings per cycle count in the 16-20 region separating the level effect from drift; that would let the pair be decided on evidence instead of on cost. |
| **18 cycles** — *introduced replacement* (`burst_len/18.BDD`) | Measured at the reference pitch: 50 gates, 1.85 mm, zero fraction 0.009190, descriptive correlation scale 11.1 mm, ACF lag 0.08956 s. Against 20 cycles the observed difference is 0.6067 of the screening threshold with 0 of 50 knots above it; no statistical equivalence is established. | **No** against 20; 0 of 50 knots. | **The information rationale is cost, not effect:** no measured quantity demonstrates a preference for 18 or 20, so the shorter pulse is taken — axial length 3.33 mm against 3.70 mm at c = 1480 m/s, marginally less delivered energy per emission and shorter ring-out at equal measured information; and it brackets the reference (10 cycles, 1.85 mm) at roughly equal log spacing together with 4 cycles (0.74 / 1.85 / 3.33 mm), which keeps the crossing's burst contrast two-sided rather than extreme-vs-reference. | As for 4 cycles. | `keep` (measured at the reference pitch; acquire the crossing cells at CC2/CC4) | Two recordings per cycle count at 18 and 20; or a replicated quantity that separates them — either would replace this cost choice with an evidential one. |
| **32 cycles** (`burst_len/32.BDD`) | Measured. Largest per-knot difference of the whole ladder region: 4 vs 28 max 44.03 mm/s = 2.273 x the screening threshold; the 28-led step in dropout (+0.0109 reaching 0.021174) and in worst gradient (+9.511 reaching 16.14 mm/s/mm) are the ladder's largest; 32's ACF e-folding lag is 0.11195 s against 0.08956 s at the reference, one profile period (0.02239 s) apart (`burst-levels.csv`, `findings.knees`, `findings.temporal_bandwidth`). | **Yes**, locally, in 17 of the 22 clearing pairs; never across the support, never monotone. | None that the two-sided corners do not already carry: 32 sits more than twice as far above the reference as 4 sits below it and carries the largest measured dropout and the widest bandwidth loss, so a corner there would confound the interaction contrast with the one level whose anomalies are single-recording. | As for 4 cycles. | `defer` (measured; not reacquired) | Two recordings at 28 or 32 cycles that separate the long-burst clearance from drift — the only way to find out whether the one systematically clearing region of the ladder is real. |

## 5. Sensitivity axis

The axis is absent: all 40 rows are `sensitivity` = `medium`, no screened axis varies it, and it is
unidentifiable from this sweep (`gain-power-screen.provenance.json` `findings.sensitivity`: `axis_present: false`,
`identifiable: false`).

| Candidate | Existing evidence | Above the screening threshold? (where/depth or N/A; screening only) | Information gained | Automation needed | Verdict | Measurement that overturns it |
|---|---|---|---|---|---|---|
| **medium** (reference) | Measured — every committed file; it is the base state's own value. | **N/A** | The comparand for the one higher condition; nothing else. | None. | `keep` (measured; the reference) | A control spread above the screening threshold inside the diagnostic run. |
| **one step higher** — *the introduced diagnostic* (§6, D1) | Not measured. Nothing in the committed set varies the axis, and no echo/energy channel exists in any file (`findings.velocity_only`: "one axial-velocity channel per file, in mm/s; no echo or energy profile"). | **N/A** — no measured variation exists. | The only measurement that can make the axis identifiable at all, and the echo/energy channel that tells SNR and saturation apart from the flow for the two TGC levels that already fail the dropout/spread screen. | Two gaps, and only one of them is a writer: (a) no `sensitivity` reader or writer exists — the dialog value table carries it as a combo row (`acquire/ui/dialog.py::dialog_value_fields`) but `DialogField` names only sound speed, first gate and burst length, and `ParamRole` has no sensitivity member; (b) the stored `.BDD` carries no echo/energy channel, so this condition **cannot be executed today by any writer** — the recording surface has to carry a second channel first. | `requires diagnostic` (acquire, once (a) and (b) land) | The manual criterion: if changing sensitivity changes the measured velocity distribution, Doppler energy is insufficient — that result re-opens transmitted power, TGC, seeding and coupling rather than the sensitivity value. |
| **one step lower** | Not measured, as above. | **N/A** | None until the higher condition is seen. | As for the higher condition. | `defer` (conditional) — acquired only if the higher condition changes validity or distribution (plan §5's own wording) | A diagnostic in which the higher condition already changes the distribution or validity — that would make the lower step the informative next measurement instead of a wider ladder. |

## 6. Conditions introduced by this decision

These rows exist because §1-§5 dropped rungs and the WP4 design needs a pitch x burst interaction that the
committed set cannot estimate: the resolution and burst ladders meet **only at the reference**, so no cell
combination of the two exists (`resolution-ladder.provenance.json` and `burst-ladder.provenance.json`
`findings.limitations`; plan §2). The crossing is **2 pitches x 2 burst levels = 4 cells**, not a Cartesian
product of the design's axes, and every cell holds the complete fixed facts of §7.

| Candidate | Existing evidence | Above the screening threshold? (where/depth or N/A; screening only) | Information gained | Automation needed | Verdict | Measurement that overturns it |
|---|---|---|---|---|---|---|
| **CC1 — 0.617 mm x 145 gates x 4 cycles** (new) | No cell measured. Its four sub-design neighbours all exist and are measured: `res/0-6.BDD` (0.617, burst 10), `burst_len/4.BDD` (1.85, 4), `res/1-8.BDD` / `prf/600.BDD` (1.85, 10). | **N/A** — the cell is new; the interaction it measures has no measurement in the committed set at all. | The first pitch x burst interaction contrast at the fine pitch: one corner of a 2x2 whose other corners are already committed. Also the setting where the finest retained pitch meets the shortest pulse. | Resolution + gates writers exist; `burst_length` is dialog-only and run-wide, so today this is one job per burst length (see CC2). No new writer is needed if the crossing runs as two jobs. | `keep` (acquire) | Two recordings of this cell (replication) showing no interaction, or a control spread above the screening threshold inside the job that contains it. |
| **CC2 — 0.617 mm x 145 gates x 18 cycles** (new) | As CC1. | **N/A** | The same contrast at the level the burst ladder cannot decide against 20 cycles; completes the fine-pitch 2x2 against the committed `res/0-6.BDD` and `burst_len/18.BDD`. | As CC1. To place CC1-CC4 and their block-local controls in **one** randomized run, a per-point `burst_length` write is required (dialog row: burst length is a combo whose choice is the value). | `keep` (acquire) | As CC1. |
| **CC3 — 2.960 mm x 31 gates x 4 cycles** (new) | No cell measured. Neighbours: `res/3-0.BDD` (2.960, burst 10, descriptive correlation scale 11.84 mm), `burst_len/4.BDD`. | **N/A** | The coarse-pitch end of the interaction: whether the structure the coarse grid still resolves changes when the pulse lengthens past the gate pitch. | As CC1. | `keep` (acquire) | A replicated loss of structure at this pitch that makes the coarse corner indefensible; or replication showing no interaction. |
| **CC4 — 2.960 mm x 31 gates x 18 cycles** (new) | As CC3. | **N/A** | Completes the coarse 2x2 against `res/3-0.BDD` and `burst_len/18.BDD`. | As CC2. | `keep` (acquire) | As CC3. |
| **BLOCK-LOCAL-CTRL — each scientific job's own anchor repeated at that job's run-wide values, at the beginning/middle/end of the run** (new repeats) | The only committed same-settings level is the WP1 pair — **one** level with two realizations, which is why every verdict above is a screening comparison against a screening threshold rather than a repeatability estimate (`reference-repeat.provenance.json` `screening_threshold.scope`). | **N/A** — this row is the within-run drift diagnostic, and it is **not** the common reference condition: for a burst block it repeats the reference spatial window (1.850 mm, 50 gates) at burst 4 or 18, and for a one-condition emissions block it repeats that emissions level itself. | Three recordings per scientific job in place of one committed repeat: one minimum within-run drift diagnostic whose two **adjacent** differences share the middle recording and are therefore **correlated**. It says nothing about the common reference condition and is never screened as if it were burst 10 / emissions 20. For the three one-condition emissions jobs those three recordings are additional realizations of that emissions level — **four same-setting acquisitions inside one run** — which sharpens that level's own within-run measurement rather than replicating the axis. | None: the anchor writes only resolution and gates, and the campaign runs the definition's point order literally, so the controls are a definition-authoring rule (position), not a code change. | `keep` (acquire, 3 per scientific job) | A control set whose per-gate spread exceeds the screening threshold inside its own job: that would say that run is drifting more than the committed dataset and the control count/duration must be raised before any other verdict is read. |
| **COMMON-REFERENCE — the true reference condition (1.850 mm, 50 gates, burst 10, emissions 20, sensitivity medium), one recording in each of four separate reference-only jobs placed between the five scientific jobs** (new repeats) | As the reference row above: one committed same-settings level with two realizations, which is why the screening threshold is one observed discrepancy rather than a repeatability estimate. | **N/A** — this is the new measurement of the sole-pair observed-discrepancy screening threshold at the one common condition. | The between-job check the superseded schedule could not execute: `CampaignDefinition` fixes `burst_length` and `emissions_per_profile` once per campaign, so a burst-4/18 or an emissions-8/64/128 job cannot hold a burst-10/emissions-20 point. Four such jobs put the true common condition between the scientific blocks. | None: the reference writes only resolution and gates, and each of these jobs needs no new writer. | `keep` (acquire, 1 per common-reference job) | A common-reference spread whose per-gate mean difference exceeds the screening threshold at any gate: that would say the new run is drifting more than the committed dataset and the control count/duration must be raised before any other verdict is read. |

## 7. The draft's excluded axes (its own review question 7)

Neither row is a draft candidate level; both were left open by the draft's "Power and TGC" section and by
question 7, and the plan's §1 decision table asks for a verdict on each. The corrected screen is **12 levels
over two axes and 39 pairs**, **2 levels flagged**, and **17 of the 39 pairs** clear the screening threshold
somewhere (`findings.screen_summary`).

| Candidate | Existing evidence | Above the screening threshold? (where/depth or N/A; screening only) | Information gained | Automation needed | Verdict | Measurement that overturns it |
|---|---|---|---|---|---|---|
| **TGC ladder** — the 9 committed levels (`tgc/0.BDD` … `tgc/40.BDD`, with the base state a level realized by both reference recordings) | Measured. The base-state bracketing pair `prf/600.BDD` vs `tgc/25.BDD` (19.9216 / 24.9412 dB) differs by at most **15.4 mm/s** at 63.8127 mm = **0.795** of the screening threshold, **0 of 50** knots; the axis's largest pair is **47.10 mm/s** (`tgc/30.BDD` vs `tgc/40.BDD` at 73.0627 mm = **2.432** x it). **17 of 36** TGC pairs clear the screening threshold somewhere. Three flag instances on two levels: `tgc/0.BDD` dropout-limited (overall 0.2437; 10 of 50 gates at 84.1627-100.813 mm, up to 0.8111 blank) and `tgc/40.BDD` dropout- **and** spread-limited (one majority-blank gate at 69.3627 mm; worst per-gate robust spread **148.1166 mm/s** = **4.97** x the axis median 29.8039 mm/s). | **Yes**, locally: 17 of 36 pairs, a few knots each, never across the support — and unattributable, because these files carry velocity only. | A wider TGC ladder adds **nothing identifiable first**: the representation itself is unsettled (word 23 stays 0 / `uniform`, word 25 stays 255, only word 24 moves — no validated scalar gain set point), and echo SNR, receiver saturation and a safe plateau are not measurable in these files. | A TGC writer does not exist (dialog-only) — and designing a wider ladder on the decoded word-24 reading is what the screen refuses until the representation is settled. | `requires diagnostic` — the echo/energy diagnostic before any wider TGC ladder (the committed verdict: `findings.diagnostic` `justified: true, wider_ladder_justified: false, outcome_claimed: false`). | The diagnostic showing the two flagged levels are a gain/energy effect rather than one recording, drift or the flow. |
| **Emitting-power ladder** — the 3 committed levels (`em_pow/low.BDD`, `em_pow/high.BDD`, and the base state as a level) | Measured. The whole power ladder differs by at most **13.39 mm/s** at 58.2627 mm = **0.691** of the screening threshold, **0 of 50** knots above it; no level carries a majority-blank gate or a per-gate spread past 3x the axis median (0 of 3 flagged) (`gain-power-pairs.csv`; `findings.axes.em_pow`). | **No.** 0 of 3 pairs; the largest difference is 0.691 x the screening threshold. | None in velocity: the axis is unremarkable at the committed resolution, and the bracketing is only three levels wide. | A power writer does not exist (dialog-only). | `defer` (measured; no wider ladder) | The echo/energy diagnostic showing the power axis matters (a saturation or energy effect invisible in velocity), or a replicated difference that clears the screening threshold. |

## 8. What the first measured augmentation is

### 8.1 Fixed facts — held by every new condition

Every value below is either the committed reference's own decoded value (`manifest.csv`, `res/1-8.BDD` and
`prf/600.BDD` rows; plan §2) or a setting the plan fixes. None of them is a new measurement, and none is swept.

| Fact | Value | Where it is evidenced |
|---|---|---|
| emitting frequency | 4 MHz | 40/40 manifest rows (`emit_freq_khz` 4000) |
| sound speed | read back and recorded (**not** fixed at 1480 by assumption) | `sound_speed_ms` 1480 in all 40 rows; the stored file stays the authority |
| Doppler angle | 0 | all 40 rows |
| first gate | ~10.163 mm (10.1626666667 mm decoded) | all 40 rows |
| observation window | the instrument's own gate grid over ~10.163-96.743 mm (keep it by compensating gates with pitch) | plan §2; `resolution-levels.csv` `support_min_mm` / `support_max_mm` |
| PRF period | **600 µs** (fixed for the whole augmentation) | `prf/600.BDD`; `findings.focus_decision` |
| emitting power | `medium` | all 40 rows |
| TGC | the committed representation: word 23 = 0 (`uniform`), word 25 = 255 (fixed 40 dB end), word 24 start = 19.9216 dB | matrix §8; `gain-power-screen.provenance.json` `definitions.tgc_representation` |
| sensitivity | `medium` — except the single blocked D1 diagnostic, scientifically selected at the operator-approved `high` (§8.2) | `findings.sensitivity` |
| velocity scale | 1 | plan; draft's reference table |
| assisted mode / filtering / alias auto-correction | OFF | the run's own recorded state |
| skipped profiles | 0 | word 84 = 0 in all 40 rows |
| sampling volume | **read back only**, never assumed: word 27 is the instrument's bandwidth-list index (4), and `sampling_volume_mm` stays unset | plan §2; matrix §9 |
| duration | one fixed window per job, **>= 11.52 s** — the smallest defensible assumption, not an established fact (§8.5) | WP1 common-duration view: 96 revolutions = 11.52 s |

### 8.2 Complete new conditions — the machine-readable rows

**Eight unique conditions, every one unconditional, in one executable schedule.** `CampaignDefinition` fixes
`burst_length` and `emissions_per_profile` once for a whole campaign, so a `job` is a set of rows that agree on
both and `block` names the scientific block they belong to; `control_kind` is `block-local`,
`common-reference` or `none` for a scientific condition; `executable` says whether today's writer surface can
record the row at all; and `recordings` is the number of recordings the row contributes to its job. This is one
row set, carried identically by [`docs/dop3000/sparse-parameter-set.md`](../../docs/dop3000/sparse-parameter-set.md)
§3.1 and checked by `tools/validate_decision_layer.py`, which refuses the two documents if their rows differ.

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

**D1 is scientifically selected and blocked.** Its sensitivity is `high`, the exact canonical option immediately
above `medium` in the application's own sidebar sensitivity dropdown, read from that dialog and then restored
without recording; its echo/energy channel does not exist in the recording surface yet, so the row carries
`executable = no`, the `none` job marker and no executable total (§9).

Pitch must be **requested in mm and read back** from the file (word 10): the rung labels are the instrument's and
the mm value is `c`-dependent, so no condition here may be identified by a folder name or a label.

**The emissions sequence is E8, E20 (reference), E64, E128**, all unconditional. E128 is an ordinary sparse
point, not a gated one: **no E20-to-E64 displacement is called a plateau test**, and the design makes every
condition unconditional.

### 8.3 Block-local controls and common-reference checks

Two different things, kept different in names, rows and analysis:

- **Block-local controls** repeat each scientific job's **own anchor** at that job's run-wide burst and emissions
  values, three recordings at the beginning, middle and end of the run. For the two burst blocks the anchor is the
  reference spatial window (1.850 mm x 50 gates) held at burst 4 or 18 — the conditions the committed sweep already
  holds as `burst_len/4.BDD` and `burst_len/18.BDD` — so those controls re-acquire those conditions and are **not**
  duplicates of CC1-CC4, which move resolution and gate count. For a one-condition emissions block the three repeats
  carry **exactly the same settings as that block's designated scientific row**, giving four same-setting
  acquisitions inside one run (1 designated scientific acquisition + 3 block-local acquisitions): that is within-run
  repeated measurement of that level, not independent run-level replication of the axis. They diagnose within-block
  drift only, and **none of them is the common reference condition**: they are never screened as if every one were
  burst 10 / emissions 20.
  Their two **adjacent** differences (beginning→middle and middle→end) share the middle recording and are
  **correlated**, not independent, so neither difference is a separate observation of an anchor level.
- **Common-reference checks** are the true **reference condition** (1.850 mm x 50 gates, burst 10, emissions 20,
  power `medium`, TGC as §8.1, sensitivity `medium`) recorded **once** in each of four separate reference-only
  jobs whose intended execution placement is between consecutive scientific jobs (the rows encode membership and
  count, not sequence — §8.3). They are between-job checks of the one common condition, not
  beginning/middle/end controls inside another run, and they are the direct check that the committed 19.3701 mm/s
  screening threshold transfers to the new run.

The name **within-run reference controls** is **no longer** used in this table: it called both types one thing, and
`CampaignDefinition` runs a whole campaign at one `burst_length` and one `emissions_per_profile`, so a burst-4/18
or an emissions-8/64/128 job cannot hold a burst-10/emissions-20 point at all.

**The rows and counts encode membership, run-wide compatibility, control type and count — not execution
sequence.** The intended within-job order is a block-local control at the beginning of a run, the run's
scientific points, one around the middle and one at the end; the intended cross-job order places a
common-reference job between consecutive scientific jobs. The campaign runs a definition's point order literally,
and a cross-job order cannot be expressed by one definition at all, so both orders are the
campaign-definition/run-plan PR's to encode and test (`sparse-parameter-set.md` §3.1, §9).

### 8.4 Already satisfied by existing data vs what actually needs acquisition

| Already satisfied — no instrument time | Needs acquisition |
|---|---|
| 0.617 mm pitch (`res/0-6.BDD`) at the reference burst | CC1, CC2 — 0.617 mm with burst 4 and 18 |
| 1.850 mm reference (`res/1-8.BDD`) | CC3, CC4 — 2.960 mm with burst 4 and 18 |
| 2.960 mm pitch (`res/3-0.BDD`) at the reference burst | E8, E64, E128 — the axis's first measured points |
| 1.233 mm pitch (`res/1-2.BDD`) — kept only as a deferral, not a rung | D1 — the one higher-sensitivity + echo/energy diagnostic, blocked today |
| PRF 400 / 600 / 800 µs (all measured) | block-local controls — 3 recordings per scientific job, at that job's own run-wide values; common-reference checks — 1 recording in each of the 4 reference-only jobs |
| burst 4, 18, 20, 28, 32 cycles at the reference pitch | |
| all 9 TGC levels and all 3 power levels; emissions 20 | |

**Counts, derived from the §8.2 rows.** The counts below are recomputed from the table by
`tools/validate_decision_layer.py`, which refuses a document whose declared value disagrees:

| count | value |
|---|---|
| unique_new_conditions | 8 |
| blocked_conditions | 1 |
| executable_scientific_recordings | 7 |
| block_local_control_recordings | 15 |
| common_reference_recordings | 4 |
| executable_jobs | 9 |
| recordings_first_pass | 26 |

Nine executable jobs under today's writers: the five scientific jobs (`burst-4`, `burst-18`, `emissions-8`,
`emissions-64`, `emissions-128`, one per distinct run-wide value — the crossing running as one job per burst
length and the emissions series as one job per level) and the four common-reference jobs whose intended placement
is between consecutive scientific jobs.
The first pass is **26 recordings** — 7 executable scientific recordings (CC1-CC4, E8, E64, E128), 15
block-local controls (3 per scientific job) and 4 common-reference checks (one per common-reference job) — and
that 26 is a coincidence of this derivation, not a preserved construction: the superseded six-job schedule
reached the same total by placing three reference-condition recordings inside every run, which
`CampaignDefinition` cannot execute. D1 is counted as the eighth unique condition and as the one blocked
condition, in no executable total.

### 8.5 Protocol assumptions the evidence cannot settle

Both are stated as assumptions with a revising condition, because nothing in the committed artifacts fixes them:

- **Fixed duration.** The committed durations span **8.1535-16.0267 s** and the comparison windows used by the
  reports span 8.04-11.52 s, so no single value is established. Smallest defensible assumption: **every job
  records for one fixed window of at least 11.52 s** (WP1's 96 nominal 500-RPM revolutions, 0.12 s each), so a
  new record can always be truncated to the same common-duration window as its comparand. Revised by: a selected
  segment rule that needs more than the window provides — WP1's temporal view needs 6-7 whole 1.9031 s segments,
  and the PRF ladder needed 8.1535 s for five whole 1.6 s segments (`reference-repeat.provenance.json`
  `views.temporal`; `prf-ladder.provenance.json` `views.temporal`) — or a control spread above the screening
  threshold.
- **Reference replication count.** One committed repeat cannot say how many repeats are enough. Smallest
  defensible assumption: **3 block-local controls per scientific job** (beginning/middle/end), which turns one
  committed difference into two adjacent, correlated within-run differences. Revised by: a control spread whose per-gate mean difference
  falls above the screening threshold (**19.3701 mm/s**) at any gate — that raises the count (a control at each
  block boundary, or a repeated run) and is the first thing to check before any other verdict above is read;
  and by any decision to treat a block as an independent replicate, which no analysis in this PR does.

## 9. Automation writers needed

The scientific set is ahead of the writer surface, and the gap is specific (`docs/dop3000/sparse-parameter-set.md`
carries the same list as the design's prerequisite):

| Needed for | Gap, as the code shows it today |
|---|---|
| the crossing as **one** randomized run (CC1-CC4 + controls) | `burst_length` is dialog-only (`acquire/actuator.py::DIALOG_ONLY_PARAMETERS`) and run-wide (`campaign.CampaignDefinition.burst_length`); no per-point write exists. Without it the crossing runs as one job per burst length, each holding that block's two points and its three block-local controls, which is executable today. |
| the emissions levels in one run (E8, E64, E128) | `emissions_per_profile` is run-wide (`campaign.CampaignDefinition.emissions_per_profile`: points may not disagree) and absent from `PARAMETER_WRITE_ORDER` = `(RESOLUTION, GATES)`, although `ParamRole.EMISSIONS_PER_PROFILE` exists. One job per level needs no new writer; one run with per-point levels does. The runner's size guard already derives from the definition's emissions, so it needs no change. |
| the sensitivity diagnostic (D1) | No `sensitivity` reader or writer: the dialog value table carries it as a combo row (`acquire/ui/dialog.py::dialog_value_fields`) but `DialogField` names only sound speed, first gate and burst length. |
| the echo/energy channel (D1) | Not a parameter write at all: the stored `.BDD` carries one axial-velocity channel, and no echo or energy profile exists in any committed file (`findings.velocity_only`). The recording surface must carry the second channel before D1 can be recorded. **D1 is therefore the one condition in §8.2 that cannot be executed by any writer today: it carries `executable = no`, belongs to no executable job and enters no executable total.** |
| already covered — no work | resolution + gates are per-point writes; `prf_us` is a run-wide field and stays at 600 µs; TGC, emitting power, sound speed, first gate and sampling volume are not varied at all; the campaign already runs the definition's point order literally, so the beginning/middle/end controls are a definition-authoring rule rather than code. |

## 10. Reviewer path

1. `resolution-pairs.csv` — the `res/0-2.BDD` - `res/0-6.BDD` row (0.3156, 0 knots above the screening
   threshold) and the `res/1-2.BDD` - `res/1-6.BDD` row (0.8966), then `resolution-ladder.provenance.json`
   `findings.screening_threshold_gate`, `findings.information` and `findings.coarsest_pitch`.
2. `burst-pairs.csv` — the `burst_len/18.BDD` - `burst_len/20.BDD` row (0.6067, 0 of 50 knots above the
   screening threshold) and the 4-vs-28 row (2.273), then `findings.knees` (non-monotone) and
   `findings.focus_window_16_20`.
3. `prf-levels.csv` — the `prf/400.BDD` row (`load_max_over_velo_max` 0.7266, `samples_beyond_limit` 0,
   `wrap_like_events` 0, `usable_bandwidth_hz` 33.3599) and the 800 µs row (1.2109, 1, 3, 16.4678), then
   `prf-ladder.provenance.json` `findings.effect_gate` (6 of the 10 pairs) and `findings.focus_decision`.
4. `gain-power-screen.provenance.json` — `findings.screen_summary` (12 levels, 39 pairs, 2 flagged),
   `findings.sensitivity` (`axis_present: false`), `findings.velocity_only` (no echo/energy channel) and
   `findings.diagnostic` (`justified: true`, `wider_ladder_justified: false`).
5. `docs/dop3000/sparse-parameter-set.md` — the design this table gates, with the same rows and the same counts.
6. `sha256sum` the artifacts against the **Binding** table above.

**Limitations carried by every verdict here.** One same-settings level only, so the committed screening threshold
is one observed realization of repeatability *plus* uncontrolled drift and a clearance can still be drift. No
acquisition order, so no time drift is reconstructed. Most levels have one recording and the shared reference
level has two realizations; **one duplicated setting is not replicated axis coverage**, so no verdict is
replicated axis evidence and no p-value is produced. Velocity only: echo SNR, receiver saturation, a safe
plateau and acoustic energy are neither measured nor inferred. The pitch x burst interaction is not estimable
from the committed set, which is why §6 is new measurements rather than a re-reading. The TGC axis is screened
through an unsettled representation, not a validated gain ladder.
