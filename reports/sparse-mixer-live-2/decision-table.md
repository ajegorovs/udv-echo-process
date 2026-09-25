# WP5 - the Stage-2 decision

The six slices this decision reads - the five measurement slices and the Stage-2 campaign's own - are frozen; this document decides nothing about what was measured, and everything about what may be concluded for the next acquisition. Every number below is read from a slice's own artefact (the revision and digest of each are in `decision-table.json`), and a slice that is missing, failed its own gate, or disagrees with another about a floor stops this document from being written at all.

## The floors this decision stands on

| floor | value [mm/s] | endpoint | from | applies to |
|---|---|---|---|---|
| between-run reference, depth-resolved | 14.201 | depth-resolved: one per-depth difference array, or its extreme | WP2 | every per-gate comparison in WP3 and WP4 |
| between-run reference, depth-averaged | 2.344 | depth-averaged: one unweighted mean over the supported gates | WP2 | every scalar comparison, and the only endpoint like for like with WP1 |
| burst-4 job's own anchor spread | 8.194 | block-local anchor spread inside one job | WP1 | the conservative guard on the burst-4 job's contrasts |
| burst-18 job's own anchor spread | 1.996 | block-local anchor spread inside one job | WP1 | the conservative guard on the burst-18 job's contrasts |
| emissions-8 job's own anchor spread | 4.455 | block-local anchor spread inside one job | WP1 | the E8 row's within-job bracketing |
| emissions-64 job's own anchor spread | 0.634 | block-local anchor spread inside one job | WP1 | the E64 row's within-job bracketing |
| emissions-128 job's own anchor spread | 1.590 | block-local anchor spread inside one job | WP1 | the E128 row's within-job bracketing |
| the Stage-2 campaign's own scalar floor | 9.404 | the campaign's own observed run-to-run maximum, scalar reduction: the larger of its two levels' largest absolute difference over that level's six unique run pairs | stage2 | the four paired E64-minus-E20 contrasts of that campaign |
| the Stage-2 campaign's own per-gate floor | 28.548 | the campaign's own observed run-to-run maximum, per gate, over the common support | stage2 | the depth-resolved reading of the same four contrasts |

## The five questions the plan's gate asks, in its order

**1. which axes can be collapsed or fixed?**

the emissions axis, on cost at both upper levels: **E20 is retained as the reference and default condition**, E8 stays useful for bandwidth, and neither upper level is worth acquiring again in this design - E128 because no measured quantity prefers it and its period is a factor of 1.79 longer than E64's, and E64 because the targeted contemporaneous campaign this pass recommended has since been run and detected no improvement over E20 large enough to separate from the variation that campaign measured for itself (answer 4). **`E128 is replaced by E64` is no longer the current state of the axis**: E64 is not the level to move to, E20 is. The pitch axis is not collapsed: its interaction is unresolved at this design's floors, which is a statement about separability rather than about the axis being irrelevant. The burst axis stays at the two levels the historical table already fixed (4 and 18 cycles at the reference pitch), and the new information here is that the burst jobs' own anchors move by 10-12 mm/s, which is what makes finer burst contrasts unresolvable rather than unnecessary.

**2. which interactions matter?**

one is estimable in this pass and it is the one the design crossed: pitch x burst. Its scalar magnitude is larger than the between-run reference variation and smaller than the movement of the anchors inside its own two jobs, so it matters as a *shape* (locally from -11.709 mm/s at 42.698 mm to +15.506 mm/s at 84.138 mm - a local magnitude as large as 15.506 mm/s - and the sign changes across the profile) and not as a statement of magnitude. No other interaction is estimable: the emissions ladder is one axis at one set of conditions, and the pass varies nothing else in a crossed way.

**3. which levels are redundant?**

on current evidence, **neither E64 nor E128 is justified for further acquisition in this design**. E128 because no depth-averaged improvement over E64 is detected and a fixed 2 s block holds 23 profiles against 41 at E64; E64 because the contemporaneous test of it has now been run and no emissions-64 improvement over emissions 20 was detected above that campaign's own floor (answer 4). **E20 remains the reference and default condition**: it is the only level with more than one realization of its own *and* the level the paired campaign measured against, which is what makes any between-run statement possible at all. **E8 remains useful for bandwidth**: it carries the ladder's advantage with no measured stability cost. Not detected is not the same as absent at any of these levels - it is a statement about the floors each one was screened against. The emissions levels' three block-local anchor sets are not redundant either: they are each job's own drift diagnostic and the reason every E-level comparison has a within-job context.

