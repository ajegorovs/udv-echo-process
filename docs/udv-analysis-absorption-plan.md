# udv-analysis → udv-echo-process absorption mapping

Status: **approved; implementation in progress** (`docs/agenda.md`).

Phase 0's private retirement/baseline pack and Phase 1's reader/inspection work
are complete. Phase 2 terminal analysis results and export remain active; Phases
3–4 follow. The source checkout has not been retired because §8 still has
unresolved external-lineage/dependency evidence.

Authority: this document is the source-analysis record for retiring the external
`udv-analysis` package and absorbing what it uniquely provides. It does **not**
change this repo's contracts — `docs/signal-model-rework-plan.md` (§5–§9),
`docs/pipeline-conventions.md` and `docs/architecture.md` remain authoritative
for the receiving model, transforms and boundaries.

## 1. Why this exists

`udv-analysis` is a separate, configuration-driven package for one job: robust
velocity-versus-depth profiles with operating-state detection and
quantile-envelope sample rejection. It is the only implementation we have of that
chain — the `references/wolfram/README.md` porting map still lists its core
(`QuantileRegression`, `PeakDetect`, image/histogram transforms) as **Not yet
ported**. The package is being retired, so its scientific content has to land
here or be lost.

Its `.BDD` path is also the reference we validated against, which is why the
numbers in §2 matter more than its code volume.

## 2. What was measured (evidence)

All figures below come from running both packages over the same recordings, not
from documentation.

| Check | Result |
|---|---|
| `udv-analysis` quality gate (`pytest`, `ruff check .`, `python -m build`) | clean; **20 passed, 1 skipped** (`UDV_TEST_BDD_PATH` unset), wheel + sdist build |
| `udv-analysis run` on a real 4-sensor `.BDD` velocity recording (channel 6) | exit 0, 2.2 s, 400 profiles × 55 gates, 12 artifacts, retained fraction 0.88–0.90 |
| Its BDD velocity vs our `.ADD`-derived reference (3-sensor 300/500 RPM, channels 6/7/8) | **max abs diff 5.0e-4 mm/s** (one quantisation step); min/median/max identical |
| Our `load()` on the same recordings | **same 5.0e-4 mm/s agreement** — the two readers are numerically equivalent |
| Gate depths on the same files | ours 9.50–96.30 mm (Δ 0.05 mm vs `.ADD`); its `bdd_source="Calc"` Δ **0.0033 mm**; its `"File"` Δ 0.05 mm |
| Our suite | **774 passed** (12.6 s) |
| Its `.ADD` reader on committed fixtures (43 files) | **0 load.** 38 single-block echo exports fail the units row (`Amp` where `mm/s` is required); 5 multi-block exports fail on the repeated per-block `Gate Depth [mm]` header or on a `_Stat.ADD` statistics label row |
| `udv-inspect <file>.BDD` | raises `not a UDV recording (missing 'ASCUDOPV' header)` — the CLI is `.ADD`-only |

Reproduce the two that matter:

```bash
# receiver side
uv run --extra dev pytest
uv run --python 3.14 --no-sync python -c "from udv_echo_process import load; \
b = load('<recording>.BDD'); print(b.recording.acquisition_mode, \
[s.acquisition.channel.device_channel for s in b.recording.streams])"

# source side (separate checkout, its own venv)
udv-analysis inspect '<recording>.ADD'   # fails: unit row is not all mm/s
udv-analysis run --config <config>.toml  # works on .BDD
```

## 3. The two pipelines

**Here** — one model, closed steps, provenance as history:

```text
bytes ─io.load()→ SignalData(+SampleSupport, AcquisitionIndex) ─source_artifact()→
ChannelArtifact ─→ Recording ─→ ArtifactBundle(recording, graph)
   └─ select_channel(ChannelKey) → ChannelBundle
        └─ filter / filter_sequence / resample      (ChannelBundle → ChannelBundle)
   └─ synchronize                                   (ArtifactBundle → ArtifactBundle, derive_many)
   └─ store_bundle / load_bundle
terminal (T → U): policy lives in analysis/ — currently echo RPM only
```

**There** — one immutable config, a fixed procedure over arrays:

```text
TOML → AnalysisConfig
load_measurement → Measurement(raw arrays, metadata dict)
valid_depth_mask → apply_tv_filter → detect_state_intervals | single_state_interval
→ extract_profiles → OutputWriter (CSV/NPZ/PNG, summaries, run_manifest v2)
```

### How the models differ, and how each evolves

