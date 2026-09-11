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

---

## Session status — 2026-09-08 (cont.): pipeline docs Rev 2 — discussion round 1 (capture only)

Docs-only session, no code. Refreshed the two pipeline docs to the landed
Stage 1–2 (commit `f2482f2`) and captured discussion round 1 (deliberately **no
final conventions committed**, no code):

- **`docs/pipeline-architecture.md` → Revision 2.** Records the converged
  model (**`ChannelSeries`** atomic unit + **`MultiplexedMeasurement`** box;
  numpy-in-Pydantic, **no pandas dep**, no `raw.py`/`dataset.py` split — the
  earlier "pandas backend" decision superseded), the landed `io/` layer + `.BDD`
  reader, revised target layout (§6), deconstruction map (§7), walkthrough (§8),
  open decisions (§10) and staged rollout (§11: Stages 1–2 ✅ landed → 3 sync
  ChannelSeries-first → 4 box uplift → 5 capacity-driven legacy migration; viz
  last). §12 migration map kept with a revision note (destinations predate
  convergence; legacy modules stay put).
- **`docs/pipeline-conventions.md` → Revision-2 banner + §10.** Structural
  rules (§§1–3,5,7–8) confirmed by landed code (`models.base.Model`,
  frozen `SourceSpec` registry key, `ChannelSeries` T2 `model_validator`);
  type-level closure rule + §6 templates **pending re-expression** on the new
  types (not authoritative until the sync-design discussion concludes).
- **Agenda §5 kept open;** geometry/`.BDD` threads unchanged.

**Round-1 decisions (capture — re-derive before implementing):**
1. Build sync **bottom-up from `ChannelSeries`**; uplift to
   `MultiplexedMeasurement` steps + `Pipeline` afterwards.
2. **`.ADD`/legacy untouched until the new stack reaches capacity** — old code
   is inspiration only (no `io/dop/add.py`, no MeasType unify, no
   `discover_data_files` flip yet; the parser-vs-models `MeasType` and the two
   `discover_data_files` are recorded as transitional duplications).
3. **stat-vs-raw under sync: deferred** (`.BDD` has no stat/raw split).
4. **Sync grid/alignment strategy: NOT decided — needs an experiment.** Plan: a
   thin marimo preview notebook (library-first) comparing candidate alignment
   implementations + the original 4-sensor signal; sync primitives take
   grid/alignment **as a `Spec`** so the notebook can swap strategies. Discuss
   separately once there is a live preview.

**Next candidates for a fresh agent (re-read both pipeline docs first — they
now carry Rev-2 state):** implement the ChannelSeries-level sync primitives
with grid-as-`Spec` (+ tests on the staggered `data/4-sensor-velocity/*.BDD`
and single-channel `data/echo/*.BDD`) and scaffold the marimo preview notebook
for the grid experiment; then box-level uplift + `process/pipeline.py`.

---

## Session status — 2026-09-08 (cont.): signal-preview notebook + TraceScrubber widget

Interactive co-work session on the **new `.BDD` stack**; no `src/` code changes
yet (prototype/exploration only, as planned in §1). Committed together with the
pipeline-docs Rev 2 work above.

**Landed in this repo:**
- `plotly>=5.24` added as a runtime dep (plotly 7.0.0) for interactive figures.
- `notebooks/channel_preview.py` — single-channel signal preview on the new
  `io/`+`models/` stack: `.BDD` dropdown (`io.discover_data_files`, content-
  sniffed) → channel → textual stats + raw time×gate heatmap (downsampled to
  ≤800 rows) → **time-step scrub** of the gate profile. All 10 cells idle, 0
  errors, `marimo check` clean (live-verified end-to-end; reactive chain tested
  via slider/state pushes).
- **Y-axis decisions (settled through live iteration):** per-gate time
  statistics are *not* shown — the echo is a travelling wave (peak sweeping
  across gates), so time-averaging mixes phases and is meaningless. The scrub
  axis shows **raw values pinned to an explicit (min, max)** — never a [0,1]
  transform: echo `(0, 2000)` (a-priori module range); velocity `(channel-wide
  data min, max)` (arbitrary per rig; fixed so frames don't rescale while
  scrubbing). Range is displayed in the widget title.
