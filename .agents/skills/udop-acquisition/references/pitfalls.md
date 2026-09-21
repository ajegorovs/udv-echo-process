# Pitfalls — the failure modes this class of application produces, and the rule each one forces

## Pitfalls

- **`GetWindowText` reads nothing from another process — use `WM_GETTEXT` (via the driver's own text
  reader).** A reconnaissance probe that used `GetWindowText` over this application's whole tree saw
  empty captions everywhere and concluded that the pre-created hidden panels state nothing; with
  `WM_GETTEXT` the same panels state `1460`, `2`, `4`, `212`, `150`, `4000`, `797`, `0.122`… — they had been
  stating the instrument's whole parameter set the entire time. The same API also decides *identity*:
  these widgets carry no caption under either reader (measured, including the five menu entries), which
  is why every binding in this driver is structural and positional, never by name.
  **`GetWindowText` is not a caption test — it cannot read across processes:** for a window owned by
  another process it returns `""` for *every* control, caption or not, so an empty read taken with it
  is evidence of nothing, and a whole-tree dump built on `win32gui.GetWindowText` reported no
  text anywhere while re-reading the same controls through
  `WM_GETTEXT` (`SendMessage`) returned all of them. Read text through the same message the driver
  uses, and only then believe that a widget carries no caption.
- **A value can live one level inside the wrapper drawn for it, and "it stated nothing" is not the
  same as "the read failed".** Some toolkits build a dialog as a row-per-value grid of wrapper
  buttons and put each value in the control *inside* its wrapper — the `Operating parameters`
  dialog's 21 **direct** children are its 15 `TSp_Value_Button` widgets, its
  header and its bottom buttons, and not one of them states a value: each field's text lives in the
  `TSp_Edit` or `TComboBox` *inside* its value button — so a
  reader written against the
  parent's direct children then finds no values anywhere and refuses with a state rather than a
  cause — walk the surface live (child → next → recurse) when the values are nested, and print the
  **child count by class** in
  the failure path, because that count is what turns a refusal into a diagnosis — and it is what
  turned a refusal into a cause here. And once a setting
  has a supported read path, a read that fails must **refuse** the run rather than quietly degrade to
  "declared": a fact you can read and did not is not a passed check, while a setting nothing in the
  driver can read is carried as unproven. Keep those two states distinct in the record — they have
  different execution consequences. Recipe: `references/control-id-mapping.md` §9.
- **Bind by a role resolved at run time — never by caption, and not by a stored `control_id`.**
  Owner-drawn toolkits (Delphi/VCL `TCustomControl` descendants, MFC owner-draw,
  accessible-disabled Qt) return **empty window text** for buttons and menu items, and UI
  Automation exposes them as bare `Pane` with no name, so a name/title lookup silently matches
  nothing — or matches a different widget. Ids are no better across launches: they are
  per-instance handles, so an id-keyed map is valid only inside the process that captured it and
  turns into "every required control is missing" after a restart. Bind `class` + containing panel
  + order, and resolve to a handle at run time.
- **Resolve the process from the window, not from the executable path.** Several instances of one
  exe can run at once — a launcher stub or a leftover owning **zero** windows alongside the real
  app — and `Application(backend="win32").connect(path="App.exe")` can bind to the windowless one.
  Every later lookup then raises `ElementNotFoundError`, which reads exactly like "the app is not
  running" or "the app hung during startup". Enumerate top-level windows of the target class
  across **all** processes, prefer the visible then the largest one, then `connect(process=pid)`
  plus `app.window(handle=hwnd)`, and print the rejected candidates so a wrong pick is visible.
  **Rule out the tuple-order mistake before believing in a windowless sibling:**
  `win32process.GetWindowThreadProcessId` returns **`(threadId, processId)` — thread first**,
  despite the name. Taking element 0 as the pid makes the real app look like a windowless second
  instance: `OpenProcess` fails with `ERROR_INVALID_PARAMETER` (87), the image name reads as
  unknown, `connect(process=<thread id>)` raises `ProcessNotFoundError`, and a scan for "windows
  owned by that pid" correctly finds none. A windowless process can also be real (a launcher stub,
  a leftover from a crashed run) — but both look identical, so check the cheap hypothesis first.
- **A control's id is not its function.** State-machine UIs relabel *and* relocate the same id:
  one record toggle sat mid-triplet as "Record" while stopped-with-data and in the leftmost slot
  as "Stop" while recording, with its sibling widgets appearing only in the first state. Capture
  each state once before designing the sequence, address every widget by a rectangle resolved at
  the moment of the action, treat *which widgets exist* as the state signal, and record
  state-dependent bindings with their per-state meaning instead of deleting them.
- **Never truncate a script's stdout with `head`/`sed`/`tail` when it writes artifacts at exit.**
  Closing the pipe raises in the child, which dies before its final write, so the JSON, screenshot
  or state file the next step depends on is simply absent — and the symptom looks like a bug in
  the script. Redirect to a log file and read the file.
- **Deduplicate the control tree by window handle before you count or reason.** These toolkits
  report the same owner-drawn widget as a child of several parents; a naive recursive walk
  inflated one window from 43 to 635 controls and duplicated every id.
- **Control ids repeat across hidden pages, tabs and panels.** Scope every lookup to the
  visible top-level window and require `is_visible()` plus a non-empty rectangle before
  accepting a match, or you will silently drive the widget on a hidden page.
- **Capture with `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT=0x2)`, not a screen-region grab.**
  A region grab returns whatever window is stacked on top, while `PrintWindow` renders the
  target's own pixels with no focus steal and no z-order change. **A window that is not realised
  — or that is hidden (`IsWindowVisible` false, e.g. the app is sitting on its startup dialog) —
  comes back pure black even through `PrintWindow`.** Wait for visibility, not existence, before
  capturing or binding, and read an all-black capture as "not visible yet", never as "nothing to
  see here". Do **not** use `PrintWindow`'s return value as the check: `TRUE` accompanied a 44–49 %
  black image from one copy of a grab routine while another copy of the same code gave 3.8 % black
  on the same window. Keep exactly one capture implementation per project and assert the black
  fraction before reading any text off a capture.
