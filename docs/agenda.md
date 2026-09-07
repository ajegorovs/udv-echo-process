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
- **Content sniffing in `extract()`** — two tracked "data" files are actually
  images (`data/echo-4-sensors-2x2/300RPM.BDD` = PNG, `300RPM_Stat.ADD` = JPEG);
  `extract()` currently has no magic/extension guard (see hardening-plan §parser).
- **Robust `describe()`** — handle the empty/`len(frames) == 0` case instead of
  degrading; surface per-channel measurement type when mixed.

### Filtering & pre-processing (from `references/wolfram/UDV_Data_Analysis_Echo`)

Not yet ported — candidates, each one module under `analysis/`:

- **Total-variation filtering** (`TotalVariationFilter`) — `analysis/tv_filter.py`.
- **Peak detection** (`PeakDetect`) — `analysis/peak_detect.py`.
- **Aliasing removal / velocity unwrapping** — DOPpy's `removeAliasing(jumpSize)`
  is the reference behaviour (❓ destructive, unsafe on noisy data).
- **Quantile regression** (`QuantileRegression.m`) — de-trending / baseline.

### Analysis algorithms (experimental-setup-specific)

- **Multi-channel RPM** — current `rpm_from_echo` mixes all channels into one
  spectrum; add per-channel estimation + cross-channel agreement (see
  hardening-plan §correctness).
- **Velocity RPM / spectral peak** on `data/4-sensor-velocity/` (the RPM method
  is currently echo-only).
- **Rotating-machinery signal model** — aliasing-unwrapped velocity, per-gate
  Doppler power, blade-pass harmonics.

### Visualization

- **Figure-returning mode** for `plot_recording` / `plot_channel_stats`
  (`return_fig=True`) so interactive marimo cells don't write a PNG per tick;
  render via `mo.mpl.interactive(fig)` (marimo 0.24.0 exposes only
  `mo.mpl.interactive`).
- Velocity-field / time-depth contour plots beyond the current heatmap.

---

## 2. Marimo + agent co-working (next up)

### Phase 1 — pin the provider & repo setup

- **Add deps to `pyproject.toml`** — `marimo[recommended]>=0.24.0,<0.25` +
  `marimo-inspect`, with `[tool.uv.sources] marimo-inspect = { git =
  "https://github.com/ajegorovs/marimo-mcp-cowork", tag = "v0.2.0" }`.
  ✅ **The `v0.2.0` tag now exists** (verified 2026-09-07) — the earlier
  "no tag cut yet" caveat is resolved. Commit `uv.lock` (expect a ~250-entry
  re-resolution diff; numpy 2.5.0→2.5.3, matplotlib 3.11.0→3.11.1, …).
- **Re-verify O16 (auto-bind)** after installing v0.2.0: `list_active_notebooks`
  should bind both `session_id` and `server_url`; relax the explicit-`server_url`
  call pattern once confirmed.
- **Re-test O17 (list-arg marshalling)** — scalar string tolerated now; a
  stringified multi-value array still needs the DSH harness fix. Filtered
  `get_variables(variable_names=[…])` unproven here.
- **Re-test O15 (headless discovery)** — headless `--no-token` servers skipped
  the registry in Phase 0; re-confirm what `list_active_notebooks` sees with
  zero args in browser-connected mode (DoD item 1).
- **Add the `marimo-pair` agent skills** (`uvx deno -A npm:skills add
  marimo-team/marimo-pair`) and commit `.agents/` + `skills-lock.json`.

### Phase 2 — first real notebook (not started)

- `notebooks/echo_explorer.py`: dropdown over `data/*` via a *public*
  `discover_data_files()` (currently private `_discover_data_files()` in
  `viz.py` — promote it).
- **Viz gap:** figure-returning mode (see §1 Visualization) so interactive
  cells render inline.

### Agent co-work (intended heavy use)

- Prefer the turn-based loop: human edits cells in browser → agent reads/runs/
  edits via the MCP tools (`list_active_notebooks` → `get_cell_map` → `run_cell`
  → `get_variables` → `get_cell_outputs` → `get_errors` → `marimo check`).
- Library code stays in `src/`; notebook cells are thin wrappers (see
  [`AGENTS.md`](../AGENTS.md) §Project purpose).

---

## 3. Scope & structure decisions

- **Remove the stale optical/camera duplicate.** ✅ Confirmed 2026-09-07: the
  image processing *was already moved* — `python-image-processing-notebooks`
  holds the canonical, further-developed copy of
  `analysis/{mixer,feature_track,temporal_projection,image_projection}` (its
  modules say "Ported from udv-echo-process/analysis/…" and have advanced past
  the originals). This repo's copies are the stale originals and should be
  **deleted**, not expanded or ported forward. Full checklist + two small
  helpers to double-check first → `docs/hardening-plan.md` §P1 scope. (The
  early "mixer particle processing" marimo work you remember was done in the
  sibling's `notebooks/mixer_pipeline.py` / `mixer_preview.py`.)
- **Result-model convention:** `RpmResult` / `TemporalProjectionResult` are
  dataclasses while the stated convention is Pydantic. Decide whether to
  migrate (hardening-plan §structure) — do not add new dataclasses meanwhile.

---

## 4. Repo hygiene

- **`.gitignore`** — add `.venv/`, `__marimo__/`, `*.marimo.session_state`,
  `marimo.toml` (Phase 1); `outputs/` already ignored. Track a placeholder
  `marimo.example.toml` (no real endpoint/key). (See hardening-plan §repo.)
- **Data hygiene** — `data/echo-4-sensors-2x2/300RPM.BDD` is a PNG and
  `300RPM_Stat.ADD` is a JPEG (both tracked). Decide rename/remove/annotate
  (hardening-plan §data).
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
