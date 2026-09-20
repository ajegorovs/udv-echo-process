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
| `marimo-inspect` | Optional **marimo co-work MCP toolkit**. Normal users install its pinned release through the `marimo` extra; keep a sibling checkout only when developing unreleased provider changes. |
| `python-image-processing-notebooks` | Image/camera processing — a **different modality**. Work there is deferred; do not expand its scope or edit it in this repo's tasks. |
| `DOPpy` | Third-party `.BDD` binary reader (reference if we add `.BDD` support — see `docs/doppy-analysis.md`). |
| `knowledge-base` | Shared notes; not a code dependency. |

## Tooling

- Package/venv manager: **uv**. Do not create or use `venv`/`pip`/`poetry`
  workflows.
- Python: **≥3.14** (pinned via `.python-version`).
- Runtime deps: numpy, matplotlib, plotly, pydantic. The optional `marimo`
  extra installs `marimo[recommended]>=0.24.0,<0.25` plus
  `marimo-inspect` from git tag `v0.3.0`; enable it only for live notebook/MCP
  work. The optional `acquire` extra carries the instrument path: `pywin32`
  (Windows-only, behind a `sys_platform` marker) and `pillow` (cross-platform —
  the capture probes and the `tools/ui/` crop tooling both need it, and the crop
  tooling has to stay installable on a host that can only read committed PNGs).
  Dev extra: pytest. (Marimo plan Phase 1 landed 2026-09-07 — see
  `docs/marimo-integration-plan.md`.)

## Common commands

| Task | Command |
| --- | --- |
| Install / sync | `uv sync --extra dev` |
| Install notebook + MCP support | `uv sync --extra marimo --extra dev` |
| Run tests | `uv run --extra dev pytest` |
| Inspect a recording | `uv run udv-inspect <file.ADD-or-BDD>` |
| Visualize | `uv run udv-viz [<file.ADD> …]` |
| Batch echo RPM | `uv run udv-run-all` |
| Lint (src/tests) | `uv run --extra dev ruff check src tests` |
| Format (src/tests) | `uv run --extra dev ruff format src tests` |
| Validate notebooks | `uv run marimo check notebooks` |
| One-off parse+plot | `uv run python -c "from udv_echo_process import extract, plot_all; plot_all(extract('data/echo/650.ADD'))"` |
| Check the UI crop index | `uv run --extra acquire python tools/ui/crop_index.py` |
| Magnify a crop / its glyphs | `uv run --extra acquire python tools/ui/magnify.py composite\|glyphs …` |
| Drive the instrument (Windows, session 1) | `./tools/live/dispatch.sh -m udv_echo_process.cli acquire status` |
| Dispatch a one-off probe | `PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh <bare-probe-name>.py` |

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
  echo/velocity, raw/stat. `.BDD` is the binary twin and **is** parsed:
  `io/dop/bdd.py` returns an `ArtifactBundle` with content-SHA-256 source
  identity, a decoded `AcquisitionMode`, and all-observed support. Discovery in
  `viz.py` is `.ADD`-only and magic-checked, while the reader sniffs *bytes*, not
  extensions — so `data/echo-4-sensors-2x2/20260723_143754.jpg` (a genuine
  4-channel echo BDD with the wrong extension) loads correctly and is not
  special-cased.
- **Manual grounding**: when recording semantics, device behavior, or
  configuration parameters are unclear, consult the text-only
  [`DOP3000/3010 manual reference`](docs/dop3000/manual-reference/).
- **Models**: Pydantic `BaseModel` for data structures; `Enum` for fixed sets
  (`MeasType`). Do not add dataclasses. The domain model is the frozen
  `ValueModel`/`ArrayModel` pair in `models/base.py` (`extra="forbid"`,
  `validate_default=True`); every ndarray field is an owned, C-contiguous,
  read-only copy taken by the shared `array_field`/`owned_array` helper. Do not
  add a mutable model base and do not hand-roll array ownership.
  `model_copy(update=...)` is never used to build transformed scientific data.
