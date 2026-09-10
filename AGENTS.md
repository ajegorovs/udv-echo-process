# AGENTS.md

Guidance for human and AI contributors working in this repository.

## Project purpose

This repo is the **Ultrasonic Doppler Velocimetry (UDV) signal-processing
toolkit**: parse, pre-process, filter, visualize, and analyse recordings from
DOP-series ultrasound Doppler instruments (`.ADD` ASCII exports today; `.BDD`
binary on the roadmap). The scope is the *signal-processing tooling* around
UDV data:

- **pre-processing** — parsing, cleaning, re-sampling, de-noising, aliasing
  removal/unwrapping;
- **filtering** — e.g. total-variation filtering and peak detection (not yet
  ported from the Wolfram references);
- **visualization** — time-synchronized heatmaps, gate profiles, summaries;
- **advanced / experimental-setup-specific algorithms** — e.g. rotor RPM from
  echo amplitude, whatever a specific rig (rotating machinery, mixer, …) calls
  for.

The design principle (same as the image-processing sibling):

> **Reusable building blocks live in plain Python modules; marimo notebooks are
> thin interactive wrappers around them.**

Backend functions in `src/udv_echo_process/` come in three shapes, all
importable and executable from a marimo notebook:

- **atomic edits** — one transformation (e.g. `parse_comma_decimal`,
  `setpoint_rpm_from_stem`, a future `tv_filter`);
- **sequences** — a composed multi-step operation over one input (e.g.
  `extract` → `ExtractedData.describe()`, `rpm_from_echo`);
- **mini-pipelines** — an end-to-end flow over a dataset (e.g. `plot_all`,
  `run_all.main`).

**Agent co-working in marimo notebooks is a first-class workflow**, not an
extra (see the Marimo section below).

**Wolfram porting is a means, not the goal.** The notebooks under
`references/wolfram/` exist only to bootstrap specialized signal-processing
tooling. New work is driven by UDV-processing needs; do not treat "what's left
in the Wolfram folder" as the roadmap.

## Sibling / companion repos (all under `~/Repos/`, never nested)

| Repo | Relationship |
|------|--------------|
| `marimo-inspect` | The **marimo co-work MCP toolkit we consume** (reference for the agent-inspection loop). Keep this repo a **sibling**, never nested (uv workspace hijack). |
| `python-image-processing-notebooks` | Image/camera processing — a **different modality**. Work there is deferred; do not expand its scope or edit it in this repo's tasks. |
| `DOPpy` | Third-party `.BDD` binary reader (reference if we add `.BDD` support — see `docs/doppy-analysis.md`). |
| `knowledge-base` | Shared notes; not a code dependency. |

## Tooling

- Package/venv manager: **uv**. Do not create or use `venv`/`pip`/`poetry`
  workflows.
- Python: **≥3.14** (pinned via `.python-version`).
- Runtime deps: numpy, matplotlib, pydantic, marimo[recommended] (pinned
  `>=0.24.0,<0.25`), marimo-inspect (git tag `v0.2.0` via `[tool.uv.sources]`).
  Dev extra: pytest. (Marimo plan Phase 1 landed 2026-09-07 — see
  `docs/marimo-integration-plan.md`.)

## Common commands

| Task | Command |
| --- | --- |
| Install / sync | `uv sync --extra dev` |
| Run tests | `uv run --extra dev pytest` |
| Inspect a recording | `uv run udv-inspect <file.ADD>` |
| Visualize | `uv run udv-viz [<file.ADD> …]` |
| Batch echo RPM | `uv run udv-run-all` |
| Lint (src/tests) | `uv run --extra dev ruff check src tests` |
| Format (src/tests) | `uv run --extra dev ruff format src tests` |
| Validate notebooks | `uv run marimo check notebooks` |
| One-off parse+plot | `uv run python -c "from udv_echo_process import extract, plot_all; plot_all(extract('data/echo/650.ADD'))"` |

Sandbox note: if `uv`/matplotlib fail with read-only cache errors, set
`UV_CACHE_DIR=/tmp/uv-cache` and `MPLCONFIGDIR=/tmp/mpl`.

## Conventions

- **Naming**: snake_case for modules/functions/variables; PascalCase for
  classes and Pydantic models.
- **Typing**: `from __future__ import annotations` at the top; type hints on
  all public functions.
- **Format**: ruff (dev extra, `[tool.ruff]` config in pyproject) — notebooks/
  excluded (marimo check validates them). Run `uv run --extra dev ruff check
  src tests` and `uv run --extra dev ruff format src tests`. Match existing
  style: 4-space indent, ~88-char lines.
- **Data**: `.ADD` files are TSV with comma as decimal separator
  (`parse_comma_decimal()`); auto-detected as single/multi-sensor,
  echo/velocity, raw/stat. `.BDD` is the binary twin (not yet parsed here).
- **Manual grounding**: when recording semantics, device behavior, or
  configuration parameters are unclear, consult the text-only
  [`DOP3000/3010 manual reference`](docs/dop3000/manual-reference/).
