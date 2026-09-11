# Marimo integration — observation log

Append-only field journal for the integration planned in
[`marimo-integration-plan.md`](marimo-integration-plan.md). This is the
*consumer-side record of what was actually observed* while enabling marimo +
`marimo-inspect` in this repo, kept separate from the plan so later phases can
trace which claim rests on which evidence. First consumer of the
`marimo-inspect` MCP stack, so the bar for recording quirks is low on purpose.

**Labels** (same convention the provider docs use):
✅ *observed* — command run in this session on this machine ·
📄 *documented* — quoted from a doc in one of the repos ·
❓ *inferred* — reasoned, not yet reproduced.

---

## Entry 2026-09-07 — review + Phase 0 (PASS)

**Machine:** provider/consumer are the same box today (single user, all repos
siblings under `~/Repos/`). Kernel under test: Python **3.14.7**. Provider
checkout: `~/Repos/marimo-inspect` (its own venv is **3.12**).

### Findings F1–F3 — repo visibility & dependency audit

- **F1** ✅ `ajegorovs/udv-echo-process` and
  `ajegorovs/python-image-processing-notebooks` are **PUBLIC** GitHub repos
  (GitHub API `private: false`, probed twice — early review and re-audit this
  session); `ajegorovs/marimo-mcp-cowork` (the `marimo-inspect` remote) returns
  `Not Found` to unauthenticated requests → **private** (📄 matches provider
  README's "private repo" statement). ⚠️ **Consequence:** committing
  `[tool.uv.sources] marimo-inspect = { git = … }` into a public
  `pyproject.toml`/`uv.lock` leaks the private URL *and* breaks `uv sync` for
  anyone without repo access (provider index §A1 says the same) → Phase 1's
  dev-extra / local-editable guidance.
  *(Correction trail, kept because this is the kind of drift this log exists to
  catch: one mid-session probe used `d.get('public')` — a field the GitHub API
  does not have — and falsely reported everything private. Re-probing with the
  correct `private` field restored the true state above. Lesson: single-field
  API probes are flaky evidence; cross-check before rewriting plans.)*
- **F2** ✅ Sibling hygiene breach is real: `python-image-processing-notebooks`
  **tracks** `marimo.toml` (verified `git ls-files` + commit `0ddf80e`) and its
  line 7 exposes a Tailscale vLLM endpoint
  `base_url = "http://100.x.y.z:8000/v1"` (IP redacted). It *does* also ship
  `marimo.example.toml` and `.gitignore` has **no** `marimo.toml` entry. →
  Phase 1's gitignore rule confirmed; the sibling should get the same fix
  (upstream note).
- **F3** ✅ Consumer `.gitignore` (3 lines: `outputs/`, `__pycache__/`,
  `.pytest_cache/`) is missing `.venv/`, `__marimo__/`,
  `*.marimo.session_state`, `marimo.toml`. Added to Phase 1.

### Feasibility re-verification (consumer side)

- **F4** ✅ Full udv dep set + `marimo[recommended]>=0.24.0,<0.25` resolves
  clean on 3.14 — re-ran `uv pip compile` **on this machine** (the plan's row
  was provider-machine only): marimo 0.24.0, numpy 2.5.3, matplotlib 3.11.1,
  opencv-python 5.0.0.93, pydantic 2.13.5, scikit-image 0.26.0, scipy 1.18.1
  (248 resolved packages). Current lockfile pins numpy 2.5.0 / matplotlib
  3.11.0 / pydantic 2.13.4 → expect a large re-resolution diff in Phase 1.
- **F5** ✅ The `marimo-inspect` MCP server is registered in this harness
  (all tools available, including `edit_cell`/`create_cell`/`delete_cell`/
  `lint_notebook` — more than the "8 read-only tools" commit message suggests).
- **F6** ✅ All provider doc pointers cited by the plan exist
  (`harness-integration/README.md`, `marimo-version-support.md`,
  `agent-onboarding-demo-mcp.md`, `agenda-remote-marimo-mcp.md`).
- **F7** ✅ `viz.plot_recording` / `plot_channel_stats` / `plot_all` end in
  `fig.savefig(); plt.close(fig); return Path` — **nothing renders in a
  notebook cell**; the return is a `PosixPath`. The plan's Phase 0 recipe
  (`plot_all(d)` alone) would have shown the user a path, not a heatmap. This
  single finding decides how Phase 0's "does it feel valuable" judgment must be
  run → see Phase-0 notebook cell design below and O23.
- **F8** ✅ marimo 0.24.0 API surface check (run in the provider's 3.12 venv):
  `mo.mpl` exists but exposes **only `interactive`**; there is **no**
  `mo.plt`/`mo.pyplot`. → Phase 0/2 render via `mo.image(path)`.
- **F9** ✅ API names used by the plan all exist and are re-exported from
  `udv_echo_process/__init__.py`: `extract`, `list_add_files`,
  `plot_recording`, `plot_channel_stats`, `plot_all`. Two discovery helpers,
  neither usable as-is for a whole-`data/` dropdown:
  `parser.list_add_files(data_dir="data/echo")` (one dir, excludes `_Stat`) vs
  `viz._discover_data_files()` (recursive over `data/*`, validates the
  `ASCUDOPV` magic line, **private**). → Phase 2: promote to public.
- **F10** ✅ Data dirs present: `data/echo/`, `data/echo-4-sensors-2x2/`,
  `data/4-sensor-velocity/` (raw + `_Stat` + `.BDD`). `data/echo/650.ADD`
  exists.

### Setup steps (Phase 0, zero repo changes)

- **S11** ✅ Launch used the plan's literal `uv run --with` overlay (adds
  marimo to an ephemeral env **on top of** the project `.venv` — no
  `pyproject.toml`/`uv.lock` change). Final working command:
  ```bash
  MPLCONFIGDIR=$PWD/.mplcache UV_CACHE_DIR=$PWD/.uvcache \
  uv run --with 'marimo[recommended]>=0.24.0,<0.25' \
    marimo edit --headless --no-token --port 29341 phase0_scratch.py
  ```
  Kernel: udv from the existing `.venv` (3.14.7), marimo **0.24.0** from the
  overlay.
- **S12** ✅ `uv` refuses to write its default cache when the agent sandbox
  mounts `/` read-only: `Could not create temporary file …
  ~/.cache/uv` → fixed with `UV_CACHE_DIR` (also `MPLCONFIGDIR` for
  matplotlib's font cache). **Consumer-side gotcha** (harness-specific;
  provider docs don't mention it).
- **S13** ✅ The probe notebook was **written statically as marimo file format**
  (cells as `@app.cell def _():` with `return` tuples) — the accepted
  authoring route in this session (no `create_cell`/`delete_cell` was used).
  ⚠️ A hand-written mistake (duplicate `import marimo as mo` across cells —
  marimo forbids cross-cell redefinition) was caught **at runtime by
  `get_errors`** (`kind:"graph"`, *"The variable 'mo' was defined by another
  cell"*), then fixed with `edit_cell` and re-run clean. Two notes on the fix
  path: `edit_cell` takes a **bare cell body** (statements, no `def`, no
  trailing `return` — a body containing `return` failed
  `SyntaxError: 'return' outside function`); and the fix only touched the
  **live kernel** — `marimo check` then exited 0, but whether the on-disk file
  was still the buggy version (auto-save timing without a browser client) was
  **not verified after the fact** (artifact deleted), so "check missed the
  DAG bug" is ❓, not a proven lesson. What IS proven: the MCP loop
  run→get_errors→edit_cell→run recovers from real notebook-authoring mistakes.
- **S14** ❓ Session materialization: the plan's Phase 0 uses the browser path.
  This agent environment has **no browser**, so the headless `/sse` handshake
  was used instead (documented path in
  `agent-onboarding-demo-mcp.md` §Prerequisites):
  `GET /sse?session_id=<uuid>&file=<abs path>` held open until `kernel-ready`.

### Agent-loop observations O15–O24 (live, 2026-09-07)

- **O15** ⚠️ **`--no-token` did NOT create a global discovery entry.** With the
  session live, `~/.local/state/marimo/servers/` stayed **empty** — so the
  plan's premise "discovery is **global**, not repo-scoped" did not hold for a
  bare-headless launch on this Linux box. This contradicts the sibling
  AGENTS.md (📄 "The marimo server must register with the discovery registry —
  start it with `--no-token`", observed there on Windows through a WSL gateway).
  Provider doc `agent-onboarding-demo-mcp.md` §Prerequisites only covers
  *session* materialization (confirmed, S14/O19), not server registration.
  All MCP reads in this session worked by addressing the server
  **directly by URL** (`http://127.0.0.1:29341`), with the session id surfaced
  by `list_active_notebooks(server_url=…)`. → Phase 1 re-test in the real
  `uv run marimo edit` (browser-connected) mode; DoD item 1
  (`list_active_notebooks` "finds it" with no explicit URL) is at risk.
- **O16** ✅ `get_cell_map` called **without** `server_url` — *after* a
  successful `list_active_notebooks(server_url=…)` — still failed with
  `Error: server_url is required.` So in this build, discovering a session
  does **not** make `server_url` optional (despite the hint text
  "session_id is now optional"). `set_active_session` exists as a tool but
  was **not exercised** in Phase 0 (explicit URL sufficed everywhere) —
  ❓ untested whether it relaxes `server_url`. The plan's Phase 3 line
  "pass `server_url` explicitly **or** `set_active_session`" should be read as
  "pass `server_url` explicitly, full stop" until proven otherwise.
- **O17** ❌ **List-typed arguments fail through the DSH MCP bridge**:
  `get_variables(variable_names=[…])` and `get_cell_outputs(cell_ids=[…])`
  both errored with pydantic `list_type` — the harness sends the JSON array as
  a *string*. The DoD-2 loop still completes (both tools accept an empty
  filter = "all"), but **filtered reads are broken on this consumer** and the
  outputs/variables dumps get chatty. Needs harness-side fix; re-test in
  Phase 1.
- **O18** ✅ Server cold start is **slow** because `marimo[recommended]` pulls
  ~340 MB (polars-runtime-32 55.8 MB, duckdb 20.5 MB, pyarrow 47.8 MB, sqlglot
  26 MB, marimo itself 37.7 MB; `uv sync --no-cache`): ~13 min on this box
  before `marimo edit` bound. The `api/version` endpoint answered `0.24.0`
  (bare version string). → Phase 1 should pre-sync so later iterations don't
  wait.
- **O19** ✅ Session materialized headlessly via `/sse`; `GET /api/sessions`
  then returned the uuid → **kernel was live with zero GUI**, satisfying the
  gotcha *without* a browser (see S14).
- **O20** ⚠️ **Session lifetime:** the SSE-holding job ended early (`curl … |
  head -40` consumed 40 lines and SIGPIPE-closed the stream), yet
  `GET /api/sessions` showed the session **still alive minutes later**, and
  every subsequent MCP call worked against it. Two possible readings: marimo
  keeps a grace period, or it doesn't GC `edit` sessions on disconnect.
  **Do not generalize** — re-test deliberately in Phase 1 before documenting
  the loop as browser-free.
- **O21** ✅ End-to-end loop PASSED on 3.14:
  `list_active_notebooks` → `get_cell_map` (6 cells, all `stale` at first) →
  `edit_cell` (DAG fix) → `run_cell` (all OK) →
  `get_variables`: `picker = dropdown "data/echo/650.ADD"`, `slider = 150`,
  `d = ExtractedData(file_path=…, 26 gates × … frames)`,
  `heatmap_png = outputs/echo/650/heatmap.png`,
  `profiles_png = …/profiles.png` →
  `get_cell_outputs`: widget HTML + the two `mo.image` `<img>` tags →
  `get_errors`: **0 errors** → `marimo check`: exit 0.
- **O22** ✅ `mo.image(str(png_path))` rendered (`<img src='./@file/…'>`) —
  the Phase 0 fix from F7 works.
- **O23** ⚠️ **Valuable for the agent, not yet for the human.** The heatmap was
  displayed *by file path* (`./@file/…`), and the library's plotting API
  writes to disk and closes the figure (F7). Interactive marimo wants
  `mo.mpl.interactive(fig)` / an inline figure. → Phase 2 **must** add a
  figure-returning display path to `viz.py` (already tracked in the plan).
- **O24** ✅ Post-run cleanup verified: server job killed (connection refused),
  no stray `marimo` processes; `phase0_scratch.py`, `.uvcache/`, `.mplcache/`,
  `__marimo__/` (server session cache dir) deleted; `git status` back to just
  `?? docs/`. Generated PNGs in `outputs/` left in place (gitignored).

### What Phase 0 proves / doesn't

Proves: the whole `extract → plot → display` path is usable from a live 3.14
marimo session through the MCP tools; widgets are read; errors surface;
figures are visible to the agent.
Does **not** prove: the browser-based `--no-token` launch flow (O15/O19 — no
browser here, and headless discovery behaved differently); the
name-filtered/list-arg call patterns (O17); session-disconnect semantics
(O20). Carry all three as Phase 1 re-test items.

---

## Entry 2026-09-07-b — decision: publish `marimo-mcp-cowork` (supersedes F1's constraint)

- **F11** ✅ Owner decision: `ajegorovs/marimo-mcp-cowork` will be made
  **public**. This removes the private-git-source blocker identified in F1:
  the URL leak and the `uv sync` portability problem both disappear, and
  Phase 1 reverts to the **sibling pattern** — `marimo-inspect` in main
  `dependencies` with the `[tool.uv.sources]` git line committed. The
  dev-extra/local-editable guidance survives in the plan as the fallback for
  as long as the repo is still private.
- **F12** ✅ Pre-publish audit of the provider tree (grep sweep):
  `LICENSE` = MIT (authored 2025) · no Tailscale/RFC1918 IPs · no credential
  strings (all `token`/`api_key` hits are docs *discussing* marimo's token
  gating) · no absolute personal paths in tracked content (test fixtures use
  `/home/user/…` placeholders) · only personal identifier is the
  `pyproject.toml` author email `aleksandrs.jegorovs@lu.lv` — same pattern the
  sibling already publishes; acceptable. No edits needed before flipping.
- **F13** ❓ Not solved by publishing (track separately): harness/MCP quirks
  O15–O17, the viz save-only-plots gap F7/O23, and — different repo — the
  sibling's *tracked* `marimo.toml` vLLM endpoint (F2) still needs its own
  fix there. Post-publish nicety: tag `v0.2.0` (the current package version)
  so the git source can pin a tag
  instead of floating HEAD (uv.lock pins the fetched commit meanwhile).

---

## Entry 2026-09-07-c — observations transferred to sibling repos

- **F14** ✅ Findings pushed to the other two repos as agenda docs (owner
  asked; elevated file access into sibling repos):
  - **marimo-inspect**: new `docs/agenda-udv-consumer-findings.md` (T1 headless
    `--no-token` skips the discovery registry — cause narrowed to marimo
    `server_registry.py` wiring in `lifespans.py`/`start.py`; T2 auto-bind
    semantics; T3 harness list-arg mangling, provider-side defensive fix
    optional; T4 3.14 private-API drift evidence; T5 **publishing checklist**
    incl. AGENTS.md §Remote + harness-integration §A1 edits that go stale the
    moment the flip lands; T6 sandbox/env consumer gotchas), indexed in its
    AGENTS.md docs map.
  - **python-image-processing-notebooks**: new
    `docs/agenda-udv-integration-lessons.md` (L1: their marimo dep lacks the
    `<0.25` upper bound — locked 0.24.0 today, any future `uv add` can drift
    past it undetected; L2: **private `marimo-mcp-cowork` git source is
    committed + locked in their *public* repo** — verified lock pin
    `#fe83cb9320313020007c25b116d83e31b225643c` (v0.2.0) — breaks `uv sync`
    for anyone without provider access until the publish decision lands; L3
    pin-sync watch), a **status update appended to
    `docs/agenda-config-hygiene.md`** (its Option-A "private repo" premise is
    false — repo is public → the history-rewrite option is now recommended),
    and a new "Docs & agendas" index in its AGENTS.md.
  - F1's visibility table was the load-bearing input for F14; re-probed with
    HTTP codes + rate-limit check before any sibling writes (one empty API
    response mid-session was anonymous rate-limiting, **not** a visibility
    flip — re-confirmed both consumer repos PUBLIC, provider 404).
- **F15** ❓ The 2026-09-07-b plan rewrite (dev-extra fallback) now also exists
    in sibling-repo docs as "pending provider publish"; if the flip happens,
    remember the three doc surfaces to touch: provider AGENTS.md §Remote,
    harness-integration §A1, and this repo's Phase 1 GATE note.

---

*(next phases: append new entries below this line, never edit earlier ones —
corrections are new entries that point back.)*

---

## Entry 2026-09-07-d — provider published; O16 fixed, O17 partially fixed

- **F16** ✅ `ajegorovs/marimo-mcp-cowork` flipped **public** (API `private: false`,
  HTML 200 unauthenticated). Phase 1 GATE satisfied; the F1 consequence is retired.
  ⚠️ **No `v0.2.0` tag cut yet** — owner has never used tags; the provider's
  AGENTS.md now documents the tag/release practice. Pin `tag = "v0.2.0"` in
  `[tool.uv.sources]` once the tag exists.
- **O16 → FIXED (provider v0.2.0).** `list_active_notebooks(server_url=…)` now
  binds **both** `session_id` and `server_url`, so later tool calls can omit
  both (explicit args still win). Re-verify against the installed build in
  Phase 1; until udv installs the new version, the old explicit-`server_url`
  pattern still applies.
- **O17 → PARTIALLY fixed (provider v0.2.0).** Tools now accept
  `str | list[str]` for `variable_names`/`cell_ids`, so a *scalar* string no
  longer errors. A stringified **multi-value** JSON array (e.g. `"['x','y']"`)
  is still not split — that is the DSH harness list-mangling bug and needs a
  harness-side fix. Re-test filtered reads in Phase 1.

*(append-only: corrections are new entries pointing back; earlier entries unchanged)*


---

## Entry 2026-09-07-e — Phase 1 landed; O15–O17 re-verified against installed v0.2.0

Repo setup (commit `8e07ec2`): `marimo[recommended]>=0.24.0,<0.25` +
`marimo-inspect` (git tag `v0.2.0`, commit `f5928de`) in `pyproject.toml`;
`uv.lock` re-resolved (+1950 lines); `marimo.example.toml` tracked;
`.gitignore` adds `.marimo/` + `.claude/`; marimo-pair / retro-marimo-pair
skills added (`.agents/` + `skills-lock.json`). Fresh `.venv` holds
`marimo 0.24.0` + `marimo-inspect 0.2.0`; the `marimo-inspect` MCP CLI is
installed. Full suite stays **34 passed**.

Re-verification ran against a live `--no-token --headless` marimo 0.24.0
session (`p2_scratch.py`, session materialized via the `/sse` handshake —
S14/O19 pattern still required; registry stays empty otherwise, see O15
below). Findings, updated for the installed build:

- **O15 → root cause identified (sandbox, not marimo).** The `--no-token`
  server *does* attempt registration — marimo 0.24.0 `lifespans.server_registry`
  only skips when `enable_auth` is true. Here the registry write fails because
  `~/.local/state/marimo/servers/` is on a **read-only filesystem** in this
  sandbox (verified: `touch` there → `Read-only file system`); the failure is
  swallowed (lifespans catches + warns). Confirmed twice: registry dir empty
  with the session live, and fresh-build `discover_servers()` → `[]` while the
  same session answers on an explicit URL. **On a writable home this should
  self-register** — re-check on a normal machine before trusting zero-arg
  discovery. Direct-URL addressing remains the reliable pattern here.
- **O16 → auto-bind does NOT persist across calls through the DSH harness.**
  `list_active_notebooks(server_url=…)` discovers and (per provider code)
  auto-binds session+URL into FastMCP ctx state, but a subsequent zero-arg
  `get_cell_map` still failed with `server_url is required`. Each harness tool
  call appears to run with fresh ctx state, so the "omit both afterwards"
  relaxation does not hold *on this consumer*. Explicit `server_url` per call
  works end-to-end. (`set_active_session(session_id, server_url=…)` was also
  rejected with `unexpected_keyword_argument` by the harness-registered server
  — its registered build predates the v0.2.0 `server_url` param.) Re-test
  against a *fresh* stdio/http server run from this repo's `.venv/bin/
  marimo-inspect` before relying on bind-persistence.
- **O17 → FIXED for real list args.** `get_variables(variable_names=["d",
  "picker"])` returned exactly the two requested variables (no full-kernel
  dump) and `get_cell_outputs(cell_ids=["vblA"])` worked — the DSH bridge now
  passes JSON arrays through as lists. Scalar-string fallback also fine.
  Filtered reads are usable end-to-end.
- Full DoD-2 loop re-confirmed on the installed build: `get_cell_map` (3 cells
  stale) → `run_cell` ×3 → `get_variables` (dropdown + `ExtractedData`) →
  `get_cell_outputs` (describe output rendered) → `get_errors` 0 errors →
  `marimo check` exit 0.

*(append-only: corrections are new entries pointing back; earlier entries unchanged)*

---

## Entry 2026-09-07-f — Phase 2 landed: first real notebook, DoD 1–4 met

`notebooks/echo_explorer.py` (9 cells) is the first real notebook: file
dropdown over every discoverable recording (`discover_data_files()`),
per-file `ExtractedData.describe()` summary, channel multiselect (defaults to
all channels), heatmap + gate-profile figures rendered via
`mo.mpl.interactive(plot_*(..., return_fig=True))`. All computation stays in
`src/`; cells are thin widget wrappers. DoD checklist:

- **DoD 1 ✅** Session materialized via the `/sse` handshake (S14/O19 pattern;
  still required in this read-only-home sandbox — O15 unchanged) and found by
  `list_active_notebooks(server_url=http://127.0.0.1:2719)`.
- **DoD 2 ✅** Full agent loop: `get_cell_map` (9 cells, stale→idle) →
  `run_cell` ×9 → `get_variables` (dropdown `200RPM.ADD`, multiselect
  `[6,7,8,9]`, full `ExtractedData` 1600 frames) → `get_cell_outputs` (both
  cells show rendered `<marimo-mpl-interactive>` elements) → `get_errors` 0
  errors. Then a **reactive** check beyond the plan: `cm.set_ui_value(fp,
  [value])` on the dropdown re-ran the whole chain (data → channels → filtered →
  both figures), ending on `650.ADD` / 4630 frames / channel `[4]` with 0
  errors. This is the first time a *notebook in this repo* was driven through
  its reactive dataflow from the agent side.
- **DoD 3 ✅** `uv run marimo check notebooks` exits 0 (had to fix the 3
  `branch-expression` errors first — display expressions must sit at cell
  top level, not nested under `if`; also ran `marimo check --fix` for the
  markdown-dedent formatting rule, which rewrote two display cells to a bare
  `return` — re-checked and restored the `heatmap_fig`/`profiles_fig` displays
  by hand afterwards).
- **DoD 4 ✅** AGENTS.md Marimo section gained a Live-notebooks pointer
  (`notebooks/echo_explorer.py` + `marimo check` validation).

New agent-side coding notes for future notebook edits (all verified against
marimo 0.24.0 in this repo's `.venv`):

- **O25** ✅ `mo.ui.dropdown` values are set through `cm` as a **single-element
  list**: `ctx.set_ui_value(fp, ["data/echo/650.ADD"])`. A bare string raises
  `AssertionError: Dropdowns only support a single value` (the element's
  `_convert_value` expects `len(value) == 1`). Setting the value inside
  `cm.get_context()` re-runs the owning cell + descendants on clean exit —
  explicit `ctx.run_cell` is not needed (and is sync, not awaitable).
- **O26** ✅ Do **not** `plt.close()` figures handed to `mo.mpl.interactive(fig)`.
  marimo closes figures after every cell run (`close_figures()` →
  `plt.close("all")`) and its `_FigureManagerRegistry`/`_MplCleanupHandle`
  lifecycle re-binds the cached WebAgg canvas and restores geometry on rerun;
  the widget stays live across reruns as long as the figure object is
  referenced. Manual closing fights that lifecycle. (Source:
  `.venv/.../marimo/_plugins/ui/_impl/from_mpl_interactive.py` +
  `_plugins/stateless/mpl/_mpl.py`.)
- **O27** ✅ `marimo check --fix` auto-canonicalizes `mo.md` markdown cells
  (MF007 dedent) but can drop trailing display expressions when it rewrites a
  cell — after `--fix`, re-read the diff and restore any display/return lines
  it removed.

*(append-only: corrections are new entries pointing back; earlier entries unchanged)*

---

### 2026-09-09 (later session) — notebook restructure + MCP experience report (O28–O32)

`notebooks/channel_preview.py` reshaped live (kernel :2718, session `s_jb93sf`)
into the agreed 4-group flow — import pickers → channel info + measured
heatmap → time-step scrubber → interpolation preview (controls → run → gate →
trace) — and filed a marimo-inspect MCP **consumer experience report** in the
sibling repo: `~/Repos/marimo-inspect/docs/
session-report-deepseek-harness-2026-09-09.md` (tool-by-tool verdicts,
frictions F1–F9, backlog P1–P5; sibling `agenda-udv-consumer-findings.md` got a
T7 review pointer). Commits: `16cdf4e`, `b4073f8`, `6bc96c4`, `5be0b0f`,
`16e9010`. New agent-side coding notes:

- **O28** ✅ UI-element handler exceptions (e.g. a bad programmatic
  `set_ui_value`) do **not** appear in the MCP `get_errors` surface — they land
  in the cell's **console** stream and leave a sticky GUI banner
  ("An exception was raised by a UIElement's on_change handler:") that clears
  only when the owning cell is rerun. Check `get_cell_outputs` console events
  when a user reports an error `get_errors` denies.
- **O29** ✅ A marimo cell **displays only what its final expression evaluates
  to**. Widget-only cells (assignments, no trailing expression) yield an empty
  kernel output — an agent's "implemented controls" render nothing until the
  cell ends with e.g. `mo.vstack([...widgets...])`. Backend-run cells may also
  not register UI-element outputs until a frontend run/refresh.
- **O30** ✅ marimo forbids reading `.value` of a UI element in the cell that
  **created** it (`RuntimeError`; fix named in the message). A widget that
  other cells consume (e.g. a gate dropdown feeding a trace) must live in its
  own upstream cell.
- **O31** ✅ `get_cell_map.has_output` read `false` for every cell although the
  kernel held real outputs; `get_cell_outputs` returns one payload per cell —
  auto-rendered UI elements are invisible to the agent. Treat `has_output` as
  unreliable; use `get_cell_outputs`/`get_cell_data` for truth.
- **O32** ⚠️ `cm.screenshot` fails with `ScreenshotError: Playwright is not
  installed` (no graceful capability detection); verifying GUI rendering
  therefore falls back to output-payload checks + user confirmation.
- **O33** ⚠️ `POST /api/kernel/restart_session` (marimo 0.24) only **closes**
  the session — no replacement kernel spawns until a browser reconnects; an
  external (agent-side) restart leaves the server at **0 sessions**. Required
  headers: `Marimo-Session-Id` + `Marimo-Server-Token` (CSRF skew token, served
  to clients as `serverToken` in the index page; only `/api/kernel/execute` is
  exempt). Reliable recovery = relaunch the marimo server so the browser
  auto-opens a fresh session (our usual flow), not the restart endpoint.
  Reproduced 2026-09-09: external restart → `sessions: 0`; relaunch → 1
  session, notebook re-run clean.
- **O34** ⚠️ Don't `import <pkg>.<submodule> as alias` in a notebook when the
  package **re-exports a function with the same name** as that submodule (here:
  `udv_echo_process.process` re-exports `filter`, shadowing the
  `process/filter.py` module) — the alias binds the attribute (the function),
  and `importlib.reload` then dies with `module filter not in sys.modules`.
  On a stale-import kernel, restart it instead of reloading; if you must
  reload, fetch modules via `importlib.import_module("a.b.c")` (sys.modules
  key, shadow-proof). Reproduced 2026-09-09 with the filter-platform bootstrap
  cell.

### 2026-09-11 (later session) — provider T-V1 round driven from the consumer (O35–O38)

Ran the provider's open post-hunt check round
(`~/Repos/marimo-inspect/docs/agenda-verification-round.md` §T-V1) against the
fix set released as **v0.3.3**, from this repo as the real consumer. Live
target: marimo **0.24.0** edit server on `:2718` on a `/tmp` copy of
`notebooks/channel_preview.py` (md5 identical to the committed file), kernel
session materialized via the `/sse?session_id=…&file=…` handshake (isolated
`XDG_STATE_HOME`); surface driven twice — through this harness's MCP tools and
through `fastmcp`/`mcp`-SDK clients (stdio + an `--transport http` instance on
`:8090`). Harness MCP server binary is the sibling checkout's
`.venv/bin/marimo-inspect` (editable, so provider HEAD). Round-1 of the run was
discarded: a crashed first pass left mutated cells in the notebook copy and two
assertions were badly phrased (they matched the *intended* guidance); the
payloads below are from the clean, correct run.

- **O35** ✅ **All five changed behaviours verified end to end** — the surface
  does what the packaged resources now say:
  - binding over stdio: argument-less `get_cell_map` after
    `list_active_notebooks` was served (21 cells), both through this harness's
    client and through fastmcp's session-per-request `Client` (the H11 case,
    i.e. the process-global fallback);
  - binding over HTTP with two clients present: the second argument-less call
    was refused `binding_ambiguous` and never handed the other client's
    notebook, while an explicit `session_id`+`server_url` call was served — and
    an `mcp`-SDK client (one MCP session) was served from its own session state
    even with many client sessions on the process. Fails closed, as documented;
  - `edit_cell` on a cell this process had only previewed returned
    `needs_read` with *"Cell ZHCJ was never read by this agent. Call
    get_cell_data for it (a get_cell_map preview does not record the read
    baseline)…"*, and succeeded after `get_cell_data`;
  - a bogus id came back in `missing_cell_ids` for both `get_cell_data` and
    `get_cell_outputs` (never an empty happy path); `get_dependency_graph` with
    `depth=1` refused `unsupported_argument` + *"Nothing was read."*, and its
    `cells[].cell_name` agreed with `get_cell_map` (empty string for unnamed
    created cells);
  - `set_ui_value`: a scalar string sent to a list-shaped dropdown was refused
    `value_shape_mismatch` with `did_you_mean: ["beta"]` and
    `accepted_shape: list[str]`; the corrected one-element list applied with
    `verified: true`; a valid change whose `on_change` handler raises gave
    `on_change_failed` + `applied: true`; repeating the held value gave
    `on_change_failed` + `applied: false` + `no_change: true` (the T13 residual
    combination, never `value_not_applied`) with `next_steps` saying
    re-sending *cannot* help;
  - `get_errors`: a cell printing `Error: 3 rows skipped` was not flagged; the
    handler traceback was, with the marker named per cell (`"traceback"`) and
    the full stderr — including marimo's *"An exception was raised by a
    UIElement's on_change handler:"* line — under that cell's `console_stderr`;
  - `get_variables` with no names returned only notebook names
    (`TraceScrubber`, `discover_data_files`, `file_picker`, `go`, `input`,
    `load`, `mo`, `np`, `spec_from_loader`, `tv1_widget`) — no `json`, `cm`,
    `get_variables`, `_is_ui`, `_serialize`.
- **O36** ✅ **Doc-vs-surface sweep clean.** All three packaged resources plus
  the provider `README.md` agree with every observed payload. Every one of the
  five `get_cell_map` mentions across them frames the map as *orientation only*
  and states the preview does **not** record the `edit_cell` baseline, with
  `get_cell_data` as the recovery read — no resource still offers
  `get_cell_map` as a read/recovery step.
- **O37** ⚠️ **Doc-precision item — filed upstream as the provider's `T-V2`.**
  *Correction to this entry's first wording:* the top level of `get_errors`
  carries **no** `console_exception_evidence` / `console_stderr` keys at all —
  they are absent, not null-valued — and the evidence (`"traceback"`) plus the
  stderr events live only on `cells[]`, which `next_steps` already points at.
  The payload is correct. What misleads is the wording: the tool description
  names `console_stderr` as a reported channel without scoping it to `cells[]`,
  and the provider's own `T-V1` §6 check line (`console_exception_evidence` says
  which marker matched) does not either — this run asserted a top-level field
  and had to be re-run to discover the difference. **Filed** in
  `~/Repos/marimo-inspect/docs/agenda-verification-round.md` §T-V2 with the
  evidence block and repro, severity *cosmetic* (the provider's
  `docs/bug-hunt-protocol.md` schema); the provider's `T-V1` boxes stay
  unticked, since that round requires a fresh zero-context agent.
- **O38** ⚠️ **Pin/install drift is the real consumer-side gap.** While the
  harness MCP server runs the sibling editable checkout at v0.3.3, this repo's
  `pyproject.toml` pins `marimo-inspect` at tag **`v0.3.0`** — so a normal
  `uv sync --extra marimo` installs the pre-fix package, and `.venv` today
  carries a v0.3.0 *metadata* + sibling-source hybrid from an earlier editable
  install. Bumping the pin to `v0.3.3` (and re-syncing) is what makes the
  verified surface reproducible for anyone else. **Landed the same session:**
  `pyproject.toml` `[tool.uv.sources]` now reads `tag = "v0.3.3"`, and
  `uv lock` + `uv sync --extra marimo --extra dev` moved `.venv` from the
  sibling editable install to
  `git+…@d0d673649527dcef07199f51fb76822b0a7d0bf3` — `marimo-inspect 0.3.3`
  imported out of `.venv/…/site-packages`, `TraceScrubber` resolves from the
  installed package, **130 passed**, `marimo check notebooks` exit 0, and the
  `uv.lock` diff is that one entry (no other package touched).

Harness recipe (recreate if the round is re-run): boot
`XDG_STATE_HOME=<tmp> .venv/bin/marimo edit <copy>.py --no-token --headless
--port 2718 --host 127.0.0.1`, materialize a session with
`GET /sse?session_id=<uuid>&file=<abs path>` and wait for `kernel-ready`, then
drive `~/Repos/marimo-inspect/.venv/bin/marimo-inspect --transport stdio` with
a `fastmcp` `Client`; use a **fresh** notebook copy per attempt — a crashed run
leaves created cells behind, and repeated names make `create_cell` fail with
`Multiply-defined names`. Scripts were throwaway under `/tmp`; payload evidence
in `/tmp/tv1/tv1_evidence.json`.
