# Plan — give every live panel one identity before any resolver can act

## 1. Why this plan exists

This is the evidence-triggered exception to the acquisition architecture stop condition in
[`acquisition-campaign-compilation-plan.md`](acquisition-campaign-compilation-plan.md) §9.1. It does not reopen
the acquisition design. It closes one device-measured defect shared by five symptoms:

1. the dialog predicate admits the 453/502/551 px acquisition strip and the 450 px `Define TGC` overlay;
2. it misses the application's reused 392x132 destructive warning guard;
3. excluding the real strip from the strip vote lets the cursor info box or warning guard become the strip;
4. the generic popup test then treats the info box's out-of-panel button as a menu popup;
5. each wrong identity can hide another, so a safe refusal reports whichever symptom survives rather than the
   surface actually on screen.

The device evidence is [`device-verification.md`](device-verification.md), *the four-button strip,
block-held* and *sitting C, V3*. The fix is warranted because V3 now fails its required diagnosis on the live
instrument, not because the abstractions could be cleaner.

## 2. Boundary: one identity pass, not five patches

Introduce one internal panel-identity result used by the dialog union, strip resolver, popup flag, surface
classifier and cleanup paths. A panel is classified once from its tree shape and screen context before any of
those consumers exclude or vote on it.

The identities required by current behaviour are:

- **measurement strip** — including all measured 352/370/453/502/551 px forms;
- **menu popup** — the Parameters popup, not “any panel that owns a button”;
- **application dialog** — the measured Operating parameters dialog and existing browse/store dialogs;
- **warning guard** — the measured warning family and the store path's overwrite warning; the tree does not
  claim which warning text is painted;
- **replacement screen** — existing `Compare profiles` / `Measure US field` behaviour remains distinct;
- **non-measurement overlay** — including `Define TGC`;
- **cursor info box** — an incidental painted surface, neither a target nor a readout;
- **other** — unknown and therefore non-actionable.

Do not encode live handles, the instrument's absolute coordinates or one build's panel order as identity.
Handles and rects below are evidence and fixture inputs only. Simulation and instrument geometry differ.

### 2.1 Classification order and structural warrants

The classifier is ordered from the narrowest actionable shapes to the broadest fallback:

1. **Menu popup.** Reuse the Parameters popup's demonstrated predicate and entry containment
   (`parameters_overlay` / `entry_buttons`). Replace the generic `open_popup` panel vote with this identity.
   Unknown button-hosting panels are not popups.
2. **Browse/store dialog.** Preserve the existing `TSp_Browse` + edit discriminator before the warning-family
   rule. A store dialog is never a warning and must retain its commit path.
3. **Warning guard.** Preserve the measured family rule: a compact panel wider than 250 px and taller than
   90 px with a two-button bottom row, after store dialogs are excluded. Fixtures cover 392x132, 397x135 and
   353x155; the store overwrite warning's geometry is not measured, so the family rule—not one rect—carries
   it. The tree cannot distinguish the two destructive warnings; any generic warning answer is left/Safe.
   A panel holding a `TSp_Value_Button` of its own is not the family at all: every measured guard
   carries only its two buttons, while the values-dialog class (`Operating parameters`, `Record
   settings`) is exactly the class that holds value buttons directly — the same fact the resolver
   splits its dialogs by. Without that clause a compact command dialog with a two-button band is
   claimed as a warning and leaves the dialog union, so a caller that asked to *read* it is answered
   as a destructive guard. The residue is recorded rather than hidden: a compact (fewer than
   `_DIALOG_MIN_CHILDREN`) non-store command dialog is not yet distinguishable from a
   non-measurement overlay, so it is refused as a blocking surface rather than read. No such panel
   is measured; the device settles it when one is.
