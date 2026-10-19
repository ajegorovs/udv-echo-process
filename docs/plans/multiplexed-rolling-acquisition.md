# Multiplexed / rolling acquisition — mapping and control path

**Task plan.** Written 2026-10-19. **State:** ready for review. Register: [agenda](../agenda.md#selected-work).
This is a *capability* plan for the instrument path, not the four-sensor analysis: it maps how the DOP3010's
multiplexer is driven and what has to exist in `acquire/` for the automation to drive it, and it stops short of
any alignment, estimator or campaign work.

## Destination

**Purpose.** Make the acquisition path able to run a **multiplexed** measurement — several front-panel channels
sampled in one acquisition, sequentially per visit, optionally rolling over — and to record, in its own run record,
the visit/sequence structure the application was actually configured with. Why now: the four-sensor effort (the
effort selected in the agenda) cannot present a joint multi-channel analysis without an alignment decision, and
neither the recordings nor the reader can currently supply the identity that decision needs — `bdd.py` decodes the
per-profile *block/sequence* word but explicitly refuses to derive round/visit identity from it
(`io/dop/bdd.py` §header notes; agenda § *Four-sensor alignment*). That is precisely the case the agenda's
acquisition constraint admits: *a condition the campaign cannot establish on its own*. The capability has to be
mapped before it can be implemented, and the mapping is what this plan owns.

**Observable outcome / acceptance criteria.**

1. **The workflow is mapped surface by surface**, each step naming the application surface, the control, the crop or
   `path:line` evidence for it, what the driver already does, and the gap. Evidence: § *The mapped workflow* below,
   each row carrying its crop id or `file:line`. **The index's own checker does not exit 0 on `master`** — 2
   pre-existing problems (its prose says 45 crops while it lists 50; UI-STRIP-04's stated width disagrees with the
   file) — recorded in the agenda, unrelated to this plan, and not a reason to trust an uncited caption.
2. **A typed mode model exists offline** — participant channels and their order, profiles-or-duration per channel,
   sequence repeats, stop-at-end vs roll-over, external-trigger mode — that cannot express a mode the application
   could not be configured with, and that refuses by name. Evidence: module + tests on the fake actuator, no device.
3. **The per-point cycle refuses, by name, while the multiplexer is enabled**, instead of reporting a failed
   parameter write as a point failure. The application states the menus are inaccessible while the multiplexer is on
   (manual §11), so the existing route-verify-write cycle cannot run inside it. Evidence: an offline test at the
   refusal, plus a live confirmation that the refusal matches what the application does.
4. **A read-only verb** (`udv-acquire multiplexer status`) opens the `Channels` surface and reports the mode's
   settings with their read-back, refusing rather than guessing when the surface cannot be proven. Evidence: a live
   session record with the readings quoted, in `dop3000/device-verification.md`.
5. **Enabling and disabling is a verified transaction**: the value is written, then read from a **re-opened**
   surface, on the discipline the burst-length write established (`write_dialog_burst_length`); a write that cannot
   be re-read is a refusal, not a success. Evidence: live, with the two reads quoted.
6. **One multiplexed recording is stored and identified from its own bytes**: the stored `.BDD`'s op words 51
   ("Nb profiles in block in multiplexer mode"), 52 (multiplexer-enable bit), 53 ("Nb blocks in multiplexer mode")
   and the per-profile block word are read back and compared with what was requested, and the comparison — including
   any disagreement — is written down. Evidence: committed data note + the decode.
7. **The mode is recorded as a measured fact, not an inference.** Because roll-over is a *runtime* option that the
   stored bytes do not carry (`AcquisitionMode.ROLLING` is deliberately never emitted), the run record must state
   which mode was requested and which was verified; the plan's evidence for this is the run record of criterion 6
   and the fact that the file cannot settle it alone.

**Non-goals.** No alignment rule, no resampling/interpolation decision, no four-sensor estimator — the open
alignment finding stays open and this plan does not pre-empt it (it may supply the *evidence* an alignment decision
would need, which is not the same thing). No rolling **campaign** automation: one verified record first. No
generalisation of menubar driving beyond the one bounded `Channels` surface (§ *Decisions* D3). No change to
single-channel semantics, no new sweep axis (burst/emissions/PRF writers are done and out of scope), no assisted
mode, no `Record settings` manipulation, no external-trigger *implementation* (the mode field is mapped and typed;
driving it is deferred).

**Authorization boundaries.** Owner direction 2026-10-19: *"I want to implement new acquisition feature for this
package — performing multiplexed/rolling measurements … It must be mapped out … write a task plan."* That grant
covers this plan and the mapping in it. It does **not** yet cover: a live device session at the instrument, any
writer landing on `master`, a campaign/run-plan extension, or changes to the four-sensor alignment finding. Those
are the next decisions, recorded under § *Next session*.

**Baseline.** Branch `feat/multiplexed-rolling-acquisition` in a dedicated worktree created from fetched
`origin/master` `d276d6e` (PR #77 merge). Not based on the retired `docs/loose-end-closeout` leaf, whose records are
still unmerged in PR #76. Device state: **unverified in this session** — no instrument was reachable, so every
device-pending item below is recorded as such rather than assumed.

## Patterns this work follows

- **The verbatim-port rule** for `acquire/` and `tools/live/` (`AGENTS.md`): move a proven gesture, never re-derive
  one. A gesture this plan cannot cite from a live session is device-pending, not "obvious".
- **The ui model's binding rules** ([`dop3000/acquisition-ui-model.md`](../dop3000/acquisition-ui-model.md) §5) are
  the only supported ones: identity by role and relative location, never by an index into a name list, never by a
  caption. The `Channels` surface needs its own proven anchor, exactly as `Parameters` has
  (`acquire/ui/menu.py`).
- **The mechanism authority is** [`dop3000/udop-automation.md`](../dop3000/udop-automation.md) §§2–4 — what commits a
  value, in what order, and which failure modes invalidate a point. Linked, never restated here.
- **The architecture invariants** ([`dop3000/acquisition-architecture.md`](../dop3000/acquisition-architecture.md)
  §7): observation → interpretation → action; a refusal is a first-class outcome; surface before target.
- **Painted captions are the crops' business.** Every caption below is quoted with its crop id from
  [`dop3000/ui-element-index.md`](../dop3000/ui-element-index.md), and the index is *checked*, not trusted
  (`uv run --extra acquire python tools/ui/crop_index.py`).
- **Task-plan convention:** `AGENTS.md` § *Planning a task* (+ [`plans/TEMPLATE.md`](TEMPLATE.md)); the shared
  work-organization source is the estate knowledge base's `dev-and-deploy/WORK-ORGANIZATION.md`.

## The mapped workflow

The owner's account (2026-10-19): *"multiplexed mode is enabled after configuring all participant-channels
individually, configuring new fields in `Channels` tab for each channel, toggling `Enable multiplexer` → starting
recording similarly to single channel recording."* The manual (§11, [`manual-reference/11-using-the-multiplexer.md`](../dop3000/manual-reference/11-using-the-multiplexer.md))
adds the ordering rule that makes step 1 load-bearing, and the state that constrains everything after step 6.

| # | step | surface + control (evidence) | what `acquire/` has today | gap |
|---|---|---|---|---|
| 1 | **Route each participant channel** and configure its operating parameters | `Parameters → Operating parameters` channel combo, then the dialog's fields (UI-OVERLAY-05; binding rules §3.3, §5) | `ensure_channel()` + `write_parameter`/`ordered_writes`; verified on the instrument (B17) | **None.** This is the one step already proven end to end |
| 2 | **Repeat step 1 for every participant channel** — the manual requires all of them defined *before* enabling | same as 1 | the per-point cycle does this for **one** channel per point | the run model has no "N channels configured" phase; a multiplexed run needs all participants configured in one pass, and that has to be the *same* configuration the visit structure assumes |
| 3 | **Per-channel fields in the `Channels` dropdown**: `For the current channel (channel 1)` → `Acquire [1] Profiles or during [0.05] seconds`, `Apply parameters from channel [1 ▼]`, and the two buttons `To current channel` / `To all used channels` (UI-MENU-10) | the `Channels` menubar entry, 8th of the ten entries `UI-WINDOW-01` paints | **nothing** — the driver's only menubar binding is `Parameters` (`acquire/ui/menu.py`), and the ui model's §9 lists "arbitrary UDOP menu driving" as out of scope | the whole surface is unbound: anchor, popup identity, and the fields. `Acquire … Profiles or during … seconds` is the per-channel acquisition size, i.e. the field that decides how long each visit is — see § *Open questions* Q1 |
| 4 | **Declare the participant set and the sequence's first channel** | same dropdown: `Use channels` over ten numbers (UI-MENU-10 paints `1` and `10` ticked green), `Start the sequence by using channel [1 ▼]` | **nothing** | needs a typed participant set and an order, both read back |
| 5 | **Choose the mode** | same dropdown: `Repeat the acquisition sequence [1] times`, `Roll over the channels` (ticked green in UI-MENU-10), `Display all channels in the same graph (if possible)` | **nothing** | `Repeat … times` and roll-over are the mode's substance; `Display all channels…` is a *display* option (manual §11.2) and must not be mistaken for a measurement setting |
| 5b | **External trigger**, if used | `External Trigger settings` (UI-OVERLAY-11: its two standing notes read `when multiplexer is OFF` and `when MPX is in sequential mode`); manual §11.2 — "Trigger each sequence" per-sequence wait | **nothing**; UI-OVERLAY-11 is `unknown (not classified)` in the index's blocking column | mapped and typed only; **driving it is deferred** (non-goal) |
| 6 | **Toggle `Enable multiplexer`** | the master checkbox in the same dropdown (UI-MENU-10) | **nothing** | the mode switch itself. Manual §11.2: once enabled, **the menus cannot be accessed and parameters cannot be changed**, and it is disabled again by `Use only channel` — so enabling it *suspends* steps 1–2, and the automation must refuse its per-point cycle by name while it is on (criterion 3) |
| 7 | **Record**, like a single-channel record | strip: `Record` → `Stop` (UI-STRIP-01..04; `StripView` classification) | the full record cycle exists, verified on the instrument | **the accounting changes**: each roll repeats N blocks, the block now holds every participant channel's profiles, and the memory/`T ≤ cap × period` assertions of `udop-automation.md` §7 are stated for a single channel. The per-channel period is what a multiplexed point has to be sized against |
| 8 | **Store**, per block | store view: `New acquisition` / `Do store` / `Clear and restart` / `Remove current block` (UI-STRIP-02), with the block slider whose maximum is the *selected block's* profile count (`acquire/actuator.py:883`). **The row itself also carries `Do store`**: UI-STRIP-03 paints `Pause` / `Record` / `Do store` / `Clear and restart` with each caption bound to a handle in one instrument process, and UI-STRIP-04 paints the paused three-button state `Resume` / `Do store` / `Clear and restart` over a history slider | `StripControl.REMOVE_CURRENT_BLOCK` and the store dialog's `Do store` exist; `udop/recording.py` already dismisses a leftover block view | `udop-automation.md` §7 rule 5 names exactly this: *"blocks only become meaningful for rolling/multiplexed multi-channel work, where each roll repeats N blocks and `Show block` plus a block-scoped `Do store` is exactly the needed unit"* — **which block is selected is not currently a semantic step**, and `Show block` has no binding or crop in the committed set |

**What a stored multiplexed file already proves** (reader side, `io/dop/bdd.py`, measured):

- the multiplexer-enable bit is op word 52's LSB (the manual numbers it "bit 1"); `_multiplexer_enabled` requires it
  set on **every** used channel, and the decoded mode is then `AcquisitionMode.SEQUENTIAL`;
- `ROLLING` is **never emitted**: roll-over is a runtime multiplexer option, so the bytes cannot distinguish a
  rolling capture from a stopped one — a limit, not a gap to be closed by guessing;
- op word 51 is "Nb profiles in block in multiplexer mode" and word 53 "Nb blocks in multiplexer mode"; on
  `data/4-sensor-velocity/200RPM.BDD` the per-profile block word spans `1..100` **matching word 53**, with four
  contiguous profiles per channel per block **matching word 51**, while on `data/echo/200.BDD` it is the constant
  `1` across 4181 blocks;
- round/visit identity is **not** derived from any of it, by explicit decision (the manual documents the word as a
  *block/sequence* number and nothing stronger).

So criterion 6's comparison is available offline today, from the committed fixtures, without the instrument — and
it is the cheapest evidence this plan can produce first.

## The `Channels` surface, measured (2026-10-19)

The dropdown's **control tree is readable while it is hidden**. This application keeps its menu
panels in the tree with `WS_VISIBLE` off (the reason `_is_visible` exists), so a passive walk of the
running application — no hover, no cursor movement, no press — returns the whole surface with
handles and rectangles. Measured on `UDOP DOP3010.43` (window `(-8,-8,1928,1058)`, maximised), via
`tools/live/probes/hidden_menus.py`:

- the dropdown is the hidden `TSp_Panel` **hwnd 2887108, rect `(526,55,919,481)`** — 393 x 426. The
  committed crop `UI-MENU-10` (`menu-channels.png`) is 393 x 460: the same width, and 460 − 34 = 426
  for the menu band it also shows, so the crop and the live panel are the same surface and every
  painted caption now has a handle;
- the menubar's `Channels` entry is the **seventh of ten** bar buttons, hwnd 507514148, rect
  `(526,28,596,53)`. Its dropdown starts at the button's own left — the same convention the
  `Parameters` popup follows (`left == 169` is that button's left), which is what makes a popup-left
  signature generalisable rather than a second hard-coded rectangle;
- the bindings, by caption (rects are screen coordinates at that window rect; `x` pitch of the two
  tick rows is 21 px, each strip 15 x 33):

| caption | control | hwnd | rect | live value |
|---|---|---|---|---|
| `Use only channel` (label + its tick) | `TSp_Button` | 266390 | 536,58,658,88 | painted |
| the ten `Use only channel` ticks | ten `TSp_Button`s | 6357834 … 6689118 | x = 687 + 21k, y 65–98 | painted |
| `Enable multiplexer` | `TSp_Button` | 2494676 | 535,91,664,123 | painted |
| `Roll over the channels` | `TSp_Button` | 266402 | 739,131,893,149 | painted |
| the ten `Use channels` ticks | ten `TSp_Button`s | 2819078 … 266384 | x = 693 + 21k, y 168–201 | painted |
| `Repeat the acquisition sequence [n] times` | `TSp_Edit` in 5834222 | 1114666 | 780,210,886,234 | `10` |
| `Start the sequence by using channel [n]` | `TComboBox` | 1053496 | 781,244,826,265 | `1` (items `1`…`10`) |
| `Display all channels in the same graph (if possible)` | `TSp_Button` | 266404 | 550,267,870,299 | — |
| `For the current channel (channel 1)` | painted heading inside 4916038 | — | — | — |
| `Apply parameters from channel [n]` | `TComboBox` | 3412402 | 782,349,832,370 | `1` (items `1`…`10`) |
| `To current channel` | `TSp_Button` | 1708122 | 566,387,716,407 | — |
| `To all used channels` | `TSp_Button` | 1511456 | 734,387,884,407 | — |
| `Acquire [n] Profiles` | `TSp_Edit` in 2626410 | 1508794 | 615,436,772,460 | `5` |
| `during [x] seconds` | `TSp_Edit` in 528502 | 855898 | 786,439,892,463 | `0.20` |

**The one finding that changes the design.** There is **no `TSp_CheckBox` in this dropdown**. Every
tick — `Use only channel`, `Roll over the channels`, the twenty channel ticks — is an owner-drawn
`TSp_Button` that answers `BM_GETCHECK` with **0** whether or not it is ticked (all twenty report 0
while the crop paints row 1 as one green tick and nine red crosses, and row 2 as `1` and `10`
green). So the multiplexer's state is
**paint, not a message**: `Enable multiplexer` cannot be read by `BM_GETCHECK`, and a read-only
status verb has to be a **capture** of the visible panel, exactly as a caption does. The field
values are the exception — the two combos and the three edits answer by message across processes, so
`Repeat`, `Acquire … Profiles`, `during … seconds` and both channel selectors *are* readable
without a picture, and they read the application's buffered values while the panel is hidden.

Two consequences for the plan's open items:

- **Q1 is answerable offline in part**: `Acquire [n] Profiles` and `during [x] seconds` are two
  separate edits in one row, both holding a value at once (`5` and `0.20` now), so they are
  alternatives the *application* resolves — not two spellings of one field. Which one the visit
  actually uses still needs a stored file's word 51 to compare against, exactly as Q1 says.
- **The classifier would not name this popup.** `ui/identity.py::_is_menu_popup` is
  `left == 169 and h > 120`, the `Parameters` rectangle; a `Channels` popup at left 526 fails it and
  resolves as neither popup nor dialog. Any verb that opens this surface has to either generalise
  that rule (panel left == a bar button's left, panel top == the band's bottom, panel hosts
  `TSp_Button`s — the convention measured above) or state its own signature. Not implemented here.

## Current checkpoint

**Established.**

- The workflow map above, from committed evidence only: manual §11 (the ordering rule and the lock), UI-MENU-10 (the
  `Channels` dropdown's full control set, its ten channel numbers, its tick states), UI-STRIP-01/02 (the strip views),
  UI-OVERLAY-11 (the trigger dialog), `acquire/ui/menu.py` (the single existing menubar anchor and the rule that
  forbids an index map), `acquire/actuator.py` (`StripControl`, the store slider's maximum), `io/dop/bdd.py`
  (the reader facts above). Revision: `d276d6e`.
- The reader-side comparison of criterion 6 is computable offline on the committed four-channel fixture.
- **The `Channels` surface's control tree is measured** (2026-10-19, live, passive): the dropdown panel, the
  menubar entry, and every control's handle and rect, bound to `UI-MENU-10`'s painted captions — § *The
  `Channels` surface, measured*. Its ticks are owner-drawn buttons, so their state is paint and not a message.
- The `Parameters` path (`ensure_channel`, the dialog transaction) is proven on the instrument. Nothing about the
  multiplexer's **state** is: no tick was read, no field written, no menu opened.

**Not established** (each is device-pending or a question, never an absence):

- whether the `Channels` entry can be opened by the *same* gesture the `Parameters` anchor uses (real-cursor hover,
  then a posted held press on the entry): only `Parameters` has been proven live, and the entry press is
  the ui model's §5 rule — a second anchor is a *new* claim. **The button is identified**
  (seventh of ten, hwnd 507514148); what is unproven is the hover;
- how a `Channels` popup is to be *named* by the taxonomy: measured 2026-10-19 it is a hidden `TSp_Panel`
  with its own rect whose left equals its menubar button's left (§ *The `Channels` surface, measured*), but
  `ui/identity.py::_is_menu_popup` is the `Parameters` rectangle (`left == 169`), so this popup currently
  resolves as neither menu popup nor dialog;
- what each `Channels` control actually commits when pressed: the ticks are owner-drawn `TSp_Button`s whose
  state is **paint** (all report `BM_GETCHECK` 0), so what a press changes is unverified, and whether
  `To all used channels` copies the current channel's whole parameter set (candidate replacement for the
  driver's own per-channel writes — unverified, and it would *bypass* the existing verification chain if
  adopted). The two `Acquire …` forms are settled as far as the surface can settle them: they are two
  separate edits holding values at once, so the application resolves which applies — not two spellings of
  one field;
- whether enabling the multiplexer makes the parameters dialog unreachable (the manual's lock) or merely refuses the
  write, and therefore what refusal the per-point cycle should raise;
- whether a **rolling** capture is observable at all from the instrument's own UI (the file cannot show it).
  What *is* observable — painted on the panel — is the `Roll over the channels` **setting**, which is a
  different claim from the capture having rolled;
- which block is selected in the store view, and where `Show block` lives — no crop, no binding;
- **how far the strip's own evidence has actually moved.** UI-STRIP-03 (four entries `Pause`/`Record`/`Do store`/
  `Clear and restart`, captions bound to handles `1574908`/`4787852`/`2821164`/`1641666` in one instrument process on
  2026-09-19) and UI-STRIP-04 (the paused `Resume`/`Do store`/`Clear and restart` row) are committed, and the index's
  own findings record that slot 0 relabels `Pause`↔`Resume` and slot 2 relabels `Clear and restart`↔`Clear all` — but
  `acquisition-ui-model.md` §3.5 names only UI-STRIP-01/02, its ledger row B10 still reads *CRITICAL device-pending*,
  `device-verification.md` still lists V4 as pending, and `acquire/ui/strip.py` still classifies a four-button
  no-slider row as `AMBIGUOUS` and refuses it. Whether that evidence settles B10/V4 — and therefore whether the code's
  refusal should change — is a disposition this plan does **not** take; it is recorded as an open finding in the agenda
  because the multiplexed store step runs straight through that row;
- how the memory cap and per-channel profile period behave in multiplexed mode (`udop-automation.md` §7's
  assertions are single-channel statements).

**Relevant revision / artifacts / live target.** `d276d6e` (worktree `feat/multiplexed-rolling-acquisition`). The
four-channel fixture `data/4-sensor-velocity/200RPM.BDD` (100 blocks × 4 profiles/channel/block) is the offline
oracle for the reader comparison. Crops that matter: UI-MENU-10, UI-STRIP-01, UI-STRIP-02, UI-OVERLAY-11,
UI-WINDOW-01. Live target: **`UDOP DOP3010.43` was running and reachable on 2026-10-19** — the passive read above
was taken from it, and captures and hovers have a working route again (`tools/live/dispatch.sh` with a task
registered for this worktree).

**Working state / recovery needs.** One live session on 2026-10-19, **read-only by construction**: a passive
control-tree walk that moves no cursor and presses nothing. Two things it did *not* do, stated so a later reader
does not infer them: no menu was opened (so no popup is stranded), and no field was written. One unintended press
did happen earlier in that session and is recorded because it touched the instrument: the primary checkout's
scheduled task still held an `acquire preflight` target, so a dispatch from this worktree ran **that** tree's
preflight (record → hold 2 s → stop → `Do store` dialog → cancel). It stored nothing, exited 0, and left the strip
`ready`; `dispatch.sh` now refuses a task that names another tree (see § *Decisions*).

## Remaining work

**Selected next (proposed, pending the owner's word).** The offline slice, in this order — all of it is checkable
without the instrument:

1. the typed mode model (criterion 2) plus its refusal matrix against the fake actuator;
2. the refusal that stops the per-point cycle while the multiplexer is enabled (criterion 3), written so that a live
   session can confirm the *reason string* rather than needing a new code path;
3. the reader-side read-back helper for criterion 6's comparison (words 51/52/53 + the block word against a declared
   request), exercised on the committed fixture.

*Stopping condition:* `ruff check src tests` clean, the suite unchanged by file and name, and a mode object that
cannot express an unverifiable mode. Nothing here touches `tools/live/` or a device.

**Blocked.** Criteria 4 and 5 (the read-only verb and the verified write) are blocked on **a live session with an
operator at the instrument** — the `Channels` anchor has to be proven on the real surface, exactly as the
`Parameters` anchor was, and an unproven anchor must refuse before any cursor movement. Unblocks with an operator
sitting; the plan's next live item is the read-only read, not a write.

**Unselected findings / open questions.**

- **Q1 — is `Acquire [n] Profiles or during [x] seconds` the visit size?** If it is, then the visit's profile count
  is a *requested* value the run record can carry, and criterion 6's comparison has two independent sides. If it is
  something else (a memory ring depth, say), the mapping has to say so before any writer is designed. Decision owner:
  a live read of the field's own values plus the stored file's word 51.
- **Q2 — does the multiplexed mode change the *strip* semantics?** The manual says the acquisition stops after the
  last sequence *or* rolls; whether the strip's classification in that state is one of the four measured views is
  unknown, and B10 (the four-button no-slider row, CRITICAL device-pending) sits directly in that territory.
- **Q3 — alignment evidence versus the alignment decision.** This plan can make a run record state the participant
  set, the order, the repeat count and the mode. Whether that is *sufficient* for the four-sensor alignment finding
  is a separate decision that the four-sensor effort owns; this plan must not settle it by implication.
- **Q4 — the decoded-metadata gate.** Words 51/52/53 have byte-level evidence and now a destination (the run record
  and the reader helper); the gate also asks for propagation rules and storage implications. Raising them into the
  domain model is a candidate change to be decided under that gate, not folded in here.
- **Q5 — is a multiplexed recording storable per visit *and* per block?** Steps 7–8 turn on the strip's own row, whose
  committed crops (UI-STRIP-03/04) have not yet been reconciled with the ledger or the code (see § *Not established*).
  If the row is a relabelling pool, a per-block store is a different gesture from a per-visit one, and the multiplexed
  store unit has to be chosen deliberately rather than inherited from the single-channel cycle.

**Deferred or excluded.** A rolling campaign/run-plan mode (after one verified record); external-trigger driving;
block-cap reading (B13 stays unproven — no invented reader); assisted mode; any generalisation of menubar driving
beyond the `Channels` surface.

## Decisions and evidence

- **2026-10-19 — the effort is mapped before it is implemented.** Owner direction recorded verbatim in §
  *Authorization boundaries*. The reason the mapping comes first: the surface that has to be driven is
  **unbound**, and the repo's own rule is that a gesture is moved, never re-derived — so the plan's value is the
  inventory plus the device-pending list, not a design that assumes the gestures.
- **2026-10-19 — this work is not based on the closeout branch.** `feat/multiplexed-rolling-acquisition` starts from
  fetched `origin/master`, matching the restart checkpoint in PR #76 ("establish a dedicated implementation branch
  from fetched master"). The retired `udv-closeout` worktree's branch and PR #76 survive unmerged and are untouched.
- **2026-10-19 — the four-sensor `time_modes` work was published separately** as PR-branch
  `feat/four-sensor-notebook-review` (12 commits, +3149/−40), because it was uncommitted in a single worktree and
  belonged to the authorized notebook effort, not to this one.
- **2026-10-19 — the first live step is the hidden panel, not an opened menu.** The dropdown's whole control tree is
  readable while hidden, so the mapping needed no gesture at all. Opening it was deliberately *not* done: this
  driver cannot dismiss a hover-opened popup (cursor restore, `ESC`, a click outside and `WM_CANCELMODE` all leave
  it up, and `WM_CLOSE` wedges the modal menu loop), so an opened `Channels` menu strands the operator's screen
  until they clear it by hand. That makes "open it and photograph the ticks" an **operator-present** step, and it is
  the only way to read the multiplexer's state (§ *The `Channels` surface, measured*).
- **2026-10-19 — a dispatch must be refused when the task names another tree.** Measured the hard way: from this
  worktree, `dispatch.sh` silently ran the primary checkout's stale `acquire preflight` target, because a scheduled
  task's action names one tree and `task_run.py` reads *that* tree's `outputs/live/`. `dispatch.sh` now reads the
  task's `<Arguments>` and refuses unless they name this clone's `task_run.py` (verified: refusal on
  `hermes_gui_probe`, runs on `hermes_gui_probe_mux`); the README and the skill's bring-up reference carry the rule
  and the second finding below it.
- **2026-10-19 — this worktree's venv was rebuilt on the system interpreter.** A venv based on the agent host's
  bundled Python cannot be launched as a Task Scheduler action (task reports *Running*, `pythonw` idles with no
  child, no log is ever written), although it works from a shell. Rebuilt with `uv venv --clear --python
  <system python>` + `uv sync --extra dev --extra acquire`; recorded in `tools/live/README.md` and the skill.
- **D3 — the `Channels` surface is a bounded exception to "no arbitrary menu driving".** The ui model (§9) excludes
  arbitrary UDOP menu driving; this plan asks for exactly one more *proven* anchor, not a general map, and it must be
  argued on the record when it is implemented. Not yet implemented.
- **Re-opening basis (for the agenda's acquisition constraint).** The capability is re-opened on the evidence class
  the constraint allows — a downstream analysis cannot establish an essential acquisition condition — not because an
  abstraction looks improvable: the four-sensor joint analysis needs a channel-time identity that the recordings and
  the reader deliberately do not provide. Recorded in the agenda in the same change as this plan.

## Next session

**Objective (proposed).** Implement the offline slice: the typed mode model with refusals, the per-point refusal
while multiplexed, and the reader-side read-back helper — with tests, no device.

**First action.** Read `acquire/actuator.py`'s `ParamRole`/`DialogField`/`StripControl` tables and `acquire/config.py`'s
value objects, then add the mode model beside them in the same style (frozen Pydantic `ValueModel`, refusals by
name, `MIN_CHANNEL..MAX_CHANNEL` bounds already defined).

**Stopping condition.** All three pieces landed with tests on the fakes, `ruff check src tests` clean, the suite
unchanged by file and name — then stop and put the two live criteria in front of an operator session rather than
inventing a substitute for it.
