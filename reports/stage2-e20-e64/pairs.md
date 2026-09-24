# The Stage-2 paired analysis — four E64 - E20 contrasts in one campaign

The eight run-level jobs of `stage2-e20-e64` (plan fingerprint `16a1f060053a`), acquired in the frozen **counterbalanced** order:

```text
E20-A   E64-A      E64-B   E20-B      E20-C   E64-C      E64-D   E20-D
```

One **campaign block**, not two interleaved campaigns: one run plan, one manifest, one ordered sequence. Emissions per profile is the only run-wide setting that differs, and the frame is otherwise identical across all eight runs in 21 decoded settings.

The two shared views are the pass's own: the designed exposure **12 s = 100 nominal 500-RPM revolutions**, cut by each recording's stored timestamps, and the common physical support 10.138 - 100.788 mm — which covers **all 50 gates** of the declared 1.850 mm x 50-gate reference window, so every contrast below is published on the full window the campaign was planned around.

## The four paired contrasts

Each pair is read **E64 - E20**, whatever order it was acquired in. The orientation is **recorded beside** each contrast rather than folded away, and the raw acquisition-order difference is published next to it: on a `64 -> 20` pair the two differ by sign, and a counterbalance read without the orientation would be a sign error on half the contrasts.

| pair | acquired | lead | follow | order difference | **oriented (E64 - E20)** | screening floor | above it |
|---|---|---|---|---:|---:|---:|---|
| A | 20 -> 64 | e20-a | e64-a | +7.2256 | **+7.2256** | 9.4044 | no |
| B | 64 -> 20 | e64-b | e20-b | +1.5733 | **-1.5733** | 9.4044 | no |
| C | 20 -> 64 | e20-c | e64-c | +0.3448 | **+0.3448** | 9.4044 | no |
| D | 64 -> 20 | e64-d | e20-d | -1.3418 | **+1.3418** | 9.4044 | no |

Depth-resolved, the strongest per-gate separation of each pair is A 15.7036 mm/s at 76.738 mm, B 10.9701 mm/s at 85.988 mm, C 17.4012 mm/s at 71.188 mm, D 17.7326 mm/s at 13.838 mm — screened against the depth-resolved floor 28.5481 mm/s at 15.688 mm, never against the depth-averaged one.

| pair | depth-averaged (E64 - E20) | rms | max abs | at depth |
|---|---:|---:|---:|---:|
| A | +7.2256 | 8.7437 | 15.7036 | 76.738 mm |
| B | -1.5733 | 4.7582 | 10.9701 | 85.988 mm |
| C | +0.3448 | 5.3456 | 17.4012 | 71.188 mm |
| D | +1.3418 | 7.5263 | 17.7326 | 13.838 mm |

## The eight runs, individually

The four emissions-20 observations and the four emissions-64 observations are reported separately, each run as its own measurement — nothing is averaged into a per-level reference, because a synthetic reference would hide exactly the run-to-run spread the screen is built from.

| step | job | pair | role | level | emissions | window mean | recording |
|---:|---|---|---|---|---:|---:|---|
| 1 | e20-a | A | lead | E20 | 20 | +22.6053 mm/s | `stage2-e20-a-ref-20260921T181717.BDD` |
| 2 | e64-a | A | follow | E64 | 64 | +29.8310 mm/s | `stage2-e64-a-ref-20260921T181901.BDD` |
| 3 | e64-b | B | lead | E64 | 64 | +30.4364 mm/s | `stage2-e64-b-ref-20260921T182211.BDD` |
| 4 | e20-b | B | follow | E20 | 20 | +32.0097 mm/s | `stage2-e20-b-ref-20260921T182425.BDD` |
| 5 | e20-c | C | lead | E20 | 20 | +30.3335 mm/s | `stage2-e20-c-ref-20260921T182504.BDD` |
| 6 | e64-c | C | follow | E64 | 64 | +30.6783 mm/s | `stage2-e64-c-ref-20260921T182715.BDD` |
| 7 | e64-d | D | lead | E64 | 64 | +31.1759 mm/s | `stage2-e64-d-ref-20260921T182752.BDD` |
| 8 | e20-d | D | follow | E20 | 20 | +29.8341 mm/s | `stage2-e20-d-ref-20260921T183037.BDD` |