- Signal observations for later: default `data/4-sensor-velocity/200RPM.BDD`
  ch6 velocity has median dt 25.4 ms but max gap 372.7 ms; velocity min/max
  −54.6/245.9 mm/s **exceeds the ±152 mm/s `velo_max` Nyquist** (aliasing /
  decode nuance to investigate during sync work). Echo fixtures run 0→2000
  module scale, gates 43→54.4 mm.

**Widget (sibling `marimo-inspect`, per user preference — editable-installed):**
`TraceScrubber` anywidget (custom, `ImagePreview` pattern): one self-contained
component = canvas line chart of the profile at step `i` + slider + ◀ ▶ +
`±1%`/`±10%` jump buttons; all scrubbing redraws in JS (no kernel per step);
optional fixed y-range; synced `index` trait for `mo.state` bridging.
Files: `src/marimo_inspection/widgets/{trace_scrubber.py, js/trace_scrubber.js}`
+ exports in both `__init__.py`s (committed in the sibling repo).
- **Environment caveat (important for fresh agents):** editable install of
  `marimo-inspect` is **session-fragile** — `uv run`'s implicit sync reverts it
  to the pinned git tag `v0.2.0` (which has **no** widgets). Start the marimo
  server / run python with `uv run --no-sync` after
  `uv pip install -e ~/Repos/marimo-inspect`, or the `TraceScrubber` import
  breaks. Consider promoting the widget to a tagged release later so consumers
  install it normally.

**Next candidates (unchanged priorities, now with a working preview vehicle):**
re-run the §15.2 sync grid/alignment **experiment** — the notebook preview
(scrub over real profiles) is the signal-understanding tool for judging
alignment strategies; then ChannelSeries sync primitives (grid-as-`Spec`) +
`.BDD`-first tests; box-level uplift; legacy migration at capacity.

---

## Session status — 2026-09-09: interpolation & resampling grounding (capture only)

Docs/discussion-only session, no code. Persisted the grounding for the
`process/sync.py` interpolation stage in a new
[`docs/interpolation-design.md`](interpolation-design.md) (companion to the
two pipeline docs + `docs/dop3000/measurements-and-recordings.md`). Verified
fixture facts: `data/4-sensor-velocity/200RPM.BDD` = 100 rounds × 4 channels
× **4 profiles/visit**, intra-visit cadence 25.4 ms, revisit ~448 ms,
per-round stagger ch7/8/9 ≈ +112/+224/+336 ms **stable across all 100 rounds**
(σ ≤ 1.6 ms, no drift); single-channel `data/echo/650.BDD` = uniform 3.2 ms.
Settled direction: the sync task = per-sensor series across all blocks (what
`ChannelSeries` already is) → **interpolate via a swappable interpolation
layer/module** producing a pre-calculated model (parameters + argument
bounds), sampled downstream at arbitrary times; re-interpolation only for
notebook quality assessment and sensor re-alignment (bounds = time-overlap
extremes). Common-grid questions fall away under this framing. Open for the
next discussion: the interpolation layer design itself (scipy dependency
decision, model shape, per-gate handling, tests). Corrections recorded in the
note: "never bridge inter-visit gaps" withdrawn as the default (bridging is
the reconstruction intent); hole-marking kept as an option for
frequency-domain consumers; alignment stage must avoid the ~448 ms
one-round ambiguity of whole-series lag cross-correlation.

---

## Session status — 2026-09-09 (cont.): interpolation-layer friction review → **CHECKPOINT, restart fresh**

Second 2026-09-09 session, capture only, no code. User reviewed the grounded
design (`docs/interpolation-design.md`) and asked three structural questions;
answers + empirical probes persisted as **§6 (checkpoint)** of that note.
Highlights:
- Scope confirmed: interpolation on `ChannelSeries` only;
  `MultiplexedMeasurement` later.
- numpy validation via `@model_validator` is fine (already the landed
  pattern) — the friction is elsewhere: ndarray fields **break model `==`**
  (raises `ValueError`; tests must use `np.allclose`) and **are shared on
  shallow `model_copy()`** (deep-copy discipline needed on transforms).