- **Never hard-code absolute screen coordinates.** Re-resolve rectangles from the window handle
  each run; express any fallback coordinates relative to the window origin.
- **Compute image coordinates as `image = screen - window_origin`.** That single line is what
  lets a label read off a capture be bound numerically to a control id.
- **Setting one parameter can make the app recompute others — so write order inside a parameter set
  is part of the spec, and the derived field goes last.** Assisted/auto modes adjust coupled fields
  (depth ranges, derived counts, resolution). Measured: writing gate count *then* resolution let the
  resolution write recompute the gate count and silently trim it (805 requested -> 474 accepted, depth
  59 mm against a 100 mm target); writing resolution *then* gate count applied the full request and hit
  the target exactly. Re-read **all** fields of the set once it is written — including ones you never wrote — and do that
  *before* the irreversible step it feeds (the recording, the store, the upload), so a clamped point
  costs a read-back instead of a wasted run and a junk artefact. **Expect the recomputation to be
  one-way, and that is what makes it dangerous for a sweep:** measured on a dialog, every commit of a
  volume knob re-derived the depth-window knob (a floor that grows with the other setting) and no later
  write of the volume could put it back, so a sweep of that single knob would have silently moved a fact
  the plan compared elsewhere — the pre-run fixed-fact check was the only thing that caught it. The app's recomputation is silent but lands in
  the control text, so assert on the read-back, never on the request.
- **Continuous-acquisition apps advance their own counters regardless of what you ask.**
  "Is it done?" must key off a specific control value or a file event — never a blanket wait on
  the screen as a whole.
- **Never fixed sleeps.** Poll for the artifact with a stability window (size unchanged across
  consecutive reads) and derive the timeout from the currently set parameters, so a 5-second
  measurement does not cost 30 seconds of dead time and a 40-second one is not cut off.
- **Index the channel/segment that actually measured before verifying against the artifact.**
  A fixed-layout per-channel block read *without* a channel selector returns a stale but
  plausible configuration — two unrelated recordings can carry byte-identical unused
  first-channel tables, so the numbers look right and are not. Read the block for the channel the
  run used, and treat a block that matches across unrelated files as a leftover, not a
  measurement.
- **Watch liveness, not elapsed time.** Legacy hardware apps lose their link mid-run (driver
  errors buried in the app's own log file, recordings named after crashes). Poll a heartbeat the
  UI already shows, and design detection + restart + resume before the first unattended run.
- **Read a stale or dirty clone out of git objects** (`git show origin/master:<path>`) instead
  of force-pulling. A force pull destroys uncommitted work, and reconnaissance usually needs two
  files, not the whole tree. Full sync procedure (three-way classification, backup branch,
  parked work): see the `safe-git-sync` skill.
- **Expect silent clamping, not an error.** Out-of-range writes come back changed, or the app
  reduces a value to satisfy a constraint it never reports (a gate count of 10 landing on 9
  because the pitch left no room in the reproducible depth; 1001 landing on 1000). Always read
  back, and distinguish *reduced* from *refused*: a refusal leaves the field at its previous
  value, a clamp moves it to a different one. **A refusal is announced by a modal whose affirmative
  button is a dismissal, not a repair:** measured, a below-floor request raised a warning naming the
  other knob with a single `Continue`, and Continue left the field holding the value from **before** the
  attempt (the remembered one), not the value the application would have derived from the current
  settings. So a refusal costs no write: read the field back, refuse the point, and never read that
  button as applying anything.
- **Specify a measurement point by wall-clock duration, never by acquired-frame count, and treat the
  frame period as an input constraint.** The physics under observation is time-dependent: a point is a
  fixed observation window, and defining it in frames makes that window drift with every parameter that
  shifts the frame rate — measured, one app's profile period is set by emission count, PRF, depth and
  sound speed, so "1000 frames" is ~20 ms in one configuration and ~26 ms in another and the points stop
  being comparable. Derive the count (`duration / period`) only to size a buffer cap and to sanity-check
  the artefact. Conversely the *period* is what constrains the parameter matrix: pin it as a target,
  read the app's own achieved period per point, log target vs achieved, and treat a point that drifts
  off target as a matrix violation rather than a pass.
- **Hold the other knobs fixed when probing a limit.** A limit measured while another knob sits
  at whatever the previous scan left behind measures that combination, not the limit — it will
  read as a capability the app does not have.
- **Set `argtypes`/`restype` before sending any message that carries a buffer.** With a bare
  `ctypes.windll.user32.SendMessageW(hwnd, msg, wparam, lparam)` the default prototypes take 32-bit
  ints, so a 64-bit buffer address raises `OverflowError: int too long to convert` — or truncates
  silently. Declare `[c_void_p, c_uint, c_size_t, c_void_p]` with a `c_ssize_t` return once per
  process and route every handle and pointer through it.
- **Send cross-thread with `SendMessageTimeout`, not a bare `SendMessage`.** A plain blocking send to a
  busy target thread never returns and takes the caller with it — measured as an unattended run that
  hung with no output and a timeout exit while the target was mid-repaint, which reads as a wedged app
  rather than a wedged caller. Pass a short timeout and treat 0 as *busy* — retry or fail loudly — and
  keep the posted path (`PostMessage`) for anything that need not wait for an answer.
- **Dispatch a GUI probe by polling its own log, never by sleeping after the start.**
  `schtasks /run && sleep 120 && cat log` makes the tool-call timer show *your* sleep, not the
  run: a probe that finished in 24 s reads as a two-minute stall, and the operator watching the
  screen has no way to tell the two apart. Write the probe's closing marker into its log and poll
  for it (2 s steps, a hard cap, print the log either way) — the call then returns when the run
  returns, and a genuine hang is legible as a timeout instead of hidden inside the wait. **And read
  the payload's reported status, not the wrapper's exit code:** a dispatcher that prints its child's
  outcome (`=== exit=2 ===`) still exits 0 itself, so a follow-up step gated on the wrapper's status
  treats every refusal as a success. Gate on the printed status line, or make the wrapper propagate
  the child's code — and check which of the two you are reading before you branch on it. **And confirm the probe actually
  started before believing anything about how long it takes:** a dispatcher that takes a bare probe *name*
silently ignores a path-shaped argument — it joins the argument onto its probe directory, finds nothing,
prints nothing and writes no log — so the poller waits out its whole budget and an empty output file reads
exactly like a slow run. Measured: two "probe runs" that never ran, one of them reported to the operator as
slowness, and the read that was supposed to establish a baseline never happened. Check the invocation form
against the dispatcher's own usage, and look for the run's first marker line before drawing any conclusion
from elapsed time.
- **A documented input rule is only as good as the context it was measured in — A/B it on the live
  widget.** "The strip ignores posted messages" was measured with an *instant* posted click (both
  messages in the same millisecond); a posted press **held** ~180 ms works fine, and a real
  `SetCursorPos` + `mouse_event` down/up changes nothing on that strip at all. Both readings were
  true in their own context, and porting the wrong one cost a live cycle. When a reference's note
  and the working code disagree, A/B both gestures on the same control in one run and believe the
  measurement — the code that worked is usually right about *this* widget.
- **Never walk down a menu's entries to recover from a failed press: press the one you mean, once.**
  A menu's entries are different actions, not variations of one. The manual's rule for that
  instrument: the second entry of a `Parameters` menu (`Default parameters`) *selects an
  operating mode* — the assisted mode — and the consequence is measured: the mode removes a whole
  sidebar panel, so every later parameter write has no target. (In the case that prompted this,
  stored-file evidence later showed the mode was old per-item configuration and the walk was never
  the cause — it stays removed as a hazard, not as a culprit.) A press that opens
  nothing must fail **with its record**, never try the next entry down: a retry that changes state
  to recover is worse than a failed point.
- **A write can replace the window you are holding — re-resolve after every write.** Measured: a
  combo write on one dialog made the application close that dialog and open a *different* one in its
  place (a narrower panel, new handles, its own combo and its own Cancel/Accept), because the new
  value switched the app into another mode. Every handle taken before the write is then dead: the
  driver's next press went to a window that no longer existed, its "how many buttons does the band
  hold" check reported **zero**, and the dialog was left sitting on the operator's screen with
  nothing able to close it. Re-resolve the surface after any write that changes state, and keep the
  close path re-resolving too (`_close_any_dialog`), so a failure can never strand a modal. The
  reference script did this all along (`find_dialog(resolve()) or dlg` after the combo write) — the
  port had dropped it. **A mode can change the whole screen:** the same write also removed an entire
  sidebar panel (43 visible controls in 4 panels became 21 in 3), so a layout fingerprint is only
  valid for the state it was captured in and a probe that refuses to run on a "dirty" screen can
  refuse to run at all on the mode that dirtied it — keep a separate way in for that state. **A
  per-item selector is also a per-item layout:** the value that replaced the window put the app in
  another mode, and that mode removed an entire sidebar panel (43 visible controls in 4 panels became
  21 in 3). Read the item's mode from the surface the app builds for it (here: a slider only the
  assisted panel carries), record it in the run log, and let the missing surface fail with the *mode*
  named — a sweep that silently has no target is worse than one that refuses. And settle "did my write
  change this state, or reflect it?" with a measurement, never with reasoning: select a *third* item
  and watch whether the state alternates (a toggle would) or stays per-item (it did) — the operator
  raising the suspicion is usually right about the risk and occasionally wrong about the mechanism.
