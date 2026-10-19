# Four-sensor velocity — notebook review: outdated visualization and controls

**Task plan.** Written 2026-10-16; implementation started 2026-10-16 (baseline established, no notebook edit yet).
**State:** in progress. Register: [agenda](../agenda.md#selected-work). Simple by intent: this is the first slice of
returning to four-sensor work, and it is about the *tooling view*, not the physics.

## Destination

**Purpose.** Continue on the four-sensor velocity recordings by making the notebook that will display them use the
current visualization and control idioms. Today the notebooks disagree with each other and with the stated
convention: one still draws matplotlib through the legacy `.ADD` path, one still builds a scrubber the sibling notebook
deliberately removed, and the two artifact-path notebooks have drifted apart with no decision about which leads. The
recording we want to look at is four-channel, so this has to be settled before any four-sensor analysis is presented.

**Observable outcome / acceptance criteria.**

1. The current inventory is measured and written down: for each `notebooks/*.py`, its plotting API, its control types
   and the data path it rides.
2. A decision is recorded on the **leading notebook** for multi-channel work (recommendation and the reason, or the
   evidence for a different choice) — the twin pair `channel_preview.py` / `channel_preview_sidebar.py` stops being an
   open question.
3. No notebook draws through `mo.mpl.interactive` / the library's matplotlib `plot_recording` / `plot_channel_stats`,
   **or** the one that does is retired onto the artifact path with that stated as the reason. Every notebook then uses
   one plotting family.
4. `TraceScrubber` is gone from the notebooks, and gate/time selection uses one `mo.state` with step buttons
   (`−page / −1 / +1 / +page`), as the sidebar notebook already does.
5. `data/4-sensor-velocity/200RPM.BDD` (channels 6–9) can be selected in the leading notebook and its four channels
   render; the channel control enumerates 6, 7, 8 and 9.
6. `AGENTS.md` § Marimo and `README.md` no longer describe a pattern the notebooks do not use.
7. Each changed notebook passes `marimo check` **and** an executed HTML export, and the control changes are
   read back in a live session; the transitions driven are listed.

**Non-goals, and they matter here.** No alignment, resampling or estimator work: how four staggered channels get onto
one time base is a separate open decision (`docs/agenda.md` § *Unselected findings and open questions*) and the notebooks must not pre-empt it by
resampling to make a view possible. No new dependencies. No change to `analysis/` results. No notebook becomes the home
of an estimator — all computation stays in `src/`.

**Authorization boundaries.** Owner-stated intent, 2026-10-16: continue on four-sensor velocity measurement processing,
review the current marimo notebook, replace outdated visualization methods and controls. That authorises notebook,
documentation and plan edits. It does not authorise changing `src/` behaviour, deleting a notebook, or merging.

**Scope note (added 2026-10-19, at publication).** The sentence above predates the branch's current
contents. Two additions were owner-directed in the 2026-10-16 session, both recorded in this plan's
own checkpoint: the time-mode view as a **new** library module pair (`models/time_modes.py` +
`analysis/time_modes.py` — new code, no existing `src/` behaviour changed), and the optional
keyword-only `gates` selection on `process/filter.py::filter`, which *does* extend an existing
transform's signature (backward-compatibly; every gate not named keeps its values and quality bit).
This note records the position; it does not widen the boundary above, which still governs everything
the branch does not name.

**Baseline.** Original drafting revision `cfd80a2`; records reconciled 2026-10-16 at `a9d807d` on
`docs/intent-progress-pivot`, with documentation edits uncommitted and notebook implementation unstarted.
Re-verify `HEAD` and `git status --short` before
starting — the primary checkout carries an uncommitted notebook change that must be preserved, and a live marimo
session may still be running against it.

**Implementation baseline (measured 2026-10-16).** Implementation runs on branch `feat/four-sensor-notebook-review` in
a dedicated worktree created from fetched `origin/master` (`443cd1c`, the PR #71 merge) — not from the closeout branch.
The primary checkout is untouched: its explorer WIP is still uncommitted and the recovery snapshot tracked by #73 is
preserved. Draft PR #76 is **still unmerged**, so its corrections to this plan and to `agenda.md` were carried forward
verbatim in this session's documentation commit; its two other files remain with #76. The notebook under review is
byte-identical in every tree (`git hash-object` = `46f3a877`).

## Current checkpoint

**Maintained checkpoint — 2026-10-16, workflow correction (owner-authorized).**
The four-channel notebook and pair overlays exist at baseline `fa61743`; their
implementation evidence is below. They were developed by disk editing followed by
MCP inspection, not continuous MCP authoring. The owner selected correction of that
workflow: `AGENTS.md` now gates authoring on reading the provider resources, followed
by MCP-first edits in the attached live session with kernel continuity. The duplicate
personal workflow was archived outside discovery, and this profile's standing rules
now send provider-specific lessons to the owning source instead of a parallel skill.
On subsequent owner direction the obsolete upstream `marimo-pair` and
`retro-marimo-pair` consumer skills and their lock entries were also removed;
integration-log O43 owns the retirement evidence and recovery baseline.
The reusable workflow cleanup is published and merged independently in PR #77
(merge `d276d6e`); its master changes are integrated into this notebook branch.
The notebook-specific checkpoint and generated-save diff are committed locally;
the notebook branch itself is not published. Profile-local instructions and the
personal-skill archive remain local, not fleet deployment.

**Cleanup verified (2026-10-16):** checkpoint `b8c41ee` and merge `2c41add`
preserve the work and integrate PR #77. The notebook raw-byte digest is unchanged,
static checks and an executed export passed, and the same kernel process and
creation time remain live. The finished cleanup worktree and its local/remote
branch were removed; the notebook worktree is retained. The verified raw-byte
recovery archive and pre-integration backup ref remain available locally.
No additional notebook feature work or notebook-branch publication was performed.

**Published (2026-10-19).** The branch's work — the four-channel notebook, the pair overlays, the owner-directed
time-mode (SVD) view and the sidebar TV filter with its gate-scoped library `filter(..., gates=)` — is committed and
published as **draft PR #78** (`feat/four-sensor-notebook-review` → `master`, head `143b8c5`, 12 commits, 15 files,
+3149/−40). This supersedes three statements above: *"the notebook branch itself is not published"*, *"No additional
notebook feature work or notebook-branch publication was performed"*, and the checkpoint's local-only framing.
Measured at the published head: **147 passed** over `tests/test_time_modes.py` + `tests/test_artifact_filter.py`,
`ruff check src tests` clean, `marimo check notebooks` exit 0, `marimo export html` exit 0 (1.4 MB executed page), and
the whole suite at **8 failed / 3636 passed / 22 skipped** — the same eight by file and name as the pre-change
baseline on this tree, so nothing regressed. PR #76 remains unmerged and is **not** this branch's base; the branch is
off fetched `origin/master`.

A comment-only edit and restoration of `pair_captions` through guarded MCP calls
verified saving, execution, output and error read-back with the same server/kernel
process identities. The caption source is restored; marimo's generated dependency
signatures/return declarations and formatting remain as a reviewable notebook diff.
All cell bodies compare equal to the Git baseline except generated final returns;
`marimo check notebooks` passes. See integration-log O42 for scope and limits.
This is a bounded interface check, not proof that a fresh agent follows the whole loop.
No restart or external notebook patch was performed in this correction pass.

**Time-mode (SVD) view added (2026-10-16, owner-directed in session).** The owner asked for a
time-direction SVD of the notebook's heatmaps — "velocity vs gate modes". Delivered under the
corrected contract, entirely through the attached live session: the library pair
`src/udv_echo_process/analysis/time_modes.py` + `models/time_modes.py` (exported from
`analysis`, `models` and the package root, with 34 tests in `tests/test_time_modes.py`), and
three MCP edits to `notebooks/four_sensor_velocity.py` — `imports` extended, `intro` given
item 5, and two new cells (`svd_time_modes`, `svd_mode_readout`) created after `pair_captions`,
run and read back with the same kernel process. Each channel is decomposed on its own, so no
cross-channel mix and no alignment decision is touched, and the drawn quantity is each mode's
per-gate **RMS** amplitude in mm/s, so the curves are velocity-scale and the four panels share
one range. **Read revised on owner direction (same session):** the decomposition keeps the mean
(`TimeModesSettings(center=False)`), because the owner's model of the rig is a *stationary* flow
carrying perturbations, and the mean-removed form (the library default) cannot show where the
mean sits. Uncentred, mode 1 is the stationary field — measured on this fixture it reproduces the
per-gate time-mean profile at r = +0.9992…+0.9999 and holds 99.9-100% of the mean field's energy
— and modes 2-4 are the perturbations about it, measured essentially orthogonal to that mean
(|cos| ≤ 0.018), so the split is readable rather than arbitrary; mode 1 is drawn heavier and the
amplitude ratio to the secondary modes is left visible. Read back live: all four touched cells
`idle`, `get_errors` zero on both error channels, `lint_notebook` zero issues, and the readout
table's live values — stationary share 72.3-86.1%, secondary modes 4.7-7.8%, 90%/95% of the
non-stationary energy at 26-28/34-35 of the 51 remaining modes, time&depth means 27.7 / 29.4 /
21.2 / 23.8 mm/s (agreeing with the dataset README's depth-averaged means). Static gates:
`ruff check src tests` clean, 34 new tests plus the package-surface tests pass, `marimo check
notebooks` clean. The figure was inspected visually by executing the notebook's own cell body
(stub `mo`) into a standalone plotly page: title not clipped (132 chars), four panels on one
shared ±52.1 mm/s range, heavy stationary curve legible against the secondary modes, legend
intact.

**Kernel-versus-file divergence — observed, then resolved by session replacement.** The live
kernel loaded both modules before that revision (no `offset` on the helper, zeros in
`TimeModes.mean_profile`), so the readout cell derived both quantities locally — identical to what
the library returns.
The session was then replaced (fresh kernel, same notebook) and the cell
was rewritten to use them: a diagnostic cell confirmed
`offset` present and `mean_profile.mean()` = the field mean = 27.7399 mm/s on ch6, and the table's
numbers are unchanged (26/34, 28/35, 27/35, 28/35 at 90 %/95 %). Divergence and workaround both
gone, measured rather than assumed; the probe cell was deleted.

**Also on owner direction (same session): `depth_profiles_at_time` and `gate_traces_at_gate` were
removed** — the two single-channel 2x2 grids (profiles at the cursor time, traces at the cursor
gate). Both were childless in the dependency graph, so nothing else broke and no variable became
dead; `intro`'s numbered list and `notes` were reconciled so no page text still describes a view
that is gone (the notebook is 14 cells). `marimo check notebooks` exit 0, an executed HTML export
completes, and the live session shows zero errors after the deletions. The overview, both pair
overlays and the time-mode view remain.

**Time-wise TV filter added on the owner's request (same session).** The notebook's sidebar gained
a third section — a toggle plus three parameters (`λ` in mm/s, solver iteration cap, `max_gap` in
ms) — and **one parameter set drives all four channels** on purpose: the control is the filter, not
a per-channel tuning, and a per-channel weight would quietly make the pair overlays incomparable.
The work is the library's: each channel goes through `process/filter.py::filter` with a
`TvFilterSpec` (the same `ChannelBundle -> ChannelBundle` call the single-channel notebooks drive),
so the ROF solver, the segment rules and the uniformity guard stay in `src/` and the cell only
routes. The figures and the mode table now draw `signal_values` (raw unless the toggle is on) and
every figure title carries `signal_label`, so filtered data can never be read as stored profiles.
Measured on `200RPM.BDD` at λ = 1 mm/s, 200 iterations, `max_gap` 40 ms: **88 000 / 88 000 cells**
carry `FILTERED`; rms Δ = 1.13-1.18 mm/s; **max |Δ| = 2.00 mm/s exactly, i.e. a cell moves by at
most 2λ**, which is what makes λ readable in velocity units; each gate's time mean moves by
≤ 1.1e-13 mm/s (ROF is mean-preserving per segment, so the depth-averaged means the captions quote
cannot drift); and the stationary share rises slightly — ch6 86.1 → 86.9 %, ch8 81.8 → 82.9 %,
ch7 73.4 → 74.2 %, ch9 72.3 → 73.3 % — while mode 1's shape is untouched (|cos| = 1.000000,
mode 2 0.9997) and ch9's mode 3 flips sign (decomposition-internal, not a structural
change). **Structural limit, stated rather than hidden:** with the visit gap at ~372 ms, TV cannot
smooth *across* visits at all — 40 ms makes each 4-profile visit its own 4-sample segment, and any
`max_gap` that spans the gap makes the library refuse the series; the notebook shows that refusal
verbatim and falls back to the raw profiles instead of smoothing across a hole. Cross-visit
smoothing would need either a uniform grid (a resampling decision this notebook refuses) or a
visit-level series (dropping three of every four profiles) — neither is chosen here, and both are
now recorded as unselected findings. Verified: `marimo check notebooks` exit 0; an executed HTML
export exits 0 and carries the sidebar controls (each label present) while defaulting to raw; all
16 cells idle with zero errors live; every figure title read back in all three states (off / on /
refused) by executing the notebook's own cell bodies offline; and the sidebar itself inspected
visually in the live app. The live session is left with the filter **on** at λ = 1 so the owner
sees it immediately; the file's default is off.

