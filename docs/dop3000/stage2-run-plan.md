# The Stage-2 pass, compiled — eight run-level jobs, four counterbalanced pairs

> **Status:** the executable form of the design the Stage-2 analysis froze as its one
> recommendation — `docs/dop3000/sparse-pass-analysis-plan.md` §4b, whose decision table is
> `reports/sparse-mixer-live-1/decision-table.md`. Both live on `analysis/sparse-pass-ingest` (PR
> #27) and land on `master` with it; this pass is compiled against them, not re-derived from them.
> The pass is
> [`examples/stage2-e20-e64/run-plan.json`](../../examples/stage2-e20-e64/run-plan.json), with one
> definition per job under `jobs/` and the operator's sheet committed beside it as
> [`operator-sheet.txt`](../../examples/stage2-e20-e64/operator-sheet.txt).
>
> This document records the pass as compiled. It does **not** re-open the science: the sequence, the
> levels and the pair structure are the frozen design's, and nothing here changes them. Compiling a
> run plan is a separate work package from the analysis that decided it — the analysis is closed and
> this is acquisition work.

## 1. The pass

One campaign, one store directory, eight run-level jobs, eight recordings of 12 s each. Every job
records **one** observation of the pass's reference window — 1.850 mm × 50 gates, burst 10,
PRF 600 µs, sound speed 1480 m/s, first gate 10 mm, channel 1 — and **emissions per profile is the
only setting that differs between any two jobs**.

| step | pair | role | job | emissions | acquisition orientation |
|---|---|---|---|---|---|
| 1 | A | lead | `e20-a` | 20 | 20 -> 64 |
| 2 | A | follow | `e64-a` | 64 | 20 -> 64 |
| 3 | B | lead | `e64-b` | 64 | 64 -> 20 |
| 4 | B | follow | `e20-b` | 20 | 64 -> 20 |
| 5 | C | lead | `e20-c` | 20 | 20 -> 64 |
| 6 | C | follow | `e64-c` | 64 | 20 -> 64 |
| 7 | D | lead | `e64-d` | 64 | 64 -> 20 |
| 8 | D | follow | `e20-d` | 20 | 64 -> 20 |

The campaign identity is its own: plan `stage2-e20-e64`, name root `stage2`, so a stored file is
`stage2-<job>-<label>-<stamp>` and names the pass, the job and the pair's letter. Neither earlier
sparse pass shares that name or that root.

## 2. Why the order is counterbalanced

Alternating the levels is what keeps slow campaign drift shared between them. Always recording
emissions 20 first would not be enough: a short-timescale order effect — handling time, thermal or
mixer evolution, settling after an emissions change, or a directional drift across adjacent jobs —
would then sit on the same side of every pair as the lower emissions level, and the pair's
difference could not tell the two apart. The pairs are therefore **E20-first in A and C, E64-first
in B and D**: each level leads twice and follows twice, and such an effect shows up as pair-to-pair
scatter rather than as a difference between the levels.

Pair and order assignment are part of the design, not an implementation detail, so the plan states
them (`pair`, `role` per job) and the layer refuses an order that disagrees with them.

## 3. The pair is the unit of analysis, and the record carries it

- Every pair is read **E64 minus E20**, in that order, whatever order its two jobs were acquired
  in. That is the plan's `analysis_orientation`, it is refused if it is anything else, and it is
  copied into the run record so the later analysis reads the rule rather than re-deriving it.
- The run record (`<plan>.run.json`, written before the first job) carries, per job, its `pair`,
  its `role` and its **acquisition orientation** (`20 -> 64`, `64 -> 20`). Pair membership and
  orientation are therefore reconstructed from the record itself — not from stored file names and
  not by inferring an order from a listing.
- The record therefore carries everything the acceptance criterion needs: the four paired
  contrasts can be published individually, one per pair, each oriented E64 − E20 with its pair's
  acquisition orientation beside it, and nothing has to be pooled into a group mean or reconstructed
  from a listing. Applying that criterion is the Stage-2 analysis' job, not this pass's.

## 4. What is checked before a recording, and after it

Statically, with no instrument (the compile):

- each job's definition file agrees with the plan on the job name, the name prefix, the duration,
  the window, the burst, the PRF **and the emissions level** — the pass's only variable is checked
  first;
- a job records the pass's own reference window, exactly one point, and carries no `ctrl-` label: a
  run-level job *is* the observation, not an anchor for one;
- every pair is two consecutive jobs, one lead and one follow, with the two jobs differing in
  emissions and in nothing else; every pair compares the same two levels; the four pairs are
  distinct letters; and the lower level leads exactly half of them;
- the pass raises `emissions_per_profile` **to a refusal** (`strict_facts`), and the model refuses a
  run-level pass that does not. Without it, a job recorded at the wrong level would be accepted as
  the one the plan asked for and the pair would compare two jobs that are not two levels;
- the block cap covers every job's nominal profile count — the compile's own requirement is
  **1000** profiles, set by the emissions-20 jobs' shorter period at 12 s (the emissions-64 jobs
  need 313) — and the pass declares 2500, the same cap as both earlier sparse passes, so the
  application's active preference has room: the planned jobs hold 531 profiles at 20 and 245 at 64,
  and the sheet asks the operator to confirm the active cap by hand.

