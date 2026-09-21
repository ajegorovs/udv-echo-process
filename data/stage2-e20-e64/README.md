# Stage-2 pass — eight run-level jobs in four counterbalanced pairs

The `stage2-e20-e64` artefacts: eight jobs ran **2026-09-21 18:17:07 → 18:30:37** (13 min 30 s)
and eight points were stored, under the compiled plan in `examples/stage2-e20-e64/`. It is the
**Stage-2 campaign the frozen analysis designed** — four counterbalanced E20/E64 pairs in one
campaign, emissions per profile the only varying run-wide setting — and it is a different pass
from both earlier sparse passes: its own plan name, its own file root (`stage2`) and its own run
record.

It exists to answer one question the earlier data could not: whether **E64 differs from E20** by
more than the run-to-run variation of the campaign it was measured in. The earlier passes put E20
(4 common-reference runs) and E64 (one bracketed point) in *different* campaigns, so comparing
them would have mixed the emissions question with campaign drift; this pass measures both levels
in one sitting, adjacent within each pair.

## The frozen order, as acquired

One operator hand change between jobs, and only one thing ever changed: **emissions per profile**.

| # | job | pair | role | acquisition | emissions | file | KiB |
|--:|---|---|---|---|---:|---|---:|
| 1 | `e20-a` | A | lead | 20 → 64 | 20 | `stage2-e20-a-ref-20260921T181717.BDD` | 68 |
| 2 | `e64-a` | A | follow | 20 → 64 | 64 | `stage2-e64-a-ref-20260921T181901.BDD` | 48 |
| 3 | `e64-b` | B | lead | 64 → 20 | 64 | `stage2-e64-b-ref-20260921T182211.BDD` | 48 |
| 4 | `e20-b` | B | follow | 64 → 20 | 20 | `stage2-e20-b-ref-20260921T182425.BDD` | 68 |
| 5 | `e20-c` | C | lead | 20 → 64 | 20 | `stage2-e20-c-ref-20260921T182504.BDD` | 68 |
| 6 | `e64-c` | C | follow | 20 → 64 | 64 | `stage2-e64-c-ref-20260921T182715.BDD` | 48 |
| 7 | `e64-d` | D | lead | 64 → 20 | 64 | `stage2-e64-d-ref-20260921T182752.BDD` | 48 |
| 8 | `e20-d` | D | follow | 64 → 20 | 20 | `stage2-e20-d-ref-20260921T183037.BDD` | 69 |

The four hand changes are the pair boundaries where the level actually moves (jobs 2, 4, 6, 8);
jobs 3, 5 and 7 needed none. Each pair is read **E64 − E20** whatever order it was acquired in —
that is why the order is counterbalanced rather than alternating: with E20 always first, any
short-timescale order effect (handling time, mixer evolution, settling after the emissions change)
would be confounded with the contrast. The lower level leads two pairs and follows two; so does
the upper.

## How it was run

- The compiled campaign path ran every job: `run-plan --next`, which reads the instrument's own
  burst, emissions and PRF **before the first recording** and refuses the job on a disagreement —
  emissions is raised to a refusal by this pass (`strict_facts`), because it is the pass's one
  varying setting. The operator set emissions; nothing else was touched.
- The application's Store directory stayed `outputs/live/store`, the plan's own `store_dir`, which
  the driver asserts against the Store dialog at every point.
- Two jobs were refused before recording, both for the same precondition: while the run waited,
  a system surface (`Windows.UI.Core.CoreWindow` — Start/Search/notification centre) took the
  foreground, and this application ignores a hover while it is inactive. Nothing was hovered,
  pressed or written either time, and the pass's own resume preserved the pair it was in the
  middle of: after the second refusal, `e20-d` was still next rather than skipped. That is the
  fail-closed behaviour the design asked for, observed rather than asserted.

## Verified from these files

Every number below is read back from the committed bytes by the project's own reader.

| | value |
|---|---|
| recordings | 8, one per job |
| zero-payload recordings | **0** |
| non-zero fraction per recording | 0.9862 – 0.9913 |
| retained span | 12.4912 – 12.5626 s |
| profile counts | 560–562 at emissions 20, 257–258 at emissions 64 |
| stored word 14 (emissions), in acquisition order | **20 64 64 20 20 64 64 20** — matching each job's own declaration, 8/8 |
| frame (gates / resolution / depth / sound speed / PRF / burst) | 50 gates, 1.85 mm, 101 mm, 1480 m/s, 600 µs, burst 10 — identical in **8/8** |
| median profile period | **22.400 ms** at emissions 20, **48.800 ms** at 64 |
| structural size law | exact on **8/8** |
| velocity range | −113.19 … 191.47 mm/s |