- **Identify dialog buttons by geometry, not by "the bottom row".** Take the bottom-right **pair**
  `Cancel`, then `Accept`/`OK`) and click the left of the two. "Leftmost button of the bottom row"
  hit a *parameter toggle* in a dialog's bottom-left corner (measured) and left the dialog open — so a
  `Cancel` that appears not to work is usually the wrong button, not a click that did not land. **Index
  such a band from the RIGHT**: the pair is the *last two* entries (Accept = `row[-1]`, Cancel = `row[-2]`),
  because a wide band also collects the indicator/toggle buttons painted to the left of the pair
  (measured on one dialog: two 194-px indicators, then an 80-px `Cancel`, then an 80-px `Accept`). A port
  that re-derived this as `row[0]` pressed an indicator and left the dialog open while its own tests —
  written from the same wrong assumption — stayed green; when a port and the reference script disagree on
  an index, the reference wins, and the fake's rows must be re-measured from the live dialog.
  **Do not filter buttons by width either:** two labels in one row measured 134 px and 138 px, four pixels apart,
  so a width band silently picks the neighbour (that mistake pressed a data-loss action instead of
  `Clear and restart` and raised a warning nobody asked for). Identify a button by its **order within
  the view that is currently showing**, re-resolved after every press, since the same position carries
  a different action per state. **Enumeration order is not screen order, and sorting is on you:**
  picking a menu entry by first match in a tree walk pressed the *second* entry instead of the first,
  because the walk happened to visit it first. Sort candidates by screen position (`top`, then `left`)
  before indexing into any list of widgets.
- **A name table indexed over *visible* widgets silently renames its neighbours the moment one is missing.**
  A menubar bound as `ORDER[i]` names the wrong control for every name after an absent item, and these
  buttons carry no text, so nothing in the tree says which name went missing. Measured: an instrument painted
  ten menubar buttons where the reference install paints eleven, so three late names resolved to the wrong
  widget (or to nothing) while the one early name a gesture uses stayed correct — which is exactly why the
  gesture kept working and the defect stayed invisible for as long as it did. Never infer **which** name is
  missing from its position in the order (that inference produced a wrong entry in a committed document);
  bind the item a gesture needs by its own rectangle, and read the rendered labels off a frame.
- **An overlay can *remove* a mapped surface, so its absence is a modality symptom, not a layout drift.**
  Measured: while a settings overlay was up, the record strip was not painted at all — which makes the
  missing strip the cheapest overlay detector on that screen, and makes the recording path fail-safe for the
  same reason (no strip, so nothing for a record press to bind to). Read the absence in that direction: a
  refusal naming the missing surface sends the operator to look at the surface, when the honest sentence is
  that an overlay is up. An overlay that merely *covers* a surface leaves it in the tree; one that replaces
  it takes it out — for a press the two are the same hazard, but only the second is visible as a missing
  role.
