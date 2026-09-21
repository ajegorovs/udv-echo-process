# WP5 - the Stage-2 decision

The five measurement slices are frozen; this document decides nothing about what was measured, and everything about what may be concluded for the next acquisition. Every number below is read from a slice's own artefact (the revision and digest of each are in `decision-table.json`), and a slice that is missing, failed its own gate, or disagrees with another about a floor stops this document from being written at all.

## The floors this decision stands on

| floor | value [mm/s] | endpoint | from | applies to |
|---|---|---|---|---|
| between-run reference, depth-resolved | 14.603 | depth-resolved: one per-depth difference array, or its extreme | WP2 | every per-gate comparison in WP3 and WP4 |
| between-run reference, depth-averaged | 4.235 | depth-averaged: one unweighted mean over the supported gates | WP2 | every scalar comparison, and the only endpoint like for like with WP1 |
| burst-4 job's own anchor spread | 9.646 | block-local anchor spread inside one job | WP1 | the conservative guard on the burst-4 job's contrasts |
| burst-18 job's own anchor spread | 11.980 | block-local anchor spread inside one job | WP1 | the conservative guard on the burst-18 job's contrasts |
| emissions-8 / 64 / 128 jobs' own anchor spreads | 2.829 | block-local anchor spread inside one job | WP1 | the E8, E64 and E128 rows' within-job bracketing |

## The five questions the plan's gate asks, in its order

**1. which axes can be collapsed or fixed?**

the emissions axis partly: E128 is replaced by E64 on cost, since no measured quantity prefers it and its period is a factor of 1.79 longer; E8 and E20 are kept, E8 having shown no stability loss and E20 being the pass's own reference. The pitch axis is not collapsed: its interaction is unresolved at this design's floors, which is a statement about separability rather than about the axis being irrelevant. The burst axis stays at the two levels the historical table already fixed (4 and 18 cycles at the reference pitch), and the new information here is that the burst jobs' own anchors move by 10-12 mm/s, which is what makes finer burst contrasts unresolvable rather than unnecessary.

**2. which interactions matter?**

one is estimable in this pass and it is the one the design crossed: pitch x burst. Its scalar magnitude is larger than the between-run reference variation and smaller than the movement of the anchors inside its own two jobs, so it matters as a *shape* (locally up to 7.615 mm/s and changing sign) and not as a statement of magnitude. No other interaction is estimable: the emissions ladder is one axis at one set of conditions, and the pass varies nothing else in a crossed way.

**3. which levels are redundant?**

E128 is not a level worth acquiring further: no depth-averaged improvement over E64 is detected, and a fixed 2 s block holds 23 profiles against 41 at E64. E8 and E20 are not redundant - E8 carries the ladder's bandwidth advantage with no measured stability cost, and E20 is the only condition observed in more than one run, so it is what makes any between-run statement possible at all. The emissions levels' three block-local anchor sets are not redundant either: they are each job's own drift diagnostic and the reason every E-level comparison has a within-job context.

**4. is a denser second acquisition justified at all?**

not as a dense pass. The pitch x burst interaction is limited by the burst jobs' own anchor movement, which more points of the same design do not shrink; the emissions ladder's one unresolved distinction (E20 against E64) is limited by how many runs each level has, and the observed difference straddles the 4.235 mm/s floor depending on which E20 run is used. Only that second limitation is worth spending recordings on, and not by acquiring emissions 64 alone: runs made in a later campaign and screened against this pass's emissions-20 runs would be separated by a campaign as well as by an emission level, and the pass has measured that between-run variation is large enough for that to enter the comparison. It takes realizations of both levels inside one campaign.

**5. if it is, which small set of new conditions, and what does each buy?**

