---
name: udop-acquisition
description: Drive and verify DOP3010/UDOP acquisition runs.
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [windows, gui, automation, win32, dop3010, udop, acquisition]
    category: software-development
    related_skills: [windows-gui-automation, udv-live-gui-probe]
---

# Driving the DOP3010/UDOP application

This is the repository's instrument-specific overlay, and it travels with a clone. It also still carries
its own copy of the shared Windows-GUI craft (the sections below), so a clone needs no profile skills to
be useful; where the profile-global `windows-gui-automation` skill states a general rule differently,
**the global one wins** and the copy here is the older text. That direction matters because a
project-local skill shadows a profile-global one of the same name: this overlay stays named
`udop-acquisition`, and no copy of the general skill may be committed here under its own name.

**The profile-global copies are not the authority for this instrument, and two of them are stale.**
`windows-gui-automation` carries instrument-named references (`dop3010-sweep-automation.md`,
`dop3010-measurement-screen-surface.md`) and `udv-live-gui-probe` carries live-probe notes; both predate
the sparse pass, so they still state the retired size signature, the planning-law period and `~8.4 s`
retention that this file corrects. Read them for the general craft and for the dispatch route, never for
a DOP3010 measurement. Which of their claims are superseded is settled by measuring the instrument, not
by preferring the newer file.

Put a lesson in exactly one home. A general Windows-GUI rule belongs in `windows-gui-automation`; a
DOP3010 fact belongs here or in `docs/dop3000/`; dispatch mechanics belong in `tools/live/README.md` and
the profile-global `udv-live-gui-probe`. When two sources disagree, measure the current process and
application state and then correct the loser — never leave both claims standing.

The project-specific work is the instrument's own screen, its parameter dialog, the record/store cycle,
the sweep/campaign commands in `src/udv_echo_process/acquire/`, the probes in `tools/live/`, the crops
and their tooling in `tools/ui/`, and the bring-up for a second machine. `docs/dev-handoff.md` is the
entry point for a machine that cannot reach the instrument at all.

**A live acceptance pass must land as portable, offline-checkable evidence, or the reviewer cannot
see it.** Everything in `outputs/live/` is git-ignored and carries absolute machine paths, so a run
that is described only in a PR body is unreviewable. Commit, beside the recordings: (a) **the actual
plan and job definitions used**, copied verbatim and free of local paths, so the design re-plans
offline; (b) a **derived, path-sanitized summary** of the runtime manifests that preserves exactly
what a reader has to judge — the structured transition objects, the compile identity, each point's
requested and decoded values — plus the SHA-256 of every recording; and (c) a small **verifier
script** that re-derives every claim from the committed files with no instrument access. State which
numbers are recomputable from the repository alone and which are not (the original runtime-file
hashes, what the dialog stated, unreadable UI fields): a derived summary presented as a raw capture
is the failure mode, and the two manifest kinds look alike.

**Tie the verifier to the plan, and do not describe it as re-deriving what it merely asserts.** A
verifier that only checks recording hashes leaves the summary floating; have it load the committed
plan and assert the plan fingerprint, the per-job definition fingerprints, and each point's label
and full requested parameter set against the summary, so BDDs, summary and plan are cryptographically
linked (prove it by perturbing each link and watching it fail). Then say exactly what it *re-derives*
versus what it *checks against hard-coded expectations* — a summary is not a raw capture, and a
reviewer who cannot execute the verifier reads the wording as the claim.

**Say what a live pass did not exercise.** A boundary-transition acceptance that changes the value
at every boundary never exercises the equal-value/no-write path, and a nine-job plan stopped after
four leaves five jobs unrun — both are real gaps in what the sitting proved. Name them in the
evidence next to the results; letting "N boundaries passed" stand for the whole state machine is the
over-claim that later costs a reviewer's trust.

**Where the DOP3010 facts live (frozen 2026-09-18).** The repository holds a small set of
authoritative documents for this instrument, and this skill **points at them instead of repeating
them**: architecture, layering and invariants —
`docs/dop3000/acquisition-architecture.md`; surfaces, widgets, bindings and the blind-spot ledger
B01..B20 — `docs/dop3000/acquisition-ui-model.md`; the refactor's device verification procedure —
`docs/dop3000/device-verification.md`; the write recipes, write order, strip state machine and store
chain — `docs/dop3000/udop-automation.md`; the state of the work —
`docs/dop3000/handoff-dop3010-acquisition.md`; painted captions and values, with the crop ids the
quotes carry — `docs/dop3000/ui-element-index.md`; the completed pass, the current structural-size
and measured-period laws, and the planner that now computes the whole period law —
`docs/dop3000/sparse-run-plan.md`. A rule learned while driving the instrument
belongs in one of those files (the mechanism, or the surface model) and is *linked* from this skill;
a second copy in a skill is how the two forks drifted apart before.

Reconnaissance, control-id mapping, message-based driving and artifact verification for
Windows desktop applications that expose no SDK, CLI or protocol.

## When to use

