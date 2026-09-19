# DOP3010 acquisition refactor — device verification

**What this document is.** The operational procedure that turns the refactor's
*device-pending* items into verified ones. It is the authoritative copy of that procedure:
no other document in the set carries a verification checklist, and a checklist copied into
a second file is a checklist that drifts.

**When it is run.** Only after the cloud refactor is green
(`uv run --extra dev pytest -q`, `uv run --extra dev ruff check src tests`) and only in an
interactive session that owns the application's desktop — see
[`live-bringup.md`](live-bringup.md) §1 for the session/scheduled-task prerequisite and
`tools/live/README.md` for the dispatcher. **V0 may be run unattended: it is a read-only
inventory that sends no message and moves no cursor.** V2's read half is the one *gesture* that is
also read-only — `tools/live/probes/w1_fixed_facts.py`, which hovers with the operator's real
cursor, presses the popup's topmost entry and the dialog's left button, and nothing else — and it
still wants the operator able to clear a stranded popup or restart the application, because
nothing this driver sends dismisses a popup once one is up (ledger B20). V2's write half, V1 and
V3-V8 involve a hand-reached state or a decision only the operator can make; §Session record is the
account of what the sessions so far found.

**Evidence that cannot be committed.** The readings a live session leaves live under `outputs/`,
which is git-ignored, so their authority is the §Session record that quotes them: name the file,
and quote what it printed.

**What it is for.** Verifying **behavioural equivalence and newly conservative refusals** —
not continuing reconnaissance. Pass criteria are written so that "refused, and said why" is
a pass wherever guesswork previously occurred. The items map to the blind-spot ledger in
[`acquisition-ui-model.md`](acquisition-ui-model.md) §6.

**Evidence levels** are as defined in
[`acquisition-architecture.md`](acquisition-architecture.md) §1. A result becomes
*cloud-verified-equivalent* only when the session's own output (status JSON, tree capture,
log line, stored file, screenshot) is attached to it; an oral "it worked" leaves the item
device-pending.

---

## 0. Before starting

- **Record the revision under test** at the top of the session log: branch, commit sha, and
  the package version. A verification session whose revision is not recorded verifies
  nothing.
- **Preserve the working frame before any action.** Record by hand, and then read back from
  the application: process caption / executable variant; routed channel; sidebar presence;
  PRF, gates, resolution, emissions, burst, first gate, sound speed; TGC mode and value if
  relevant; the configured store directory; and any block currently retained.
- **Confirm no measurement is underway** and the strip is in a startable view.
- **Declare the expected process variant** for every recording path (`--expect-mode`), so a
  run launched in the wrong build refuses instead of substituting silently (ledger B14).
- **Do not test assisted mode as an operating mode.** It is out of scope for this
  experiment; an assisted channel is a *refusal* case, not a test case.
- **Do not provoke unknown warning paths for coverage.** A warning is a side effect
  (`Continue` rewrites TGC mode and amplification — ledger B11), not a target.
- **Capture evidence as you go**: status JSON, the log, the stored files, and — where the
  question is about paint — a screenshot of that same moment. A tree read and a screenshot
  taken at different instants may not be compared as if they were one observation.

## V0 — diagnostic-only startup (no state change)

1. Run the read-only inventory (`acquire status` or its equivalent).
2. Confirm in the output: the real-process variant is recognised; the measurement surface
   is recognised; the fast-access parameter panel is present and its roles are complete; no
   overlay/replacement surface is active; the strip state is recognised; and the
   visible-control count is **recorded but does not gate**.
3. Save the JSON.

**Pass:** nothing on the instrument changed, and every statement in the output matches the
visible screen.

## V1 — sidebar prerequisite (ledger B01)

If it is safe and the operator approves, temporarily untick
`Show fast access parameters panel (not available in assisted mode)` in the `Preferences`
dialog (UI-OVERLAY-06) **without changing assisted mode**.

1. Run status/compile only.
2. Confirm the run **refuses manual acquisition** and does **not** claim `assisted`.
3. Restore the preference.
4. Re-read status.

**Pass:** the absence is diagnosed as a missing/ambiguous manual panel, and recovery is
clean.

If this is not safe or convenient, **skip it and leave it pending** — do not substitute
another UI state for it, because the whole point is that absence has more than one cause.

## V2 — the `Parameters` menubar anchor (ledger B03)

Goal: prove the refactored binding still opens only `Parameters` → `Operating parameters`
(entry and dialog quoted from UI-MENU-05 and UI-OVERLAY-05).

1. Put the application in the foreground (the hover cannot be satisfied from a background
   process — see [`live-bringup.md`](live-bringup.md) §4).
2. Invoke the read-only fixed-fact/dialog command:
   `PROBE_TIMEOUT_S=240 ./tools/live/dispatch.sh w1_fixed_facts.py`. **Not** `acquire compile` and
   **not** `select_channel`: those route first, so they *write* the channel before the dialog is
   read, which this item forbids on an instrument standing on another channel. The probe reports
   the dialog's **own** channel (`read_dialog_parameters` never routes); comparing it with the
   channel the run is configured for is the caller's step, because the read route does not
   perform it.
3. Confirm: the popup opens; the **top** entry (by screen `top`, not by highlight) is the one
   selected; no lower entry is pressed; the dialog's channel equals the run's channel; the dialog
   closes by the safe/cancel path — its **left** button on the read route, its accept end being
   the routing route's and not this one's; and no parameter changed.
4. Repeat in the simulation build only if it is available and useful.

**Pass:** the same successful gesture as the pre-refactor code, with no configuration
change. **Fail-closed pass:** if the anchor cannot be proven, the run refuses *before* the
hover and says which precondition was missing — record that as a pass with an open item, not
as a silent workaround.

## V3 — overlay and replacement refusal (ledger B06, B08)

