# `udv-analysis` reference and preservation register

Status: **reference document. `udv-analysis` is not retired.** The source checkout
stays in place and the private preservation pack stays in place; deleting either
requires a separate explicit decision by the repo owner.

Authority: [`udv-analysis-absorption-plan.md`](udv-analysis-absorption-plan.md) is
the source-analysis and decision record (what was measured, why each capability was
shaped the way it was, the D1–D5 decisions). **This** document is the standing
inventory: it answers "what exists in `udv-analysis`, what happened to each piece,
and what is preserved for later" at file granularity, so an unported capability
cannot be lost silently.

## 1. Why a separate reference exists

Absorbing a package and retiring it are two different risks:

- The absorption record is decision-shaped. Its §4/§5 tables are capability rows,
  and its §5 heading (`Do not absorb`) reads as final. A capability that was
  neither absorbed nor listed there leaves no trace that it ever existed.
- Retirement is one-sided. Upstream is unreachable
  (`https://github.com/MaksimiliansPirs/udv-analysis` → HTTP 404, probed at pack
  time; local history is a single commit `1efe97d` + annotated tag `v0.1.0`), so
  the preservation pack is the **only** remaining copy. Losing it loses the work
  outright.

Hence: every tracked source file gets a disposition here, and every *rejection* is
recorded with the reason plus what would revive it — so a later reader re-opens a
decision deliberately instead of rediscovering the code by accident.

`udv-analysis` 0.1.0 was a configuration-driven package for one job: robust
velocity-versus-depth profiles with operating-state detection and quantile-envelope
sample rejection. The package is 4,858 lines of Python across 18 modules
(`_vendor/doppy.py` alone is 2,255 of them); the repository has 40 tracked files,
including two top-level shim scripts and 7 test modules (plus `conftest.py`). It is
also the reference our `.BDD` reader was validated against — see the plan's §2 for
the measured numbers.

## 2. The preserved copy

| Item | Value |
|---|---|
| Pack root (default) | `$UDV_ANALYSIS_ARCHIVE`, default `~/.hermes/artifacts/udv-analysis-retirement/1efe97d/` |
| Preserved commit | `1efe97dc91b475d8b8bee68f8a7371ce07c2ae65` (`main`, annotated tag `v0.1.0`) |
| Git bundle | `git/udv-analysis-1efe97d*.bundle`, sha256 `1575375488ca85374fa25a66aeb5284828c4ced3bfeb99f347c15ca1743a372a` |
| Tree snapshot | `git/udv-analysis-1efe97d-tree.tar.gz`, sha256 `5a07ab73029f07b61bf8143d965d0d8537519770eca4bf1cb34bfd36a061d07a` |
| Checksummed inventory | `inventory.json` (168 files, 14,329,546 bytes) |
| Full evidence record | `metadata.json` (versions, commands, fixtures, blockers, cross-check residuals) |

Also preserved: both `dist/` artifacts (wheel + sdist), `LICENSE`/`NOTICE` and the
vendored DOPpy licence, both example configs, the six committed `.ADD`/`.BDD`
fixtures, the five generated baseline configs, five reproduced run directories, the
capture/CLI JSON+NPZ baselines, and every pack script.

The pack path is deliberately referenced through the `UDV_ANALYSIS_ARCHIVE`
environment variable — the unset-by-default skip gate on the archived-replay tests
(`tests/test_states.py`, `tests/test_profiles.py`) — not as a hard-coded absolute
path. Keep it that way: the repo is public.

### Verify the copy

```bash
export UDV_ANALYSIS_ARCHIVE=~/.hermes/artifacts/udv-analysis-retirement/1efe97d

# 1. the bundle is complete, and reconstructs the source
git bundle verify "$UDV_ANALYSIS_ARCHIVE"/git/udv-analysis-1efe97d*.bundle
git clone "$UDV_ANALYSIS_ARCHIVE"/git/udv-analysis-1efe97d*.bundle /tmp/udv-analysis

# 2. every file still matches its recorded sha256
python3 - <<'PY'
import hashlib, json, os, pathlib
root = pathlib.Path(os.environ["UDV_ANALYSIS_ARCHIVE"])
inv = json.loads((root / "inventory.json").read_text())
bad = [f["path"] for f in inv["files"]
       if hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
print(f'{len(inv["files"])} recorded, {len(bad)} mismatched: {bad}')
PY

# 3. the archived numbers still reproduce through the receiver
uv run --extra dev pytest tests/test_profiles.py tests/test_states.py
```