Signs: *"automate this old Windows program"*, *"click through this software for N parameter
sets"*, *"sweep parameters in our instrument software"*, *"hook up to the UI elements or use
AutoHotkey?"*, *"find out how we can automate it"*. Use it for the **reconnaissance** even when
the conclusion turns out to be "do not drive the GUI at all".

Adjacent: `computer-use` (bundled) drives the desktop by screenshot + element index and is the
right tool on macOS/Linux or when an app must be driven visually. This skill is for
**control-level Win32/UIA automation**, which keeps working when the window is occluded,
unfocused, or the session is locked.

## Order of attack

**0. Exhaust the cheaper interfaces first.** Before writing any GUI code, check for a vendor
SDK/DLL, a CLI, a documented serial/TCP command set, a config file the app re-reads on start,
and a documented output format. Search the install directory for shipped helper code and sample
data (`*.py`, `*.m`, `*.dll`, `*.chm`, `DEMO*`, `UTILITIES`) — a vendor-supplied reader for
the product's own file format removes an entire reverse-engineering track, and a vendor's own
constants beat anything inferred. Bypassing the GUI beats automating it, always.

**1. Reconnoitre before designing, and classify every control A/B/C/D.** Run
`scripts/win_ui_probe.py`. The classification decides the entire implementation; guessing it
costs a rewrite. Explore with an **incremental step runner** — one script taking
`--steps snap,click:<role>,wait:3,snap` and persisting its state to JSON — rather than one
do-everything script, so each action is inspected before the next one is chosen; a monolith
cannot answer a question you only discover halfway through.

| Class | Symptom in the probe output | How to drive it |
|---|---|---|
| **A** | real child window: class name + control id, text readable | messages: `WM_GETTEXT` / `WM_SETTEXT`; for any button a **posted down / ~180 ms hold / up** at the rectangle centre — never an instant down+up |
| **B** | reachable through UI Automation (control type, automation id) | UIA patterns / `pywinauto` `backend="uia"` |
| **C** | nothing identifying, but keyboard-reachable | focus + keys (prefers matching bitness) |
| **D** | owner-drawn: no child window at all | coordinates from the *parent* rectangle, plus vision for labels |

**2. Drive with messages; escalate to input injection only on returned evidence.**
`WM_SETTEXT` + a `VK_RETURN` key message applies values in many apps with no focus, no cursor
movement and no keystrokes — verified against a vendor whose widgets are fully custom-drawn.
For a **button**, the message recipe is a press that is *held*: post `WM_LBUTTONDOWN`, sleep
~180 ms, post `WM_LBUTTONUP`, both with **client-relative** `lParam`. Custom widget layers discard
an instant down/up, and a discarded click is indistinguishable from an unreachable control — one
record strip was written off as undrivable for an entire session on that alone, then driven
normally the moment the press was held. `scripts/win_click_probe.py` runs the whole recipe matrix
against any control and reports which one the app actually reacts to.
Escalate only when the app ignores **every** recipe: focus + keys, then real `SendInput` with the
window foregrounded. **Foregrounding is its own step**, and a driver launched from a console finds the
app unfocused as a matter of course — blaming the surface before establishing the state wastes live
slots. `SetForegroundWindow` returns 0 from a background process (the foreground lock refuses it);
attach to the current foreground thread, set foreground, detach, then confirm with
`GetForegroundWindow() == target` rather than trusting the return value:
`AttachThreadInput(GetWindowThreadProcessId(GetForegroundWindow(), None),
GetWindowThreadProcessId(target, None), True)` -> `SetForegroundWindow(target)` -> detach. **Treat the
foreground request as a precondition the operator satisfies, not as a driver failure:** Windows refuses
a foreground request from anything but the user (measured: `SetForegroundWindow(hwnd)` returned 0 three
times from an interactive session), a probe dispatched into a *separate* session cannot take it at all,
and a console window opened by the launcher is the usual thief — so put the guard **before** the first
hover, where a refusal has opened nothing and stranded nothing, and the remedy is for the operator to
click the window or Alt+Tab to it and re-run the **same** command (`docs/dop3000/live-bringup.md` §4,
plan §15.1). An inactive
window ignores hover and gives its first click to activation, which is indistinguishable from a surface
that does not answer input at all. Message-based control is also bitness-agnostic, which matters because
`pywinauto` warns loudly when a 64-bit interpreter drives a 32-bit target.

**2b. Write only where a wrong value is harmless, and put it back.** Probe writes in the app's
own simulation/demo/idle state when it has one — never mid-run on real hardware. Change one
field, read it back, check the coupled observable, then restore the original value and confirm
the restore. State in the report which field you touched and what it held before: a
reconnaissance session that silently leaves an instrument configured differently, or a run
triggered while a measurement was live, is worse than one that asks first.