**4. is a denser second acquisition justified at all?**

not as a dense pass, and no longer as a bounded one either. The pitch x burst interaction is limited by the burst jobs' own anchor movement, which more points of the same design do not shrink. The emissions ladder's one unresolved distinction (E20 against E64) was limited by how many runs each level has rather than by the rig, and the observed difference then straddled the 2.344 mm/s floor depending on which E20 run was used - so that one distinction was worth spending recordings on, and not by acquiring emissions 64 alone: runs made in a later campaign and screened against this pass's emissions-20 runs would be separated by a campaign as well as by an emission level. Realizations of both levels inside one campaign were therefore acquired (answer 5), and **that campaign's result closes the question at its own resolving power**: no emissions-64 improvement over emissions 20 was detected above the variation the campaign measured for itself, in either direction, depth-averaged or per gate. Nothing measured here now argues for a denser acquisition of any kind.

**5. if it is, which small set of new conditions, and what does each buy?**

**the one bounded set this pass recommended was the eight-job Stage-2 campaign**, and this is the record of it: E20-A, E64-A, E64-B, E20-B, E20-C, E64-C, E64-D, E20-D - four counterbalanced pairs, so each level led two pairs and followed in two and slow drift was sampled by both, with emissions per profile the only setting that differed (1.850 mm, 50 gates, burst 10, PRF 600 us, and the same power, sensitivity, TGC, first gate, sound speed and duration). It bought the one thing the ladder could not supply: four emissions-64 and four emissions-20 observations made contemporaneously, a floor measured inside that same campaign, and four adjacent paired contrasts oriented E64 minus E20. **It has since been run**, and its result is unresolved overlap / not detected: every one of the four contrasts sits inside the floor that campaign measured for itself and they do not share a direction. **No further emissions acquisition is currently recommended from this workstream** - the set recommended by this pass has been acquired, analysed and incorporated into the E64-vs-E20 row above, and nothing in its result names a measurement worth buying next.

## The decision table

The seven columns are the historical sweep's, so the two tables compare: the evidence, the floor the effect was screened against, the observed effect, the interpretation, the automation needed, the verdict and the measurement that would overturn it. `decision-table.csv` carries the same rows plus the machine fields (`key`, `decision_class`, `scope`, and both numeric effect columns).

### the pitch x burst interaction (0.617 against 2.960 mm, burst 4 against 18): may its magnitude be stated, and is a denser pitch sweep justified by this pass?

- **verdict:** `defer` - stage-2 decision
- **decision class:** `not resolvable with this design`
- **evidence:** WP3's crossed 2x2 on 31 common knots no finer than 2.960 mm, with each corner sampled at its nearest native gate; WP1's per-job anchor spreads as the within-job guard; WP2's two endpoints.
- **floor:** the scalar reads against WP2's depth-averaged endpoint, 2.344 mm/s, and the conservative guard is each burst job's own anchor spread, 8.194 mm/s (burst-4) and 1.996 mm/s (burst-18); the per-knot magnitudes read against the depth-resolved endpoint, 14.201 mm/s
- **observed effect:** the scalar interaction is +1.083 mm/s, i.e. 0.46x the depth-averaged floor, and it stays below both anchor guards (8.194 and 1.996 mm/s); depth-resolved it reaches -11.709 mm/s at 42.698 mm and +15.506 mm/s at 84.138 mm, with 1 of 31 knots above the depth-resolved floor, 7 above the burst-4 guard and 25 above burst-18's
- **interpretation:** an interaction-shaped difference is present and is *larger* than the campaign's own between-run reference variation, but it is *smaller* than the movement of the anchors inside the two jobs it came from: the pass cannot separate its scalar magnitude from that movement, so this is a limitation of separability and NOT evidence that the interaction is absent. Locally it changes sign, and some knots exceed the anchor-spread guards; those local crossings do not establish a replicated interaction magnitude across the two moving burst jobs.
- **automation needed:** none for the pitch axis as measured: the corners write only resolution and gates, and no new dialog value is needed. Shrinking the guard would need something other than an acquisition change - the anchors' movement inside a burst job is itself unexplained.
- **would be overturned by:** burst-job realizations whose own anchor spread is materially smaller than 10-12 mm/s (which is a diagnostic question about what moves inside those jobs, not a denser sweep), or a replicated interaction whose scalar magnitude exceeds the anchor guards at every realization

