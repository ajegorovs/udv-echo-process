# Custom-widget Windows apps: menus, real input, and cursor clipping

Lessons from automating UDOP 6.07.4 (32-bit Delphi/VCL, `TSp_*` widgets) on Windows 10,
all verified live on the instrument. These extend `win32-control-recipes.md`, which covers
the ordinary cases (numeric writes, combos, held presses, verification).

## A custom menu bar is not a menu bar

- Such an app may draw its own dropdowns as overlay **panels** with no captions. Do not
  look for a native menu window (class `#32768`) to detect one - it is never there. Detect
  the overlay as the panel that appeared since a snapshot taken just before the opening
  gesture, with a geometry predicate as fallback.
- That appearance check is necessary but **not sufficient**: the overlay panel and its entry rects can
  sit in the child tree while nothing is displayed. Measured on a freshly restarted app with the
  operator watching: the driver found the overlay, clicked four real entry coordinates, and no dropdown
  had ever been on screen — the popup simply stayed put. The mechanism is a **pre-created panel**: the
  overlay exists from startup with `WS_VISIBLE` off and the opening gesture shows it, so "in the tree"
  and "on screen" are separate states. Filter every overlay candidate on `IsWindowVisible`, refuse to
  press an overlay or entry that reports false, and name the hidden panel (handle + rectangle) in the
  refusal — the driver then reports "that panel is not on screen" instead of "the popup did not react".
- Menu entries can be caption-less buttons inside that overlay, so **matching an entry by
  title can never succeed**. Match by geometry: the buttons whose rects lie inside the
  overlay, **sorted by screen `top`** - enumeration order is not screen order, and picking
  the wrong one once pressed a destructive entry instead of the intended one.
- Identify the resulting **dialog structurally**, and only then tell two dialogs apart by content: a
  dialog is a panel that is not the sidebar column, is wider than ~400 px and is full of controls of its
  own (a direct child edit/combo/checkbox, a browse button, or a large direct-child count). Demanding a
  *specific* control — say the channel combo — as the test that a dialog opened is stricter than the
  evidence and rejects a correctly opened dialog; measured, that rule was why every entry looked like it
  had opened nothing. Use the distinctive control only as the discriminator between dialogs, and close
  an unidentified dialog with a safe/leftmost button, never Accept/OK.

## Real input is required in places, posted messages elsewhere

- A menubar item may answer **nothing** posted: a posted `WM_MOUSEMOVE` and a posted held
  press both opened nothing, while the real cursor did — the hover is the proven menu-opening gesture.
  Hovering a computable point derived from the item's rectangle-at-run-time works; a recorded literal
  goes stale as soon as the window moves.
- The **entry** takes an ordinary **posted held press on its own handle** (`WM_LBUTTONDOWN` with
  `MK_LBUTTON`, ~180 ms, `WM_LBUTTONUP`) — the same recipe as any other custom widget, and the one a
  working probe script used repeatedly to open, read, edit and accept such a dialog. It needs no cursor,
  so the hover is the *only* real-input step on the whole menu path. Keep it posted: a re-derived real
  click on the same entry opened nothing at all, and the two failures (that click, and the
  phantom overlay above) mislead in the same direction.
- Everything else in the same app answered posted messages fine (record strip, sidebar
  numerics, dialogs, nested combos). Keep posted messages as the default and escalate to
  real input only where measured.
- Real input means `SetCursorPos` + `mouse_event`, and it moves the operator's cursor: save
  the position, restore it, and gate the whole path behind an `allow_real_input` flag.

## ClipCursor is a systemic hazard for real-cursor gestures

- A blocking popup can clip the cursor to its own rectangle. Then `SetCursorPos` is
  **silently clamped**: a restore aimed at the previous position lands on the popup's
  corner, and a move aimed outside the clip never arrives - which reads as "the cursor
  would not move" and gets misattributed to a locked desktop.
- Read `GetClipCursor` before moving; if the target is outside the clip, call
  `ClipCursor(None)` to free it and retry. Restore the operator's cursor only once the
  clip is clear, so a restore can never be trapped.
- **Always read the cursor back after moving.** That check is what caught this. A full-screen
  rect `(0,0,W,H)` is *not* a clip - test for an empty/screen-sized rect, not for
  `right`/`bottom` being non-zero, or you will report a clip that does not exist.

## Focus and window activation

- Hover-opening such a menu does **not** require the app to be focused; measure before
  adding activation. Plain `SetForegroundWindow` often returns 0 and merely flashes the
  taskbar (that flash is the failure, not the app asking for attention).
- When activation is genuinely needed, `AttachThreadInput(foreground_thread, app_thread)`
  followed by `SetForegroundWindow` works - keep it scoped and detach afterwards.

## State checks before pressing anything

- A layout fingerprint (visible control count / panel count) is the cheapest whole-screen
  assertion: a leftover open dropdown shows up immediately as extra controls and panels.
- Refuse and stop on an unrecognised overlay or layout instead of pressing the safest
  looking button: in a measurement app a stray press can store stale buffer contents or
  reset parameters.
- Some transients look like failures: `Clear and restart` collapses the record strip to
  zero buttons for a few seconds while the block rebuilds. Do not read that as a wedge.
- **Order surface verification before any control that collapses the UI**, and wait for the control
  inventory to be *stable*, not merely "startable" — the readiness poll can pass mid-rebuild. Verify
  the instrument selector (channel) once at the start of a run on a rested app, not inside a per-point
  cycle that opens with a reset.
- **Restart the app to eliminate stale UI state as a variable.** One run against a fresh launch either
  fixes the failure or removes the hypothesis for the cost of a single slot; a fresh restart
  reproducing an identical failure was worth more than the run that produced it.
