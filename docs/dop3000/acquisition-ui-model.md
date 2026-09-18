# DOP3010 acquisition — the UI model: surfaces, widgets, bindings, known unknowns

**What this document is.** The authoritative description of the application surfaces the
acquisition automation is allowed to touch, the widgets it binds to, how those bindings are
made, and what is still unknown about them. It is the frozen reference for **surfaces,
widgets, bindings and known unknowns**.

**What it is not.** It does not restate the mechanism. What commits a value, in what order,
and which failure modes silently invalidate a point live in exactly one place:
[`udop-automation.md`](udop-automation.md). The architecture and the layer boundaries live in
[`acquisition-architecture.md`](acquisition-architecture.md). The verification procedure is
[`device-verification.md`](device-verification.md). Painted captions are the committed crops'
business: [`ui-element-index.md`](ui-element-index.md) + [`ui-crops/`](ui-crops/).

**Evidence levels** are used as defined in
[`acquisition-architecture.md`](acquisition-architecture.md) §1: *cloud-verified* /
*live-reported, screenshot-supported* / *device-pending*. A caption is quoted here only
with its crop id so the quote stays checkable; a code binding rule is quoted as
`path:line` at the freeze commit `bfbbb10`.

---

## 1. Surface taxonomy

Treating every extra panel as "an overlay" is what produced the wrong diagnosis in ledger
B06 and B08. The model distinguishes four kinds, and the kind is decided **before** any
target is resolved:

| kind | means | instances (with evidence) |
|---|---|---|
| **MEASUREMENT** | the clean measurement screen: menubar band, parameter column, monitor, recording strip, status bar | `UI-WINDOW-01` (`app-whole.png`) is the whole frame; `UI-SIDEBAR-01`, `UI-STRIP-01`, `UI-BAR-01` are its regions |
| **OVERLAY** | a panel drawn *over* the measurement surface — dropdown/popup, dialog, warning | the `Parameters` popup (`UI-MENU-05`), the `Operating parameters` dialog (`UI-OVERLAY-05`), the `Define TGC` overlay (`UI-OVERLAY-01`..`UI-OVERLAY-04`), the power↔TGC `Warning` (`UI-OVERLAY-23`) |
| **REPLACEMENT** | a surface that **replaces the client area**, so "no sidebar / no strip" is not a mode, it is another surface | `Measure US field` (`UI-OVERLAY-19`), `Compare profiles` (`UI-OVERLAY-21`, `UI-OVERLAY-22`) |
| **UNKNOWN** | anything the model cannot classify | the refusal state — it has no binding |

The reason the distinction is load-bearing: `overlay-full-screen-compare-profiles-add-second-curve.png`
(UI-OVERLAY-22) is a whole-window capture with **no left parameter column anywhere** — the
band the column occupies is the comparison widget's own plot field, and the menubar, strip
and status bar are gone as well. Sidebar absence therefore has at least three causes
(channel in assisted mode, the fast-access panel hidden by a preference, a replacement
surface), and only two of them are about the measurement screen at all.

## 2. The measurement-screen predicate for this experiment

Assisted mode is **out of scope** for this experiment. The predicate is conjunctive and
every clause is a refusal reason in its own right:

```text
process variant is recognised
AND the top-level surface is the measurement screen
AND no active overlay / dialog / popup / replacement surface
AND the manual fast-access sidebar is present AND complete
AND the strip observation is a known-safe state
AND the status-bar and menubar structural anchors are present
```

**No inference from sidebar absence to assisted mode.** The preference
`Show fast access parameters panel (not available in assisted mode)` can hide the column
while assisted mode is off — quoted from `UI-OVERLAY-06`, the `Preferences` dialog, where
that checkbox is the ticked one. Older code and docs inferred an assisted channel from the
absent column; a live incident disproved it (ledger B01). The refusal an absent panel
produces names the ambiguity:

> Fast-access parameter panel is absent. This automation operates a manual channel and
> requires that panel; it may be hidden by Preferences or the channel may be assisted.
> Restore/verify the manual measurement screen before continuing.