| | here | there |
|---|---|---|
| Unit of state | `(ChannelArtifact, ArtifactGraph)` / `(Recording, ArtifactGraph)` | `Measurement` in, `ProfileResults` + manifest out; between stages, local arrays |
| What a step is | `bundle -> bundle`, spec-typed, registered by `(kind, schema_version)` | plain function over `ndarray` returning arrays + a diagnostics dict; sequence hard-coded in `pipeline.py` |
| History | provenance DAG (operation nodes + derivation edges); artifacts hold ids, not history | manifest: source hash, config echo, interval/diagnostic dicts; no per-step nodes |
| Identity | content-addressed sha256 for operation and artifact; no wall clock, path or address | source SHA-256 + config fingerprint (config-level, not per-artifact) |
| Missing/invalid data | first-class per cell: `SupportKind` + `valid` + `quality` bitmask; NaN iff invalid | no per-cell concept; ad-hoc bool masks; NaN only as an empty profile envelope |
| Adding a transform | new spec branch + `register_operation` + arrays → `derive()` | edit `analyze_run` or add a stage function |
| Failure policy | invalid states unconstructible; solver failure is an error | solver failure raises; no synthetic coefficients |

The consequence that drives §4: here, "evolving the model" means **appending
operations** to a content-addressed graph; there, it means **editing code** and
tightening config validation. Absorption therefore has to re-express its
algorithms as *our* kinds of thing, not copy its stage shapes.

## 4. Absorption mapping

| Source (there) | Destination (here) | Verdict / shape |
|---|---|---|
| `processing/profiles.py` (239 L) — clamped B-spline quantile LP, TV-smoothed envelopes in mm/s, in-envelope median + **unscaled MAD**, retained counts | **`analysis/`** + a Pydantic result model beside `RpmResult` / `ProfileStatistics` | **Terminal `T -> U`, not a mid-chain transform.** It drops samples and changes counts; keep rejection in terminal retained/input counts and typed statuses, not `SampleSupport` and not a new quality flag |
| `processing/states.py` (237 L) — local-σ texture → depth median → \|Gaussian d/dt\| → Kittler–Illingworth threshold × factor → persistent peaks → half-open intervals; transitions belong to neither neighbour | **`analysis/states.py`** + an interval result model | Terminal product. `SignalData` has no interval concept; making it a mid-chain transform (new payload field + provenance semantics) is the heavier alternative |
| `processing/tv.py::custom_tv_l1` (~60 L of 163) — 2-D primal-dual, **L1** fidelity | new branch in **`process/specs.py`** *if* a gate-coupling filter is accepted | Decision, not a port: our `TvFilterSpec` is 1-D, per-gate, segment/`EDGE_AFFECTED`-aware; a 2-D kernel changes segment, edge and support rules |
| `io/bdd.py::bdd_depth_source="Calc"` gate reconstruction | patch to `io/dop/bdd.py` | Pure win: 0.05 → **0.0033 mm** depth agreement with our `.ADD` reference |
| `io/bdd.py` metadata coverage (~25 named settings, every scalar channel param, BDD comment) | extend `models/channel_config.py` | Missing today: `velo_scale`, `emitNprofile`, `profile_skip`, `medianProfileN`, `movAvgProfileN`, `bandwidth`, profile-filter code, external trigger, and the comment |
| `ARCHITECTURE.md` "Core invariants" (exclusive depth rule; transitions in neither state; unscaled MAD is not uncertainty; quantile fit is per depth, not per gate; solver failure is an error) | `docs/` prose + model validators where enforceable | These are *why* the algorithms are correct — higher value than the code |
| Output contracts (long-form profile CSV schema, NPZ keys, finite-JSON rule, relative paths, versioned schema + legacy reader) | a terminal-result JSON/CSV export following store-1 conventions | Export shape only — not a second manifest or provenance plane |
| Test ideas (TV determinism, constant-field exactness, envelope-failure path, cache-fingerprint invalidation, strict JSON parse) | `tests/` | Plus the anti-lesson in §6.4 |

## 5. Do **not** absorb

Each item below would violate a rule this repo already settled:

- `_vendor/doppy.py` (2255 L) — redundant: our reader is numerically equivalent
  (§2). Keep the `NOTICE` pattern as the precedent for documenting vendoring, not
  the code.
- `models.py` (`Measurement` / `AnalysisResult` dataclasses) — superseded by
  `SignalData` / `ChannelArtifact`; adopting it breaches *Pydantic, not
  dataclasses* (`pipeline-conventions.md` §1).
- `io/add.py` — our parser is strictly better on real files. Absorb one idea:
  its strict units check is what stopped it ingesting amplitude as velocity
  (see the mux entry in `docs/agenda.md`).
