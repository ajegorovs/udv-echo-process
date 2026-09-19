# The DOP3010 measurement screen: what it paints, and what a mode moves

Read-only observations of the 6.07.x instrument in **real-experiment mode**, taken from window-tree dumps,
the probe's own full frames and crops, and the operator's own vision of open dialogs. Bindings age: re-verify
a rectangle against a fresh live read before pressing, per the rules in SKILL.md.

> **Authority (frozen 2026-09-18).** The repository's surface model is
> `docs/dop3000/acquisition-ui-model.md`, and the painted captions quoted here are the committed
> crops' business (`docs/dop3000/ui-element-index.md`, cited by crop id). Where this file and the
> repository documents disagree, the repository documents decide.

## The left parameter column

The **labels are painted**, not controls — the tree gives the row *values* with `role=None` for every row, so
this list comes from a frame, not from a read. The values are the control texts.

| row | control shape | values seen |
|---|---|---|
| `Channel` | row of red digits 1–10, the active one highlighted | 1 |
| `US Frequency [kHz]` | edit | 4000 |
| `PRF [us]` | edit | 600 (the same quantity the definition calls `prf_us`) |
| `Nb of gates` | edit | 50 |
| `Resolution [mm]` | edit | 1.850 |
| `Velocity scale factor` | edit | 1.00 |
| `Emissions/profile` | edit | 20 |
| `Doppler angle` | edit | 0 |
| `Tgc [dB]` | value button + cell | 20, 40 — **painted only while the TGC mode is `Uniform`** |
| `Sensitivity` | combo | medium (very high … very low) |
| `Emitting power` | combo | Medium (low / medium / high) |

The bottom two rows each nest an extra edit reading `89` inside the combo's own rectangle: a control inside a
control, not a row — count rows by the painted labels, not by the edit list.

## TGC: where the mode is set, and what it moves

- **The editing surface is `Tools → Define TGC`**, a movable caption-less overlay (small black triangle
top-left, the same family as every other popup here). Its **field set depends on the mode selected inside it**:
  - `Uniform` → a `Start [dB]` edit and **no** `Recompute`;
  - `Auto` → a `Recompute` button and **no** `Start [dB]`;
  - both → the mode dropdown `{Uniform, Slope, Auto, Custom}`, two mutually exclusive checkboxes
    (`Profile and Tgc` / `Echo and Tgc`) choosing what the monitor paints (left plot `Velocity` or `Echo`,
    right plot always `Tgc` vs depth), and `Cancel` / `Accept`. `Accept` commits; `Cancel` is the read-only
    gesture.
  So re-resolve the dialog's children after changing its mode control, and never assume a control you saw once
  is still there.
- A hidden `TComboBox` at `[434,182,498,203]` (inside a hidden value button inside the hidden panel
`[400,168,850,288]`) states the **mode word**, hidden in every mode. It is a press-free read of the mode and
it moves in lockstep with the setting; a mode read out of the *dropdown* is not the same thing, because that
control opens on a default rather than the stored state.
- The sidebar's `Tgc [dB]` row mirrors the overlay's `Start [dB]`, and its **presence tracks the mode**:
measured on one instrument minutes apart, `Uniform` read **44** visible controls with the row present (two
controls — a `TSp_Value_Button [10,325,105,349]` plus its cell), `Auto` read **42** with the row absent. A
single *setting* therefore moves a total visible count by two, which is the measured argument against using
one as a cleanliness gate or in any identity that decides whether two runs used the same instrument.
- The same instrument's menubar is one button shorter than the reference install's, so a 43-vs-44 comparison
across two *processes* mixes three differences at once — window mode, TGC mode, and bar composition. Check
all three before attributing a delta to any one of them.

## The menubar

- The reference install paints **eleven** buttons: `File Preferences Parameters Compute Cursors Filters Tools
Channels UDV mode Display Help`.
- The instrument paints **ten**: `UDV mode` is never rendered, while the tree still names the buttons
positionally from that eleven-name list — so the late names resolve to the wrong widget or to nothing, and
early names stay correct (why the `Parameters` hover gesture still works).
- Every one of those buttons carries `text: ''` in the tree, so only a frame can say which name a button is
painted with.

## Overlays and toggles seen on this build

- `Operational parameters` — the dialog the `Parameters` menu opens, and the surface the parameter write
recipes drive.
- `Tools → Define TGC` — above. While it is up the **record strip is not painted** and the monitor splits into
side-by-side plots, so no read taken with it open is comparable to one taken with it closed.
- The `Preferences` menu carries the **assisted-mode toggle**, and toggling it rewrites the acquisition frame —
measured, `PRF / gates / resolution / velocity scale / emissions` all moved together (to
`296 / 726 / 0.123 / 0.49 / 150`) in one step. That set is exactly the quantities the assisted compromise
owns, so a frame comparison taken across such a toggle measures the toggle: ask the operator what else they
touched before attributing a change to the variable under study.
