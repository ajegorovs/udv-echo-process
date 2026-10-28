# Message-route port: what still has to move off input emulation

**Task plan.** Written 2026-10-23. **State:** in progress.

## Destination

**Purpose (owner clarification, 2026-10-26).** The basic goal is automated control of the UDV instrument. The current
product goal is **regular and multiplexed recordings while the application runs in the background**, so the operator can
use the machine normally during acquisition. A foreground setup step and **one binding to the running application at the
beginning of a session are acceptable**; automatic rediscovery after every restart is not a prerequisite for this milestone.
The binding must still identify the current instance and be invalidated when that instance changes.

The UI route emulates an operator; the message/bridge route reads window state and calls application routines. The latter
is the chosen enabling mechanism, not a deliverable merely because its interfaces or register are complete. Whether it
reduces the cost of mapping new controls is unproved. Targeted reverse engineering should remove a named workflow blocker.
Mapping the remaining controls is a later goal; full application reconstruction is a possible future direction, not selected
implementation. The [host contract](../dop3000/guarded-cycle-contract.md) owns the binding/execution interface.

**Established background baseline (owner correction, 2026-10-26).** Background execution is already demonstrated for the
then-mapped action set, not a new feasibility milestone. The owner confirms the full-screen Explorer covering test; the
2026-10-23 evidence below includes complete acquisition, parameter-changing series, and releasing the save dialog's
cursor confinement while restoring the pointer. Later restart/binding and packaged-interface gaps do not erase that result.
The subsequent guarded-cycle, report and readiness slices are principally hardening/integration, not first proof of background control.

**Observable outcome / acceptance criteria.**

1. After a documented setup/binding step, execute a regular recording end to end: verify the selected configuration,
   start, stop and store a uniquely named recording, then check its decoded settings, channel and acquired time span.
2. Execute multiplexed recordings for the channel/sensor configurations required by the experiment, verifying participating
   channels, per-channel settings and recorded data. A simpler sensor combination is not evidence for a required unsupported one.
3. Repeat the required recording cycles while another application remains in use: no recurring foreground requirement,
   stolen keyboard/mouse input, cursor movement or persistent cursor confinement. The existing Explorer/pointer-guard test
   establishes this baseline for the previously mapped actions; apply the criterion to new workflows, not as a reason to repeat it.
4. Reuse the valid session binding without per-recording setup. After restart or identity change, refuse until a new binding
   is established; automatic rebinding is not required for this delivery.
5. Preserve honest refusals and recording evidence. Offline tests, a complete control register and a historical probe do not
   substitute for an exercised live workflow.

**Delivery order.** Prove regular background recording first, then multiplexed background recording. Map additional controls
as later coverage work, driven by actual use. Full reconstruction remains conditional on need and feasibility; it does not
block either recording milestone. These priorities do not authorize live actions or private-provider changes by themselves.

**Multiplexing question (owner report, 2026-10-26).** Mixed-base-frequency sensors are refused with a requirement concerning
matching sampling volume, even after parameters are adjusted to give similar sampling volumes. Exact application text,
settings and the validation condition have not been captured in this slice. This is an observed restriction, **not a proved
bug**. Establish the requirement for the intended sensor set and investigate the actual comparison if it blocks that setup;
do not silently substitute a simpler setup or bypass the check before its meaning is understood.

**Register evidence rules (not a feature queue).**

1. Every row of the port register in *Remaining work* carries a status that is backed by a measurement, and a status is
   never raised without the acceptance evidence named in its row.
2. Each action marked `works` can be executed with `allow_real_input=False` in one run, with the read-back recorded.
3. Each action marked `blocked` names its blocker as a capability (an unknown object, a missing routine, a dialog) and
   not as "not attempted".
4. No row is closed by widening what counts as the message route: a step that presses, hovers, teleports the cursor or
   types into a control is input emulation, whichever function it is called from.

**Non-goals.**

- Retiring the UI route. **Owner decision 2026-10-23: the old system stays.** Both routes coexist; `--route ui` remains
  available and remains the fallback for anything the message route cannot do. There is no retirement date, and no work
  here removes an old-route capability.
- Changing the acquisition semantics (`models/`, `process/`, `storage/`). This plan touches only how the application is
  driven.
- Redesigning measurement physics, experiment definitions or campaign semantics. Investigating an application validation
  condition that blocks the required multiplexed recording is relevant, but bypassing it is not authorized by that relevance.
- Requiring automatic binding discovery after every restart before the first useful background-recording workflow.
- Completing every control mapping, eliminating every posted press, or reconstructing the application before either
  recording milestone. Mechanisms remain accurately classified in the register; background usability is the delivery test.

**Authorization boundaries.** The owner authorised continued construction on the message route and asked for this
register so it is discoverable at session start (2026-10-23). That covers: building, measuring and documenting the
message route; committing to this branch, never pushing. It does not cover unattended mutation of the instrument's Store,
relaxing a safety guard, or editing the machine-local binding material, each of which needs a fresh, explicit grant.

The bounded slice of 2026-10-26 was granted on narrower terms and is recorded as such: offline evidence and build fixes
with an independent review — no live action against the instrument, no application restart, no commit or push, no binding,
secret or machine-local configuration change. The wider grant above is unchanged; work that needs the application running,
or an operator at it, is listed in *Selected next* as needing its own session's authorization rather than being implied by
this one.

**Current execution grant and setup (owner, 2026-10-26).** The owner requested delegated continuation without further
routine involvement and explicitly granted bounded unattended live integration: machine-local adapter/binding updates,
reversible setup changes with read-back and verified restoration, and uniquely named test recordings. No application
restart, existing-file overwrite, validation bypass, secrets changes or push is authorized. All transducers are
disconnected; retained channel configurations may include 10 MHz. Sensors of interest are 4 MHz and 10 MHz, but mixed-frequency
multiplexing is lower priority unless it can be understood quickly/cheaply. Prioritize usable regular recording, then
straightforward multiplexing. Sensorless files can establish control/configuration/timing/storage, not physical flow or
signal validity. A fresh scheduled read found instrument mode, a clean READY screen and no visible application error box;
that is a starting-state observation, not acquisition acceptance. The coordinator alone owns live desktop access.

**Baseline.** Round-based measurement at 2026-10-23, application instances discovered per probe (never cached), session
unlocked. The message route's building blocks as measured that day: reads by window message; dropdown selection by
`CB_SETCURSEL` with read-back; overlay open/close by routine call; one numeric setter transition proven. The UI route's
capabilities are those recorded in `docs/dop3000/` and `.agents/skills/udop-acquisition/`.

## Patterns this work follows

The repository's own conventions: transforms and drivers are bundle-closed and testable off the instrument
(`AGENTS.md`, `docs/pipeline-conventions.md`); the acquisition package is import-safe everywhere and only
`acquire/driver.py` may touch the platform API; anything that touches the screen runs in the interactive session through
`tools/live/dispatch.sh`. The method source for planning is the estate's work-organization guide, linked from
`AGENTS.md` § Planning a task.

Two measured facts that a fresh reader would otherwise re-derive, and that shape every row below:

