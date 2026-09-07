# Hardening plan — udv-echo-process

Prioritized list of what needs to be **fixed / hardened** to tie loose ends and
give this repo a solid foundation for continued development. This is the
*action* list; the *ideas/backlog* live in [`agenda.md`](agenda.md). Priority
order: **P0** = correctness/hygiene that risks wrong results or a broken/leaky
repo today · **P1** = structure & foundations · **P2** = marimo wiring (its own
plan exists) · **P3** = polish.

Status legend: `[ ]` open · `[x]` done. Evidence: ✅ observed · 📄 documented ·
❓ inferred.

---

## P0 — Correctness & repo hygiene (do these first)

### parser — content sniffing / misnamed files
- **[ ] Guard `extract()` against non-Udv content.** ✅ Two *tracked* "data"
  files are images, not recordings: `data/echo-4-sensors-2x2/300RPM.BDD` is a
  **PNG** (1366×768) and `data/echo-4-sensors-2x2/300RPM_Stat.ADD` is a
  **JPEG** (Samsung photo). `extract()` reads them with no magic/extension
  check and would mis-parse them (or crash). Add a header guard — e.g. verify
  the first line starts with `ASCUDOPV` (mirrors `_discover_data_files()`'s
  check) and raise a clear `ValueError` otherwise. Add a regression test for
  the two known-bad files.
- **[ ] Decide the misnamed files' fate.** Either rename to their true
  extension (`.png`/`.jpg`), remove from `data/`, or move to a
  `data/echo-4-sensors-2x2/photos/` subfolder. They are currently **tracked**,
  so the fix is a rename/`git mv`, not just a local delete.

### parser — empty-data degradation
- **[ ] `describe()` on empty data.** `ExtractedData` with zero frames
  degrades (e.g. `by_channel()[...]` empty → `ch_frames[0]` IndexError in the
  channel loop; `meas_type` returns `None`). Return a clear "no frames parsed"
  description instead of raising. Test: `extract()` of a header-only file.

### rpm — channel mixing & magic constants
- **[ ] `rpm_from_echo` currently flattens *all* channels** into one spectrum
  (`np.array([f.values for f in extracted.frames])`), which is wrong for
  multi-sensor data (channels 6–9 would be concatenated as if one series).
  Route by `extracted.by_channel()`, or document+assert single-channel-only
  input. Add a multi-channel regression test.
- **[ ] `DT_S = 0.0032` magic constant** in `run_all.py` — the sampling
  interval is hard-coded. Derive it from the parsed data (mean of
  `diff(tbd_ms)/1000`) or expose it as a parameter; at minimum document where
  it comes from.

---

## P1 — Structure & foundations

### scope — remove the stale optical/camera duplicate
- **[ ] Delete the optical/camera modules — the canonical, further-developed
  copy already lives in the sibling repo.** ✅ Verified 2026-09-07: the image
  repo's `src/image_processing_lib/{mixer,motion,projection}.py` are direct
  ports *from* this repo's `analysis/{mixer,feature_track,temporal_projection}.py`
  and have **advanced past** them (stage-split `crop_mask`/`image_roi_box`/
  `pipeline_preview`, `bit16` de-flicker, `frames.py`/`export.py`, and the
  `mixer_pipeline.py`/`mixer_preview.py` notebooks covering stages 3.2–3.9).
  This repo's copies are the stale **originals** (committed 2026-08-18, one day
  before the sibling's further work). **Do not port them "forward" — that would
  regress the sibling.** Remove:
  - `src/udv_echo_process/analysis/mixer.py`
  - `src/udv_echo_process/analysis/feature_track.py`
  - `src/udv_echo_process/analysis/image_projection.py`
  - `src/udv_echo_process/analysis/temporal_projection.py`
  - `tests/test_mixer.py`, `tests/test_feature_track.py`, and the
    `test_temporal_projections_*` block + `_synthetic_stack` helper in
    `tests/test_analysis.py`
  - `udv-project` / `udv-mixvel` console scripts (`pyproject.toml`) and
    `project_main` / `mixvel_main` in `cli.py`, plus their imports
  - the matching re-exports in `analysis/__init__.py` and the top-level
    `__init__.py` (keep `rpm.py` and any UDV-signal tooling).
  - `references/wolfram/README.md` porting-map rows for `Mixer_velocimetry.nb`
    / `TemporalProjections_v1.1.0.wl` — ✅ **already done 2026-09-07**: both
    files were moved to `python-image-processing-notebooks/references/wolfram/`
    (with a new porting-map README there) and removed from this repo's
    `references/wolfram/` + its README.