**2c. Treat menus as setup-only surfaces and never clean one up with `WM_CLOSE`.** These popups
open on **mouse-over, not on a click**: move the real cursor onto the menubar button (`SetCursorPos`
alone) and the menu appears — provided the point is actually on the item, so derive it from the item's
**rectangle at run time**: one full-screen app sat at `(-8,-8)` and had shifted out from under every
literal hover point recorded earlier, and a hover that misses looks exactly like a surface that ignores
input. Hold the pointer on the item through the popup poll *and* the entry press, restoring it only
afterwards — moving off a hover-opened popup is itself a dismissal, and restoring early was enough to
defeat a working gesture. And check the **detector** before the gesture (evidence discipline, below) —
a click (posted *or* injected) sent after that moment *closes* the menu
it just opened, which is why every click-based attempt failed and why the one menu that did open did
so with the operator's cursor already over the button. Once open, its **entries take ordinary posted
clicks**, which performs the action *and* consumes the popup: that is the whole recipe for menu-driven
setup, with no cursor hijack. Nothing else dismisses a popup — moving the cursor away, clicking the
button again, clicking the plot, and `ESC` (posted or real) and a posted `WM_CANCELMODE` all leave it on
screen (measured: the posted `WM_CANCELMODE` leaves it up too), and opening a different menu merely
replaces it. **Escape closes nothing here, and a hover-opened popup cannot be dismissed
programmatically: the only clean exit is a *press*, which selects an entry and closes the popup.** So
menus are the one place that should not be in a per-point loop. **If a popup is open when a run
resumes, stop and raise the failure; do not try to close it.** **A gesture that opens a popup owns its
cleanup in a `finally`.** A probe that dies between the hover and the cursor restore — an exception
anywhere in the read it was doing — leaves that popup on the desktop with nothing able to close it
programmatically, and every run afterwards refuses with "a menu popup is already open"; the operator has
to clear it by hand. Restore in a `finally`, then **re-read the popup state on the failing exit** and
report that the application is unverified plus the operator/restart remedy; an attempted entry press and
a restored cursor are not proof that the popup was consumed, and this diagnostic must never replace the
original failure if its own read errors. When a probe has to leave the application as it found it, say
what it found and what it left in its own output: a state the operator has to fix by hand must never be
discovered by them. **The policy for one that has already stranded the application is the
operator's restart:** abort the run, mark the application's state unverified, and require the operator —
no automatic restart, no speculative menu press, no silent continuation — because nothing in Win32 closes
it (measured: `ESC`, moving the cursor off, moving past the last entry and a posted `WM_CANCELMODE` all
failed; plan §9.3). `WM_CLOSE` to a popup panel destroys the popup window while the app is
still inside its modal menu loop, and from then on *no* menu opens by any means — posted clicks,
real clicks, real `ESC`, a click outside, `Alt` — until the app is restarted; the rest of the app
keeps working, so a liveness check will not catch it. Dialog panels are different: they own a
Close button and a posted click on it works. Best to worst for applying a parameter set: a
prepared config file the app recalls in one action, message-based writes to the fields, menus
driven by design-time recall or by hover + entry-click in setup, never menu navigation per point.

**2d. Dropdowns take a selection plus a notification, never a typed string.** A combo answers combo
messages even across processes (the OS marshals `CB_GETLBTEXT` exactly like `WM_GETTEXT`, so your own
buffer address is fine): read `CB_GETCOUNT`, each item with `CB_GETLBTEXT`, and `CB_GETCURSEL`. To set
one, `CB_SETCURSEL(index)` and then send the parent a `WM_COMMAND` carrying `CBN_SELCHANGE` in the high
word and the control id in the low word — the selection alone updates the control, but the app's
parameter changes only when its change handler runs. A list-style combo has **no inner edit**, so
text-based tricks have no target; an edit-style one has both, and setting only the text leaves
`ItemIndex` stale. Verify the write like any other: read the index back *and* check a coupled
observable — but take the **text** as the authority: `CB_GETCURSEL` is a hint and it
goes stale — measured, a cell stated `4` while `CB_GETCURSEL` returned the index of `8` after a
programmatic selection, so an index-based read-back reports a value the application does not state. Read
the entry's text back *and* check a coupled observable (the app's own painted value, or a readout it
recomputes). **And treat an edit's tree text as a claim about the control, not about what the surface
displays:** measured, a dialog's tree read listed four value edits holding `89` while the crop of that same
dialog painted no such value anywhere, and two combos' inner edits held `89` while the combos themselves
painted `medium`/`Medium`. So read a combo through its own selection, and require the value to be *painted*
before believing an edit states a parameter — an unpainted edit's text is a buffer value, and building a
read path on one reports a setting nobody applied. The cheap test is one read plus one crop of the same
moment, compared cell by cell. **Select a combo's
item by value, never by counting steps or keystrokes:** a combo can step *past* a value (measured: one
step up from burst length `4` landed on `6`), so read the options back, take the index whose text states
the value you mean, and then read the field back to confirm what it now states — the entry-list traps
that hide inside that rule are spelled out under the discretised-knob rule below.

When a `TSp_Value_Button`-style
wrapper and its inner combo report the **same control id they are one widget** — put one entry in the
map, not two.