- **Filter a panel's children by the panel's own rectangle before counting them as a state signal.**
  These toolkits keep extra children positioned *outside* their parent (measured: two buttons 13 px
  below the strip's bottom edge, never painted until a prompt is active), so a naive count reported 5
  buttons where the screen showed 3 and every "is it in this state?" assertion failed. Those unpainted
  children becoming live is also how you locate a prompt that never gets its own window.
- **Prove each control surface accepts the input you intend, before building a loop around it — and
  vary the RECIPE, not just the target, before calling anything undrivable.** Surfaces differ *inside
  one app*: on one target the menubar needed hover, popup entries and dialog buttons took posted
  clicks, and the record strip took posted clicks **only with the press held ~180 ms** — every instant
  down/up it was given was discarded, so a session spent switching targets
  (widget, parent panel, plot, main window, injected real clicks, single and double) proved nothing at
  all. Before concluding a widget is unreachable: vary hold time, coordinate space (client vs screen)
  and a preceding move; rule out the mundane causes with `IsWindowEnabled`/`WS_DISABLED` and a
  `WindowFromPoint` hit-test at the centre; and enumerate the parent's **entire** child z-order, since
  these panels show and hide button windows per state. Only after that, redesign around a mechanism
  that presses no button (an auto-record/trigger path) — and re-measure on the target build, because
  this is a property of that build's widget, not of the platform.
- **A write recipe that commits on one surface can silently fail on another.** The same app took
  `WM_SETTEXT` + `WM_COMMAND(EN_CHANGE)` + `WM_KEYDOWN`/`WM_KEYUP VK_RETURN` in its **dialog** fields
  (proved by a coupled readout moving 27 -> 14 -> 27) while the identical recipe earns no such proof
  everywhere it is used. So the surface test is **per field family, not per app**: probe the exact
  surface the loop will drive, and confirm each change through something the app *recomputes* or
  *writes out*, never through the control you just wrote. Prefer the surface whose effect is
  verifiable — a dialog with a derived readout beats a field that only echoes text.
- **Before concluding a write did not commit, prove your read-back is reading the right slot.** A
  confident "this surface ignores writes" verdict on the same app turned out to be **wrong** and cost
  a session: the values had been applied where the loop was writing them, while the artefact decoder
  defaulted to a *different* slot (channel / instance / block) and reported an untouched
  configuration — distinctive values "failing" to appear, twice, made it convincing. When a read-back
  disagrees with a write, suspect the reader before the writer: print every candidate slot and state
  which one you compared, then call a surface unwritable. A verification path is a component under
  test like any other, and a wrong read-back is indistinguishable from a refused write.
- **When a load-bearing control refuses every software *recipe* (see the bullet above), do not stall:
  watch while the operator drives.** Run a watcher that samples the control inventory once a second and captures on every
  signature change, ask the operator to perform the sequence at their own pace, and read the trace
  afterwards. Pausing them between steps burns turns and loses the timing evidence (which control
  appears when, and how long the app takes to settle). **This is a reconnaissance technique, never a
deliverable.** A production loop that needs a human step is a failure of the goal, not a partial
success, and the operator will say so plainly — the moment a run depends on their hands, the answer is
to keep hunting recipes (hold time, coordinate space, target surface, a different surface of the same
app) rather than to ship it. Measured: a control written off as undrivable this way was driven by
software the instant its press was held, i.e. the blocker was never real.
- **A posted click ignores modality — check for an overlay before every press.** The message reaches
the window it names even when a modal panel covers it, so a driver will press a button the operator
cannot even see (measured: a press landed on a record strip *behind* an open warning panel). Before
each press, walk the main window's child panels topmost-first (`GW_CHILD` is the top of the z-order),
skip the panels the map already accounts for, and answer any leftover panel that owns bottom buttons
— it is a prompt, and its **left** button is the safe one. Distinguish "the press did nothing" from
"the press did something invisible": verify the state change you expected, not merely the absence of
an error, or a stray confirmation will sit over the surface you are driving
(`scripts/win_find_overlay.py`).
- **Name every artefact uniquely per run, and answer an "already exists" prompt with the safe option.**
A store dialog inherits the previous run's file name, so the second run either overwrites data or
raises a `replace? No/Yes` panel — and a loop with no handler waits in front of it until it reads as
a hang (measured: the modal warning left the app wedged and the next point came up on an unexpected
screen state). Put a run id or timestamp in every name so the collision path is rarely taken, and
still handle it: detect the panel **structurally** — this toolkit reuses one geometry for *all* its
warnings, so position identifies nothing, while "a panel with bottom buttons that is not the dialog I
opened" does — press the safe (left) button, then retry the store under a fresh name. An
unrecognised prompt is one you must not answer blind.
- **Commit a field with a message, never with focus-dependent keystrokes.** `send_keys` and
  `pyautogui` deliver to whichever window currently holds focus — possibly the user's editor.
  Post `WM_KEYDOWN`/`WM_KEYUP` of `VK_RETURN` to the control's own handle instead.
- **A minimized window renders blank and reports no usable rectangles.** Assert not minimized as
  a precondition; read `IsIconic`/`IsZoomed`/`GetDpiForWindow` through `ctypes.windll.user32`,
  because `win32gui` does not expose them.
- **A capture session's mode is a variable of the map.** Mark mode- or licence-dependent
  bindings `required: false` and re-check them on the target instance; a control that exists only
  in the demo build must not silently become a skipped step in a live run.

- **Read a per-channel state without pressing, and never read a mode out of an absence.** The
  channel itself costs a menubar hover (the dialog is the only place it lives), but the channel's
  *mode* does not: the sidebar parameter column exists only for a manual channel, so the
  measurement screen states the mode for free. The half that matters is the other direction —
  when the column is missing, that fact is only evidence of a mode if the screen is actually the
  measurement screen; with a dialog or a popup up, return "not read" and let the caller carry it,
  or a manual channel behind a dialog is refused *naming the mode* instead of the screen. Same
  rule as the one that stops a filtered probe's empty result from being evidence.

- **A dialog can be a child panel of the main window, not a window.** A settings/options dialog
  that never appears in a top-level window enumeration can still be on screen and fully drivable
  (measured: a settings dialog was a `TSp_Panel` inside the main window, owning real
  `TEdit` fields with Browse buttons — and its fields take `WM_SETTEXT` like any other edit; **name
  which surface it was**, because this application's *Store* dialog is that shape and its path is
  exercised, while its `Record settings` surface — the one holding the block cap — has never been opened
  here, and evidence about one surface is not evidence about the other (a retelling that calls the panel
  measured here "Record settings" has swapped one surface for another). Dump
  the **child tree** before concluding that a dialog, or a feature behind it, does not exist, and
  identify such a panel structurally (directly owns an edit plus a browse button) rather than by
  position. A press that seems to do nothing is often exactly this: an `EnumWindows`-based "did a
  window appear?" check returns nothing for a child-panel dialog, so read the outcome from the
  **child tree** and never from a top-level-window count.

- **A legacy app can confine the pointer with `ClipCursor`, which silently kills injected input.**
  Measured: opening a Store dialog clipped the mouse to exactly the dialog's rectangle
  (`GetClipCursor` returned `(676,391)-(1260,721)` for a `584x330` panel) and released it on close.
  While a clip is active, a parked or injected cursor cannot reach anything outside the popup — a
  second, independent reason real clicks fail where message posts succeed, since messages never
  consult the cursor position. Detect it (compare `GetClipCursor` against `GetSystemMetrics(0/1)`)
  before blaming your own input code, prefer messages so a live popup cannot trap the run, and keep
  `ClipCursor(NULL)` as the escape hatch if the app wedges with a clip set. A dialog left open pins
  the *operator's* pointer too, so answering overlays is a courtesy as well as a correctness rule.
  `GetClipCursor` sees only the documented API: a window that "traps the pointer" may instead run a
  low-level mouse hook that snaps it back, which no API query reveals. So test capture
  **behaviourally** — `SetCursorPos` to a point where no dialog is, then read `GetCursorPos` back; a
  position that is not where you put it means the pointer is confined, whatever the mechanism. Run
  that test *after* the interaction of interest, never before, because it moves the cursor and moving
  off a hover menu dismisses the menu you were about to test. Either signal doubles as a free modality
  detector: a live clip means a capturing popup is on screen, so answer it before pressing anything.
- **A modality block can leak, so never argue safety from a captured cursor.** The capture that keeps a popup
  modal is released by a focus change: measured, Alt-Tabbing away from the application and back freed the
  pointer, after which other menus opened and more than one overlay could be up at once. Two consequences.
  The guard is the overlay's **presence** check, never the capture, so no safety argument may rest on "the
  mouse is trapped"; and the multi-overlay screen is a state of its own (the read reports it as extra
  control-hosting panels), so a sequence assuming at most one overlay assumes something the operator can break
  in two keystrokes. Where the block *is* in force it is worse than a nuisance: the pointer is confined to the
  overlay, so a press aimed at a column row or a strip button lands on whatever sits at that point **inside**
  the overlay — refuse the press on the presence check, before the cursor moves. Classify each popup's modality
  once and keep it in the map: on one app every `Parameters` entry, the record and display-option dialogs, the
  filter-parameter dialog and the measurement tools block, while the TGC editor, the PRF search, the raw-data
  capture and a cursor read-out window do not.
- **A menu entry's name and the window it opens need not match — record both.** Measured on one app: the entry
  `Search artefacts` opens a window captioned `Sweep PRF`; `Record options` opens `Record settings`; `Options`
  opens `Preferences`. The entry names the purpose, the window names itself, so identify a surface by the
  caption you can actually see and keep both strings in the map; filing a crop or a note under the entry's name
  alone is how a later reader concludes a surface is missing — a crop named after the entry read as a
  filename/content mismatch, while the window it showed was that surface all along. Dropdown contents are
  state-dependent in the same way — toggles add entries (`Show cursors` adds a cursor item, enabling a filter
  adds a parameter item) — so never press a dropdown entry by a remembered index.
- **A panel the operator can drag must be found through its widgets, not by position or ordinal.**
  Measured: the record strip is a floating panel the user can move by dragging a corner, while every
  script bound it as `x == 448`. Bind it as `GetParent()` of the widgets it owns — correct wherever
  it has been dragged, and unaffected by the panel's own rectangle changing with state
  (352x40 -> 98x40 -> 594x123). This is the structural form of "never hard-code coordinates": find a
  movable container by what it contains.
- **Learn what the record button does to data already in memory before designing a sweep.** An app
  may not overwrite its buffer: measured, pressing Record **opened a new block** — the `Block` counter
  incremented, the `Profile` counter restarted from 0 (1948 -> 420, i.e. **per block, not
  cumulative**), and the store dialog's block selector gained an entry with the old block still
  selectable. Nothing reached disk until the store was confirmed, and that store wrote **only the
  selected block** (the dialog's slider maximum equalled that block's profile count). So a sweep can
  record point after point without losing earlier ones — and a per-block counter must never be read
  as a cumulative one. **Do not build block reclamation until a scenario needs it.** The cap is a
  setting, not a hardware limit (measured values accepted above 1,000,000), and the cap — not physical
  memory — is *not* what ends a recording: the block behaves as a **ring**, so the app keeps
  acquiring and the window silently becomes the last `cap x period` seconds. Measured after the cap
  was crossed: the artefact was not truncated at the cap, it was still growing, and it had *not* been
  deposited — it was picked up by the **next** cycle's store and written under that point's name at
  roughly 10x the expected size, in a file that still looked perfectly valid. So design for both ends:
  assert `duration <= cap x period` from the period you measured, detect the warning, sanity-check
  every stored artefact against a **size signature** (bytes per gate-profile, calibrated once on a
  known-good point), and never store a point whose cycle failed — a failed cycle must be stopped and
  cleared before the next point, never left to roll into it.
  Blocks carry meaning only where the unit of work is a *repeat* — rolling/multiplexed multi-channel
  acquisition, each roll contributing N blocks, where the store's block selector is exactly the right
  handle. A single-channel parameter sweep needs no block management at all.
  **The cap lives in a storage surface of its own, not in the store path you exercise.** Measured: this
  application commits a recording through its *Store* dialog (geometry known, path exercised) while
  `Do not keep in a block more profiles than` sits in `Record settings` — a different surface that this
  automation has never read or written — so "the settings dialog" is ambiguous and a plan that depends on
  the cap depends on a value nothing here has established. The cap is **not a planning limit** (the UI
  accepted a million) while the value *in force* does truncate a long point's start (plan §18;
  `docs/dop3000/udop-automation.md` §7, §12.4).
  **Treat the cap as an input you were told, not as a law you measured, and never let it refuse the
  project's own operating point.** Measured: the production point length stores less than it asks for
  (12 s asked, ~8.4 s kept — the last ~257 profiles), and that recording *is* the deliverable, so a plan
  guard that refuses it makes the goal unrunnable while proving nothing. State the consequence instead —
  N profiles above a cap of C covers its last `C x period` seconds — and let the run continue, keeping
  the refusal for the genuinely unsatisfiable (a window outside the period law's depth budget, a pitch
  that would snap to another rung). **And never let a shipped example or definition dodge that guard
  with a placeholder constant:** its values must be the measurements, or be marked unknown, because a
  placeholder there is a measurement hidden from whoever reads the file next.
  **Reset the block unconditionally before every point, not only after a failure you noticed:** stale
  profiles outlive the run that produced them. Measured: a point recorded into a buffer that still held
  ~6,000 profiles from an earlier aborted attempt was stored at **60x** the expected size at identical
  settings, and the app's own status readouts were the leading indicator — large **negative** timing
  averages and maxima, i.e. the app computing across frames with a broken time base. Impossible values
  in the app's own readouts mean the buffer is the problem, not your loop; clearing first produced a
  correct artefact. **Fail closed on the size check:** if the expected size cannot be computed (a
  definition missing the acquisition rate or frame count it needs), the point is invalid, not
  unchecked-but-fine. And read the signature as an approximate factor guard — two clean points at
  identical settings implied 64 and 88 frames, so it catches gross contamination, not small drift.
  Refine the guard's *shape* (a gross factor on an expectation derived from the point's own parameters)
  rather than its precision: the frame period is jittered by the OS and by mechanics, so a fitted model
  is nominal at best, and the parameters that derive the expectation must be carried on the point
  definition or the point is invalid by rule. Re-check the guard at the production point length before
  trusting it — short scaffolding points are not the operating condition: at a 12 s production length a
  factor-2 guard accepted a block holding **0.62** of what the period law predicted, while those same
  settings at 4 s matched that law to within measurement (32.5 ms against 33 ms). So the loose factor is
  not what let it pass — **a long point stores less than the duration it asked for**, and the shortfall
  grows with the length (one configuration, measured: 3 s asked, ~3 s stored; 6 s asked, ~4.4 s stored;
  12 s asked, ~8.4 s stored). Measure that at the production length with a **two-duration linearity
  run** — two points, identical settings, one delay double the other, the buffer reset before each — and
  read the stored window off the artefacts. Never explain the gap by a period-law error: that is a cause
  to be measured against the app's own counters, not inferred from file sizes, and size arithmetic has
  already produced two wrong readings in one session (a claimed per-item mode toggle, and a claimed
  1.6x period-law error — both retracted once the artefacts that actually record those quantities were
  read). **A tolerance guard is never a stand-in for the achieved quantity:** carry the achieved
  period/duration on the point's own record, because the guard passing only means "not grossly
  contaminated", and a duration-based comparison needs the achieved window. **And check that the read
  exists:** a cycle whose own docstring promised the achieved period was read from the status bar and
  logged carried `timing: {None, None}` in every record, because that read was never implemented — a
  promised measurement is a claim like any other.
