# Plan: integrate marimo + marimo-inspect into udv-echo-process

> **Status:** Plan under execution — **Phase 0 ran 2026-09-07 and PASSED**;
> **Phase 1 (deps + repo setup) ran 2026-09-07 and PASSED** (commit `8e07ec2`;
> O15–O17 re-verified — see log Entry 2026-09-07-e). Phase 2–3 not started.
> Every observation is recorded with evidence labels in
> [`marimo-integration-log.md`](marimo-integration-log.md) (findings **F1–F10**,
> setup **S11–S14**, agent-loop **O15–O24**); the log is the traceable record —
> this plan's Phase 0 section is the summary. Three Phase-0 results feed forward
> as **Phase 1 re-test items**: browser `--no-token` discovery behaved
> differently headless (O15), the MCP bridge rejects list-typed args (O17), and
> a headless session outlived its client (O20, unconfirmed semantics).
> Feasibility table re-verified on the *consumer* machine: the full udv dep set
> + `marimo[recommended]>=0.24.0,<0.25` co-resolves clean on 3.14 (marimo
> 0.24.0 / numpy 2.5.3 / scipy 1.18.1 / pydantic 2.13.5 / scikit-image 0.26.0).
> Source of the tooling being integrated: sibling repo `~/Repos/marimo-inspect`
> (package `marimo-inspect`, public git remote `ajegorovs/marimo-mcp-cowork`). This doc lives in the *consumer*
> repo and is the consumer-side half of the integration; provider-side facts
> (transports, harness registration, draft gap list) live in
> `marimo-inspect/docs/harness-integration/README.md` (**that doc is itself a
> draft** — treat its ❓-labelled claims as unverified here too).

## Where udv stands today

- **No marimo anywhere in this repo**: no `notebooks/`, no `import marimo`, no
  marimo dependency. Everything is `src/udv_echo_process/` (parser, viz,
  analysis) + CLIs over `data/*.ADD`. So "integrate marimo-inspect" is really
  two moves: **(a)** introduce live marimo notebooks, **(b)** wire agent
  inspection into them. If only (b) was intended, stop and say so.
- Python **≥3.14** (uv-managed), deps: numpy / matplotlib / opencv / Pillow /
  pydantic / scikit-image.
- Design principle to keep (same as the image-processing repo): *library code in
  `src/`, notebooks are thin interactive wrappers.*

## Feasibility — checked 2026-09-07 (provider-side machine)

| Claim | Evidence |
|---|---|
| Full `marimo-inspect` stack installs and runs on Python **3.14.7** | fresh 3.14 venv: `fastmcp 4.0.3`, `marimo 0.24.0`, `numpy 2.5.3`, `pydantic 2.13.5` resolved; `create_server()` + in-process lint OK |
| udv's dep set co-resolves with `marimo[recommended]==0.24.0` on 3.14 | `uv pip compile` clean (scipy 1.18.1 etc.) |
| A **3.14 marimo kernel** driven by the 3.12 provider works | drift probe: `cell_map`/`errors` templates + in-process lint clean (provider repo `docs/agenda-remote-marimo-mcp.md` §Evidence) |
| The `marimo-inspect` MCP server is **already registered in this machine's DSH harness** | consumer-side confirmed 2026-09-07: `list_active_notebooks` answers from this repo's agent session (0 sessions until one is started) |

Residual risk: all contract testing so far ran on 3.12; the 3.14 evidence above
is a manual probe, not the repo's live suite. marimo stays pinned
**`>=0.24.0,<0.25`** in this repo — do not let a future `uv add` widen it
(provider doc: `marimo-version-support.md`).

## Plan

### Phase 0 — zero-config proof (~30 min, no repo changes)

The provider machine's DSH harness already registers the `marimo-inspect` MCP
server, and discovery is **global** (`~/.local/state/marimo/servers`), not
repo-scoped. So a quick end-to-end proof needs only a throwaway notebook:

1. `uv run --with 'marimo[recommended]>=0.24.0,<0.25' marimo edit --no-token scratch.py`
   (or add marimo first and skip `--with`)
2. In the notebook: `from udv_echo_process import extract, plot_recording` →
   `d = extract('data/echo/650.ADD')` → `mo.image(plot_recording(d))`.
   **Gotcha (verified in `viz.py`):** `plot_recording`/`plot_all` end in
   `fig.savefig(); plt.close(fig); return Path` — they save to
   `outputs/<experiment>/<stem>/*.png` and display **nothing** in a notebook
   cell. The Phase 0 go/no-go call must be made on `mo.image(path)`, or (cleaner)
   a fig-returning cell whose last expr is a `matplotlib.figure.Figure` — marimo
   auto-renders it, and `mo.mpl.interactive(fig)` adds pan/zoom. Phase 2 needs a
   viz option that returns/displays the figure instead of writing PNGs on every
   re-run. (Verified in marimo 0.24.0: `mo.mpl` exposes only `interactive`;
   `mo.pyplot`/`mo.plt` do not exist.)