- **Input is gated on activation.** The application ignores a press while its window is inactive, and its overlay acts on
  the row it believes is hovered rather than on the child window that received the click. Posted messages are not a
  substitute: `WM_MOUSEMOVE` + `WM_LBUTTONDOWN`/`UP` posted to a row's own handle, to the overlay, synchronous or posted,
  with the cursor teleported onto the row, changed nothing — and the post-press window capture was pixel-identical to the
  one before it.
- **Real input injection is unavailable here.** `SetCursorPos` moves the pointer, `SendInput` is accepted and discarded
  (both processes at the same integrity level, session unlocked, no cursor clip in force). So the UI route can only be
  exercised by a human at the machine, which is the reason the message route matters at all.

## Current checkpoint

**How to read this section (revised 2026-10-26).** Three kinds of claim sit below and are not interchangeable.
*Measured live before the application's restart (2026-10-23)* — historical successes against the instance then running, and
the evidence rows 11 and 12 rested on until 2026-10-26. *Measured live after it (2026-10-25/26)* — the boundary acceptance, plus a crash box
seen during live work that is not attributed to a route here. *Offline state (2026-10-26)* — what the code now does and
refuses, the guarded cycle and its factory/CLI selection included, verified without an instrument. **Established by none of
them:** a restart-safe way to find the owning object — settled on 2026-10-26, where the owner is re-observed per command
rather than remembered, so record, stop and store work through the guarded route and the rows say what each still costs.
A register status describes the capability today, not what once ran.

**Established** (measured 2026-10-23, this branch):

- Reads are message-level and focus-independent: sidebar column, fast-access roles, a dialog's fields, strip state,
  process-mode note. Verified with `allow_real_input=False` while another window held the foreground.
- A dropdown can be selected by exact text with a read-back, and a walked list cannot be left on its last step
  (`ui/combo.py`, double-select + double-read + per-control vocabulary cache).
- A menu overlay can be opened and closed by calling the application's own routines
  (`Enter_Menu`, `Leave_Current_Menu`), with a census guard refusing a dirty screen before and after.
- The operating-parameters dialog can be opened, read and closed with no cursor and no focus, which is what makes the
  channel check unattended.
- A numeric setter committed a value once (one transition, artifact-verified) and did **not** commit again in a fresh
  attachment, which is why the current wrapper repairs a mismatch through the UI instead.

**Not established.** Whether the application's own strip routines (`record`, `stop`, `store`) can be called in a **fresh
instance**: they execute when given the owning object for that instance, and fault without one, so the call is not the
open question — finding the object is (2026-10-23 settled the call for the instance then running). Whether a row's
`…Change_State` handler can be made to act: it runs without error and changes nothing, because its `Sender` is not
supplied. Whether a numeric write can be made repeatable. Whether channel selection can leave input emulation at all — the
old route itself is unsafe there.

**The bridge's evidence rules were tightened, and reviewed offline (2026-10-26).** An uncommitted slice in
`acquire/bridge.py` and two test files changed three rules: an explicit `target_digest` now gates a supplied store cycle as
well as a host dispatch — a cycle replaces execution, not the build its routine addresses belong to; a stored host report
must state true booleans for its configuration and identity verdicts, a well-formed SHA-256 and a path, where a missing
field or a truthy string used to read as success; and the returned file must be the requested point — its directory, and its
name exactly or with one application-added suffix — because "a file exists" is satisfied by the previous point's block. A
supplied cycle's own return is validated the same way: `_cycle_result` refuses a malformed one as
`bridge_cycle_result_invalid:{ok,stored_path,result}` rather than crediting a truthy string or a non-path, and `_named_for`
refuses `point.tmp.BDD` for `point`.

Offline verification at the time (2026-10-26, before the slice below): `uv run --no-sync --extra dev python -m pytest -q
tests/test_acquire*.py tests/test_bridge*.py` — 1207 passed, 37.43 s, with five failures that are the established baseline
and not this slice's (two in `tests/test_acquire_dialog.py`, three in `tests/test_acquire_live.py`, every one a fake-driver
escape into real session-0 window discovery). A scoped `ruff check` over the acquisition source and the bridge/wiring tests
passed, as did `git diff --check`; no repo-wide lint claim is made here. The independent review passed the evidence/build
patch; its follow-up — the malformed cycle return, the non-path outcome and the `point.tmp.BDD` suffix case — was
implemented by a separate worker and checked by the coordinator's rerun. That is verification of a fix, not a second
independent review of it.

**The guarded cycle is implemented, offline-verified and independently reviewed (2026-10-26).** The identity/state
contract, the host factory and the `point`/`sweep` selection now exist; the host-facing contract is written once in
[`dop3000/guarded-cycle-contract.md`](../dop3000/guarded-cycle-contract.md). The independent review's verdict was
*changes required — records only*: the safety proof held — refusals make zero calls and leave a `preflight` report, a
mid-cycle restart blocks the next call and the commit, unconfirmed transitions drive the report flags — and four seams were
weaker than their prose (a static digest comparison made after the factory, an unusable offered report erased into absence,
one note serialised twice, a zero-byte store credited when a decoder answered anyway). All four were fixed, and a
**closure review** of the fixed tree approved each with the test that pins it. The independent review's one blocking
finding was this file and the agenda row still claiming no factory, no command and no fixture — corrected in this pass.

Verification of record: `uv run --no-sync --extra dev python -m pytest -q tests/test_acquire*.py tests/test_bridge*.py` —
1370 collected, **1365 passed, 5 failed in 39.25 s**, the same five session-0/fake-driver failures as above and not this
slice's; a scoped `ruff check` over the changed sources and tests passed, as did `git diff --check`. No repo-wide lint
claim is made. Source, tests and the fixture are locally committed at `29cbd0a`; nothing is pushed, published, deployed
or live-verified.

**Readiness/error guard checkpoint (2026-10-26).** Locally committed at `429597f`, implemented and verified offline.
The shared `ui.readiness` guard covers UI and bridge single-point entry, preflight and the sweep runner; an offered
unreadable, non-callable or malformed capability is not a clear screen, including through the bridge's forwarding boundary.
The reader uses the main window rather than a healthy layout to identify the target process, and the existing bounded
`WM_GETTEXT` query when the caption snapshot lacks text. A visible target dialog with unreadable text still blocks.
A readiness refusal during a UI recording skips recovery for that invocation, even if the box subsequently disappears;
ordinary clear-screen recovery is unchanged. Prior cycle evidence is cleared before a new entry refusal.
Independent review and closure checks covered the forwarding, ordering, stale-report and recovery findings, then the final
explicit-`None` capability correction. The combined acquisition/bridge gate is **1416 passed, 5 failed in 38.31 s**;
all five failure IDs match the earlier session-0 baseline. Scoped Ruff, formatting of the new files and staged whitespace
checks passed. The tests inject native APIs; no live application, production host integration or fault recovery was proved.
The detector conservatively blocks target-process `#32770` dialogs; it does not prove a dialog is a crash. Standalone
channel/column commands remain outside this bounded guard slice.