- **Pipeline & module structure**: the ground-up modular rebuild described by
  [`docs/signal-model-rework-plan.md`](docs/signal-model-rework-plan.md) has
  **landed** (9 phases, one commit each). The working rules are: transforms are
  bundle-closed (`ChannelBundle -> ChannelBundle` per channel,
  `ArtifactBundle -> ArtifactBundle` at recording level), a transform body
  computes owned arrays and then calls `process/derive.py::derive()` — or
  `derive_many()` for a multi-output recording operation — and never constructs a
  derived artifact by hand; `provenance.select_channel`/`replace_channel` are the
  only bridge between the two states; `models/` imports nothing from
  `process/`/`provenance/`/`storage/`/`io/`; and specs are discriminated Pydantic
  unions (`process/specs.py`) so an irrelevant parameter is an error.
  [`docs/pipeline-conventions.md`](docs/pipeline-conventions.md) carries the
  Revision-3 banner for the same contract.
- **Two reviewed limits** (do not "fix" these without new decoded evidence):
  the `.BDD` header version string and the 512-byte comment are decoded and then
  dropped, because §6.6/§6.7 pin `ChannelArtifact` and `Recording` at five fields
  each; and the binary format proves no round/visit identity, so `synchronize()`
  has no real fixture and is exercised on synthetic topology only.
- **Ported features**: one module per ported Wolfram feature under
  `udv_echo_process/analysis/`; record it in `references/wolfram/README.md`.

## Driving the instrument (do not re-derive these)

Six facts every session otherwise rediscovers the hard way. The measurements behind them
— and the pitfalls beside them — are in `.agents/skills/udop-acquisition/`; this list is
the short form that has to survive a session that reads nothing else.

- **The menu bar opens on a real cursor *hover*; the entry then takes a posted *held*
  press** (`WM_LBUTTONDOWN`, ~180 ms, `WM_LBUTTONUP`, client coordinates) on its own
  handle. A posted move, a posted hover and an instant down/up all open nothing.
- **Every caption is paint.** `WM_GETTEXT` returns `""` for nearly all of these widgets,
  and `GetWindowText` returns `""` for *everything* owned by another process — so an empty
  read taken with it is evidence of nothing. To read a label: screenshot, then magnify.
- **Read digits at x5-x6 with a glyph-level comparison** before believing them; a
  full-frame capture is downscaled before any reader sees it and `600` reads as `500`.
  `tools/ui/magnify.py` (magnify the committed crops) is the tool; the crops are the oracle.
- **A write commits at the dialog's `Accept`** (`row[-1]`); `Cancel` (`row[-2]`)
  *discards*, so a write "verified" against Cancel proves nothing about what was kept.
  Read the field back from a **reopened** dialog.
- **Combos are selected by value text, never by counting steps** (one step up from `4`
  landed on `6`), and `CB_GETCURSEL` goes stale after a programmatic select — the text is
  the authority.
- **The application clips the cursor while its popups are open** (`ClipCursor`), and a
  clipped `SetCursorPos` is clamped *silently*: read the clip, release it with
  `ClipCursor(NULL)` when the target lies outside, and name the clip rather than blaming a
  locked desktop.

Anything that touches the screen must run in the **interactive session** (the agent shell
is session 0 and sees no GUI): `./tools/live/dispatch.sh <bare-probe-name>.py`, log in
`outputs/live/task-<probe>.log`. See `tools/live/README.md`.

## Vision and the inspection crops

- **45 UI crops are committed** under `docs/dop3000/ui-crops/`, indexed row per crop in
  `docs/dop3000/ui-element-index.md` (id, file, size, surface, state, what it shows). They
  are the only oracle for this application's painted captions — the control tree carries no
  text for the button classes — and they are the first thing to read when a control or a
  caption has to be identified. **Cite the crop id** (`UI-MENU-05`, `UI-OVERLAY-22`) when a
  caption is quoted, so the quote stays checkable.
- **`uv run --extra acquire python tools/ui/crop_index.py`** verifies that the index
  describes the files it claims to (existence, real pixel size, unique and gapless ids,
  row count against the prose). Run it in any change that adds, renames or withdraws a
  crop; `tools/ui/magnify.py` is the composite/glyph tool. See `tools/ui/README.md`.
