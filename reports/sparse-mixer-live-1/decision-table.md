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

not as a dense pass. The pitch x burst interaction is limited by the burst jobs' own anchor movement, which more points of the same design do not shrink; the emissions ladder's one unresolved distinction (E20 against E64) is limited by how many runs each level has, and the observed difference straddles the 4.235 mm/s floor depending on which E20 run is used. Only that second limitation is worth spending recordings on, and it takes a few run-level realizations rather than a matrix.

**5. if it is, which small set of new conditions, and what does each buy?**

three additional run-level realizations of the E64 condition, in their own reference-style jobs and at the same decoded condition E64 already has. They buy the one thing the ladder cannot currently supply: a four-run E64 against the four-run E20, so that the E64-to-E20 step is a like-for-like run-level comparison whose realization dependence is visible instead of inferred. Nothing else is recommended, and the acceptance criterion is stated in advance below.

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
- **would be overturned by:** additional independent run-level realizations of the E64 condition, so that the step is a four-run against four-run comparison whose realization dependence can be seen rather than inferred (this is the targeted campaign below)

### does emissions 128 improve the estimate enough over emissions 64 to pay its cost?

- **verdict:** `replace` - stage-2 decision
- **decision class:** `not detected at this design's floors`
- **evidence:** WP4's ladder and its temporal view measured from the stored per-profile timestamps, at the same 12 s window and support for the velocity side.
- **floor:** WP2's depth-averaged endpoint, 4.235 mm/s; E128's own anchor spread, 3.304 mm/s, as its within-job context
- **observed effect:** the E64-to-E128 depth-averaged difference is -2.365 mm/s, inside the 4.235 mm/s floor; meanwhile the achieved period rises from 48.800 to 87.200 ms and the rate falls from 20.492 to 11.468 Hz, so a fixed 2 s physical block holds 41 profiles at E64 against 23 at E128, and the Nyquist frequency halves from 10.246 to 5.734 Hz
- **interpretation:** no depth-averaged improvement of E128 over E64 is detected - the observed difference is inside the between-run floor - while the bandwidth cost is a factor of 1.79 in period and a halving of Nyquist. The information rationale is therefore cost, not effect: no measured quantity prefers 128 over 64, so the shorter period is taken.
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
- **interpretation:** a dense second pass would reproduce these floors: the pitch x burst interaction is limited by movement *inside* the burst jobs, and adding more pitch or burst conditions of the same design does not shrink that. Only the E20/E64 realization dependence is bounded by the number of runs rather than by the rig, and only it is worth measuring again - and a handful of run-level realizations, not a matrix.
- **automation needed:** none for the recommended set: it writes only resolution and gates, the same as every other point
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

the pass's floors are adequate for everything it measured except one distinction, and that one is limited by how many runs a level has rather than by the rig: the E64-to-E20 difference spans -6.405 to -2.170 mm/s depending on which of the four E20 runs it is compared with, so it straddles the 4.235 mm/s between-run floor. More run-level realizations of E64 settle it; more conditions of the same design do not settle anything else.

| recommended | count | what each buys |
|---|---|---|
| emissions 64 at the reference spatial window (1.850 mm, 50 gates), burst 10, in its own reference-style jobs rather than inside a scientific job's block | 3 | a four-run E64 level to compare like for like with the four-run E20, which turns 'suggestive but realization-dependent' into either a difference that holds at every run or an overlap that can be stated as one; a measured between-run spread for E64 on the same footing as E20's, so a later emissions decision has two replicated levels rather than one |

**Acceptance criterion, stated in advance:** the distinction is decided when every run-level E64-to-E20 depth-averaged difference lies on one side of the 4.235 mm/s between-run floor; if the four E64 runs overlap the four E20 runs instead, that overlap is itself the answer and no further recording is indicated

**Refused, on this pass's own evidence:**

- a dense second pass over the sparse matrix: the pitch x burst interaction is limited by movement inside the burst jobs, which the same design reproduces
- any new pitch or burst condition: nothing this pass measured suggests a third level on either axis
- the sensitivity condition (D1): the recording surface carries no echo/energy channel, so it is a capability project rather than a Stage-2 acquisition
- reopening the pulse repetition frequency: the pass's own achieved grid matches the fixed 600 us law at every emissions level

## What is checked before this decision is published

| check | holds |
|---|---|
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
| `the_recommended_set_is_small_and_run_level` | yes |
| `the_seven_questions_are_the_reviews_own` | yes |
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