### The period law reproduces at both levels

`period = emissions x 600 us + 10.400 ms` gives 22.400 ms and 48.800 ms — what these files
measure, exactly, at both levels of one campaign. (The earlier pass measured the same intercept as
10.369 ms; the 31 µs difference is below the 0.1 ms quantisation of the timestamps, and neither
pass's files are edited to match the other. The achieved period is always the one taken from the
stored timestamps.)

### "The same settings except emissions", checked rather than asserted

The pass was designed to vary one thing. That is now verified against the bytes rather than
trusted, by decoding **21 configuration fields** — gates, resolution, first gate, max depth, sound
speed, PRF, burst, emit power, sensitivity, TGC mode and its two dB values, skipped profiles,
Doppler angle, source frequency, velocity scale, module scale, wall filter, sampling volume,
trigger delay and trigger state — in:

- all eight Stage-2 files, against each other: **identical**;
- `stage2-e20-a` against the earlier pass's **E20 reference condition**
  (`sparse2-common-reference-1-cr1-…`) and against its **E64 point** (`sparse2-emissions-64-e64-…`):
  **identical**.

So the Stage-2 campaign sits on the frozen reference condition field for field, and the one thing
that moves between its jobs is the emissions word. Two details worth recording, neither a defect:
the sheet's TGC parenthetical states the *word-level* reading of the earlier pass (≈19.92 dB)
where this reader decodes `tgc_start_db` 23.06 / `tgc_end_db` 40.0 dB in uniform mode — the two
statements describe the same setting, and both passes agree on it; and `wall_filter` decodes as
absent in every file of both passes, so "filtering during acquisition OFF" is a state the
artefacts do not themselves state.

### Provenance is in the record, not in the file names

`stage2-e20-e64.run.json` carries, per job: `pair`, `role`, the acquisition `orientation`, the
declared `condition`, the definition fingerprint, the expected and successful recording counts, and
the log path; and at the pass level the plan fingerprint **`16a1f060053a…`** and
`analysis_orientation: E64 - E20`. A later reader can reconstruct pair membership and orientation
directly from the record — no inference from file names, and no reliance on the order the jobs
happen to be listed in.

## Reproduce

The structural-size and decode regressions read this directory through the reader:

```bash
uv run --extra dev pytest -q tests/test_acquire_log.py tests/test_acquire_stage2_run_plan.py
```

Each recording's own words, off the instrument (the file is the authority):

```bash
for f in data/stage2-e20-e64/*.BDD; do
  uv run udv-acquire decode "$f" --channel 1 | grep WordFacts
done
```

The pass's own status, and the sheet the operator worked from:

```bash
uv run udv-acquire run-plan --plan examples/stage2-e20-e64/run-plan.json --status
uv run udv-acquire run-plan --plan examples/stage2-e20-e64/run-plan.json --sheet
```

Signal content and retention, per recording:

```python
from pathlib import Path
import numpy as np
from udv_echo_process.io.dop.bdd import read

for path in sorted(Path("data/stage2-e20-e64").glob("*.BDD")):
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

## Contents

- 8 `.BDD` recordings — every job of the pass, root `stage2`;
- eight per-job JSONL logs (`stage2-e20-e64-<job>.jsonl`) and their job manifests
  (`…-<job>.manifest.json`);
- `stage2-e20-e64.run.json` — the pass's own status, the plan fingerprint
  (`16a1f060053a…`), the analysis orientation and the per-job pair/role/orientation.

## What is not here

The **Stage-2 analysis** is not in this directory, and was not run as part of the sitting. It is
what this pass unblocks, and the frozen decision table states the acceptance criterion it must be
read against: the four E20 observations and the four E64 observations reported separately; their
within-level run-to-run spreads; the **four adjacent paired E64 − E20 contrasts**, each normalized
to `E64 − E20`; the full cross-run range as context; and depth-resolved differences against a
**floor measured in this same campaign** — never against the earlier pass's 4.235 mm/s, which
belongs to a different sitting. Until that analysis is done, the decisions the analysis froze
(E64 `defer`/not-resolvable, E128 `replace`, PRF `keep`, the pitch x burst `defer`) stand as they
were published.
