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
- [x] **Guard `extract()` against non-Udv content.** ✅ Two *tracked* "data"
  files are images, not recordings: `data/echo-4-sensors-2x2/300RPM.BDD` is a
  **PNG** (1366×768) and `data/echo-4-sensors-2x2/300RPM_Stat.ADD` is a
  **JPEG** (Samsung photo). `extract()` reads them with no magic/extension
  check and would mis-parse them (or crash). ✅ **Done 2026-09-07:** `extract()`
  now verifies the first line starts with `ASCUDOPV` and raises a clear
  `ValueError` otherwise (mirrors the discovery magic check); malformed /
  truncated sections yield an empty `ExtractedData` instead of crashing.
  Regression tests cover image/binary/empty files (incl. the two known-bad
  names should they ever return).
- [x] **Decide the misnamed files' fate.** ✅ **Done 2026-09-07 (rename in
  place):** `git mv` → `data/echo-4-sensors-2x2/300RPM.png` and
  `data/echo-4-sensors-2x2/300RPM.jpg`. No false `.ADD/.BDD` recording signals
  remain; the discovery scan only matches `*.ADD` + magic anyway.

### parser — empty-data degradation
- [x] **`describe()` on empty data.** `ExtractedData` with zero frames
  degrades (e.g. `by_channel()[...]` empty → `ch_frames[0]` IndexError in the
  channel loop; `meas_type` returns `None`). ✅ **Done 2026-09-07:** `describe()`
  returns a clear "No frames parsed" block when `frames` is empty. Test:
  `extract()` of a header-only file.

### rpm — channel mixing & magic constants
- [x] **`rpm_from_echo` currently flattens *all* channels** into one spectrum
  (`np.array([f.values for f in extracted.frames])`), which is wrong for
  multi-sensor data (channels 6–9 would be concatenated as if one series).
  ✅ **Done 2026-09-07:** `rpm_from_echo` now raises `ValueError` for
  multi-channel input (documented single-channel-only; route per channel via
  `by_channel()`). Multi-channel regression test added.
- [x] **`DT_S = 0.0032` magic constant** in `run_all.py` — the sampling
  interval is hard-coded. ✅ **Done 2026-09-07:** new
  `mean_sample_interval_s()` derives it from the parsed TBD column (mean of
  `diff(tbd_ms)/1000`); `rpm_from_echo`/`collect_results`/`run_all.main` take
  it as an optional parameter and default to the derived value. The old
  constant is gone.

---

## P1 — Structure & foundations

### scope — remove the stale optical/camera duplicate
- [x] **Delete the optical/camera modules — the canonical, further-developed
  copy already lives in the sibling repo.** ✅ Verified 2026-09-07: the image
  repo's `src/image_processing_lib/{mixer,motion,projection}.py` are direct
  ports *from* this repo's `analysis/{mixer,feature_track,temporal_projection}.py`
  and have **advanced past** them (stage-split `crop_mask`/`image_roi_box`/
  `pipeline_preview`, `bit16` de-flicker, `frames.py`/`export.py`, and the
  `mixer_pipeline.py`/`mixer_preview.py` notebooks covering stages 3.2–3.9).
  This repo's copies are the stale **originals** (committed 2026-08-18, one day
  before the sibling's further work). ✅ **Done 2026-09-07:** removed
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
    `__init__.py` (kept `rpm.py` and the UDV-signal tooling). Deps that only
    the optical modules used (`opencv-python`, `Pillow`, `scikit-image`) were
    dropped from `pyproject.toml` + re-synced `uv.lock`.
  - `references/wolfram/README.md` porting-map rows for `Mixer_velocimetry.nb`
    / `TemporalProjections_v1.1.0.wl` — ✅ **already done 2026-09-07**: both
    files were moved to `python-image-processing-notebooks/references/wolfram/`
    (with a new porting-map README there) and removed from this repo's
    `references/wolfram/` + its README.
- [x] **Before deleting, check two small helpers not verbatim in the sibling.**
  `analysis/image_projection.py` also defines `project_images()` (folder →
  lazily-loaded projections) and `save_projections()` (min-max-normalized PNG
  dump). ✅ **Done 2026-09-07:** nothing else in this repo referenced them —
  deleted without porting (sibling covers the functionality).