**Not established by any of that:** no live compatibility or deployment. The saved-report fixture now shows the
stored-result parser reading a real cycle's own report as typed evidence — a gate before deployment rather than a reason to
relax the checks — and by its own provenance grounds schema only. This slice implements no production host export: a fake
host on disk did construct and run real guarded cycles in tests, but no real configured export or current-instance binding
was implemented or validated, no live run exercised the new route, and no NEW binding or guard contract has been observed
against a running application (the owner observations recorded above are the earlier, raw-routine measurements). The
review's input-name and link/symlink policy findings are deferred, not selected.

**A campaign reports its own points as valid (2026-10-23/24).** Rungs 5 and 6 through `live.sweep`, driving the composed
cycle with the application covered: both points `PointStatus.OK`, `camp-k5` 514 × 96 at 0.6167 mm and `camp-k6` 513 × 80 at
0.74 mm, both spanning ~20.7 s, two log lines, four dialog clips released, cursor restored. Wall clock 62 s per point.

The fix was to state the window instead of assuming it: the cycle's limit became an overhead allowance (`duration + 20 s`,
the measured cost of two attachments) and `SweepRunner` gained `window_overhead_s`, set to 20 s by `live.sweep` exactly when
a cycle is supplied. Same file, both ways: against the requested window the ratio was 2.111 (refused), against
`requested + 20 s` it is 0.909, against the achieved span 1.005.

**The false verdicts were a recording window nobody had measured (2026-10-23).** The size guard's rate model is correct —
`profile_period_s(50, 600)` is 0.0406 s and the stored blocks' mean profile interval is 40.34 ms — and its arithmetic for the
*requested* window is correct too: 4 s predicts 99 profiles. What was wrong was the premise that the recording lasted the
requested window. It did not: the block spans **20.657 s** (513 profiles at 40.34 ms), because record and stop are two
separate attachments and the recording keeps writing until the second one lands. So a sound 21 s file was compared against a
4 s expectation and called contaminated at 2.11x.

Two facts follow. The guard was right to fire on the numbers it was given — the input was the lie, not the check. And a
requested 4 s point costs about 21 s of data, which matters for a sweep's duration budget as much as for its verdict.

`RoutineCycle` now reads the span from the block's own timestamps, reports it, and refuses a block that ran past twice the
requested window; an unmeasurable span is a refusal rather than a pass. That turns the silent wrong verdict into an
explicit one, and it deliberately makes the current live behaviour fail: with attachment overhead inside the window, a 4 s
request is refused as a 20 s recording.

**The campaign path ran end to end, and it exposed a defect in a guard, not in a file (2026-10-23).** `live.sweep` over
rungs 5 and 6, driving the composed cycle with the application covered: two points recorded and stored
(`camp-k5-…`, `camp-k6-…`), the JSONL log holding one entry per point, and four dialog clips released. Both artifacts are
sound — 513 profiles × 96 gates at 0.6167 mm and 602 × 80 at 0.74 mm, last gate ≈71.8 mm on both — but the runner returned
`PointStatus.INVALID` for both, because its size signature predicted **99 profiles** where the recording achieved **513**.

The arithmetic is exact and it exonerates the files: `31 268 + (19 + 2×96) + 513 × (19 + 96) = 90 474`, which is
byte-for-byte the stored size, while the same equation at 99 profiles gives 42 864 — the number the guard compared against,
a 2.11× ratio just past its 2× band. So the container/block model is right and the **profile-count prediction is wrong by
about five times for this configuration**; a genuine block is being called contaminated. That is a calibration defect in a
safety check, and it deserves a measured fix rather than a widened band: the prediction should come from the rate the
application actually achieves, or the decode should be the verdict with the size as an advisory. Until it is fixed, a
campaign through `SweepRunner` cannot report its own points as valid, even when they are.

**The cycle is package code now, not a runner that presses (2026-10-23).** `acquire/cycle.py` composes record → stop → store
→ name → commit from the application's own routines and one press on the dialog's commit, and carries the refusals a
sweep depends on when nobody is watching: a stored name is refused before recording, an undispatched routine stops the
cycle naming its stage, a commit that writes no file fails, and a block counts only when it decodes to a stream. The
caller, dialog and decoder are injected, so all of it is tested without an instrument (10 tests), and `BridgeActuator`
prefers a supplied cycle to any host dispatch — the sweep runner and its evidence rules are untouched.

Proven live with the application covered: two points, `0.617` then `0.740`, each written by message and stored through the
composed cycle, each returning its artifact path from the package rather than from a host report, and decoding to 0.6167 /
0.74 mm with last gates at 71.83 / 83.55 mm. The pointer guard released both dialogs' clips and restored the cursor.

**A two-point sweep ran, and its blocks prove the measurement changed (2026-10-23).** Resolution was written between
points — `0.617` then `0.740`, each read back from the sidebar before recording — and both points stored. The acceptance
is the decode, not the read-back: `sweep-01` decodes to 0.6167 mm with a last gate at 71.83 mm, `sweep-02` to 0.74 mm with
a last gate at 83.55 mm, same gate count and same first gate. So a parameter that moves the measurement can be changed
between points by message, and the change reaches the stored data. The pointer guard released two clips and restored the
cursor; the parameter was put back to `0.617` afterwards and read back.

Worth recording as a correction: this row had been carried as "commits once, not repeatably" on the strength of the
bridge's setter dispatch. The message recipe commits as often as asked — four times in one attachment, four more in a
second — so the limitation was the mechanism's, not the application's, and the register's status was too pessimistic.

**A three-point series ran, with a parameter changed between points and the guard held throughout (2026-10-23).** Points
at `high`, `medium`, `high` sensitivity, each selected by text with a read-back that matched, then record, stop, store,
name and commit. All three stored blocks exist and decode (538, 536 and 535 profiles × 96 gates; finite; every gate
supported; resolution 0.6167 mm). The pointer guard ran for the whole series rather than around one dialog: three clips
detected, three released, all the same rectangle, and the cursor returned to where it was found. Coverage held at every
sample — the application never came forward — and the cadence was about 67 seconds per point. The store dialog opened with
the previous point's name in its field each time, which is the contract the plan pinned: the name is written before every
commit and never assumed empty.

**The pointer can be kept usable, and here is why it mattered (2026-10-23).** With a real operator working in a covered
window, the store dialog confined the mouse to its own rectangle — a desktop-wide clip set by an application that was not
even in front, so the pointer was trapped inside a dialog nobody could see. Measured: the clip was exactly the dialog's
rect, `ClipCursor(NULL)` from the non-foreground probe released it, the application did not re-apply it, and the modal had
also re-centred the cursor (423,0 → 968,556), which the guard puts back. A covered cycle then ran with the guard around the
store step: one clip detected, one release, cursor restored, and the block stored — so the two things an operator notices
are both handled, and both are now package code (`acquire/ui/pointer.py`) rather than probe scaffolding.