- **Models**: Pydantic `BaseModel` for data structures; `Enum` for fixed sets
  (`MeasType`). Do not add dataclasses. (The optical
  `TemporalProjectionResult` dataclass left with the removed stale
  optical modules; `RpmResult` is now a `BaseModel` too — hardening §structure.)
- **Pipeline & module structure (rebuild)**: the authoritative rules for the
  ground-up modular rebuild — Pydantic-not-dataclass, `Recording -> Recording`
  transform closure, `*Spec` param models, validation tiers, and templates —
  live in [`docs/pipeline-conventions.md`](docs/pipeline-conventions.md).
  Consult it when adding modules during the rebuild; this file's flat-era
  conventions are placeholders until then.
- **Ported features**: one module per ported Wolfram feature under
  `udv_echo_process/analysis/`; record it in `references/wolfram/README.md`.

## Marimo (live notebooks + agent inspection)

- Launch a notebook: `uv run marimo edit --no-token notebooks/<nb>.py`
  (deps landed 2026-09-07 — `marimo[recommended]>=0.24.0,<0.25` +
  `marimo-inspect` pinned via git tag `v0.2.0`).
- **`marimo-inspect` editable install (required for widget notebooks).**
  The pinned tag `v0.2.0` does **not** ship `TraceScrubber`/widgets — those
  were added to the sibling repo *after* the tag — yet
  `notebooks/channel_preview.py` imports `TraceScrubber` from
  `marimo_inspection`. Working on such a notebook therefore needs
  `marimo-inspect` installed **editable from the sibling repo**:
  `uv pip install -e ~/Repos/marimo-inspect`.
  - **Gotcha — `uv sync` / `uv run` silently clobber it:** both re-materialise
    the venv from `uv.lock` (git tag `v0.2.0`), replacing the editable install
    and breaking the widget imports (reproduced 2026-09-09: notebook failed to
    start with `cannot import name 'TraceScrubber'` right after a scipy
    `uv sync`). After any sync, reinstall editable.
  - **Launch from the venv binary, not `uv run`**, so the launch itself does
    not resync the venv: `MPLCONFIGDIR=/tmp/mpl .venv/bin/marimo edit
    --no-token notebooks/channel_preview.py`. (`marimo check`/lints are
    import-free and safe under `uv run`; only launching the kernel needs the
    editable install present.)
  - **Durable fix (open):** tag the sibling repo at/after the `TraceScrubber`
    commit and repin `[tool.uv.sources]` here to that tag — then the editable
    override becomes unnecessary.
- **Live notebooks:** `notebooks/echo_explorer.py` (marimo plan Phase 2,
  2026-09-07) — dropdown over `discover_data_files()`, channel pills, heatmap +
  gate-profile figures via `mo.mpl.interactive`. All computation stays in
  `src/`; cells are thin widget wrappers. Validate changes with
  `uv run marimo check notebooks`.
- **Session-materialization gotcha:** a bare `--headless` launch discovers
  nothing until a client connects — open the printed URL in a browser or do the
  `/sse` handshake (`docs/marimo-integration-log.md` §S14; provider repo
  `docs/agent-onboarding-demo-mcp.md` §Prerequisites). Zero-arg discovery also
  needs a **writable `~/.local/state/marimo/servers/`** (read-only home =
  empty registry, log O15) — when in doubt, pass `server_url` explicitly.
- **Agent loop:** `list_active_notebooks` → `get_cell_map` → `run_cell` →
  `get_variables` → `get_cell_outputs` → `get_errors` → `marimo check`.
  Through the DSH harness, **auto-bind does not persist across tool calls**
  (log O16) — pass `server_url` (and `session_id` when targeting) explicitly
  on every call. Filtered list-arg reads (`variable_names=[…]`,
  `cell_ids=[…]`) work on v0.2.0 (log O17).
- **Viz:** every plot function saves to a `Path` by default; pass
  `return_fig=True` to get the open `matplotlib` figure(s) back instead
  (needed for in-notebook display). In marimo 0.24.0 use
  `mo.mpl.interactive(fig)`; `mo.pyplot`/`mo.plt` are not exposed.
- Keep this repo **sibling** to `marimo-inspect`, never nested. Track a
  placeholder `marimo.example.toml`; gitignore the real `marimo.toml`.

## Architecture