### Conventions mismatch: dataclasses vs Pydantic
- [x] **`RpmResult` (`analysis/rpm.py`) and `TemporalProjectionResult`
  (`analysis/temporal_projection.py`) are `@dataclass`es**, while the repo
  convention (AGENTS.md, README) is "Pydantic `BaseModel` for all data
  structures". ✅ **Done 2026-09-07:** `TemporalProjectionResult` left with the
  deleted optical modules; `RpmResult` migrated to Pydantic `BaseModel`. No
  dataclasses remain in the package.

### viz — figure-returning mode (blocking marimo interactivity)
- [x] **Add `return_fig` / figure-display path to `plot_recording`,
  `plot_channel_stats`, `plot_all`.** ✅ **Done 2026-09-07:** all three accept
  `return_fig=True` and hand back the open `matplotlib` figure(s) instead of
  `savefig()` + `plt.close()` (default behaviour unchanged). Notebooks render
  via `mo.mpl.interactive(fig)` (marimo 0.24.0 exposes only
  `mo.mpl.interactive`). Tests lock in both save and figure-returning paths.

### viz — promote the discovery helper
- [x] **Promote `viz._discover_data_files()` to a public `discover_data_files()`**
  (✅ confirmed private, log F9). ✅ **Done 2026-09-07:** public
  `discover_data_files(data_root="data")` (whole-`data/` recursive scan,
  validates the `ASCUDOPV` magic line), re-exported from the package
  `__init__`; `cli.viz_main` and the new test use it.

### package surface / naming audit
- [x] **`analysis/__init__.py` re-exports `enrich_particles` and `tone_map`
  but the top-level `__init__.py` does not** — the public surface is
  inconsistent. ✅ **Done 2026-09-07:** the optical exports left with the
  deletion; `analysis/__init__.py` now exports only `rpm` and the top-level
  `__init__` mirrors `analysis` (+ parser + viz) exactly. New
  `tests/test_package_surface.py` imports the whole `__all__` (top level,
  `analysis`, `parser`, `viz`) and asserts top-level ↔ subpackage parity.
- [x] **`parser.py` carries backward-compat aliases** (`parse_add_file`,
  `parse_stat_add_file`, `load_all_data`, `list_stat_add_files`) that are thin
  wrappers. ✅ **Done 2026-09-07:** kept (documented as backward-compat) and
  listed explicitly in a new module-level `__all__`; covered by the
  surface test.

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
- [x] **README scope statement.** README describes "multi-sensor UDV …
  rotating machinery". ✅ **Done 2026-09-07 (verified):** after the P1 optical
  removal the README intro, usage and architecture tree are already UDV-only —
  no camera/optical tooling is implied anywhere, so no caveat note is needed.
  (AGENTS.md §Scope boundaries is current.)
- **[ ] `DOPpy` cross-check experiment** (P3→ when `.BDD` work starts): decode
  the `.ADD`/`.BDD` twins and compare gate depths / PRF to validate both paths
  (see `doppy-analysis.md` §Relevance).

---

## Baseline (verified this pass)

✅ `uv run --extra dev pytest` → **34 passed** (with `UV_CACHE_DIR=/tmp/uv-cache
MPLBACKEND=Agg`). ✅ Working tree clean after this pass's commits: `f63684c`
(P0), `315d3ee` (P1 code), and the P0/P1 doc update commit. ✅
`marimo-inspect` `v0.2.0` tag exists. ⚠️ `marimo.example.toml` and
`notebooks/` do not exist yet (expected — Phase 2). ✅ `.venv/`,
`__marimo__/`, `*.marimo.session_state`, `marimo.toml` explicitly gitignored.
⚠️ Runtime deps slimmed to numpy/matplotlib/pydantic (opencv/Pillow/
scikit-image removed with the optical modules).

### Remaining open (P2, P3)
- P2 — pin `marimo[recommended]` + `marimo-inspect` (v0.2.0) and commit the
  re-resolved `uv.lock`; track `marimo.example.toml`; re-verify O15–O17 against
  the installed v0.2.0 build.
- P3 — ruff config + format sweep; DOPpy cross-check when `.BDD` work starts.
