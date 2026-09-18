# Attach lifecycle and UI state machines

The map tells you what the controls are. This file is about getting to a state where the map is
usable at all, and about the states the map has to describe.

## 1. Resolve the process from the window

**Rule: bind to the window, then to its process — never to the executable path first.**

`Application(backend="win32").connect(path="App.exe")` selects by executable path. Several
processes can share that path: a launcher stub, a second instance the user opened, or a leftover
that owns **zero** windows. When it binds to the windowless one, every subsequent
`window(class_name=...)` raises `ElementNotFoundError` — and that is indistinguishable, from the
outside, from "the app never started" or "the app hung". **Before concluding that a windowless sibling exists, verify your pid really is a pid:**
`win32process.GetWindowThreadProcessId` returns **`(threadId, processId)` — thread first**, despite
the name. Taking element 0 as the pid makes the real app look like a windowless second instance:
`OpenProcess` fails with `ERROR_INVALID_PARAMETER` (87), the image name comes back unknown,
`connect(process=<thread id>)` raises `ProcessNotFoundError`, and "windows owned by that pid"
correctly finds none. A windowless process can also be real — a launcher stub, or a leftover from a
run that crashed or was quit while recording — but the two are indistinguishable from the outside,
so rule out the tuple order first; it is the cheaper hypothesis, and it was the actual cause once.

Recipe (`scripts/win_attach.py` does this):

1. `win32gui.EnumWindows` → keep windows whose `GetClassName` matches the target class.
2. `win32process.GetWindowThreadProcessId` → the owning pid; `GetModuleFileNameEx` → the exe, so
   candidates from unrelated apps are visible when the class name is common.
3. Sort by `(not visible, -area)`; take the first, print the rest.
4. `connect(process=pid)` then `app.window(handle=hwnd)` — pin to *that* window rather than
   re-finding by class later.

A hidden candidate is still a legitimate answer (startup, see §2) — accept it with a warning
rather than waiting forever for a visible one.

## 2. Cold start: the window you want may not exist, or may exist hidden

Attach order: **find the process → wait for the target class → wait for visibility → validate the
map → drive.** Skipping the visibility wait produces an all-black capture (§4) and an empty
control set, which reads as "the app is broken".

- **A modal startup or mode-selection dialog can sit in front of a main window that already exists
  but is hidden.** The process may own *no* window of the class you asked for while that dialog is
  up. Enumerate by pid and report what the app *does* own before concluding the app is dead.
- **Demo/simulation builds front such a dialog to choose the simulated instrument and the
  simulated option packages.** That selection is why the demo shows menu entries and capabilities
  the real target lacks, and it is a lever: set the simulated options to match the target's real
  licence state before comparing UI, capability or a measured domain. Never quote the demo's
  option list as evidence of the target's licence — read it off the target.
- **Mode is asymmetric.** The dialog may exist only without hardware attached; with the device
  connected the app may open straight into its normal screen. A driver must therefore neither
  require the dialog nor assume it is absent — wait for the main window, and treat either arrival
  path as normal.

## 3. Capture the state machine instead of inferring it

For an app whose controls change with state, spend one cycle per state before writing the
sequence: dump the visible control set, capture the window, and diff state against state. What
the diff tells you:

| Observation | Meaning |
|---|---|
| same `control_id`, different caption and/or slot | one widget, two functions — the map entry needs `states: {...}`, not two entries |
| sibling widgets present in one state only | their presence *is* the state predicate; mark them `required: false` |
| new widget appears (an indicator, a stop control) | a state you have not seen yet — capture it before driving it |

Captions on owner-drawn toolkits are unreadable, so the state predicate is always *which widgets
exist* plus the painted readouts in the status bar. Say so explicitly in the map, because the next
session will otherwise assume "the id is present" means "it is in the state I want".

## 4. Unattended recording: treat the buffer as a budget

Telling a recording app to acquire is cheap; letting it run is not. A block costs
`frames × points × samples-per-point`, and an app that runs out mid-session raises an error the
sweep cannot continue past (measured: recording with a small configured buffer exhausted memory
and the app had to be quit, leaving a windowless leftover process behind — see §1).