4. **Measurement strip.** Resolve it independently of the dialog union. Its warrant uses `strip_row`'s exact
   geometry: button centres inside the panel, button `top < panel.top + 30`, left-to-right, in the plot-band
   context already used by the resolver. Identity and binding are separate: the measured 453x40 four-button,
   no-visible-slider row is the strip but remains `AMBIGUOUS` and unbound. A direct `TSp_Sliding_Bar`
   strengthens identity but cannot be required. This rejects the info box (owned button outside the panel),
   warnings (two bottom buttons), and `Define TGC` (its measured buttons begin 46–89 px below panel top).
5. **Cursor info box.** A small caption-less panel containing a caption-less child panel, with no in-panel
   actionable row; an owned button whose centre lies outside the panel does not confer strip or popup
   identity. It is ignored by action routing. Its painted depth/velocity remain out of scope.
6. **Replacement screen.** Preserve `_replacement_evidence` and its precedence over overlay unchanged;
   committed `Compare profiles` / `Measure US field` fixtures must remain `REPLACEMENT`.
7. **Non-measurement overlay.** Classify `Define TGC` as `OVERLAY` before the broad input-class dialog fallback,
   but not by reusing `_overlay_candidates` unchanged: today it returns empty when no strip resolves. Evidence
   comes from the 2026-09-18 read-D tree (`tgc-d-overlay-open.json`) and existing crop-derived test fixture;
   sitting C independently confirms the 450x120 panel and that the real strip panel is absent from the
   **visible** panel set. Two plots are corroborating evidence, not a required production discriminator.
8. **Application dialog fallback.** After the identities above are excluded, preserve `_is_dialog_panel` for
   the measured Operating parameters dialog (627x384, 21 direct children) and non-store dialogs. Width alone
   remains insufficient.
9. **Other.** Refuse without guessing.

This removes the current circularity: dialog membership may not decide which panel is the strip while strip
membership simultaneously decides which panel counts as a popup.

### 2.2 The admitting clause and the decoy, measured off the kept trees

Re-read offline with the **unmodified** predicates against the 2026-09-19 dumps under `outputs/live/keep/`
(probe `tools/live/probes/main_geometry.py`; each dump carries the whole 273-row tree, so a panel's *direct*
children are the dump's own parent links):

| panel | state | `_is_dialog_panel` | the clause that decided it |
|---|---|---|---|
| 453x40 | the intermediate four-button strip | **True** | one direct `TComboBox` |
| 502x123 | the grown strip after a removal | **True** | one direct `TComboBox` |
| 551x123 | the grown strip, block held | **True** | one direct `TComboBox` |
| 370x123 | `Pause` / `Record` / `Clear and restart` + slider | False | `w > 400` only |
| 392x132 | the reused destructive guard, both warning states | False | `w > 400` only |
| 149x59 | the cursor info box | False | `w > 400` only |

Three corrections to the account in §1 and §2.1:

- **The clause that admits the strip is the input-class one, not "full of controls".** Each admitted strip
  panel directly owns exactly one `TComboBox` — the `Show block` combo — and `_DIALOG_INPUT_CLASSES` accepts
  that for any panel wider than 400 px. A fix that narrows *shape* while leaving the input-class clause
  unconditional would leave the 453 row red and the 370 row green for the wrong reason: 370 escapes only
  because the sizing rule happens to stop 30 px short of the width guard.
- **The guard is not admitted at all** (`392 <= 400`), in either warning state, so "the predicate misses the
  warning family" is exact. What the guard does instead is win the **strip** vote: `strip.panel_id` is the
  392x132 panel in both warning dumps, and the cursor info box (`131916`) in the block-held and intermediate
  ones, which is present in every one of those reads and holds its caption-less button in the held states.
  The §1 chain is therefore reproduced without the instrument — and item 4's warrant has to reject the guard
  and the info box on its own evidence rather than on the dialog union.
- **A strip panel's children can lie outside its own rect.** In the 453x40 state the panel is
  `[343,414,796,454]` while the row's four buttons paint at y 423-444 and the two `Profiles history` toggles
  at y 467-482. Item 4's warrant survives this (`top < panel.top + 30` with an in-panel centre excludes the
  pair); a rule that asks *only* for "inside the panel" does not.