The positive form of the manual screen is measured: a channel in assisted mode is **21
visible controls in 3 panels** with no parameter column, against the clean **43 in 4** on
the simulation build and **44 in 4** on the instrument (`driver.EXPECTED_CONTROL_COUNT`
= 43, `driver.EXPECTED_PANEL_COUNT` = 4, re-exported from `acquire/ui/layout.py`, which is
where the constants live as of Patch 2; the 44/4 instrument reading
is *live-reported*, [`live-bringup.md`](live-bringup.md) §4). Those totals are **evidence**
carried in the reading — the shape verdict is what gates a run, never the total.

## 3. Surfaces, and what is known about each

### 3.1 The measurement screen

- Ten menubar entries — `File`, `Preferences`, `Parameters`, `Compute`, `Cursors`,
  `Filters`, `Tools`, `Channels`, `Display`, `Help` — with `Help` closing the band's right
  end (UI-WINDOW-01). A cut crop of the band shows only the first nine (UI-MENU-01).
- The left parameter column paints its row **labels**; they are not controls. UI-WINDOW-01's
  frame carries **ten** rows including a `Tgc [dB]` row reading `40`; UI-SIDEBAR-01's frame,
  57 minutes earlier, carries **nine** and paints no `Tgc [dB]` row. Both are committed; the
  mode's own TGC state is what moves that row (ledger B02), and the discrepancy is recorded
  in the index's own cross-checks rather than resolved here.
- The status bar (`UI-BAR-01`) reads `Profile`, `CH`, `Block`, `Memory`, and
  `Time bewteen profile = 22.3 ms` (spelling as printed).
- The strip floats **inside the monitor** in UI-WINDOW-01 (about x 344-693, y 415-452) and
  is draggable; its rect is a property of the moment it was shown, never a constant.

### 3.2 The `Parameters` popup

Four to five entries in this build, painted with captions although the control tree carries
none (UI-MENU-05, which is the oracle the plan says it lacked):