- **E20** (emissions 20) — 4 runs, window means +22.6053, +32.0097, +30.3335, +29.8341 mm/s, spread 9.4044 mm/s
- **E64** (emissions 64) — 4 runs, window means +29.8310, +30.4364, +30.6783, +31.1759 mm/s, spread 1.3449 mm/s


## The contemporaneous variation

The screen is **this campaign's own** run-to-run variation, measured on its eight runs by the endpoint WP2 used on the reference runs — the largest absolute window-mean difference over each level's six unique run pairs:

| level | runs | depth-averaged floor | at | depth-resolved floor | at depth |
|---|---|---:|---|---:|---:|
| E20 (emissions 20) | e20-a, e20-b, e20-c, e20-d | 9.4044 mm/s | e20-a-e20-b | 28.5481 mm/s | 15.688 mm |
| E64 (emissions 64) | e64-a, e64-b, e64-c, e64-d | 1.3449 mm/s | e64-a-e64-d | 10.8574 mm/s | 76.738 mm |

- screening floor (depth-averaged): **9.4044 mm/s** from E20; the larger of this campaign's two within-level depth-averaged floors (E20 9.4044 mm/s; E64 1.3449 mm/s), each measured on that level's own four runs of this campaign
- depth-resolved floor: **28.5481 mm/s** at 15.688 mm from E20; the larger of this campaign's two within-level depth-resolved floors (E20 28.5481 mm/s at 15.688 mm; E64 10.8574 mm/s at 76.738 mm), each measured on that level's own four runs of this campaign

**How the screen is composed matters as much as its value.** Both floors are maxima over the six unique run pairs of one level, so a single run that departs from the other three of its own level sets the screen for the whole campaign. That is the endpoint WP2 used on the reference runs and it is deliberately conservative: it is not an average of the campaign's noise, it is the campaign's worst same-level disagreement, and reading a contrast against it asks whether the emissions change is larger than the largest thing this campaign did on its own. The runs that set each floor are named in the table above, and the per-level spreads above that are the same numbers that build it.

The campaign's first run, `e20-a` (step 1, +22.6053 mm/s), is one of the two runs in E20 (e20-a-e20-b): the screen this campaign measures for itself includes whatever settled during the sitting, and the campaign's own first job is reported here rather than excluded or smoothed — pre-filtering a run out of the floor would be a choice made after seeing the contrasts.

## The outcome

**unresolved overlap** (depth-averaged) — not detected.

The four contrasts span 0.3448 to 7.2256 mm/s in absolute value (mean +1.8347, range 8.7989), with 0 of 4 above the 9.4044 mm/s floor and an inconsistent direction.

**unresolved overlap** (depth-resolved) — not detected.

**No supported gate satisfies both requirements at once.** A gate counts as resolved only when **all four** paired contrasts at that gate are above the depth-resolved floor *and* the four agree in sign — so a gate where one pair clears the floor, while another does not or disagrees in sign, is not resolved. Of the 50 supported gates, 0 have at least one pair above the floor and 0 have all four above it; neither count is the resolved share, which also requires the four signs to agree.