### does emissions 8 lose useful estimator stability against emissions 20?

- **verdict:** `keep` - stage-2 decision
- **decision class:** `not detected at this design's floors`
- **evidence:** WP4's ladder: E8 is one scientific recording inside its job's three block-local anchors, E20 is the four common-reference runs; both are reduced on the same 12 s window and the same 49-gate support.
- **floor:** WP2's depth-averaged endpoint, 2.344 mm/s, for the E8-to-E20 step, with E8's own anchor spread, 4.455 mm/s, as its within-job context
- **observed effect:** the E8-to-E20 depth-averaged differences span +2.679 to +5.023 mm/s across the four E20 runs, a spread of 2.344 mm/s, which is the E20 level's own run-to-run spread; E8's own anchors move by 4.455 mm/s and its profile rate is the ladder's highest at 65.789 Hz
- **interpretation:** no stability loss is detected at the floors this pass has: every E8-to-E20 difference lies inside the E20 runs' own spread, E8's own anchors are the quietest of the three single-recording levels, and E8 carries the ladder's strongest temporal-bandwidth advantage. Not detected is not the same as absent, but nothing measured here points the other way.
- **automation needed:** none: E8 is already writable and was written in this pass
- **would be overturned by:** an E8-to-E20 difference outside the four-run spread at replicated realizations, or an E8 residual against its own anchors exceeding that job's own anchor spread

### does emissions 64 improve the estimate enough over emissions 20 to justify its slower profile rate?

- **verdict:** `replace` - stage-2 decision
- **decision class:** `not detected at this design's floors`
- **evidence:** the counterbalanced Stage-2 campaign - the one this table's own recommendation asked for, since acquired and frozen - read through its own slice: eight run-level jobs in four pairs, emissions per profile the only run-wide setting that differs, every pair read E64 minus E20 whatever order it was acquired in, with each pair's acquisition orientation retained. This pass's ladder is kept beside it as the prior context that made the campaign necessary.
- **floor:** the campaign's own scalar floor, 9.404 mm/s - measured on its own eight runs, from the larger of its two levels' six-pair maxima - applied to its four paired contrasts; depth-resolved, the campaign's own per-gate floor, 28.548 mm/s at 15.688 mm. The earlier pass's 2.344 mm/s is quoted as prior context and screens nothing here: that pass observed both levels inside one campaign, but with one emissions-64 realization against four emissions-20 runs, so its floor cannot separate the step from whichever emissions-20 run it is read against - and topping emissions 64 up alone would have crossed a campaign, which is the confounding the paired design exists to remove.
- **observed effect:** the four paired contrasts are A +7.2256, B -1.5733, C +0.3448, D +1.3418 mm/s, i.e. A acquired 20 -> 64, B acquired 64 -> 20, C acquired 20 -> 64, D acquired 64 -> 20, all oriented E64 - E20; 0 of the four exceed the 9.4044 mm/s floor and their directions are not consistent, so the largest |contrast| is 7.2256 mm/s. Depth-resolved, 0.0% of the 50 supported gates are resolved and no gate has even one pair above the 28.5481 mm/s per-gate floor. The scalar floor is set by this level's own worst same-level disagreement (E20 at 9.4044 mm/s) rather than by the emissions-64 side, whose four runs are tight.
- **interpretation:** no emissions-64 improvement over emissions 20 is detected at this experiment's resolving power: all four contemporaneous paired contrasts sit inside the floor that same campaign measured for itself and they do not share a direction, so the step is neither shown better nor shown the same. **Not detected is not the same as absent** - it is a statement about this campaign's resolving power, and the floor is set by one emissions-20 run rather than by the emissions-64 side. The practical consequence is a cost decision, not a supersession: no evidence-based reason remains to pay emissions 64's slower profile rate for this setup, so `replace` here means **do not spend further acquisition effort on emissions 64 in this design and keep emissions 20's higher rate**. `defer` would now mean waiting for a measurement that this campaign was designed to supply and did.
- **automation needed:** none: E64 is already writable and was written in the campaign
- **would be overturned by:** an emissions-64-minus-20 difference that exceeds a contemporaneous campaign's own floor in a consistent direction - more runs per level inside one campaign, or a setup where the longer coherent integration is needed for a reason this campaign did not test (a slower or noisier flow). A single extra pair would not do it: this campaign's floor is one level's own worst same-level disagreement, so it takes replication on both sides rather than one more recording.
- **what this row said before:** `defer` / not resolvable with this pass's design: the emissions-20 level already had four realizations - the four common-reference runs, the only level of the ladder observed in more than one run - while emissions-64 had one scientific recording bracketed by its own anchors, so the E64-to-E20 step changed classification with whichever of the four E20 runs it was compared against, and the pass could neither show E64 better nor show it the same. Both levels were recorded inside this one campaign; the confound the row named was prospective rather than already present - an emissions-64-only top-up acquired later would have been separated from these four emissions-20 runs by a campaign as well as by an emission level - and the overturning measurement the row named, realizations of both levels inside one campaign, is the campaign this row now reads.

