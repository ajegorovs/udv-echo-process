# Mapping control ids to meaning (the reusable recipe)

An owner-drawn app gives you ids and rectangles but no labels. Labels live only in pixels, so
bind them once, by geometry, and freeze the result in a map file.

## 1. Enumerate, both backends

```bash
python scripts/win_ui_probe.py --process MyApp.exe --out probe
python scripts/win_ui_probe.py --process MyApp.exe --class TMain_Scr --uia   # compare
```

Run `win32` and `uia` and compare. Classic Win32/VCL/MFC apps usually yield far more through
`win32`; UWP, WinForms and some Qt builds yield more through `uia`. Whichever backend sees the
real windows is the one to automate with; the other is a cross-check.

Trust the **handle-deduplicated visible** count. Verify a suspicious count by grouping on
`(class_name, control_id, screen_rect)` — identical triples are the same widget reported twice.

## 2. Capture, then read the labels with vision

`PrintWindow` returns the window's own pixels; its origin is the window's top-left, so

```
image_x = screen_x - window_left
image_y = screen_y - window_top
```

For each candidate control ask vision for the captions and their approximate image coordinates
(instruct it to transcribe, not summarise), then bind each caption to the control whose
rectangle **contains the label's baselines or sits immediately beside it**: a numeric field is
the `Edit`-like control in the same row; a menu item is the `Button` whose x-range contains the
caption's x. Store the observed value alongside the binding — a binding that also explains the
current value is a binding you can trust.

Cross-check one binding against an independent fact before trusting the set. If a field reads
`4000` and the data file produced by that session carries `4000` in its own metadata, the label
you think you read is confirmed. Cheap corroboration like that is what makes the rest of the map
believable.

## 3. Toolkit fingerprints (from window classes)

| Classes | Toolkit | Expectation |
|---|---|---|
| `TApplication`, `TPUtilWindow`, `TMain_*`, `TSp_*`, `TRx*` | Delphi/VCL (incl. custom control suites) | real windows for edits/combos, **empty captions** on custom buttons |
| `AfxWnd*`, `AfxControlBar*` | MFC | standard child windows, ids often usable |
| `WindowsForms10.*` | .NET WinForms | `uia` backend is usually the better one |
| `Qt5QWindow*` | Qt | accessibility must be enabled, else class D |
| `Chrome_WidgetWin*` | Electron/Chromium | not this skill: drive page content through a browser/CDP path |

A custom-suite class name (vendor-prefixed, e.g. `TSp_Edit`) does **not** mean unreachable:
widgets derived from the toolkit's edit base are real windows, so `WM_GETTEXT`/`WM_SETTEXT` work
even when nothing is named.

## 4. Input escalation ladder

1. **Messages** — `SendMessage(hwnd, WM_SETTEXT, 0, value)` then `WM_KEYDOWN`/`WM_KEYUP` of
   `VK_RETURN` to commit. Bitness-agnostic, works unfocused and occluded.
2. **Rectangle-centre click** — resolve `ctrl.rectangle()` at run time and click its centre
   (posted `WM_LBUTTONDOWN`/`WM_LBUTTONUP`, or `pywinauto` `click_input`).
3. **Focus + keys** — only for controls the app genuinely refuses to take by message.
4. **Real input injection** (`SendInput`) with the window foregrounded — last resort: the
   machine is unusable by a person while a run is going, and a locked desktop may block it.

After each escalation, re-capture and confirm the state actually changed. Do not conclude "the
app cannot be driven" from one ignored message; climb and re-verify.

## 5. Coupled-observable verification

Pick an output the app *derives* from the parameters you set, and assert on it:

- a status-bar readout (a derived interval or count) read from a `PrintWindow` capture;
- the parameters embedded in the artifact the app writes (most measurement/instrument formats
  store their own operating parameters; prefer a vendor-supplied reader over your own parser);
- a recomputed sibling field in the form.

Keep the three-way chain `requested -> shown in GUI -> present in the artifact`, and note unit
or encoding traps: an instrument may take a *period* where you expected a rate, or store an
encoded value (a scale factor where the display shows the decoded number). Compare against the
encoding, never the raw word.

### Verifying against a fixed-layout binary artifact

1. Find the block layout and its **stride** in the vendor's own reader, then address the block for
   the channel/segment the run actually used. A block read at the base offset without a channel
   index returns whatever the *first* channel last held — frequently a stale default that looks
   entirely plausible. Two unrelated recordings carrying byte-identical first-channel blocks are
   the tell.
2. Decode two files that differ in exactly one known parameter and confirm the difference shows
   up where the layout says it should. One matching file can be coincidence; two is a decode.
3. Expect the same physical quantity to be stored encoded (an integer scale, a period instead of
   a rate, tenths of a unit). Compare *decoded meaning with tolerance*, never one raw constant:
   the same `s = 1.00` was stored as `3141` in one recording and `3142` in another, so a
   strict-equality check would fail half the fixtures.