- **Break the run, do not cascade, when the application's state is unverified.** Classify every failure:
  an **artefact-side** failure (a file exists and is wrong — contamination, a size off the signature, a
  refused verification) is a normal point failure and the loop carries on; an **app-side** failure (the
  layout, an overlay, the reset, a parameter write, the record/store cycle) means the app is no longer
  in a state you understand, so stop the whole run. Continuing past one burns every remaining point into
  an identical failure, which reads as bad parameters rather than as a dead application. Mark the abort
  on the returned outcome *and* in the log, so a caller can separate "this point was bad" from "the run
  was cut short and the rest was never attempted". Measured three times in one session: each abort left
  the app in exactly the state it was found in, no file written, nothing pressed, no cleanup needed —
  which is why the failure costs a slot and not the run.

- **Make a run of tens of seconds say what it is doing, and treat "it hangs" as a data question.** The
  operator watches the screen, not your log: a cycle that is silent through its own setup — the buffer
  reset, a verification dialog, the parameter writes — is indistinguishable from a stalled run, and
  that is how it gets reported (*"a long delay without any progress"*, twice in one measured session).
  Emit a note at every stage boundary, with its offset from the run's start (reset, item verified,
  recording confirmed and the duration being held, hold over, store dialog up and named, stored), and
  stream them so the wait is legible while it happens. Two hard rules come with it: **a note must never
  touch the filesystem** — a note that `stat`ed the stored artefact turned a *faked* store into a failed
  point, which is what a fake-only suite is for — and **a "hang" report is checked against the run's own
  clock before any code changes.** Measured: the run took 24 s from log start to last write with its
  task `Ready` and no stray process alive, while the two minutes the operator experienced was the
  agent's own fixed sleep after dispatching it. So poll the task's log for its completion line instead
  of parking a fixed sleep, verify the target and argument **files** are in sync before dispatching — a
  probe handed its own script name as its first argument read it as a duration, exited instantly, and
  looked like a run that did nothing, so validate argv and fail loudly — and report the screen state you
  ended in, including when you have not re-read it.