eight run-level jobs in one campaign, sampling the two levels alternately: E20-A, E64-A, E20-B, E64-B, E20-C, E64-C, E20-D, E64-D. Emissions per profile is the only setting that differs - 1.850 mm, 50 gates, burst 10, PRF 600 us, and the same power, sensitivity, TGC, first gate, sound speed and duration - and alternating the order means slow drift is sampled by both levels. They buy the one thing the ladder cannot supply: four emissions-64 and four emissions-20 observations made contemporaneously, a between-run floor measured inside that same campaign, and four adjacent paired contrasts. This pass's four emissions-20 runs and its existing emissions-64 recording stay as prior context; only the decisive comparison moves. Nothing else is recommended, and the acceptance criterion is stated in advance below.

## The decision table

The seven columns are the historical sweep's, so the two tables compare: the evidence, the floor the effect was screened against, the observed effect, the interpretation, the automation needed, the verdict and the measurement that would overturn it. `decision-table.csv` carries the same rows plus the machine fields (`key`, `decision_class`, `scope`, and both numeric effect columns).

### the pitch x burst interaction (0.617 against 2.960 mm, burst 4 against 18): may its magnitude be stated, and is a denser pitch sweep justified by this pass?

- **verdict:** `defer` - stage-2 decision
- **decision class:** `not resolvable with this design`
- **evidence:** WP3's crossed 2x2 on 31 common knots no finer than 2.960 mm, with each corner sampled at its nearest native gate; WP1's per-job anchor spreads as the within-job guard; WP2's two endpoints.
- **floor:** the scalar reads against WP2's depth-averaged endpoint, 4.235 mm/s, and the conservative guard is each burst job's own anchor spread, 9.646 mm/s (burst-4) and 11.980 mm/s (burst-18); the per-knot magnitudes read against the depth-resolved endpoint, 14.603 mm/s
- **observed effect:** the scalar interaction is -7.922 mm/s, i.e. 1.87x the depth-averaged floor, and it stays below both anchor guards (9.646 and 11.980 mm/s); depth-resolved it reaches -21.743 mm/s at 45.658 mm and +7.615 mm/s at 60.458 mm, with 9 of 31 knots above the depth-resolved floor, 14 above the burst-4 guard and 10 above burst-18's
- **interpretation:** an interaction-shaped difference is present and is *larger* than the campaign's own between-run reference variation, but it is *smaller* than the movement of the anchors inside the two jobs it came from: the pass cannot separate its scalar magnitude from that movement, so this is a limitation of separability and NOT evidence that the interaction is absent. Locally the effect is real-shaped and changes sign across the profile, but every local extreme sits inside a job whose own anchors move by 10-12 mm/s.
- **automation needed:** none for the pitch axis as measured: the corners write only resolution and gates, and no new dialog value is needed. Shrinking the guard would need something other than an acquisition change - the anchors' movement inside a burst job is itself unexplained.
- **would be overturned by:** burst-job realizations whose own anchor spread is materially smaller than 10-12 mm/s (which is a diagnostic question about what moves inside those jobs, not a denser sweep), or a replicated interaction whose scalar magnitude exceeds the anchor guards at every realization

### does emissions 8 lose useful estimator stability against emissions 20?

- **verdict:** `keep` - stage-2 decision
- **decision class:** `not detected at this design's floors`
- **evidence:** WP4's ladder: E8 is one scientific recording inside its job's three block-local anchors, E20 is the four common-reference runs; both are reduced on the same 12 s window and the same 49-gate support.
- **floor:** WP2's depth-averaged endpoint, 4.235 mm/s, for the E8-to-E20 step, with E8's own anchor spread, 1.521 mm/s, as its within-job context
- **observed effect:** the E8-to-E20 depth-averaged differences span -1.827 to +2.408 mm/s across the four E20 runs, a spread of 4.235 mm/s, which is the E20 level's own run-to-run spread; E8's own anchors move by 1.521 mm/s and its profile rate is the ladder's highest at 65.789 Hz
- **interpretation:** no stability loss is detected at the floors this pass has: every E8-to-E20 difference lies inside the E20 runs' own spread, E8's own anchors are the quietest of the three single-recording levels, and E8 carries the ladder's strongest temporal-bandwidth advantage. Not detected is not the same as absent, but nothing measured here points the other way.
- **automation needed:** none: E8 is already writable and was written in this pass
- **would be overturned by:** an E8-to-E20 difference outside the four-run spread at replicated realizations, or an E8 residual against its own anchors exceeding that job's own anchor spread