`Operating parameters`, `Default parameters`, `Save parameters`, `Recall parameters`,
`Tigger parameters` (the build's own spelling of *trigger*).

The manual's v6.6/6.7 menu lists `Assisted mode parameters` as its own entry; **this build
has no such entry**, and an assisted panel is reached by selecting a channel that is in
assisted mode instead (*live-reported*,
[`handoff-dop3010-acquisition.md`](handoff-dop3010-acquisition.md) §3). The popup panel is
**pre-created in the tree at startup with `IsWindowVisible == False`** — presence is not
visibility, and a rule that accepts presence presses real coordinates into empty screen.

### 3.3 The `Operating parameters` dialog

Measured geometry (*live-reported*): panel `627x384` at `(655, 364)`, 21 direct children /
42 descendants, seven `TSp_Value_Button` value fields, header channel combo
`Operating parameters for channel [n ▼]` at `(1083, 373)` listing `1`…`10`, and a bottom
band of **four** buttons: two wide indicator buttons and then the narrow `Cancel` and
`Accept` pair. The committed crop UI-OVERLAY-05 shows the same dialog on channel `1` with
its painted cells and its green `Sampling volumes overlapped` line.

Two hazards follow from that shape, both already paid for live:

- the bottom button pair is the **last two of the band sorted by `left`**
  (`row[-1]` = accept, `row[-2]` = cancel), never the band's leftmost — the leftmost is an
  indicator button and pressing it leaves the dialog open;
- **the application replaces the dialog when the channel changes**: every handle taken
  before the write is dead, so a read-back and the accept must use a re-resolved panel.

> The read/write recipes for these fields — resolution before gates, combo selection by
> value, the `Accept`-committed transaction, re-open before belief — are in
> [`udop-automation.md`](udop-automation.md); do not restate or "improve" them here.

### 3.4 Overlays with a committed crop

`Define TGC` in all four `Mode` states (UI-OVERLAY-01 `Uniform` with `Start [dB]` and no
`Recompute`; UI-OVERLAY-02 `Auto` with `Recompute` and no `Start [dB]`; UI-OVERLAY-03
`Slope`; UI-OVERLAY-04 `Custom`); `Preferences` (UI-OVERLAY-06); `Record settings`
(UI-OVERLAY-07, whose `Do not keep in a block more profiles than` reads `932068` in that
frame and whose yellow line states `Your memory can record up to 2097152 profiles`);
`Recall parameters from` (UI-OVERLAY-08); `Save parameters on` (UI-OVERLAY-09);
the default-parameters `Warning` (UI-OVERLAY-10); `External Trigger settings`
(UI-OVERLAY-11, `unknown (not classified)` in the index's blocking column); `Sound speed
measurement` (UI-OVERLAY-12); `Raw data acquisition settings` (UI-OVERLAY-13); `Update
files` (UI-OVERLAY-14); the `Sweep PRF` overlay behind `Tools > Search artefacts` in both
its idle and running states (UI-OVERLAY-15, UI-OVERLAY-20 — the running state paints a
live `562 us` readout and a `Keep and exit` button); `Auto correction of the aliasing`
in both forms (UI-OVERLAY-16 disabled, UI-OVERLAY-17 enabled); the cursor info window
(UI-OVERLAY-18); and the power↔TGC `Warning` (UI-OVERLAY-23: caption `Warning`, message
`The TGC is in auto mode. Changing the emitting power` / `will modify the TGC mode and
amplification`, buttons `Cancel` and `Continue`).

Two surfaces are **deliberately unmapped**, not to-dos: `Compare profiles`
(UI-OVERLAY-21, UI-OVERLAY-22) — the comparison this experiment wants is done in the
operator's own post-processing — and the caption-less sampling-volume rejection, which is
**deliberately deferred** because a crop of it would capture a shape rather than words.
`Measure US field` (UI-OVERLAY-19) is a **replacement** surface: it is cropped as a region,
and the operator's statement that it replaces the monitor with a single echo plot is *not*
readable from that crop.

### 3.5 The recording strip

| view | structural signature | buttons, left → right | evidence |
|---|---|---|---|
| recording | one top-row button, no slider | `Stop` | *live-reported* |
| stopped, no data | fewer than three buttons | `Record` | *live-reported* |
| stopped with data | three top-row buttons, **no** slider | `Pause` / `Record` / `Clear and restart` | UI-STRIP-01, three captions read at x10 |
| store view | three top-row buttons **+** a `TSp_Sliding_Bar` child | `New acquisition` / `Do store` / `Clear and restart` / `Remove current block` | UI-STRIP-02 (grown, four captions read at x8-x10) |

**The four-button, no-slider row is unresolved and is the highest-priority device item**
(ledger B10). UI-STRIP-01's ready frame paints `Pause` / `Record` / `Clear and restart`;
UI-STRIP-02's grown frame paints `New acquisition` / `Do store` / `Clear and restart` /
`Remove current block` — so the third slot is demonstrably the same button, while the first
two are not the same captions. Whether the button at index 1 is one control that relabels,
or two different buttons, is a question **only a tree read in that exact state can
answer**, and a tree and a screenshot may not be the same instant.

**That refusal is landed** (Patch 2's widget slice, `acquire/ui/strip.py` + `actuator.py`): a
row of four buttons and no slider classifies as `StripView.AMBIGUOUS`, `STRIP_BUTTON_ORDER` has
**no row for it**, `StripState.is_startable` is `False`, `strip_controls` / `press_index` refuse
it, `Win32Actuator.press` refuses **before** the held press is posted (nothing is pressed and
nothing is recorded), and `layout_shape_reasons` refuses the row instead of gating a run on it.
The state itself — which role each of the four buttons has — stays **device-pending**: V4 in
[`device-verification.md`](device-verification.md) is what resolves it, and the day it does, the
role map goes into `STRIP_BUTTON_ORDER` and this paragraph changes with it. Nothing in this
document claims the row behaves on the instrument; the claim is only that no press comes out of
it until a live tree settles it. The strip's other views are *live-reported* and were measured in
simulation; the grown panel's rect in UI-STRIP-02 is a fourth measurement (about `594x123`)
and is not either of the two views the plan records as unmeasured.

## 4. Widgets

- **Every widget is caption-less.** `WM_GETTEXT` returns `""` for nearly all of them and
  the column's row labels are not controls at all, so a caption exists on the screen or not
  at all. Captions are quoted from crops with their id; they are never used as runtime
  identity.
- **A `control_id` is a per-instance handle, not an identifier.** Bind by role — class plus
  its containing panel plus order within it — and re-resolve to a live handle at run time.
  The measured case: across two launches of one executable, 43/43 classes at the same
  sorted position and 1 of 43 ids in common.
- **A combo's child edit can hold stale, unpainted text.** `WM_GETTEXT` on a combo's inner
  `TSp_Edit` returned the same stale string (`89`) in three unrelated combos while the
  combos themselves painted `medium`/`Medium`; a crop of that same dialog paints no `89`
  anywhere. A combo's parameter value comes from the combo's own selection/text; an unpainted
  edit's text is a buffer value, never a fallback (ledger B09).
- **A `TSp_Value_Button` wrapper and its inner combo that report the same control id are one
  widget** — one entry in the map, not two.
- **The bottom button band is the last two of the band, not the first two** (see §3.3).
  Identity is positional; never a width or a title.
- **The application confines the cursor inside its popups** (`ClipCursor`); the Store dialog
  clips the pointer to its own rect and releases on `Cancel`. Posted messages are immune,
  but a dialog left open traps the operator, and a clipped `SetCursorPos` is clamped
  *silently*. Test clipping behaviourally — move the cursor somewhere no dialog is and read
  it back — and probe **after** the interaction of interest, because moving the cursor closes
  a hover menu.
- **The menubar needs real cursor input; everything else takes posted messages.** A hover
  (`SetCursorPos` onto the resolved button centre plus one short relative `mouse_event` move)
  is what opens the popup; the entry is then taken with a plain **posted held press** on the
  entry's own handle (~180 ms hold), exactly like a strip button. Do not "improve" the entry
  press into a real click: a re-derived click on the same entry opened nothing.
- **Dialog panels have a Close button and it works; popups do not.** Never `WM_CLOSE` a
  popup: it wedges the modal menu loop until the application is restarted.
- **Never `EnumWindows` to detect a dialog** — the Store dialog is a **child panel**, so no
  top-level window appears and the check reports "nothing happened".

## 5. Bindings — what may be bound, and how

**The only supported binding rules are these; each was paid for live.**

| binding | how it is made | what may not stand in for it |
|---|---|---|
| **`Parameters` anchor** | a structural/relative-location signature for one dedicated anchor, then **verify the popup/dialog that appeared**; if the anchor cannot be proven, refuse *before* the hover. **Landed** (Patch 2's widget slice, `acquire/ui/menu.py`): the resolver publishes the anchor only when the bar's painted length is one of the two measured ones (ten entries, `UI-WINDOW-01`; or the eleven-name vocabulary `MENU_ORDER` carries) and the anchor is the third button of that bar; otherwise **no** binding is published and `Win32Actuator._open_parameters_dialog` refuses, naming the clause, before the cursor is read or moved. A binding a tree *does* publish is held to agreement with the bar (its names in the vocabulary's own left→right order, `Parameters` bound to the third entry) — **corrected 2026-09-18**: the first version instead demanded that the entries to the anchor's left be *named* `File` and `Preferences`, which no tree can state, and it read the binding it was itself the precondition of, so it refused the instrument's own clean screen (V0; see [`device-verification.md`](device-verification.md) §Session record) | a generic `MENU_ORDER[i]` map. Simulation and instrument builds do not paint the same menubar buttons and tree button text is empty, so an index map silently renames later entries when one is absent — the current item happening to sit at index 2 is accidental safety, not a rule (ledger B03). An anchor proved by its index in a name list is that same map |
| **popup entry** | order by screen `top`, press the entry's own handle with a posted held press; the overlay **and** the entry must report `IsWindowVisible == True` first | the highlighted entry (the application highlights `Default parameters` by itself), a title match, or a real click. A press on an entry closes the popup, so what must be read about the popup is read **before** the gesture |
| **dialog identity** | structural: a panel that is not the sidebar, wider than 400 px, full of controls (≥15 direct children, or a `TSp_Browse`, or input controls) — and **then** its content (the channel combo) tells the operating dialog from another dialog | requiring the channel combo to decide whether a dialog opened at all; that is stricter than the evidence and rejects a correctly opened dialog |
| **dialog bottom pair** | the last two `TSp_Button`s of the bottom band sorted by `left` | the band's leftmost button, a width, or a caption |
| **strip state** | structural classification into `StripKind`; an executable `StripBinding` exists **only** for known-safe states. **Landed** (Patch 2's widget slice): `classify_strip_view` answers `AMBIGUOUS` for a four-button no-slider row, `STRIP_BUTTON_ORDER` holds no row for it, and the press path refuses before the held press | a count-only verdict. Every three-to-four-button no-slider row classified as `READY` is exactly the unsafe behaviour; the four-button row maps to `AMBIGUOUS` and binds nothing |
| **parameter field** | widget-type-aware extraction: numeric edits by their own value; combos by selection/text; each field's value read back from the re-opened dialog or from the stored file | a combo's child edit, a control's painted text as proof of what the application kept, or a dialog read before the channel is attributed |
| **channel** | the dialog's channel combo is compared against the **routed** channel before any of its facts are accepted | assuming the dialog is the one the router selected |

The combination rules — which field to write first, when an `Accept` commits, when a
re-open is mandatory, when a stored artifact must be decoded — are in
[`udop-automation.md`](udop-automation.md) §§2–4, and in the plan's §18–§19 for the writer
design.

## 6. Known unknowns — the blind-spot ledger

Each row is a mechanism that has already been observed or measured somewhere, with the
engineering risk it creates, the response the refactor adopts, and — most importantly —
**what may be asserted before the next device session**. Status wording: *cloud-supported*
means committed evidence exists in this repository; *live-reported* means a device
observation is recorded but cannot be reproduced here; *device-pending* means the
assertion is not available yet.

| ID | mechanism / blind spot | risk | refactor response | status before device |
|---|---|---|---|---|
| B01 | the sidebar can be hidden by `Preferences` independently of assisted mode (UI-OVERLAY-06) | a no-column screen is misclassified as assisted | stop inferring channel mode from absence; a manual sweep requires a complete sidebar; refuse with an ambiguity message | cloud-supported by committed live record; device regression pending |
| B02 | TGC `Uniform`/`Auto` changes the visible-control total (44 vs 42) | false clean-layout/resume mismatch | counts are diagnostic only, never a gate and never in the identity | live-reported, screenshot/docs supported |
| B03 | menubar buttons differ between app variants and tree captions are empty | an index map silently renames menu roles | dedicated `Parameters` anchor + post-open verification; no generic menu role list — **landed by Patch 2's widget slice**: `acquire/ui/menu.py` publishes the anchor by its relative location in a bar of a measured painted length, and publishes none (refusing before the hover) when it cannot. **The first version of that clause was corrected on the instrument 2026-09-18** (`e1a8e47`): it demanded the names of the entries left of the anchor — which no tree states — and read the binding whose publication it was itself the precondition of, so it refused the application's own clean measurement screen; the proof is now positional, and a *published* binding is held to agreement with the bar | **precondition verified on the instrument** (V0, 2026-09-18: the clean screen proves the anchor again); the gesture half of V2 (hover → popup → topmost entry → dialog) stays device-pending |
| B04 | popup/dropdown contents can be state dependent | entry-by-index can hit the wrong action | each menu surface owns its own binding; the `Parameters` recipe only, not generalised | screenshot/docs supported |
| B05 | the raw tree grows after first-show surfaces | total tree size, handles and pre-show rects are unstable identities | bind a normalized visible projection; raw rows are diagnostics | fixture/docs supported |
| B06 | an overlay can be selected as a strip candidate | misleading diagnosis; a wrong press if checks are reordered | classify the active surface before the target resolver; refusal precedes diagnostics | live-reported; offline synthetic regression required |
| B07 | Alt-Tab can release cursor capture | modality is not a safety boundary | a software gate before every press; expect multiple coexisting surfaces | operator/live-reported |
| B08 | `Compare profiles` / `Measure US field` replace the client content | "no sidebar/strip" may be another surface, not a mode | explicit `SurfaceKind` including replacement and unknown | screenshots support |
| B09 | a combo child edit can hold a stale/unpainted `89` | a wrong parameter read reported as a fact | widget-specific extraction; no child-edit fallback | fixture + screenshots support |
| B10 | the four-button no-slider strip has a contradictory role map (UI-STRIP-01 vs UI-STRIP-02) | a destructive wrong strip press | classify as `AMBIGUOUS`/`UNKNOWN` until the exact device tree is captured; no binding, no press — **the refusal is landed by Patch 2's widget slice** (`StripView.AMBIGUOUS`, no `STRIP_BUTTON_ORDER` row, the gate refuses, and `press` refuses before the held press); the role map stays open | **CRITICAL device-pending** (the refusal is cloud-verified; the role map is not) |
| B11 | TGC `Auto` + emitting power raises a `Warning` with side effects (UI-OVERLAY-23) | answering `Continue` rewrites TGC mode and amplification | state the scientific coupling in the matrix and keep an explicit policy; never auto-`Continue` | screenshot supported |
| B12 | the application's own PRF search actively writes PRF (`Tools > Search artefacts`, UI-OVERLAY-15/20) | campaign state changes outside the sweep | use it only before a run, if at all; re-state and re-read the complete frame afterwards | screenshot/operator supported |
| B13 | the block cap is painted in `Record settings` (UI-OVERLAY-07) but no production read path exists | false wrap/retention certainty | leave unproven; implement no invented reader | screenshot supported |
| B14 | a process "mode" is in fact a distinct build/variant (simulation `UDOP Simul` vs instrument `UDOP DOP3010.43`) | treating one mutable mode confuses lifecycle assumptions | call it the **process/app variant** in the internal model; keep the caption as the evidence (`UI-WINDOW-01` title bar) | docs/live supported |
| B15 | screenshot captions exist where `WM_GETTEXT` is empty | runtime cannot use visual text as control identity | keep the visual oracle separate from the runtime tree binding | screenshot + tree supported |
| B16 | dialog values can be stale until the dialog is reopened | an immediate read-back lies | `Accept`, then reopen before belief; the stored `.BDD` is the final authority | live-proven |
| B17 | the dialog's channel attribution can differ from the routed channel | facts attached to the wrong channel | compare the dialog channel to the routed channel before accepting dialog facts | previously identified; verify current behaviour on device |
| B18 | multiple parameter frames appeared across assisted/manual/tour operations | session state drifts far from the declared frame | compile against a live snapshot immediately before the campaign | live-supported |
| B19 | the Store dialog (and other modal panels) clip the cursor | real-input recovery can fail | drive by messages and always close in a `finally`; state is unverified if the close fails | live-proven |
| B20 | a popup cannot be safely dismissed programmatically | a recovery gesture wedges the application | abort and require an operator restart; never `WM_CLOSE` | live-proven |

## 7. Priority before any real acquisition after the refactor

1. **B10** — the four-button strip state (device tree, then a role map, then a binding).
2. **B01** — the sidebar/manual-mode prerequisite.
3. **B03** — the `Parameters` menubar anchor on the real process.
4. **B06** — overlay-first surface classification.
5. **B17** — dialog/routed-channel attribution.
6. The existing compile mismatch, the six-point campaign and resume — i.e. the standing
   acceptance rehearsal in [`live-bringup.md`](live-bringup.md) §§3-4, re-run after the
   refactor.

## 8. Reading the committed oracle

The 45 committed crops in [`ui-crops/`](ui-crops/) plus the row-per-crop
[`ui-element-index.md`](ui-element-index.md) are the **only** oracle for painted captions.
The index is checked, not trusted:

```bash
uv run --extra acquire python tools/ui/crop_index.py
# index rows: 45   crops on disk: 45   families: {'UI-BAR': 1, 'UI-MENU': 17, ...}
# ok: every indexed crop exists, is the size the index states, and is numbered without a gap
```

It exits non-zero on any mismatch; run it in the same change as any crop added, renamed or
withdrawn. `tools/ui/magnify.py composite|glyphs` is the two-step read (x5-x6
nearest-neighbour, then glyph bitmaps against a digit known in the same frame) that the
index's own method section requires — measured traps: `600` read as `500` (twice), `3.49`
for `0.49`, `725` for `726`, and two independent vision passes agreeing on a wrong number.
See [`tools/ui/README.md`](../../tools/ui/README.md).

## 9. Deliberately out of scope

Do not generalise, and do not implement writers for: arbitrary UDOP menu driving; assisted
mode as an operating mode; automatic popup recovery; arbitrary dialog writers; app-side
`Compare profiles` / cursor statistics; `Record settings` manipulation; a generic
"all parameters" sweep. A writer exists only when the sensitivity matrix names the axis.