Verified against the live pack on 2026-09-12: step 1 passes (the bundle records a
complete history and clones to 40 tracked files at `1efe97d`), step 2 reports **168
recorded / 1 mismatched** (the §Known integrity defect file, below), and step 3's
tests split **212 passed + 22 skipped** with the variable unset versus **234 passed**
with it set — 26 archive-gated tests that read the pack's baselines. That split is
the preservation test: a pack that stops reconstructing turns those tests into
failures rather than skips.

### Known integrity defect (one file)

A full re-verification on 2026-09-12 read **167 of 168 files matching**. The single
mismatch is `baseline/validation_report.json`: `inventory.json` was sealed at
23:21:39 and that report was rewritten at 23:22:53, i.e. *after* the seal, so the
recorded hash for it is stale — same byte count, different content, most likely a
re-run with a different result set (the report's `strict_json` count of 46 files
also disagrees with `metadata.json`'s recorded 42). Nothing else is affected, and
the report is derived evidence rather than source. Either re-run
`scripts/validate_archive.py` + `scripts/finalize_archive.py` to re-seal the pack, or
record the staleness in the pack README. **Do not treat the current
`inventory.json` as covering that one file.**

## 3. Dispositions — all 40 tracked source files

`Absorbed` = a landed counterpart exists in this repo (path given). `Rejected` = a
deliberate decision with its reason. `Open` = preserved, no counterpart, live for a
future use case. Line counts are the source's.

### 3.1 Python — processing (the scientific core)

| Source file | Lines | Disposition |
|---|---|---|
| `processing/profiles.py` | 239 | **Absorbed** → `analysis/profiles.py` (clamped B-spline quantile LP, TV-smoothed envelopes, in-envelope median + unscaled MAD, retained counts). Archived arrays reproduce exactly. |
| `processing/states.py` | 237 | **Absorbed** → `analysis/states.py` (local-σ texture → depth median → \|Gaussian d/dt\| → Kittler–Illingworth × factor → persistent peaks → half-open intervals). |
| `processing/tv.py::custom_tv_l1` | ~60 of 163 | **Absorbed, private** → `analysis/_tv_l1.py`. No public `FilterSpec` branch (decision D1). |
| `processing/tv.py::opencv_tv_l1` | — | **Rejected** — OpenCV as a hard dependency (plan §5). |
| `processing/tv.py::apply_tv_filter` | — | **Rejected** as a dispatcher — our `TvFilterSpec` is 1-D per-gate and segment-aware; a backend switch has no equivalent shape. |

### 3.2 Python — I/O

| Source file | Lines | Disposition |
|---|---|---|
| `io/bdd.py` — calculated gate depths | — | **Absorbed** → `io/dop/bdd.py::_calc_gate_depths_mm`. Depth agreement with the `.ADD` reference improved 0.05 → **0.0033 mm**. |
| `io/bdd.py` — `repair_circular_timestamps` | — | **Absorbed** → the reader's overflow-corrected timestamps. |
| `io/bdd.py` — metadata coverage | — | **OPEN.** ~25 named settings and every scalar channel parameter are not carried into `ChannelConfig`: `velo_scale`, `emitNprofile`, `profile_skip`, `medianProfileN`, `movAvgProfileN`, `bandwidth`, profile-filter code, external-trigger state, and the 512-byte BDD comment. The op words are decoded locally for the depth/velocity maths only. See §4.1. |
| `io/add.py` | 139 | **Rejected** — our parser is strictly better on real files (its reader loaded 0 of 43 committed `.ADD` fixtures). One idea absorbed: the strict units check that stops amplitude being ingested as velocity. |
| `io/__init__.py` | 25 | Rejected with the reader layer — plumbing for `load_measurement`. |

### 3.3 Python — model, config, pipeline, output, CLI, plotting

| Source file | Lines | Disposition |
|---|---|---|
| `models.py` | 73 | **Rejected** (`Measurement`/`AnalysisResult` dataclasses — plan §5). The `StateInterval` concept survives as `OperatingStateInterval`. |
| `config.py` | 549 | **Rejected as a plane** (D3 — no second TOML/config surface); its **documented default values are absorbed** as the archived baseline defaults asserted by `test_defaults_are_the_archived_baseline_defaults`. Its unknown-key rejection is our `extra="forbid"`. |
| `pipeline.py` — `analyze_run` sequence | 244 | **Rejected as a shape** — a hard-coded stage sequence in one function, against bundle-closed registered operations. |
| `pipeline.py::valid_depth_mask` | — | **OPEN.** The exclusive depth rule (`depth < maximum_mm`, enabled/maximum only, and "excludes every gate" is an error). Nothing in `src/udv_echo_process/` applies a depth cutoff — `ChannelConfig.max_depth_mm` is metadata only. See §4.1. |
| `pipeline.py::inspect_measurement` | — | **Absorbed as intent** → content-aware `udv-inspect` (dispatches on bytes, reports decoded dimensions and config). |
| `outputs.py` | 299 | **Rejected as a plane** — manifest v2 + cache fingerprint is a competing provenance/state plane (`ArtifactGraph` + store-1 already win). Intents absorbed: strict finite JSON, deterministic run directory. **OPEN:** the profile fingerprint / result-reuse cache has no counterpart (no cache by design). |
| `plotting.py::symmetric_color_limit` | 179 | **OPEN.** No shared raw/filtered colour limit; `viz.py` computes limits per panel. |
| `plotting.py::state_detection_figure`, `interval_gallery_figure`, `profile_figures` | — | **OPEN.** No state-change trace, interval gallery, or colour-grouped profile figure; viz panels are `(channel, meas_type)` heatmaps only. |
| `handoff.py` | 87 | **OPEN, low priority.** The only implementation of reading a run manifest back into arrays (`udv-analysis/run-manifest/v2` + legacy `udv_run_handoff/v1`). Rejected by decision (the export boundary writes no legacy reader), but a run-directory consumer would want this. |
| `cli.py` | 116 | **Rejected** (D3) — its content is absorbed into `udv-inspect` instead of a second analysis CLI. |
| `_vendor/doppy.py` | 2255 | **Rejected** — our reader is numerically equivalent (max abs diff 5.0e-4 mm/s, one quantisation step). `_vendor/DOPPY_LICENSE.txt` is preserved as the vendoring-notice precedent. |

### 3.4 Python — tests, shims, packaging, docs

| Source file | Disposition |
|---|---|
| `tests/test_processing.py` | Absorbed as ideas → `tests/test_profiles.py`, `tests/test_states.py` (plus archived-baseline replay). |
| `tests/test_bdd_integration.py`, `tests/test_cli.py`, `tests/test_io.py` | Absorbed as ideas → `tests/test_io_bdd_artifacts.py`, `tests/test_cli.py`, `tests/test_parser.py`. |
| `tests/test_config.py` | Rejected with the config plane. |
| `tests/test_pipeline.py` | Not ported — no equivalent chain to test; its depth-rule assertions are part of the §4.1 open item. |
| `tests/test_scope.py` | **Anti-lesson, not absorbed.** Asserts *absence* (no animation/replay entrypoint, no pillow/ffmpeg). The analogue here is `tests/test_package_surface.py`. |
| `tests/conftest.py` | Test plumbing. |
| `run_0500rpm_single_state.py`, `udv_data_analysis.py` | **Rejected** — deprecation shims (plan §5). |
| `configs/example-single-state.toml`, `configs/example-sweep.toml` | **Rejected** (D3); preserved in the pack. Both point at input paths that do not exist. |
| `pyproject.toml`, `MANIFEST.in`, `.gitignore`, `.github/workflows/ci.yml` | Packaging/build plumbing — no counterpart needed. |
| `LICENSE`, `NOTICE` | MIT, Copyright (c) 2026 Maksimilians Pirs. Preserved in the pack. **See §4.2 — attribution has not been carried into this repo.** |
| `README.md`, `AGENTS.md`, `ARCHITECTURE.md` | `ARCHITECTURE.md`'s "Core invariants" are **absorbed as prose** (exclusive depth rule, transitions in neither state, unscaled MAD is not uncertainty, quantile fit is per-depth, solver failure is an error). The other two are source-specific; the pack keeps them, and their falsified numeric claims are recorded in the plan's §2. |

## 4. Open items this register exists to prevent losing

### 4.1 Capabilities with no counterpart yet

1. **Exclusive depth rule** (`pipeline.py::valid_depth_mask`) — a configured
   `maximum_mm` cutoff with an enabled switch, applied before state detection and
   profiling; excluding every gate is an error. Nothing applies it today, so an
   analysis can silently include gates the original would have dropped. Natural
   home: a field on the terminal analysis settings (not `ChannelConfig`, which is
   decoded device metadata) or an explicit gate-mask argument.
2. **`ChannelConfig` metadata coverage** — the ~25 named settings above. This is the
   plan §4 row that never landed: `models/channel_config.py` is unchanged since
   signal-model phase 1 and `bdd.py`'s `ChannelConfig(...)` construction still omits
   them. The BDD comment stays dropped by design (a reviewed five-field loss).
3. **Visualization intents** — shared symmetric colour limit for raw/filtered pairs,
   a state-change trace with interval panels, and profile-group figures.
4. **Run manifest read-back** (`handoff.py`) — only worth revisiting if a consumer of
   a written run directory appears.

### 4.2 Attribution and licence

The receiver carries **no** `LICENSE`/`NOTICE` file, while several landeds are
adapted from an MIT-licensed source whose copyright line is
`Copyright (c) 2026 Maksimilians Pirs`. The absorbed modules acknowledge the origin in
their docstrings and `references/wolfram/README.md` carries the porting row, but no
licence text or attribution notice is distributed. Upstream is now unreachable, so
the pack's `licenses/` copies are the only surviving statement of terms. Decide
whether to add a third-party attribution note (the receiver's own licensing is the
owner's call and is out of scope here).

### 4.3 Evidence holes (recorded, not worked around)

- **No multi-state velocity fixture.** Both committed 4-sensor recordings are steady
  200 RPM (0 transitions), so the multi-transition interval path has no committed
  fixture; equivalence is proven against the source's own function on synthetic
  topology and on the pack's generated configs.
- **No accepted non-example config exists.** The exact configuration behind the
  source's cited results is unrecoverable; the pack's baselines were generated from
  the package's own documented defaults.
- **The immediate predecessor is unrecoverable** — an unnamed Python
  `QuantileRegression` package and earlier "State 5" output. The echo Mathematica
  notebook is a same-campaign relative, not proven to be the direct predecessor.
- **Its `.ADD` reader loads none of the committed fixtures** (38 echo exports fail
  the all-`mm/s` units row, 5 multi-block exports fail on repeated headers / stat
  labels). Velocity cross-checks therefore use our reader for the `.ADD` side.

Blockers B1–B5 with their full statements and mitigations are in the pack's
`metadata.json`, and the machine-readable residuals are in its
`baseline/crosscheck_receiver.json`.

## 5. Re-deriving this inventory

```bash
# source-side inventory and per-file API
git -C ~/Repos/udv-analysis ls-files
wc -l ~/Repos/udv-analysis/src/udv_analysis/**/*.py

# what the receiver already covers
grep -rn "<symbol>" src/ tests/

# the pack's own evidence
python3 -c 'import json;print(json.load(open("$UDV_ANALYSIS_ARCHIVE/metadata.json"))["blockers"])'
```

When a §4.1 item lands, move its row from **OPEN** to **Absorbed** with the
destination path, and record the landing in `docs/agenda.md` plus
[`references/wolfram/README.md`](../references/wolfram/README.md) when it is a
ported feature.

## Further reading

| Question | Source |
|---|---|
| Why each decision was made, and what was measured | [`udv-analysis-absorption-plan.md`](udv-analysis-absorption-plan.md) |
| What is active right now | [`agenda.md`](agenda.md) |
| How a new module must be shaped | [`pipeline-conventions.md`](pipeline-conventions.md) |
| What the receiving model contracts are | [`signal-model-rework-plan.md`](signal-model-rework-plan.md) §5–§9 |
| What is ported from the Wolfram sources | [`references/wolfram/README.md`](../references/wolfram/README.md) |