### does emissions 128 improve the estimate enough over emissions 64 to pay its cost?

- **verdict:** `replace` - stage-2 decision
- **decision class:** `not detected at this design's floors`
- **evidence:** WP4's ladder and its temporal view measured from the stored per-profile timestamps, at the same 12 s window and support for the velocity side.
- **floor:** WP2's depth-averaged endpoint, 2.344 mm/s; E128's own anchor spread, 1.590 mm/s, as its within-job context
- **observed effect:** the E64-to-E128 depth-averaged difference is -1.615 mm/s, inside the 2.344 mm/s floor; meanwhile the achieved period rises from 48.800 to 87.200 ms and the rate falls from 20.492 to 11.468 Hz, so a fixed 2 s physical block holds 41 profiles at E64 against 23 at E128, and the Nyquist frequency halves from 10.246 to 5.734 Hz
- **interpretation:** no depth-averaged improvement of E128 over E64 is detected - the observed difference is inside the between-run floor - while the bandwidth cost is a factor of 1.79 in period and a halving of Nyquist. The information rationale is therefore cost, not effect: within this pair the shorter period is E64's, and this row does not move the axis - **E20 remains the reference and default condition** (answer 1), so no measured quantity prefers 128 over 64 and none prefers either upper level over the reference the ladder is read against. **`replace` here means do not spend further acquisition effort on emissions 128 in this design** - it is not a claim that emissions 64 is scientifically proven superior, and a future measurement that needs the extra profiles, such as a slower flow, a noisier one or a longer coherent window, could reopen it.
- **automation needed:** none: both levels are already writable
- **would be overturned by:** a replicated E64-to-E128 difference outside the between-run floor, or a measurement that needs the extra profiles more than it needs the bandwidth (nothing in this pass shows such a quantity)
- **what this row said before:** `replace` / not detected at this design's floors, drafted when the axis's own replacement level was emissions 64: this row's cost rationale then read as `E128 is replaced by E64`, and the level the axis moves to is no longer E64 - the campaign above measured E64 against E20 and detected no improvement, so E20 is retained as the reference and default condition. The row's scope is unchanged: it still reads the E64-to-E128 step and that step's bandwidth cost, and `replace` still means only that emissions 128 is not worth acquiring in this design.

### is there any reason from this pass to reopen the pulse repetition frequency?

- **verdict:** `keep` - stage-2 decision
- **decision class:** `measured and resolved`
- **evidence:** the pass's own achieved grid: every recording's period is the emissions block at the fixed 600 us PRF plus a fixed intercept, measured at all four emissions levels
- **floor:** not applicable: this row tests an identity, not an effect against a floor
- **observed effect:** the four measured periods, 0.015 / 0.022 / 0.049 / 0.087 s, are predicted to within 0.000 ms by emissions x 600 us + 10.400 ms, and the intercept decomposes as 9.600 ms of internal emission (16 PRF terms) plus 0.800 ms of transfer term
- **interpretation:** the fixed 600 us PRF explains every achieved period in the pass, at every emissions level, with one constant intercept and no residual that varies with the level. Nothing measured here departs from it, so nothing here argues for reopening it.
- **automation needed:** none
- **would be overturned by:** an achieved period that departs from the law at some level, or a measurement that needs a bandwidth the current PRF cannot deliver while keeping the emissions levels where they are