- Size the block explicitly in the plan; never record open-endedly, and size it from the app's own
  **inter-frame interval** readout, never from a free-running frame counter — the two disagree and
  the interval is the trustworthy one (measured ~21 ms, i.e. ~47-50 frames/s, against a counter that
  appeared to advance ~8/s). The interval is what makes the fill time predictable.
- Control the **cap**, do not police the readout: set the per-block frame cap to fit the longest
  point rather than watching the memory readout and aborting blocks. A readout saying the ring is
  **full** means the block reached its cap — the ring then keeps overwriting its oldest frames and
  acquisition continues (visible on the time axis of a compute view), so it is saturation, not a
  stop and not an error. What ends a block is the configured cap, and the warning the app raises
  means "this recording hit its cap", not "out of memory". The cap is an ordinary editable field and
  takes effect without restarting the app (verified by re-opening the dialog and by the readout
  switching from full to filling). Its upper range is wide — measured, the field accepts values above
  **1,000,000** — so size it from the longest point rather than designing around a limit. Because the
  cap is what ends a recording, the one guard worth building is for a point that crosses it: the app
  warns and the artifact is **truncated yet still valid on disk**, so detect the warning and mark that
  point invalid rather than store-and-log it as complete. Block reclamation itself is needed only where
  the unit of work is a *repeat* (rolling / multiplexed multi-channel: each roll contributes N blocks);
  a single-channel sweep needs none.
- Do **not** characterise the buffer limit in a demo/simulation build — the target's limit
  differs, so the number is not transferable.
- The clear/restart control is the release valve between points; make it a planned step, not an
  emergency action.