**A complete acquisition cycle ran with the application covered (2026-10-23).** The whole cycle — record, stop, store,
name, commit — with another window in front, checked at every stage: three sample points under the screen's centre returned
the covering window's class and never the application's, and the application never held the foreground, before recording,
during it, with the store dialog up, and after the commit. The dialog was raised, its name field was filled by a window
message, its `Accept` took one posted press, and the block landed: `covered-cycle-01.BDD`, 2713 profiles × 96 gates, every
gate supported, finite values, resolution 0.6167 mm. So the cycle does not need the application in front, and the store
dialog becomes active enough to receive its press without it — which was the one thing the earlier foreground runs could
not settle.

**A complete acquisition cycle ran from the message route (2026-10-23).** Record, stop, store, name and commit, in one
run: the three strip routines were called with the primed form object (their bodies read the form's control fields and
write the application's own command codes — 28 for record/stop, 29 for store — so no input is involved in starting or
stopping), the store raised its dialog, the file name was set by `WM_SETTEXT`, and the dialog's `Accept` took one posted
held press. Acceptance is the artifact: the stored block decodes to 4677 profiles × 96 gates with every gate supported and
the resolution the instrument was set to. Two facts worth keeping: a store dialog's `Accept` is a `TSp_Button` that does
take a posted press — a modal dialog is the active window — and the file name is a plain `TEdit`, so naming needs no input
at all.

**Menu rows work by calling the handler — and the earlier "needs its Sender" reading was wrong (2026-10-23).** The
disassembly settled what trial could not: the Display rows' handlers take `Self` and `Sender`, store both at `[ebp-4]` and
`[ebp-8]`, and never read them again; the body is a bitwise operation on the display-flags slot, a `Leave_Current_Menu`
call and a redraw request. So neither object was ever required. My earlier "the handler executes and changes nothing, so
it needs its Sender" was an inference from an effect, not from evidence — the real reason was that the request cleared a
bit that was already clear, which is a no-op by construction. Measured after the correction: the horizontal row took
`display_flags` 0 → 2 and the vertical row 2 → 0, in one attach, no objects, no input, restored to the start. The
generalisable rule, now recorded: read a handler's body for `[ebp-4]`/`[ebp-8]` before deciding it needs an object.

**A row's control is located, and the three obvious ways to act on it are measured and do not act (2026-10-23).** The
form holds the row's control at field offset `0x45c` (32-bit pointer — reading eight bytes there picks up the neighbouring
field, which is why the attachment now reads the narrow value and validates the class). With that, the three act-paths
were tried in the order a click performs them and all three failed differently: the handler executes and does nothing, the
control's `Change_State` executes and does nothing, and the two-step (state setter then handler) faults at `0xffffffff`,
which says the setter expects an argument the call never gives it. The operator's own click remains the only thing that
moves the flag, so the row's path exists but is not yet described. What is described is the *boundary*: the objects, the
field offset, and the setter's address — enough for a disassembly pass to say what the setter wants, and not enough for
another probe to find out by trial.

**A row's object is captured by observation, and it is not enough on its own (2026-10-23).** Window→object is refused by
the application outright: the attachment's own resolver reports `no TSp_Button object on hwnd …` after trying a property
atom, `GWLP_USERDATA`, and the small negative offsets. So the row's object was captured the other way — a read-only hook
on the row's handler while the operator pressed it once: `self` = the form, `sender` = the row's object, and the form
value matched the one the setter hook produced independently, which is a second, independent confirmation of the same
object. Supplying both to the handler executes it without error and changes nothing, while the operator's own click does
change the state — so a row acts through its control's toggle (state byte and notify), not through its handler alone.

**The owning object is now resolved, and priming needs no input (2026-10-23).** Two routes are closed and one works.
The discovery observes the application's own call, so it needs the application to act: instead of a human pressing
something, the message route changes a parameter itself (select a combo entry by text, then put it back), the application
calls its setter, and the discovery reads the widget's owner. Measured on the live instance: the run reported
`complete: true` with seven observations and one owning object, class `TMain_Scr`. Supplying that object to the strip's
record routine then executed it — `ok`, `executed`, no errors — and the strip's own state moved from `recording` to
`store`. So **priming is a step a probe performs**: attach the discovery, change one value and restore it, keep the
object, and every later call in that instance needs no input. A restart invalidates it, and a stale object must refuse.

**Two routes tried and closed (2026-10-23).** The binding captured for an earlier instance cannot be
reused: reading the process's memory shows its form pointer is not even mapped in the running instance, so a recorded
object pointer is stale by construction and must refuse rather than be trusted. Nor can the object be found by its class
signature alone: scanning the process's committed readable memory (371 MB, 477 regions) for the recorded VMT pointer
found exactly one occurrence, inside the module's own class metadata and not an object — so that signature does not
identify a live form in this instance. What is *not* in doubt is the module: routine addresses from the table still
resolve and execute in this instance, so code is stable while objects are not. That leaves observation — capturing the
object the application itself uses when it calls one of these routines — as the only route with a mechanism behind it,
and it needs the instrumentation step that currently fails (see *Relevant revision*).

**Instrumented steps need a node a probe can execute.** The agent shell's bundled tool directories are ACL-closed to a
dispatched probe (`Access denied`), so a probe's `node` lookup finds nothing and the instrumentation spawn fails with a
file-not-found that reproduces nowhere from a shell. A copy of the executable inside the repository's scratch works for
both sides and is what the priming step uses.

**Relevant revision / artifacts / live target.** This branch (`feat/application-backed-bridge`), and the machine-local
binding table that carries routine addresses and the menu row map; those stay machine-local and are never committed.

**Working state / recovery needs.** The UI route's record runner is machine-local scratch and is not part of the package.
A bridge run reaches the message route's own cycle only when it asks: `--route bridge --bridge-guarded-cycle` selects it
and refuses by name instead of falling back to a press dispatch, so with the flag no press-driven cycle is used, while the
default route and the legacy bridge path are unchanged. The guarded-cycle source, tests and fixture are checkpointed
locally at `29cbd0a`; the completed readiness guard is at `429597f`. No push or live action is implied.

## Remaining work

### The port register

Statuses are claims about the **message route only**. `works` = no input of any kind. `partial` = the message route does
part of it and input does the rest. `blocked` = the message route cannot do it yet, with the blocker named as a
capability. `absent` = no message-route implementation exists.

Two consequences of criterion 4 that the rows below apply (2026-10-26). **A posted press is input emulation** — whether it
lands on a modal dialog's `Accept` or on a form control — so a row only a press can perform is `absent`, and a row whose
last step is a press is at most `partial`, never `works`. **A row whose mechanism is a routine call that needs an object
nobody can currently discover is `blocked`** on that discovery, however cleanly it ran against an earlier instance; a row
that composes such calls with message-level steps is `partial` and names the row that blocks it. One classification is left
open rather than decided here: the numeric-write recipe posts a synthetic Return key event (`WM_SETTEXT`, a synthetic
`EN_CHANGE`, then the key message), and row 8's status rests on that being a control write rather than a press. This pass
does not settle it, and calling the row `works` would not settle it either.