- Storing a **live scipy interpolant in a Pydantic model: rejected**
  (untyped/heterogeneous across methods, mutable, non-serializable,
  behaviour-in-data). Direction: **recipe model** (method enum + params +
  argument bounds), scipy materialized lazily at the sampling call site.
  Full-OOP conversion rejected (loses validation/coercion/serialization the
  repo deliberately bought); a small scoped behaviour class inside
  `process/` remains allowed (conventions §6.2).
- User takes a review round; **work restarts in a fresh session.**

**Next session (fresh context):** open `docs/interpolation-design.md` — read
§1–5 then §6 (checkpoint, incl. §6.5 restart reading order) — and reopen the
interpolation-layer brainstorm (**issue b**), starting from §6.4 open
question 1 (recipe-as-field on `ChannelSeries` vs pure-data series + separate
recipe + `sample(recipe, times) -> ChannelSeries`; author lean: pure data).
Keep it discussion/capture until decisions land; no code, no new deps (scipy
decision = open question 5). Tree at checkpoint: `docs/agenda.md` modified +
`docs/interpolation-design.md` new; everything else clean.

---

## Session status — 2026-09-09 (cont.): interpolation brainstorm concluded → implementation-ready

Review round over `docs/interpolation-design.md` (goal / limitation / current
ideas) plus the implementation brainstorm. **Decisions landed** (persisted as
that doc's new §7; no code written this session):
- **API = closed transform** `resample(series, spec, *, times | dt_s) ->
  ChannelSeries` (conventions closure rule); two-phase fit/sample deferred until
  a real consumer needs pre-fit.
- **Recipe = `InterpSpec`** in `process/` (not `models/`); recipe-as-field
  dropped; no knots copied; method as a constrained `Enum`.
- **scipy adopted as a runtime dep** (future filtering / spectral / unwrapping
  work will need it); wiring into `pyproject.toml` / `uv.lock` is left to the
  implementation session.
- **Method regimes:** `LINEAR` default (no-overshoot across the ~372 ms /
  14.6-step inter-visit gap), `MONOTONE` / `CUBIC` / `BSPLINE` where smoothness
  is safe; interpolation is per-gate 1-D (vectorized along axis 0).
- **`InterpSpec` fields:** method + explicit `extrapolation`
  (`error | nan | nearest`) + `nan_policy` + per-method params; output carries
  `channel`/`config`, input unmutated; hole-marking seam deferred.
- **Tests:** knot round-trip, overshoot guard, uniform-echo idempotency,
  extrapolation / NaN behaviour, non-mutation — via `np.allclose`.

**Next session = implementation (Stage 3):** wire scipy into the deps, then land
`process/sync.py` (`InterpSpec` + `resample()`) + tests on
`data/4-sensor-velocity/*.BDD` (staggered) and `data/echo/*.BDD` (uniform), per
`docs/interpolation-design.md` §7.

---

## Session status — 2026-09-09 (cont.): Stage 3 implementation session — scope confirmed

Implementation session opens. Docs checkpoint committed (`2ce6671`); the
settled design (§7) plus the implementation-level clarifications agreed in
discussion are now captured as `docs/interpolation-design.md` **§8** (this
session, before code). Scope confirmations, all within §7's "implementation
may refine" latitude:

- **Exactly one grid arg** (`times` xor `dt_s`); `times` strictly increasing +
  finite (never silently sorted).
- **Duplicate source knots: uniform strict rule** — DOP never emits repeated
  timestamps (all fixtures strictly increasing), so `resample` requires
  strictly-increasing `time_s` for *every* method; duplicate-tolerant handling
  for non-DOP devices = future note, not built.
- **`dt_s` grid = inclusive `[time_s[0], time_s[-1]]`** (short final interval),
  `dt_s <= 0` or `> span` errors.
- **Per-method params bundled** as nested `InterpSpec.params: InterpParams`
  (`spline_order: int = 3`, BSPLINE-owned); data-count constraints validated at
  apply time; discriminated per-method spec union deferred until a 2nd
  parameterized method exists.
- **Extrapolation per-sample rows** (error / nan / nearest), never silent
  clamp; **NaN policy**: non-finite times always error, `error` default,
  `propagate` LINEAR-only with clear spline error.
- **Exports:** `process/__init__.py` + package top level.

Next step: wire scipy (`pyproject.toml` + `uv.lock`), land `process/sync.py`
per §7/§8, then the test set on `data/echo/650.BDD` + `data/4-sensor-velocity/
200RPM.BDD` and synthetic tiny arrays.

---

## Session status — 2026-09-09 (cont.): Stage 3 interpolation **implemented**

The Stage 3 interpolation layer landed. **scipy 1.18.1** is a runtime dep
(wired into `pyproject.toml` + `uv.lock`, cp314 wheel verified on Python
3.14.7). `src/udv_echo_process/process/sync.py` now holds:

- `InterpMethod` (str-`Enum`: LINEAR default → MONOTONE → CUBIC/BSPLINE),
  `InterpParams` (nested per-method params, `spline_order` default 3,
  BSPLINE-owned), `InterpSpec` (method + `extrapolation`
  `error|nan|nearest` + `nan_policy` `error|propagate` + params), and the
  closed transform `resample(series, spec, *, times | dt_s) -> ChannelSeries`
  — all per `docs/interpolation-design.md` §7/§8, including: exactly-one
  grid arg; strictly-increasing finite times/knots (uniform dup rule);
  inclusive `dt_s` span with shortened final interval; apply-time spline
  capacity checks; per-sample extrapolation rows; NaN pre-scan with
  propagate=LINEAR-only; never a silent endpoint clamp; input unmutated,
  `channel`/`config`/gates carried through.
- Exports from `process/__init__.py` **and** the package top level.

Tests: `tests/test_process_sync.py` — 45 tests on synthetic tiny arrays +
`data/echo/650.BDD` (uniform: knot round-trip all 4 methods, idempotent
re-resample) + `data/4-sensor-velocity/200RPM.BDD` (gappy/staggered: knot
round-trip, LINEAR no-overshoot across the ~370 ms gaps, monotone stays in
envelope, cubic overshoot on a step documented as regime honesty),
extrapolation ×3 policies, NaN policy, grid semantics, purity. Full suite:
**103 passed** (58 prior + 45), ruff check + format clean.

**Where this leaves the sync task:** per-sensor interpolation is done; the
next sync stages are the ones §3/§7 deliberately deferred — grid/alignment
strategy on `MultiplexedMeasurement` (match per-round reference times, avoid
the ~448 ms one-round cross-correlation ambiguity), the hole-marking seam
once a frequency-domain consumer appears, and re-expressing the
pre-convergence templates of `pipeline-conventions.md` §§2/4/6 on
`ChannelSeries`/`MultiplexedMeasurement` types.

---

## Session status — 2026-09-09 (cont.): channel_preview restructure → MCP experience report filed

Live notebook `notebooks/channel_preview.py` reshaped into the agreed 4-group
flow and committed: `16cdf4e` (extrapolation-testing controls) → `b4073f8`
(controls render via a final-expression `mo.vstack`) → `6bc96c4` (heatmap
x=time/y=gate; own gate dropdown for the trace) → `5be0b0f` (measured-only
heatmap moved into the Overview slot) → `16e9010` (merge channel info +
heatmap into one cell). Structure now: import pickers → channel info +
measured heatmap → time-step scrubber → interpolation preview (controls → run
note → gate dropdown → per-gate trace). Kernel still live on :2718
(session `s_jb93sf`), 0 errors, `marimo check` green, tree clean.

**New — marimo-inspect MCP experience report (open for review).** Per user
request, filed a consumer "what using it felt like" report in the sibling repo:
`~/Repos/marimo-inspect/docs/session-report-deepseek-harness-2026-09-09.md`
(tool-by-tool verdicts, frictions F1–F9, improvement backlog P1–P5, guide
gap). Provider-side review pointer added there as
`agenda-udv-consumer-findings.md` **T7**; evidence logged here as
`docs/marimo-integration-log.md` **O28–O32**.

**Next session:** review the report (marimo agent rules: final-expression
display, creator-can't-read-own-`.value`, list-form `set_ui_value`, UI-handler
error channel; decide `execute`/`set_ui_value` MCP tools vs documented `cm`
guidance) — and fold the durable rules into this repo's `AGENTS.md` Marimo
section where missing.

---

## Session status — 2026-09-09 (cont.): per-gate filter review → sequence-platform plan (handoff)

Review-only session, no `src/` changes. Reviewed the filter handoff
([`docs/filter-design.md`](filter-design.md)) and re-planned the layer as a
**sequence-capable** smoothing/outlier platform. Findings + decisions + target
module snippet persisted as that doc's new **§7** and committed (`c7e106b`);
**implementation is the handoff** to a follow-up agent (same machine — no
push).

**Verified findings (§7.1):** `weight` is data-scale dependent (same
`weight=1.0` → 0.45% change on echo std 298 vs 3.8% on velocity std 23); TV
is not idempotent (2nd-pass max-Δ 0.066, decaying); scikit-image pulls
imageio/networkx/tifffile/lazy_loader; Wolfram's `TotalVariationFilter` is a
**2-D image** filter with a `Method -> Laplacian|Poisson` noise model that
skimage's ROF cannot express — the per-gate-1-D choice is a deliberate
divergence, not an approximation. Aliasing is present in the velocity fixture
but **out of scope**.

**Settled decisions (§7.2, user):**
1. Purpose = **pre-interpolation smoothing + outlier removal** (not aliasing —
   recording params minimise that). Order: average/remove-outliers **before**
   `resample`, on the raw gappy series.
2. **Keep scikit-image** (no thin-repo mandate; the §5.1 framing is withdrawn).
3. **Native sequence support, simple** — a fold, not a `Pipeline`.

**Target shape (§7.3–7.4):** `FilterMethod` (MEDIAN/MEAN/SAVGOL on scipy +
TV on skimage) · bundled `FilterParams` · `FilterSpec` · `filter()` (rename of
`denoise`) · `filter_sequence()` (fold) — mirroring `sync.py`. Cadence rule:
index-window filters are fine on the gappy series; TV requires uniform cadence
(post-`resample`, or rejected). Implementation checklist in §7.5.

**Next session (fresh agent):** implement `process/filter.py` to
`docs/filter-design.md` §7.4, update exports (`process/__init__.py` + top
level, drop `denoise`), extend `tests/test_process_filter.py` (per §7.5), keep
scikit-image, and log the landing here.

---

## Session status — 2026-09-09 (cont.): filter sequence platform **implemented** (handoff picked up)

The §7 handoff was implemented (same machine, follow-up agent): the
TV-only `denoise` layer became the sequence-capable filter platform per
`docs/filter-design.md` §7.3–7.5. `src/udv_echo_process/process/filter.py` now
holds `FilterMethod` (MEDIAN / MEAN / SAVGOL on scipy, TV on skimage) ·
`FilterParams` (window / polyorder / weight / iterations, bundled per the
`InterpParams` pattern) · `FilterSpec` (method + params, default MEDIAN) ·
`filter()` (closed `ChannelSeries -> ChannelSeries`, the `denoise` rename) ·
`filter_sequence()` (plain fold). Cadence rule per method: index-window
methods run on the raw gappy series; TV requires (near-)uniform cadence and
is rejected otherwise. Exports updated in `process/__init__.py` + the top
level (added `FilterParams` / `filter` / `filter_sequence`; dropped
`denoise`); `references/wolfram/README.md` port row renamed to match. No
notebook imports the filter layer yet.

**Tests: 27 in `tests/test_process_filter.py`** (was 13) — old TV behaviour
retained against the new spec shape (noise cut / edge kept, weight monotonic,
gate independence, purity verbatim, re-appliability); new: per-method
behaviour (MEDIAN spike removal, MEAN noise averaging, SAVGOL smooth-vs-
stair-step), spec validation (`window >= 1`, `polyorder >= 0`, `weight > 0`,
`iterations >= 1`, SAVGOL `window > polyorder` **and odd** at apply time),
fold identity + order-matters for `filter_sequence`, cadence rule on both
fixtures (TV rejected raw-gappy, accepted uniform echo + post-`resample`),
and the settled pipeline order `filter_sequence(raw, [MEDIAN]) → resample` on
`200RPM.BDD`. Full suite **130 passed**, ruff check + format clean.

**Deviations found at implementation (logged in filter-design.md §7.4):**
1. `scipy.ndimage` has **no `median_filter1d`** — MEDIAN uses
   `median_filter(..., axes=0)` (verified element-equal to per-gate 1-D).
2. The "echo fixture is exactly 3.2 ms uniform" claim was **wrong**: 833 of
   4629 intervals are 3.1 ms (periodic ~3% timebase jitter). `_is_uniform`
   now tolerates `rtol=0.05` over **interior** intervals (final interval
   excluded — `resample`'s inclusive `dt_s` grid ends shortened); the gappy
   velocity fixture still fails it by ~2 orders of magnitude.

**Where the sync task stands:** Stage 3 interpolation (`process/sync.py`)
and this filter layer are both landed; remaining sync work is unchanged —
`MultiplexedMeasurement`-level grid/alignment strategy, hole-marking seam
for a frequency-domain consumer, and re-expressing the pre-convergence
`pipeline-conventions.md` templates on the landed types.

## Session status — 2026-09-10: retire repo-wide marimo skills in favor of MCP authority

Decision under consideration: remove the manually installed
`marimo-pair`/`retro-marimo-pair` skills from this repository rather than make
them part of the fresh-user experience. The custom `marimo-inspect` MCP and
its packaged resources should be the single operational authority, avoiding
drift between official marimo skills and this provider's custom tool surface.

**Consumer onboarding agenda — prerequisite:**

Before this repository adopts installation guidance or retires the skills, the
provider must establish a supported distribution route and graduate its
harness-integration guide from draft to authoritative, tested documentation.
Today the package-index route is unverified; use the provider's documented git
or local-editable routes only until that changes.

**Consumer onboarding agenda — development mode:**

1. Keep `marimo-inspect` as a sibling checkout, not nested inside this repo:
   ```text
   ~/Repos/marimo-inspect
   ~/Repos/udv-echo-process
   ```
2. Clone the provider separately, then add it to this project as an editable
   dependency with uv (`uv add --editable /path/to/marimo-inspect`).
3. Install/run the provider's editable environment and point the agent harness
   at the sibling checkout's `.venv/bin/marimo-inspect` using stdio, rather than
   `uv run` or a source path inside the consumer repository.
4. Once the provider guidance is authoritative, add the corresponding
   per-harness MCP entry. For Hermes, the verified shape is an
   `mcp_servers.marimo-inspect` entry with
   `command: <sibling>/.venv/bin/marimo-inspect`, args
   `["--transport", "stdio"]`, and an explicit timeout. Use a distinct
   harness server name/key when multiple provider instances are present.
5. Read the provider's MCP resources after connection; use them as the
   workflow/safety/fallback authority. Do not install repo-local marimo skills.

**Consumer onboarding agenda — end-user mode:**

1. Decide whether the current regular notebook/MCP dependencies should move to
   a dedicated optional extra. No `marimo` extra exists today; do not document
   `uv sync --extra marimo` until the extra exists and is tested.
2. After the provider has a supported distribution route, define the normal
   install command around that route. It must install a compatible marimo pin
   and `marimo-inspect` without requiring a sibling clone or editable install.
3. Point the user's MCP harness at the installed console script
   (`<environment>/.venv/bin/marimo-inspect`, or the platform-equivalent
   executable) with `--transport stdio`; do not point it at repository source.
4. Document the harness configuration using the provider's authoritative
   integration guide, while keeping this repo's instructions limited to
   installation, selecting the installed executable, enabling the MCP, and
   reading its packaged resources. State clearly that resources/tools are
   unavailable until the MCP is installed and enabled.
5. Keep the MCP's supported marimo version range aligned with the provider;
   consumers must not widen the marimo pin without the provider's live-suite
   validation.

**Scope:** agenda/documentation only for now. Do not remove the skills, alter
`pyproject.toml`, change harness configuration, or implement provider fixes in
this item. Before retirement, verify that the README/AGENTS onboarding text
covers the supported installation route and the documented fallback boundaries
(screenshots, server/kernel lifecycle, and arbitrary CodeMode probes).

---

## Session status — 2026-09-11: marimo-inspect upstream fixes — agenda reconciliation

Docs-only session, no code. The sibling provider landed its post-hunt fix set
(hunt #1 closed with all 11 findings resolved, the udv consumer agenda closed
`T3`/`T14`) and released **v0.3.1 → v0.3.3**. This entry re-reads the agenda
above against that state; the older items are left in place (append-only) — the
corrections are here.

**Closed by the provider (📄 provider git log/docs; consumer-unverified):**

- **§2 O17 (list-arg marshalling) — closed.** Real list args work; the provider
  closed its `T3` as non-reproducing (the defensive types were already in
  `v0.2.0`).
- **§2 O16 (auto-bind persistence) — fixed upstream; no longer a consumer
  action.** The "does not persist across harness tool calls → keep explicit
  `server_url` per call" line above describes the pre-fix provider. Binding is
  now MCP-session state with a process-global fallback, and
  `session_id`/`server_url` are **omittable over stdio for every client**; over
  HTTP/SSE they are omittable only while a single client session is on the
  process, otherwise the call is refused `binding_ambiguous` and is never handed
  another client's notebook. **Caveat (❓):** the provider's own consumer-level
  check round (`docs/agenda-verification-round.md`, `T-V1`) is still open, so
  treat this as fixed-but-unverified **from this repo** — and restart the
  harness's MCP process before any check, since payloads, docstrings and
  resources are served by the process started at launch.

**Unchanged — do not close:**

- **§2 O15 (zero-arg headless discovery)** — environment, not provider: the
  read-only `~/.local/state/marimo/servers/` here yields an empty registry. Keep
  passing `server_url` explicitly in this environment.
- **§5 live notebook cell-run smoke tests** — the token-gated
  `/api/kernel/instantiate` gap is closed only inside the provider's own live
  suite (redesign resolved 2026-09-06; 19 live tests green); a `--no-token`
  consumer session still cannot be instantiated. Do not promise these here yet.

**Consumer-side work still owed (not closed by the upstream fixes):**

- **`AGENTS.md` Marimo section** — the 2026-09-09 follow-up is half done: the
  provider half is closed (`agenda-udv-consumer-findings.md` = closed), but the
  five behaviours that changed shape on 2026-09-11 are not yet folded in:
  `get_cell_map` no longer arms `edit_cell` (a first edit owes a
  `get_cell_data`); `get_dependency_graph` refuses `cell_id`/`depth` instead of
  ignoring them; read tools report `missing_cell_ids` instead of an empty happy
  path; `get_errors` flags a cell only on real exception evidence.
- **§2026-09-10 onboarding block** — its own stated prerequisite is now largely
  met (tagged releases + an authoritative provider harness-integration guide and
  the git-tag install route). Two corrections to that block: (a) the line
  "No `marimo` extra exists today; do not document `uv sync --extra marimo`" is
  now false — the `marimo` extra exists and is documented in
  `AGENTS.md`/`README.md`; (b) the package-index route is **still** unsupported,
  so keep documenting git-tag/local routes only. Retiring the
  `marimo-pair`/`retro-marimo-pair` skills remains open.
- **Pin bump (concrete follow-up; not previously an agenda item)** — the
  `marimo` extra pins `marimo-inspect` at tag **`v0.3.0`**
  (`pyproject.toml` `[tool.uv.sources]`) while the provider is at **`v0.3.3`**,
  so none of the hunt #1 fixes (binding scope, read baseline, payload
  truthfulness, `get_errors` evidence) nor the `T13` widget residual is in this
  install. Bumping the tag is a code change (`pyproject.toml` + `uv.lock` +
  notebook re-check), deliberately not part of this doc session.

Working tree clean at `114c358` before this entry.

---

## Session status — 2026-09-11 (cont.): T-V1 consumer run + pin drift confirmed

Execution session for the two follow-ups listed above. Live verification +
docs only; no `src/` changes.

**T-V1 round run from the consumer — all checks PASS (evidence:
`marimo-integration-log.md` O35–O38).** Against provider **v0.3.3** on a live
marimo 0.24.0 session (a copy of `notebooks/channel_preview.py`), driven through
this harness's MCP tools **and** through `fastmcp`/`mcp`-SDK clients (stdio + an
`--transport http` instance): binding over stdio (including the
session-per-request client shape, i.e. the process-global fallback) and the
HTTP `binding_ambiguous` refusal that fails closed; `needs_read` after a
preview-only read and success after `get_cell_data`; `missing_cell_ids` for both
read tools; `get_dependency_graph` argument refusals + `cell_name` agreement;
the `set_ui_value` shape / apply-and-verify / T13-repeat cases; the `get_errors`
console split; `get_variables` scaffolding exclusion. The doc-vs-surface sweep
found **no contradiction** — no resource still offers `get_cell_map` as a
read/recovery step. One nit filed in the log (O37): `get_errors`' top-level
`console_exception_evidence` / `console_stderr` stay `null` while the values sit
on `cells[]`.