4. Reconcile against a second independent derivation before trusting the decode — the vendor
   reader, the manual's own parameter table, and an already-decoded fixture from another project
   should agree. When they disagree, the disagreement is the finding; record it rather than
   picking the source you like.

## 6. Map file schema

```json
{
  "app": { "exe": "...", "version": "...", "ui_toolkit": "...", "bitness": "32-bit process",
           "main_window": { "class_name": "...", "title": "..." } },
  "parameters": { "<field label>": { "control_id": 123, "class_name": "...", "kind": "numeric|enum",
                                     "rect_at_capture": [l, t, r, b], "observed": "..." } },
  "menu_bar": { "<item>": { "control_id": 123, "class_name": "..." } },
  "status_bar": { "_note": "painted, not a control: read it from a capture" },
  "not_exposed": { "<thing>": "painted by the parent; needs coordinates" },
  "pitfalls": [ "..." ]
}
```

Record `rect_at_capture` as evidence, never as the addressing mechanism, and note the window
origin used for the capture. A binding should carry a **role** — `class_name`, containing panel,
order within it — and not just a `control_id`, which does not survive a restart (§8). Add a `pitfalls` array — it is what stops the next session
re-committing the same wrong assumption.

## 7. Map provenance, required flags and the geometry fingerprint

A map is only as good as the instance it was captured on. The same executable presents different
controls depending on state — simulation/demo mode with no device attached, an unlicensed build
missing a package the demo pretends to have, a different instrument — so record **what was
attached when you captured it** and treat the map as a hypothesis elsewhere.

Add these to the map:

- `capture_context` — mode (`simulation`/`demo`/`instrument`), whether hardware was attached, and
  a line naming which bindings that makes mode-specific.
- `required: true|false` per binding — `false` for anything mode- or licence-dependent, instead
  of deleting it, so a pre-flight check reports *absent (optional)* rather than failing.
- `verify_on_attach` — the checklist to re-run on a new instance: pre-flight check, a fresh probe
  capture, and a diff of the new dump against the baseline committed from the capture session.
- a `geometry` fingerprint produced by the checker, alongside the recorded rectangles.

### Pre-flight check to run before the driver writes anything

1. Attach and find the main window by **class name**, never by title — a simulation build appends
   a suffix and licence-dependent title text is not stable.
2. For every binding resolve `(class_name, control_id)` among visible, handle-deduplicated
   descendants; report found / missing / unknown-not-in-map.
3. Confirm the text still matches the declared `kind` (numeric vs enum). A field that changed kind
   is usually a different field.
4. Emit the geometry fingerprint and compare it with the one recorded at validation:
   - `client_size` from `win32gui.GetClientRect(hwnd)`
   - `dpi` from `ctypes.windll.user32.GetDpiForWindow(hwnd)`
   - minimized/maximized from `ctypes.windll.user32.IsIconic` / `IsZoomed` — **`win32gui` does not
     expose `IsIconic`/`IsZoomed`**, so go through `ctypes`
   Fail on `IsIconic` rather than on a blank image: a minimized window renders blank under
   `PrintWindow` and reports meaningless rectangles.
5. Write the run's result (found/missing/unknown/geometry) to JSON so instances, modes and
   sessions can be diffed instead of re-argued.

Maximizing is a reasonable convention — it makes the painted status bar cheap to crop
reproducibly — but it is **not** what makes the driver correct. Correctness comes from a **role resolved to a live handle** plus a rectangle resolved at run time, with `PrintWindow` for state. Only the real
input-injection rung of §4 needs the window foregrounded and the machine left alone; the message
path does not.

## 8. Bind by role, not by id

Measured, same executable, two launches: 43 visible controls in both, **43/43 classes at the same
sorted position, 1 of 43 ids in common**. The survivor was a real Win32 `Edit` with a dialog id;
every custom-suite widget received a fresh handle. So an id-keyed map passes every check inside the
process that captured it, returns nothing after a restart, and any driver that caches `pywinauto`
child wrappers at startup breaks on its second run.

A role is a stable key that resolves to a live handle:

```
role = (class_name, containing panel, order within that panel)
```

1. Enumerate visible, handle-deduplicated descendants of the main window.
2. **Group by immediate parent panel, not by fractions of the window.** Toolkits put each cluster in
   its own panel; panels are children of the main window in a deterministic top-to-bottom order
   (measured: menu bar, left parameter panel, a strip floating over the plot, bottom status bar).
   Panel ids change per launch like everything else, so identify a panel by its **order** and address
   children by `GetParent(hwnd)` equality rather than by a containment test alone.
3. Inside a panel, order by one axis: `left` for a row, `top` for a column, and map that order onto
   the role names you read off a capture.
4. Keep a **clipped guard**: a child whose rectangle falls outside its parent's client area is never
   painted and cannot be clicked, yet still reports `IsWindowVisible` and a rectangle. It must not
   count toward "which widgets exist".
