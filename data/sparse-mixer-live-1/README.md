# Sparse mixer live pass — the same nine jobs on a measuring rig

The `sparse-mixer-live-1` artefacts: nine jobs ran **2026-09-21 12:32:32 → 12:49:15**
(16 min 43 s) and 26 points were stored, under the derived plan in
`examples/sparse-mixer-live-1/`. It is the frozen first pass's design — the same nine
jobs, the same windows, the same 12 s window and the same 2500-profile block cap —
re-run on a mixer that is actually moving.

This pass exists because the first pass's 26 recordings are **all zero** (the rig was
not producing signal; see `data/sparse-mixer-first-pass/README.md`). The two passes
share a design and differ only in the payload, so this directory is where the burst,
emissions and drift contrasts can be measured from, and the first pass remains the
acquisition layer's own structural evidence. Neither replaces the other, and nothing in
the first pass was overwritten: this is a **new realization of the same frozen design**,
under its own plan name, its own file root (`sparse2`) and its own run record.

## How it was run

- One operator hand change between jobs (burst length, then emissions per profile);
  everything else — the per-point resolution and gate count, the record/stop/store
  cycle, the file naming, the read-back and the decode — is the compiled campaign path.
- The application's Store directory was left where the first pass put it
  (`outputs/live/store`): the plan's own `store_dir`, asserted by the driver at every
  point, so nothing had to be changed by hand for the pass to be able to store.
- The plan is a **derived copy** of the frozen first pass with a new plan name and root
  (`sparse2`), so its files, logs, manifests and run record cannot collide with the
  first pass's — one pass writes one directory, and the record of each stays checkable
  on its own.
- Before job 1, one 12 s point was recorded at the instrument's then-current settings
  (burst 10, emissions 128, PRF 600): **7,146 of 7,200 samples non-zero**, −67.44 …
  122.83 mm/s. That is the moment the rig went live; it is not part of the pass and is
  not committed here.

## Verified from these files

Every number below is read back from the committed bytes by the project's own reader.

| | value |
|---|---|
| recordings | 26 (nine jobs: 5 + 1 + 5 + 1 + 4 + 1 + 4 + 1 + 4) |
| zero-payload recordings | **0** — first pass: 26 |
| non-zero fraction per recording | 0.9864 – 0.9939 (first pass: 0.0000) |
| retained span | 12.4686 – 12.5888 s, all above the pass's 11.52 s usable gate |
| profile counts | 826–829 / 559–562 / 257–259 / 144–145 at emissions 8 / 20 / 64 / 128 |
| structural size law | exact on **26/26** (see below) |
| stored word 14 (emissions) | 8, 20, 64, 128 — matching each point's own request (4 / 14 / 4 / 4 points) |
| stored words 27 / 84 | 1 / 0 in all 26 |

### The measured period law, and its two terms

The median interval between recorded profile timestamps is **15.2 / 22.4 / 48.8 /
87.2 ms** at emissions 8 / 20 / 64 / 128 (0.1 ms quantisation), i.e.

```text
period = emissions x PRF + 10.369 ms       (PRF 600 us here)
        = 15.169 / 22.369 / 48.769 / 87.169 ms
```

That intercept is the manual's `T_profile ≈ T_tran + T_prf · (N_Stb + N_PRF)`
(docs/08 §8.8) and it is **two terms, not one**: at 600 µs the instrument's own
`N_Stb = 16` emissions are `16 × 600 µs = 9.6 ms`, and the remaining ~0.77 ms is the
transfer term `T_tran`. The 10.369 ms is the two together; it is not the 16-emission
term on its own.

**This pass ran while the planner still used the retired `emissions × PRF + 1 ms`
form**, which dropped the 16-emission term: the `--sheet` estimate for these points
read 924 profiles at emissions 20 and 2069 at emissions 8, against the 531 and 780 the
corrected law gives. That changed no recording — the law sizes an *expectation*, never
the window — and the correction landed after this pass, in
`acquire/plan.py::profile_period_s`.

What it did change is the gross size guard's margin, and this pass is the evidence
that the margin was thin. Ratio = stored size / the size the guard expected, computed
per file with its own gate count, band `[0.5, 2.0]`:

| emissions | profiles the law expected (before → after) | ratio (before → after) |
|---:|---|---|
| 8 | 2069 → 780 | **0.508 → 1.037** |
| 20 | 924 → 531 | 0.673–0.767 → 1.027–1.039 |
| 64 | 305 → 245 | 0.937–0.939 → 1.017–1.020 |
| 128 | 155 → 138 | 0.982–0.984 → 1.010–1.012 |

Emissions 8 — the level a review of the planning law named as a credible
false-rejection risk — verified at **0.508**, 1.6 % inside the guard's lower edge. It
passed, but on a margin a slightly different profile count would have removed.

### The structural size law

A `.BDD` is the container plus its blocks:

```text
bytes = 31,268 + (19 + 2 x gates) + profiles x (19 + gates)
```

It reproduces **all 26 files of this pass and all 26 of the first pass** byte for byte,
and `tests/test_acquire_log.py` reads both directories back through the reader and
asserts the equation against each file's real size. (The retired model —
`1.7 x gates x profiles`, the payload alone — is what falsely refused the first pass's
`emissions-128` job at 3.14x. On this pass that job verified `4/4 ok`.)

## Reproduce

The structural-size regression reads these files:

```bash
uv run --extra dev pytest -q tests/test_acquire_log.py
```

Signal content and retention, per recording:

```python
from pathlib import Path
import numpy as np
from udv_echo_process.io.dop.bdd import read

for path in sorted(Path("data/sparse-mixer-live-1").glob("*.BDD")):
    stream = read(path).recording.streams[0]
    values = stream.data.values
    times = np.asarray(stream.data.time_s, dtype=float)
    print(
        path.name,
        values.shape,
        f"{np.count_nonzero(values)}/{values.size} non-zero",
        f"span {times[-1] - times[0]:.4f} s",
        f"word14={stream.config.emissions_per_profile}",
    )
```

The pass's own record (`sparse-mixer-live-1.run.json`) and each job's log and manifest
can be re-read without touching the instrument:

```bash
uv run udv-acquire report --log data/sparse-mixer-live-1/sparse-mixer-live-1-burst-4.jsonl
```

## Contents

- 26 `.BDD` recordings — every point of every job, root `sparse2`;
- nine per-job JSONL logs (`sparse-mixer-live-1-<job>.jsonl`);
- nine per-job manifests (`…-<job>.manifest.json`);
- `sparse-mixer-live-1.run.json` — the pass's own status, the plan fingerprint
  (`655298032dab…`) and the per-job definition fingerprints.

## What is not here

The analysis this pass was captured for — per-job drift, the reference checks across
runs, the pitch x burst contrast and a Stage-2 recommendation — is **not** in this
directory. Only the acquisition layer's own evidence is: every point stored, verified,
retained and decoded. The contrasts are the analysis work item the pass unblocks
(`docs/dop3000/acquisition-closeout-plan.md` §"What runs next", item 4).