3. From the agent: `list_active_notebooks` → `get_cell_map` → `run_cell` →
   `get_variables` → `get_cell_outputs`.

Session-materialization gotcha applies even here: a `--headless` launch
discovers nothing until a client connects — open the printed URL in a browser,
or do the `/sse` handshake (provider `docs/agent-onboarding-demo-mcp.md`
§Prerequisites has the exact snippet).

If this doesn't feel valuable, stop before Phase 1.

**Phase 0 result (ran 2026-09-07, this machine): PASS.** A 6-cell scratch
notebook (dropdown over `data/echo`, dpi slider, `extract` → `plot_recording` +
`plot_channel_stats` → `mo.image`) on Python 3.14.7, served
`--headless --no-token` via `uv run --with marimo…` (zero repo changes). The
agent loop completed end-to-end through the harness `marimo-inspect` MCP
server: `list_active_notebooks` → `get_cell_map` → `edit_cell` → `run_cell` →
`get_variables` (dropdown value `data/echo/650.ADD`, slider `150`, full
`ExtractedData` visible) → `get_cell_outputs` (two rendered `<img>` heatmaps)
→ `get_errors` clean → `marimo check` exit 0. Three field findings:

1. **The `/sse` handshake works from the consumer side** (curl stream to
   `/sse?session_id=<uuid>&file=<abs path>`; the session was still serving
   minutes after the SSE connection dropped — disconnect/GC semantics
   unconfirmed, re-test deliberately, log O20).
   Discovery dir `~/.local/state/marimo/servers/` stayed *empty* yet
   `list_active_notebooks(server_url=…)` worked — with an explicit URL the
   registry isn't needed; a `--no-token` loopback edit server should still
   self-register, but Phase 1 must re-confirm what the agent sees with zero
   args in the browser-connected mode (that's DoD item 1; log O15).
2. **`get_variables` without explicit names dumps every kernel variable** —
   very chatty. Passing `variable_names` was rejected by *this* harness's MCP
   argument marshalling (list → string). Workaround: omit and filter, or check
   the harness bridge before relying on name-filtered reads.
3. `run_cell` on a hand-written DAG-violating cell surfaced as a graph error
   through `get_errors` exactly as promised — the inspection loop catches real
   marimo mistakes, so hand-rolled notebook sources are safe to fix in-place
   via `edit_cell`.

Probe artifacts (`phase0_scratch.py`, `.uvcache/`, `.mplcache/`, `__marimo__/`)
deleted after the run; `outputs/` is gitignored.

### Phase 1 — dependencies and repo setup

> **GATE (2026-09-07): provider repo made PUBLIC — satisfied.** `ajegorovs/marimo-mcp-cowork`
> is now public (API `private: false`), so the sibling pattern is unblocked:
> commit the git source without leaking a private URL. Pin a tag once the owner
> cuts `v0.2.0` (provider AGENTS.md now documents tags); `uv.lock` pins the
> fetched commit meanwhile.

```toml
# pyproject.toml — matches python-image-processing-notebooks
dependencies = [..., "marimo[recommended]>=0.24.0,<0.25", "marimo-inspect"]

[tool.uv.sources]
marimo-inspect = { git = "https://github.com/ajegorovs/marimo-mcp-cowork", tag = "v0.2.0" }
```

- `uv sync --extra dev` (or `uv sync` for the runtime-only graph) → commit `uv.lock`.
- **Lockfile churn expected:** adding marimo re-resolves the whole graph (~250
  package entries; numpy 2.5.0→2.5.3, matplotlib 3.11.0→3.11.1, etc. bump
  silently). Don't be surprised by the diff size.
- `.gitignore`: add `__marimo__/`, `.venv/`, `*.marimo.session_state`, and
  **`marimo.toml`** (the local AI-endpoint config). `outputs/` is already ignored.
- **Hygiene rule (the sibling repo actually breaks this — do NOT copy the
  mistake):** `python-image-processing-notebooks` *tracks* `marimo.toml` in a
  public repo, exposing its vLLM base_url. Here, local
  `marimo.toml`/`marimo.local.toml` stays **gitignored**; track only a
  placeholder `marimo.example.toml` with no real endpoint/key.
- Keep the repo **sibling** to `marimo-inspect`, never nested (uv workspace
  hijack would rewrite the provider's lockfile).
- **Agent skills (part of the "same structure and rules" the sibling ships):**
  `uvx deno -A npm:skills add marimo-team/marimo-pair`, then commit `.agents/`
  and `skills-lock.json` so the marimo-pair / retro-marimo-pair skills match.
  `uv add --extra dev pytest` stays the test command; no ruff configured here
  yet (sibling excludes `notebooks/` from ruff — N/A until we add one).

**Phase 1 result (ran 2026-09-07, commit `8e07ec2`): PASS.** Dependencies
pinned (`marimo[recommended]>=0.24.0,<0.25` + `marimo-inspect` @ git tag
`v0.2.0`), `uv.lock` committed (+1950 lines), `marimo.example.toml` tracked,
`.gitignore` extended, marimo-pair / retro-marimo-pair skills committed.
O15–O17 re-verified against the installed v0.2.0 build with a live session —
details in the log Entry 2026-09-07-e. Headline: O17 list-arg reads **fixed**;
O15 root cause = read-only `~/.local/state/marimo/servers/` here (marimo
registers `--no-token` servers on a writable home); O16 auto-bind does **not**
persist across DSH harness tool calls (pass `server_url` per call).

### Phase 2 — the first real notebook

- `notebooks/echo_explorer.py`: file dropdown over `data/*` (auto-discover via
  `list_add_files()`), sensor/channel selector, `plot_recording` heatmap with
  synced time axis, gate-profile stats via `plot_channel_stats`; controls =
  `mo.ui` widgets, values read back by the agent through `get_variables`.
  A velocity twin comes later — one notebook end-to-end beats two half-done.
- **Discovery gap:** `list_add_files()` defaults to `data/echo` only and excludes
  `_Stat`; the cross-experiment scan lives in viz's *private*
  `_discover_data_files()`. Promote that to a public helper (e.g.
  `discover_data_files()`) so the notebook dropdown covers
  `echo-4-sensors-2x2/` and `4-sensor-velocity/` without globbing in a cell.
- **Viz gap (from Phase 0):** add a figure-returning/displaying mode
  (`plot_recording(..., return_fig=True)`) so interactive cells don't write a PNG
  per slider tick, and the notebook cell can display the `Figure` directly (or via
  `mo.mpl.interactive`).
- All computation stays in `udv_echo_process`; cells are thin.

### Phase 3 — harness wiring

- **Default: no new registration.** The stdio `marimo-inspect` server already
  sees every locally-discovered session, udv included.
- Only if udv wants its own pinned server binary: add a second `- insert:`
  entry in the harness profile with a **distinct `serverName`**, pointing at
  `udv-echo-process/.venv/bin/marimo-inspect` (never `uv run`).
- **Two-servers caveat** (likely once both repos run notebooks):
  `list_active_notebooks` auto-binds the first discovered session — pass
  `server_url` explicitly or `set_active_session` to pick udv's.
  *(Updated 2026-09-07-d: provider v0.2.0 fixed O16 — `server_url` is now bound
  alongside `session_id`, so the explicit-`server_url`-everywhere pattern is
  relaxed once we install the new build; re-verify in Phase 1.)*

### Definition of done

1. `uv run marimo edit --no-token notebooks/echo_explorer.py` opens with a live
   session; `list_active_notebooks` finds it from the agent.
2. Agent loop works end-to-end: `get_cell_map` → `run_cell` →
   `get_variables` (slider/dropdown values read) → `get_cell_outputs`
   (heatmap present) → `get_errors` clean.
3. `uv run marimo check notebooks` passes.
4. AGENTS.md here gains a short *Marimo* section (commands + the `--no-token` /
   session-materialization gotcha: a bare `--headless` launch discovers nothing
   until a client connects).

## Risks / open questions

- **Phase 0 carry-over re-tests** (full detail in the log, entries O15/O17/O20):
  browser-mode discovery, list-arg MCP marshalling, session-disconnect GC.
- **marimo-on-3.14 is probe-tested, not suite-tested** here; if the provider's
  live suite later gains a 3.14 leg, re-validate.
- marimo `<0.25` pin vs this repo's modern 3.14 stack: fine per the probes, but
  any provider-side pin bump must land here in a deliberate lockfile update.
- Whether notebooks should join `uv run --extra dev pytest` territory (cell-run
  smoke tests) — provider has an unsettled instantiation-token gap; don't
  promise live notebook tests in this repo until that resolves.
- Remote/Tailscale hosting of the kernel or MCP server is explicitly an
  **open agenda**, not this plan's scope:
  `marimo-inspect/docs/agenda-remote-marimo-mcp.md`.

## Pointers (provider repo: marimo-inspect)

- `docs/harness-integration/README.md` — consumer index (**draft**; ❓ labels =
  unverified)
- `docs/marimo-version-support.md` — the pin and upgrade-validation procedure
- `docs/agent-onboarding-demo-mcp.md` — demo runbook; Prerequisites = the
  session-materialization gotcha
- `docs/agenda-remote-marimo-mcp.md` — remote hosting question, incl. the
  3.14-kernel drift evidence