Use an already-understood, easily closable surface (`Define TGC`, UI-OVERLAY-01..04)
**without modifying it**.

1. Open it by hand.
2. Run status/compile.
3. Confirm the refusal names an active overlay / non-measurement surface **before** blaming
   the strip or the sidebar, and that no press is attempted against overlay state.
4. Cancel the overlay by hand and re-run a clean status.

**Pass:** diagnosis is truthful and the refusal precedes any target resolution.

## V4 — **CRITICAL**: the four-button strip state (ledger B10)

This must be settled before the automation is allowed to act from a four-button no-slider
state. The contradiction to resolve is between the two committed crops — UI-STRIP-01
(`Pause` / `Record` / `Clear and restart`) and UI-STRIP-02 (`New acquisition` / `Do store` /
`Clear and restart` / `Remove current block`).

1. Reach the known "block held / grown strip" state by the **normal operator workflow**.
2. **Do not let the automation press any strip button.**
3. Capture, in one moment: the strip panel rect; every visible top-row button's handle,
   class and rect; slider existence/visibility; all strip descendants; a screenshot of the
   same moment; and the current block/status indicators.
4. Compare the tree against UI-STRIP-02's captions, and answer the one question a crop
   cannot: **is the button at index 1 one control that relabels, or two different buttons?**
5. Establish which state this is (`STORE` / `READY`-with-block / other) by observing safe
   transitions under operator control.
6. Only after the role map is proven may the code gain an executable mapping.

**Pass before mapping:** automation refuses this state as ambiguous.
**Pass after mapping:** the role map is backed by a tree read **plus** the pixels **plus** a
safe observed transition.

## V5 — fixed-fact compile, and a declaration-only mismatch

1. Restore the intended frame.
2. Compile the matching definition; verify the routed channel equals the dialog channel
   (ledger B17) and that the supported fixed facts read back agree with the declaration.
3. Confirm the block cap remains **explicitly unproven** unless a separate safe reader has
   been validated — a painted `Record settings` value (UI-OVERLAY-07) is evidence, not a
   read path (ledger B13).
4. Then make one **declaration-only** mismatch (for example a burst declaration that differs)
   without touching the instrument.

**Pass:** the mismatch refuses before `Record`, and no `.BDD` is written.

## V6 — the unchanged six-point campaign

Use the established multi-point test campaign with the intended real-process frame.

1. Run the complete campaign.
2. Confirm exactly the expected files are created.
3. For every point, confirm: the correct channel; the requested gates/resolution; the fixed
   covariates; the retained profile count/span; and the verification verdict.
4. Confirm no unexplained overlay/popup remains afterwards.

**Pass:** every point verified, **or** a failure is explicit and the run does not silently
continue from an unverified state.

## V7 — resume identity

1. Re-run with resume.
2. Confirm instrument/session compatibility is proven **before** any point is removed from
   the todo set.
3. Confirm no point records again.
4. Confirm that a TGC/visible-count change alone (ledger B02) does **not** invalidate a
   resume whose scientific state and declared identity are otherwise compatible.

**Pass:** the resumed run skips exactly the points already proven, and says why it accepted
the instrument as the same one.

## V8 — post-run recovery

After all tests: verify the intended frame is still active; no popup, dialog or overlay
remains; the cursor is not clipped (probe behaviourally, and only after any hover menu is
gone — ledger B19/B20); the store directory is the one expected; and the device outputs and
logs used to validate the refactor are preserved with the session record.

## Mapping: item → risk → evidence already committed

| item | blind spots | committed evidence to compare against |
|---|---|---|
| V0 | B02, B05, B14 | UI-WINDOW-01 (title bar, ten menubar entries, ten painted column rows), UI-BAR-01 |
| V1 | B01 | UI-OVERLAY-06 (`Show fast access parameters panel (not available in assisted mode)`) |
| V2 | B03, B04 | UI-MENU-05 (the five painted popup entries), UI-OVERLAY-05 |
| V3 | B06, B08 | UI-OVERLAY-01..04, UI-OVERLAY-19, UI-OVERLAY-22 |
| V4 | B10 (critical), B15 | UI-STRIP-01, UI-STRIP-02 |
| V5 | B13, B16, B17, B18 | UI-OVERLAY-05, UI-OVERLAY-07 |
| V6 | B02, B09, B16 | UI-SIDEBAR-01, UI-OVERLAY-05 |
| V7 | B02, B05 | — (the live job logs of the run under test) |
| V8 | B19, B20, B07 | — |

## Stop condition

**Do not add new automation during this verification session.** If a test exposes a concrete
failure, capture the evidence, name the failing invariant, and fix it in a **separate
commit** — do not fold a device-driven fix into a structural move, because which assumption
the device invalidated is the thing worth knowing afterwards. If the session cannot continue
because the application's state is unverified (a stranded popup, a wedged menu loop, a
clipped pointer), stop, require the operator to restart the application, and record the
state that was left behind — never attempt a speculative recovery gesture.

## After the session

- Each discrepancy becomes **its own commit** on the refactor branch (Patch 5).
- The items that passed are promoted in the ledger of
  [`acquisition-ui-model.md`](acquisition-ui-model.md) §6 from *device-pending* to verified,
  **with the session's evidence named**; failed hypotheses stay in that ledger as history
  rather than quietly leaving the text (Patch 6).
- Record the exact verified application/version/device scope on this page when it is
  established — **see §Session record below**: `UDOP DOP3010.43`, instrument variant, **V0 and
  V2**. Every other item still covers **no** specific version.

## Session record

### 2026-09-18 — the first V0 after the refactor, and the finding it caught

Application: **`UDOP DOP3010.43`**, instrument (non-simulation) variant — the window caption is
the discriminator (ledger B14) — 1920x1080, maximized. Revision under test: branch
`refactor/acquire-foundation`; the three readings below are the merge base `bfbbb10` (before
the refactor), the tip `b68b80d` (patches 0-4 with the module-graph correction) and `e1a8e47`
(the fix this session forced). One command, read-only, unchanged across all three:

