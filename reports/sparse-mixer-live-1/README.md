# WP0 — the sparse pass's ingest, and the table every later work package reads

**Status:** WP0 deliverable of
[`docs/dop3000/sparse-pass-analysis-plan.md`](../../docs/dop3000/sparse-pass-analysis-plan.md)
§4. It converts the 26 committed recordings of
[`data/sparse-mixer-live-1/`](../../data/sparse-mixer-live-1/README.md) — the mixer-enabled
realization of the frozen nine-job design — plus the pass's own record, into the two
documents the drift, reference, interaction and emissions work packages select from.

Nothing here measures a scientific effect, and nothing here changes acquisition. The
ingest is the evidence a *later* step needs; the contrasts are that step's own.

| artefact | what it is |
|---|---|
| [`points.csv`](points.csv) | one row per committed recording: identity, order, condition, requested and stored window, decoded settings, the achieved timing measured from the stored timestamps, the retention the file covers, the signal statistics of the common window on the common support, and the provenance that ties the row to the bytes, the log, the manifest and the plan |
| [`qc-summary.json`](qc-summary.json) | the pass-level assertions, the two views, the metric definitions, the gate verdict, and the SHA-256 of `points.csv`'s own bytes |

## Reproduce

The generator is `a822b3f` (the commit before the artefacts); the command that
reproduces both files byte for byte is

```bash
.venv/Scripts/python.exe -m udv_echo_process.cli sparse-inventory \
    --analysis-commit a822b3f
```

The bare command records the **current HEAD** instead, which changes
`analysis_commit` and therefore the QC document's bytes — pass the recorded
**generator** revision to reproduce the committed pair exactly.
`tests/test_sparse_inventory.py::test_committed_artefacts_are_reproducible_with_the_recorded_commit`
runs that comparison, LF-normalized so a checkout's `core.autocrlf` cannot decide it.

## The two views

Both are **derived from the decoded recordings**, never declared:

- **common window** — the largest whole number of nominal 500-RPM revolutions every
  recording retained: **103 revolutions = 12.36 s**. A recording is cut by its own
  stored timestamps, so the cut is at the same *duration* though the profile counts
  differ — 814 profiles in the window at the fine window's rate, 551–553 at the
  reference rate, and 142 as the emission level lengthens the period.
- **common physical support** — the intersection of the recordings' decoded depth
  ranges: **10.138 – 98.938 mm**. The supported metrics are computed on each
  recording's own native gate grid inside it; no interpolation, no resampling, and
  no upsampling of the coarse window's data. The 1.85 mm window ends at 100.788 mm,
  so its last gate falls outside the support and 49 of its 50 gates are compared.

## What the committed bytes say

Every number below is read back from the committed files by the project's own
reader — the run is the reproduction command above.

| | value |
|---|---|
| recordings | **26** (nine jobs: 5 + 1 + 5 + 1 + 4 + 1 + 4 + 1 + 4) |
| decode failures / NaNs / non-monotone timestamp files | 0 / 0 / 0 |
| non-zero fraction per recording | 0.9864 – 0.9939 (the rig was live for every point) |
| retained span | 12.4686 – 12.5888 s, every recording above the pass's 11.52 s usable interval |
| achieved period from the stored timestamps | 15.193 / 22.393 / 48.793 / 87.193 ms (median interval) at emissions 8 / 20 / 64 / 128 |
| profiles per recording | 826–829 / 559–562 / 257–259 / 144–145 at those four levels |
| requested vs stored pitch | 0.617 → 0.6166667, 1.85 → 1.85, 2.96 → 2.96 mm (the ladder's own snapping) |
| common support / window | 10.138 – 98.938 mm / 103 rev = 12.36 s |
| job wall clock | 12:32:32 → 12:49:15 (16 min 43 s), nine jobs in plan order |

### The achieved period, and the planner's law

The period in the table is `(t_last − t_first) / (profiles − 1)` from each
recording's **own stored timestamps**. The planner's law
(`acquire/plan.py::profile_period_s`, the manual's `T_tran + T_prf · (16 + N_PRF)`)
is carried beside it as `period_expectation_s`, because the *departure* is itself a
measurement of this pass: it is **−0.21 to −0.22 ms at all four emission levels and
in one direction** — the planner's 1 ms transfer term is ~0.77 ms on these files, so
its profile-count expectation is under 1 % high at every level of this pass. That is
recorded here as a measurement, not as a change: acquisition is closed, and no
recording was affected by it.

### The retired target the logs keep

Each job log's `timing.target_s` reproduces the **retired**
`emissions × PRF + 1 ms` form the planner used on the day of the run — 0.0058 s at
emissions 8, 0.0130 s at 20, 0.0394 s at 64, 0.0778 s at 128 — and not the achieved
period at any level. The ingest carries it as `log_target_s`, next to
`achieved_period_s`, and **refuses a log whose target no longer reproduces that
law**: an edit to the later law is the one change these files must never be given
(`data/sparse-mixer-live-1/README.md` says so; the two commits that corrected the law
sit above the pass, not inside its logs).

## What is checked before a row is written

A refusal is a named error and a non-zero exit, never a traceback and never a
half-written artefact. The ingest refuses when

- the pass record's plan or plan fingerprint is not the committed plan's;
- a job's step, condition or definition fingerprint is not the plan's, or a job
  manifest answers a different definition than the plan's;
- a stored file is claimed twice, a committed recording no planned point claims, or a
  planned point's recording is not committed;
- a log's point name, file path, key or status disagrees with the manifest's, or a
  committed point's own verdicts are not `ok`;
- this reader's decode disagrees with the acquisition layer's own decode of the same
  bytes (settings, shape, size, span, median interval, period);
- a stored word is not the declared setting — including word 14, this pass's *raised*
  fact, where a disagreement invalidates the point rather than becoming an advisory;
- the stored pitch is not the rung the application accepts for the request, or the
  point's window is not one of the pass's three;
- the log's `timing.target_s` is not the retired law for that point's emissions.

and the QC gate — `ok` — holds only when all twelve of the summary's checks pass:
recordings, per-job counts, decode failures, NaN cells, timestamp monotonicity, signal
content (non-zero fraction ≥ 0.5), retention (≥ 11.52 s), the common window, the common
support, the achieved period inside the planner's law (≤ 1 ms), the retired target
recorded, and the recorded analysis commit.

## What is deliberately not here

The within-job control drift, the CR1–CR4 reference drift, the 2×2 pitch × burst
interaction and the emissions 8/20/64/128 behaviour are WP1–WP4 of the plan. They
select from this table by **decoded settings**, never by filename, and they must not
change these artefacts: later work packages add documents beside them.