At the machine, per job: the compile reads the run-wide values back from the application and
**refuses before the first recording** if any raised fact disagrees — the operator is told which
value to set, and the setting is read, not assumed. After acquisition the stored file is verified
against the plan as well: the raised fact is enforced from the **file's own word** (word 14 is
emissions per profile, word 8 is the burst length), so a job that recorded at another level is
invalidated rather than averaged in.

## 5. The resume rule, and why it matters here

A pass is run in the plan's own order. `next_job` names the first job that is not ok, and
`record_job` **refuses a job that is not next, by name**, with the step standing in front of it. Two
consequences the design depends on:

- **a half-finished pair is finished first.** If a session stops after `e20-a`, the next job is
  `e64-a` — the same pair's follow — and not another pair's lead;
- **a pair cannot be reversed by running its follow first.** That would be a different design, and
  it is refused rather than recorded, because the counterbalancing only means what it intends if the
  order that actually ran is the order that was planned.

Resume *within* a job is the campaign layer's own concern and is unaffected: a job that ended
`partial` keeps the campaign's point-level resume and is simply the next job again.

## 6. Using it

```bash
# what the pass is, and that it compiles — no instrument needed
uv run udv-acquire run-plan --plan examples/stage2-e20-e64/run-plan.json --check

# the operator's sheet, as committed: run-wide values, pairs, points, what to set by hand
uv run udv-acquire run-plan --plan examples/stage2-e20-e64/run-plan.json --sheet

# where the pass stands, from its own record
uv run udv-acquire run-plan --plan examples/stage2-e20-e64/run-plan.json --status

# the next job, once the application is open and the store directory is confirmed by hand.
# --next *records*, so it declares the process this pass was measured against; --check, --sheet and
# --status need no declaration.
uv run udv-acquire run-plan --plan examples/stage2-e20-e64/run-plan.json --next --expect-mode <mode>
```

The pass's record is `outputs/live/store/stage2-e20-e64.run.json` and each job's log sits beside it
as `stage2-e20-e64-<job>.jsonl`. The store directory is asserted against `--store-dir` /
`UDV_STORE_DIR`, and the application's own Store dialog cannot resolve a relative path — pass an
absolute, existing one or the cycle stops on its warning modal.

Anything that touches the screen runs in the interactive session
([`tools/live/README.md`](../../tools/live/README.md)); the live-dependent suites are the first
preflight at any sitting, and a failure that is not an understood live-state prerequisite stops the
sitting before a recording is spent.

## 7. What this pass is not

- **It is not a new design.** The sequence, the two levels, the fixed window and the fixed frame are
  the frozen Stage-2 decision's; re-deriving them is out of scope, and a plan that moved any of them
  would be a different pass with its own justification.
- **It is not a dense sweep.** Eight jobs in one campaign, four pairs, one window: the pass exists
  to make one step — E20 against E64 — comparable within one campaign.
- **It does not touch the earlier passes.** The first sparse pass and the mixer-enabled pass keep
  their own plans, records and stored files; their four emissions-20 runs and their single
  emissions-64 observation stay prior context for the later analysis.
- **It does not acquire the sensitivity condition (D1).** That remains a separate capability
  project: the recording surface carries no echo/energy channel, so no acquisition of that condition
  produces evidence yet.
- **It does not decide the science.** The acceptance criterion the decision table states in advance
  — a resolved difference or an unresolved overlap, both screened against a floor measured inside
  this campaign — is applied when this pass's recordings are analysed, not here.