| # | Action | How it is done today | Message route | Blocker / evidence |
|---|---|---|---|---|
| 1 | Read a fast-access parameter | input on the value button, then read the dialog | **works** | `read_parameter` by window message; 7 roles read with `allow_real_input=False` |
| 2 | Read the whole parameter set | same as 1, repeated | **works** | `main` block of the same read; used by the preflight |
| 3 | Read the sidebar column, channel identity, strip state | screen reading by a human | **works** | `WM_GETTEXT` on the column's edits; strip state from the control |
| 4 | Read a dialog's fields | reading the dialog by eye | **works** | dialog opened by dispatch, fields read by message |
| 5 | Select `Sensitivity` / `Emitting power` by text | click, then keyboard arrows | **works** | `select_by_text` + read-back after a settle; drift regression covered by a test |
| 6 | Select the TGC mode | Tools → Define TGC → mode list → Accept, by hand | **partial** | mode **selection** is message-level; the dialog's `Accept` is still a press |
| 7 | Accept / cancel a dialog | click | **absent** | no message-level acceptance exists. The measured mechanism is one posted held press on the dialog's own button: it closed the store dialog and the file was written, which is the one place a press has been seen to land because a modal is the active window. A posted press is input emulation by the definition above, so that measurement is input debt rather than message-route capability, and the row is downgraded from `works` (2026-10-26) |
| 8 | Write a numeric parameter (`us_frequency_khz`, `prf_us`, `gates`, `resolution_mm`, `emissions_per_profile`, `doppler_angle_deg`) | click the value, type, Accept | **works** | `write_parameter` is the measured message recipe — `WM_SETTEXT`, a synthetic `EN_CHANGE`, then the Return key event — with no press and no cursor. Measured with the application covered: four commits in one attachment and four more from a second, independent one, every value read back from the sidebar. The earlier doubt belonged to the bridge's *setter dispatch*, a different mechanism, and is withdrawn for this path |
| 9 | Choose / enable a measurement channel | press the channel cell | **absent** | not attempted in the message route; the old route restarts the measurement loop and is the path that failed at the device layer |
| 10 | Activate a menu row (grids, persistence, filters, assisted mode, record options) | hover the menu bar, press the row | **works** | calling the row's handler directly moves the application's own flag: the horizontal-grids row took `display_flags` 0 → 2 and the vertical-grids row 2 → 0, in one attach, with no objects, no input and no cursor. The handler's body does not read `Self` or `Sender` at all — it stores them and ignores them, then acts on the flags slot, closes the menu and requests a redraw. Rows whose handler *does* read those registers are untested |
| 11 | Start / stop a recording | press the strip | **works** | measured 2026-10-26 through the assembled command: `point --route bridge --bridge-guarded-cycle` dispatched the record/stop handler twice and the strip moved `ready` → `recording` → `store` on two consecutive points, both stored and decoded. The owner is re-observed **per command** rather than remembered: the producer attaches, has the application apply one value through the message route (which makes it call its own setter), reads `TSp_Value_Button.callback_self` for the `TMain_Scr` pointer, and states it with its source, so the 2026-10-25/26 discovery blocker is closed without a saved pointer. The earlier 2026-10-23 measurement stands as history |
| 12 | Store a recorded block | press the strip, name it in a dialog | **partial** | the store handler is dispatched like record/stop, the dialog is waited for, its `Working directory` is **read and compared** (`store_directory_mismatch:...` refuses before naming), the name goes in by window message and the accept is one posted press — still input, and the row says so. Measured 2026-10-26: two blocks stored and decoded (`host-01.BDD` 58 profiles, `host-02.BDD` 57, both 80 gates, name and directory the requested ones). The 2026-10-23 block (4677 × 96, resolution 0.6167 mm) stands as history |
| 13 | Pick a stored file / refresh the file list | menu entry, then dialog | **absent** | no message-route implementation; likely the same `Sender` unknown |
| 14 | Answer an unexpected prompt (warning, overwrite, directory) | a coordinate guess — unsafe, withdrawn | **absent** | policy decision needed before any implementation: the message route should refuse and report rather than guess |
| 15 | Close the application | window close | **absent** | untested; `WM_CLOSE` is the obvious candidate |
| 17 | Keep the operator's pointer usable while a popup is open | nothing — the operator lived with it | **works** | the application confines the cursor to its dialog's rect (`ClipCursor`), which is desktop-wide. A guard releases it and restores the cursor: measured on the store dialog, one clip seen at exactly the dialog's rect, one release that took effect, the application did not re-apply it, and the cursor returned to where the operator left it |
| 16 | Compose and run a campaign from stored points | package code; the guarded cycle is selectable on `point`/`sweep` only | **partial** | the composition exists and is measured: `RoutineCycle` composes record/stop/store/name/commit with the refusals a run needs, `BridgeActuator` prefers it to a host dispatch, and two live points at differing resolutions each returned their artifact from the package and decoded to the geometry they asked for. A command asks for the hardened cycle with `--route bridge --bridge-guarded-cycle` on `point` and `sweep`, and as of 2026-10-26 a real host implements the export: [`tools/live/bridge_host`](../../tools/live/bridge_host/README.md) plus a machine-local producer, exercised live twice through `point` (rows 11 and 12). What is still missing for this row: `sweep` and `campaign` have not been run through the guarded route, and `campaign` in `cli.py` still builds `live.live_actuator(...)` with no route flag at all. Partial, and the remaining gap is now the multi-point composition rather than the single cycle. |
| 18 | Clear the block before a recording (the fresh-block boundary) | press the strip's clear-and-restart | **partial** | the boundary is composed and verified in package code: `SweepRunner._reset_block` requires the empty `READY` view and refuses with a reason on every failure path. The application-side act is a `CLEAR_AND_RESTART` press inside it, and no clear-and-restart command code is measured — only 28 (record/stop) and 29 (store). It exists only in the runner; `live.point` has no boundary on either route (`recording.py`'s cycle presses `NEW_ACQUISITION` only to dismiss a leftover store view). Added 2026-10-26; the press is input debt, so this row also blocks any claim that a bridge cycle is free of input |

### Selected next

**Current execution (owner-selected 2026-10-27).** The regular host-integration slice below is complete. The bounded
[finite background multiplexed recording plan](background-multiplex-recording.md) now owns implementation, live acceptance,
restoration and the next checkpoint. Owner renewed bounded live tests on 2026-10-27 with no active multiplexing left behind. A retained caller and disabled-mode flag/count/first-channel prototypes have bounded live proof. Routing recovery is adjudicated; channel-4 configuration and channel-10 gain restoration remain open. Owner directed commit/continuation on 2026-10-28 using offline delegation and coordinator-only live tests; participant composition and verified finite finish remain open. This document remains the per-action capability register and historical evidence;
do not restart the completed regular-recording slice or expand the multiplexed trial into general hardening.