- **Hoist per-item modal work to once per run when each item's own artefact already certifies it.** A
  modal costs the operator's attention plus several seconds per item, and a verification dialog opening
  once per point of a sweep is exactly what an operator objects to (*"why do you open that twice?"*). It
  usually proves nothing the item's artefact does not: the stored file is its own certificate, because
  the decoder **refuses** a file carrying no data for the channel it is asked for (measured: a
  channel-2 artefact raises "carries no data for channel 1"). Verify once, before the first
  irreversible step (the first recording), pass the per-item call a flag that skips it, and keep the
  guard intact for a bare single-item invocation. Nothing inside a run changes the verified property,
 and if something does, the item's own artefact fails the point that follows it.
 - **When the target machine does not exist yet, vary the one variable you cannot change later.** A
 window's *maximized* state is why absolute screen coordinates look stable — the frame is the screen,
 so every earlier hover point happens to hold. Un-maximize the target and move it, and every such
 coordinate shifts at once. Run the read-only inventory and the cycle checks against the moved window:
 the *structural* rules (class + containing panel + order, containers found by what they own, dialogs by
 content) should survive, while anything stated in screen coordinates is now on its fallback — which is
 the answer you wanted. It is the cheapest available proxy for a fresh install, a second monitor or a
 different DPI; restore the window afterwards and re-read the inventory to prove you did.

 ## From reconnaissance to a driver module