- **Taking new crops needs Windows and the instrument's desktop** — `tools/live/probes/
  dialog_shot.py` (whole screen + the dialog's rect from the *same* frame, with the
  non-blank/stability guards) through `dispatch.sh`. A clone on Linux, or any machine
  without the desktop, can read, magnify, check and quote the set but cannot extend it.
  That boundary is the reason the crops are committed at all; it is written out in
  [`docs/dev-handoff.md`](docs/dev-handoff.md).

## Marimo (live notebooks + agent inspection)

- **Bootstrap is outside MCP.** The MCP resources are available only after the
  optional feature is installed and the harness connects. The normal consumer
  path is `uv sync --extra marimo --extra dev`, then configure the harness to
  execute `.venv/bin/marimo-inspect --transport stdio`. Read
  `README.md` §Optional live marimo co-work first; use the provider's README
  for harness-specific setup. Do not use `uv run` as the long-lived MCP command.
- **No editable install for normal work.** This project pins provider tag
  `v0.3.0`, which includes `TraceScrubber`; `notebooks/channel_preview.py`
  therefore works from the normal `marimo` extra. A local editable provider
  override is only for testing unreleased `marimo-inspect` changes, is
  temporary, and must never be committed here.
- Launch a notebook: `.venv/bin/marimo edit --no-token notebooks/<nb>.py`
  after syncing the `marimo` extra. `uv run marimo` is acceptable for a
  one-off static check but not as the MCP server command.
- **Live notebooks** (both migrated onto the landed model in the rework's
  Phase 9). A lint pass does not execute cells, so prove a notebook change by
  running it:
  `uv run --no-sync --extra marimo marimo check notebooks` **and**
  `uv run --no-sync --extra marimo marimo export html notebooks/<nb>.py -o /tmp/nb.html`.
  `notebooks/echo_explorer.py` (marimo plan Phase 2, 2026-09-07) — dropdown over
  `discover_data_files()`, channel pills, heatmap + gate-profile figures via
  `mo.mpl.interactive`; it rides the `.ADD` path (parser + `viz`).
  `notebooks/channel_preview.py` — the artifact/bundle API (`load()` →
  `ArtifactBundle`, `select_channel` → `ChannelBundle`, discriminated specs,
  bundle-closed `filter`/`resample`). All computation stays in `src/`; cells are
  thin widget wrappers.
  `notebooks/channel_preview_sidebar.py` — the same notebook with the
  recording → channel selection moved into a `mo.sidebar` cascade (every other
  cell identical; both files are kept side by side).
- **Session-materialization gotcha:** a bare `--headless` launch discovers
  nothing until a client connects — open the printed URL in a browser or do the
  `/sse` handshake (`docs/marimo-integration-log.md` §S14; provider repo
  `docs/agent-onboarding-demo-mcp.md` §Prerequisites). Zero-arg discovery also
  needs a **writable `~/.local/state/marimo/servers/`** (read-only home =
  empty registry, log O15) — when in doubt, pass `server_url` explicitly.
- **A materialized notebook is not a *run* notebook.** No control holds a value
  and no cell has output until the cells have actually run, so a freshly opened
  window (or an un-run session) has inert widgets and empty execution state;
  `marimo check` executes nothing either. Let the notebook finish running before
  reviewing a live window, and verify a change with `marimo export html` or app
  mode — both execute. Mechanism: provider
  `docs/agent-onboarding-demo-mcp.md` §Prerequisites and
  `reference://marimo-inspect/fallbacks-and-limits` §A session is not a run.
- **MCP workflow authority:** after the server is connected, list and read its
  packaged resources before live mutation. The normal loop is
  `list_active_notebooks` → `get_cell_map` → read required cells → mutate/run
  → `get_variables` / `get_cell_outputs` / `get_errors` →
  `marimo check`. `set_ui_value` values are widget-specific; verify every
  update by reading state back. Pass `server_url` (and `session_id` when
  targeting) explicitly when harness session binding does not persist.
- **Viz:** every plot function saves to a `Path` by default; pass
  `return_fig=True` to get the open `matplotlib` figure(s) back instead
  (needed for in-notebook display). In marimo 0.24.0 use
  `mo.mpl.interactive(fig)`; `mo.pyplot`/`mo.plt` are not exposed.
