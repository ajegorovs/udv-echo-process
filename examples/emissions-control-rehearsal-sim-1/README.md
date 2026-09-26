# Emissions control — the four-job sequence, rehearsed in simulation

The emissions-control slice (`docs/dop3000/emissions-control-plan.md`) commissions four jobs:

```
E20  →  E64  →  E64  →  E20
```

This directory is the record of that sequence **run in simulation mode**, on the application
alone, with no instrument attached. It exists because the rig could not be used on 2026-09-26
(the box was powered off and the application was sitting behind its own *Loss of USB connection*
warning), and the code path was worth exercising anyway — it was, and it found two defects that
the live sitting would have hit first.

**This is not rig acceptance.** No ultrasound was emitted, no hardware state was moved, and the
frame is the simulation frame, not the instrument's. The merge gate stays on the live sitting
(`docs/dop3000/emissions-control-plan.md` §6). Treat every claim below as a claim about the
*software path*.

## What was run

The plan is committed here verbatim (`run-plan.json`, `jobs/*.json`) and every job definition
carries `write_emissions_per_profile: true`, so the boundary — not the operator — establishes the
run-wide emissions. The frame is whatever the simulated application states, read before planning:

| fact | value | how the run treats it |
|---|---|---|
| sound speed | 1460.0 m/s | dialog-only, declared, disagreement refuses |
| first gate | 2.0 mm | dialog-only, declared, disagreement refuses |
| PRF | 212 µs | read from the parameter column, refusal |
| burst length | 4 | read from the Operating parameters dialog; **declared at 4 in every job, so the boundary has nothing to transition** |
| emissions/profile | 20 at the start | written by the boundary when the job requests something else |
| window | 0.122 mm × 797 gates | written by the point |

Two pairs of `run-level` jobs, A (20 → 64) and B (64 → 20), counterbalanced, read `E64 − E20`
whatever order they were recorded in — the first two pairs of `examples/stage2-e20-e64`.
The join between them is the equal-value boundary: pair A's follow and pair B's lead are both 64.

Run with the worktree's interpreter, one job per invocation:

```
uv run --no-sync --extra acquire python -m udv_echo_process.cli acquire run-plan \
    --plan examples/emissions-control-rehearsal-sim-1/run-plan.json --next \
    --expect-mode simulation --channel 1 --store-dir outputs/live/store
```

## What it proved

`evidence.json` is the machine-readable form; `records/` holds the pass's own logs, copied
unmodified. The instrument sat at 150 emissions before the first job, so the sequence's first
transition is that 150 → 20 — an artifact of the simulated state, not of the design.

| job | requested | boundary | stored file | word 14 | word 8 (burst) | word 27 (index) | profiles |
|---|---|---|---|---|---|---|---|
| e20-a | 20 | wrote 150 → 20 (verified) | `emctl-sim1-e20-a-ref-…T201754.BDD` | **20** | 4 | 3 | 897 |
| e64-a | 64 | wrote 20 → 64 (verified) | `emctl-sim1-e64-a-ref-…T201852.BDD` | **64** | 4 | 3 | 454 |
| e64-b | 64 | **no write, no event** | `emctl-sim1-e64-b-ref-…T201926.BDD` | **64** | 4 | 3 | 454 |
| e20-b | 20 | wrote 64 → 20 (verified) | `emctl-sim1-e20-b-ref-…T202041.BDD` | **20** | 4 | 3 | 903 |

Every stored file's `emissions_per_profile` word was *enforced* against the request
(`covariates_enforced` names it alongside `sound_speed_ms`, `prf_us` and `burst_length`) — the
acceptance contract this slice changed, working on the stored word rather than on the screen.

The three durable mutations, in occurrence order, all `verified`, all distinct:

| occurred | id | job | transition | readback | fresh read |
|---|---|---|---|---|---|
| 20:05:08.338 | `b2f17f34…` | e20-a | 150 → 20 | 20 | 20 |
| 20:18:49.419 | `b0a039da…` | e64-a | 20 → 64 | 64 | 64 |
| 20:20:38.672 | `71688b33…` | e20-b | 64 → 20 | 20 | 20 |

Each record carries the writer's own read-back **and** the independent post-write read, the job,
the definition fingerprint, the routed channel and the parameter role; each was appended
**before** the job's own compile/resume record (the log's first line is the mutation, the second
is the point). No `unverified` mutation exists in any log: a write whose fresh read disagrees is a
refusal, so it never reaches the history.

The final state came back to **E20**: a `compile` against the live screen reconciles with
`emissions_per_profile 20`, every fact agreeing, with emissions raised to a refusal.

## What the rehearsal found

Two defects, both fixed in the commits above this one, both of which the live sitting would
have hit on its first job:

1. **A relative `--store-dir` was written into the Store dialog verbatim** (`427a1be`). The
   field is read by *another process*, which resolves it against its own working directory — so
   the string "verified" here (`same_directory` resolves both sides against this process) and the
   application then stored nothing, raising its own non-existent-directory warning. The operator
   recognised the warning immediately: it is what this application raises for relative paths. The
   boundary now resolves the target to an absolute path before it writes, compares or reports it.
2. **The pass's operator sheet still told the operator to set emissions by hand** (`6a7749e`),
   which is what the boundary does now. A sheet that asks for work the run is about to do is a
   sheet that gets followed: the operator sets 64, the boundary finds it equal, spends no write
   and appends no event, and the automation is never exercised. The sheet now says who writes
   each run-wide fact, per job.

And one operator-side precondition, recorded because it will apply to the live sitting too: the
application's own **Save dir** (Preferences → Record settings) was still pointing at the retired
reconnaissance archive's `…\RECON\OUT\CAPTURE`, a directory that no longer exists — the
application warns about it on every store attempt, and *even when closing that settings dialog*.
It was set to this repository's `outputs/live/store` before the run above.

## What it does not prove

- **Rig acceptance** — nothing here touches the instrument. The four-job live sequence is still
  owed, on the instrument's own frame (the stage2 sheet's 600 µs PRF, burst 10, 1480 m/s,
  10 mm), and its evidence package has to come from that sitting.
- **Hardware-dependent behaviour** — the write path's timing against real acquisition, and what
  a real store does under a real block cap, are untested here.
- **Anything about word 27 beyond its index.** It is recorded as provenance (index 3 in every
  file) and no physical sampling-volume value is derived from it, as the review requires.

The raw `.BDD` files are not committed (2.3 MB of simulation data); every word decoded from them
is in `records/`, and their sha256 and sizes are in `evidence.json`. Re-running the plan
reproduces them.