- Detect the artifact as **complete** (size stable across consecutive reads, or the companion file
  present) rather than as **arrived**, or a half-written recording is parsed as a valid truncated
  one.

  ### Set the app's own output settings instead of renaming files afterwards

  Before designing folder management, look for a settings dialog that owns the output paths and the
  size caps — and look for it in the **child tree**, because such a dialog is often a panel inside the
  main window and will never appear in a top-level window enumeration (`control-id-mapping.md` §8).
  **A storage surface you have not driven is not a surface you can read or write from.** Two surfaces in
  one application are easily conflated: measured on this app, the **Store** dialog (geometry known, path
  exercised, buttons indexed from the right) commits a recording, while the cap — `Do not keep in a block
  more profiles than` — lives in `Record settings`, a **different** surface the automation has never read
  or written. So "the settings dialog takes `WM_SETTEXT`" is a claim about one surface and not about
  both: record which surface a finding belongs to, and where such a field has no exercised path, say the
  reader is unexplored rather than implying one exists.
  Worth setting deliberately on the target rather than inheriting a default:

  - the output/data directory, plus any **second** output location (one dialled-in dialog shipped a
    data directory and a field-data directory both defaulting to a drive root);
  - the **per-block cap**, which is the real memory control — the ceiling the app quotes for total
    memory is not the cap that protects a run;
  - the **pre-trigger ring depth**, i.e. how much of the past before a trigger is retained.

  Pointing the app at one output folder beats post-hoc renaming, and the app's own counter is usually
  recorded inside the artifact, so a single folder plus parse-later needs no external index. These
  fields are real edits wherever the toolkit derives from an edit base, so `WM_SETTEXT` sets them like
  any parameter field. Finally, distinguish the ring being full (a readout saying "memory: full" while
 the app idles is normal) from working memory being exhausted, which is the state that raises.

 ## 5. Menus and popups: the surfaces you must not wedge

 Measured on an owner-drawn toolkit whose menus are custom panels; treat it as the default
 hypothesis and re-measure, but do not assume better without evidence.

 | action | result |
 |---|---|
 | posted `WM_LBUTTONDOWN/UP` on a **menubar button** | opened the menu **once**, then nothing (the operator's cursor happened to be over it) |
 | posted click on a **popup entry** | works — the entry's action runs **and the popup is consumed**, the only safe way out of an open menu |
 | posted click on a **dialog's Close button** | works |
 | posted click outside the popup, or posted `ESC` to the main window | does **not** dismiss |
 | **hover** the menubar button (`SetCursorPos` alone, no click) | **opens the menu** — the popup appears on mouse-over |
 | a click (posted or injected) on that button once a popup is open | **closes** it; a click on its own never opens one, which is why every click-based attempt failed |
 | **`WM_CLOSE` to the popup panel** | closes it visually and **wedges the app**: afterwards no menu opens by any of the above, nor real `ESC`, a real click outside, or `Alt`. Restart only. |
 | hover the button again, move the cursor away, or click the plot | does **not** dismiss an open popup |
 | open a *different* menu | replaces the open popup — but consuming it costs that menu's own action, so it is not a free dismissal |

 **Mechanism:** the popup window is destroyed while the app is still inside its modal menu loop, so
 the loop never unwinds and later menu requests queue behind it. The application otherwise stays
 healthy — windows present, acquisition running, counters advancing — so nothing except "the menus
 never open" reveals it.

 Rules that follow:

 1. **No menu navigation in an unattended run.** Per-point changes go to sidebar fields by message,
  or to a config file the app recalls. Menus belong to setup.
 2. **If a popup is open when a run resumes, stop and raise.** A detector, never a cleaner — there is
  no safe programmatic dismissal. One toolkit-version-dependent exception the operator may know about:
  in older builds a stuck hover element closed when the same button was **re-hovered**, so try a single
  re-hover before declaring the run blocked, and record whether it worked.
 3. **Detect it with the layout fingerprint** (§4 of `control-id-mapping.md`, the control-count
  check). A popup adds a short panel that hangs under the menubar and *directly owns buttons of the
  expected class*; require all of those properties, because each one alone also matches a permanent
  panel.
 4. **Do not confuse dialogs with popups.** A dialog panel owns a Close button and a posted click on
  it works — that is the supported way to dismiss it. A menu popup has no Close button.
 5. **Read menu entries from a capture, and record their count.** Popup entries are painted, so the
  control tree gives rectangles and nothing else; capture the window while the menu is open and
  address entries later as `menu:index` (top-to-bottom), noting how many the menu had so a future
  session can tell an empty menu from a shifted one.
 6. **A menu entry that applies a whole configuration in one action** (a "recall parameters from
  file" path) is the most robust shape of all — it removes per-field writes entirely. Such an
  entry is worth having the operator drive once during setup and capturing, and it is worth
  preferring over scripting the same fields one at a time.

## 6. The record / stop / store cycle, and the strip's state views

The acquisition strip is one panel that **morphs**, which makes it the archetype of "a control that
looks undrivable". Recognise its view **structurally** — button count plus the presence of a child
of a given class — never by remembered pixel geometry: the panel's own rectangle changes with the
view (measured `352x40` → `98x40` → `413x123`) and the buttons' positions and widths change with it.

| view | predicate | top-row buttons, left to right |
|---|---|---|
| recording | exactly one top-row button, no slider child | `Stop` |
| stopped, no data | fewer than three buttons | one button |
| stopped with data | top-row buttons, **no** slider-shaped child | `[Pause][Record][Clear and restart]`, gaining `[Do store]` once a block holds data — the **second** button starts a recording |
| store view (reached after Stop) | top-row buttons **plus** a slider child | `[New acquisition][Do store][Clear and restart]`, plus `[Remove current block]` once more than one block exists |

The same slot means different things per view (the second button is `Record` while stopped and
`Do store` in the store view), so branch on the view predicate *before* pressing anything — a
positional map written from one view will press the wrong thing in another. **Never identify a button
here by width, and never as "the last one"**: `New acquisition` measures 134 px and
`Clear and restart` 138 px, so a width filter silently selected the wrong button and raised a
data-loss prompt where a clear was intended. Assert the button **count** the view should have, then
index by ordinal position inside that view. In the store view the slider's maximum reads how much the
selected block will store — measured equal to that block's own frame counter (421 against a `Profile`
of 420), and the configured cap when the ring was saturated — so treat it as "how big is this
store", not as a memory reading.

### The press must be held

`WM_LBUTTONDOWN` → ~180 ms → `WM_LBUTTONUP`, client-relative `lParam`. `Record`, `Stop` and
`Do store` all yield to this; an instant down/up yields to nothing. Find the working recipe per
control with `scripts/win_click_probe.py` rather than assuming it transfers across a toolkit.

### `Do store` opens a child panel, not a window

No top-level window appears, so an `EnumWindows` "did anything happen?" check reports that the
button did nothing — read the child tree instead. The dialog is a panel owning, in order, a browse
button, a working-directory edit, a file-name edit, a comments memo, and a bottom-right button
**pair** whose **rightmost** member is the real store action (the left one cancels).

Identify the two edits by **content, not by order**: the working-directory edit is the one whose text
contains a drive letter or a path separator, the file-name edit is the other. Both are plain edits in
the same panel, so a positional guess puts the file name into the directory field. These fields **do**
take the `WM_SETTEXT` + `WM_COMMAND(EN_CHANGE)` + `VK_RETURN` commit — verified by the stored file
landing under the name written into the field. (An earlier note here claimed the app's *sidebar*
fields accept the identical recipe but keep the old value. That was **wrong**: the writes had applied,
and only the verification was broken — it read a different channel of the stored artifact. See the
read-back-slot rule in the main skill.)

Unattended store, verified end to end on one target:

1. Write the file-name edit — `WM_SETTEXT` + `WM_COMMAND(EN_CHANGE)` to the parent + `WM_KEYDOWN`,
   `WM_KEYUP` of `VK_RETURN` to the edit itself (a bare `WM_SETTEXT` alone never commits).
2. Press the rightmost bottom button with the held-press recipe.
3. Confirm on disk: a new file, mtime now, and it parses.

### What `Record` does to data already in memory: the block model

Measured on the target, answering the operator's question "does pressing `Record` dump what is
already buffered?" — it does not, in either sense:

| observation | before | after `Record` + record + `Stop` |
|---|---|---|
| status-bar `Block` | `2` | `2` (incremented when the recording started) |
| status-bar `Profile` | `1948` | `420` — the counter is **per block**, not cumulative |
| `Show block` combo | `n=1 ['1']` | `n=2 ['1','2']`, selection on the new block |
| store slider maximum | — | `421` ≈ the new block's frame count |

- **`Record` opens a new block.** The previous block stays in memory and stays selectable through
  `Show block`; nothing is overwritten and nothing is flushed. A per-block `Profile` counter falling
  back to 0 is not data loss — read `Block` before concluding the recording restarted from scratch.
- **Nothing reaches the filesystem without the store action.** Verify it rather than assume: search
  for the artifact at every stage (recording, stopped, prompt open, dialog open) — no file appears
  until the store button is confirmed.
- **A store is block-scoped, not buffer-wide.** It writes the block selected in `Show block`, so a
  loop can record several points and store them one at a time — but blocks accumulate against the
  cap, so the reclaim step belongs in the plan.
- **`New acquisition` is a dismissal, not a start.** It closes the store prompt and returns to the
  stopped view; it does **not** begin recording. Keep it as the "decline to store" path.
- **A state-dependent button can raise its own confirmation.** `Remove current block` answers with
  `WARNING — All data contained in the current block removed from memory` and a button pair, and
  `New acquisition` can raise a data-loss prompt too. Re-read the state after every press instead of
  assuming it acted; a new panel is a question that must be answered (left button = cancel) before
  the loop continues.

### Loop gotchas

- **The dialog remembers the previous name and directory.** Set a fresh name for every point or
  each point overwrites the last; the directory needs setting only when it changes, and the browse
  button can be ignored entirely.
- **`Clear and restart` is the release valve; `New acquisition` is not.** The first empties and
  rebuilds the buffer — the operator sees the `Record` button absent for a few seconds, so poll for
  the button row to return before pressing `Record`. The second only dismisses the store prompt.
  Pressed from the *store* view, `Clear and restart` produced no visible change at all on one target
  (blocks and the combo untouched, every button enabled), so verify its effect from the state it
  leaves rather than from the caption, and prefer the view where it is known to act. An accepted
  press can be silent: "nothing changed" is a finding about the view, not proof the press failed.
- **Follow the app's own output directory; never watch a hard-coded path.** Read the store dialog's
  working-directory field and watch *that* folder for the new file — the field persists across stores
  and represents the app's decision, so a driver watching a constant reports "no file" while the app
  writes happily somewhere else.
- **Prove a point from its artifact, not from its field read-back.** Decode the stored file and
  assert the parameter landed there; the field echoing your write proves only that the text buffer
  changed. Read the slot the run actually used (channel / segment / block) and print which one you
  read — a neighbouring slot returns a plausible, stale configuration that looks like a refused write.
  Recipe, traps and cross-checks: `references/artefact-decoding.md`.