- Keep this repo **sibling** to `marimo-inspect` only when developing the
  provider. Normal users do not need a sibling checkout. Track a placeholder
  `marimo.example.toml`; gitignore the real `marimo.toml`.

## Architecture

```
src/udv_echo_process/
├── models/                          — the domain model (frozen, owned arrays)
│   ├── base.py                      — ValueModel, ArrayModel, array_field, owned_array
│   ├── identity.py                  — ChannelKey, SignalQuantity, SignalDescriptor,
│   │                                  SourceAsset, AcquisitionRef, recording_id_for
│   ├── support.py                   — SupportKind, QualityFlag, SampleSupport
│   ├── acquisition.py               — AcquisitionIndex, AcquisitionMode
│   ├── signal.py                    — SignalData, ChannelArtifact, source_artifact,
│   │                                  array_digest, the artifact-id equations
│   ├── recording.py                 — Recording, ProfileStatistics
│   ├── channel_config.py            — serializable frozen channel metadata
│   └── io.py                        — SourceSpec/SourceFormat (source enums)
│
├── process/                         — the transforms (bundle-closed)
│   ├── specs.py                     — discriminated FilterSpec/InterpSpec + SyncSpec
│   ├── filter.py                    — filter / filter_sequence over ChannelBundle
│   ├── sync.py                      — resample (channel) + synchronize (recording)
│   ├── derive.py                    — derive / derive_many + operation registry
│   └── segments.py                  — private shared segment/uniformity helpers
│
├── provenance/                      — ArtifactGraph, ChannelBundle, ArtifactBundle,
│   │                                  OperationRecord, ImplementationRef, and the
│   │                                  pure graph helpers (insert_operation,
│   │                                  source_bundle, select_channel, replace_channel)
│   └── models.py
│
├── storage/                         — NPY + manifest store, schema v1
│   ├── models.py                    — ArrayRef, BundleManifestV1, StoredRecordingV1
│   └── npy.py                       — store_bundle / load_bundle, StoreError
│
├── io/                              — readers; io/dop/bdd.py returns an ArtifactBundle
│
├── acquire/                         — the third pipeline: make the instrument record.
│   ├── actuator.py                  — the Actuator protocol + the dialog/binding tables
│   │                                  (DIALOG_FIELD_ORDER, DIALOG_ANCHORS, the roles)
│   ├── driver.py                    — the Windows half (pywin32; lazily imported)
│   ├── plan.py  config.py           — the sweep math and its value objects (pure)
│   ├── campaign.py runner.py        — points, permutations, resume, per-point cycle
│   ├── verify.py                    — requested vs GUI read-back vs the decoded words
│   ├── snapshot.py  log.py  live.py — instrument reading, JSONL log, live commands
│   └── __init__.py                  — the public surface; import-safe off Windows
│
├── parser.py                        — `.ADD` parser (unchanged by the rework)
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
├── viz.py                           — visualization layer (`.ADD` path)
│   ├── plot_recording(d[, return_fig])  — per-channel heatmaps, synced time axis
│   ├── plot_channel_stats(d[, return_fig]) — gate depth vs mean±std across time
│   ├── plot_all(d[, return_fig])    — heatmap + profiles in one call
│   └── discover_data_files()        — `.ADD` files under data/* (recursive,
│                                      ASCUDOPV magic check; public)
│
├── analysis/                        — one module per ported feature / domain tool
│   └── rpm.py                       — RPM from single-sensor echo (FFT peak /2);
│                                      RpmResult (Pydantic), mean_sample_interval_s
│
├── run_all.py                       — batch RPM extraction + viz per file
└── cli.py                           — udv-inspect / udv-viz / udv-run-all / udv-acquire

tests/                               — pytest suite (models, transforms, provenance,
                                       storage, parser, analysis, acquire, surface)
tests/data/*.json                    — committed tree fixtures; each names the probe it
                                       came from, so a measured screen is re-checkable
references/wolfram/                  — original Wolfram notebooks + porting map
data/<experiment>/                   — per-experiment .ADD/.BDD/notes (raw+stat mixed)
examples/                            — a working campaign definition
                                       (examples/campaign-single-channel.json)
tools/live/                          — the interactive-session route for anything that must
                                       touch the screen: dispatch.sh, task_run.py, probes/
                                       (Windows-only; its README is the entry point)
tools/ui/                            — the inspection crops: crop_index.py (the checker —
                                       index vs the 45 committed PNGs), magnify.py
                                       (composite + glyph bitmaps), README
docs/                                — agenda, the landed rework plan, hardening plan,
                                       integration plan/log, dev-handoff.md (read this
                                       first on a machine that cannot reach the instrument),
                                       dop3000/ (the instrument's docs and the retirement
                                       register for the recon archive)
```

