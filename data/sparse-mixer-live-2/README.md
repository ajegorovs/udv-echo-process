# Sparse mixer pass 2 — the frozen design acquired a third time

The `sparse-mixer-live-2` artefacts: nine jobs ran **2026-09-24 17:17:18 → 17:37:12**
(+03:00, 19 min 54 s) and **all 26 points were stored**, under the derived plan in
`examples/sparse-mixer-live-2/`. It is the frozen first pass's design — the same nine
jobs, the same three windows, the same 12 s window, the same 2500-profile declared
block cap, PRF 600 µs and the same plan-level facts — acquired under its own plan
name, its own file root (`sparse3`) and its own run record, so nothing it wrote can
collide with the two earlier realizations and each stays checkable on its own.

Like `sparse-mixer-live-1`, this pass exists to be a dataset and not to extend the
acquisition layer: **no writer, reader or gesture was added for it**, and its plan is a
derived copy of `sparse-mixer-live-1`'s with only the identity fields moved
(`plan`, `name_prefix`; every scientific value, point order, window and cap is
byte-identical to that file's).

## How it was run

- **Preflight, before anything was recorded.** The clone was at the reviewed `master`
  (`9df6384`, clean tree, 0 behind `origin/master`); the cross-platform suite passed
  **2540 tests, 22 skipped** with a clean `ruff check`; the two live-dependent suites
  passed **48 tests**; `run-plan --check` planned all nine jobs and 26 recordings
  without touching the instrument, and the live pre-run compile for job 1 refused on
  exactly one fact — the instrument stated `Burst length` 10 against the job's 4 —
  which is the declared-facts gate working, not a defect.
- **One bring-up recording before job 1**, at the instrument's then-current settings
  (burst 4, emissions 20, PRF 600), as `sparse-mixer-live-1` had: 561 profiles × 50
  gates, **27,749 of 28,050 samples non-zero** (0.9893), −111.99 … 191.47 mm/s, span
  12.5402 s, median interval 22.400 ms. That is the moment this sitting's rig was
  shown to be live; **it is not part of the pass and is not committed here**.
- **One operator hand change between jobs**, and nothing else: burst length
  4 → 10 → 18 → 10 (jobs 1-4), then emissions per profile
  20 → 8 → 20 → 64 → 20 → 128 (jobs 5-9). Every other step — the per-point resolution
  and gate count, the record/stop/store cycle, the file naming, the read-back and the
  decode — is the compiled campaign path, and the pass's own record refuses a job that
  is not next.
- **A refusal earned its keep.** The step-5 change was first entered into the dialog's
  *left* column (`Burst length`) rather than its *right* column (`Emissions/profile`),
  and the run stopped before recording anything: `burst_length: the campaign declares
  10, the instrument states '8'` and `emissions_per_profile: the campaign declares 8,
  the instrument states '20'`. Burst is dialog-only so nothing cross-checks it;
  emissions is read from the measurement screen's parameter column with the dialog as
  an agreeing anchor, which is why both sides read 20. Nothing was stored and the
  application was left untouched.
- **The application's Store directory was left where the earlier passes put it**
  (`outputs/live/store`), the plan's own `store_dir`, asserted by the driver at every
  point.

**The records committed here are the run's own, with one declared normalization.** This
sitting started the run with the absolute `--store-dir` that
[`sparse-run-plan.md`](../../docs/dop3000/sparse-run-plan.md) §6 documents, so the
logs, manifests and run record it wrote carried `C:\Repos\udv-echo-process\outputs\live\store\…`
where the three earlier datasets record `outputs\live\store\…`. The prefix names one
machine's clone layout, is not covered by any recorded digest (`campaign_fingerprint`
hashes the definition), and varies between clones — so the copies committed here have
exactly that literal prefix removed (84 occurrences over 19 files, each file re-parsed
afterwards, the size delta asserted per file), and, as with the earlier datasets'
records, git stores them with LF line endings under the `data/sparse-mixer-live-2/`
pins in [`.gitattributes`](../../.gitattributes). Nothing else moved: **26/26
recordings are byte-identical to the stored originals, all 19 records equal their
originals minus the prefix, and all 9 manifest fingerprints still equal the definition
fingerprint of the job they name.** The originals under `outputs/live/store/` are
untouched, and a clone without them can verify everything below from the committed
bytes.

## Verified from these files

Every number is read back from the committed bytes by the project's own reader
(`load` → artifact model, `acquire.verify.read_words` → the operation words), and
cross-checked against the run's own log line for the same point.