## 3. Consumer rules

All consumers take the same classified inventory; none re-derives panel meaning.

- `_resolve`: publish the identities alongside roles. Select the strip only from `MEASUREMENT_STRIP`; derive
  `value_dialogs` / `browse_dialogs` only from `APPLICATION_DIALOG`; derive `open_popup` only from
  `MENU_POPUP`. Add an explicit blocking-surface result for warning/overlay/dialog so narrowing `open_popup`
  does not erase safety information.
- `surface_kind` / `surface_clauses`: keep `REPLACEMENT` ahead of `OVERLAY`; state warning/overlay/dialog/real
  popup before strip/sidebar clauses. A missing strip under `Define TGC` is a consequence, not the diagnosis.
- every current `open_popup` consumer must migrate deliberately: `ScreenObservation.popup_open` receives only
  a real menu popup; recording's held-strip guard consumes the blocking-surface result; the parameters
  gesture's stranded-surface note names warning/overlay/dialog/menu and who must clear it; cleanup survivor
  reporting names a remaining classified surface rather than silently dropping warnings/overlays.
- recording presses: a warning guard is handled only by the existing overlay answer path and only with
  `DialogControl.SAFE`. The warning must never pass through generic dialog cleanup even though the same left
  button would currently result; one path owns one meaning. An unknown panel has no answer.
- `_open_parameters_dialog`: refuse before hover if any warning, overlay, dialog or real menu popup is up.
  Never infer a popup from the info box.
- `_close_any_dialog`: accept only `APPLICATION_DIALOG`. It must never pass a strip, warning, TGC overlay,
  info box or unknown panel to `bottom_row[-2]`.
- strip actions: continue binding by the visible row's live left-to-right index after strip identity is proven.
  The existing index-0 role name is not corrected by this change; the live record supersedes its old crop
  caption, and executable mapping remains a follow-up. **And the strip's own row is the pressable row** once
  that identity is proven: the measured 370x123, 502x123 and 551x123 states stop refusing because their panel
  was called a dialog (502/551) or because the info box made the screen report a menu (370) — false refusals
  from the defect this plan closes, not safety properties. What stays refused is the *ambiguous* four-button
  453x40 row, by `ui/strip.py`'s own named refusal, and nothing else changes: no cleanup, no parameters
  gesture and no dialog close may address any strip panel's band (§3.1, §4 Slice 3).

### 3.1 The cleanup hazard this plan must close