The criterion has exactly two allowed outcomes and this is one of them: a **resolved difference** or an **unresolved overlap**. Inside an overlap the vocabulary keeps two findings apart — **not detected** (the contrasts sit inside the campaign's own variation) and **not resolvable with this design** (they reach past the floor on some pairs but not consistently, or disagree in direction). Neither is a claim that no effect exists, and a depth-averaged verdict says nothing about a single gate.

## The earlier pass, as context only

quotations of the earlier pass (sparse-mixer-live-1)'s published between-run floors, carried as context only: that pass recorded its four emissions-20 references and its single emissions-64 observation in one campaign, so the two levels are not split across campaigns there, but its floors are the spread of those four emissions-20 runs alone — one side of a contrast, measured in another sitting — so they are not this campaign's contemporaneous variation and screen no contrast here. The confounding section 4b avoids is prospective: comparing further emissions-64 realizations against that pass's existing emissions-20 runs would cross campaigns, which is why both levels are sampled inside one campaign here. `sparse-mixer-live-1`'s published floors were **4.235 mm/s** depth-averaged and **14.603 mm/s** depth-resolved; they appear here so the two campaigns can be read side by side, and no number above was screened against them.

## What this does to the frozen decision table

Nothing in `reports/sparse-mixer-live-1/decision-table.md` is rewritten: its E64-vs-E20 row was published as `defer` / not resolvable **with that pass's design**, and this campaign was the measurement that row named as the one that would overturn it. Folding this outcome into that table is a one-row change to a pinned artefact, so it belongs in its own reviewed slice rather than in this one.

## Reproduce

```bash
uv run python -m udv_echo_process.cli sparse-stage2-pairs --analysis-commit ca8e40c
```

The table is `pairs.csv`, the definition document `pairs.json` (it carries the definitions, the gate checks and the table's SHA-256), and the figure `figures/pairs.png`.

## Every published number, defined

- `pair` — the design's pair letter (A-D); the campaign's four pairs are its four contrasts
- `acquisition_orientation` — the order the pair was actually acquired in, retained beside its contrast: '20 -> 64' or '64 -> 20'
- `oriented_mm_s` — the published paired contrast: this pair's emissions-64 depth-averaged window mean minus its emissions-20 one, oriented E64 - E20 whatever order the pair was acquired in
- `order_difference_mm_s` — the raw acquisition-order difference (the follow-up run minus the lead run). It equals oriented_mm_s on a '20 -> 64' pair and its negative on a '64 -> 20' one: a counterbalance read without the orientation is a sign error on half the pairs
- `max_abs_mm_s` — the largest absolute depth-resolved (per-gate) contrast of this pair
- `run.depth_averaged_mean_mm_s` — the run's unweighted mean of the per-gate window means over the supported gates: the same reduction the frozen table's supported cells use
- `screening_floor_mm_s` — the larger of the two within-level depth-averaged floors measured in this campaign's own eight runs, each the largest absolute difference over that level's six unique run pairs. It is this campaign's contemporaneous variation, not the earlier pass's floor
- `depth_resolved_floor_mm_s` — the larger of the two within-level depth-resolved floors measured in this campaign's own eight runs, taken per gate over the common support, at the depth stated
- `outcome` — one of exactly two: 'resolved difference' (the four contrasts consistently larger than the contemporaneous variation with a consistent direction) or 'unresolved overlap' (the separation comparable to or smaller than it)
- `overlap_kind` — 'not detected' (every contrast inside the campaign's own variation) or 'not resolvable with this design' (at least one contrast exceeds the floor, but the four do not consistently exceed it in one direction); null when the outcome is resolved. Direction disagreement alone does not change 'not detected' when all contrasts remain inside the floor
- `depth_resolved_reading` — the same two rules applied per gate against the depth-resolved floor, reduced to the strongest depth-resolved separation per pair; never mixed with the depth-averaged verdict

## The gate

- `eight_runs` — ok
- `four_pairs` — ok
- `one_run_of_each_level_per_pair` — ok
- `stored_word_is_the_declared_level` — ok
- `frame_identical` — ok
- `orientation_stated` — ok
- `orientation_matches_order` — ok
- `window_is_the_designed_one` — ok
- `one_native_grid` — ok
- `floors_are_this_campaigns` — ok
- `floor_is_the_larger_level_floor` — ok
- `outcome_is_one_of_two` — ok
- `overlap_kind_is_consistent` — ok
- `prior_floors_are_context_only` — ok