**Measured live through the assembled route (2026-10-26, owner-granted sitting).** Two consecutive 2 s points were
recorded and stored through `point --route bridge --bridge-guarded-cycle` against the running instrument-mode
application, with the producer adapter as the only machine-local part: `host-01.BDD` (37,189 bytes, 58 profiles) and
`host-02.BDD` (37,090 bytes, 57 profiles). Each decodes to one axial-velocity stream of 80 gates whose words match the
column before the run (4000 kHz, PRF 600 us, 0.740 mm, emissions 50, burst 4, sensitivity `high`), and each stored span
is its own window (2.299 s, 2.259 s) at the measured 40.3 ms period rather than a stale buffer. A passive
`activate.py` preflight passed every check beforehand (config, store directory, producer, table operations, composed
menu dispatch, binding, strip). **What this establishes:** record, stop, store and the Store-dialog commit run through
the application's own routines from a command, without the operator, and the binding is re-observed per command rather
than reused from a file. **What it does not:** the transducers were disconnected, so the files carry configuration,
timing and storage evidence and no signal claim; `sweep`/`campaign` were not exercised; the Store dialog's accept and
any fresh-block reset remain presses; and one producer-attach lifetime is capped at 60 s, so the whole cycle has to fit
inside it. Two integration facts cost a run each and are now written into the host protocol: the demonstrated chain
proves its dispatch boundary on one posted operation before it will honour any command (without it the record is
refused as `Dispatch boundary changed`), and the host config is read as the table's sibling, so a per-point producer
command means a per-point table directory.

**Selected bounded implementation (owner-authorized 2026-10-26).** Reuse the demonstrated producer to supply the real
guarded host adapter and Store-dialog seam behind the existing point/sweep interface; do not redesign the bridge or add
flags already present. One editor owns that integration and focused offline tests; a separate worker inventories
multiplexed control gaps, with mixed-frequency analysis time-boxed. The coordinator owns live observation, binding,
restoration and integration acceptance. Before any mutation, resolve the actual current-instance identity and owner and
verify that restoration has an executable route. Stop at either a decoded, uniquely named sensorless recording through
the assembled public path with verified restoration, or a concrete named runtime blocker. Do not expand to full control
mapping, generic hardening or a mixed-frequency bypass.

**Current position (2026-10-26).** The identity/state contract, the host factory and the `point`/`sweep` selection are
**implemented, offline-verified, independently reviewed and closure-reviewed** (see *Current checkpoint*) — locally committed
at `29cbd0a`, but
not published or deployed. **Verified live on 2026-10-26**: the capability the register is really about, recording and storing
through the message route in a fresh instance, now works from a command — two points stored and decoded, with reliable
current-owner observation (re-taken per command) and a real host provider in `tools/live/bridge_host`. What was not
exercised live: `sweep`, `campaign`, multiplexing and the transducers themselves. The dated entries below are the
evidence and decisions behind that position, not a queue: each one that states a next action since done or overtaken carries
a dated note saying so.

**The offline slice selected on 2026-10-26 is complete — history.** It asked for three things and each is in place: a
binding carrying `pid` + `created_ns` + the table's build digest and the source of every observation, refused by name before
the first call on an unknown instance, a changed pid or creation time, a changed build, or a null/unmapped pointer
(`cycle.ProcessIdentity` / `CycleBinding`, and `RoutineCycle.configuration_problem` with its identity and owner checks); a
factory in the pattern of `live.bridge_dispatch` plus a `point`/`sweep` flag that refuses rather than silently taking the
press dispatch (`bridge.guarded_cycle_from`, the `bridge_actuator` selection in `live.py`, the `cli.py` route arguments);
and a cycle that confirms its own transitions and returns a typed `CycleReport` on every exit (`RoutineCycle.try_record_and_store`).
Its stopping condition was met: every pre-call identity refusal has a test that also asserts `caller.calls == []`, a failure
after record or stop began is asserted at its stage and never as an empty call list, the happy path runs on its own identity,
the existing cycle tests are unchanged in meaning, and a scoped `ruff check` passed. What a real identity reader still needs
is an observation taken on the running instance — the one thing this slice could not do.

**Continuation completed locally (owner-authorized 2026-10-26).** The requested readiness slice is committed at
`429597f`, with the offline evidence above. The following records its grant, not a new implementation queue.
The guarded-cycle implementation is locally committed at `29cbd0a`; publication is not authorized. Its continuation was the bounded
**offline readiness/error-guard slice**: prevent UI and bridge single-point cycles and preflight from proceeding past an
application error, share the runner's refusal semantics, and test the real top-level-reader boundary with injected Windows
APIs. An unreadable check must not become a clear screen. Acceptance: a known error or unreadable check yields a named
refusal before channel/configuration changes, overlay handling, routine calls or presses; clear/legacy paths remain
compatible; scoped tests and the acquisition/bridge gate are run, with baseline failures attributed. No live calls,
private host/configuration changes, pushes or guard weakening are selected. Other offline findings remain unselected.

**Subsequent live direction, proposed and not a grant.** With the contract closed, the next live work needs an instrument, so it is proposed
rather than selected. The bounded entry-point readiness guard is now implemented and offline-verified; standalone
channel/column coverage and the other dispositions below are not silently included. Next, propose a supervised session that
**observes the owning object on the current
instance**, allowing one operator-assisted foreground setup per session, and captures it with the process id, creation
time and build digest in one reading, through the host
`guarded_cycle` export, so that the package's own checks accept a cycle the factory actually bound. Only after that a live
mutating validation of the guarded cycle — record, stop, store — under the plan's existing authorization for building and
measuring the message route, with the Store dialog's `Accept` still a press. No part of this is authorized by the
2026-10-26 offline slice.

**Needing a supervised live session, not a person.** Owner observation is not inherently manual: the measurement recorded
above primed the object by changing a combo entry and restoring it, so the application called its own setter and the widget's
owner could be read — a probe can do that, and nothing about it requires someone touching the application. What this trial
excluded is live work of any kind, so the observation needs a session with an applicable supervised live grant, and that run
must capture the pointer, the process id, its creation time and the build digest together or the binding cannot be checked
later. The plan's authorization withholds unattended Store mutation, relaxing a guard, and editing machine-local binding
material; a restart or a re-prime belongs to that live session's own grant, and a process that faulted inside a UI routine is
not a state to record in.

**Durable findings the register's rows do not carry.** `--bridge-numeric-writes` is inert on the commands that carry it:
`apply_point` is delegated to the inner actuator through `BridgeActuator.__getattr__`, whose `apply_point` in `driver.py`
calls its own `write_parameter`, so `BridgeActuator.write_parameter` is never reached. A campaign that carried a cycle would
compute its size expectation without the allowance `live.sweep` sets on the runner — a wiring and validation gap whose
effect depends on window, profile count and container, not a proven refusal. The former runner-only application-error
gap is closed for UI/bridge points and preflight at `429597f`; standalone channel/column commands were not included.

