# DOP3010 acquisition — handoff (2026-09-17)

State of the automation work: what is proven, what is broken, and exactly what to do
next. Written for a fresh session starting in this repository.

> **Authority (added 2026-09-18, documentation freeze).** This document is the
> **state-of-the-work and measurement record**: what was proven, when, on which machine, and
> what to do next. It is not the authority for architecture and invariants
> ([`acquisition-architecture.md`](acquisition-architecture.md)) or for surfaces, widgets and
> bindings ([`acquisition-ui-model.md`](acquisition-ui-model.md)), and it is not the device
> verification procedure ([`device-verification.md`](device-verification.md)) — a fact about
> a surface below is a measurement made on a date, not the current model of that surface.
> Nothing in the body changed at the freeze; this header is the only edit.

## Current state and next actions (2026-09-25)

The state a fresh session needs before reading anything below. **§1's checkout, branch and
test-count facts are from 2026-09-17 and are superseded by this section.**

**Merged.** `master` is `5538b43`: both acquisition slices and the analysis track's first gate,
each reviewed externally (the review dispositions are in the PR bodies).

| slice | merge | what it delivers |
|---|---|---|
| **B5** — job-boundary burst transitions | `7209609` (PR #38) | the runner transitions the burst between jobs from the plan, with the ordered `burst_transitions` history, resume at an already-correct burst, and refusals ordered **before** any instrument gesture |
| **B6** — stored-artifact verification | `33dbb44` (PR #39) | stored **word 8 is an unconditional burst oracle** (a mismatch invalidates the point, whatever `check_covariates` says); stored **word 27** is carried as receiver-bandwidth-definition provenance only — compared with nothing, never written, no millimetre derived |
| provenance design proposal | `426dd5a` (PR #40) | `failed-invocation-provenance.md`, **no implementation**: what a verified write followed by a refusal loses, the rejected options, and the accepted recommendation |
| **SA0** — sparse ingest and explorer | `5538b43` (PR #41) | the cross-realization signal-analysis plan (merged separately as PR #36 at `43c4a87`, revised by #41) and its first implementation gate: a pass-general sparse ingest whose identity derives from its inputs, its guards, `notebooks/signal_explorer.py`, and one pass-identity rule shared by the frozen and interactive readers |

**Proven, live.** Four job boundaries of the nine-job portable plan ran on 2026-09-25 with no hand
change: `10 → 4 → 10 → 18 → 10`, effective Sampling volume read back `1.776 / 1.850 / 3.330 /
1.850 mm`, word 27 constant at `1`, 12 stored BDDs whose word 8 matches each job. Evidence and
hashes: [`../../data/burst-commissioning-b5/`](../../data/burst-commissioning-b5/README.md).

**Verification is per-package, not a repository-wide property.** Only `data/burst-commissioning-b5/`
ships an executable instrument-free verifier: `verify.py` re-derives the plan fingerprint, each
executed job's definition fingerprint and point list, every recording's SHA-256, its stored
operation words and its decoded configuration, and its docstring states what it *cannot* re-derive
(the dialog transition objects and the compilation identities, whose inputs stay local because they
carry machine paths). The other evidence packages (`burst-commissioning-b4/`, `stage2-e20-e64/`,
`sparse-mixer-*`) commit artifacts and a README, not a verifier; B6's evidence is the test suite plus
its own mutation check. Say **which** package carries a verifier; do not attribute one to "the
committed evidence" in general.

**Not claimed.** The equal-burst/no-write path is offline-verified only (review accepted: it
performs *less* device interaction, not an unknown gesture). Mutation provenance across a refused
invocation is a real gap and is **not** covered by anything merged. A bandwidth other than `1` has
never been observed in word 27. No offline test establishes live behaviour.

**Next actions, in order.**

1. **SA1 first — let the science pay back the engineering.** Two 26-recording mixer-enabled sittings
   are committed and nothing in the acquisition layer blocks them: get per-gate profiles, traces and
   recurrence diagnostics onto both sittings and ask whether UDV settings explain the reported
   20–40% CFD discrepancy and the apparent ~1 s vortex motion. Report each sitting's contrast
   separately; two sittings are a reproducibility check, not a population claim, and gates/profiles
   are correlated samples, not independent replicates.
2. **Implement the provenance recommendation** (PR #40's document) — offline, no instrument: append
   the verified transition to the job's own log at the boundary under an explicit occurrence
   identity, fail closed if the append cannot be written, refuse a log carrying an unknown entry
   type. The document carries the sketch, the record fields and the tests it obliges. Revisit a
   pipeline-wide journal only when a *second* independently owned instrument mutation enters the
   automated path.
3. **Then formalize B7/B8** — the plan's definitions are authoritative and are not to be restated
   loosely: **B7** is a miniature automated burst campaign (`4 / 10 / 18 / 10`, all recordings and
   the restoration verified) and **B8** is the next sparse experimental run using it
   (`burst-length-control-plan.md` §4). Nothing in the plan is an instrument-free *dry run*; do not
   reintroduce that reading.
4. **At the instrument** (operator present, interactive session): the **five remaining jobs** of the
   portable nine-job plan (`emissions-8/64/128` plus the two references — 14 recordings). They
   request a *manual* emissions change, which is why the 2026-09-25 pass stopped after job 4. Drive
   job boundaries with `run-plan --next`; never set the burst by hand.

**Direction review (2026-09-25).** An external review judged this direction **sound** and reordered
the work, which the list above now reflects. Its strongest counter-argument: the project risks
over-investing in acquisition-provenance machinery **before** the two high-value live datasets are
exploited scientifically — so SA1 runs in parallel with the provenance work rather than after it.
That does not make the acquisition work wrong; it stops provenance completeness from gating signal
analysis. **What would reverse the order:** if SA1 shows the conclusions dominated by unexplained
acquisition-state inconsistency — nominally identical common-reference records differing in a
state-dependent way that the existing manifests and logs cannot trace — acquisition provenance, and
likely the full journal, comes first again. **Guardrails the review named as not to be "improved":**
no generic `Operating parameters` dialog editor; no word-27 → millimetre derivation; no statistical
merging of the two sittings; no global mutation journal for architectural uniformity; the notebook
stays a wrapper, never the computation layer; no forced `.ADD` → artifact bundle adapter until a real
cross-pipeline scientific use case demands one. **On the record:** word 27 may stratify or report
acquisition state; it must not feed spatial resolution, effective sample volume, uncertainty or
weighting until an independent relation is measured.

**Working in this repository.** Gates are `uv run --no-sync --extra dev pytest -q` (2655 passed /
22 skipped at `5538b43`; it was 2632 / 22 at `33dbb44`, before SA0's tests landed), `uv run --no-sync --extra dev ruff check src tests`, and
`uv run --no-sync python tools/check_screening_terms.py`. Two traps cost a session real time on
2026-09-25: a fresh worktree needs `uv sync --extra dev --extra acquire` before the acquisition
tests can run at all (`ModuleNotFoundError: win32con`), and **copying a `.venv` between worktrees
leaves an editable install pointing at the other tree** — re-sync after the copy and check with
`python -c "import udv_echo_process; print(udv_echo_process.__file__)"`.

## 1. Where the work lives

- *(Superseded 2026-09-25 — see the section above for the current checkout and `master`.)*
  `C:\Repos\udv-echo-process`, branch **`feat/dop3010-acquisition`**, pushed to origin;
  `master` untouched at `ef8b0e5`. Working tree clean.
- Commits, newest first: `1395887` (ClipCursor + real-click entry), `33e1e0c` (geometry
  entry matching), `c9b2e55` (real-hover channel selection), `6659412` (posted held
  press for the menubar), `f1068c9` (sweep runner), `4f4221e` (lint), `92eb024`
  (acquire core, docs, BDD pin).
- Package `src/udv_echo_process/acquire/`: `plan.py`, `config.py`, `log.py`,
  `actuator.py` (the pure Protocol), `driver.py` (`Win32Actuator`), `runner.py`
  (`SweepRunner`), `verify.py` (artifact verification).
- Tests ~1,420 pass; the acquire set ~300; ruff clean. Pre-existing failures unrelated
  to this work: `tests/test_storage_npy.py` (~35) and
  `test_io_bdd_artifacts.py::test_canonical_depth_ids_round_trip_through_storage` —
  `PermissionError` from `storage/npy.py::_fsync_dir` (`os.open` on a directory).
- **Retired 2026-09-18** — Campaign repo (was `~/Repos/dop-control`, never a git repo): its
  `recon/` held the probes that are the source of truth for the application's behaviour,
  `docs/16-record-strip-automation.md` the verified UI rule set, `recon/out/` the captures and
  JSONL logs. It is now **`~/Repos/_archive/dop-control-20260918.zip`** (498 files, integrity
  verified); the tooling moved to `tools/live/` and `acquire/`, and the findings to
  `docs/dop3000/`. Both the store directory it was doubling as and what was never ported are
  recorded in [`recon-archive-retirement.md`](recon-archive-retirement.md).

## 2. The immediate task — port the menu interaction VERBATIM — **PORTED (2026-09-17)**

Source of truth: `recon/41_burst_sampling_volume.py` **in the retired archive**
(`~/Repos/_archive/dop-control-20260918.zip`; see
[`recon-archive-retirement.md`](recon-archive-retirement.md)),
`open_operating_parameters()` (lines 109–135), plus `udop_roles.py` (`click_hold`,
`resolve`, `children`, `combo_state`, `text_of`). This code opened the menu, selected
`Operating parameters`, read the dialog, changed a combo, and accepted — repeatedly.

**Landed in `acquire/driver.py`** (uncommitted at the time of writing — see §4), and
**verified live on 2026-09-17** (see §5a: the menu cycle opened, read and closed cleanly,
three times, including one run that recovered the dialog this port had left open):

- the entry press is the **posted held press on the entry's own handle**
  (`GESTURE_POSTED_PRESS`, `_press_entry` → `_click_hold`); the real-click path is gone,
  together with `_real_click_centre`, `GESTURE_REAL_CLICK` and the mouse-button flags;
- **the bottom button pair is the LAST TWO of the band** — `row[-2]` is Cancel/`No` and
  `row[-1]` is Accept/`Do store`, which is the reference's own rule
  (`recon/41`: `bottom[-1] if accept else bottom[-2]`). The port had used `row[0]`, the
  band's *leftmost*: on the live dialog that is an **indicator** button
  (`No emission on Probe In/Out`) and pressing it left the dialog open. Found and fixed
  from the live run; never press the band's leftmost;
- the popup **visibility precondition** is enforced twice: the overlay poll only ever
  returns a visible panel, and `_require_visible_popup` refuses an overlay or entry that
  reports `IsWindowVisible == False`, naming the pre-created panel (`_hidden_panels()`,
  `_is_visible()`);
- **dialogs are found structurally** (`_dialog_panels` / `_poll_dialog`): not the
  parameter column, wider than 400 px, and full of controls (`>= 15` direct children, a
  `TSp_Browse`, or input controls of its own). The channel combo is now only the test
  that tells the operating dialog from another dialog, never the test that decides
  whether a dialog opened;
- the **channel combo's nesting was dropped**: identity is the item list (`'1'`..`'10'`).
  The live dialog holds it in its **header** — a direct child of the panel at
  `(1083, 373)`, read from the watch capture — so requiring a `TSp_Value_Button` around
  it was an assumption that could reject the correctly opened dialog;
- the **overlay is identified by the reference's own predicate first** (`left == 169 and
  h > 120`, when visible); this port's appearance diff is demoted to the fallback for an
  overlay painted elsewhere. An addition must never outrank the proven rule;
- the **combo write settles for the reference's 0.8 s** (`_COMBO_SETTLE_S`), not the
  shorter text-write settle: this is the path that decides the channel;
- the per-entry dialog window is the reference's own 8 s (`_ENTRY_DIALOG_TIMEOUT_S`), not
  a re-derived 2 s. **The retry that walked down the popup is gone: one entry is pressed,
  the topmost.** The second entry is `Default parameters`, and the manual's rule is "the
  default parameters select the assisted mode" (doc 04) — so a retry to recover from a
  transient failure switched the instrument's mode on, silently, while the popup (and its
  cursor clip) was up. The reference never pressed more than the entry it meant. The
  measured cost is in the mode section below; the guard is
  `_assert_assisted_unchanged`;
- the entry-attempt record is read **before** the press (`_pressed_state`): after it the
  popup is gone, and the record of a press that worked said `overlay_visible: false`,
  `overlay_items: 0` — a record worse than none.

Tests: `tests/test_acquire_driver.py` — the fake carries the **live-measured** dialog
(627x384 at `(655, 364)`, its header channel combo, seven value fields, and a bottom band
of **four** buttons: the two indicators, then `Cancel` `(1091, 703, 80x25)` and `Accept`
`(1183, 702, 80x25)`), so the old `row[0]` bug now fails the suite instead of the
instrument. 123 driver + actuator cases green, `ruff check` clean (the fake now scripts the
live replacement dialog too, so the stale-handle bug is a suite failure and not an instrument
one).

Original instructions, kept for the record:

**The entry press is `click_hold(entry_hwnd)`** — a *posted* held press
(`WM_LBUTTONDOWN` with `MK_LBUTTON`, ~180 ms, `WM_LBUTTONUP`) on the entry's **own
handle**. It is *not* a cursor move followed by a click. A recent fix replaced it with a
real click; the menu then opened and the entry was never pressed, which is the whole
failure. Restore the posted held press as the primary gesture.

**Dialog identification is structural**: a panel with `>= 15 children` or containing a
`TSp_Browse`, and width `> 400`. The driver currently requires the presence of the
channel combo, which is stricter than the evidence and can reject a correctly opened
dialog.

**Bottom buttons** sorted by `left`: leftmost is `Cancel`, rightmost is `Accept`. Never
press Accept on a dialog that has not been identified.

**The hover**: `SetCursorPos(204, 40)` → 0.3 s → `mouse_event(MOUSEEVENTF_MOVE, 2, 0, 0, 0)`
→ 1.0 s. The driver derives the point from a resolved rect instead — pin it to the
measured point, or require the overlay to *become visible* as proof the hover worked.
(The derived centre *is* that point: the `Parameters` button's rect centres on
`(204, 40)`. The appearance proof is what the driver now relies on, since a coordinate
stated in logic is not allowed in this codebase.)

**Precondition before pressing any entry**: the overlay panel must report
`IsWindowVisible == True`. The panel `(169, 55, 401, 250)` is **pre-created in the control
tree with `visible = False`**. Presence is not visibility; a rule that accepts presence
will click real coordinates into empty screen, which is what happened.

**No window activation anywhere.** The overlay opens on an unfocused application and it is
sticky — it survives activation and needs an explicit close.

## 3. Verified facts (measured on the instrument, not inferred)

- **Word map** — uint32 little-endian, 256 words per channel, stride 1024, channel 1 at
  byte offset 548 (`548 + (c-1)*1024`): 2 = depth mm; 5 = PRF µs; 8 = burst; **10 =
  0-based resolution rung index, `resolution_mm = (idx+1) * c / 12000`**; 13 = gates;
  14 = emissions; 19 = sound speed m/s; 27 = sampling-volume index (identity unresolved
  against the manual's bandwidth); 11/12 = auto flags (both 1).
- **Depth law** — the window's *end* is `first_gate + gates * resolution` as the application
  derives it; the **stored word** (`word 2`) is the depth of the window's **last** gate,
  `first_gate + (gates - 1) * pitch`, rounded to the integer that word holds. Measured on the
  committed sweep (`data/mixer-sensitivity-analysis/4MHz/0500RPM/001`: 40 files, 13 distinct
  gates × resolution pairs) the last-gate form reproduces every stored word, the window-end
  form 4 of 40 floored and 2 of 40 rounded — no single first gate fits the window-end form.
  The two differ by exactly one pitch, which is under the 1.5 mm file-check tolerance at the
  fine rungs (0.12-0.49 mm) every earlier campaign ran at and over it at this pass's 1.85 mm
  and 2.96 mm rungs. The first gate is dialog-only and not stored.
- **Write order matters** — resolution first, then gates; writing gates first clamps them
  (words 11/12 set auto resolution and auto gate count).
- **The chain works** — record → stop → store → confirmed file, unattended, strip back to
  `ready/3` (three buttons, no slider) every time. Three points recorded by the driver:
  805 / 403 / 201 gates at 100 mm, c = 1460.
- **Block hygiene** — a point recorded into a buffer still holding ~6,000 stale profiles
  was stored as **8,272,897 B** where ~90 KB was expected, looked like a valid `.BDD`, and
  the status bar showed large **negative** time-between-profile values. One
  `Clear and restart` before the point produced a clean 87,281 B (64 profiles). Reset
  before every independent point.
- **Size signature** — roughly 1.7 bytes per gate-profile at the calibration
  configuration; use it as a *gross* factor check (the contamination cases were 10× and
  60×), never as a precise expectation. For reference, `466 B/profile + 1.20 B/gate` fits
  three clean points within 0.2%, but the profile count depends on the achieved period.
- **The dialog's own geometry (read off the watch capture, 2026-09-17)** —
  `Operating parameters` is a `627x384` panel at `(655, 364)`, holding seven
  `TSp_Value_Button` value fields, four `TSp_Button`s (two checkboxes and the bottom row)
  and its channel combo. That combo is the dialog's **header** field,
  `Operating parameters for channel [n ▼]`, a `TComboBox` at `(1083, 373)` that is a
  **direct child** of the panel — *not* nested in a value field, which is what an earlier
  driver revision wrongly required.
- **The overlay holds five entries** (screen tops 61, 95, 130, 165, 205 inside the
  `169, 55, 401, 250` panel); the first is `Operating parameters`, the second
  `Default parameters`.
- **Profile period** — the manual gives `T_profile ≈ T_tran + T_prf * (16 + N_PRF)`, and
  word 17 = 16 in every file, which corroborates it. Its two terms are separate: at 600 µs PRF
  `16 * T_prf` is 9.6 ms, while the 10.369 ms intercept the committed sparse files measure is
  that plus a ~0.77 ms transfer term. Compute the period from the point's parameters
  (`acquire/plan.py::profile_period_s`, the whole law); log the achieved value once per
  configuration as a certificate. The ported doc's §8 has been corrected accordingly
  (`docs/dop3000/udop-automation.md`, as have the two code comments that repeated the withdrawn
  "measure it, don't trust the formula" line: `acquire/plan.py::profile_period_s`,
  `acquire/config.py::ProfileTiming`).
- **One channel is the scope.** Everything measured on channel 1, c = 1460. The channel is
  a single knob: `UDV_CHANNEL` → `ChannelSetting` (default 1, range 1–10).
- **Store dialog** — its `Working directory` field decides where points land (currently
  `C:\REPOS\DOP-CONTROL\RECON\OUT\CAPTURE`); it persists. Names must be unique: a repeat
  raises a `No`/`Yes` overwrite panel, and the correct response is the **left** button
  (`No`). The dialog also sets `ClipCursor`.
- **ClipCursor** — this application clips the cursor while its popups are open, and a
  clipped `SetCursorPos` is clamped *silently*; that pinned the operator's cursor into the
  dropdown's corner and made the entry loop's re-hover impossible. Read the clip, release
  it with `ClipCursor(NULL)` when the target lies outside, never restore the cursor into a
  clip, and name the clip rectangle rather than blaming a locked desktop.
- **The menubar needs real input; nothing else does.** Posted messages never open the
  menubar (a posted move and a posted held press both failed), while the record strip,
  the sidebar numerics, the popup entries and the dialogs all accept posted messages.
- **Caption-less widgets** — the entire UI is caption-less `TSp_*` controls. Never match by
  title. The menu entries are `TSp_Button`s inside the overlay, ordered by screen `top`
  (first = `Operating parameters`, second = `Default parameters`, then a third and fourth).
- **The artifact is the authority** — verify every point from the stored bytes
  (`verify.py`: gates exact, resolution rung inverted from the request, depth within
  tolerance), never from the request, the driver's intent, or a control's text.

### The parameters dialog is per-channel, and a write replaces it (2026-09-17)

Two live runs settled the channel path, and both changed what the driver may assume:

- **The write works, in both directions, with the reference's own gesture.**
  `CB_SETCURSEL` + a `CBN_SELCHANGE` posted to the combo's parent, no Enter, then accept,
  then re-open and read the channel back: `verified channel: 2` and `verified channel: 1`,
  each followed by a clean layout (`layout_note: None`, 43 controls in 4 panels). The
  write's settle is the reference's own 0.8 s (`_COMBO_SETTLE_S`).
- **The application *replaces* the dialog when the channel changes.** Measured: the write
  closed `Operating parameters` at `(655, 364)` — 627x384, 21 direct children, seven
  `TSp_Value_Button` fields, the two indicator buttons plus `Cancel`/`Accept` — and opened
  **`Assisted mode parameters for channel 2`** at `(713, 364)`, 511x384, 14 visible
  children, six value fields, the `Shorter acquisition time / Best quality` slider, and its
  own `Cancel`/`Accept`. Every handle taken before the write is **dead**, so the read-back
  and the accept must use a re-resolved panel. The reference did exactly this
  (`find_dialog(resolve()) or dlg`, `recon/41_burst_sampling_volume.py`); the port kept its
  old handle, pressed a window that no longer existed, and left the new dialog on the
  operator's screen with nothing able to close it (twice — the operator reported it both
  times, and was right). `ensure_channel` now re-resolves after the write
  (`_poll_dialog(_DIALOG_REPLACE_S)`) and says so in a note.
- **A channel's *mode* changes the whole screen, and the mode belongs to the channel.**
  Measured live 2026-09-17, one channel change per run: selecting **channel 2** gives the
  assisted panel, then selecting **channel 3** gives an assisted panel *too* (a mode that
  flipped on every channel change would have alternated back to manual there), and returning to
  **channel 1** gives the manual panel with its sidebar — the state it started in. So the
  channel combo re-renders the parameters panel for the channel you pick; it does not toggle a
  mode, and the operator can do exactly this from the same combo, from inside the dialog.
  Assisted mode **removes the sidebar parameter column**: that screen is **21 visible controls
  in 3 panels**, not 43 in 4, so `roles["params"]`/`param_rows` are empty there and a parameter
  write has no target. Consequences:
  - a **sweep cannot be parameterised on an assisted channel** — it fails at the first write
    (now with a message that names the mode: `_assisted_mode_clause`), so pick a channel in
    manual mode or leave assisted mode in the application's own Preference menu first;
  - `layout_note` says the sidebar is absent and calls it what it is;
  - `ensure_channel` records which panel the channel's parameters came up in
    (`panel_mode`: the assisted panel carries the acquisition-rate/quality `TSp_Sliding_Bar`,
    the manual one the value table) — the application's own statement of the mode, read
    structurally because every widget here is caption-less;
  - a probe that refuses to start on a non-clean screen will refuse to start on such a channel
    at all, which is why `recon/55_restore_channel.py` exists to put the channel back.
  **And the mode is per channel, and it predates every press this session made.** The same
  word read at each channel's own offset (`_word_offset(word, channel)`: the parameter area
  holds a block per channel) says channel 1 = **0** and channels 2, 3 and 4 = **1** — in
  *every* file on the installation, `test.BDD` at 14:54 included, hours before the first
  channel write at 21:26, and the two channel-2 files the earlier session stored at 16:16 and
  18:41. That makes a falsifiable prediction, and it was tested: selecting **channel 4**,
  which no write had ever touched, brings up the application's assisted panel with the
  sidebar gone (21 visible controls in 3 panels), and channel 1 comes back with it (43 in 4).
  The flag and the screen agree, so **the assisted mode of channels 2-4 is this
  installation's long-standing per-channel configuration** — not a consequence of a channel
  write, and not something this session switched on. The popup walk above was therefore a
  real *hazard* (the manual's rule stands, and the application highlights `Default
  parameters` by itself) but **not the cause** of what was seen here: it was removed as a
  hazard, not as a culprit. The driver still refuses any point whose sidebar disappears
  mid-interaction, and still never leaves the mode itself — its own toggle is the
  application's Preference menu, which `docs/16` records as deliberately not driven.
  Nothing
  else was changed: the channel selector was left where it was found.
- **The `Parameters` popup's five entries are fixed labels** — read off a 3x screenshot of the
  live menu: `Operating parameters`, `Default parameters` (the one the application itself
  highlights), `Save parameters`, `Recall parameters`, `Tigger parameters` (the build's own
  spelling of *trigger*). The manual's v6.6/6.7 menu lists `Assisted mode parameters` as an
  entry of its own; **this build has no such entry**, and the assisted panel is reached by
  selecting a channel that is in assisted mode. The driver presses entry 0 **by screen top,
  never by caption** — which is why it keeps working across both builds — and then requires the
  channel combo. `PARAMETERS_ENTRY` names the *entry that is expected*; the panel that opens is
  identified structurally, as always, and its *own* title is the application's statement of the
  mode (pixels only: no caption in the tree).

## 4. Open / unproven

- **The menu cycle is now live-verified** (2026-09-17, §5a): hover → visible overlay → posted
  held press on the first entry by screen top → `Operating parameters` at `(655, 364, 1282,
  748)` → channel combo read (`(1083, 373)`, items `1`..`10`, index 0) → Cancel → clean layout
  (`43 controls in 4 panels`, `layout_note: None`). Nothing was written and nothing accepted.
- **The channel *write* path is now live-verified in both directions** (2026-09-17): channel
  1 → 2 and 2 → 1, each `verified channel: N` after accept + re-open, dialog closed and the
  clean layout restored. What the write *does* to the dialog — replace it — is in §3.
- **A whole point runs through the port, live.** Three files, 2026-09-17: `port-probe-01.BDD`
  (3 s, 111,080 bytes), `port-probe-02.BDD` (2 s, 88,859 — the repeat, same parameter
  signature), both on channel 1, and `port-probe-03.BDD` (3 s, 79,286) on channel 2 with the
  layout gate lifted by the probe. Each came out through `record_and_store`: `ensure_channel`
  (read, written, verified), `Record` → hold → `Stop`, `Do store`, the working directory
  asserted, the name written, `Do store` on the Store dialog, the file waited for and read
  back with `verify.read_words` (gates 804, resolution 0.12 mm, depth 99 mm, sound speed
  1460 m/s, PRF 212 µs, 150 emissions/profile, burst 4). The operator's sequence is
  *(if needed `Clear and restart`, wait for the record button to come back) → record → stop →
  `Do store` → the Store window with the cursor trapped in it → (change the fields) →
  `Do store`*, and `recon/56_point_cycle.py preflight` runs it read-only (it opens the Store
  dialog, reads its name and working directory, cancels) — the run's own notes for a channel
  write are in §3.
  The write reaches the **data**, not just the label: each stored profile record carries its
  channel — `port-probe-02` (channel 1) and `port-probe-03` (channel 2), same configuration,
  differ at byte 881 and then at every 1024-byte stride, reading 1 and 2, and nowhere else in
  the file.
- **The channel guard is once per run, not once per point** (2026-09-17). `ensure_channel`
  opened the `Operating parameters` modal for every point of a sweep, which an operator sees as
  windows opening and closing for no visible reason, and which proved nothing a point's own file
  does not: the decoder **refuses** a file carrying no data for the channel it is asked for
  (`port-probe-03.BDD`, stored on channel 2, raises "carries no data for channel 1"), so every
  stored point is checked against the run's channel by its own file. `SweepRunner` now verifies
  the channel once, before the first recording is spent (`_verify_channel_once`), and passes
  `verify_channel=False` for every point; a bare `run_point` still gets the dialog. Two tests
  pin it: one dialog for a four-point run, and a standalone `run_point` still verifying.
- **A run says what it is doing.** The cycle's stages were silent, so its normal 7-8 s of setup
  per point — the block reset, the channel dialog, the parameter writes — was indistinguishable
  from a stalled run to anyone watching the screen. The actuator's note channel now carries the
  stage boundaries (channel verified, recording confirmed and held, hold over, Store dialog up
  and named, stored), and `recon/62` streams them with their offsets: measured 2026-09-17, a 3 s
  point cost 13.3 s of wall clock and a 6 s point 8.6 s, with the holds exactly 3.0 s and 6.0 s
  from the confirmed recording view to the Stop press. **A note must not touch the
  filesystem** — the first version stat'ed the stored file and turned a *faked* store into a
  failed point, which is how it was caught.
- **A two-point sweep runs through the runner** (`recon/60_two_point_sweep.py`, 2026-09-17):
  one channel, one duration (12 s, inside the operator's 10-15 s band), **one axis** — the
  resolution ladder at a *constant* 99 mm window, k=1 (0.122 mm, 797 gates) and k=2
  (0.243 mm, 399 gates), the two rungs `plan_sweep` computes from the measured laws. Both
  points `ok`, no abort, no note from the actuator, and the permutation is in the stored
  words: resolution 0.1217 -> 0.2433 mm, depth 99 mm and channel 1 on both, burst 4. The log
  (`recon/out/two-point-sweep.jsonl`) carries one entry per point — `sweep_id`, `key`, `name`,
  `status`, `requested`, `readback_gates`, `readback_resolution`, `file_path`,
  `file_size_bytes`, `expected_size_bytes`, `decoded`, `failure` — which is the job-tracking
  record in its minimal usable form.
  **Superseded measurement (2026-09-21):** the completed sparse pass proved that the following
  ring-buffer interpretation was wrong. Its 26 production files retain 12.4651–12.5713 s for a 12 s
  request, and profile timestamps establish `emissions × PRF + 10.369 ms`; the historical paragraph
  is retained below only to explain the older code and review findings. See `sparse-run-plan.md` §5.
  **What the record does not carry, and what that hid — measured twice, `recon/62`:** the
  block is a **ring that stops at about 257 profiles**. A 4 s recording at the same
  configuration stores 123 profiles (83,499 B) — an implied period of **32.5 ms**, i.e. the
  manual's law (33 ms) to within measurement — while a 12 s recording at that configuration
  stores 257 (174,623 B, and 259 in the sweep): **~8.4 s of signal, not 12**, at a ratio of
  2.09 where the durations are 3.00. So the manual's period law is *right* and the long block is
  **truncated**; the earlier reading in this document — that the law's transfer term is short by
  ~1.6x — was an artefact of counting the missing profiles as a longer period, and is retracted
  here. Nothing refused the point: `assert_window_fits` is checked against the *law's* period and
  `RecordSettings.max_profiles_per_block` (default 1,000,000) is not the application's own
  "Do not keep in a block more profiles than" setting, `SizeSignature.matches` tolerates a
  factor of 2 either way (0.62 passes), and `timing` is `target_s: None, achieved_s: None` —
  the one field that would have said so. **For the operator's goal this is the number that
  matters:** a 10-15 s recording at these settings keeps only its last ~8.4 s, identically for
  every point, so a like-for-like comparison holds — but a campaign that wants 10-15 s *stored*
  has to raise the application's block cap, and the log has to carry the achieved duration
  (profiles from the file's own size, period = T / profiles, the cap flagged) before that can be
  taken on trust.
- **The write-replaces-the-dialog rule is pinned** (`test_the_dialog_is_re_resolved_after_a_
  channel_write_replaces_it`): the fake scripts the replacement at the live geometry — the
  operating dialog at `(655,364)` giving way to the assisted one at `(713,364)`, new handles —
  and asserts the accept came *after* the replacement, i.e. on the new dialog's own button.
- `dialog_note`/`layout_note` and the `Store` dialog's own band were not re-measured today; the
  Store dialog's pair is assumed to be the same two-rightmost rule (it resolved correctly in
  the port's tests, never live since the port).
- `layout_note()` returns `None` for the clean screen (a documented sentinel) and a summary
  otherwise; `StripState.slider_max` is always `None` (the slider's range is never read).
- The at-cap warning's text was never captured (the state clears before it can be read).
  With independent points and a 10,000-profile cap it is off the critical path.
- A point's duration is nominal, not measured — the driver waits out the recording window
  blind, so the real length is uncertified (a few percent at 10–20 s points).
- The §2 port is **uncommitted**; the branch is `feat/dop3010-acquisition` and the working
  tree holds the driver + tests + docs changes together.

## 5. Running a live point

```
cd C:/Repos/udv-echo-process
UDV_STORE_DIR=<the app's working directory> \
  ./tools/live/dispatch.sh -m udv_echo_process.cli acquire sweep --seconds 12 --rungs 1,2
```

**The command above is the current route** (`tools/live/README.md` lists them all, and the app's
Store directory is now `outputs/live/store/` — see
[`recon-archive-retirement.md`](recon-archive-retirement.md)). The original form of this section
ran a probe from the retired archive:

```
cd C:/Repos/udv-echo-process
uv run --with pywin32 python ./dop-control/recon/45_live_sweep_runner.py   # archived
```

Preconditions: UDOP 6.07.4 simulator (`TMain_Scr`) in the `ready/3` view, **no popup
open** (a lingering one makes the layout guard refuse: `49 visible controls in 5 panels`
against the clean `43 in 4`), and a clean buffer. `pywin32` is declared as the optional
`acquire` extra.

Diagnostics that answered the hard questions:
`recon/46_menubar_probe.py` reports, before and after a hover, whether the app is focused,
the dropdown panel's rect and `IsWindowVisible`, and the desktop pixels inside it. It also
snapshots the driver's own prelude (its strip press and its sidebar write) — that is what
proved the prelude is not the cause and that focus is irrelevant.

## 5a. Running a live test when the agent drives it (measured 2026-09-17)

**The agent's own shell cannot touch the GUI.** Hermes' terminal tool runs in **session 0**
on window station `Service-0x0-9a468fe$` (a service station), while UDOP runs in **session 1**
on `WinSta0`; from session 0 `GetForegroundWindow()` returns 0, `GetCursorPos()` fails with
*"requires an interactive window station"* (1459), `EnumWindows` sees no application window
and `FindWindow("TMain_Scr")` returns 0 — so the driver refuses with *"no visible
TMain_Scr window"*, which looks like a broken driver and is not one (`recon/49` proves it).
`hermes computer-use` is not installed here either, so there is no second route.

**The route that works: a scheduled task that runs in the interactive session.**

```
printf '47_menu_open_probe.py' > recon/out/task_target.txt   # which probe
printf 'popup'                > recon/out/task_args.txt      # its args (may be empty)
schtasks /run /tn hermes_gui_probe
```

The task is created once, with the caller's own principal so it lands in session 1 and needs
no password:

```
schtasks /create /tn hermes_gui_probe /tr "\"<clone>\.venv\Scripts\pythonw.exe\" \"<clone>\tools\live\task_run.py\"" \
         /sc once /st 23:59 /ru INTERACTIVE /it /f
```

(The action was originally the archive's `recon/task_run.cmd`; it is
`tools/live/task_run.py` since the port — same rules, and `tools/live/README.md` carries the
current form of this command. The archive is `~/Repos/_archive/dop-control-20260918.zip`.)

The task starts **`pythonw.exe`, not a `.cmd`** — a `.cmd` action gives the task a *console
window* on the interactive desktop, in front of the application, and that alone breaks the
hover: measured 2026-09-17, the foreground window was `ConsoleWindowClass` / `cmd.exe` and
UDOP reported `is_foreground=False`, after which the cursor moved onto `Parameters` and **no
popup appeared**. `recon/task_run.py` is the action: it reads the probe name and its args from
the two files above (argument quoting through `schtasks /tr` is where that breaks), runs the
probe with the venv's python under `CREATE_NO_WINDOW`, and writes `out/task-<probe>.log`.
Verified through it: no console window exists, and the driver's foreground precondition
(`_require_foreground`, `driver.py`) is satisfied.
stdout+stderr to `recon/out/task-<probe>.log` — which the agent then reads, so the whole
transcript is machine-readable instead of a description.

**The application must be in front for the hover, and that is now a precondition.**
`_require_foreground` reads the foreground window, asks Windows to activate the application
(`AttachThreadInput` + `SetForegroundWindow`, because a plain `SetForegroundWindow` from a
process the user is not touching is refused by the foreground lock), reads it back, and
**refuses** if it is still not the application. An inactive window ignores hover — its first
mouse event only activates it — so without this check the failure is silence, and silence is
indistinguishable from a gesture that does not work. It cost a live slot to learn exactly
that; `recon/53` prints the foreground window, the cursor, the clip and the visible panels,
and is the first thing to run when a hover opens nothing.

**Screenshots are the only route to the *labels*.** Every `TSp_*` widget answers
`GetWindowText` with `""`, so the painted text (which entry says `Operating parameters`,
which button says `Cancel`) exists only in pixels. `recon/51` (`PIL.ImageGrab`, run in
session 1) saves the full screen plus crops of the popup and the dialog, and the agent reads
the PNG with its own vision. That is how the two indicator buttons were told from the
Cancel/Accept pair.

**Make the probe state its own expectations.** `recon/47` prints an `EXPECTED (plan) vs
OBSERVED` table (overlay rect, entry count and tops, dialog rect, combo identity and items,
channel) and flags each mismatch, so a divergence is a named line rather than a coordinate
somewhere in a wall of text. Two of its rows were wrong about the plan and right about the
instrument: the dialog directly owns **21** controls (the plan said 12; the probe's 42 was
`EnumChildWindows` counting *descendants*), and the bottom band holds **four** buttons, not
three.

## 6. Rules that were expensive to learn

- **Refuse, don't press.** On an unrecognised state or panel, stop the run. The circuit
  breaker did this five times live and never once sent a stray press.
- **One change at a time**, and verify from the artifact rather than from the code, the
  request or the control tree.
- **Never `WM_CLOSE` a popup** — it wedges the modal menu loop until the application is
  restarted.
- **Trust the operator's eyes over telemetry.** Twice the control tree reported the popup
  open while the screen showed nothing; both times the eye was right.
- **Port proven code verbatim before re-deriving it.** The working menu interaction existed
  in `recon/41` all along; three fix cycles went into reinventing it. The live run of
  2026-09-17 found the *same* mistake once more, one line deep: the reference takes a dialog's
  Cancel as `bottom[-2]` ("the last two of the band") and the port took `bottom[0]` ("the
  leftmost"), which on this dialog is an indicator button — the dialog stayed open and the
  operator saw it. **Corollary: an addition must never outrank the proven rule.** The
  appearance-diff overlay finder was this port's invention and was tried *first*, ahead of
  the reference's `left == 169 and h > 120`; it is now the fallback. When a rule in the
  reference exists, it decides order and identity; this repository's additions are fallbacks
  and diagnostics, and each one is written down as such.
- **A record read after the fact is a record of the wrong fact.** The entry press closes the
  popup, so "was the overlay visible / what entries did it offer" has to be read *before* the
  gesture; read after, a press that had opened the dialog reported `overlay_visible: false`
  and `overlay_items: 0`.

## 7. Delegation notes

Subagents deliver when given one file (or a tight, disjoint file set), no exploration, a
blueprint, the exact test command, and the report format. An open-ended ask burns the
output budget and writes nothing (one did: 545 s, twelve API calls, no file). State
explicitly whether they may run ruff — one task was told not to, and the lint landed red.
Two siblings editing one file produce flaky runs; keep the file sets disjoint.