- **[ ] Before deleting, check two small helpers not verbatim in the sibling.**
  `analysis/image_projection.py` also defines `project_images()` (folder →
  lazily-loaded projections) and `save_projections()` (min-max-normalized PNG
  dump). The sibling covers these functionally (`frames.py` loaders +
  `temporal_projections((get_chunk, n))`; the notebook's inline `_u8()` dump),
  but not as named functions — confirm nothing else needs them, then delete
  without porting (or port only if a real gap shows up).

### Conventions mismatch: dataclasses vs Pydantic
- **[ ] `RpmResult` (`analysis/rpm.py`) and `TemporalProjectionResult`
  (`analysis/temporal_projection.py`) are `@dataclass`es**, while the repo
  convention (AGENTS.md, README) is "Pydantic `BaseModel` for all data
  structures". Decide and migrate both to `BaseModel` (note:
  `TemporalProjectionResult` holds `np.ndarray` fields — Pydantic v2 supports
  this via `ConfigDict(arbitrary_types_allowed=True)` or `numpy` typing), or
  explicitly amend the convention. Do **not** add new dataclasses meanwhile.

### viz — figure-returning mode (blocking marimo interactivity)
- **[ ] Add `return_fig` / figure-display path to `plot_recording`,
  `plot_channel_stats`, `plot_all`.** Today they `savefig()` + `plt.close()`
  and return a `Path` — ✅ confirmed (log F7) this renders nothing in a
  notebook cell. Needed for Phase 2 notebooks; render via `mo.mpl.interactive`
  (marimo 0.24.0 exposes only `mo.mpl.interactive`).

### viz — promote the discovery helper
- **[ ] Promote `viz._discover_data_files()` to a public `discover_data_files()`**
  (✅ confirmed private, log F9). It's the whole-`data/` recursive scan (validates
  the `ASCUDOPV` magic line) the notebook dropdown needs. Re-export from the
  package `__init__`.

### package surface / naming audit
- **[ ] `analysis/__init__.py` re-exports `enrich_particles` and `tone_map`
  but the top-level `__init__.py` does not** — the public surface is
  inconsistent. Decide the canonical export list (top-level should mirror
  `analysis` for the ported features) and add a test that imports the whole
  `__all__`.
- **[ ] `parser.py` carries backward-compat aliases** (`parse_add_file`,
  `parse_stat_add_file`, `load_all_data`, `list_stat_add_files`) that are thin
  wrappers. Keep (documented) or drop; at minimum list them explicitly in
  `__all__` (today they're exported but not all declared).

---

## P2 — Marimo integration (plan exists: `docs/marimo-integration-plan.md`)

- **[ ] Phase 1 — pin the provider.** Add `marimo[recommended]>=0.24.0,<0.25`
  + `marimo-inspect` (git tag `v0.2.0` — ✅ tag now exists) to `pyproject.toml`;
  commit `uv.lock` (expect ~250-entry re-resolution diff). Pre-sync to avoid
  the ~13 min cold start (log O18).
- **[ ] `.gitignore` — marimo runtime files.** ✅ Done 2026-09-07 (this pass):
  added `.venv/`, `__marimo__/`, `*.marimo.session_state`, `marimo.toml`.
  Track a placeholder `marimo.example.toml` (no real endpoint/key) when Phase 1
  lands.
- **[ ] Re-verify O16 (auto-bind) / O17 (list-args) / O15 (headless discovery)**
  against the installed v0.2.0 build — see `agenda.md` §2 Phase 1.

---

## P3 — Polish

- **[ ] Formatter/linter.** No ruff configured here. Add `ruff` (dev extra) +
  a `[tool.ruff]` config once `notebooks/` exists; exclude `notebooks/` from
  ruff like the sibling, and run `ruff check`/`ruff format` on `src/` + `tests/`.
  (AGENTS.md "no formatter configured" line then updates.)
- **[ ] README scope statement.** README describes "multi-sensor UDV …
  rotating machinery" but the tree also ships the optical mixer port; add a
  one-line scope note (or a "camera/optical tooling is a deferred sibling
  concern" caveat) matching AGENTS.md §Scope boundaries.
- **[ ] `DOPpy` cross-check experiment** (P3→ when `.BDD` work starts): decode
  the `.ADD`/`.BDD` twins and compare gate depths / PRF to validate both paths
  (see `doppy-analysis.md` §Relevance).

---

## Baseline (verified this pass)

✅ `uv run --extra dev pytest` → **32 passed** (with `UV_CACHE_DIR=/tmp/uv-cache
MPLBACKEND=Agg`). ✅ Working tree clean. ✅ `marimo-inspect` `v0.2.0` tag
exists. ⚠️ `marimo.example.toml` and `notebooks/` do not exist yet (expected —
Phase 2). ⚠️ `.venv/` was only incidentally ignored via uv's internal
`.venv/.gitignore`; now explicitly ignored.