Two corrections to the entry above: **§2 O16 is now verified from the consumer**
(not just "fixed upstream"), with the HTTP nuance that a session-per-request
client is refused *there* by design and must pass both arguments explicitly; and
the provider's own T-V1 boxes remain **unticked** deliberately — that round
requires a fresh zero-context agent, which this run was not.

**Pin drift is the remaining consumer action (O38).** The `marimo` extra pins
`marimo-inspect` at tag **`v0.3.0`** (`pyproject.toml` `[tool.uv.sources]`) while
the verified provider is **`v0.3.3`**, and `.venv` today is a
v0.3.0-metadata + sibling-source editable hybrid — so a plain
`uv sync --extra marimo` would install the pre-fix package. The bump
(`v0.3.3` tag + relock + re-sync + notebook re-check) is a code change and is
delegated, not part of this doc session. **Landed the same session:** the tag
now reads `v0.3.3`; `uv lock` + `uv sync --extra marimo --extra dev` installed
`marimo-inspect 0.3.3` from the tag (`d0d6736`) out of `.venv/…/site-packages`
— replacing the sibling editable hybrid — with `TraceScrubber` resolving,
**130 passed**, `marimo check notebooks` exit 0, and no other lock entry
changed. All four modified files remain **uncommitted** (`docs/agenda.md`,
`docs/marimo-integration-log.md`, `pyproject.toml`, `uv.lock`).

