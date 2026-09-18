# DOP3010 acquisition refactor — device verification

**What this document is.** The operational procedure that turns the refactor's
*device-pending* items into verified ones. It is the authoritative copy of that procedure:
no other document in the set carries a verification checklist, and a checklist copied into
a second file is a checklist that drifts.

**When it is run.** Only after the cloud refactor is green
(`uv run --extra dev pytest -q`, `uv run --extra dev ruff check src tests`) and only in an
interactive session that owns the application's desktop — see
[`live-bringup.md`](live-bringup.md) §1 for the session/scheduled-task prerequisite and
`tools/live/README.md` for the dispatcher. **One item may be run unattended: V0 is a read-only
inventory that sends no message and moves no cursor.** V1-V8 involve gestures, a hand-reached
state, or a decision only the operator can make; §Session record is the account of what a
first, unattended V0 found.

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
2. Invoke the read-only fixed-fact/dialog command.
3. Confirm: the popup opens; the **top** entry (by screen `top`, not by highlight) is the
   one selected; no lower entry is pressed; the dialog's channel matches the routed channel;
   the dialog closes by the safe/cancel path; and no parameter changed.
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
  established — **see §Session record below**: `UDOP DOP3010.43`, instrument variant, V0 only.
  Every other item still covers **no** specific version.

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
does not exercise a gesture at all, which is precisely why V0 could be run unattended and V2
cannot.

## What this session may **not** claim

- That a green cloud suite implies working live behaviour. Tests assert self-consistency
  with primitives and with the fake's event vocabulary, never the installation's numbers.
- That a hover, a held press or a Store-dialog commit still works because the code moved
  verbatim — the *verbatim* part is exactly what V2/V4/V6 exist to check.
- That the four-button strip state is understood because a crop shows its captions.
- That a painted value (store directory, block cap) is a read path.