**Three pipelines coexist by design.** The `.ADD` path (`parser.py` → `viz.py`/`run_all.py`/
`cli.py`/`analysis/rpm.py`) keeps its own entry points; the `.BDD` path produces
the artifact model above; and the acquisition path (`acquire/` + `tools/live/` +
`tools/ui/`) drives the instrument and hands its stored files to the `.BDD` reader.
Echo RPM now exists on **both** readable paths (`rpm_from_echo` /
`rpm_from_channel`, one shared private kernel, numerically identical on the paired
fixtures) but there is still **no `.ADD` → bundle adapter** — `udv-run-all` stays on
the `.ADD` path because it also writes legacy heatmaps/profiles with no artifact-model
counterpart. `ChannelSeries`/`MultiplexedMeasurement` (and the legacy mutable `Model`
base) were **removed** in Phase 9 — do not reintroduce them or an adapter that
masquerades as the new domain model.

Only the acquisition pipeline is platform-bound: `acquire/driver.py` is the single module
allowed to touch `pywin32`, it imports it lazily, and `acquire/__init__.py` stays
import-safe everywhere — so the whole package (and every command, against the fakes) is
testable on Linux. `docs/dev-handoff.md` is the entry point for a machine that cannot reach
the instrument.

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
  live/                               — everything the instrument path writes
    task-<probe>.log                  — the dispatcher's log for each dispatched probe
    *.png, *.json                     — captures and probe reports (git-ignored)
    store/                            — the application's own Store directory