**Nothing is overwritten, and the original is shown where it is read (owner direction,
2026-10-16).** `values` is the imported signal — the read-only arrays the reader froze, where a
write raises `assignment destination is read-only` (verified) — and the filter publishes a second
dict plus a new artifact whose parent bundle is untouched, so both fields coexist. The comparison is
drawn *inside `pair_traces_at_gate`*: the stored samples as grey markers with the plotted curve over
them (raw when the filter is off, the filtered curve when it is on), which is the cell that reads
the filtered gate. Two intermediate before|after cells were built first and **removed** on the same
direction — with a single-gate scope a four-row stored|filtered heatmap pair would have differed in
one row — so the notebook carries one comparison instead of three.

**Cost of the filter, measured (owner question).** The pass is 22 000 solver calls — 4 channels ×
55 gates × 100 visits — at ≈0.30 ms each, 6.55 s wall at the defaults; the *same* 22 000 samples
solved in one 1-D call take 1 ms, so the cost is per-call overhead, not the algorithm. The
implementation is scikit-image 0.26.0's `denoise_tv_chambolle` (Chambolle's projected-gradient ROF
solver) — stock, not custom. The repository's own *custom* TV solver (`analysis/_tv_l1.py`) is 2-D,
L1-fidelity and private to the robust-profile chain by decision D1, so it is not a drop-in here.
The iteration cap is not the lever: 200 → 30 leaves the time unchanged (6.55 → 6.58 s) and 100
gives bit-identical output, while 10 costs up to 0.16 mm/s of accuracy. A batched call cannot
preserve the semantics (skimage denoises n-D, so stacking segments would couple them), so the
remaining lever is a library-level direct 1-D solver — a numerical-kernel change with new tests and
a solver-contract decision, recorded as **unselected** rather than done unilaterally.