Reconnaissance ends in a prototype; the deliverable is a module someone else can run. Shape it so
the GUI-coupled part is quarantined and the rules are pinned by tests:

- **Put the interface in front of the implementation.** Define the actuator as a `Protocol` (or ABC)
  carrying only the primitives — read/write a parameter, press, resolve the strip state, wait for a
  view, store, wait for the artefact — with the binding tables, write order, view-to-button mapping
  and overlay answers held as **data**, not as branches. Then the driver and its tests can be written
  in parallel against the interface, and the whole loop is exercised through a fake with no app
  present, which is the only way this class of code is testable at all.
- **Transcribe the verified rules as table-driven tests with the measured numbers in the tables.**
  Ladder rungs, gate counts, expected depths and the byte-per-gate-profile signature belong in the
  test data, so an arithmetic change that silently moves a plan fails in CI instead of at the rig.
  Pin the artefact decode against a real capture committed as a fixture — a decode nobody can re-run
  is a claim, not a test.
- **Keep the optional GUI dependencies lazy and out of the dependency declaration.** Touch
  `ctypes.windll` inside functions, import `pywinauto`/`watchdog`/`pillow` only where used: the
  package must import cleanly on a host with no Windows, or the suite stops being collectible and the
  tests stop being a gate.
- **No control ids or screen coordinates in the ported logic.** Geometry tables are fine; an id or a
  literal coordinate written into a branch is a bug the next launch will find.