```bash
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh -m udv_echo_process.cli acquire status
```

| reading | revision | `layout_shape_reasons` | what else the output read |
|---|---|---|---|
| before the refactor | `bfbbb10` | `[]` | 44 visible controls in 4 panels; strip `ready`, 3 buttons, no slider; no overlay; `layout_note: None` |
| after patches 0-4 | `b68b80d` | **the anchor clause** | the anchor refused as *"not at its measured location: the bar's buttons were bound [] to the left of it"*, on the same screen the pre-refactor code read cleanly |
| after the fix | `e1a8e47` | `[]` | the same 44/4 reading, plus the surface evidence clause `the active surface reads 'measurement' with the fast-access panel 'present_complete'` |

**What the refusal was.** Not a typo — a *class* of bug, and the reason this session exists.
The anchor's name clause read `observation.menu.named`, the binding the resolver publishes,
while `Win32Actuator._resolve` publishes `roles["menu"] = {}` and fills it **as the result of**
proving the anchor. The clause therefore read its own output and could never pass on a live
tree, where no widget carries text and nothing names the anchor's predecessors. It passed in
the suite only because every synthetic screen hands the resolver a fully *named* bar — a screen
this application never paints. **The tests were not wrong; they were describing a tree the
device does not produce**, which is exactly the class of assumption a cloud-only refactor
cannot settle on its own.

**The fix** (`e1a8e47`, its own commit per the stop condition): the anchor is proven by
**position** — the third button of a bar whose painted length is one of the two measured ones —
and a binding a tree *does* publish is held to agreement with that bar (its names in the
vocabulary's own left→right order, and `Parameters` bound to the bar's third entry), which is
the check that believes the bar and not the map. The predecessors' names are no longer demanded,
because no tree states them: what settles the identity on a device is the chain **after** the
hover. Three tests pin it, all driven off the instrument's own measured bar (quoted in
`tests/test_acquire_ui_counterexamples.py` from
`tests/data/udop-measurement-screen-tree-instrument.json`), and the first was run against the
un-fixed module to confirm it fails there — it did, with the live symptom.

**Settled by this session.** **V0 passes** on the instrument's own clean screen, with nothing
changed on the device (the status command is read-only), and the **precondition half of V2**:
the anchor is provable on the real bar, so the gesture is reachable rather than refused before
it starts.

**Not attempted, and why.** The gesture half of V2 (real-cursor hover → popup → topmost entry →
dialog → safe close) and all of V1, V3-V8. A popup this application opens cannot be closed
programmatically (ledger B20), so a gesture that went wrong would strand the application with
nobody at the console, and V4's four-button state has to be reached by hand. `acquire status`
does not exercise a gesture at all, which is precisely why V0 could be run unattended and the
gesture half of V2 cannot. (The next subsection is what happened when the gesture was attempted
against this refactor.)

### 2026-09-19 — the V2 gesture, and the defects standing between it and a completed run

Application: **`UDOP DOP3010.43`**, instrument (non-simulation) variant, 1920x1080, maximized —
the installation the V0 reading above came from. Revision under test: branch
`refactor/acquire-foundation`, tip **`7de790c`** (the five commits `45e2ae4`, `b5a2bd3`,
`f194d77`, `b9ecb29`, `7de790c` past the refactor the V0 session read). The gesture runs through
the read-only probe, because no in-repo command is both read-only and gesture-performing:
`acquire status` presses nothing, while `acquire compile` and `select_channel` route first and
therefore **write** the channel. Three commands, in this order, all pinned at `7de790c` — a status
reading to bracket each side of the gesture:

```bash
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh -m udv_echo_process.cli acquire status
PROBE_TIMEOUT_S=240 ./tools/live/dispatch.sh w1_fixed_facts.py
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh -m udv_echo_process.cli acquire status
```

**Evidence.** `outputs/live/task-w1_fixed_facts.py.log` — the probe's JSON, run
`19/09/2026 01:04:33`, `=== exit=0 ===` — and `outputs/live/task-udv_echo_process.cli.log` — the
**post**-run status, `01:06:07`, `exit=0` — the second of the two status readings, the first being
the session's opening one (`01:04:24`, same fields). The dispatcher writes every run to
`outputs/live/task-<slug>.log` after `rm -f`ing that path, and both status runs carry the same
slug, so the post-run file **replaced** the pre-run one on disk: the pre-run text is quoted here
from the reading taken while it stood, and the pre-gesture screen reading that still survives on
disk is the probe's own `snapshot.fingerprint` (`01:04:33`), which states the same sixteen screen
fields. `outputs/` is git-ignored, so the readings are quoted here rather than committed; all
three commands can be re-run and compared against this page.

