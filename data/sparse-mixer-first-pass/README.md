# Sparse mixer first pass — complete nine-job run

The complete `sparse-mixer-first-pass` record: nine jobs, 26 points, stored
2026-09-20–21 under the frozen plan in `examples/sparse-mixer-first-pass/`. Kept
because the pass is the acquisition layer's own evidence — its structure,
retention, stored words and provenance are checkable from these files.

## What the acquisition layer has to answer, and does

- **All 26 points stored and verified.** Every file carries the requested window
  (gates, resolution rung, last-gate depth), the requested fixed facts (channel 1,
  PRF 600 µs, sound speed 1480 m/s, first gate 10 mm) and its own
  `emissions_per_profile` / `burst_length` word matching the point's request.
- **Retention.** Spans 12.4651–12.5713 s, all above the pass's 11.52 s usable
  gate. The profile count follows the achieved period
  (`emissions × PRF + 10.369 ms`): 827–829, 561–563, 257–258 and 144 profiles at
  emissions 8, 20, 64 and 128. That intercept is the manual's
  `T_tran + T_prf · (16 + N_PRF)` as two terms and not one: 9.6 ms of fixed emission time at
  PRF 600 µs, plus ~0.77 ms of transfer. The planner now computes both
  (`acquire/plan.py::profile_period_s`).
- **The structural size law.** A `.BDD` is the container plus its blocks:

  ```text
  bytes = 31,268 + (19 + 2 × gates) + profiles × (19 + gates)
  ```

  It reproduces all 26 files **byte-for-byte**, and the block chain ends exactly
  at EOF in every one — no truncation, no trailing bytes, no foreign file.

## One job was refused, and the guard was wrong, not the files

`emissions-128` was logged `invalid: 0/4`, four files on disk. The refusal was
entirely the old size signature, which modelled bytes as
`1.7 × gates × profiles` — the payload alone, with no container:

```text
old expectation:  1.7 × 50 × 155 = 13,175 B   (nominal 155-profile estimate)
actual file:     31,268 + 119 + 144 × 69 = 41,323 B
ratio:           3.14× → outside the 2× band → refused before the words were read
```

At 144 profiles the fixed 31,268 bytes dominate, so a payload-only rate cannot
describe the file. The four files are otherwise unremarkable: emissions 128 in
their own word 14, 144 profiles, 12.4651 s span, 50 gates / rung 14 / 1.85 mm /
depth 101, block chain ending at EOF, and their stored words verify against the
job's own request. The same guard sat close to its lower edge on the other axis
(0.503 at emissions 8) for the same reason — the fixed term, not the payload, is
what the old model omitted. That second margin is now gone as well: with the period law corrected
the emissions-8 expectation drops from 2069 profiles to 780, and the ratio moves from 0.508 to
1.037 — see the commit that landed `acquire/plan.py::profile_period_s`.

## The rig is not producing signal yet

Every decoded sample in all 26 recordings is zero, including the six
independently committed bounded-trial files. This is the intended state while the
capture functionality is developed: the mixer experiment is not running, and the
operator has deliberately deferred it rather than keeping the instrument busy for
days. It is recorded here so the zero payload is not later mistaken for a defect
in these files, and it is **not** something the acquisition layer has to explain.

The historical rig reference is not zero
(`data/mixer-sensitivity-analysis/4MHz/0500RPM/001/res/1-8.BDD`: 25,594 of 25,850
samples non-zero, −74.66 to 184.24 mm/s), so a future reader can tell a live rig's
files from these by content alone.

Consequence for the analysis: no burst, emissions, drift or Stage-2 conclusion is
available yet, and none was attempted. The contrasts the pass was designed for
need a rig that is actually measuring.

## Reproduce

The structural-size regression is in `tests/test_acquire_log.py`: it reads the
committed recordings back through the project's own reader and asserts the
equation above against each file's real size, with the `emissions-128` case
locked at 41,323 B.

Signal content:

```python
from pathlib import Path
import numpy as np
from udv_echo_process.io.dop.bdd import read

for path in sorted(Path("data/sparse-mixer-first-pass").glob("*.BDD")):
    values = read(path).recording.streams[0].data.values
    print(path.name, values.shape, int(np.count_nonzero(values)))
```

## Contents

- 26 `.BDD` recordings — every point of every job;
- nine per-job JSONL logs (`sparse-mixer-first-pass-<job>.jsonl`);
- nine per-job manifests (`…-<job>.manifest.json`);
- `sparse-mixer-first-pass.run.json` — the pass's own status and fingerprints.

The bounded-trial folder `data/sparse-mixer-first-pass-trial/` is deliberately
left unchanged so the fingerprints and provenance its review accepted do not move.