- **Answer "can the tool turn every knob?" with a coverage inventory against the operator's own list,
  never from memory.** Take the parameter list from *their* document (a sweep matrix, a settings table,
  a manual chapter), key the inventory to their names, and give every row: which mechanism reaches it
  (the parameter column / a dialog's positional value table / a settings dialog nothing reaches),
  whether it is *read*, whether it is *written*, and what is missing. Two things fall out that a
  recollection never gives. The writing half is regularly already present as a private helper —
  measured, a driver's `_combo_select` and `_set_text_commit` both took the field's own handle all
  along, so a "read-only" dialog field needed a positional binding rather than a new mechanism — and
  the arithmetic of the unbound surface is the work list: a dialog's 15 value fields with 10 bound sat
  beside exactly 5 knobs with no home anywhere else, which is a mapping to *confirm*, not to assume.
  State the confirmation method with the hypothesis (change one knob by hand, re-read the surface, see
  which field moved) and never code against the guess. Name the one knob with no path at all rather
  than letting it disappear into the list: it is the honest gap in the answer.
  **A knob is the group of controls it takes, not the field holding its number.** A value field paired
  with an enable flag is inert while the flag is off — measured: a skipped-profile count of `2` changed
  nothing in the application or the artefact because the "apply" tick box beside it was unticked, and a
  record written from that field alone would have claimed a setting nobody applied. Identify the whole
  group before writing it, read the flag back with the value, and treat a value without its flag the way
  you treat a value without its source. The flag is usually a different control class from the surface's
  value fields, so it does not disturb the field count the inventory above depends on.
  **Trust only a baseline captured before the change, and probe with something that returns in
  seconds.** A read dispatched before the operator's edit but landing after it is not a baseline — a dump
  taken earlier and committed is, or sequence it strictly (read, change, read). Do not reuse the
  multi-purpose reconnaissance probe for an operator round trip: measured, it ran past four minutes with
  zero bytes written, because a probe that prints its JSON once at the end gives you nothing to poll for
  and in-flight is indistinguishable from hung. Write a fast single-purpose read of that one surface, and
  never dispatch a slow read while asking the operator to change something "meanwhile". Recipe:
  `references/parameter-probing.md` §Identifying which control is which knob.
- **The coordinator owns the gate, whoever wrote the code.** Run the lint and the focused tests
  yourself before committing a port, and check that the changed file set is exactly the set you
  expected before you write the commit message. When the suite is red, **classify the failures
  instead of counting them**: a cluster of identical errors inside one module is one defect with one
  cause, and a failure that predates the branch is not automatically unrelated to it — reproduce the
  failing call on two unrelated inputs to tell an environment problem from a platform one. (On
  Windows `os.open` on a directory always raises `PermissionError`, so a directory-durability helper
  built on it is broken there unconditionally, and a Linux CI passes it and hides that.) A gate
  nobody can run green is not a gate.
- **The proven probe script is the spec: port it verbatim, and never re-derive a gesture.** When
  reconnaissance left a script that demonstrably performed the interaction (opened the dialog, read its
  fields, changed a value, accepted — repeatedly), transcribe its gesture, its order and its decisions
  literally. A "better" gesture invented to explain a fresh live failure replaced a proven posted held
  press with a real click and made the failure worse, and three fix cycles went into rediscovering what
  the reference already did. When a live step fails, first **diff the driver against that script** —
  gesture, target handle, target point, and the *preconditions* it checked (a visible overlay, the write
  order, the ordering by screen position) — and only then consider a new mechanism.
- **When the driver gains a platform call, add the fake's seam in the same change.** These ports are
  tested through a hand-rolled fake that *subclasses* the driver, so a new unmocked call
  (`IsWindowVisible`, `GetClipCursor`) kills every case that reaches it on a missing import — measured,
  two dozen tests failing with `ModuleNotFoundError: No module named 'win32con'`, which reads as a broken
  fake rather than a missing seam. Route the call through a one-line method on the class, override it in
  the fake, and keep the fake's constants **measured**: a stand-in dialog at an invented `360x200` fails a
  `width > 400` predicate the driver now enforces, and an invented child count passes a test the live
  panel would fail. Replace the fake's guesses with the numbers off the live capture in the same commit.
- **Make the implementer name what its fakes cannot verify.** A fake written from your spec encodes
  your assumptions as passing tests: it proves call order and contract, never that a gesture works on
  the instrument. Require that list in the report and treat it as the live-verification plan — the one
  caveat an implementer volunteers unprompted (a menubar gesture it could not exercise off-hardware)
  was exactly the code that failed first on the instrument, and it was the only part of the port that
  needed two more passes. **And spec the observable, not a name:** an instruction to match a menu entry
  by its title is implemented faithfully and can never work on a caption-less toolkit — the
  subcontractor has no way to know the title does not exist, and the failure surfaces only on the
  instrument. State the binding as class plus geometry plus screen order, and say explicitly that
  captions must not be used.
- **Build every object before the first input action.** Construct and validate the whole run inside one
  guarded block and print the field names/types of anything that refuses to construct; a spec mistake
  (a parameter that is 1-based when you assumed 0-based, a required field you guessed) then costs one
  command instead of a live slot, and it cannot half-drive the app before failing.
- **Expose the channel, or any per-instrument selector, as one knob.** A config field with documented
  precedence (explicit > environment variable > default) and a validated range, read by the driver and
  the decoder from that single place, so retargeting an instrument is not a code edit in several files.
  Verify a selection by **re-opening the surface and reading it again** after accepting: a control can
  hold a value the application discarded, and silently measuring the wrong channel or protocol is worse
  than a refused point — fail the point when the selection did not take.
- **Order an inspection after the routing step that establishes which item is in scope.** A "read the
  current state" step placed *before* the per-item selection (channel, port, segment) reports whatever
  was selected before it, so a plan that compares that against the requested item reports a mismatch
  for a state the run was about to fix — turning supported behaviour (select the requested item) into
  a refusal. Read-only means *changes no configuration*, not *runs before everything*: select, then
  read, then decide, and record the selection beside the reading it preceded. A helper that returns
  the verified selection together with a fresh screen read is the shape to copy.
- **Carry the live path in the deliverable repository, not in the reconnaissance project.** The probes,
  the dispatch wrapper and the interactive-session route are what make the automation *runnable*; leave
  them in a scratch archive and a second machine can clone the repository and still run nothing. Ship
  them beside the code (outside the packaged `src/`, so they stay out of the wheel), with **every path
  derived from the file's own location** and the interpreter falling back to the running one. Keep the
  reconnaissance archive as evidence — cite it by name in docstrings, never import it — and do not
  promote its numbered probes into the package: their durable output is the ported logic, the docs and
  the tests. Layout, staged bring-up and the machine-measurement table: `references/live-run-bringup.md`.
- **Make the parameter list a checked artefact and the job a resumable record.** Three commands carry
  the work: a **plan** that validates every point and touches nothing (it must run where the application
  is not installed — that is where a definition gets written), a **run** that emits one record per point
  plus a manifest beside the log (definition fingerprint, start and finish, per-point status), and a
  **report** that reads log and manifest with no instrument attached. Key **resume** on the identity the
  record already carries rather than adding a required field to the log — the stored name's prefix plus
  the point's label — and **re-run a point whose identity cannot be established instead of skipping it**:
  a wrong skip is silent, a re-run costs one slot. Carry the derived window (and the consequence of any
  cap) per point, so the plan says what will be stored before a single slot is spent. Measured on six
  permutations: one verification dialog for the whole job, ~17 s per 12 s point, and a re-run with nothing
  to do finishing in seconds.
- **Report a refusal as one line with the documented exit code — never re-parent an exception to make a
  handler catch it.** Measured: the pre-run verb against a non-foreground application printed a full
  traceback and exited 1, because the driver's refusal type is not a `ValueError` while the CLI's handlers
  caught only `(ValueError, OSError)`. A refusal is still a refusal — the run did not happen and nothing
  was written — so catch the driver's own error at the **CLI boundary**, print one `<prog>: <message>`
  line and exit with the code the interface documents for a refusal (2 here, distinct from 1, a refused
  item, and from a crash). Do not re-parent the exception class to make an `except` match instead: the
  hierarchy is what lets a caller tell a *refused point* from a *broken instrument*, and blurring it buys
  one caught case at the price of that distinction (plan §16.2).
- **A moved script is verified by running it, not by compiling it.** `py_compile` passes on a
  `NameError` that only fires at runtime — a path rewrite that used `Path` before the module's own
  import compiled clean and died in the dispatched session. After porting, run each script once in its
  read-only mode from the new location, and fix the import order rather than the symptom. Compile
  as well, immediately after any **structural** patch: module-level code inserted at column 0
  inside a class body silently *ends* the class, leaving the file indentation-broken below it —
  anchor module-level additions before the class, not next to a method, and let the compiler catch
  the rest.
- **Do not generalize the machine's measurements — ship them as a bring-up table instead.** A control
  count, a window class, a dialog's geometry, the application's own working directory, the first-run
  configuration values: these are *that machine's* readings. The user's position on a second-machine
  test is to fix what differs *there*, not to fund an abstraction for machines nobody can test — so list
  each measurement with what to do when it does not hold, and give a staged way to find out which one
  it is (`references/live-run-bringup.md`). Never let a fallback silently accept a state the run was not
  designed for.
- **The Store dialog's `Working directory` does not resolve a relative path.** Handed
  `outputs/live/frame-probe` the application raised its own *"The selected directory does not exists —
  Do you want to create it?"* warning, and the live cycle stopped on that modal: the recording sat
  unsaved while the caller waited on a dialog nobody was watching. An absolute path to an existing
  directory is written and accepted, and the application's own note then says which directory it had
  and which it wrote — read that line before trusting a store. Pass `--store-dir` absolute on the
  command line and let a plan keep its portable relative default; answer a stray warning with the
  driver's own rule, the *left* button of the dialog's bottom pair (`DialogControl.SAFE`), never a
  guessed handle or a coordinate.