| what the run reported | the reading |
|---|---|
| popup at start / the bar | `popup_open_at_start: false`; the menubar resolves to exactly `["Parameters"]` |
| the screen's own mode | `manual`, `source: read`, off the probe's **pre-gesture snapshot** (`screen_mode(roles)`, `driver.py:1378`) — the status dump has no channel-mode field; the post-run screen reads the same shape that snapshot did (44 visible controls in 4 panels, the fast-access panel `present_complete`) |
| the surface the gesture opened | the `Operating parameters` dialog: `TSp_Panel` at `(655, 364, 1282, 748)`, 627x384, 21 direct children — 15 `TSp_Value_Button`, 5 `TSp_Button`, 1 `TComboBox`, classes `{TComboBox, TSp_Button, TSp_Value_Button}` — i.e. the measured dialog the committed fixture `tests/data/udop-parameters-dialog-tree.json` carries |
| the dialog's channel | `'1'` (`dialog_reading.channel`), the channel this run is configured for (`UDV_CHANNEL` unset → `DEFAULT_CHANNEL = 1`); this run wrote no channel |
| the three dialog-only facts | `burst_length 4`, `first_gate_mm 1`, `sound_speed_ms 1480`, all `source: read`, through `read_dialog_parameters` — the reader the campaign's own compile step hands to the snapshot (`campaign.py:1320`) — and in the same run's snapshot taken *without* the reading handed over, all three `unreadable` with the reason |
| the close | three closes, each by the dialog's own left (`Cancel`) button: the step-4 dump, the step-5 diagnostic open, and `read_dialog_parameters` itself. The key the dump records, `dialog_closed: true`, is **not** a screen check and cannot be one: the probe sets it whenever its own `_close_parameters_dialog` returns (`w1_fixed_facts.py:294-299`), and that helper *notes* a bottom row it cannot resolve instead of raising (`parameters.py:368-376`), so the key is `true` even for a close that pressed a dead handle. The close that **is** asked of the screen is the read route's: `read_dialog_parameters` closes through `_close_any_dialog` (`parameters.py:544-554`, `626-664`), which re-resolves the panel, presses its safe end and then asks the screen again, reporting — by a note naming the surviving dialog's rect, not by a key — a dialog it could not take down; and what the screen itself said after the run is the post-run status's `0 dialog panel(s)` |
| error keys | none: no `popup_error`, `resolve_error`, `dialog_error`, `dialog_close_error` or `read_path_error` — and no popup reported stranded |
| the framed facts | `prf_us 600` and `emissions_per_profile 20`, read off the parameter column before the dialog work and the same after it; `max_profiles_per_block` still `unreadable` — a Preference, not a parameter, so V5's cap stays **unproven** |
| post-run `acquire status` | **identical field for field** to the pre-run one (the two texts differ only in their `running` header line, `01:04:24` vs `01:06:07`) and to the probe's pre-gesture `snapshot.fingerprint`: 44 visible controls in 4 panels, strip `ready` / 3 buttons / no slider, `overlay: None`, `layout_note: None`, `layout_shape_reasons: []`, `process_mode: instrument`, `layout_evidence` naming the fast-access panel `present_complete`, no menu popup, 0 dialog panels |

**V2 passes, both the precondition and the read-only gesture halves, on the instrument.** The
popup opens off the real-cursor hover on the anchor the V0 session proved positionally; the entry
taken is the topmost one, proved by its outcome and not by its highlight — the surface that
appeared is the `Operating parameters` dialog, where a lower entry (`Default parameters`)
selects the assisted mode, while the post-run screen reads the same manual shape the pre-gesture
snapshot recorded (`mode: manual`, `source: read`; 44 visible controls in 4 panels, the fast-access
panel complete — the status dump states no channel-mode field of its own); the dialog's own channel
agrees with the run's; the close is the dialog's safe end, and the close whose screen the read
route asks is answered by the post-run status's `0 dialog panel(s)`; and
the run's only presses are the topmost entry and the dialog's left button — no lower entry, and
nothing on the dialog's own field row — so nothing on the instrument changed: the pre- and
post-run status readings are identical field for field. The gesture is also not a one-off: the
probe's read half opens and closes the dialog three times in that one run (the dialog dump, the
reader's own diagnostic, and the accepted reading), and all three came out the same.
**B03/B04 (the anchor and the entry order) are what this settles** — the
ledger rows those blind spots live in are promoted per §After the session, with this record named
as their evidence. **B20's popup behaviour is not promoted by it**: the session attempted no
dismissal and no `WM_CLOSE`, no key reports one, and that ledger row stands as it was — the
blind spot is the reason the operator has to stand by a gesture that hovers at all. V1, V3-V8 stay device-pending, V4's four-button role map and V5's block cap
included; the popup's own entry inventory (`--popup`, five caption-less entries, measured
2026-09-18) was not re-run, because that reconnaissance leaves the application in a state only the
operator can clear, and the *write* half of the gesture — `ensure_channel`, which presses the
dialog's **accept** end and writes the channel — is a different path from the read this session
ran (its home is V5/V6).