- `config.py` + `cli.py` TOML surface (`init-config` / `validate` / `run`) — a
  second config plane duplicating our `Spec` objects, and contrary to
  "no env-driven numerical defaults".
- `outputs.py` manifest v2 + cache fingerprint — a competing provenance/state
  plane; `ArtifactGraph` + store-1 already win (hash verification and id replay
  on load).
- `plotting.py` verbatim — it writes files from inside the pipeline; `viz.py`
  returns figures for marimo. Absorb the intents (raw+filtered sharing one
  colour limit, state-change trace with interval panels, profile groups).
- Deprecation shims (`udv_data_analysis.py`, `run_0500rpm_single_state.py`),
  OpenCV as a hard dependency, and its `.ADD` support claims.

## 6. Gaps this exposes here

1. **Terminal analysis is not yet absorbed.** State detection and robust profiles
   remain in the retiring package; `analysis/rpm.py` covers echo `.ADD` only.
2. **No interval/state metadata** exists in the domain model by design; Phase 2
   therefore needs typed terminal result models rather than new `SignalData`
   fields.
3. **No JSON/CSV/NPZ export path** exists for terminal results (store-1 persists
   signal bundles only).
4. **Fixture blindness remains a general risk.** The mux parser defect was
   invisible before a synthetic test reproduced the real 93-column geometry;
   every absorbed algorithm needs equivalent realistic geometry and archived
   numerical baselines rather than a simplified fixture.

## 7. Sequencing

- **Phase 0 — complete.** The private, checksum-inventoried retirement pack is
  stored outside both repositories under the Hermes artifact area. It preserves
  a reconstructible git bundle/tree, source distributions, licenses, exact
  scripts/configs and five reproducible numerical baselines. The source had no
  accepted non-example config and no multi-state velocity fixture; those are
  recorded blockers, not synthesized evidence.
- **Phase 1 — complete:** calculated canonical BDD depths, high-confidence
  `ChannelConfig` corrections, and content-aware `.ADD`/`.BDD` `udv-inspect`.
- **Phase 2 — active:** typed terminal operating-state and robust-profile
  results/producers are complete and baseline-verified. The small JSON/CSV/NPZ
  export boundary remains.
- **Phase 3 — complete:** the 2-D TV-L1 solver is private to robust-profile
  analysis, with no public `FilterSpec`, support-semantics change, or provenance
  operation. Promotion would require a separate gate-coupling use case and
  contract review.
- **Phase 4 — active/blocked:** update the porting map to distinguish the
  absorbed quantile-envelope implementation from still-unported `PeakDetect`.
  Exact predecessor Mathematica lineage remains unconfirmed (§8).

## 8. Retirement prerequisites

1. Baseline pack (§7 Phase 0).
2. **Predecessor provenance.** The source describes itself as a "validated port
   of an earlier Mathematica workflow" and cites earlier Python
   `QuantileRegression` failures, but neither repo names which notebook or
   script produced its accepted results. Confirm and record it before the
   checkout is gone; without it the absorbed algorithms have no scientific
   ancestry.
3. Confirm nothing else depends on the retiring package (no CI, notebook or
   downstream consumer outside this repo).

## 9. Resolved architectural decisions

| # | Decision | Resolution |
|---|---|---|
| D1 | 2-D TV-L1 (depth × time, L1 fidelity) | Keep the solver private to the terminal robust-profile analysis chain; do not add a public `FilterSpec` branch or redefine bundle-transform support semantics without a separate use case and contract review. |
| D2 | Where profiles and states live | Typed terminal `analysis/` results. Do not add interval fields to `SignalData`. |
| D3 | Whether a config/CLI surface is wanted | No second TOML/config plane and no speculative analysis CLI. Extend the existing inspection CLI by content only; expose analysis through typed library calls/notebooks until a reusable batch need exists. |
| D4 | Where terminal-result JSON/CSV/NPZ is written | A small standalone export module, outside bundle storage and the provenance graph. |
| D5 | Sample rejection representation | Retained/input counts plus typed terminal statuses. Do not add `QualityFlag.EXCLUDED`; the source artifact remains unchanged. |

## Further reading

| Question | Source |
|---|---|
| What is the receiving model's contract? | `docs/signal-model-rework-plan.md` §5–§9 |
| How must a new module be shaped? | `docs/pipeline-conventions.md` |
| Where does a change belong? | `docs/architecture.md` |
| What is written from the Wolfram sources, and what is missing? | `references/wolfram/README.md` |
| What is active right now? | `docs/agenda.md` |
