# Agenda — udv-echo-process

Open items to do or assess, in rough priority order. Use this file (or add
`docs/agenda-*.md` topic files) to store what needs doing; keep it current as
items resolve. Evidence labels ✅ observed / 📄 documented / ❓ inferred.

## Marimo integration (next up)

- **Phase 1 — pin the provider.** Repo is public now. In `pyproject.toml` add
  `marimo-inspect` to `dependencies` + `[tool.uv.sources]` with
  `tag = "v0.2.0"` once the provider cuts the tag (see
  `docs/marimo-integration-plan.md` §Phase 1). Commit `uv.lock`; expect a large
  re-resolution diff (~250 entries).
- **Re-verify O16 (auto-bind) after installing the new build.** With v0.2.0,
  `list_active_notebooks(server_url=…)` should make both `session_id` and
  `server_url` optional on later calls. Confirm before relaxing the
  explicit-`server_url` call pattern in docs.
- **Re-test O17 (list-arg marshalling).** Provider now tolerates a scalar
  string, but a stringified multi-value array still needs the DSH harness fix.
  Filtered `get_variables(variable_names=[...])` is still unproven here.
- **Re-test O15 (headless discovery).** Headless `--no-token` servers skipped
  the registry in Phase 0; re-confirm what `list_active_notebooks` sees with
  zero args in browser-connected mode (DoD item 1).

## Phase 2 — first real notebook (not started)

- `notebooks/echo_explorer.py`: dropdown over `data/*` via a *public*
  `discover_data_files()` (currently private `_discover_data_files()` in
  `viz.py` — promote it).
- **Viz gap:** add a figure-returning mode (`plot_recording(..., return_fig=True)`)
  so interactive cells don't write a PNG per slider tick; render via
  `mo.mpl.interactive(fig)` (marimo 0.24.0 has only `mo.mpl.interactive`).

## Repo hygiene

- **Commit `docs/`.** It is currently untracked (`?? docs/`). Before committing,
  run the provider's privacy scan — no absolute `/home/<user>` paths, no
  Tailscale/RFC1918 IPs, no credentials. (Redactions applied 2026-09-07-d.)
- **`.gitignore`** is missing `.venv/`, `__marimo__/`,
  `*.marimo.session_state`, `marimo.toml` (Phase 1). `outputs/` already ignored.
- **AGENTS.md** — add a short *Marimo* section (Phase 1 / DoD item 4).

## Known open questions (deferred)

- Remote/Tailscale hosting of kernel or MCP server — provider open agenda
  `marimo-inspect/docs/agenda-remote-marimo-mcp.md`, out of scope here.
- Live notebook cell-run smoke tests — blocked on the provider's
  instantiation-token gap; do not promise them here yet.
- **Sibling leak:** `python-image-processing-notebooks` tracks `marimo.toml`
  with a real vLLM base_url — needs its own fix upstream (log F2).
