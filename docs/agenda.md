# Agenda — udv-echo-process

Open ideas, backlog, and deferred questions for this repo, in rough priority
order. This is the *single source of truth for what could be built next* —
feature ideas, porting candidates, integration steps, open decisions. For the
**prioritized fix list** (loose ends + hardening, the "make it solid" work),
see [`hardening-plan.md`](hardening-plan.md); for the detailed marimo
integration steps and evidence, see
[`marimo-integration-plan.md`](marimo-integration-plan.md) /
[`marimo-integration-log.md`](marimo-integration-log.md).

Evidence labels: ✅ observed · 📄 documented · ❓ inferred. Append status
updates; don't rewrite history.

---

## Session status — 2026-09-07 end (handoff snapshot)

**Hardening plan P0 + P1 + P2 (marimo Phase 1) are DONE and committed** on a
clean tree (`master` @ `d1901f3`): `f63684c` P0 · `315d3ee` P1 code ·
`4cb5d15` P0/P1 docs · `8e07ec2` P2 setup · `d1901f3` P2 docs. `34 passed`
with `UV_CACHE_DIR=/tmp/uv-cache MPLBACKEND=Agg`.

**Marimo Phase 2 (first real notebook) landed 2026-09-07:** `notebooks/
echo_explorer.py` — dropdown over `discover_data_files()`, channel
multiselect, heatmap + gate-profile figures via `mo.mpl.interactive`; verified
end-to-end through a live session (all 9 cells idle, 0 errors, reactive
dropdown change re-ran the chain; `marimo check notebooks` exit 0). Details in
`hardening-plan.md` §P2 Phase 2 and `marimo-integration-log.md` Entry
2026-09-07-f.

**P3 (ruff) landed 2026-09-07:** ruff in the dev extra +
`[tool.ruff]` config (exclude `notebooks/`, `.agents/`; `extend-select = ["I"]`),
format sweep + check-clean on `src/` + `tests/`; suite stays 34 passed. The
**hardening plan (P0–P3) and marimo plan Phases 1–2 are now complete**; `.BDD`
+ the DOPpy cross-check move to the development stage (agenda §1).

**Next work for a fresh agent:**
1. Domain backlog below (§1) — `.BDD` (development stage), filtering ports,
   multi-channel RPM, etc.
2. Marimo plan Phase 3 (harness wiring) — default no action.

