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
