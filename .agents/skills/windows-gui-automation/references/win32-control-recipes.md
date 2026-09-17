# Win32 control-level recipes for custom (Delphi/VCL) widget apps

Lessons learned automating a Delphi/VCL instrument app (TSp_* custom widgets, no accessible names) at the
message level, with no focus and (optionally) a locked desktop. Each rule below cost a wrong conclusion
first.

## Committing values

- `WM_SETTEXT` **alone never commits** a value into the app's model. Follow it with
  `WM_COMMAND`/`EN_CHANGE` to the parent edit, then `WM_KEYDOWN` + `WM_KEYUP` with `VK_RETURN`.
  `WM_CHAR` with `\r` does not commit.
- Combos: `CB_SETCURSEL(index)` + `WM_COMMAND`/`CBN_SELCHANGE` to the parent **commits**; no Enter needed.
- **Verify against the app's own derived readout, or against the artifact it produces — never against
  the control's text.** A control happily displays a value the model refused; one app showed `805`
  while its stored file carried `474`.
- **Write order matters.** Write the structure-determining parameter first and the one the app derives
  from it last. A resolution write caused an app to silently recompute and trim a gate count written
  just before it; swapping the order made the same request stick.

## Clicking custom widgets

- Posted `WM_LBUTTONDOWN` + a **~180 ms hold** + `WM_LBUTTONUP`, client-relative coordinates. Down and
  up in the same millisecond is frequently discarded by such widgets — the hold is the recipe.
- **Posted clicks ignore modality.** A press can land on a widget *behind* an open warning. Check for
  overlays before every press.
- Identify buttons by **order in the view** or by role+geometry — never by width, and never by control
  id (ids are per-launch). Two buttons differing by 4 px meant the difference between a harmless
  button and a data-loss warning.

## Detecting dialogs, menus and modality

- A dialog that is a **child panel** is invisible to an `EnumWindows`-based "did a new top-level window
  appear?" test. Detect overlays structurally: a new panel rect that is not one of the known panels
  and owns its own button row.
- `GetClipCursor()` is a usable **modality detector**: a blocking popup clips the pointer to its own
  rect and releases it on cancel. But it is blind to a low-level mouse hook, so probe behaviourally
  (`SetCursorPos` then read the position back) as well. Posted messages are immune to a clip either way.
- **Never `WM_CLOSE` a menu popup** — the popup dies while the modal menu loop lives, wedging the app
  until restart. Dismiss by performing an entry's action instead.
- Menu entries open on **hover**, and a hover menu may be dismissed by any pointer motion — run
  behavioural probes *after* an interaction, never before. Keep the pointer on the item through the poll
  and the entry press, and restore it only afterwards: putting it back early is the dismissal the recipe
  warns about. The **entry** is then taken by the ordinary posted held press on its own handle, so the
  hover is the only step that needs the cursor.
- **Detect the overlay the way the driver detects it — never with a stock-Windows class.** These
  toolkits draw their own menus: entries are ordinary child widgets inside a panel the app positions
  itself, so a native-menu-class lookup returns 0 whether the menu is open or not. A probe built on it
  reported "no menu" for every position and every gesture, and the agreement between runs read as
  confirmation instead of as a broken detector. Filter the app's own control tree (`class` + geometry +
  owning panel) exactly as the map filters it, and treat a stock-API negative as *untested*, not as
  evidence of absence.
- **Foregrounding is its own step.** `SetForegroundWindow` returns 0 from a background process (the
  foreground lock), and a driver launched from a console finds the app unfocused as a matter of course.
  Attach to the current foreground thread first —
  `AttachThreadInput(GetWindowThreadProcessId(GetForegroundWindow(), None),
  GetWindowThreadProcessId(target, None), True)` -> `SetForegroundWindow(target)` -> detach — and confirm
  with `GetForegroundWindow() == target`. An inactive window ignores hover and gives its first click to
  activation, which is indistinguishable from a surface that does not respond to input.
- Hover points recorded as literals go stale with the window: one full-screen app measured `(-8,-8)`,
  so a point measured in an earlier frame lands off the item by that offset. Whether an offset that small
  is *why* a hover missed is **not established** — so derive the point from the item's rectangle at run
  time, and when a hover misses, re-measure the item and re-check the foreground state before concluding
  the surface is undrivable.
- Select menu entries by **sorted screen position**, not by enumeration order: enumeration order is not
  screen order, and picking the wrong one ran a destructive "reset to defaults" entry.

## Long unattended loops

- **Never sleep blindly through a wait.** Poll the app while waiting, or a modal warning raised
  mid-operation is invisible to the loop.
- **Return to a known-good state before the next item.** Abandoned work can roll into the next item's
  output: an app whose recording never stopped stored that accumulated data under the *next* point's
  name, at 10x the expected size, in a file that still looked valid.
- **Sanity-check the produced artifact** (size, count, identity) against an expected signature, and
  invalidate the item when it is off by a large factor. This is the cheapest guard against the above.
  **Fail closed:** if the expectation cannot be computed at all (the signature needs a parameter your
  definition does not carry), the item is invalid — never unchecked-but-fine. Keep the tolerance gross:
  the frame period is jittered by the OS and by mechanics, so refine the guard's *shape* rather than its
  precision, and re-check it at the production point length instead of the short scaffolding one.
- **Reset the buffer before every item, not only after a failure you noticed.** Stale data outlives the
  run that produced it: a point recorded into a buffer still holding ~6,000 frames from an earlier
  aborted attempt stored at **60x** the expected size at identical settings, and the app's own readouts
  were the tell — large *negative* timing averages and maxima, i.e. the app averaging across a broken
  time base. Impossible values in the app's readouts mean the buffer, not your loop.
- **Stop the run when the application's state is unverified; continue only for artifacts.** An
  artifact-side failure (a file exists and is wrong) is a normal item failure and the loop carries on; an
  app-side failure (layout, overlay, reset, a parameter write, the record or store cycle) means the app is
  no longer in a state you understand — stop, mark the abort on the result and in the log, and skip the
  rest. Continuing past one turns every remaining item into an identical failure that reads as bad
  parameters rather than a dead application.
- **Verify the stored item's parameters, not just its size.** These files carry the operation settings in
  fixed word positions (uint32 words, 256 per channel, stride 1024, the measured channel-1 offset 548;
  among them a resolution rung index, gate count, rate and sound speed), so "the bytes say what was
  requested" is checkable independently of the code that wrote them. Prefer that to trusting the write
  path, and keep any such word marked unverified until two sources agree on it.
- Prefer reading a protocol selector's current selection back right before the destructive action
  (e.g. which buffer/block is selected), because such stores are usually scoped to that selection.
  Verify a selection by **re-opening the surface and reading it again** after accepting it: the control
  can keep a value the application discarded, and silently measuring the wrong channel or protocol is
  worse than a refused item — fail the item when the selection did not take.
- Recording windows in physics instruments are usually specified in **time**, not in sample/frame
  count; a sample-count-defined window changes meaning when other parameters change the sample rate.
