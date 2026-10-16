# Four-sensor velocity — notebook review: outdated visualization and controls

**Task plan.** Written 2026-10-16. **State:** authorized. Register: [agenda](../agenda.md#selected-work). Simple by intent: this is the first slice of
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

**Baseline.** Original drafting revision `cfd80a2`; records reconciled 2026-10-16 at `a9d807d` on
`docs/intent-progress-pivot`, with documentation edits uncommitted and notebook implementation unstarted.
Re-verify `HEAD` and `git status --short` before
starting — the primary checkout carries an uncommitted notebook change that must be preserved, and a live marimo
session may still be running against it.

## Current checkpoint

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

**Owner priority (2026-10-16).** This is the next implementation effort after the bounded documentation
publication/parking pass. No notebook implementation is part of that cleanup; re-derive the inventory before starting.

**Not established.** Nothing has been changed. Which notebook leads is undecided; whether `echo_explorer.py` is
modernised or retired is undecided; the live widget read-back has not been attempted this session.

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

- Steps 2–7 above, and the acceptance criteria they serve.
- **Unselected, and not to be started here:** the alignment decision for the four staggered channels; any four-sensor
  estimator; the sparse explorer's own cursor work in PR #71's sibling directory.

## Decisions and evidence

- The measured notebook inventory in *Current checkpoint*; re-derive it before acting on it.
- The four-channel fixture's properties, measured on the file itself.
- The pattern source for the method this plan follows: the estate knowledge base's
  `docs/knowledge-base/dev-and-deploy/WORK-ORGANIZATION.md` (an estate document, not part of this repository),
  designated authoritative by the owner. P1 index ownership is a local trial, not evidence of general validation.

## Next session

**Objective (agreed).** Work steps 1–7 and meet the seven acceptance criteria, or record which are unmet and why.

**First action.** Re-derive the inventory table for `notebooks/*.py`, then read both `channel_preview` twins and write
the leading-notebook decision.

**Stopping condition.** Stop when the acceptance criteria are met with evidence or explicitly unmet, the live
transitions are listed, and the plan owns the result with its agenda selection updated. Stop and hand back if step 3 turns
out to require changing `src/` behaviour — that is a different slice and a different authorization.