### does emissions 64 improve the velocity estimate over emissions 20?

- **verdict:** `defer` - stage-2 decision
- **decision class:** `not resolvable with this design`
- **evidence:** WP4's ladder: E64 is one scientific recording inside its job's three block-local anchors; E20 is the four common-reference runs, so the step is four run-resolved differences and no averaged E20 profile exists to take it from.
- **floor:** WP2's depth-averaged endpoint, 4.235 mm/s, as the between-run reference; E64's own anchor spread, 2.829 mm/s, as its within-job context
- **observed effect:** the E64-to-E20 depth-averaged differences span -6.405 to -2.170 mm/s depending on which E20 run E64 is compared with, with a per-gate extreme of 17.504 mm/s at 19.388 mm; the span straddles the 4.235 mm/s floor
- **interpretation:** the comparison changes classification with the reference realization: against one of the four E20 runs the difference exceeds the between-run floor and against others it does not. E64 is therefore suggestive against E20 and unresolved by this pass - it is neither shown better nor shown the same, and one realization per level is what makes that undecidable.
- **automation needed:** none: E64 is already writable and was written in this pass
- **would be overturned by:** run-level realizations of *both* levels inside one campaign - the paired alternating set recommended below - so that the step becomes a contemporaneous four-against-four comparison carrying its own measured between-run floor, rather than new emissions-64 runs screened against an older reference

### does emissions 128 improve the estimate enough over emissions 64 to pay its cost?

- **verdict:** `replace` - stage-2 decision
- **decision class:** `not detected at this design's floors`
- **evidence:** WP4's ladder and its temporal view measured from the stored per-profile timestamps, at the same 12 s window and support for the velocity side.
- **floor:** WP2's depth-averaged endpoint, 4.235 mm/s; E128's own anchor spread, 3.304 mm/s, as its within-job context
- **observed effect:** the E64-to-E128 depth-averaged difference is -2.365 mm/s, inside the 4.235 mm/s floor; meanwhile the achieved period rises from 48.800 to 87.200 ms and the rate falls from 20.492 to 11.468 Hz, so a fixed 2 s physical block holds 41 profiles at E64 against 23 at E128, and the Nyquist frequency halves from 10.246 to 5.734 Hz
- **interpretation:** no depth-averaged improvement of E128 over E64 is detected - the observed difference is inside the between-run floor - while the bandwidth cost is a factor of 1.79 in period and a halving of Nyquist. The information rationale is therefore cost, not effect: no measured quantity prefers 128 over 64, so the shorter period is taken. **`replace` here means do not spend further acquisition effort on emissions 128 in this design** - it is not a claim that emissions 64 is scientifically proven superior, and a future measurement that needs the extra profiles, such as a slower flow, a noisier one or a longer coherent window, could reopen it.
- **automation needed:** none: both levels are already writable
- **would be overturned by:** a replicated E64-to-E128 difference outside the between-run floor, or a measurement that needs the extra profiles more than it needs the bandwidth (nothing in this pass shows such a quantity)

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
- **floor:** not a single floor: the binding constraints are the burst jobs' own anchor movement (9.646 and 11.980 mm/s) and the between-run floor (4.235 mm/s depth-averaged, 14.603 mm/s depth-resolved)
- **observed effect:** the largest unresolved effect this pass can see is the scalar pitch x burst interaction at 7.922 mm/s, which is inside the burst jobs' own anchor movement; the only unresolved *distinction* that additional run-level realizations can settle is E20 against E64, whose span (-6.405 to -2.170 mm/s) straddles the 4.235 mm/s floor
- **interpretation:** a dense second pass would reproduce these floors: the pitch x burst interaction is limited by movement *inside* the burst jobs, and adding more pitch or burst conditions of the same design does not shrink that. Only the E20/E64 realization dependence is bounded by the number of runs rather than by the rig, and only it is worth measuring again - as a bounded paired block inside one campaign, not a matrix.
- **automation needed:** none, and for a different reason than the pointwise surface's: the recommended block changes neither resolution nor gates - it is eight run-level jobs at the reference window's own settings - and its one varying run-wide setting is emissions per profile, which the operator sets before each job and the compile's read-back verifies. No acquisition-layer change is needed to run it.
- **would be overturned by:** a diagnostic that shows the within-job anchor movement is an artefact of the schedule rather than the rig, or a named question that the recommended targeted set does not answer