### is a dense second acquisition across the sparse matrix justified by this pass?

- **verdict:** `defer` - stage-2 decision
- **decision class:** `not resolvable with this design`
- **evidence:** WP1 through WP4 together: the four floors this pass measured, and what each unresolved question is limited by.
- **floor:** not a single floor: the binding constraints are the burst jobs' own anchor movement (8.194 and 1.996 mm/s) and the between-run floor (2.344 mm/s depth-averaged, 14.201 mm/s depth-resolved)
- **observed effect:** the largest unresolved effect this pass can see is the scalar pitch x burst interaction at 1.083 mm/s, which is inside the burst jobs' own anchor movement and is not settled by more points of the same design. The one *distinction* additional run-level realizations could settle was E20 against E64, whose span (-2.304 to +0.040 mm/s) then straddled the 2.344 mm/s floor - and that distinction has since been measured: the targeted campaign returned four paired contrasts whose largest is 7.2256 mm/s, all inside the 9.4044 mm/s floor that campaign measured for itself, with no consistent direction
- **interpretation:** a dense second pass would reproduce these floors: the pitch x burst interaction is limited by movement *inside* the burst jobs, and adding more pitch or burst conditions of the same design does not shrink that. The E20/E64 realization dependence was the one limitation bounded by the number of runs rather than by the rig, and it was addressed by the bounded paired block rather than by density: **that measurement has been performed and did not detect a stable emissions-64 benefit above its contemporaneous floor**, so it is no longer an open distinction and nothing here remains worth measuring again by density or by a further emission level.
- **automation needed:** none. The bounded block this row pointed to has been acquired and analysed: it was eight run-level jobs at the reference window's own settings, its one varying run-wide setting (emissions per profile) was set by the operator and verified by the compile's read-back, and no acquisition-layer change was needed to run it. Nothing about that block is future work.
- **would be overturned by:** a diagnostic that shows the within-job anchor movement is an artefact of the schedule rather than the rig, or a named question that density could answer and the targeted set could not - the E20/E64 realization dependence this row once pointed to is no longer one of those, having been measured and reported not detected
- **what this row said before:** this row said that the only unresolved distinction additional run-level realizations could settle was E20 against E64, that it was worth measuring again as a bounded paired block inside one campaign, and that the eight-job block was the next acquisition. That block has since been run (see the campaign record above) and its result is not detected at that campaign's floors.

### does the higher-sensitivity condition change the measured velocity distribution (the SNR / saturation question)?

- **verdict:** `requires diagnostic` - outside the stage-2 decision: its own capability project
- **decision class:** `not measured`
- **evidence:** not measured, and not measurable here: every committed recording carries one axial-velocity channel in mm/s, with no echo or energy profile, so no file in this pass can distinguish SNR or saturation from the flow.
- **floor:** none: there is no measurement to screen
- **observed effect:** no committed recording varies the sensitivity axis
- **interpretation:** this is a capability question rather than a Stage-2 acquisition: answering it needs the recording surface to carry a second (echo/energy) channel first, and until that exists no acquisition of this condition produces evidence.
- **automation needed:** two gaps, and only one of them is a writer: the dialog carries sensitivity as a combo row but the acquisition bindings do not name it, and the stored file has no echo/energy channel at all
- **would be overturned by:** the manual's own criterion: if changing sensitivity changes the measured velocity distribution, Doppler energy is insufficient - which reopens transmitted power, TGC, seeding and coupling rather than the sensitivity value

## What was recommended, what it returned, and what is refused