**2e. A dialog write is a transaction committed by the dialog's `Accept`, and `Cancel` never verifies
anything.** Write each field with its own surface recipe, then commit once at the dialog's `Accept` button
(the band's rightmost entry, `row[-1]`; `row[-2]` is `Cancel`). `Cancel` **discards** and is the read-only
gesture, so a write "verified" against a Cancel proves nothing about what the application kept, and the
read path and the write path must not share that step. Then verify in three rungs, in this order: (1) the
application's own model of the field, not the control's painted text — a typed value that was never
committed still reads as set, measured as a field that kept its old value until an explicit Enter; (2) after
`Accept`, a re-opened dialog or a readout the app *derives* from the value — **an open surface is not a read**: these dialogs keep displaying the value from before the change while the application has already recomputed it, so reading rung 2 in the dialog you just wrote shows the old number and looks exactly like a refused write (measured: an operator watching that open field reported "it never changes" — correctly, *about their surface* — while every freshly re-opened read saw it move). When their observation and your read disagree, establish which surface each read came from before believing either, and never treat an un-reopened surface as evidence in either direction; (3) the artefact the run
produces, read for the item that actually measured. Rung 3 is the one that counts, and a point that fails
any rung is refused rather than recorded. **Expect the companion field to be derived by the app, and treat
its refusal as an outcome to record, not as a retry:** writing a source knob re-selects a coupled one
(measured: the burst length re-selects the sampling volume from a physics-driven list, and a value below the
burst's floor is rejected with a modal warning), so a point's declaration must carry the *pair actually
accepted*, read back — and when the coupled field was itself the value under study, refusing the point is
correct, because an approximate substitute silently changes what was measured. Write the determining knob
first, and re-read the whole group before the irreversible step.

**3. Verify with a coupled observable, never with an echo.** Reading back the field you just
wrote only proves the text buffer changed. Pick a value the app *recomputes from* that
parameter (a status-bar readout, a derived count, a timestamp interval, the parameters
embedded in the file it writes) and assert on that. This is the difference between "the sweep
ran" and "the sweep ran with these parameters".

**4. Persist the map as ROLES, not ids, and re-resolve both at every launch.** In these toolkits a
`control_id` is a per-instance handle, not an identifier: measured across two launches of one
executable, both dumps held 43 visible controls with **43/43 classes at the same sorted position
and 1 of 43 ids in common**. An id-keyed map therefore passes every check inside the process that
captured it and reports *0 found* on the next launch — which reads as a broken app, not a broken
map. Store the role (`class` + its containing panel + its order within it) and resolve it to a
live handle at run time; keep ids for logging and for diffing two dumps of one launch. Rectangles
move within a session too (a window was relocated so every absolute coordinate went stale).
Identify the **container** by its ordinal position among its siblings — its handle changes per launch
like every other id — and band widgets on the parent panel, never on a fraction of the window: the
percentage cut moves relative to the widget as the client is resized (`references/control-id-mapping.md`
§8 has the measured case).
Recipe: `references/control-id-mapping.md` §8.

**5. Re-validate the map against the live instance before the first write — and attach in the
right order.** Find the process, wait for the main window's *class*, wait for it to become
**visible**, and only then validate. On a cold start the window may not exist yet, or may exist
hidden behind a startup/mode-selection dialog, and binding by executable path can attach to the
wrong instance of it — all three look identical to "the app is not running". Resolve with
`scripts/win_attach.py`; the state-machine capture method is in
`references/app-lifecycle-and-state.md`.

A map captured in one state — simulation/demo mode, an unlicensed build, a different
instrument — is only a hypothesis for any other instance. Mark every binding `required: true|false` and run a pre-flight
check that prints found/missing/unknown and **exits non-zero when a required control is absent**,
so driving fails loudly instead of clicking blind. Record a **geometry fingerprint** at
validation time (client size, DPI, minimized/maximized) and assert it before a run: screenshot
crops and anything cached depend on it. Put the **launch mode / caption** in that same assertion and
refuse a run launched in a mode the map was not measured against — the window title, or whichever state
string the app publishes, is the cheapest discriminator there is, and it is what makes "measured in
simulation, run on the instrument" a refusal instead of a silent substitution. **Compare two dumps as a
set difference on class, rectangle and text, and report only the controls that differ:** dumping both
whole trees drowns the delta, whereas one moved overlay plus ten changed values *is* the entire difference
between two modes of one application — and that short list is small enough to enumerate and act on. Maximizing is a fine convention for reproducible crops,
but it is not what makes the driver correct — `control_id` plus a run-time rectangle is. See
`references/control-id-mapping.md` §7.
Record a **control-count fingerprint** alongside the geometry one and assert it in the same
pre-flight: it is the cheapest detector for "a menu popup or a dialog is open, so this is not the
screen you mapped". When it fires, report what is extra and stop, rather than resolving roles against it.

**But a count is evidence, not the gate — one integer cannot carry three jobs.** A count that refuses
your own target mode is a fingerprint doing too much: *an overlay is open*, *this is a mode you did not
measure* and *this build's layout changed* all land on the same number, so the refusal names a layout
and gets read as drift when it is really a mode. Measured: a count captured in the application's
simulation mode refused the same application in its real mode — one extra parameter-row label painted
into the column, 43 visible controls against 44 — and the first press could not be made at all, while
every read ran fine. Two rules follow. **Do not admit an unmeasured mode by widening the number:**
write the new count down only once the difference is explained, and until then gate on *structure* —
the containers and panels the map already resolves, the strip's own shape and row length, nothing over
the top of it — carrying the count as evidence in the refusal text instead of as the gate. And
**assert the mode separately, from the stated string**: the caption assertion above is what gates a
mode; a total merely correlates with one. Then the refusal sentence names everything it read — the
counts, the strip's view, the caption — because a refusal that says only "unclean layout" costs a
session spent hunting a drift that is not there, and the honest fix looks like a second magic number.
Related: a screen's *clean* count is a property of one mode, so the bring-up table a second machine
reads must say which mode each number was measured in.

**A whole-state reading is two objects, not one: the evidence, and the identity anything
compares.** Keep the full fingerprint for diagnosis — geometry, `hwnd`, cursor, foreground,
because that is how a screen that does not match gets *described* — and derive a separate projection
for "is this the same instrument as last time", which is the same split as a per-state fingerprint
versus a stable identity. The projection must exclude
everything a **restart** changes (a new `hwnd`, a drag, maximising, another screen: keying on
those makes a restart read as a different instrument, and the resume re-runs a finished job), and
everything that is the *run's own data* — the store slider's maximum is the selected block's profile
count, so an identity carrying it moves as the buffer fills. A fingerprint is
*evidence* — capture it whole, volatile fields included, because a trimmed fingerprint is no longer
the diagnostic it exists to be. An identity is what a resume, a cache or a compatibility check
compares, and it may hold only facts that survive a restart: `hwnd`, window rectangle,
maximized/screen state, cursor position and the foreground flag are session-volatile (an `hwnd`
changes on every launch), so an identity keyed on them makes a restarted but identically configured
instrument read as a different one — which surfaces as a resume refusing, or a cache miss, after a
restart that changed nothing scientific. Project onto the item scope (channel, port, segment), the
mode, the configuration values **with their provenance**, the window class, the panel and
visible-control counts, and the strip view. A transient condition — a modal or overlay being up, a minimised window — is
in neither object: it is a precondition whose meaning is *refuse* rather than a property of the
instrument, so it must not enter the identity silently either.

Two more buckets leave the identity, and both are easy to include by accident. A value that is the
**run's own progress** rather than the item's configuration goes out — a readout that grows as the
buffer fills (a store slider's maximum, a button count that gains a control once data is held) — exclude *all* of the state that changes with the run's own data, not only the obvious part: this
application's ready row is 3 buttons or 4 depending on whether a leftover block is held, and the store
slider's maximum is the selected block's profile count. Two
  readings of one instrument then differ by how far the run had got, which is a false mismatch and a
wasted re-run. Keep what such a count *classifies into* instead (the view a press is bound against):
the binding is resolved live at press time, so nothing about driving depends on the identity carrying
the count. And a fact's **explanatory prose** goes out too: an identity is each value plus its
*source*, never the sentence explaining why — that sentence is written for a human and rewritten as it
improves. Exclude a fact's explanatory `reason` on the same principle: it is written to be
rewritten, so hashing it turns a documentation improvement into "a different instrument" and re-runs a
finished job — put the value and the *source* in the projection and leave the prose in the reading. Make that structural
(a projection model with a value field and a source field, plus a case asserting the identity's fact
fields are that type) rather than a convention in a comment. The **source stays in**: a fact that moved
from read to unreadable, or from *declared* to *verified by the step that established it*, is a
weaker or stronger claim about the same instrument, and the two must not share a name. When a value
rests on another step's verification, give it its own source
name (a channel the router selected and read back is neither "the caller declared it" nor "this
reading read it") and make the caller hand it over as a **required** argument — a
reading that pressed nothing, with an optional parameter, implies a verification that never ran.

**5b. Read the instrument's own fixed facts before the first recording, and refuse a disagreement
before anything is stored.** A plan may rest only on facts read off *this* instrument: read them from
the surfaces that state them (the measurement screen, the dialogs) before the first point, refuse the
run when a fact disagrees with the definition — naming **every** fact that disagreed, in one message,
because the comparison is cheap and the instrument is in front of the operator — and carry the reading
into the run's manifest as a projection of each fact's **value and its source** (`read` / `routed` /
`declared` / `unreadable`), so a stored file can be attributed to the state that produced it. Two rules
make the gate mean something. **A fact that has a reader and whose read failed refuses the run**,
instead of falling back to the declared value: "this instrument cannot state it" and "this attempt
failed" are different claims, and demoting the second is knowingly proceeding past a check that exists.
And the declaration is never overwritten by the reading, so the record keeps both and a disagreeing
fact is visible after the fact. `docs/dop3000/acquisition-campaign-compilation-plan.md` §9.2, §13,
§15; stage 5b of `docs/dop3000/live-bringup.md` is the live acceptance of it.

**6. Measure a discretised knob's domain instead of trusting the number you typed.** Numeric
fields snap to a ladder and clamp silently. Scan a range, read each value back, and design around
the value the app *accepted*. See `references/parameter-probing.md`.
**Choose an option by reading the control's own list back, never by counting steps from the current
value.** A measured combo stepped **past** a value — one step up from `4` landed on `6` — so a
step-counting writer asks for a configuration nobody wants, and the mistake survives every check that
only compares the field against the request. Enumerate the entries, match the requested value's text,
select that entry, then verify by read-back as usual. **The entry list is not a set:** the value currently
held occupies the first slot as well as its own, and the order is not sorted, so one requested value can
match two entries — take the **lowest matching index** (measured: `0.876` appeared at slots 0 and 4 of an
unordered seven-entry list, with the held value at slot 0). And a value the application states may be
**absent from its own list** (measured: a floor the app derived and displayed had no entry at all), so
"select by value" cannot express every request the application itself would accept.
**Derive the sweep plan from the app's own read-back constants, not from what you were told the
settings are.** A stated change may not be in the configuration you are actually driving: a sound
speed reported as changed to 1460 m/s was still 1500 in the channel's stored parameters, which moved
the resolution ladder rung from 0.1217 mm to 0.125 mm and would have put every planned point on the
wrong rung. Read the constants out of the app (its dialog readouts, or the artifact it writes) before
computing a plan, and where a derived readout exists — total depth as a function of first gate, gate
count and resolution — compute the plan so that it is checkable against that one number. **Assert the plan against the artefact's own derived quantity, not against the UI's text:** the app's painted first-gate/depth values are control values, and a decoder that reproduced the file's own depth profile matched it to within the quantisation step while the UI's stated first gate was 0.2-0.3 mm out — close enough to look right, and wrong enough to bias every planned point.

## The measured timing law: the achieved profile period

**The stored timestamps, never the log's `timing.target_s`.** The period a recording actually
achieved is the median of the successive differences of its own per-profile time array. The
retired planning field stays provenance only — it is what the planner *asked* for, and using it
as a measurement silently substitutes intent for observation.

**The fixed intercept is what you measure; the transfer term is only its remainder.** Do not
call the intercept a transfer term - this instrument's period law carries 16 PRF terms before
the transfer term, so at 600 us the intercept is 9.6 ms of internal emission plus the transfer
proper. On the mixer-enabled sparse pass, every level's achieved period was exactly

```
achieved period = emissions_per_profile × 600 µs + 10.400 ms
```

measured at all four values of emissions (8, 20, 64, 128): 15.200 / 22.400 / 48.800 / 87.200 ms,
i.e. 65.789 / 44.643 / 20.492 / 11.468 Hz, Nyquist 32.895 / 22.321 / 10.246 / 5.734 Hz. The
intercept decomposes as the manual's 16-term (16 × 600 µs = 9.600 ms) plus a 0.800 ms transfer
term proper — which is what makes it worth stating: it is the instrument's own overhead, not a
rounding artefact, and it is what any period *prediction* must add to match what the files show.

Two consequences for an acquisition that trades time for stability: the sampling rate falls with
emissions exactly as this law says, so the bandwidth cost is computable before running; and
levels must be compared on **equal physical duration**, not equal profile counts — the same 2 s
block holds 132 / 89 / 41 / 23 profiles at emissions 8 / 20 / 64 / 128, so an equal-count
comparison silently gives the low-emissions level more time.

## Pitfalls

The measured failure modes of this class, each with the observation behind it and the rule it
forces: reads that return empty across processes, presses the application ignores, dialogs that
dismiss instead of repair, and count-based gates that refuse the wrong thing. The full list is in
`references/pitfalls.md` — read it before driving an unfamiliar application or diagnosing a run.

## Evidence discipline

Label every load-bearing claim **verified** (measured on this machine), **from documentation** or
**unverified**, and treat a read-back from the write path as the strongest evidence there is. The
full rules — what a negative result proves, and when an empty answer is not evidence at all — are in
`references/evidence-discipline.md`. Re-read it before asserting a fact about the application.

## Reading the pixels: the committed crops, and how to magnify them

**Labels are paint; values are API.** A caption on this class of application is not in the control
tree — `WM_GETTEXT` returns `""` for nearly every widget and the row labels are not controls at
all. So a caption is quoted from pixels or not at all, and the way to be wrong is to read those
pixels at their own size or through a summariser.

**The oracle, and it is committed.** `docs/dop3000/ui-crops/` holds the cropped surfaces with
`docs/dop3000/ui-element-index.md` as the row-per-crop index (id, file, size, surface, state, what
it shows, and the `blocking` cell that is the operator's answer because no crop can show it). Read
the index before re-deriving a caption, and **cite the crop id** (`UI-MENU-05`, `UI-OVERLAY-22`)
wherever a caption is quoted, so the quote stays checkable. The index is checked against the files
rather than trusted: `uv run --extra acquire python tools/ui/crop_index.py` verifies existence,
real pixel size, unique and gapless ids and the row count, and exits non-zero otherwise. An index
that misdescribes its own files is worse than no index, because a quoted caption then carries a
provenance nobody can check.

**Two steps before a digit is believed.** Magnify at x5-x6 nearest-neighbour and compare glyph
bitmaps — `tools/ui/magnify.py composite` (labels + the flat-image guard) and
`… magnify.py glyphs` (ASCII bitmaps, so a contested `6` is settled against a digit known in the
same frame). Measured: reading at the crop's own size returned `500` for `600` (twice), `3.49` for
`0.49` and `725` for `726`; a *downscaled* full frame is worse, and two independent vision passes
on one value agreed on a wrong number — agreement is not corroboration. Prefer a column- or
band-wide crop to a whole frame, and read numbers from the API read, not from the picture.

**Taking a new crop is Windows-only.** `tools/live/probes/dialog_shot.py` captures one whole-screen
frame plus the dialog's own rect cropped from that same frame (so the two cannot disagree about the
moment), lossless, with a non-blank/stability guard, dispatched in the interactive session through
`tools/live/dispatch.sh`. A clone on Linux can read, magnify, check and quote the committed set but
cannot extend it; `docs/dev-handoff.md` is the protocol for what a machine without the instrument
must ask for. Details: `references/screen-vs-api-reading.md`.

## Deliverables shape

Put findings in reading order under `docs/NN-topic.md`, keep the machine-readable control map
next to the tooling, and keep the reconnaissance scripts re-runnable so the next session
re-derives nothing. The final report states what was measured, what was assumed, and the single
experiment that would settle each open question — with the highest-risk unknown first.

**Scratch scripts live in `.hermes/scratch/`, never directly in `.hermes/`.** The repo gitignores
`.hermes/` as the agent's working-artifact home and reconnaissance produces throwaway scripts
constantly — but a file written *directly* in a project-local `.hermes/` is read by Hermes' write
guard as agent-steering config, so every `write_file`/`patch` there asks the human to approve it:
one prompt per operation, no persisted scope, not bypassed by `--yolo` or the command allowlist
(the rule matches the parent directory name only, so the file name is never examined). One level
down is outside it. This is the same rule `AGENTS.md` states, and the reason to honour it is that
an approval-gated scratch write stalls a live acquisition session at the worst moment — move any
existing loose files into the subdirectory with `mv`, which is a shell command and not gated.

**Answer a capability question with the mechanism, one measurement and the gap — not a
narration of the implementation.** When the operator asks whether something is possible (*can we
record for a fixed time? is this value settable?*), what they need is: the exact step that sets
it, one number from a real run showing it took effect, and what still does not hold. Code
detail, call order and internal naming read as evasion when the question was yes-or-no, and a
report that opens with what changed rather than what is now *true* gets pushed back on even
when the work was correct. Lead with the number, then the caveat, then the file.

## Support files

- `references/pitfalls.md` — the whole pitfall list moved out of this file verbatim, so this
  router stays cheap to load: every measured failure mode with the observation behind it.
- `references/evidence-discipline.md` — the whole evidence section moved out of this file verbatim:
  verified / from documentation / unverified, the write path over a read-back, and what a negative
  result does and does not prove.
- `references/control-id-mapping.md` — the geometry recipe, toolkit fingerprints, input
escalation ladder, the map-file schema, and **§8 role binding** (why ids do not survive a restart,
  and the panel-based recipe to bind instead), and **§9 reading a value table by position**
  (values nested one level inside their wrapper, a row's choice control versus the read-out beside
  it, confirming a position against a second surface, and why a failed read of a *readable* fact
  must refuse rather than degrade).
- `scripts/win_ui_probe.py` — read-only probe: lists windows, dumps the handle-deduplicated
visible control tree, and captures each window's own pixels.
- `scripts/win_control_io.py` — the write path: read a control's value by id, set it by message,
read it back, and restore the previous value.
- `scripts/win_param_scan.py` — measure a numeric field's accepted domain: scan a ladder of
values, report what was accepted, and restore every field it touched.
- `references/parameter-probing.md` — snapping, silent clamping, hidden constants revealed by a
  ladder, and the confounded-probe trap.
- `references/app-lifecycle-and-state.md` — attach and cold-start resolution, hidden windows,
  capturing a UI state machine, the buffer budget for unattended recording, **§5 menus and popups**
  (the dismissal matrix, the `WM_CLOSE` wedge, and why menus stay out of a run), and **§6 the
  record/stop/store cycle** (the strip's state views, the held-press recipe, the store dialog).
- `scripts/win_click_probe.py` — run the click-recipe matrix against one control (hold time,
  coordinate space, move-first, posted vs injected) and report which recipe the app reacts to, with
  the enabled / `WindowFromPoint` diagnostics that rule out the mundane causes.
- `scripts/win_attach.py` — resolve which process owns the target window (by class, across all
  pids) and print the candidates; run it before any driver binds, and after any restart.
- `scripts/win_find_overlay.py` — the modality guard: lists the main window's child panels
  topmost-first, flags the one covering the mapped surface, and with `--press` answers its safe
  (left) button. Run it before a press sequence, and whenever a press appears to do nothing.
- `references/artefact-decoding.md` — decoding the file a run produces, which is the only read-back
  that proves a point: proving word size/stride/channel indexing before trusting a number, pinning
  fields by differencing two labelled fixtures, and the cross-checks that make a decode verified
  rather than merely plausible. **§5** adds what the file proves about the run's *duration* (requested
  vs stored window, the two-duration linearity run) and about per-item state.
- `references/win32-control-recipes.md` — the condensed recipe sheet for this class: value and
  commit recipes, the held press, overlay-before-press, button identity by order in the view, menu
  hover, and the long-unattended-loop rules (poll instead of sleeping, return to a known-good state
  before the next item, size-check every artefact).
- `references/custom-menus-clipcursor-and-real-input.md` — the custom-widget app's own menu overlays
  (caption-less panel + entries, geometry and screen-order matching, content-based dialog identity),
  when real cursor input is required and when posted messages still work, `ClipCursor` as a systemic
  hazard for real-cursor gestures, and the state checks that must precede any press.
- `references/dop3010-sweep-automation.md` — the project-specific sweep notes for the instrument this
  class was developed against.
- `references/dop3010-measurement-screen-surface.md` — what that instrument's measurement screen actually
  paints: the parameter column's labels with units (painted, so absent from the tree), the TGC mode's
  editing overlay and the sidebar row whose *presence* tracks the mode, the menubar's composition per mode,
  and the toggle that silently rewrites the acquisition frame.
- `references/screen-vs-api-reading.md` — reading a value out of an application you cannot introspect:
  labels from the pixels and values from the API, why a downscaled frame loses the digit that matters,
  the magnify-then-compare-glyphs step, and why two agreeing vision passes are not corroboration.
- `references/live-acceptance-rehearsal.md` — proving a pre-run check against the real application: the
  foreground precondition a dispatched process cannot satisfy on its own, refusing in both directions
  (declaration side and instrument side), reading the run's output directory out of the app rather than
  off the disk, the form a refusal must take (a message and a documented exit code, not a traceback),
  and the resume case that must prove its identity before it skips anything.
- `references/live-run-bringup.md` — running the automation on a machine that is not the one it was
  measured on: what the repository must carry to be runnable at all (the interactive-session wrapper,
  the dispatcher, the capability probes), the staged bring-up with pass criteria, the
  measurements-folded-in table, what to declare open, and the window-move proxy test.
- `docs/dop3000/acquisition-architecture.md` (repository) — the architecture, the layer boundaries
  and the invariants the refactor may not reinterpret, plus the target module layout with a
  *status: target / landed by patch N* marker per module. Read it before describing how this
  subsystem is organised.
- `docs/dop3000/acquisition-ui-model.md` (repository) — the surface taxonomy, the
  measurement-screen predicate, every cropped surface by crop id, the widget and binding rules, and
  the blind-spot ledger B01..B20 with what may be asserted before the next device session.
- `docs/dop3000/device-verification.md` (repository) — the V0..V8 procedure that retires the
  device-pending items after a refactor, with its stop condition and its promotion rules.
- **Promote the probes' private reach into a public surface, and let the package be the
  interface.** A capability probe calls the driver's *privates*, which makes it the least verified
  code in the repository: the fakes model the public surface, so no test can drive it. Move each
  capability into the package as a command returning a report **model** (the project's model base,
  JSON-serialisable, declared with the protocol's vocabulary because a report is destined for the
  job log), add a thin public wrapper for every private a command needs
  (`hold_recording`, `wait_for_view_guarded`, `peek_overlay`), and give a whole sequence one
  composed method whose destructive step is replaced by the safe one (`preflight`: record, stop,
  read the store dialog, **cancel** it). Three rules make the seam testable, and each was forced by
  a fake that could not be driven otherwise: it reads through the **public primitive** the double
  already answers rather than the internal helper beside it (`strip_state()`, not
  `_state_of(roles)` — the same read, and only one of the two a double can produce); it uses the
  **same detector the cycle uses** rather than a parallel finder, so a reader and a run cannot
  disagree about what is on screen; and it captures the run's notes **into the report** as well as
  to the caller's sink. Add the module-level dispatcher in the same change —
  `python -m <pkg>.cli <command> …` is the form the live route can actually start, so an entry
  point with no `__main__` guard cannot be dispatched at all. Then split the tests by what each
  layer owes: driver-level cases against the existing fake, command-level cases with the actuator
  **replaced** (a CLI owes argument handling and exit codes, not the cycle it delegates to).
  Assert **self-consistency with the primitives and the double's own event vocabulary** — never the
  installation's measured numbers, which belong in the bring-up table: a control count is a fact
  about that machine, and a double may not model a state at all (assert the absence of its own
  "stored" event rather than a dialog flag it never clears).
  **Retire the probe once its command exists, and correct every document that still names it.** A probe
  earns its place only while it *measures* something no command covers (a geometry stress test, a
  one-off diagnostic); a probe that acts on the instrument and duplicates a command is a second
  implementation of the same gesture — the untested one, and therefore the copy that drifts. Delete the
  superseded files, say in the README what the survivor is for, and grep the docs, the bring-up
  checklist **and the dispatcher's own usage examples** for the old filenames: a checklist that names a
  deleted probe, or a command form that never existed, costs the next machine its first hour. Re-run the
  survivor from the clone after the deletion — a surviving script is verified by running it, never by
  compiling it.