**Offline findings and their disposition.** The bounded error guard is completed; other findings remain unselected:
the five fake-driver/session-0 suite failures (**DEFERRED** — the established baseline, unrelated to this
slice); the numeric-write composition above (**UNSELECTED** — `--bridge-numeric-writes` stays inert until a caller needs
it); the single-point application-error guard (**IMPLEMENTED AND OFFLINE-VERIFIED** at `429597f`); the campaign
route/window wiring (**UNSELECTED** — `campaign` has no route flag and would compute its size expectation without the
sweep's allowance); and the review's input-name and link/symlink policy (**DEFERRED** — no implementation decision taken).
Cosmetic, and also **DEFERRED with no code change**: `RoutineCycle`, `CycleBinding`, `ProcessIdentity`, `ObservedAddress`
and `CycleReport` are not re-exported from `acquire/__init__.py` although the factory types are, so a host factory imports
`acquire.cycle` directly.

**The size verdict is a decision for the owner, not a patch (2026-10-24).** Making the decode the verdict and the size an
advisory was tried and reverted: it failed five pinned tests, and two of them matter — a `leftover` and a `truncated`
fixture that *decode cleanly* and were caught by size alone. So the change is not a tidy-up of a mislabelled check; it
removes the only thing standing between a stale block and a point reported `OK`, and the buffer finding cuts both ways (size
follows buffer age, so it cannot be trusted to catch staleness either).

The decision therefore needs three things settled before any code moves: whether a leftover block that matches every word
of the request should be accepted (the words include gates, resolution, prf, emissions and channel); whether the timing
certificate already in the record is a better staleness signal than size; and what a caller should see when the only
disagreement is the buffer's age — today it is `INVALID` with a ratio in the reason, which reads as a data fault and is
not one. Nothing in this plan changes that rule until that is answered.

*(2026-10-26: unchanged. The boundary fix recorded below moved **when** the stored block starts; it did not license
weakening this check, so this stays an owner question and is deliberately not part of the proposed slice.)*

**The application crashed, and the crash box is invisible to every guard we have (2026-10-26).** A Delphi access
violation appeared during this session's live work: *"Violation d'accès à l'adresse 007262A6 dans le module 'Udop607_4.exe'.
Lecture de l'adresse 1004FFF8."* — a read through a garbage pointer. The nearest exported symbol below the fault address is
`Uti::Get_No_Block_In_Profile`, i.e. a utility reading a block count through a pointer it was handed.

The consequence was the whole afternoon's failure mode, and it was not obvious: **a message box is a top-level `#32770`
window, not a child of the main form**, so every census in this project — the overlay guard, `EnumChildWindows`, the
layout fingerprint — cannot see it. While it was up, the modal loop's own message filter discarded the posted wake-up, so
every menu call reported `executed: 0` after its full timeout, and every run refused at channel verification with a reason
about focus. Three separate diagnoses were chased before a screen capture showed the box: the guard has no way to say "the
application is showing an error".

What follows from it:

- **The message route must check for top-level dialogs of the target process before anything else**, and report "the
  application is showing a modal error" as its own refusal. This is a named gap, not a theory: the box was visible only to
  a person looking at the screen. *(2026-10-26, later the same day: implemented for the runner's guard in commit
  `9b481d0`, which asks `Win32Actuator.application_error()` before any overlay and refuses with the box's own text. It is
  was then absent from the single-point, preflight, channel and column paths. The later `429597f` continuation gates
  point/preflight entry and recovery, verified offline; standalone channel/column paths remain outside that slice.)*
- **An access violation is a possible outcome of calling routines**, not an exogenous event. The self-injection hazard
  documented for a restarted process applies to any stale or wrong object pointer, and the harness had been passing a
  captured `Self` without validating it.
- The box can be cleared by pressing its own `OK` (measured: `dismiss_crash.py`, one round, application still alive), but a
  process that has faulted inside a UI routine is not a state to record in: after the box was dismissed the strip was no
  longer where the census expects it, and the driver refused on a non-measurement panel at the bottom of the screen.
- **The layout defect is visible, and the operator reported it before any probe found it**: the plot window is drawn *over*
  the status row, so `Block: … / Memory: Filling … / Time between profile … ms` is clipped by the plot's bottom edge
  (screen capture 2026-10-26 12:47, bottom-left region). That is why the bottom-most panel the census resolves is the plot's
  footer rather than the strip. A run must refuse in that state, and it did; the state itself is repaired only by a restart.

**The boundary move is proved (2026-10-26).** Two points through `live.sweep` at 4 s: `uib-k5` **114 profiles, 4.56 s**,
96 gates at 0.6167 mm and `uib-k6` **113 profiles, 4.52 s**, 80 gates at 0.74 mm — both `PointStatus.OK`, both stored, the
whole run 22 s wall clock. Against the same request before the change: 513 profiles spanning 20.657 s, refused at 2.11x, and
62 s per point.

So the window is now the window, and the size signature agrees with it instead of being overridden — no acceptance rule had to
move. Two limits belong beside that result: it was measured on the **UI route** (the application in the foreground), because
after the application's restart no valid owner object could be found (the setter hook captured nothing, `GWLP_USERDATA` is
empty, and a VMT scan found only a module-data false positive) — the boundary is `SweepRunner` code shared by both routes, so
the change is established, but the message route's own record/stop still depends on an owner pointer no reliable discovery
currently produces. And the 0.56 s above the request is the stop-to-store residual. *(Corrected 2026-10-26: that residual
passed the size check through the signature's default factor, not through an overhead allowance — on the UI route no cycle
is supplied, so `live.sweep` sets `window_overhead_s = 0.0` on the runner.)*

**The window framing was wrong: a store writes the application's buffer, not our recording interval (2026-10-24).** The
two-boundary sequence works mechanically — record, stop and store each issued at its own deadline across boundaries
(`pending_command` 28 → 29), the dialog raised and committed, the block written — and its file spans **397.17 s** for a 4 s
window. Profiles run from 0.0 to 397.17 at a 40.3 ms interval, i.e. the whole buffer the application had been filling. So the
~20 s campaign blocks were 20 s of *buffer*, not of window, and the size expectation that looked five times too small was
reading buffer age. The cycle's span limit is therefore withdrawn (span is reported, with an optional ceiling for a caller
that wants one); the runner's size ratio has the same defect and is now the open decision, because a verdict that depends on
when the application's buffer was last cleared is not a verdict. The plan's own principle applies: the decode is the
acceptance.

**Cutting the window overhead — one attempt closed.** The blocking variant is closed: issuing record,
holding the application's GUI thread for 3 s inside the stub, then stop and store produced **no dialog and no file**, because
the application consumes its shared command slot on its own loop and a held loop collapses three commands into the last one
(store, with nothing to store). So the window cannot be defined by blocking.

The variant that spans two boundaries without blocking is now built and measured: `menu_call` takes a per-call deadline
(`due=ms`), re-posts its own wake-up message, and issues each call at the first boundary past its deadline, so three
commands ran in one attachment with the application never blocked. It did not shorten the stored data, because the stored
data is the buffer — see the buffer finding above — and that is the more useful result: the wall-clock cost of a point is
real (~62 s) but the *data* cost is not something the cycle controls.

**Then:** resume and permutation across a longer plan, and the `absent` capabilities (channel selection, file pick,
unexpected prompts), of which channel selection carries a recorded hazard — it restarts the measurement loop.

*(2026-10-26: history. The series part has since run; resume and permutation across a longer plan have not, and channel
selection, file pick and unexpected prompts remain `absent` in the register.)*