### does the higher-sensitivity condition change the measured velocity distribution (the SNR / saturation question)?

- **verdict:** `requires diagnostic` - outside the stage-2 decision: its own capability project
- **decision class:** `not measured`
- **evidence:** not measured, and not measurable here: every committed recording carries one axial-velocity channel in mm/s, with no echo or energy profile, so no file in this pass can distinguish SNR or saturation from the flow.
- **floor:** none: there is no measurement to screen
- **observed effect:** no committed recording varies the sensitivity axis
- **interpretation:** this is a capability question rather than a Stage-2 acquisition: answering it needs the recording surface to carry a second (echo/energy) channel first, and until that exists no acquisition of this condition produces evidence.
- **automation needed:** two gaps, and only one of them is a writer: the dialog carries sensitivity as a combo row but the acquisition bindings do not name it, and the stored file has no echo/energy channel at all
- **would be overturned by:** the manual's own criterion: if changing sensitivity changes the measured velocity distribution, Doppler energy is insufficient - which reopens transmitted power, TGC, seeding and coupling rather than the sensitivity value

## What is recommended next, and what is refused

the pass's floors are adequate for everything it measured except one distinction, and that one is limited by how many runs a level has rather than by the rig: the E64-to-E20 difference spans -6.405 to -2.170 mm/s depending on which of the four E20 runs it is compared with, so it straddles the 4.235 mm/s between-run floor. Acquiring emissions 64 alone would not settle it: those runs would be made in a later campaign and compared against emissions-20 runs from this one, and the between-run variation this pass measured is large enough that campaign-level drift would enter the emissions comparison. The two levels therefore have to be sampled alternately inside one campaign, so that slow drift is shared by both levels and the decisive comparison carries a floor measured in its own campaign. The existing four emissions-20 runs and the existing emissions-64 recording stay as prior context; only the decisive comparison moves to the new block.

**The pairs, and why the order alternates:** The four pairs are **acquired in the order below**, and that assignment is part of the design rather than an implementation detail. Alternating the levels keeps slow drift shared, but always acquiring emissions 20 before emissions 64 would leave a short-timescale order effect - handling time, thermal or mixer evolution, settling after an emissions change, or a directional drift across adjacent jobs - confounded with the emissions contrast. The order is therefore counterbalanced: the pair is acquired E20-then-E64 in two pairs and E64-then-E20 in the other two, so each level is first twice and second twice, and an order effect of that kind shows up as pair-to-pair scatter rather than as a difference between the levels. It is one campaign block, not two interleaved campaigns: one run-plan, one manifest, one ordered sequence and one failure/resume state. The analysis publishes the four paired contrasts **individually**, each oriented as E64 minus E20 whatever order its pair was acquired in, and records that pair's acquisition orientation beside it - the orientation is retained, not discarded. The run-wide emissions value is set by the operator before each job, exactly as every job's run-wide values were set in this pass, and the compile's own fact table verifies the setting from the read-back, so no acquisition-layer change is needed.