5. **A dialog is a panel too.** Identify it structurally — a panel that *directly owns* an edit plus
   a Browse-style button — not by position, so it is found wherever it was dragged. Its edits are
   real windows, so `WM_SETTEXT` sets output paths and numeric fields alike.

Traps that cost a cycle each:

- **A band expressed as a fraction of the client height is not stable.** One button strip sat at a
  fixed client `y ≈ 472` while the client height went from 819 to 1027 when the window was
  maximized — 58 % to 46 % of the height, crossing any 50 % or 60 % cut. Band on geometry relative
  to the *parent*, or on the panel a widget belongs to.
- **"The panel with the most buttons" is not the toolbar you want.** An open menu popup is itself a
  panel full of buttons near the menu bar and wins that vote. Take the candidate whose centre lies in
  the expected zone (for a strip floating over a plot: the middle third of the plot rectangle).
- **`GetClientRect` always returns `(0, 0, w, h)`.** Its left/top are not the client's screen origin;
  get that with `win32gui.ClientToScreen(hwnd, (0, 0))`. Using the window rect's top-left shifts every
  relative coordinate by the frame height and silently moves widgets out of their band.
- **Order tidy rows by one axis, not `(top, left)`.** One menu button sitting a pixel higher than its
  neighbours reordered the whole row in a `(top, left)` sort.
- **Fingerprint the layout.** The clean measurement screen held exactly 43 visible controls in 4
  panels across two independent launches; any other count names what is extra (open popup, dialog,
  simulator-only screen) and can be normalised away before roles are resolved. This turns "the map
  does not match" into "a menu is open".

## 9. Reading a value table by position (and when to distrust the binding)

A dialog that states its values as a label-less grid — one wrapper widget per row with the value
*inside* it — can be read with no gesture at all, but only by position, and position is the binding
most likely to return a plausible wrong number. Three things have to be measured before it is worth
trusting.

**1. The values sit one level inside the row wrappers, so walk the surface.** A dialog's *direct*
children are its row wrappers, its header and its footer buttons, and not one of them states a
value. Measured: a 627x384 dialog had 21 direct children — 15 value-buttons, a header combo, footer
buttons — and every value lived in the edit or combo **inside** its own wrapper. A reader written
against the resolver's child enumeration therefore found *no table at all*, and its refusal ("stated
no value") named a state rather than a cause. Walk the surface live (`GW_CHILD` → `GW_HWNDNEXT`,
recursing) when the values are nested, and make the failure path print the **child count by class** —
that count is the difference between a diagnosis and a mystery.

**2. A row that offers a choice states its value in the choice control.** Where a row holds a combo
*and* an edit beside it, the combo's selected value is the parameter and the edit is a **different,
derived quantity**. Measured: the burst row read combo `4`, inner `4`, and edit `89` — the 89 being
the sampling volume that window is documented to display (0.876 mm at a 1460 m/s sound speed), not
the burst. So bind the choice control when the row has one, and **never fall back to its neighbour
when the choice is unreadable** — the row is then unreadable, because the two controls are different
physics. Prove the rule survives **enumeration order**: controls come back in creation order, which
is not the layout's order, so a case that only ever sees the real order lets a "first control in this
row" implementation pass for the wrong reason (measured — it did, until the case reversed the order).

**3. Confirm every position against a second surface, and keep the two refusals apart.** Choose the
facts the dialog and another surface *both* state (here seven: emitting frequency, PRF, gate count,
resolution, emissions per profile, Doppler angle, velocity scale), and require all of them to read the
same text on both before any positionally-read fact is believed — a re-laid-out dialog puts a
different value in the same cell while still reading exactly like a value. Then check the table's
**shape**: the number of fields per column is a measured constant, and a table that no longer builds
it is not the table the positions were bound in. Two refusals come out of this and they must not be
merged: **uncheckable** (one surface does not state the anchor at all — an assisted-mode screen has
no parameter column) versus **disagreement** (both state it, the texts differ). Different faults,
different fixes, and the run record has to say which happened.

**A fresh instance builds this table empty on the first open.** Measured: the first open after a
restart read 2 stating controls where the next read 22 — the table is filled once the dialog has been
up. Poll for the fill with a bounded timeout, then record *which* of the two states was seen: an empty
field is not a value, and taking the first empty answer as the answer turns three readable settings
into three "unreadable" ones.

**And the read-failure policy is not the unreadable policy.** Once a setting has a supported read
path, "this attempt failed" and "nothing in this driver can read it" need different execution
consequences: a supported read that fails **refuses** the run (fail closed), while a genuinely
unsupported setting is carried as unproven and does not block it. Keep the table of which facts have
a read path next to the readers and let the pre-run check consult it — otherwise a failed read
degrades silently into "declared", which is the check passing without having run.