| | value |
|---|---|
| recordings | 26 (nine jobs: 5 + 1 + 5 + 1 + 4 + 1 + 4 + 1 + 4) |
| zero-payload recordings | **0** |
| non-zero fraction per recording | 0.9879 – 0.9939 |
| retained span | 12.4687 – 12.5850 s, all above the pass's 11.52 s usable gate |
| profile counts | 826-827 / 558-563 / 257-258 / 144-145 at emissions 8 / 20 / 64 / 128 |
| structural size law | **byte-exact on 26/26** (`SizeSignature.expected_bytes`, ratio 1.000) |
| stored word 14 (emissions) | 8, 20, 64, 128 — matching each point's own request (4 / 14 / 4 / 4 points) |
| stored word 8 (burst) | 4 (job 1), 18 (job 3), 10 (every other job) — matching each job's declaration |
| stored words 5 / 19 (PRF, sound speed) | 600 µs / 1480 m/s in all 26 |
| point order within each job | the design's own: control at the beginning, the block's scientific rows, a control around the middle, a control at the end |

| step | job | label | file | profiles | span (s) | period (ms) | non-zero |
|---:|---|---|---|---:|---:|---:|---:|
| 1 | `burst-4` | ctrl-begin | `sparse3-burst-4-ctrl-begin-20260924T171726.BDD` | 561 | 12.5403 | 22.400 | 0.9888 |
| 1 | `burst-4` | cc1 | `sparse3-burst-4-cc1-20260924T171726.BDD` | 558 | 12.5160 | 22.500 | 0.9917 |
| 1 | `burst-4` | ctrl-mid | `sparse3-burst-4-ctrl-mid-20260924T171726.BDD` | 563 | 12.5850 | 22.400 | 0.9879 |
| 1 | `burst-4` | cc3 | `sparse3-burst-4-cc3-20260924T171726.BDD` | 561 | 12.5309 | 22.400 | 0.9902 |
| 1 | `burst-4` | ctrl-end | `sparse3-burst-4-ctrl-end-20260924T171726.BDD` | 560 | 12.5179 | 22.400 | 0.9889 |
| 2 | `common-reference-1` | cr1 | `sparse3-common-reference-1-cr1-20260924T172037.BDD` | 560 | 12.5179 | 22.400 | 0.9906 |
| 3 | `burst-18` | ctrl-begin | `sparse3-burst-18-ctrl-begin-20260924T172136.BDD` | 560 | 12.5180 | 22.400 | 0.9928 |
| 3 | `burst-18` | cc2 | `sparse3-burst-18-cc2-20260924T172136.BDD` | 559 | 12.5384 | 22.500 | 0.9907 |
| 3 | `burst-18` | ctrl-mid | `sparse3-burst-18-ctrl-mid-20260924T172136.BDD` | 561 | 12.5403 | 22.400 | 0.9902 |
| 3 | `burst-18` | cc4 | `sparse3-burst-18-cc4-20260924T172136.BDD` | 561 | 12.5309 | 22.400 | 0.9908 |
| 3 | `burst-18` | ctrl-end | `sparse3-burst-18-ctrl-end-20260924T172136.BDD` | 560 | 12.5179 | 22.400 | 0.9903 |
| 4 | `common-reference-2` | cr2 | `sparse3-common-reference-2-cr2-20260924T172424.BDD` | 562 | 12.5627 | 22.400 | 0.9912 |
| 5 | `emissions-8` | ctrl-begin | `sparse3-emissions-8-ctrl-begin-20260924T172909.BDD` | 826 | 12.5345 | 15.200 | 0.9892 |
| 5 | `emissions-8` | e8 | `sparse3-emissions-8-e8-20260924T172909.BDD` | 826 | 12.5346 | 15.200 | 0.9910 |
| 5 | `emissions-8` | ctrl-mid | `sparse3-emissions-8-ctrl-mid-20260924T172909.BDD` | 827 | 12.5497 | 15.200 | 0.9897 |
| 5 | `emissions-8` | ctrl-end | `sparse3-emissions-8-ctrl-end-20260924T172909.BDD` | 827 | 12.5497 | 15.200 | 0.9913 |
| 6 | `common-reference-3` | cr3 | `sparse3-common-reference-3-cr3-20260924T173145.BDD` | 561 | 12.5403 | 22.400 | 0.9921 |
| 7 | `emissions-64` | ctrl-begin | `sparse3-emissions-64-ctrl-begin-20260924T173312.BDD` | 257 | 12.4912 | 48.800 | 0.9924 |
| 7 | `emissions-64` | e64 | `sparse3-emissions-64-e64-20260924T173312.BDD` | 257 | 12.4911 | 48.800 | 0.9899 |
| 7 | `emissions-64` | ctrl-mid | `sparse3-emissions-64-ctrl-mid-20260924T173312.BDD` | 258 | 12.5399 | 48.800 | 0.9926 |
| 7 | `emissions-64` | ctrl-end | `sparse3-emissions-64-ctrl-end-20260924T173312.BDD` | 258 | 12.5399 | 48.800 | 0.9939 |
| 8 | `common-reference-4` | cr4 | `sparse3-common-reference-4-cr4-20260924T173503.BDD` | 560 | 12.5179 | 22.400 | 0.9904 |
| 9 | `emissions-128` | ctrl-begin | `sparse3-emissions-128-ctrl-begin-20260924T173603.BDD` | 144 | 12.4687 | 87.200 | 0.9939 |
| 9 | `emissions-128` | e128 | `sparse3-emissions-128-e128-20260924T173603.BDD` | 145 | 12.5559 | 87.200 | 0.9917 |
| 9 | `emissions-128` | ctrl-mid | `sparse3-emissions-128-ctrl-mid-20260924T173603.BDD` | 145 | 12.5559 | 87.200 | 0.9914 |
| 9 | `emissions-128` | ctrl-end | `sparse3-emissions-128-ctrl-end-20260924T173603.BDD` | 144 | 12.4687 | 87.200 | 0.9938 |