**A cycle at scale, and the store directory contract.** Covered operation is established for one point. The next useful
step is the same cycle repeated across a series of points with a parameter change between them — which is where the
numeric-write path (row 8) and the sweep's store-naming have to hold up, and where a failure costs a stored file rather
than a display toggle. Before that, one small contract worth pinning: the store dialog always opens with the *last* name in
its field, so a caller that writes the name must do so before every commit and must never rely on the field being empty.

*(2026-10-26: done. A three-point series ran with the name written before every commit, and `cycle.py` implements that
naming contract. What is open now is owner discovery, not coverage.)*

**Also open, and cheap:** which rows read their registers. The rule is now mechanical — read the handler's body — so the
register's remaining `blocked` rows can be classified without another probe.

*(2026-10-26: partly answered by the disassembly above; classifying the remaining rows that way is unselected work.)*

**The owning object (`Self`) — closed for one instance, open as a capability (reconciled 2026-10-26).** Rows 10, 11, 12
and 7 all reduce to one capability: calling a routine that belongs to some object the dispatcher does not know. Form
methods work because the form is identified; the strip's and the rows' owners are not. The measurement that settles it is
capturing the object pointer the application itself uses when it calls one of these routines, for the *current*
application instance — a binding captured for an earlier instance is stale and must refuse rather than be reused.

*(This paragraph was headed "Closed: the owning object", which reads as a capability that exists. It does not: the object
was captured and used against the pre-restart instance, and after the restart no discovery produced another — row 11 now
says so. "Closed" is true of that instance's binding only.)*

**Stopping condition.** Either a row toggle acts with `allow_real_input=False`, or the control-toggle path is shown not
to act either — in which case row 10 is recorded as blocked by design (three routes measured) and the store's naming
dialog (row 12) is what remains between the message route and an unattended recording.

*(2026-10-26: superseded as the selected objective; the slice's stopping condition at the top of this section governs rows
11 and 12 now. The text is kept because it records what was being asked before the restart.)*

**Before starting, read the two closed routes** in *Current checkpoint*: a recorded object pointer is stale by
construction, and the class signature does not find a live instance. Do not re-run either scan. The instrumentation step
is the one that has to work, and its failure mode is recorded there too: the runner reaches its own preflight (pid and
seven fast-access roles read) and then dies in the instrumentation step with a file-not-found from its process spawn and
an empty output file.

## Decisions and evidence

- **2026-10-23 — the old system is kept.** Owner direction: do not retire UI emulation; keep building the message route
  alongside it. Consequence: the register is a to-do list, not a countdown, and no row's removal is implied by another
  row's completion.
- **2026-10-23 — a "bridge" run that presses is not a message-route run.** The route wrapper still delegates the
  record/stop/store cycle to a machine-local runner that presses strip buttons, and repairs a mismatched numeric write
  through the UI. Both are recorded here as debt against rows 8, 11 and 12 rather than being counted as message-route
  capability.
- **2026-10-23 — coverage is not the question.** Focus, occlusion and minimisation were measured and withdrawn as
  explanations: an inactive window ignores input regardless of coverage, a minimised one paints nothing, and real input
  cannot be injected here at all. The message route's limits are about objects and routines, not about focus.
- **2026-10-23 — disassembly beat trial, again.** Three act-paths were tried on a row before its handler was read; the
  read showed the objects were irrelevant and the test was malformed. For a handler whose effect is invisible, read the
  code before designing the probe: an attach costs twenty seconds, and three of them taught less than one decompile.
- **2026-10-23 — which bit is which.** `display_flags` bit 1 is the **vertical** grids, established by the operator
  clicking that row and watching the value go 2 → 0. Earlier work in this effort called it horizontal; that reading was
  wrong, and any note that relies on it should be corrected rather than inherited.
- **2026-10-23 — a withdrawn claim.** Presses were reported as working with the application in front (`display_flags`
  2→0 and 0→2). Four mechanisms on the same row, cursor teleported onto it, application in front, reproduced nothing.
  The earlier observation is not used as evidence anywhere in this plan.
- **2026-10-23 — the environment's own constants.** A sweep's constants must be the instrument's own: points planned from
  another experiment's values (1460 m/s, PRF 212) were stored and then reported `INVALID` naming depth, sound speed and
  PRF, so a stored-then-refused point is the decoder working. The column command selects combos by exact text and treats
  the TGC mode as a separate step, because accepting a TGC mode resets the receiver settings beside it.
- **2026-10-26 — a classification correction, not a new rule.** A posted press on a modal's `Accept` was already input
  under criterion 4, which no row may read around; applying that rule as written downgrades rows 7 and 12 from `works` and
  adds row 18 for the fresh-block press. No row was promoted, and no owner decision was taken: the alternative — letting a
  modal make a press message-level — would have been a change of definition to fit the code.
- **2026-10-26 — the slice was offline by this trial's terms.** Evidence and build fixes with independent review: no live
  action, no application restart, no commit or push, no binding, secret or machine-local configuration change. The plan's
  own authorization (building and measuring the message route) is wider and unchanged; a later live step is taken under
  that grant, in its own session, not under this one. Neither a restart nor a re-prime was attempted offline — the driver
  refuses to record from a state whose strip the census no longer resolves — and whether a later session automates
  discovery is its own question, not something this trial settled.

- **2026-10-26 — verified offline is not accepted.** The guarded cycle's contract, factory and `point`/`sweep` selection
  are implemented, pass the scoped suite and two reviews, and are still uncommitted, unpublished, undeployed and unobserved
  live. The effort therefore stays *in progress* at that checkpoint, and what it is missing is a capability — reliable owner
  observation on the current instance, and a production host provider that implements the factory — rather than permission. A
  supervised grant is a precondition of the next live step, not the reason the step is blocked.

## Next session

**Objective (owner correction, 2026-10-26).** Start from the demonstrated background action set and pointer guard.
Identify the exact gap between that working path and usable regular/multiplexed recording commands; distinguish packaging
and current-session binding from genuinely missing controls or application restrictions. Do not select another background
feasibility demonstration or open-ended hardening round. One-time binding is acceptable; automatic rebinding is not a first
delivery gate. New implementation, live observation, Store mutation and private-provider changes need applicable scope/grants.

**First action.** Read *Current checkpoint*, *Selected next* and the
[guarded-cycle contract](../dop3000/guarded-cycle-contract.md), then register rows 7, 11, 12, 16 and 18 in that order.
Preserve source checkpoints `29cbd0a` and `429597f` and the unrelated untracked worktree directory.
Do not re-run the two closed routes in *Selected next*: a pointer captured on the previous application instance is
stale, and the class signature does not find a live form. A valid current-instance binding may be reused for its session.

**Stopping condition.** Do not repeat the closed offline slices. Stop before live observation, instrumentation, restart,
Store mutation or private-provider changes without an applicable grant and a concrete execution component. A proposed
binding session must produce a current-instance binding the package accepts or a named refusal, never guessed pointers.
Its provider and the GUI half must target the same instance; offline fakes do not establish that live join.

**Previous objective, kept as history (2026-10-23).** Capture the owning object the running instance uses for a strip
routine, then call `record` and `stop` with `allow_real_input=False`, first re-measuring the baseline. Attempted and not
achieved after the restart: the measurement is in *Selected next*, the capability is row 11.
