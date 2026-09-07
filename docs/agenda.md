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

**Done this session** (details in each section + `hardening-plan.md`):
content guard + misnamed-file renames, empty-data `describe()`, single-channel
rpm + derived `dt_s`, optical-module removal + dep prune, `RpmResult`→Pydantic,
viz `return_fig`, public `discover_data_files`, `__all__` surface audit,
marimo deps pinned, skills committed, O15–O17 re-verified (log Entry
2026-09-07-e).

**Next work for a fresh agent:**
1. **Marimo plan Phase 2** — write `notebooks/echo_explorer.py` (dropdown over
   `discover_data_files()`, `plot_recording(..., return_fig=True)` +
   `mo.mpl.interactive`); verify DoD items (see §2 Phase 2).
2. **P3 ruff** — config + format sweep once notebooks exist (hardening §P3).
3. Domain backlog below (§1) — `.BDD`, filtering ports, multi-channel RPM, etc.

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
- **formatter/linter** — no ruff configured here yet; sibling excludes
  `notebooks/` from ruff. Decide when we add notebooks (hardening-plan §ruff).
- **`references/wolfram/`** — ✅ done 2026-09-07: `Mixer_velocimetry.nb` and
  `TemporalProjections_v1.1.0.wl` were moved to
  `python-image-processing-notebooks/references/wolfram/` (with a new
  porting-map README) and removed from this repo. Only the UDV-specific
  `UDV_Data_Analysis_Echo.nb/.txt` remain here.