---

## Session status — 2026-09-11 (cont.): wrap-up — outstanding items only

Session closed. What is *done* is recorded above; this is the live open list, so
a fresh agent can pick any of it up without re-deriving the context.

1. **Provider `T-V2` — filed, open (doc precision).** `get_errors` carries its
   evidence marker + stderr events per cell while the surfaces (`errors.py` tool
   description, the provider's own `T-V1` §6 check line) don't say so. Filed in
   `~/Repos/marimo-inspect/docs/agenda-verification-round.md` §T-V2 with an
   evidence block and repro (severity *cosmetic*). No provider release carries
   the fix yet; when one does, the consumer-side re-check is just the O37
   assertion again — no code changes here.
2. **Provider `T-V1` — open (zero-context check round).** The consumer run
   (O35–O36) passed every check but deliberately did not tick the provider's
   boxes, since the method requires a fresh, zero-context agent. Until that run
   happens, "verified from the consumer" rests on this repo's evidence log.
3. **Pin re-bump trigger.** `pyproject.toml` now pins `v0.3.3`. When the provider
   cuts a release carrying the `T-V2` fix (or `T-V1` closes with findings), bump
   the tag again and repeat the O38 verification (`uv lock` + `uv sync --extra
   marimo --extra dev`; installed version + import path out of
   `.venv/…/site-packages`; `TraceScrubber`; `pytest`; `marimo check`).
4. **Undecided: commit the consumer-side check harness?** The T-V1 run needed a
   throwaway harness (headless server boot + `/sse` session materialization +
   `fastmcp` drive, recipe in the log entry above) and it lived in `/tmp`. If
   provider releases are to be re-checked from here regularly, it should live in
   the repo instead of being rewritten each time; deliberately not built yet
   (no tooling before a repeated need).
5. **Dev-mode note.** `.venv` now installs the tagged release, so testing
   *unreleased* provider changes again needs the temporary editable override
   (`uv add --editable ~/Repos/marimo-inspect`), whose session fragility
   (`uv run`'s implicit sync reverting it) is recorded in the 2026-09-08
   notebook entry.
6. **Working tree: committed and pushed.** `f5d1188` = `docs/agenda.md` +
   `docs/marimo-integration-log.md` (this session's record), `9f2409f` =
   `pyproject.toml` + `uv.lock` (the pin bump). Push published
   `bcb23a7..9f2409f` on `origin/master` — 39 commits, i.e. the 37 commits this
   branch had accumulated locally went up with them (this repo's
   `master` had been ahead of `origin/master` for a while; the previous
   convention of keeping handoffs local no longer applies as of this push).