**Scope narrowed to the gate being read (owner direction, 2026-10-16).** The filter is now a *gate*
tool with the whole field one click away, because the cost is per-gate work and the view that reads
it is a gate: `process/filter.py::filter` gained a keyword-only `gates` selection (validated, never
silently dropped; 12 new cases in `tests/test_artifact_filter.py`), the sidebar gained a **scope**
dropdown defaulting to the cursor's gate, and `pair_traces_at_gate` draws the stored samples as grey
markers under each filtered line. Measured on this machine, four channels: **0.127-0.136 s** for the
cursor's gate (400 solver calls, 1600 of 1600 cells marked `FILTERED`, every other gate untouched bit
for bit) and **7.09 s** for all 55 gates (22 000 calls, 88 000 cells) — the note beside the figures
reports the measured time of whatever scope is selected, so the tradeoff is visible rather than
asserted. The scope is a *selection* argument on the transform, the shape `resample` takes for its
target grid, which keeps `params_json` built from `spec` alone (plan §8.3) — so it is deliberately
**not** in the recorded params, and the note says so; a scoped pass and a whole-field pass remain
distinguishable by the derived artifact's data-derived id. **The kernel was restarted for this** —
the one case the provider lists for it (an imported package's source changed): the running kernel
held the pre-`gates` `filter()`, which would have raised `TypeError` on the first call. Cost paid:
widget values back to defaults, the change tracker cleared (every cell needed a re-read), and
cell ids re-keyed — the cell created after the restart came back under the id of a cell deleted
earlier, which is why edits now confirm the returned `name` every time. Verified after the restart:
all 16 cells `idle` with zero errors, both scopes driven live and read back, `marimo check
notebooks` exit 0, an executed export exit 0, and the figures read in both scopes through the
cell-body harness (8 traces in the pair-trace figure: 4 stored-marker traces + 4 curves).

**Limits stated, not resolved:** the
caption says the perturbation spectrum is broadband and the shares are sampling-weighted; no
noise-vs-flow separation and no quadrature-pair test is performed, no mode is claimed to be a
coherent structure, and the uncentred mode 1 is an approximation of the mean (r ≥ 0.999, not the
The full suite was re-run after the gate-scope change (**8 failed, 3636 passed, 22 skipped**,
719 s) and failed for **the same 8 by file and name** as the pre-change baseline on this tree
(**8 failed, 3620 passed, 22 skipped**, 771 s): 5 screen-reading `test_acquire_dialog`/
`test_acquire_live` cases (no UDOP window in this session — session 0), 2 `test_screening_terms`
cases (a pre-existing violation at `docs/dop3000/sa5-cross-sitting-agreement-prespec.md:31`) and
`test_sparse_signal_report_verifier` (recorded source drift in `acquire/*` and `cli.py`). The +16
passing are the new gate-scope cases and the split of the two parameterised refusals, so nothing
regressed; earlier in the session the same 8 were also shown to fail with the three `__init__`
edits reverted, which is what ruled the library exports out as their cause.

**Remaining:** the placement visual and level-factor presentation decision remain
selected, joined by the question of whether the time-mode view is taken further (a pair's mode
shapes on the shared depth axis need no alignment; a *shared* mode across channels does, so it
stays behind the alignment decision); inventory/leading-notebook work remains deferred as
recorded below. The 2026-10-16 mode view was added on the owner's in-session direction as a new
library module plus notebook cells and changes no existing `src/` behaviour, so it does not
extend the earlier grant. No
alignment, estimator, merge, deployment or provider implementation is authorized by
this correction. Continue by attaching to the intended existing notebook, not by
recreating the worktree or restarting its kernel.

### Historical baseline and preconditions (before four-channel implementation)

The following inventory and initial-session observations are historical; they do not
supersede the maintained checkpoint above or select a new implementation step.

**Established (measured 2026-10-16):**

| notebook | lines | plotting | controls | path |
|---|---:|---|---|---|
| `channel_preview.py` | 811 | `mo.ui.plotly` ×4 | 10 dropdown · 5 slider · 3 number · **`TraceScrubber`** | artifact (`load()` → `ArtifactBundle`) |
| `channel_preview_sidebar.py` | 1014 | `mo.ui.plotly` ×5 | 10 dropdown · 7 slider · 4 button · `mo.state` + sidebar cascade | artifact |
| `echo_explorer.py` | 129 | **`mo.mpl.interactive` ×2** (library `plot_recording`, `plot_channel_stats`) | 1 dropdown · 2 multiselect | legacy `.ADD` (`extract` + `viz`) |
| `rpm_analysis.py` | 710 | `mo.ui.plotly` ×7 | 1 dropdown · 1 slider · 2 table | artifact |
| `signal_explorer.py` | 2052 | `mo.ui.plotly` ×8 | 9 dropdown · 5 number | artifact (sparse views) |

- `echo_explorer.py` is the only notebook on the legacy path, and the only one drawing matplotlib; its
  `discover_data_files()` is `.ADD`-only, so it cannot see `data/4-sensor-velocity/200RPM.BDD` at all.
- `channel_preview.py` still constructs `TraceScrubber` (lines 14, 156, 170); the sidebar notebook removed it precisely
  because its scrub index is browser-local and can disagree with the slider.
- The fixture: `data/4-sensor-velocity/200RPM.BDD` loads as four velocity streams, channels 6–9, 55 gates at 1.095 mm,
  400 profiles each over 44.2 s, adjacent-interval coefficient of variation 1.34; `.ADD` twins exist
  (`200RPM.ADD`, `200RPM_Stat.ADD`, `…_v2`).

**Preconditions established this session, before any notebook edit:**

- **The recommended candidate is being served, not decided.** `channel_preview_sidebar.py` runs as the *candidate* for
  the leading notebook (step 2's recommendation) so it can be reviewed; step 2's decision line is still unwritten, and
  this is not it.
- **The fixture is selectable and defaults in.** The recording picker's default is
  `data/4-sensor-velocity/200RPM.BDD`, because `io.discover_data_files()` sniffs content — 176 files (`.BDD` twins,
  `.ADD`, and one misnamed `.jpg` that is a genuine 4-channel recording) with the four-sensor `.BDD` sorting first.
  Re-measured on the file: `sequential`, device channels **6–9**, `(400, 55)` float64 per channel, first gate
  20.002 mm, `sha256:643d5d56b173…`.
- **The live notebook is healthy.** 22 cells, all `idle` with output in the running session; `marimo check` exit 0; an
  executed HTML export completed in 6.2 s with no error markers; `lint_notebook` reported no issues.
- **The step-7 verification route works on this notebook.** The MCP read path (`list_active_notebooks`, `get_cell_map`,
  `get_variables`, `get_cell_outputs`, `get_errors`, `lint_notebook`, `get_dependency_graph`, `set_active_session`) was
  exercised against the live session while a browser held it, and interaction (`set_ui_value`, `run_cell`) was confirmed
  by kernel read-back. Findings, including two provider-surface pitfalls measured here:
  [`marimo-integration-log.md`](../marimo-integration-log.md) entry 2026-10-16 (O39–O41).
- **Inconsistency found, for step 1:** the picker's label reads "Recording (.BDD, content-sniffed)" while its option
  list also holds `.ADD` files and one misnamed `.jpg`.
- **The rig is now described where the data lives** (owner grounding, 2026-10-16): the four-probe 2x2 layout with its
  channel→position map, the operator's 90°-symmetry expectation (outer 6↔8, inner 7↔9), and the measured multiplexed
  acquisition that constrains how a pair may be compared. Single homes: the mounting and the expectation in
  [`data/4-sensor-velocity/README.md`](../../data/4-sensor-velocity/README.md), the vessel/pill/flow in
  [`data/mixer-sensitivity-analysis/README.md`](../../data/mixer-sensitivity-analysis/README.md).

**Owner priority (2026-10-16).** This is the next implementation effort after the bounded documentation
publication/parking pass. No notebook implementation is part of that cleanup; re-derive the inventory before starting.

**Not established.** No notebook source has been changed. The step-1 inventory has **not** been re-derived this
session, and no decision is recorded for the leading notebook (step 2), the fate of `echo_explorer.py` (step 3) or
`TraceScrubber`'s removal (step 4). Criterion 5 is partly met only: the channel control enumerates 6–9 and channels 6,
7 and 8 rendered during probes, but the four channels were not checked as a deliberate transition series. The step-6
documentation reconciliation is untouched. Whether the live server should keep its token disabled is an open exposure
question (agenda § *Unselected findings and open questions*).

**Relevant revision / live target.** Branch `feat/four-sensor-notebook-review` at `origin/master` `443cd1c`, plus this
documentation commit; one marimo edit server serving the candidate notebook, bound to the machine's overlay address
with the token disabled. Port, overlay address, process id and notebook-session id are **machine bindings** and live in
the machine-local kit, not in this plan; the session id is re-keyable by a browser reconnect, so re-discover it
(`list_active_notebooks`) rather than caching one.

**Working state / recovery.** The implementation worktree is otherwise clean. A disposable sandbox notebook plus its own
loopback server were used for the mutating-tool verification and have been removed; the notebook under review was
confirmed byte-identical afterwards. A second, pre-existing marimo server for `signal_explorer.py` was already running
from the primary checkout on another port and was deliberately left alone.

## Steps

1. **Inventory.** Re-derive the table above from the files (do not trust this copy) and add, per notebook, which
   recordings it can already select. Output: the table in this plan's checkpoint, corrected.
2. **Decide the leading notebook.** Read both twins; the recommendation is the **sidebar** notebook as the base, since
   it carries the current selection cascade and the newer control idiom, and the agenda already records the twin
   divergence as an open decision. Either way, record the decision and the fate of the other file (retire to a pointer,
   or keep as the divergent sandbox with the reason stated). Output: a decision line here.
3. **One plotting family.** Replace `echo_explorer.py`'s `mo.mpl.interactive` cells with plotly figures consistent with
   the other notebooks, **or** retire the notebook onto `load()` → `ArtifactBundle` so it can also open `.BDD`
   recordings, and say which and why. Do not do both. Output: no `mo.mpl.interactive` under `notebooks/`.
4. **Controls.** Remove `TraceScrubber`; put gate/time selection on one `mo.state` with sliders plus
   `−page / −1 / +1 / +page` buttons, keeping one coarse step because the profile axis spans an order of magnitude
   between fixtures. Output: the control inventory in the table above, updated.
5. **Wire the four-channel fixture**, then confirm the channel control enumerates 6–9 and each channel renders.
   Output: a selected recording named in the notebook's default, and the four channels checked.
6. **Reconcile the documentation with practice.** `AGENTS.md` § Marimo currently names `mo.mpl.interactive(fig)` as the
   pattern; state what the notebooks actually do, and update `README.md`'s notebook list if a notebook's role changed.
   Output: no stated pattern that the code contradicts.
7. **Verify and record.** `marimo check notebooks` and an executed HTML export for every changed notebook; then drive
   the controls in a live session and read the dependent displays back (the kernel-side recipe is in the machine-local
   kit — a browser is needed only when interaction fidelity is the question). Update this checkpoint, the agenda row,
   and its selected entry in the agenda.

## Verification

The repository's own gates, in this order: `uv run --no-sync --extra marimo marimo check notebooks`, then
`marimo export html` per changed notebook — an export executes every cell once from a fixed default, so it proves the
static path and **cannot** prove a control transition; and finally the live read-back, with the transitions listed.
`uv run --extra dev pytest` if anything under `src/` moved (it should not). Report what could not be verified, and name
the instrument.

## Remaining work

- **Selected next (bounded): steps 1–2.** Re-derive the inventory table, then record the leading-notebook decision
  and the fate of the other twin. Stopping condition: the corrected table is in this checkpoint and the decision line
  exists — whichever outcome it records, not necessarily the recommendation. **Deferred on owner direction
  (2026-10-16):** the owner directed work straight at the four-channel data, so the notebook below was built first; this
  item is unstarted and is still the next bounded step after it.
- **Also selected (owner, 2026-10-16), riding steps 4–5 rather than adding to them:** show the four channels so the
  *pairs* can be compared, and decide how the **sensor placement** is presented — the two orthogonal mounts, the
  inner and outer probe of each, the four channel numbers, and the vortex-plus-toroid flow they sample. The
  constraint is binding: the pairs are sampled ~224 ms apart and are never simultaneous, so a pair view may put each
  channel on its **recorded timestamps** and compare level, gate profiles or spectra, but it may **not** interpolate
  or shift one channel onto another's samples — that is the open alignment decision, not a presentation choice.
  Stopping condition: a recorded decision on the placement visual, and the pair comparison shown in the candidate
  notebook with no resampling anywhere in it. It must also record **how the mount-to-mount level factor is presented**
  (raw values with the factor annotated, or normalised by a stated factor) — see the depth-profile test in
  [`data/4-sensor-velocity/README.md`](../../data/4-sensor-velocity/README.md), where the two expected-equal pairs agree
  in shape (r = +0.94 / +0.95) but differ in level by 1.31 / 1.24.
- **Landed (2026-10-16), and the pair comparison it asks for: `notebooks/four_sensor_velocity.py`.** The owner asked to
  start on the four-sensor data directly, so the four-channel view is a purpose-built notebook rather than a change to
  the candidate under review (which keeps its single-channel scope and its reviewed file identity). It carries one
  hardcoded recording (`data/4-sensor-velocity/200RPM.BDD`), a 2x2 overview of all four channels on **one shared
  colour scale**, a 2x2 grid of depth profiles at the selected time, and a 2x2 grid of gate traces at the selected
  gate; the time and gate cursors are sliders carrying the `signal_explorer.py` remembered-physical-coordinate pattern,
  and each channel's **nearest stored profile** is used and its offset from the cursor printed rather than aligned away.
  The pair comparison is drawn as **overlays** (owner direction, same day): outer 6 vs 8 and inner 7 vs 9, each pair on
  top of each other against gate depth and again against time, with one colour per channel pinned so the overlays match
  the per-channel grids and the legend naming each trace's own stored profile or recorded span. **Still open here:** the
  sensor-placement visual, and the decision on how the mount-to-mount level factor is shown. **Amended the same day:**
  the two single-channel grids named above (depth profiles at the cursor time, gate traces at the cursor gate) were
  removed on owner direction, and the time-mode view was added — see the maintained checkpoint; the bullet is kept as
  the landing record, not as a description of the notebook's current cells. The pair overlays ask the question a pair's
  *mode shapes* would also answer, which is now available on the shared depth axis.
- Then steps 3–7 and the acceptance criteria they serve.
- **Unselected, and not to be started here:** the alignment decision for the four staggered channels; any four-sensor
  estimator; the sparse explorer's own cursor work in PR #71's sibling directory.

## Decisions and evidence

- The measured notebook inventory in *Current checkpoint*; re-derive it before acting on it.
- The four-channel fixture's properties, measured on the file itself.
- The pattern source for the method this plan follows: the estate knowledge base's
  `docs/knowledge-base/dev-and-deploy/WORK-ORGANIZATION.md` (an estate document, not part of this repository),
  designated authoritative by the owner. P1 index ownership is a local trial, not evidence of general validation.
- **2026-10-16 — serving the candidate is not the step-2 decision.** The sidebar twin runs for review because the plan
  recommends it; the decision still has to be written against both files.
- **2026-10-16 — the mutating MCP tools are not exercised on the notebook under review.** Write-side verification
  (create/edit/delete/run/restart, plus the refusal shapes) ran on a disposable sandbox notebook; on this notebook only
  the read path and one restored widget transition were used, and the file was confirmed byte-identical afterwards.
- **2026-10-16 — the live server keeps its token disabled** on the overlay address, matching the existing local pattern
  for this notebook work. The exposure this creates is recorded as an open finding in the agenda rather than accepted
  silently.
- Findings from the MCP co-work verification, including two provider-surface pitfalls measured here — a *refused*
  `set_ui_value` leaves its exception in the owning cell's console-error channel while the structured error count stays
  `0`, and an integer-valued dropdown takes its option keys as strings:
  [`marimo-integration-log.md`](../marimo-integration-log.md) entry 2026-10-16 (O39–O41).
- **2026-10-16 — the rig description and the comparison constraint are recorded with the data, not in this plan:**
  [`data/4-sensor-velocity/README.md`](../../data/4-sensor-velocity/README.md) carries the operator's channel→position
  map, the 90°-symmetry expectation, and the measured multiplex pattern (4 profiles per ~448 ms visit, per-channel
  mean interval ~112 ms, visits offset 112 ms in the order 6→7→8→9), so a later session does not re-derive them. The
  vessel, pill and flow stay single-homed in the mixer-sensitivity README.
- **2026-10-16 — the four-channel notebook's verification, named.** `marimo check notebooks/four_sensor_velocity.py`
  clean; an executed HTML export whose three figures were read back at full resolution — the four heatmaps on one
  shared ±246 mm/s scale with both cursors on every panel, the four depth profiles at the cursor time each carrying its
  own timestamp and offset (ch6 +0.0, ch7 +112.6, ch8 −147.7, ch9 −35.5 ms) inside one shared y range, and the four gate
  traces at gate 27 = 49.57 mm inside a shared x/y range. Two presentation defects were found this way and fixed before
  the record was written: plotly clips a title longer than the plot area, and an unwrapped subplot title collides with
  its neighbour's. **Also verified live**, in the browser-held session served to the tailnet: all 11 cells run to `idle`
  with zero structured errors and no console exception; the time slider was moved 200 -> 100 and the kernel read-back
  showed the dependent chain actually re-run (`selected_time_s` 22.2891 -> 11.1419 s, nearest profiles 100/100/99/99,
  offsets +0.0/+111.3/-147.2/-35.6 ms) — the `mo.state` remembered-coordinate self-loop settles instead of fighting the
  widget — and the value was then restored to its declared default 200 (22.2891 s). **Not verified:** a full `pytest`
  run, because no `src/` change was made, so the suite was not re-run.

## Next session

**Restart checkpoint (2026-10-16).** The owner selected four-sensor work for a new session; no notebook
implementation occurred during closeout. PR #71 is merged (`443cd1c`). The bounded loose-end closeout is
published separately in draft PR #76 and remains unmerged; its plan/agenda corrections are not yet on `master`.
Read this plan through that published continuation before choosing an implementation baseline. Reconcile the
actual branch, HEAD and dirty state; do not implement on the closeout branch. Establish a dedicated implementation
branch/worktree from fetched `origin/master`, accounting explicitly for PR #76 if still unmerged rather than
silently assuming its records have landed. Preserve the primary checkout and the recovery snapshot tracked by #73.
No PR merge, explorer-WIP adoption, alignment, resampling or estimator work is implied by this restart.
No notebook/server launch or delegated work remains pending from closeout.

**Restart checkpoint (2026-10-16) — executed.** The dedicated worktree and branch off fetched `origin/master` exist;
the candidate notebook is served and selectable on the four-sensor fixture; the step-7 live read-back route is verified
on it. PR #76 is still unmerged, and its corrections to this plan and the agenda are carried in this session's
documentation commit. The primary checkout and the WIP snapshot are preserved, and no notebook source was edited.

**Restart checkpoint (2026-10-19) — the branch is published; resume here.** Work in this leaf
(`C:/Repos/udv-4s-notebook`) on `feat/four-sensor-notebook-review` at `143b8c5`, tracking
`origin/feat/four-sensor-notebook-review`; the working tree is **clean** and the branch is a fast-forward addition to
`master`. PR #78 is open as a **draft** — flip it to ready when the work is the thing under review. **No marimo server
or kernel is running**: the live session that made the mode view and the filter is gone and has to be started again
(the launch, address, port and session bindings are machine-local, per *What the next reader must not have to
rediscover*). That costs no state, because the notebook **file** is the artifact and it is committed. The first
bounded step is unchanged and still unstarted: **steps 1–2 of § *Remaining work*** — re-derive the notebook inventory
table, then record the leading-notebook decision and the fate of the twin.

**What the next reader must not have to rediscover.** The launch recipe, the overlay address, the port, the process id,
the notebook-session id, the sandbox that reproduces the write-side verification, and the stop path are machine
bindings and live in the machine-local kit — not in this plan. This plan keeps the state and the criteria.

**Objective (agreed, updated 2026-10-16).** Preserve the MCP-first co-work contract
while continuing the selected four-sensor presentation work: decide the placement
visual and level-factor presentation before implementing them. Inventory/leading-notebook
work remains deferred; do not infer a new priority from its old position in this plan.

**First action.** Read `AGENTS.md` and the connected provider's packaged workflow
resources, then discover and confirm the existing `four_sensor_velocity.py` session
using the machine-local target bindings. Read the full cells before live edits.
Do not relaunch a healthy server/kernel or externally patch its notebook. Report
missing resources/session/tool blockers before substituting a workflow.

**Stopping condition.** For this correction, stop once the instruction cleanup,
recoverable retirement, bounded live verification and records checks are reported
with their limits. Future product work stops at its separately agreed presentation
milestone; source behavior, alignment, resampling and estimator work remain outside
this grant. A fresh-agent full authoring trial and cross-machine rollout remain
unverified; a documentation audit alone cannot establish either.