```

The instrument's Store directory is `outputs/live/store/`: the driver asserts it against
`--store-dir`/`UDV_STORE_DIR` and refuses a point whose setting disagrees, rather than scattering
files. It used to live inside the reconnaissance archive, which was retired on 2026-09-18 (see
[`docs/dop3000/recon-archive-retirement.md`](docs/dop3000/recon-archive-retirement.md)).

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

Keep modules **flat within their sub-package** while one module = one concern.
The artifact model is organised as `models/`, `process/`, `provenance/` and
`storage/` because a second pipeline (`.BDD` artifacts) reuses the same
primitives — the exception this rule always allowed. Do not add another nesting
level until a module again mixes unrelated concerns or crosses ~400–500 lines
(`models/signal.py`, at ~540, is the current one to watch).

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

- `docs/agenda.md` — current action-oriented backlog, active decisions and
  acceptance blockers. Fold superseded/resolved detail into its authority
  document and `docs/agenda-history.md`; do not turn the live agenda into a
  session transcript.
- `docs/agenda-history.md` — compact historical index and superseded-concept
  map; Git retains the verbatim pre-consolidation session record.
- `docs/hardening-plan.md` — the prioritized fix/"harden" list (what needs
  fixing now to tie loose ends). Read before structural changes.
- `docs/marimo-integration-plan.md` + `docs/marimo-integration-log.md` — the
  consumer-side marimo + `marimo-inspect` integration plan and its
  evidence log (append-only).
- `docs/doppy-analysis.md` — the `.BDD` reader review (the reference for the
  decoding that `io/dop/bdd.py` now implements).
- `docs/architecture.md` — current user-facing system map: the two pipelines,
  dependency boundaries, public entry points and verification workflow. Read it
  before changing a cross-layer concern.
- `docs/signal-model-rework-plan.md` — the **landed** signal-model rework
  contract (9 phases, one commit per phase). Read it before changing the
  semantics of `models/`, `process/`, `provenance/` or `storage/`.
- `docs/udv-analysis-absorption-plan.md` — the source-analysis record for
  absorbing the retiring external `udv-analysis` package (measurements, module
  mapping, do-not-absorb list, sequencing, open decisions). Read it before
  adding state detection or profile-extraction code, and before deleting the
  source checkout.
- `docs/udv-analysis-reference.md` — the standing preservation register for
  `udv-analysis`: every tracked source file with its disposition (absorbed →
  where / rejected → why / **open** — preserved, no counterpart), how to verify
  and reconstruct the private pack, and the live open items. Read it before
  re-opening a rejected decision, claiming a capability was fully absorbed, or
  deleting the source checkout or pack.
- `docs/dop3000/acquisition-review-and-verdict.md` — the DOP3010 acquisition
  review as received plus its verdict: findings verified with `file:line`
  evidence, what the review over-stated or missed, the per-phase decision
  (accepted / modified / deferred behind a trigger) and the first
  implementation slice. Read it before re-proposing that review, before
  extending the sweep parameters, and before splitting `acquire/driver.py`.
- `references/wolfram/README.md` — Wolfram notebooks + porting map.

## Privacy — do not overexpose

This repo is public (`ajegorovs/udv-echo-process`). Never commit absolute
local paths naming the user/machine (`~/Repos/…` is fine), credentials, or
tailnet/RFC1918 IPs. Before committing docs/config, scan:
`git grep -nE '/home/[a-z]+|api[_-]?key|password|secret|BEGIN .*PRIVATE|tailscale|vllm' -- . ':!uv.lock'`

## Skills (agent tooling)

Repo-local skills live in `.agents/skills/` — the cross-client Agent Skills layout
(`SKILL.md` plus `references/`, `scripts/`, `assets/`), versioned with the code so a clone carries
the project's *procedures*, not only its source. Update the copy here whenever a lesson is learned
in this repository; the whole point is that it travels.

- `udop-acquisition/` — driving the DOP/UDOP acquisition application through the Win32
  message layer: reconnaissance and role binding, the record/stop/store cycle, per-channel
  mode, artefact decoding, the sweep and campaign workflow, the crops/vision route, and the
  staged bring-up for a machine that is not the one the measurements were taken on. Read it
  before changing `tools/live/`, `tools/ui/` or `src/udv_echo_process/acquire/`, and before
  investigating anything the application's own UI has to answer.

**One copy, and it lives here.** This skill is the authoritative one: it travels with a
clone, and it is where a lesson about *this instrument* belongs. The generic cross-project
craft is the Hermes skill `windows-gui-automation`, which lives outside the repository and
is maintained by the agent itself; a lesson about GUI automation in general belongs there.
The two must not be allowed to fork — and the hazard is directional, because a project-local
skill **shadows** a profile-global skill of the same name (first-wins name deduplication),
so a repo copy that falls behind silently *hides* the newer global one for every session
inside this repository. That is exactly what happened while both were named
`windows-gui-automation`: two forks, 284 lines of newer material unreachable from here.
Rename rather than re-introduce a colliding name.

Most agentic harnesses load `.agents/skills/` on their own when the working directory is in the
repository. **Hermes Agent needs the project trusted once per machine**, from the repository root:

```bash
hermes skills trust "$(git rev-parse --show-toplevel)"   # once per machine
hermes skills untrust "$(git rev-parse --show-toplevel)" # revoke
```

Pass the root explicitly: `hermes skills trust` with no argument resolves the cwd itself and
reports *"Not inside a git checkout"* even when run from this repository.


`.hermes/` is git-ignored on purpose: agent working artifacts (dispatch plans, scratch state),
never repository documentation.

**Scratch files go in `.hermes/scratch/`, never directly in `.hermes/`.** Hermes' write guard
reads *any* file whose immediate parent directory is a project-local `.hermes` as agent-steering
config (`tools/file_tools_write_guards.py::_protected_instruction_reason`) and asks a human to
approve each `write_file`/`patch` there — one prompt per operation, no persisted scope, not
bypassed by `--yolo` or the command allowlist. The match is on the parent directory name and the
file name is never examined, so a scratch script sitting at `.hermes/fmt_cli.py` is treated
exactly like `.hermes/config.yaml`. One level down is outside the rule: `.hermes/scratch/x.py`
is never gated. Keep the root of `.hermes/` empty of hand-written files.