**Environment caveats for agents on this machine** (see AGENTS.md too):
read-only `~/.local/state/marimo/servers/` → zero-arg marimo discovery finds
nothing; pass `server_url` explicitly per MCP call (auto-bind doesn't persist).
`uv`/`uvx`/deno need `UV_CACHE_DIR=/tmp/uv-cache` (+ `UV_TOOL_DIR`/`DENO_DIR`
under /tmp) — the home caches are read-only in this sandbox. Skills
(`marimo-pair`/`retro-marimo-pair`) are already committed — don't re-add.

---

## 1. UDV domain backlog (the core of this repo)

The signal-processing tooling is the product. This is where new work should
concentrate.

### Parsing & data model

- **`.BDD` (binary) support** — read the full instrument metadata (PRF, burst
  length, TGC, sound speed, Doppler angle, filter settings, trigger state) +
  interleaved velocity+echo profiles that `.ADD` drops. Cherry-pick from the
  sibling `DOPpy` reader rather than vendoring it (NumPy-2 breakage, no
  packaging) — see [`doppy-analysis.md`](doppy-analysis.md) §Relevance.
  Map onto `ChannelFrame`/`ExtractedData`; `printSettings` ≈ `udv-inspect` for
  BDD. Cross-check DOPpy-decoded gate depths / PRF against our `.ADD` values on
  the same recordings.
- **Content sniffing in `extract()`** — ✅ done 2026-09-07 (hardening §P0):
  `extract()` verifies the `ASCUDOPV` magic header and raises a clear
  `ValueError` on non-UDV content; the two misnamed tracked images were
  renamed in place to `300RPM.png` / `300RPM.jpg`.
- **Robust `describe()`** — ✅ done 2026-09-07 (hardening §P0): empty/
  `len(frames) == 0` returns a clear "No frames parsed" description instead of
  raising.

### Filtering & pre-processing (from `references/wolfram/UDV_Data_Analysis_Echo`)

Not yet ported — candidates, each one module under `analysis/`:

- **Total-variation filtering** (`TotalVariationFilter`) — `analysis/tv_filter.py`.
- **Peak detection** (`PeakDetect`) — `analysis/peak_detect.py`.
- **Aliasing removal / velocity unwrapping** — DOPpy's `removeAliasing(jumpSize)`
  is the reference behaviour (❓ destructive, unsafe on noisy data).
- **Quantile regression** (`QuantileRegression.m`) — de-trending / baseline.

### Analysis algorithms (experimental-setup-specific)

- **Multi-channel RPM** — ⚠️ *still open, reframed by P0:* `rpm_from_echo` now
  **asserts single-channel input** (raises on multi-sensor); a genuine
  per-channel estimation + cross-channel agreement pass is the remaining work.
- **Velocity RPM / spectral peak** on `data/4-sensor-velocity/` (the RPM method
  is currently echo-only).
- **Rotating-machinery signal model** — aliasing-unwrapped velocity, per-gate
  Doppler power, blade-pass harmonics.

### Visualization

- **Figure-returning mode** for `plot_recording` / `plot_channel_stats`
  (`return_fig=True`) — ✅ done 2026-09-07 (hardening §P1): all plot functions
  take `return_fig=True` and hand back the open figure; notebooks render via
  `mo.mpl.interactive(fig)`.
- Velocity-field / time-depth contour plots beyond the current heatmap.

### Modular pipeline architecture (rolling-measurement synchronization) — NEW primary direction

The repo should grow from *flat per-file tooling* into a **modular
signal-processing pipeline**: data source → standardize → process → visualize,
each stage a swappable module. Driving use case = the planned **rolling /
sequential multi-sensor pipeline**:

1. **Import + standardize** — ingest a rolling measurement (`.ADD` today,
   `.BDD`/other sources later) into a canonical, time-indexed, per-sensor,
   per-gate layout (pandas `DataFrame` behind a thin Pydantic model).
2. **Time-synchronize** — the instrument samples sensors sequentially
   (round-robin), so channel *k* lags channel 0 by *k·DT*; shift each channel
   back by its offset (`DT`, `2·DT`, … derived from the data, never
   hard-coded) and interpolate every sensor onto one common time grid so all
   sensors read "the same instant".
3. **Visualize** — (a) per-sensor time×gate heatmaps, and (b) **measurement
   lines**: instantaneous cross-sections drawn on the real sensor geometry
   (echo peaks = wall / mixer-pill surfaces along each line).
4. **Spatial interpolation** — *future / out of scope now*: interpolate the
   synchronized, geometry-positioned sensor lines into a 2D field.

Deconstructed into a **layered package** (see
[`pipeline-architecture.md`](pipeline-architecture.md)): `io/` (data-source
layer — `base.py` + `dop/{add,bdd}.py`), `models/` (`raw.py`, `dataset.py`,
`geometry.py`), `process/` (`sync.py`, `pipeline.py`, future `spatial.py`),
`viz/` (`heatmap.py`, `profile.py`, `lines.py`), plus the existing `analysis/`.

**Granularity decisions (settled 2026-09-08):** split into **sub-packages now**
(io / models / process / analysis / viz); within a layer, still one module =
one domain concern, a function = one atomic transform, a pipeline = explicit
ordered composition of named steps. **Canonical storage = one 2D series per
sensor, each with its own timestamps** (`SensorSeries`: `time_s` + `(T,G)`
`values`) — *not* one merged N-D array; merged pandas long/wide frames are
derived views. **pandas** is the dataset backend; **geometry** comes from
explicit `data/<experiment>/layout.toml`; the **`.BDD` binary format** will be
read via the sibling **DOPpy** parser. Still open: stat-vs-raw handling under
sync; DOPpy integration mode (cherry-pick vs dep).

---

## 2. Marimo + agent co-working (next up)

### Phase 1 — pin the provider & repo setup

- ✅ **Done 2026-09-07 (commit `8e07ec2`).** Deps added
  (`marimo[recommended]>=0.24.0,<0.25` + `marimo-inspect` @ git tag
  `v0.2.0`), `uv.lock` committed (+1950 lines), `marimo.example.toml`
  tracked, `.gitignore` covers `.marimo/` + `.claude/`, and the marimo-pair /
  retro-marimo-pair skills are committed (`.agents/` + `skills-lock.json`).
  Original checklist preserved below for reference:
- **Add deps to `pyproject.toml`** — `marimo[recommended]>=0.24.0,<0.25` +
  `marimo-inspect`, with `[tool.uv.sources] marimo-inspect = { git =
  "https://github.com/ajegorovs/marimo-mcp-cowork", tag = "v0.2.0" }`.
  ✅ **The `v0.2.0` tag now exists** (verified 2026-09-07) — the earlier
  "no tag cut yet" caveat is resolved. Commit `uv.lock` (expect a ~250-entry
  re-resolution diff; numpy 2.5.0→2.5.3, matplotlib 3.11.0→3.11.1, …).
- **Re-verify O16 (auto-bind)** after installing v0.2.0: `list_active_notebooks`
  should bind both `session_id` and `server_url`; relax the explicit-`server_url`
  call pattern once confirmed. ✅ Re-verified 2026-09-07 (log Entry
  2026-09-07-e): **does NOT persist across DSH harness tool calls** — keep
  explicit `server_url` per call here.
- **Re-test O17 (list-arg marshalling)** — scalar string tolerated now; a
  stringified multi-value array still needs the DSH harness fix. Filtered
  `get_variables(variable_names=[…])` unproven here. ✅ Re-tested 2026-09-07
  (log Entry 2026-09-07-e): **real list args now work** — filtered reads OK.
- **Re-test O15 (headless discovery)** — headless `--no-token` servers skipped
  the registry in Phase 0; re-confirm what `list_active_notebooks` sees with
  zero args in browser-connected mode (DoD item 1). ✅ Re-tested 2026-09-07
  (log Entry 2026-09-07-e): root cause = **read-only
  `~/.local/state/marimo/servers/` in this sandbox** — marimo 0.24.0 does
  register `--no-token` servers on a writable home.
- **Add the `marimo-pair` agent skills** (`uvx deno -A npm:skills add
  marimo-team/marimo-pair`) and commit `.agents/` + `skills-lock.json`.
  ✅ Done 2026-09-07.

### Phase 2 — first real notebook (building blocks ready, notebook not started)

- `notebooks/echo_explorer.py`: dropdown over `data/*` via `discover_data_files()`
  (✅ promoted to public in P1) + figure-returning mode
  (`plot_recording(..., return_fig=True)`, ✅ landed in P1) so interactive
  cells render inline (`mo.mpl.interactive(fig)`). Remaining work: write the
  notebook + the DoD-1 launch check against a writable-home session.
  ✅ **Done 2026-09-07:** `notebooks/echo_explorer.py` committed. File dropdown
  over all 43 discoverable recordings, channel multiselect (defaults to all),
  `ExtractedData.describe()` summary, heatmap + gate-profile figures. Verified
  end-to-end via a live `/sse`-materialized session: agent loop reads widget
  values and both rendered interactive figures; a `cm.set_ui_value` dropdown
  change re-ran the reactive chain error-free; `uv run marimo check notebooks`
  exits 0 (DoD 1–3). AGENTS.md updated (DoD 4).

### Agent co-work (intended heavy use)

- Prefer the turn-based loop: human edits cells in browser → agent reads/runs/
  edits via the MCP tools (`list_active_notebooks` → `get_cell_map` → `run_cell`
  → `get_variables` → `get_cell_outputs` → `get_errors` → `marimo check`).
- Library code stays in `src/`; notebook cells are thin wrappers (see
  [`AGENTS.md`](../AGENTS.md) §Project purpose).

---

## 3. Scope & structure decisions

- **Remove the stale optical/camera duplicate.** ✅ **Done 2026-09-07**
  (hardening §P1, commit `315d3ee`): `analysis/{mixer,feature_track,
  temporal_projection,image_projection}` + their tests, the `udv-project` /
  `udv-mixvel` CLIs, and the now-unused deps (opencv/Pillow/scikit-image)
  were deleted. The canonical copy stays in `python-image-processing-notebooks`
  — do not port back or re-add optical tooling here.
- **Result-model convention:** ✅ **Done 2026-09-07** (hardening §P1):
  `TemporalProjectionResult` left with the deleted optical modules; `RpmResult`
  migrated to Pydantic `BaseModel`. No dataclasses remain in the package.
- **Ground-up rebuild + CLI policy (draft, 2026-09-08):** the modular-pipeline
  work (§1, [`pipeline-architecture.md`](pipeline-architecture.md)) will be a
  **ground-up rebuild** — the current flat modules are *inspiration* (the
  migration map §12 says *where old things live*), not something whose import
  paths or public names we preserve. **CLI draft rules** (proposal §13): no CLI
  by default; add a console script only when a *full, stable pipeline* exists
  **and** the run is *repeatable/batch*; one CLI per pipeline/driver (never per
  step); `cli.py` stays pure argparse glue with zero signal-processing logic.
  No new CLIs until the rolling-sync `Pipeline` runs end-to-end.
- **Pipeline-element conventions (agreed 2026-09-08):** persisted as the
  authoritative reference in
  [`docs/pipeline-conventions.md`](pipeline-conventions.md) — consult it before
  adding any module. **Pydantic models, not dataclasses.** Models are the
  *nouns* (domain containers, `*Spec` stage params, results, source
  descriptors); **transforms are typed functions** (the verbs); **pipelines are
  ordered compositions**. **Closure rule:** processing steps are
  `Recording -> Recording` (chained and re-appliable — interpolation→
  re-interpolation is just applying the step twice); terminal `Recording -> U`
  stages live in `analysis/` and end a pipeline. **Validation tiers:** full at
  the `io/` boundary, structural (shape/dtype) at stage entry via
  `model_validator`, none in inner loops. Templates + testing rules live in the
  conventions doc; fold into AGENTS.md once `models/`+`process/` land.

---

## 4. Repo hygiene

- **`.gitignore`** — ✅ done 2026-09-07: `.venv/`, `__marimo__/`,
  `*.marimo.session_state`, `marimo.toml`, `.marimo/`, `.claude/` ignored;
  `outputs/` already ignored. Placeholder `marimo.example.toml` tracked (no
  real endpoint/key). (See hardening-plan §repo.)
- **Data hygiene** — ✅ done 2026-09-07: misnamed files renamed in place
  (`300RPM.png`, `300RPM.jpg`) — see hardening-plan §P0.
- **Privacy scan** before any new docs/config commit: this repo is public —
  no absolute `/home/<user>` paths, no tailnet/RFC1918 IPs, no credentials.
  Redactions already applied 2026-09-07-d.

---

## 5. Known open questions (deferred)

- Remote/Tailscale hosting of kernel or MCP server — provider open agenda
  `marimo-inspect/docs/agenda-remote-marimo-mcp.md`, out of scope here.
- Live notebook cell-run smoke tests — blocked on the provider's
  instantiation-token gap; do not promise them here yet.
- **Sibling leak:** `python-image-processing-notebooks` tracks `marimo.toml`
  with a real vLLM base_url — needs its own fix upstream (log F2); out of scope
  for this repo.
- **formatter/linter** — ✅ done 2026-09-07: ruff configured (hardening
  §P3) — `ruff check src tests` / `ruff format src tests`, notebooks
  excluded (validated by `marimo check` instead).
- **`references/wolfram/`** — ✅ done 2026-09-07: `Mixer_velocimetry.nb` and
  `TemporalProjections_v1.1.0.wl` were moved to
  `python-image-processing-notebooks/references/wolfram/` (with a new
  porting-map README) and removed from this repo. Only the UDV-specific
  `UDV_Data_Analysis_Echo.nb/.txt` remain here.

---

## Session status — 2026-09-08: pipeline architecture planning

Planning-only session (no code changes). Captured the **rolling-measurement
synchronization pipeline** as the next primary direction (new §1 domain-backlog
item above) and wrote the modular-layout proposal to
[`pipeline-architecture.md`](pipeline-architecture.md). Decisions settled this
session: **sub-packages now** (io / models / process / analysis / viz) · a
**data-source (IO) layer** keyed on (vendor/device, format) — current source is
the Signal Processing SA **DOP 3010** (`io/dop/{add,bdd}.py`), `.BDD` read via
**DOPpy** · **pandas** backend · explicit `layout.toml` geometry · **per-sensor
2D series with own timestamps** as the canonical store (no single merged array).
Also settled: **ground-up rebuild** (current modules = inspiration; proposal §12
is a "where old things live" map, no import-compat) · a **draft CLI policy**
(§13: no CLI by default; one CLI per stable, repeatable pipeline, never per
step) · **pipeline-element structure rules** (canonical in
`docs/pipeline-conventions.md`: Pydantic-not-dataclass,
`Recording -> Recording` closure for transforms, `*Spec` param models,
T1/T2/T3 validation tiers). Still open: stat-vs-raw under sync, DOPpy
integration mode (cherry-pick vs dep), and the small §12.10 placement choices.
Working tree was clean at `72d45a8` (P3 ruff) before these doc edits.

---

## Session status — 2026-09-08: model convergence + `.BDD` reader (Stage 1–2 landed)

Priority shift (user direction): **visualization is last priority**; **`.ADD` is
treated as superseded by `.BDD`** — the binary format (full instrument metadata,
interleaved profiles, ~3–6× smaller) is the primary data source going forward.

**Model design converged** (discussion; Option B — full new model, not
`ExtractedData`-reuse):
- `MultiplexedMeasurement` = the **box** over an ordered `list[ChannelSeries]`
  — a *view of a rolling/multiplexed file*; single-channel recordings are just
  the box with one element. (Named over `MultiChannel` to avoid implying
  simultaneous acquisition, which newer DOP devices may do.)
- `ChannelSeries` = the atomic single-channel unit: **own real `time_s`**
  (no assumed `k·DT` — DT can fluctuate per measurement; sync later derives
  offsets from actual timestamps), `(T,G)` values, nested `ChannelConfig`.
- `ChannelConfig` = per-channel static op-param metadata (optional, dense
  defaults). **`SourceSpec` kept** (dispatch key). **Geometry deferred** (addon
  used only far downstream; no `layout.toml` work yet).
- Ground-up stance confirmed again; current flat modules are *inspiration* only.

**Landed (58 tests pass, ruff clean):**
- `src/udv_echo_process/models/` — `base.py` (numpy-capable `Model` + `shape_2d`),
  `io.py` (`MeasType`/`SourceFormat`/`SourceSpec`, `frozen` so it keys the
  reader registry), `channel_config.py`, `channel_series.py` (T2 shape/time
  invariant), `measurement.py`.
- `src/udv_echo_process/io/` — `base.py` (`Reader`, `register_reader`, `sniff`,
  `read_path`, `load`) + `io/__init__.py` content-based `discover_data_files()`.
- `src/udv_echo_process/io/dop/bdd.py` — **DOP3000/3010 `.BDD` reader**
  (cherry-picked DOPpy decode rewritten clean: per-channel op blocks at
  548+k·1024, measurement chain from 31268, nested profiles, overflow-corrected
  µs→s time, velocity→mm/s, echo→module-scale, file depth grid → one
  `ChannelSeries`+`ChannelConfig` per channel). **All 22 `data/` fixtures load**
  (20× echo ch4, 2× 4-ch velocity, + a genuine `.BDD` misnamed `.jpg` —
  content sniffing catches it). Values cross-verified vs `doppy-analysis.md`
  (4180×26 echo, 400×55 ×4 ch, velo_max 152.05 mm/s, res 1.091/0.455 mm,
  gate1 20/43 mm).
- `tests/test_models.py` + `tests/test_io_bdd.py`; `process/` skeleton only.

**Next-session direction (candidates — REWRITE from ground up first):** do
not treat the steps below as decided; re-derive them from the two pipeline docs
in a fresh discussion before implementing. Open threads:
- `docs/pipeline-architecture.md` staged rollout §11 (restructure → `sync` →
  `pipeline`+`lines` → `.BDD`/`spatial`) predates the `.BDD`-first reprioritization
  and needs re-planning around the new model (no `Raw`/`dataset.py` split as
  proposed; models now `ChannelSeries`+`MultiplexedMeasurement`).
- Conventions (`docs/pipeline-conventions.md`) assumed `Recording` — now
  `MultiplexedMeasurement`/`ChannelSeries`; sync/pipeline sections need
  re-expression on the new type (closure rule: `ChannelSeries`-level or
  `MultiplexedMeasurement`-level transforms?).
- Where `.ADD` support goes (keep legacy `parser.py` as-is vs migrate to
  `io/dop/add.py`); whether top-level `discover_data_files` flips to the
  content-based `io` version; `MeasType` unify (parser vs models).
- Later-stage candidates kept on the table but uncommitted to: `process/sync.py`
  (+ tests on the two velocity/echo fixtures), `process/pipeline.py`, `viz/`
  (last), `.ADD`-to-`.BDD` cross-validation, DOPpy-independent gate-depth calc.

