# Message-route port: what still has to move off input emulation

**Task plan.** Written 2026-10-23. **State:** in progress.

## Destination

**Purpose.** The acquisition package now has two ways to drive the instrument application: the **UI route**, which
emulates an operator (hover, press, dialog typing), and the **message route**, which reads window state and calls the
application's own routines in-process. The message route is the one we are building on: it needs no cursor, works while
the application is unfocused or covered, and leaves a record of what it asked for. This plan keeps that construction
honest by naming, action by action, what the message route can already do and what it still borrows from input.

**Observable outcome / acceptance criteria.**

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
- Anything to do with the instrument's measurement physics, campaigns or experiment definitions.

**Authorization boundaries.** The owner authorised continued construction on the message route and asked for this
register so it is discoverable at session start (2026-10-23). That covers: building, measuring and documenting the
message route; committing to this branch, never pushing. It does not cover unattended mutation of the instrument's Store,
relaxing a safety guard, or editing the machine-local binding material, each of which needs a fresh, explicit grant.

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

**Not established.** Whether the application's own strip routines (`record`, `stop`, `store`) can be called at all: a
call without the owning object faults. Whether a row's `…Change_State` handler can be made to act: it runs without error
and changes nothing, because its `Sender` is not supplied. Whether a numeric write can be made repeatable. Whether
channel selection can leave input emulation at all — the old route itself is unsafe there.

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

**Working state / recovery needs.** The UI route's record runner is machine-local scratch and is not part of the package;
a run through `--route bridge` today delegates its record/stop/store cycle to it, so a "bridge" run is not yet free of
input. Nothing in the package is mid-write; the tree is clean apart from this plan.

## Remaining work

### The port register

Statuses are claims about the **message route only**. `works` = no input of any kind. `partial` = the message route does
part of it and input does the rest. `blocked` = the message route cannot do it yet, with the blocker named as a
capability. `absent` = no message-route implementation exists.

| # | Action | How it is done today | Message route | Blocker / evidence |
|---|---|---|---|---|
| 1 | Read a fast-access parameter | input on the value button, then read the dialog | **works** | `read_parameter` by window message; 7 roles read with `allow_real_input=False` |
| 2 | Read the whole parameter set | same as 1, repeated | **works** | `main` block of the same read; used by the preflight |
| 3 | Read the sidebar column, channel identity, strip state | screen reading by a human | **works** | `WM_GETTEXT` on the column's edits; strip state from the control |
| 4 | Read a dialog's fields | reading the dialog by eye | **works** | dialog opened by dispatch, fields read by message |
| 5 | Select `Sensitivity` / `Emitting power` by text | click, then keyboard arrows | **works** | `select_by_text` + read-back after a settle; drift regression covered by a test |
| 6 | Select the TGC mode | Tools → Define TGC → mode list → Accept, by hand | **partial** | mode **selection** is message-level; the dialog's `Accept` is still a press |
| 7 | Accept / cancel a dialog | click | **blocked** | dialog buttons are pressed; whether their handlers can be called with a `Sender` is the same unknown as row 10 |
| 8 | Write a numeric parameter (`us_frequency_khz`, `prf_us`, `gates`, `resolution_mm`, `emissions_per_profile`, `doppler_angle_deg`) | click the value, type, Accept | **partial** | setter commits once; not repeatable in a fresh attach; today's mismatch repair is a UI write, which this plan treats as input |
| 9 | Choose / enable a measurement channel | press the channel cell | **absent** | not attempted in the message route; the old route restarts the measurement loop and is the path that failed at the device layer |
| 10 | Activate a menu row (grids, persistence, filters, assisted mode, record options) | hover the menu bar, press the row | **works** | calling the row's handler directly moves the application's own flag: the horizontal-grids row took `display_flags` 0 → 2 and the vertical-grids row 2 → 0, in one attach, with no objects, no input and no cursor. The handler's body does not read `Self` or `Sender` at all — it stores them and ignores them, then acts on the flags slot, closes the menu and requests a redraw. Rows whose handler *does* read those registers are untested |
| 11 | Start / stop a recording | press the strip | **works** | with the primed owning object supplied, the routine executes (`ok`, `executed: 1`, no errors) and the strip's own state changes: `recording` → `store` |
| 12 | Store a recorded block | press the strip, name it in a dialog | **blocked** | the routine call reaches the strip's `store` state, so only the naming step remains — and that is a dialog (row 7) |
| 13 | Pick a stored file / refresh the file list | menu entry, then dialog | **absent** | no message-route implementation; likely the same `Sender` unknown |
| 14 | Answer an unexpected prompt (warning, overwrite, directory) | a coordinate guess — unsafe, withdrawn | **absent** | policy decision needed before any implementation: the message route should refuse and report rather than guess |
| 15 | Close the application | window close | **absent** | untested; `WM_CLOSE` is the obvious candidate |
| 16 | Compose and run a campaign from stored points | package code, UI route for the per-point cycle | **partial** | the composition and verification are already message-level; the cycle is row 11–12 |

### Selected next

**The store step, which is now the only thing between the message route and a full cycle.** Rows work, record and stop
work; what remains for an unattended recording is the naming dialog that the store step ends in, and whether a dialog
button's handler reads its `Sender` (the same question this round answered for rows, and answered the same way it should
be answered — by reading the handler, not by guessing).

**Also open, and cheap:** which rows read their registers. The rule is now mechanical — read the handler's body — so the
register's remaining `blocked` rows can be classified without another probe.

**Closed: the owning object (`Self`).** Rows 10, 11, 12 and 7 all reduce to one capability: calling a routine
that belongs to some object the dispatcher does not know. Form methods work because the form is identified; the strip's
and the rows' owners are not. The measurement that settles it is capturing the object pointer the application itself
uses when it calls one of these routines, for the *current* application instance — a binding captured for an earlier
instance is stale and must refuse rather than be reused.

**Stopping condition.** Either a row toggle acts with `allow_real_input=False`, or the control-toggle path is shown not
to act either — in which case row 10 is recorded as blocked by design (three routes measured) and the store's naming
dialog (row 12) is what remains between the message route and an unattended recording.

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

## Next session

**Objective.** Capture, for the running instance, the owning object the application uses when it invokes a strip routine,
then call `record` and `stop` through the message route with `allow_real_input=False`.

**First action.** Read this plan, then the register's rows 10–12; re-measure the baseline (application instance, strip
state, that the message route still reads state with no input) before touching anything.

**Stopping condition.** As in *Selected next* above. Record the outcome in the register even when it is a refusal: a row
that is blocked by design is a result.