**The set, in acquisition order:** `E20-A` -> `E64-A` -> `E64-B` -> `E20-B` -> `E20-C` -> `E64-C` -> `E64-D` -> `E20-D` - 8 run-level jobs, reported here as a set rather than as a schedule (the acquisition layer owns ordering, and nothing in it changes).

| condition | what it buys |
|---|---|
| emissions 20 at the reference spatial window: 1.850 mm, 50 gates, burst 10, PRF 600 us, and every other setting identical to this pass's reference condition - power, sensitivity, TGC, first gate, sound speed, duration - as four run-level jobs, one per block letter | four emissions-64 and four emissions-20 run-level observations acquired inside one campaign, which is what lets the E64-to-E20 step be compared without campaign drift entering it; a between-run floor measured in that same campaign, so the comparison is screened against contemporaneous run-to-run variation instead of against a floor this pass measured in an earlier session; four adjacent paired E64-to-E20 contrasts published individually, one per pair, each oriented E64 minus E20 with its pair's acquisition orientation recorded beside it, which makes the distinction a paired comparison rather than a difference of two group means and keeps every contrast checkable against the two jobs that produced it; each level's own run-to-run spread on the same footing, so a later emissions decision has two replicated levels rather than one |
| emissions 64 at those same fixed settings - 1.850 mm, 50 gates, burst 10, PRF 600 us, and the same power, sensitivity, TGC, first gate, sound speed and duration - differing from the emissions-20 jobs in emissions per profile only, as four run-level jobs alternating with them | four emissions-64 and four emissions-20 run-level observations acquired inside one campaign, which is what lets the E64-to-E20 step be compared without campaign drift entering it; a between-run floor measured in that same campaign, so the comparison is screened against contemporaneous run-to-run variation instead of against a floor this pass measured in an earlier session; four adjacent paired E64-to-E20 contrasts published individually, one per pair, each oriented E64 minus E20 with its pair's acquisition orientation recorded beside it, which makes the distinction a paired comparison rather than a difference of two group means and keeps every contrast checkable against the two jobs that produced it; each level's own run-to-run spread on the same footing, so a later emissions decision has two replicated levels rather than one |

**Acceptance criterion, stated in advance:** the new campaign reports, separately: the four emissions-20 observations and the four emissions-64 observations; each level's own run-to-run spread; the four adjacent paired E64-to-E20 contrasts individually and oriented E64 minus E20, with each pair's acquisition orientation retained; the full cross-run range as context; and the depth-resolved differences against the between-run floor measured inside that campaign. The decision is then stated in one of two ways and no other. **Resolved difference:** the E64-to-E20 contrasts are consistently larger than the contemporaneous between-run variation and have a consistent direction. **Unresolved overlap:** the separation remains comparable to or smaller than the contemporaneous run-to-run variation, in which case that overlap is the answer and no further recording is indicated.

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
| `both_levels_are_sampled_in_one_campaign` | yes |
| `d1_is_outside_the_stage_2_scope` | yes |
| `every_frozen_slice_is_cited_and_held_its_gate` | yes |
| `every_question_carries_its_class` | yes |
| `every_question_cites_a_resolvable_artefact` | yes |
| `every_verdict_is_one_of_the_plans_four` | yes |
| `no_dense_sweep_is_kept` | yes |
| `not_detected_is_not_read_as_absent` | yes |
| `the_engine_revision_is_recorded` | yes |
| `the_first_answer_names_the_unresolved_axis_as_unresolved` | yes |
| `the_five_gate_questions_are_answered_in_order` | yes |
| `the_floors_are_read_not_declared` | yes |
| `the_numbers_are_the_slices_own` | yes |
| `the_pair_order_is_counterbalanced_and_part_of_the_design` | yes |
| `the_seven_questions_are_the_reviews_own` | yes |
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