**this block was this pass's one recommendation, and it has been acquired.** It existed because the pass's floors were adequate for everything it measured except one distinction, and that one was limited by how many runs a level has rather than by the rig: the E64-to-E20 difference spanned -2.304 to +0.040 mm/s depending on which of the four E20 runs it was compared with, straddling the 2.344 mm/s between-run floor, and acquiring emissions 64 alone would not have settled it - those runs would have been made in a later campaign and compared against emissions-20 runs from this one, so campaign-level drift would have entered the emissions comparison. Sampling both levels alternately inside one campaign was the answer, and the block below is what was designed and run. Its result is unresolved overlap / not detected: no emissions-64 improvement over emissions 20 was separable from the variation that campaign measured for itself. **No further acquisition is recommended from this workstream.**

**The pairs, and why the order alternates:** The four pairs are **acquired in the order below**, and that assignment is part of the design rather than an implementation detail. Alternating the levels keeps slow drift shared, but always acquiring emissions 20 before emissions 64 would leave a short-timescale order effect - handling time, thermal or mixer evolution, settling after an emissions change, or a directional drift across adjacent jobs - confounded with the emissions contrast. The order is therefore counterbalanced: the pair is acquired E20-then-E64 in two pairs and E64-then-E20 in the other two, so each level is first twice and second twice, and an order effect of that kind shows up as pair-to-pair scatter rather than as a difference between the levels. It is one campaign block, not two interleaved campaigns: one run-plan, one manifest, one ordered sequence and one failure/resume state. The analysis publishes the four paired contrasts **individually**, each oriented as E64 minus E20 whatever order its pair was acquired in, and records that pair's acquisition orientation beside it - the orientation is retained, not discarded. The run-wide emissions value is set by the operator before each job, exactly as every job's run-wide values were set in this pass, and the compile's own fact table verifies the setting from the read-back, so no acquisition-layer change is needed.

**The set, in acquisition order:** `E20-A` -> `E64-A` -> `E64-B` -> `E20-B` -> `E20-C` -> `E64-C` -> `E64-D` -> `E20-D` - 8 run-level jobs, reported here as a set rather than as a schedule (the acquisition layer owns ordering, and nothing in it changes).

| condition | what it buys |
|---|---|
| emissions 20 at the reference spatial window: 1.850 mm, 50 gates, burst 10, PRF 600 us, and every other setting identical to this pass's reference condition - power, sensitivity, TGC, first gate, sound speed, duration - as four run-level jobs, one per block letter | four emissions-64 and four emissions-20 run-level observations acquired inside one campaign, which is what lets the E64-to-E20 step be compared without campaign drift entering it; a between-run floor measured in that same campaign, so the comparison is screened against contemporaneous run-to-run variation instead of against a floor this pass measured in an earlier session; four adjacent paired E64-to-E20 contrasts published individually, one per pair, each oriented E64 minus E20 with its pair's acquisition orientation recorded beside it, which makes the distinction a paired comparison rather than a difference of two group means and keeps every contrast checkable against the two jobs that produced it; each level's own run-to-run spread on the same footing, so a later emissions decision has two replicated levels rather than one |
| emissions 64 at those same fixed settings - 1.850 mm, 50 gates, burst 10, PRF 600 us, and the same power, sensitivity, TGC, first gate, sound speed and duration - differing from the emissions-20 jobs in emissions per profile only, as four run-level jobs alternating with them | four emissions-64 and four emissions-20 run-level observations acquired inside one campaign, which is what lets the E64-to-E20 step be compared without campaign drift entering it; a between-run floor measured in that same campaign, so the comparison is screened against contemporaneous run-to-run variation instead of against a floor this pass measured in an earlier session; four adjacent paired E64-to-E20 contrasts published individually, one per pair, each oriented E64 minus E20 with its pair's acquisition orientation recorded beside it, which makes the distinction a paired comparison rather than a difference of two group means and keeps every contrast checkable against the two jobs that produced it; each level's own run-to-run spread on the same footing, so a later emissions decision has two replicated levels rather than one |

**Acceptance criterion, stated in advance:** the new campaign reports, separately: the four emissions-20 observations and the four emissions-64 observations; each level's own run-to-run spread; the four adjacent paired E64-to-E20 contrasts individually and oriented E64 minus E20, with each pair's acquisition orientation retained; the full cross-run range as context; and the depth-resolved differences against the between-run floor measured inside that campaign. The decision is then stated in one of two ways and no other. **Resolved difference:** the E64-to-E20 contrasts are consistently larger than the contemporaneous between-run variation and have a consistent direction. **Unresolved overlap:** the separation remains comparable to or smaller than the contemporaneous run-to-run variation, in which case that overlap is the answer and no further recording is indicated.