The 453x40 intermediate strip is admitted by the dialog predicate — measured, not inferred:
`ui.dialog._is_dialog_panel` returns True for the `[343,414,796,454]` panel of
`outputs/live/keep/main-geometry-2026-09-19-intermediate.json`, on its one direct `TComboBox` (§2.2). Its
broad “bottom 70 px” row then resolves **six** buttons rather than the row's four: left -> right the two
caption-less `Profiles history` toggles (`2690436` at `[350,467,401,482]`, `1967842` at `[409,467,453,482]`,
painted below the panel's own 40 px rect and inside the band), then the row's `1574908` `[353,424,432,444]`,
`4787852` `[442,424,527,444]`, `2821164` `[537,423,628,443]`, `1641666` `[638,423,776,443]`. So a cleanup
path's safe end (`row[-2]`) lands on `2821164` — the control the same-process handle map binds as
**`Do store`** — and its confirm end (`row[-1]`) lands on `1641666` — **`Clear and restart`**: *both* ends
are state-changing strip controls, and even `row[0]` is not the row's first button. This is code- and
tree-proven, not a device claim. The first regression test must make that press impossible before any
production edit proceeds, and it must assert against the **six-entry band**: a four-button fixture makes it
pass for the wrong reason.

The V3 status run did not exercise cleanup, so no document may claim that `Define TGC` cleanup is presently
safe or unsafe. The implementation must establish safety through classification tests first, then a bounded
operator-attended device recheck.

## 4. Implementation slices

Each device-forced correction is its own commit. Do not mix behaviour changes with fixture or record edits.

### Slice 1 — prove the measured counterexamples red, then land the tests with Slice 2

Add a surface-identity matrix assembled from named evidence sources; each row states whether it is a raw tree,
a committed fixture or a synthesized measured shape. The states the instrument produced on 2026-09-19 already
exist as raw trees under `outputs/live/keep/` — `…-intermediate.json` (453x40), `…-after-removal.json`
(502x123), `…-blockheld.json` (551x123), `…-pause3.json` (370x123), `…-clearall-warning.json`
and `…-remove-warning.json` (the 392x132 guard) — and the fixtures are those trees **sanitised to the
committed convention** (`cls` / `text` / `rect` only, no handles, no parent links), the shape
`tests/data/udop-measurement-screen-tree-instrument.json` already has. It covers:

- strip: 352, 370, 453, 502 and 551 px, with absent/visible slider and an explicitly excluded hidden node;
- warnings: measured 392x132, 397x135 and 353x155 two-button forms, plus an unmeasured-geometry overwrite
  warning case carried by the family rule;
- cursor box: child panel plus parent-owned button outside the panel;
- Parameters popup: the existing 169-left / >120-high shape and five entries;
- `Define TGC`: the 2026-09-18 read-D tree, crop-derived test fixture and sitting-C 450x120 confirmation kept
  as three distinct evidence sources;
- replacement screens: both committed replacement fixtures;
- Operating parameters: the committed 627x384 / 21-direct-child fixture;
- browse/store dialog: the existing synthetic driver fixture, distinguished before warning classification.

For each case assert identity, dialog-union membership, strip selection, `open_popup`, blocking-surface result,
surface kind and the first refusal clause. Add a cleanup negative control in which any attempted press raises;
the 453x40 strip must make the pre-fix code try `Do store`, proving the test can see the hazard. The Slice 1
commit is intentionally red only as a demonstrated pre-fix run; land the tests with Slice 2 rather than leave
the branch red.

### Slice 2 — centralize identity, preserve observation output

Add the smallest internal identity type/helper and route `_resolve` through it. Keep existing role keys and
`ScreenObservation` fields stable; this is a behaviour correction, not a public model redesign. Update the
existing dialog, surface-classification, instrument-screen and strip-ambiguity tests rather than duplicating
their assertions.

Pass when the matrix says:

- every strip shape is the strip and never a dialog; the 453 row remains ambiguous/unbound;
- every measured warning-family shape is `WARNING`, never strip/dialog/popup;
- browse/store dialog is `APPLICATION_DIALOG`, never warning, and the overwrite-warning continuation remains
  available after the store dialog is handled;
- info box is incidental, never strip/popup;
- `Define TGC` is `OVERLAY`, never dialog or replacement;
- both replacement fixtures remain `REPLACEMENT`, never overlay;
- real Parameters popup alone sets `open_popup`;
- Operating parameters remains `DIALOG`;
- the clean instrument fixture remains ready, 44 controls / 4 panels, no false surface.

### Slice 3 — make action and cleanup paths consume identity

Route `dialog_up_clause`, recording overlay discovery, `_open_parameters_dialog`, `_dialog_panels` and
`_close_any_dialog` through the shared result. Remove only predicates made redundant by that routing.

Required negative assertions:

- no press for strip, `Define TGC`, info box, unknown panel or menu popup;
- warning answer is left/Safe only, never Confirm, including the overwrite-warning continuation path;
- a failed gesture with warning/overlay/menu still reports the surface and names the operator remedy;
- cleanup cannot press `Do store` on the 453x40 strip, and no cleanup, gesture or dialog close may address
  a 502/551/370 strip band either — those shapes are non-actionable **for those paths**, which is what §3
  intends, while the strip's own bound press (a proven identity plus a startable state) is unchanged by this
  change and is not what this bullet refuses;
- no hover occurs when a blocking surface is already identified;
- browse/store dialog remains distinct from warning and retains its store behaviour;
- a real Operating parameters dialog still closes by its left/Safe end and screen recheck;
- failure to identify a surface leaves the application state unverified and asks for the operator; it does
  not attempt recovery.

### Slice 4 — refusal wording and stale-document corrections

Make V3's expected first reason name an active overlay/non-measurement surface. Strip/sidebar reasons may
follow as evidence but may not precede or replace identity. The document half of this slice **landed with
[#15](https://github.com/ajegorovs/udv-echo-process/pull/15)**: the five-button pool supersedes “ready gains
Do store”, V1 disproves “missing column means assisted”, and the `89` edits are buffer values. What remains
here is the V3 first-clause wording and the V1/V3/V4/V5 status table's agreement with the device record.

## 5. Verification ladder

### Cloud gates

1. Run the focused identity, layout, dialog-guard, dialog, strip-ambiguity and instrument-screen suites.
2. Run `ruff check src tests`.
3. Run the full pytest suite and record counts/timing.
4. Independently review the diff for two forbidden patterns: absolute live handles/rects in production
   identity, and any new Confirm/hover/strip press.

### Device gates — operator attended, in this order

Take and preserve a clean read before the first behaviour-changing commit, then rerun the identical command
at the final head and compare fields.

1. **Clean screen:** read-only status stays measurement/ready with the same application fields.
2. **V3:** operator opens `Define TGC` without changing it. Status must put the overlay clause first in
   `layout_shape_reasons`, and `layout_evidence` must say the active surface reads `overlay`; it must not name
   dialog/popup/strip first, and automation sends no input. Operator cancels; clean status restores.
3. **Info box:** operator places one cursor. Read-only status must remain a measurement surface, resolve the
   real strip when present, and report no popup. No attempt is made to read painted cursor numbers.
4. **Grown strip:** operator reaches one 453/502/551 state already understood by the state tree. Read-only
   status must identify the strip and must not report a dialog. Automation presses nothing.
5. **Warning guard:** operator raises one already-understood destructive guard but does not confirm it. A
   read-only status must identify `WARNING`, not strip/dialog/popup. The operator presses Cancel. Do not
   provoke a new warning path.
6. **Cleanup safety:** only after cloud negative tests pass, with UDOP foreground, no popup open and the
   operator present, run
   `PROBE_TIMEOUT_S=240 ./tools/live/dispatch.sh w1_fixed_facts.py`. This is the existing read route whose
   `read_dialog_parameters` `finally` calls `_close_any_dialog`; it may press only the real Operating
   parameters dialog's left/Safe end. Preserve pre/post status logs because the probe's `dialog_closed` key is
   not a screen check. Do not run cleanup against `Define TGC` merely to prove a negative; V3's no-input
   status and the press-raising tests are the proof.

Any changed clean-screen fingerprint, unknown modal, stranded popup, attempted strip press, Confirm press or
unverified state stops the device session. The operator restores/restarts; automation does not improvise.

## 6. Acceptance and non-goals

Done means one classifier supplies every consumer, all measured counterexamples pass, the full cloud suite is
green, and the operator-attended read-only reruns produce truthful first diagnoses without changing the app.
V3 then passes; the identity defect is closed before Sitting D writes begin.

Not part of this change:

- no new acquisition architecture, campaign verb or public schema;
- no executable mapping for new strip states;
- no cursor-value OCR or app-side cursor readout;
- no distinction between the two reused destructive guards from the tree;
- no TGC writer and no assisted-mode test;
- no sampling-volume warning provoked for coverage;
- no V5/V6 write, Store, Record or `.BDD` output;
- no absolute geometry or control handle as production identity;
- no speculative popup dismissal or cleanup gesture.

Evidence under `outputs/live/` remains git-ignored: records must name the command, time and local artifact,
quote the relevant fields, and commit only crops that a reviewer cannot reconstruct from the text.