```
src/udv_echo_process/
├── parser.py                        — unified parser (Pydantic models + auto-detect)
│   ├── MeasType (enum)              — ECHO | VELOCITY
│   ├── ChannelFrame (Pydantic)      — one measurement: channel, block, tbd_ms,
│   │                                  meas_type, gate_depths_mm, values,
│   │                                  n_profiles, std_dev, min_val, max_val
│   ├── ExtractedData (Pydantic)     — file_path, header, comment, frames[]
│   │                                  .by_channel() / .by_block() / .describe()
│   ├── extract(filepath)            — ASCUDOPV-guarded; auto-detect: single vs
│   │                                  multi-sensor, echo vs velocity, raw vs stat
│   └── list_add_files(), load_all_data() — convenience helpers
│
├── viz.py                           — visualization layer
│   ├── plot_recording(d[, return_fig])  — per-channel heatmaps, synced time axis
│   ├── plot_channel_stats(d[, return_fig]) — gate depth vs mean±std across time
│   ├── plot_all(d[, return_fig])    — heatmap + profiles in one call
│   └── discover_data_files()        — valid .ADD files under data/* (recursive,
│                                      ASCUDOPV magic check; public)
│
├── analysis/                        — one module per ported feature / domain tool
│   └── rpm.py                       — RPM from single-sensor echo (FFT peak /2);
│                                      RpmResult (Pydantic), mean_sample_interval_s
│
├── run_all.py                       — batch RPM extraction + viz per file
└── cli.py                           — udv-inspect / udv-viz / udv-run-all

tests/                               — pytest suite (parser + analysis + surface)
references/wolfram/                  — original Wolfram notebooks + porting map
data/<experiment>/                   — per-experiment .ADD/.BDD/notes (raw+stat mixed)
docs/                                — agenda, hardening plan, integration plan/log
```

The optical/camera modules (`analysis/{mixer,feature_track,image_projection,
temporal_projection}.py`) and the `udv-project`/`udv-mixvel` CLIs were
**removed** — the canonical, further-developed copy lives in the sibling
`python-image-processing-notebooks` repo. Do not port them back or re-add
optical tooling here.

Detection logic:
- **Column header**: `Amp` → echo, `mm/s` → velocity
- **Gate Depth count**: 1 → single-sensor, >1 → multi-sensor
- **Post-header line**: starts with "Statistical" → stat format, otherwise raw

Output structure:
```
outputs/
  summary.png                         — cross-file RPM summary (udv-run-all)
  <experiment>/<stem>/
    heatmap.png                       — per-channel heatmaps
    profiles.png                      — mean ± std gate profiles
```

## Adding a backend module

To add a new building block (atomic edit, sequence, or mini-pipeline):

1. Create `src/udv_echo_process/<concern>.py` (or `analysis/<feature>.py` for a
   ported feature) with pure, typed, docstringed functions. **No `marimo` or
   `mo.` imports in library code.**
2. Export public names from `udv_echo_process/__init__.py` (and the
   `analysis/__init__.py` when applicable).
3. Add tests under `tests/` that lock in the behaviour on the committed
   `data/` fixtures.
4. Wire a CLI entry in `cli.py` + `pyproject.toml` only when it's a genuinely
   reusable batch/pipeline step, not for one-off experiments.
5. If it ports a Wolfram feature, add a row to `references/wolfram/README.md`.

Keep modules **flat** while one module = one concern. Do **not** introduce
sub-packages pre-emptively; split (`analysis/{filter,measure,io}/`, …) only when
a module mixes unrelated concerns, crosses ~400–500 lines, or a *second,
different pipeline* starts reusing the same primitives.

## Scope boundaries

**In scope (this repo):** UDV `.ADD`/`.BDD` parsing and the signal-processing
tooling around it — pre-processing/filtering, visualization, analysis
algorithms, and experimental-setup-specific algorithms.

**Out of scope (defer or defer-to-sibling):**
- Optical/camera image processing → `python-image-processing-notebooks`. The
  stale duplicates (`mixer.py`, `feature_track.py`, `image_projection.py`,
  `temporal_projection.py`) and the `udv-project`/`udv-mixvel` CLIs were
  **removed** (hardening §P1) — the canonical copy is in the sibling repo.
  Do not port them back or re-add optical tooling here.
- marimo inspection tooling itself → `marimo-inspect` (we consume it).
- Wolfram notebook *porting* as an end in itself → only port when a UDV need
  justifies it.

## Docs & agendas

- `docs/agenda.md` — **OPEN** idea/backlog tracker (domain backlog, marimo
  integration, open questions). Append status updates; don't rewrite history.
- `docs/hardening-plan.md` — the prioritized fix/"harden" list (what needs
  fixing now to tie loose ends). Read before structural changes.
- `docs/marimo-integration-plan.md` + `docs/marimo-integration-log.md` — the
  consumer-side marimo + `marimo-inspect` integration plan and its
  evidence log (append-only).
- `docs/doppy-analysis.md` — the `.BDD` reader review (reference for future
  `.BDD` support).
- `references/wolfram/README.md` — Wolfram notebooks + porting map.

## Privacy — do not overexpose

This repo is public (`ajegorovs/udv-echo-process`). Never commit absolute
local paths naming the user/machine (`~/Repos/…` is fine), credentials, or
tailnet/RFC1918 IPs. Before committing docs/config, scan:
`git grep -nE '/home/[a-z]+|api[_-]?key|password|secret|BEGIN .*PRIVATE|tailscale|vllm' -- . ':!uv.lock'`