The stored window words match the committed reference set's own: controls 50 gates /
resolution index 14 / 1.85 mm / depth 101, `cc1`/`cc2` 145 / 4 / 0.6167 / 99,
`cc3`/`cc4` 31 / 23 / 2.96 / 99.

**The block cap was never the limiter.** The application's own preference is unreadable
here by design, so the pass declares a *requirement* (2500 profiles) rather than a
capacity; with the measured period, no point of this pass could wrap it, and the
files confirm the retention: the highest-count point holds 827 profiles and every
stored span covers the requested 12 s.

### The period law, measured again

The median interval between stored profile timestamps reads **15.200 / 22.400 / 48.800
/ 87.200 ms** at emissions 8 / 20 / 64 / 128 — the 0.1 ms stamp, so an exact multiple
check is not available at any single level. The two 145-gate recordings (`cc1`, `cc2`)
read 22.500 ms instead, and their own gaps show what that is: 165 gaps at 22.4 ms and
392 at 22.5 ms, i.e. a quantisation boundary rather than a different period.

The logs carry the *achieved* mean interval at sub-tick resolution, and subtracting the
programmed `emissions × PRF` term leaves this sitting's intercept:

| emissions | achieved mean period (ms) | intercept (ms) |
|---:|---:|---:|
| 8 | 15.193 | 10.3934 |
| 20 | 22.402 | 10.4020 |
| 64 | 48.793 | 10.3935 |
| 128 | 87.194 | 10.3937 |

The **form** of the law is unchanged — `period = emissions × PRF + intercept` holds at
all four levels to within 40 µs — and the intercept itself reads **10.393–10.402 ms**
against the previous pass's **10.369 ms**: about 25-33 µs higher, which is a measured
difference between sittings, not a change of law. The emissions-20 group is the widest
(10.3766-10.4704 ms over 14 recordings) because it holds all four reference checks.

## What this directory does not contain

- **The analysis.** The burst, emissions and drift contrasts over these 26 recordings
  are their own slice, exactly as they were for the previous two datasets; this README
  carries acquisition facts only.
- **The rig's physical condition.** The file's own words prove the *instrument's*
  settings; what the mixer, the fluid and the transducer were doing is the operator's
  record, not something these bytes can state.

## Reproducing it

```text
# the whole pass, statically (no instrument): nine jobs, 26 recordings, the order
uv run udv-acquire run-plan --plan examples/sparse-mixer-live-2/run-plan.json --check

# where it stands, from its own record
uv run udv-acquire run-plan --plan examples/sparse-mixer-live-2/run-plan.json --status \
    --store-dir "$PWD/outputs/live/store"

# the operator's sheet: run-wide values, points, and what to set by hand
uv run udv-acquire run-plan --plan examples/sparse-mixer-live-2/run-plan.json --sheet
```

Plan fingerprint `f9de5b803921b62e788572ef5209a779d05638f1f7da4933384a743c02b6b7ef`; each
job's definition fingerprint is in its own manifest, and the pass record's
`definition_fingerprint` per job.
