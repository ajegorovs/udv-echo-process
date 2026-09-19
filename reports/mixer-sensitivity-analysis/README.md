# Mixer sensitivity analysis reports

This directory is the reviewer-visible output contract for
[`docs/dop3000/existing-sweep-analysis-plan.md`](../../docs/dop3000/existing-sweep-analysis-plan.md).
It begins with the contract rather than hand-produced results: generated artefacts land here only when
the command that regenerates them and their acceptance tests land in the same commit.

Expected outputs, in work-plan order:

| Path | Owner | Purpose |
|---|---|---|
| `manifest.csv` | WP0 | one authoritative row per committed BDD |
| `qc-summary.json` | WP0 | file counts, invariants and decode/timestamp/data-quality checks |
| `reference-repeat.csv` | WP1 | same-settings repeatability/drift bound versus depth |
| `figures/reference-repeat.*` | WP1 | reviewer-visible repeat comparison |
| `figures/resolution-*` | WP2 | spatial-pitch evidence on native and common grids |
| `figures/burst-*` | WP2 | burst transition and smoothing evidence |
| `figures/prf-*` | WP2 | alias margin and temporal-bandwidth evidence |
| `figures/energy-*` | WP2 | velocity-only TGC/power diagnostics and their limits |
| `decision-table.md` | WP3 | candidate-level keep/defer/replace/diagnostic verdicts |

The WP0 artefacts are regenerated with the committed reader and nothing else:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli sweep-inventory
```

It writes `manifest.csv` and `qc-summary.json` in this directory from
`data/mixer-sensitivity-analysis/4MHz/0500RPM/001` (both overridable with
`--dataset-root` / `--report-dir`). Manifest paths are dataset-relative, both files use LF endings and
one trailing newline, and floats carry 12 significant digits, so a regeneration from the same revision
is byte-identical. `qc-summary.json` records the revision it was generated against and the manifest's
own SHA-256, and the command exits non-zero when any WP0 gate check fails.

**Provenance: which revision a run records.** The bare command above records the
**current HEAD** of the checkout it runs in, so running it on a later commit
regenerates the two files with a different `analysis_commit` and therefore
*different bytes* — that field is a provenance statement about the run, not a
constant. The committed `manifest.csv` and `qc-summary.json` are reproduced byte
for byte only by passing the generator commit that the committed
`qc-summary.json` already records:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli sweep-inventory \
    --analysis-commit <the analysis_commit recorded in the committed qc-summary.json>
```

`--analysis-commit` therefore has two legitimate uses: reproduce a committed
artefact exactly (pass its recorded commit), or label a fresh run with the
revision whose reader produced it (pass that revision). The equivalent
`analysis.sweep_inventory.write_sweep_inventory(..., analysis_commit=...)`
keyword does the same for callers.

Every generated table or figure must carry or sit beside:

- the analysis git commit;
- the input content hashes (directly or through `manifest.csv`);
- the exact regeneration command;
- units and the selected time/depth view;
- an explicit distinction between observed data, derived metric and decision threshold.

Large caches, temporary arrays and exploratory notebook state do not belong here. If a result cannot be
regenerated from the committed BDD files, it is not an accepted report artefact.

## WP1 — the reference-repeatability bound

The only same-settings repeat in the committed set is `prf/600.BDD` against `res/1-8.BDD`: identical
operating parameters, different durations (14.956 s / 11.5529 s, 669 / 517 profiles). Their difference
is an **upper bound** on same-setting repeatability, because duration and unknown acquisition time also
differ — the files carry no acquisition order, so drift can be bounded but never reconstructed. The
WP1 artefacts are:

| Path | What it is |
|---|---|
| `reference-repeat.csv` | 50 rows, one per gate: mean, median, robust spread (IQR), RMS and zero fraction for each recording and for their signed difference |
| `reference-repeat.provenance.json` | the binding (manifest hash, both source hashes, generator commit), the metric definitions, both time views, the temporal parameters with the full ACF/PSD curves, the declared envelope and the figure caption |
| `figures/reference-repeat.png` | four panels: the two depth profiles, the signed difference against the declared envelope, the ensemble autocorrelation and the ensemble PSD on the identical 50-gate grid |

They are written by:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli reference-repeat
```

The command selects the pair **from `manifest.csv`** (never from a hand-maintained filename list),
re-checks both source SHA-256 values against the bytes and every re-checked manifest cell against the
decoded recording, and refuses to produce anything when a selection, hash or setting disagrees
(exit 1, named reason, no half-written artefact). As with WP0, the bare command records the current
HEAD; the committed artefacts are reproduced byte for byte only by passing the commit the committed
`reference-repeat.provenance.json` already records:

```text
.venv/Scripts/python.exe -m udv_echo_process.cli reference-repeat \
    --analysis-commit <the analysis_commit recorded in reference-repeat.provenance.json>
```

Definitions the table cannot be read without, all restated in the provenance document:

- **common-duration view** — the largest integer number of nominal 500-RPM revolutions (0.12 s each)
  that fits both recordings: 96 revolutions = 11.52 s, truncated per file by the recorded timestamps
  (515 profiles of each). Every distributional metric uses that window and nothing else.
- **robust spread** — the interquartile range `p75 - p25`, linear-interpolated percentiles.
- **RMS** — root mean square about zero, so a mean offset raises it: it is not a standard deviation.
- **zero fraction** — the share of samples exactly equal to `0.0`.
- **difference** — signed, `prf/600.BDD - res/1-8.BDD`, field by field; a negative value means
  `res/1-8` is faster at that gate.
- **repeatability envelope** — the largest absolute per-gate mean difference over depth, with the gate
  and depth where it occurs. It is a bound on repeatability *plus* uncontrolled drift, not a
  repeatability estimate on its own, and it is the number every WP2/WP3 verdict must be compared to.
- **temporal view** — each full record in non-overlapping segments of 86 profiles (1.9031 s,
  15.9 revolutions), identical for both files, on one shared profile rate; frequency resolution
  0.5194 Hz at a 22.33 Hz Nyquist limit.
- **500 RPM = 8.33 Hz is a marker only** — there is no tachometer in these files, so the setpoint is
  never a phase reference, and neither gates nor profiles are independent experimental replicates.