**What the attempt before this one exposed.** The session opened from a live test on this
instrument that had not completed, and the V2 path was traced end to end against `eafc0e2` before
anything was touched. The trace found the ways the path could fail *or lie*; each fix is its own
commit (the stop condition's rule), and each had passed the cloud suite unchanged:

- **`45e2ae4` — the dialog could be classified as the strip, and the surface as a popup.** The
  resolver decided which panels are dialogs by a rule of its own (a direct `TEdit`/`TSp_Edit`
  **and** a `TSp_Browse`), while every other reader of that question uses
  `ui.dialog._is_dialog_panel` — wider than 400 px and full of controls. The measured dialog
  satisfies the canonical predicate and not the narrower one, so `value_dialogs`/`browse_dialogs`
  came back empty on the one screen that has a dialog on it; the dialog stayed in the strip vote,
  outvoted the recording strip's three buttons (its five-button row centre sits at 0.68 of the
  plot's height, inside the 0.30-0.70 band) and was bound as `strip_panel`; the screen's own strip
  was then read as an open menu popup and `classify_surface` answered **POPUP** where `DIALOG` was
  the truth. That is B06's own rule — classify the surface *before* diagnosing it — inverted on
  the surface it was written for.
- **`b5a2bd3` — the dialog's close could not report its own failure.** `read_dialog_parameters`
  closed on the panel handle it had opened, and the close swallows its error into a note: if the
  application replaces the dialog while the table is being read (measured on a channel write), the
  close presses a dead handle, nothing is raised, and V2's "closes by the safe end" can be unmet
  while the command exits 0 with a modal dialog still on the operator's screen. The close now
  re-resolves through `_close_any_dialog` as the routing path already did, and ends by asking the
  screen whether a dialog is still up — naming it by its rect and the remedy if it is.
- **`f194d77` — a failure after the hover said nothing about the popup it left up.** Nothing this
  driver sends dismisses a hover-opened popup — not `ESC`, not the cursor restore, not a click
  outside, not a posted `WM_CANCELMODE` — and `WM_CLOSE` to a popup **wedges** the modal menu loop
  until the application is restarted (B20). A gesture that failed after the hover therefore left
  an application this driver can neither clear nor verify, and said so nowhere. The failure now
  names the popup, where the attempt last saw it, that the application's state is **unverified**,
  and who has to act.
- **`b9ecb29` — the observation could contradict the view it belongs to.**
  `ScreenObservation` re-scanned all descendants for a slider after the resolver had classified
  the strip from its direct children, so a nested slider could make the observation answer
  `has_slider: True` for a strip the view and its press binding read as `ready`/no-slider. The
  carried reading is projected first now, and geometry is scanned only when no reading exists.
- **`7de790c` — the layout gate could raise instead of refusing.** Its incomplete-column clause
  indexed the raw row's `rect` although a captured row may state equivalent `left/top/w/h`, so a
  gate documented as *total over an already-resolved role map* raised `KeyError` on a rect-less
  capture instead of returning its normal refusal.

Which of them the earlier attempt hit is not recorded here; what is recorded is that each was a
live-plausible path in the code that attempt ran, and that the run at `7de790c` — after all five —
completed with the readings above. Four of the five correct behaviour that predates the move: the
review that found them checked each path against `bfbbb10` and found the panel/dialog/strip block,
`read_dialog_parameters` and both close paths, and the hover's `try`/`finally` and press-entry body
byte-identical there, and the clause `7de790c` renders is in `bfbbb10`'s flat module unchanged
(`bfbbb10:src/udv_echo_process/acquire/driver.py:970`). The fifth, `b9ecb29`, is a divergence the
refactor's own new projection introduced — `ScreenObservation` has no counterpart at `bfbbb10` at
all. The device, not the move, is what would have found the four — which is the point of running
this page's items at all.

### 2026-09-19 — post-review recheck stopped at the foreground precondition

After the independent review fixes (`00fd6a0`) and their evidence correction (`3a3cc29`), the same
three-command bracket was attempted again. Both status reads were clean and equal on the screen
fields — 44 visible controls in 4 panels, ready three-button strip, no overlay, no popup, no dialog,
and no layout refusal — but `w1_fixed_facts.py` stopped **before the hover** because `TMain_Scr` was
not the foreground window and Windows did not grant foreground activation within 1.0 s. The reported
foreground window was `Windows.UI.Core.CoreWindow`; the remedy is to bring UDOP to the front and stop
anything that steals focus, then rerun.

That refusal moved no cursor, opened no popup or dialog and pressed nothing, and the post-run status
confirmed that nothing was stranded. It proves the foreground guard on the final head, not the V2
clean path: the successful V2 device claim remained pinned to `7de790c` until the bracket was rerun with
the application already in front — which it was, on 2026-09-19, on the merge head (see the next
subsection).

### 2026-09-19 — the V2 bracket on the merge head, and the `89` rule read off the pixels

Application: **`UDOP DOP3010.43`**, instrument (non-simulation) variant, 1920x1080, maximized,
main hwnd **3935144** — the installation the two readings above came from. Revision under test:
**`master` at `5a36b40`**, the merge head of `#9` → `#8` → `#10` → `#11`. `src/` at that revision is
byte-identical to `b007278` (the merges carried no source changes; `git diff b007278 5a36b40` is three
documentation files), so the recipe under test is the refactor's final head.

**The bracket, in order, and the one field that differs across it.** The three commands of the V2
procedure, with `PROBE_TIMEOUT_S=240` on the probe:

```bash
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh -m udv_echo_process.cli acquire status   # 11:22:24, exit=0
PROBE_TIMEOUT_S=240 ./tools/live/dispatch.sh w1_fixed_facts.py                        # 11:22:33 → 11:22:47, exit=0
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh -m udv_echo_process.cli acquire status   # 11:22:51, exit=0
```

The dispatcher `rm -f`s `outputs/live/task-<slug>.log` before each run, so the two status readings share
one path and the second one overwrites the first; the pre-run text is therefore **copied aside
immediately** (`outputs/live/sittingA-pre-status.log`, and the gesture's JSON as
`sittingA-gesture.json.log`, the shot's as `sittingA-dialog-shot.log`). The pre- and post-run readings
are **identical field for field except `cursor`** — `[1874, 0]` → `[453, 0]`, the position the gesture
left the pointer at. That is the honest shape of this bracket, and it is one field stricter than the
`7de790c` run: that one's two readings differed only in the `running` header line, because its cursor
happened to be put back where it started. Nothing else in either text moves: 44 visible controls in 4
panels, strip `ready` / 3 buttons / no slider, `overlay: None`, `layout_note: None`,
`layout_shape_reasons: []`, `process_mode: instrument`, `layout_evidence` naming the fast-access panel
`present_complete`, no menu popup, 0 dialog panel(s).

**`is_foreground: true`** in the pre-run reading — the precondition the earlier final-head attempt
lacked, and the reason that attempt refused before the hover. This time the guard was satisfied and the
gesture ran.

| what the run reported | the reading |
|---|---|
| popup at start / the bar | `popup_open_at_start: false`; the menubar resolves to exactly `["Parameters"]` |
| the screen's own mode | `manual`, `source: read` (`snapshot.mode`); `process_mode` `instrument`, `source: read`; 44 visible controls in 4 panels, fast-access panel `present_complete` |
| the surface the gesture opened | the `Operating parameters` dialog: `TSp_Panel` at `(655, 364, 1282, 748)`, 627x384, **21 direct children** (`read_path_children: 21`), classes `{TComboBox, TSp_Button, TSp_Value_Button}` — the measured dialog the committed fixture `tests/data/udop-parameters-dialog-tree.json` carries. Resolved live and agreeing with the driver's own report (`rect_from_driver`, `dialog_shot` run, same rect) |
| the dialog's channel | `'1'` (`dialog_reading.channel`) = the run's configured channel (`UDV_CHANNEL` unset → `DEFAULT_CHANNEL = 1`); this run wrote no channel |
| the three dialog-only facts | `burst_length 4`, `first_gate_mm 1`, `sound_speed_ms 1480`, all `source: read`, `reason: ""`, `dialog_reading_readable: true`. The same snapshot **without** the reading handed over reports all three `unreadable` with the reason — the routing that makes the read meaningful, measured both ways in one run |
| the framed facts | the parameter column resolved **7 of 7** roles: `4000` US Frequency, `600` PRF, `50` gates, `1.850` resolution, `1.00` velocity scale factor, `20` emissions/profile, `0` Doppler angle |
| the close | `dialog_closed: true` **and** the screen's own answer to it: the post-run status reads `0 dialog panel(s)` and no menu popup. The key alone is not a screen check (see the caveat under *What these records may not claim*), which is why the bracket's second status read is the evidence and not the key |
| error keys | **none**: no `popup_error`, `resolve_error`, `dialog_error`, `dialog_close_error` or `read_path_error`; no key names a stranded popup, and the only keys matching an error pattern in the whole report are the four reasons that *should* be there (`max_profiles_per_block`, and the three dialog-only fields in the snapshot that was not handed a reading) |
| the cap | `max_profiles_per_block` is still `unreadable` — *the block cap is an application Preference* — so **V5 stays unproven**; this run does not touch it |

**V2 passes on the merge head**: the popup opens off the real-cursor hover on the anchor the V0 session
proved positionally, the topmost entry is the one taken (proved by its outcome — a lower entry is
`Default parameters`, the assisted mode — and refuted by the screen, which still reads `manual` with the
fast-access panel complete), the dialog's own channel agrees with the run's, the close is the dialog's
safe end, and the run's only presses are that entry and that left button. The device-pending item — *the
final-head foregrounded V2 rerun* — is closed by this record. V1, V3, V4, V5, V6, V7, V8 remain
device-pending; V4's four-button map and V5's cap stay the critical ones.

**The `89` rule, confirmed on the pixels (sitting A's second item).** The same run's dialog walk read
**four `TSp_Edit` controls carrying `89`** — at `[987,604,1057,620]` inside the `TSp_Value_Button` whose
combo reads `1.776`, at `[1187,526,1257,542]` under the `medium` combo, at `[786,492,856,508]` under the
`4` combo, and at `[786,530,856,546]` under the `Medium` combo. `dialog_shot.py`, run a minute later
(same rect, `frame_stable: true`, `non_blank: true`, 43 distinct greys), photographed that dialog; each
of the four areas magnified x6 reads **`1.776` / `4` / `medium` / `Medium`** and nothing anywhere reads
`89` — the crop is committed as `ui-crops/ui-89-rule-dialog-rows.png` (UI-OVERLAY-24) so the reviewer can
check it without this machine. The two sidebar combos behave the same way in the same screen read: their
`TSp_Edit`s read `89` at `[14,354,74,370]` and `[14,379,74,395]` while the combos above them paint
`medium` and `Medium` (the combo's inner `Edit` child reads the painted value). **So the rule holds live:
an edit's tree text is not evidence of a displayed parameter unless it is painted** — and the four
dialog edits the index could "neither confirm nor refute" are now confirmed as buffer values, not
painted ones.

**The monitor side, and what the tree does *not* carry (sitting A's third item, partly).** Of the 44
visible controls, **two** start right of x=690: the monitor's own `TDop_Plot` `[200,65,1910,1006]` and
the bottom bar's `Exit` `[1840,1025,1900,1045]`. The plot has no children, and no control anywhere on the
monitor side carries text. In this state (no cursor placed, so no info box up) there is therefore no
app-side readout to read — but that is not yet the full question, because the info box was not up: a
window this application spawns over the plot need not be a descendant of `TMain_Scr` at all, and the
main-window walk can only ever see descendants. The item is **sharpened rather than closed**: the next
read wants a **top-level window enumeration** (`EnumWindows`) with the box up, not another main-tree
dump. That is one operator action (show cursors, click a depth) and a small probe, and it belongs with
V4's sitting, which already asks the operator to reach a state by hand.

**Evidence.** `outputs/live/` is git-ignored, so the readings above are quoted here rather than
committed (this page's own rule), together with the run times and the exact three commands; the four
logs of this sitting are `sittingA-pre-status.log` (11:22:24), `sittingA-gesture.json.log` (11:22:33,
`=== exit=0 ===`), `sittingA-post-status.log` (11:22:51) and `sittingA-dialog-shot.log` (11:23:43), plus
`dialog-full.png` / `dialog.png` from the same moment as the shot. The only committed artefact is the
crop, because it is the one piece of evidence a reviewer cannot reconstruct by rerunning the commands.

### 2026-09-19 — the four-button strip, block-held: the role map, two false diagnoses, and the cursor info box

**Operator-driven, and the automation pressed nothing.** The operator reached the block-held state by hand
(`Record` -> `Pause` -> `New acquisition` -> `Pause`), left the monitor **paused**, and placed a cursor at
**45 mm**; later in the same session they cleared the block and reached the intermediate state below. All
three reads are the **same process**, main hwnd **3935144** — the process the V2 bracket above read two
minutes before the first of them — which is what makes the handle comparison below a measurement rather
than an inference. Read-only probes only, pressing nothing: `main_geometry.py` (11:22's state was read by
`w1_fixed_facts.py` for the V2 bracket; 11:41:54 and 11:55:34 are `main_geometry.py` plus its same-moment
frame) and the new `top_level_windows.py` (11:43:40).

### The role map: the row is drawn from a pool of five buttons

The panel is `TSp_Panel 3149132`, and it is the same control in every state — at the same top-left corner,
sized by the state:

| state (time) | panel rect | size | visible row (left to right) | slider |
|---|---|---|---|---|
| `ready` (11:22) | `[343,414,695,454]` | 352x40 | `Pause`, `Record`, `Clear and restart` | absent |
| intermediate (11:55) | `[343,414,796,454]` | 453x40 | `Pause`, `Record`, `Do store`, `Clear and restart` | present, **hidden** |
| block-held (11:41) | `[343,414,894,537]` | 551x123 | `Resume`, `Do store`, `Clear and restart`, `Remove current block` | present, visible |

Those captions are bound to handles **by position** (each caption's start falls inside its own rect, read
off the frame at x5-x6), and the handles say what the captions alone cannot:

| handle | its caption | `ready` (11:22) | intermediate (11:55) | block-held (11:41) |
|---|---|---|---|---|
| `1574908` | `Pause` -> `Resume` — **the one control that relabels** | visible, `[353,424,432,444]` | visible, same rect | visible, `[353,424,444,444]` |
| `4787852` | `Record` | visible, `[442,424,527,444]` | visible, same rect | **hidden**, same rect |
| `2821164` | `Do store` | hidden | visible, `[537,423,628,443]` | visible, `[454,423,545,443]` |
| `1641666` | `Clear and restart` | visible, `[537,423,675,443]` | visible, `[638,423,776,443]` | visible, `[555,423,693,443]` |
| `7867344` | `Remove current block` | hidden | **hidden** | visible, `[703,423,874,443]` |

**So the answer to the question a crop could never settle is a pool, not a slot.** Exactly one button
relabels (`1574908`: `Pause` <-> `Resume`); every other change to the row is **visibility and position**,
and the row's slots shift with it — `Do store` is the second visible button in the block-held state and the
third in the intermediate one, and the intermediate state shows `Record` **and** `Do store` side by side,
so the two are not competing for one slot at all. `ui-element-index.md`'s finding 20 ("the strip's grown
row relabels its first two buttons") is therefore **wrong in its second half, corrected here**: one control
relabels, and the rest of the row is a subset of a five-button pool.

### Reproduced exactly, and the transitions observed

After clearing the block, passing through the intermediate state and pressing `Pause`, the operator returned
to the block-held state and a fourth read was taken (11:59:23). Compared with the 11:41 read by the
repository's own comparator (`tools/live/compare_reads.py`), it is the **same state, not a similar one**:
same `TMain_Scr` hwnd `3935144`, same counts (50 visible controls, 5 panels, 273 tree rows), the same ten
strip-panel children at **identical handles and rects**, the same `Show block` = **`2`**, the same
`layout_note` naming `((343, 414, 894, 537), 'TSp_Panel')` as a dialog — and **tree delta `+0 / -0 / moved 0
of 273` common controls**. So neither the state nor either misdiagnosis (the resolver naming `131916`, the
classifier saying "a dialog is up") is a one-off of one moment: they are what this screen does whenever a
block is held.

**The transitions, observed by the operator** (nothing pressed by the automation; the three starred states
are the ones *read*, and the operator's two crops are the ones photographed): from the block-held state,
`Clear and restart` -> the three-button `Pause` / `Record` / `Clear and restart` row with `Show block` = `1`;
`Pause` -> the three-button `Resume` / `Do store` / `Clear and restart` row **with the slider up**
(UI-STRIP-04, cropped only); `Resume` -> the four-button `Pause` / `Record` / `Do store` / `Clear and
restart` row with nothing painted below it (`*` read at 11:55); `Pause` -> the block-held four-button row
with the slider (`*` read at 11:41 and again at 11:59). That is the "safe observed transition" V4 asks for as
its third witness — and it is the operator's; the tree, not the operator, is the witness for the handles.

### The slider, and where it is

`TSp_Sliding_Bar 3344390`, a **direct child of the strip panel**, painted as a two-handle range over the
history: `1513` at the left end and `8297` at the right with `6785` under the track in the block-held state,
the left portion filled green with a red segment at the right end. Its own width is a property of the state
too (`[465,449,897,499]` block-held, `[465,449,716,499]` intermediate), and in the intermediate state it is
present and **hidden**. A **second, hidden** `TSp_Sliding_Bar` (`5573538`) sits in a hidden panel
`[782,488,1024,541]`, so the class is not unique to the strip: a resolver keying on the class alone would
find the wrong one.

The combo `1967830` at `[429,506,474,527]` is the `Show block` selector (painted caption `Show block`,
which is the value that states *which* block: **`2`** block-held, **`1`** in the intermediate state, with a
hidden sibling `1249874` reading `1` in both). It is the one control here whose *value* is readable without
pixels; the slider's numbers are paint only.

### The two caption-less buttons below the row — identified

`2690436` `[350,467,401,482]` and `1967842` `[409,467,453,482]`, direct children of the strip panel; the band
they sit in paints `Profiles history in` `second` `✓` `profile` (read at x8), the green tick standing on the
second control's rect. So the pair §22.2 carried as "13 px below the panel, painting nothing" is the
**`second` / `profile` history-unit selector**, and the read `ui-element-index.md` asked for ("what settles
it is a tree read in the state that paints them, not a photograph") is this one. The tick also says which
unit the history is counted in here: **profiles**, not seconds.

### `visible: true` is not paint — measured three ways in one session

In the **intermediate** state the panel is only 40 px tall and **nothing is painted below the row**: the
same-moment frame shows the plot's white field and its grid rules where the block-held state paints
`Profiles history in`, the slider and `Show block`. Yet the tree reports the toggle pair and the `Show block`
combo **visible** in that state (their rects lie *outside* the panel's own rect, and the panel's height is
the reason nothing of them is painted). The same trap appears twice more in this session: `TSp_Button
131918` `[917,578,997,598]` is reported visible while the frame paints nothing there, and the four `89`
edits of the V2 record above carry text no pixel shows. So a control's `visible`, its `rect` and its `text`
are each a claim about the tree — **only the frame says what is painted.**

### Two refusals on the state — both safe, both misdiagnosed

1. **The strip resolver names the cursor info box as the strip.** In both the block-held and the
   intermediate read it returns `view: "unknown"`, `button_count: 0`, `panel_rect [908,466,1057,525]`,
   `row_meanings_error: "no known button row for view 'unknown' with 0 button(s); the view must be
   re-resolved, not guessed"`. That rect is the **cursor info box**, not the strip, and the same
   `has_slider: false` in the same report is not a fact about the strip (its slider is `3344390`).
   Refusing is the designed behaviour (`d04a88c`, a row it cannot map binds nothing) and nothing was
   pressed — but the *diagnosis* misdirects: a caller reading this report is told a different button panel
   sits in the plot's middle band.
2. **The layout classifier calls the strip's own panel a dialog.** `layout_note` opens *"a dialog is up: 1
   panel(s) of this screen are application dialogs and not the measurement layout"*, naming
   `((343, 414, 894, 537), 'TSp_Panel')` in the block-held state and `((343, 414, 796, 454), 'TSp_Panel')` in
   the intermediate one — the strip panel in both — with the active surface reading **`dialog`** and the
   count 50 visible controls in 5 panels (block-held) / 49 in 5 (intermediate) against the clean 44 in 4. So
   the canonical `>400 px` dialog predicate admits the strip itself — twice, at two different widths — and
   PR #10's one deliberately-open item (`_close_any_dialog` could treat an operator-opened panel in that
   class as a dialog) is therefore about **the strip**, in the state a running block leaves the screen in,
   not about an exotic panel. Nothing in this sitting pressed it; what the cleanup path would *do* with it
   is still the open question.

### The cursor info box: in the tree, but its numbers are paint only

This closes sitting A's third item. The box is `TSp_Panel 131916` `[908,466,1057,525]` with one child,
`TSp_Panel 131920` `[916,475,1045,514]`, both visible, both caption-less, and that child has no children of
its own. The same-moment frame paints `Depth = 45.0 mm` and `Velocity = 0.0 mm/s` inside a red rectangle
(read at x4) — one cursor at 45 mm against a paused monitor. **No control in the tree carries either
number**: the top-level enumeration lists 46 windows for this process, of which the only *visible* one that
is not the main window is the application's own `TApplication` message window at `(960,540,960,540)` with no
children, and no child control of any window carries a depth or a velocity string.

**This is a one-cursor measurement of a surface out of scope.** The operator states the box depends on the
monitor's state and would change, and likely multiply, with a second cursor added — and that the experiment
does not use this feature. It is recorded here for the **strip mis-resolution it causes** (refusal 1 above),
not as a readout: an app-side readout of the tracked cursor does not exist, so the analysis stays
post-processing, which is where §26.11 already put it, and those two numbers can come only from pixels.

### The fourth combination is cropped but not read

The operator's second new crop (`ui-crops/overlay-pause.png`, UI-STRIP-04) shows a state one step earlier —
reached by pressing `Pause` while the strip reads `Pause` / `Record` / `Clear and restart` — painting
**three** buttons (`Resume` / `Do store` / `Clear and restart`), the `Profiles history in second / profile`
row, a slider whose ends read `1` ... `392`, and `Show block` = `1`. Its handles are **unmeasured** (that
state was photographed, not read). Its row is consistent with the pool above — `1574908` / `2821164` /
`1641666` visible, `4787852` and `7867344` hidden — but that is a **prediction from the pool, not a
reading**, and it is recorded as a prediction.

### Evidence

`outputs/live/` is git-ignored, so the readings are quoted here with their times: the three reads are kept
beside each other as `keep/main-geometry-2026-09-19-blockheld.json` (11:41:54) and
`keep/main-geometry-2026-09-19-intermediate.json` (11:55:34), with `top-level-windows-blockheld.log`
(11:43:40) and the `ready` state's row from the V2 bracket's own gesture log (11:22:33) — all `exit=0`. The
same-moment frames are `main-geometry-full.png` (two of them, 11:41 and 11:55) and
`top-level-windows-full-a.png` (`stable: true`, `non_blank: true`). Committed artefacts: the operator's
**two new strip crops** (`overlay-record-stop-new-acquisition.png` = UI-STRIP-03,
`overlay-pause.png` = UI-STRIP-04) and the measured rects above.

## What these records may **not** claim

- That a green cloud suite implies working live behaviour. Tests assert self-consistency
  with primitives and with the fake's event vocabulary, never the installation's numbers.
- That a hover, a held press or a Store-dialog commit still works because the code moved
  verbatim — the *verbatim* part is what V4/V6 still exist to check; V2's hover and its
  topmost-entry press are now device-verified, and only those.
- That the read half of V2 passing means its write half works: the routing route
  (`ensure_channel`) presses the dialog's **accept** end and writes the channel before it reads,
  and this session never ran it.
- That the probe's `dialog_closed: true` is a screen check. It is set by a close helper that
  *notes* a bottom row it cannot resolve and returns instead of raising, so it cannot fail;
  the close that asks the screen is the read route's `_close_any_dialog`, which reports a dialog
  it could not take down by naming its rect, and the screen reading this session has is the
  post-run status's `0 dialog panel(s)`.
- That a reported stranded popup is a repaired one. What `f194d77` added is a truthful report
  with the remedy; nothing this driver sends dismisses a popup, so the operator still clears it
  or restarts the application.
- That the four-button strip state is understood because a crop shows its captions.
- That a painted value (store directory, block cap) is a read path.