**This campaign has since been acquired, and this is what it returned:**

The recommendation above is no longer pending. It was run as `stage2-e20-e64` (8 run-level jobs), and its bytes are frozen at `data/stage2-e20-e64` with the report at `reports/stage2-e20-e64/` (generator `6253a1d`). Its four paired contrasts are A +7.2256 mm/s, B -1.5733 mm/s, C +0.3448 mm/s, D +1.3418 mm/s, every one inside the 9.4044 mm/s floor it measured for itself and with no consistent direction; depth-resolved, no gate has even one pair above its per-gate floor. The E64-vs-E20 row above is updated to that outcome, and the acquisition itself is a separate reviewed slice.

**Refused, on this pass's own evidence:**

- an emissions-64-only acquisition screened against this pass's emissions-20 runs: the later campaign's drift would enter the comparison, which the paired design exists to prevent
- screening the new block against this pass's 4.235 mm/s floor: the Stage-2 comparison uses the floor measured in the campaign that produced it, with this pass's floor kept as context
- a dense second pass over the sparse matrix: the pitch x burst interaction is limited by movement inside the burst jobs, which the same design reproduces
- any new pitch or burst condition: nothing this pass measured suggests a third level on either axis
- the sensitivity condition (D1): the recording surface carries no echo/energy channel, so it is a capability project rather than a Stage-2 acquisition
- reopening the pulse repetition frequency: the pass's own achieved grid matches the fixed 600 us law at every emissions level

## What is checked before this decision is published

| check | holds |
|---|---|
| `a_block_that_has_run_is_not_still_recommended` | yes |
| `both_levels_are_sampled_in_one_campaign` | yes |
| `d1_is_outside_the_stage_2_scope` | yes |
| `every_frozen_slice_is_cited_and_held_its_gate` | yes |
| `every_question_carries_its_class` | yes |
| `every_question_cites_a_resolvable_artefact` | yes |
| `every_verdict_is_one_of_the_plans_four` | yes |
| `no_dense_sweep_is_kept` | yes |
| `not_detected_is_not_read_as_absent` | yes |
| `the_answers_carry_the_post_campaign_state` | yes |
| `the_campaign_row_reads_the_campaigns_own_floor` | yes |
| `the_dense_row_records_the_measurement_it_pointed_to` | yes |
| `the_e64_row_records_the_state_it_moved_from` | yes |
| `the_engine_revision_is_recorded` | yes |
| `the_fifth_answer_quotes_the_campaigns_own_sequence` | yes |
| `the_first_answer_names_the_unresolved_axis_as_unresolved` | yes |
| `the_five_gate_questions_are_answered_in_order` | yes |
| `the_floors_are_read_not_declared` | yes |
| `the_numbers_are_the_slices_own` | yes |
| `the_old_future_state_is_gone` | yes |
| `the_pair_order_is_counterbalanced_and_part_of_the_design` | yes |
| `the_seven_questions_are_the_reviews_own` | yes |
| `the_stage2_campaign_is_recorded_as_run` | yes |
| `the_stage2_comparison_carries_its_own_floor` | yes |
| `the_two_endpoints_are_kept_apart` | yes |

## Artefacts

| file | what it is |
|---|---|
| [`decision-table.csv`](decision-table.csv) | the decision table, one row per question |
| [`decision-table.json`](decision-table.json) | the slices with their digests and revisions, the floors, the rows, the five answers, the campaign and the gate |
| this document | the same decision for a reader |

## What is deliberately not here

- **No new measurement.** Nothing in this document is computed from a recording; a number that is not in a frozen slice's artefact is not in the table.
- **No statistical certainty.** The floors are observed differences over a handful of recordings, so a verdict is a decision about the next acquisition and not a test outcome.
- **No second capability project.** D1 is listed and marked outside the Stage-2 scope: the surface cannot answer it yet.
- **No broad sweep.** A dense second pass is refused here on the pass's own evidence rather than deferred for lack of time.
