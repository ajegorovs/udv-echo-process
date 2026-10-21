# UDOP automation — driving a DOP3010 sweep unattended

How a sweep point is **set, recorded, stored and validated** with nobody at the
console: the write recipes that actually commit, the order they must be written
in, the record strip's state machine, the store chain, and the failure modes
that silently invalidate a point.

> **Authority (added 2026-09-18, documentation freeze).** This document is the single
> authoritative copy of the **mechanism**: what commits a value, in what order, the strip's
> state machine, the store chain and the failure modes that invalidate a point. It is *not*
> the authority for the subsystem's architecture and invariants
> ([`acquisition-architecture.md`](acquisition-architecture.md)), for surfaces, widgets and
> bindings ([`acquisition-ui-model.md`](acquisition-ui-model.md)), or for the device
> verification procedure ([`device-verification.md`](device-verification.md)); where a caption
> is quoted below, the committed oracle is
> [`ui-element-index.md`](ui-element-index.md) and the quote carries its crop id. Nothing in
> the body of this document changed at the freeze — this header is the only edit.
>
> **Status:** the rules marked *(measured)* are verified on a live DOP3010
> running UDOP 6.07.4 (instrument-side control session, 2026-09-17). Statements
> that are inference rather than measurement are marked *(hypothesis)*; §11
> lists what remains open.
>
> **Scope:** the instrument as an **actuator** for a parameter sweep. The
> parameter plan itself — which axes to sweep, which to co-set, which to freeze
> — is [`parameter-sweep-matrix.md`](parameter-sweep-matrix.md); this document
> supplies the mechanism and the read-back that plan assumes.
>
> **Evidence:** the private instrument-side control repository
> (`~/Repos/dop-control`, **retired 2026-09-18** and archived at
> `~/Repos/_archive/dop-control-20260918.zip` — see
> [`recon-archive-retirement.md`](recon-archive-retirement.md)) — `docs/14-input-methods.md`,
> `docs/15-labelled-fixture.md`, `docs/16-record-strip-automation.md`, and the
> `recon/` scripts those documents cite (`recon/05`, `08`, `14`, `30`,
> `33`–`35`, `40`–`42`) with their JSONL logs and captures. Nothing below is
> inferred from the manual alone, and nothing below should be re-derived from
> the manual instead of read here; a `recon/NN` citation names a probe in that
> archive, not a dependency of this repository.

---

## 1. The chain, and what a point is

A sweep point is a **duration in seconds**, not a profile count (§8):

```
set the parameters  →  Record  →  wait T s  →  Stop  →  Do store  →  decode
```

Only the last step proves the point. The `decode` step reads the stored `.BDD`
and compares the parameters the *instrument used* against the parameters that
were *requested*; a control's displayed text is not evidence (§2).

Measured end-to-end cycle (a `recon/30` run):

```
START  view=stopped  panel=(448,477) 352x40  buttons=[(458,79),(547,85),(642,138)]
press Record (x=547)  -> view=recording   strip collapsed to one 68 px button
record 5 s
press Stop   (x=458)  -> view=store       panel 413x123, slider present
press Do store (x=602) -> Store dialog open at (676,391) 584x330
set File name = 'auto-cycle-1'
press Do store (dialog, rightmost) -> STORED  .../auto-cycle-1.BDD  108,865 bytes
```

The stored file decoded to the expected channel-10 point, so it is a real
recording, not an empty shell. The cycle has since been run as a two-point sweep
with parameter changes between the points (§9), and as six consecutive short
cycles of one parameter set (§7).

---

## 2. What commits, and what silently does not

| target | mechanism | commits? |
|---|---|---|
| numeric edit field (sidebar parameter column, dialog numeric fields) | `WM_SETTEXT` + `WM_COMMAND(EN_CHANGE)` to the parent + `WM_KEYDOWN(VK_RETURN)`/`WM_KEYUP(VK_RETURN)` | **yes** *(measured)* |
| combo box (sidebar and dialog) | `CB_SETCURSEL` + `WM_COMMAND(CBN_SELCHANGE)` | **yes**, no Enter needed *(measured)* |
| record-strip widgets (`Record`, `Stop`, `Do store`, `Pause`, `Clear and restart`) | posted `WM_LBUTTONDOWN` (client coords, `MK_LBUTTON`) + **~180 ms hold** + `WM_LBUTTONUP` | **yes** *(measured)* |
| dialog / modal-alert buttons (`Accept`, `Cancel`, `Continue`, the Store dialog's `Do store`) | posted held click | **yes** *(measured)* |
| menubar buttons (`Parameters`, `Tools`, …) | **hover only** — the overlay opens on mouse-over, and a click after the hover *closes* it | n/a |
| menu overlay entries | posted held click on the entry's handle | **yes** *(measured)* |
| `WM_SETTEXT` alone, or `WM_CHAR` Enter | — | **no** — the control shows the value, the application keeps its own |
| injected real input (`SetCursorPos` + `mouse_event`) as a *click* | — | **no** |
| injected real input as a **hover of a menubar button** | `SetCursorPos` onto the button's centre + a relative `mouse_event` move | **yes** — the one interaction posted messages cannot drive at all *(measured)* |
| posted down/up inside the same millisecond | — | **no** |

Two consequences organise everything else:

1. **The commit is the key event, not the text write.** `WM_SETTEXT` alone
   changes what the widget paints and reverts; the operator's own description is
   the rule — *a line-edit needs Enter to confirm, else it reverts*. `WM_CHAR`
   Enter does **not** work.
2. **Verify against the application's model, never the control.** The decisive
   read-back is the stored `.BDD` (§9). The cheapest in-dialog read-back is a
   derived field the widget cannot fake — e.g. `Depth = first gate + gates ×
   resolution`, which moved 27 → 14 mm when the gate count was written.

*(Corrected, and worth keeping as a caution:* an earlier session concluded that
the sidebar's parameter fields do not accept a programmatic write at all. That
verdict is **withdrawn** — the decode that "disproved" it had read the *wrong
channel's* block. Sidebar writes commit; see §6 on the channel trap.)

**Combo writes can silently apply.** Writing `Sensitivity = very high` worked,
but writing it back to `medium` set the control while the application kept
painting `very high`. Read the painted value or the file — `CB_GETCURSEL` only
reports what the control believes. And do not read a combo through
`WM_GETTEXT` on its inner edit: it returned the same stale string (`89`) in
three unrelated combos.

**Never block on a cross-process `SendMessage`.** Use
`SendMessageTimeoutW` with `SMTO_ABORTIFHUNG` and a ~2 s budget, so the driver
reports a busy application instead of hanging with it.

### 2.1 The one dialog parameter this repository writes: burst length

The `Operating parameters` dialog's burst row is written by
`udv_echo_process.acquire.udop.parameters.write_dialog_burst_length`
(`uv run udv-acquire burst-length <N> --channel N`), and it is a *transaction*,
not a field poke — the recipe is §18.9/§18.10/§19.1 of
[`acquisition-campaign-compilation-plan.md`](acquisition-campaign-compilation-plan.md)
and the plan it serves is [`burst-length-control-plan.md`](burst-length-control-plan.md):

* `CB_SETCURSEL` + `WM_COMMAND(CBN_SELCHANGE)` **to the combo's parent** — the
  selection is by the entry whose own text **is** the request, never by counting
  steps from the value in force, and `CB_SETCURSEL` alone would set the
  control's belief and leave the model alone;
* the dialog is committed with its bottom band's **rightmost** button and
  refused with the one before it, so a refusal leaves the application where the
  dialog found it — a write left with the `Cancel` commits nothing (measured);
* the read-back is taken from a **re-opened** dialog: the dialog that was
  written states what precedes the commit, and it can state a selection that was
  never kept at all;
* the **sampling volume is read, never written**. A burst change does not
  re-select the volume; it re-derives the floor the volume has to clear,
  `floor(N) = 1000·c·N/(2·f_e)` (the manual's own length, §20.1 of the same
  plan), and the value in force is `max(remembered, floor)` — `4 → 8` with
  `0.876` remembered states `1.460`, `8 → 4` states `0.876` again, because a
  floor-raise is not a remembered write. The volume's option list is `[the value
  in force] + a fixed six-entry tail`, so the application can state a volume its
  own combo does not offer;
* a request below the floor raises the caption-less modal warning whose one
  button applies nothing. This driver answers a warning with its **left** button
  and refuses the transition; an overlay it has no answer for is named and left
  standing, never guessed at.

`word 8` (burst) and `word 27` (the volume **index**) remain the oracles a
stored point is checked against — §9 — and no measured law relates the dialog's
millimetre statement to the stored index yet.

---

## 3. The write-order rule

**Write the structure-determining parameter first, the one the app derives from
it last — then read back before recording.**

Measured, same requested point, two write orders:

| order | requested | control read-back | stored `.BDD` | depth |
|---|---|---|---|---|
| gates, then resolution | 805 gates @ 0.1217 mm | **474** gates | 474 gates | 59 mm (target 100) |
| **resolution, then gates** | 805 gates @ 0.1217 mm | **805** gates | 805 gates | 100 mm |

Cause: this channel had the manual's *auto resolution mode* and *auto selection
of number of gates* flags set (words 11/12 = 1), so writing the resolution makes
the application recompute the gate count and silently trim the gates just
written. The recomputation is **visible in the control text** (474, not 805), so
a pre-record read-back catches a clamped point without spending a recording or
leaving a junk file behind. The driver prints a note when the gate count moves
by more than 5 % of the request.

Rules that follow:

- Write **resolution (and first gate) before gate count**; re-read both.
- The plan's ladder rung depends on the **real `c`**, not the intended one —
  recompute the sweep table from the read-back `c` before the next run.
- Sidebar values display with **3 decimals**: writing `0.121667` shows `0.122`.
  That is the app's rounding, not a failure — write 3-decimal values and take
  the achieved resolution from the file.
- The achieved resolution is recoverable from the file:
  **word 10 is the 0-based resolution rung index**, and

  ```
  resolution_mm = (word 10 + 1) × c / 12000
  ```

  verified as `4 → 0.6083 mm` at `c = 1460` and `1 → 0.250 mm` at `c = 1500`.
- The app writes its own derived window to **word 2**, so the depth can be checked inside the
  file without re-deriving the physics. What word 2 holds is the window's *last* gate —
  `first gate + (gates - 1) × pitch`, rounded — not the dialog's `Depth` one pitch beyond it
  (`dop3000/handoff-dop3010-acquisition.md` §3, measured on the committed sweep; the two
  coincide inside the rounding only at rungs narrower than the check's 1.5 mm tolerance).

**Burst length is a dialog-only write.** There is no sidebar field for it, so
any burst sweep must drive `Parameters → Operating parameters`. Changing it
**auto-updates the `Sampling volume` dropdown** (a larger burst raises the
volume; a smaller one selects the minimum entry), and the allowed values are
physics-driven, so they change with `c` and `f_e` — never hard-code a
millimetre value, read the dropdown. Requesting a volume *below* what the burst
allows raises `Warning — The burst length should be reduced [Continue]`: that is
a rejection, not a crash, and it is answered like every other overlay (§6).

---

## 4. The record → stop → store chain

1. **Start from a verified `ready` state.** Resolve the strip structurally (§5)
   and refuse to start from `recording` — a leftover recording contaminates the
   next stored block (§7).
2. **`Record`** — measured: this opens a **new block**. Nothing is dumped to
   disk or out of memory; the previous block stays in memory and stays
   selectable in the store view's `Show block` combo (`['1'] → ['1','2']`), and
   the status-bar `Profile` counter restarts **per block** (1948 → 420), not
   cumulatively.
3. **Wait the point's duration `T`.** Seconds define the point (§8).
4. **`Stop`** — the panel grows to the store view (413x123 here; `269x123` in
   the two-button row of §5) and a `TSp_Sliding_Bar` child appears.
5. **`Do store`** on the strip opens the **Store dialog**. It is not a top-level
   window — it is a **child panel** (e.g. `(676,391) 584x330`), which is why an
   `EnumWindows` check reports "nothing happened":

   ```
   Store                                    [Browse]        <- optional
   Working directory [<capture directory>]                  <- TEdit
   File name         [sim-label-2]                          <- TEdit
   Comments          [Memo_Comments]                        <- TMemo
     Add an ASCII file containing all data values           <- optional toggles
     Add an ASCII file containing only statistical values
                               [Cancel]  [Do store]         <- 80x25
   ```

   `Browse` can be ignored entirely. **The working directory persists from the
   previous store**, so it only needs setting when the target folder changes;
   the **file name does not** — it keeps the previous name, so a sweep must set
   a fresh, unique name for every point or points overwrite each other.
6. **Set `File name`** with the numeric/text recipe (§2), then press the
   **rightmost bottom button** (`Do store`).
7. **Handle the overwrite warning.** A repeated name raises
   `WARNING … file already exists → replace? [No] [Yes]`, which the driver must
   answer — press the **left** button (`No`) so an existing file is never
   silently replaced, then retry with a fresh name. Without that handler the
   store never completes and the application is left **modal** (the strip becomes
   unusable behind it), which is exactly what happened once. Name every point
   uniquely — include the sweep id and a timestamp.
8. **Nothing reaches the filesystem before that button is pressed.** Searched at
   every stage (record, stop, store prompt, dialog open): no new `.BDD` until the
   dialog's button is pressed. Detect completeness, not arrival — wait for size
   stability before decoding.
9. **`Do store` is block-scoped, not buffer-wide.** It writes whichever block
   `Show block` has selected, and the store slider's maximum equals **that
   block's** profile count. Successive points are therefore separable in memory
   and each stored file holds exactly one point's block — but blocks accumulate
   up to the configured cap (§7).
10. **Verify by decoding the stored file**, naming the channel explicitly (§6).
    The `.BDD` op-parameter block (words 0–95) *is* the sweep log; the status-bar
    `Profile` counter is not trustworthy for pacing.

**The `Stop` gesture above is the single-channel recipe, and MPX does not inherit it.** During a
multiplexed acquisition there is no `Stop`: `Clear and restart` and the Channels menu's
disable entry are the only operator routes out (§12.13). A manual `Record` in an MPX idle row does
not raise `Stop` either, and what that idle row *is* depends on the roll-over toggle at enable time
(§12.13): roll-over **on** leaves `Pause` / `Record` / `Clear and restart`; roll-over **off**
auto-arms and records on enable. No tree read of the active MPX row exists, so the MPX stop gesture
is unresolved (ledger B21) and this chain's step 4 must not be posted there (§5). What *was*
verified for MPX is the store half — step 5 onward — and it was verified with the recording already
completed by the operator or by `record-multiplexed` (§§12.6–12.7).

**Strip buttons outside the record cycle:**

- `New acquisition` — dismisses the store prompt and returns to the recording
  view; it can raise a data-loss warning. It is **absent** from the two-button
  store row a multiplexed run ends in (§5), where asking for it is a refusal.
- `Remove current block` — deletes the selected block, guarded by
  `WARNING — All data contained in the current block removed from memory`, whose
  `[Cancel]` is the left of its button pair.
- `Clear and restart` — the release valve between points. Pressed in the
  no-slider view, the operator sees `Record` disappear and the strip collapse to
  two buttons for **~3–4 s** while the buffer is rebuilt, so the loop must
  **poll until the `Record` button is present again** before pressing `Record`.
  Pressed from the *store* view it produced no visible change here, so its effect
  is view-dependent: press it in the no-slider view, then poll. In the two-button
  store row it is the **right-hand** button, and no press on that row has been
  measured — only the position/role binding is (§5).

---

## 5. The strip's view states — recognise structurally, press by order

The strip is a **draggable floating panel**, and its own rectangle changes with
the view (`352x40` → `98x40` → `413x123`, and `269x123` for the two-button store
row measured on 2026-10-20). Locate it **structurally** (the parent of the
recording widgets), never by remembered coordinates, and re-resolve after every
press.

| view | how to recognise it | buttons, left → right |
|---|---|---|
| recording | 1 top-row button, no slider | `[Stop]` — *single-channel only; in an MPX configuration the same structure was operator-reported as `Clear and restart`, so this row binds nothing there (below)* |
| stopped, no data | fewer than 3 top-row buttons, no slider | `[Record]` — *live-reported; only the 1-button row is bound, so 0 or 2 buttons classify `unknown` and nothing is pressed* |
| **stopped with data** | 3 top-row buttons, **no** `TSp_Sliding_Bar` child | `[Pause] [Record] [Clear and restart]` |
| **store view** (after `Stop`) | 3 top-row buttons **+** a `TSp_Sliding_Bar` child | `[New acquisition] [Do store] [Clear and restart]` |
| store view, four buttons | 4 top-row buttons **+** a `TSp_Sliding_Bar` child | `[New acquisition] [Do store] [Clear and restart] [Remove current block]` |
| **store view, after a multiplexed run** | **2** top-row buttons **+** a `TSp_Sliding_Bar` child, plus the block/channel `TComboBox` pair | `[Do store] [Clear and restart]` |
| **store view, after a repeated multiplexed run** | **3** top-row buttons **+** a `TSp_Sliding_Bar` child on a `477x123` panel, painted widths `91 / 138 / 198`, plus the block/channel `TComboBox` pair | `[Do store] [Clear and restart] [Remove current sequence]` — *accepted only when that exact measured geometry selects `StripRowVariant.REPEATED_MPX_COMPLETION`; a three-button row without it stays the legacy row above and is refused* |
| stopped with data, four buttons | 4 top-row buttons, **no** slider | **nothing — the roles are unresolved**, and the row is refused (below) |

**The row's length is part of the binding, not a detail of it.** `Do store` is
slot 0 in the two-button row and in the repeated-run row below, and slot 1 in both
legacy longer store rows, so a press
keyed on a fixed position — or on a width — lands on `New acquisition` or on a
neighbour. The count is taken from the **visible** top-row buttons only.

**The two-button store row is where a multiplexed run ends** *(measured
2026-10-20)*. A read-only control-tree capture on the instrument (`UDOP
DOP3010.43`, multiplexer sequence probe) shows the strip panel built `269x123`
holding two visible top-row `TSp_Button` widgets (91 px and 138 px wide — again
too close to tell apart by width), the visible `TSp_Sliding_Bar`, and two
`TComboBox` children for block and channel; two further buttons are painted
*behind* the row at the same height with `visible: false` and are not part of it.
The slider had already classified that structure as the store view, so the view
was reachable while this table carried no row for its length — a `Do store` press
out of exactly the state an MPX run ends in **raised instead of committing the
store**. The two roles are `Do store` (left) then `Clear and restart` (right),
and their provenance is narrow: they were **read by hand off that captured frame,
not landed by a press** — the capture fixes which position means which role, and
says nothing about how the instrument answers it. `New acquisition` and
`Remove current block` are absent from this row by measurement, not by choice;
asking for either here is a refusal.

**A repeated multiplexed run was measured to end in a three-button store row**
*(2026-10-21, read-only tree capture of the same instant as
`outputs/live/top-level-windows-full-a.png`)*. The panel is `477x123` with three
painted `TSp_Button` widths of 91, 138 and 198 px, the visible slider and the
block/channel `TComboBox` pair; the frame paints `Do store` / `Clear and restart` /
`Remove current sequence` across them, and the tree's button text is empty. It is
recorded as its own variant, `StripRowVariant.REPEATED_MPX_COMPLETION`, selected
by **exact** match on that measured signature — panel size and all three widths.
`Remove current sequence` is its own role and not `Remove current block`: the two
captions were never compared on one screen, and no command presses either.

**What the store paths accept is then exactly two measured rows, each on its own
evidence.** `store-completed` and `record-multiplexed` share one predicate
(`store_completed.is_completed_row`) over `_COMPLETED_ROWS`: the two-button row
above and the repeated-run three-button row above. Neither is accepted by its
length or by an inferred caption: the three-button row is accepted only when its
measured geometry selected `REPEATED_MPX_COMPLETION`, so the legacy
`New acquisition` / `Do store` / `Clear and restart` store row — `Do store` in slot
1 — and any unmeasured three-button row are refused by name with nothing pressed,
as are every four-button row, a non-store view and a missing slider. `Do store` is
slot 0 in both accepted rows, which is the only fact the press depends on.

**The one-button row means `Stop` on a single channel and is unresolved in MPX.** With rolling MPX
enabled and roll-over **on** (the ready row), the operator reported on 2026-10-21 that a manual
`Record` leaves a sole `Clear and restart` button — not `Stop` — and the operator's route out of an
active MPX acquisition is `Clear and restart` or the Channels menu's disable entry, never `Stop`
(§12.13). That is an *operator report* plus a §12.7 one-button active-row observation, not a role
read, so the role in that state is unknown (`acquisition-ui-model.md` ledger B21). This is not the captured two-button
store row above — that capture is the naturally completed MPX store view, while this report is the row during an
active acquisition, so the two observations are separate. Because the two readings are
structurally identical — one top-row button, no slider — the classifier cannot separate them, and
this table's `[Stop]` must not be applied to an MPX configuration: pressing `STOP` there would
clear the block. The `STOP` binding stays **single-channel**; for MPX the only rows this document
binds from evidence are the two completed store rows above (two-button, and the repeated-run
three-button row by its measured signature), and the 1-button MPX state has no binding of its
own, so nothing may be posted from it by generic classification.

**The four-button, no-slider row presses nothing.** `UI-STRIP-01`
(`ui-crops/run-controls.png`) paints `Pause` / `Record` / `Clear and restart`
for the *three*-button row, while `UI-STRIP-02`
(`ui-crops/overlay-record-extra-block.png`, the grown state) paints
`New acquisition` / `Do store` / `Clear and restart` / `Remove current block`
for this one: the third slot is demonstrably the same button in both frames, the
first two are not. No tree of that state exists, so the row has **no binding at
all** — it classifies as its own ambiguous view (`StripView.AMBIGUOUS` in
`acquire/actuator.py`), `strip_controls` / `press_index` refuse it by name, and a
press is refused *before* anything is posted. `device-verification.md` V4 is
where a live tree settles it (ledger B10).

- **Identify buttons by their ORDER in the view, never by width.** 134 px vs
  138 px was the difference that once produced a data-loss warning, and the
  two-button row's 91 vs 138 is no better.
- The strip's child list is **not** the three buttons you can see — it is up to
  ten windows, including state-specific buttons, the store slider, two combos,
  and buttons the panel never paints. The row is counted from the **visible**
  children: the 2026-10-20 capture carries two buttons behind the row at the
  same height with `visible: false`, and counting them would make that row four
  wide (an earlier store view carried two below the panel's rect instead).
- The buttons are real, enabled, visible `TSp_Button` child windows
  (`IsWindowEnabled` true, nothing covering them — `WindowFromPoint` at each
  centre returns the button), so an unreachable-looking control is a *recipe*
  problem, not a disabled control.
- The store slider's maximum doubles as a free "how much is there to store"
  read-out: it equals the selected block's profile count and its cap.

---

## 6. Traps

- **Posted clicks ignore modality.** A posted `WM_LBUTTONDOWN`/`WM_LBUTTONUP`
  reaches the window it names **even when a modal panel covers it** — a script
  once pressed a strip button *behind* an open warning panel, which the operator
  could not even see. **Rule: look for an overlay before every press.** Find it
  structurally — walk the main window's child panels topmost-first, skip the
  four known clusters (menubar, parameter column, strip, status bar) and treat
  any remaining panel with bottom buttons as an overlay to answer first. Press
  the **left** button of the pair: `Cancel` is the left of the bottom-right pair
  in every dialog seen in this application.
- **The app confines the cursor inside its popups** (`ClipCursor` signature).
  Menu entries that open `Parameters` dialogs capture the pointer; so do the
  `Tools` warnings about needing channel 1; and the **Store dialog clips the
  pointer to its own rect** (measured `(676,391)-(1260,721)`, released on
  `Cancel`), which is why the driver must always close it. Two consequences:
  message-based input is immune (posted messages never consult the cursor
  position, so the driver works with the pointer trapped anywhere), and a dialog
  left open **traps the operator** — `ClipCursor(NULL)` is the escape hatch if
  the app wedges. Test capture **behaviourally**, not with `GetClipCursor`
  alone: move the cursor somewhere no dialog is and read it back; a pointer that
  is not where it was put is confined. Run that probe **after** the interaction
  of interest — moving the cursor closes a hover menu.
- **The channel trap.** A stored `.BDD` holds an independent configuration per
  channel; reading the wrong channel's block "disproves" a write that worked. In
  the measured run the sidebar parameter column edited **channel 1** while the
  status bar read `CH: 10`. So: the decoder has **no safe default** — always
  name the channel, record it in the log, and when something looks wrong decode
  **all** channels of the file. Never conclude "the write did not commit" from a
  single channel's block, or from a control's text.
- **`strip_panel()` can resolve the wrong panel.** While a dialog is open, the
  widget-used-to-find-the-strip can belong to *that dialog*, so the helper
  returns the dialog's panel instead of the strip (observed with the Store
  dialog open). Fix: take the first widget whose parent is not a panel
  containing a browse control.
- **Menu navigation is setup-time only, and enumeration order is not screen
  order.** Sort an overlay's entries by their screen position before pressing:
  matching the first entry in enumeration order picked `Default parameters`
  instead of `Operating parameters` and raised a modal panel. Keep
  `Default parameters` off the critical path. Never `WM_CLOSE` an open popup —
  that wedges the menu loop until restart. `ESC` does nothing on these panels.
- **Presence is not visibility: the `Parameters` overlay is pre-created and
  hidden.** The panel is in the control tree from startup with a caption-less
  `TSp_Panel` rect of `(169, 55, 401, 250)` and `IsWindowVisible == False`, and the
  menubar hover is what shows it. An enumeration that ignores visibility (or a
  rule that accepts a panel because it is *present*) therefore finds an "open
  menu" that is not painted, and the press lands on whatever is behind it. **Rule:
  the overlay *and* the entry must report `IsWindowVisible == True` before an
  entry is pressed**, and a hidden candidate is named in the refusal rather than
  pressed into. The overlay's five entries sit at screen tops 61, 95, 130, 165 and
  205 — the first is `Operating parameters`.
- **The menubar takes the real cursor; everything else takes messages.** Hovering
  the `Parameters` button with the operator's own cursor (`SetCursorPos` onto the
  button's centre, then one short relative `mouse_event` move) is what opens the
  overlay — a posted move and a posted held press both opened nothing in live
  runs — while the **popup entry** is taken with a plain *posted held press on the
  entry's own handle*, exactly like a strip button. Do not "improve" the entry
  press into a click: a re-derived real click on the same entry opened nothing.
- **A dialog is identified structurally, and which dialog it is by its content.**
  A dialog is a panel that is not the sidebar column, is wider than 400 px and is
  full of controls (≥15 direct children, or a `TSp_Browse`, or input controls of
  its own); the measured `Operating parameters` panel is `627x384` at `(655, 364)`,
  directly owning **21** controls (42 descendants), holding seven
  `TSp_Value_Button` fields, its bottom button band and — in its header, as a
  direct child, **not** nested in a value field — the channel combo
  (`Operating parameters for channel [n ▼]` at `(1083, 373)`, items `1`…`10`).
  Requiring the channel combo to call a dialog "the operating one" is the content
  test; requiring it to call a panel "a dialog" is stricter than the evidence and
  rejects correctly opened dialogs.
- **The bottom button pair is the *last two* of the band, not the first two.** Sort
  the `TSp_Button`s whose `top` is in the dialog's last 60 px by `left`: `Accept`
  (`Do store` on the Store dialog, `Yes` on a warning) is `row[-1]` and `Cancel`
  (`No`) is `row[-2]` — the reference's own rule
  (`recon/41_burst_sampling_volume.py`, `bottom[-1] if accept else bottom[-2]`).
  Never the band's **leftmost**: the live `Operating parameters` band holds **four**
  buttons — `No emission on Probe In/Out` `(663, 712)` and `Use US coupling
  parameters` `(862, 712)` are *indicator* buttons painted to the left of the pair,
  and pressing the leftmost pressed an indicator and left the dialog open
  (measured 2026-09-17). The pair is narrow (`Cancel` `(1091, 703, 80x25)`, `Accept`
  `(1183, 702, 80x25)`) while the indicators are wide; identity is positional, so
  the rule is "the two rightmost", never a width or a title.
- **The popup highlights `Default parameters` by itself.** A live screenshot of the
  open menu shows the second entry highlighted (the application's own default
  selection) with `Operating parameters` unhighlighted above it. So the *highlight*
  is not a target, and "press the selected entry" opens the wrong dialog — press the
  entry at the first screen `top` by its own handle.
- **A press on an entry closes the popup before it opens the dialog**, so anything
  that must be read about the popup — its visibility, its entries, their order —
  has to be read *before* the gesture.
- **Never `EnumWindows` to detect a dialog** — the Store dialog is a child panel
  and no top-level window appears.

---

## 7. The cap hazard

**A block is the application's memory-management unit; the cap is a setting.**
`Do not keep in a block more profiles than` (in `Record settings`, dialog-only)
accepted **1,000,000** — the manual's "limit of 32,000 profiles" is contradicted
by the UI, and the *effective* limit was not established. Hitting the cap is what
raises the memory warning; physical memory is not the binding factor in the
observed runs.

Measured:

- **Small blocks accumulate harmlessly.** 6 consecutive 1.5 s cycles of one
  parameter set at cap `10000`: all `ok`, uniform file sizes (97,993 B and one
  97,169 B), strip back to `ready` after every cycle, no warning, no
  degradation. Short points need no block management at all.
- **Crossing the cap wedges the cycle.** With cap `100` and a 6 s recording
  (~240 profiles needed), the cycle reported `Stop did not reach the store view
  (recording)` and every later attempt read `cannot start from view recording`;
  the recording **kept running** throughout, and its data was later stored by a
  *later* cycle as a **1,039,825 B** file — ten times a normal point.
- **A leftover recording contaminates the next stored block.** Because the store
  is block-scoped (§4), that accumulated data was written under the *next*
  point's name. The specific warning text was never captured.

**Rules for the driver:**

1. **Only start from a verified `ready` state**, never from `recording`.
2. **After any failed cycle, stop or clear before the next point.**
3. **Assert `T ≤ cap × period`** using the period measured for that point (§8),
   and treat any memory/cap warning seen during the recording as
   **invalidating the point**.
4. **Sanity-check the stored file size against the expected signature** — about
   98 KB per 1.5 s at 805 gates — and invalidate a point that is off by a large
   factor. That size check is the cheapest guard against silent contamination.
5. Size the cap well above the largest expected point, so the question never
   arises; blocks only become meaningful for rolling/multiplexed multi-channel
   work, where each roll repeats N blocks and `Show block` plus a block-scoped
   `Do store` is exactly the needed unit.

Behaviour at the cap is a **ring** *(hypothesis, from the operator's
observation that memory "rolls over and starts rewriting itself")*: the block is
not stopped at the cap, it wraps, and the stored block then covers only the last
`cap × period` seconds — while the `.BDD` still looks entirely valid. Either
behaviour (wrap or truncate) means the point no longer represents the intended
window `T`, which is why rule 3 is an assertion and not a comment. See §11.

---

## 8. The profile-period constraint

**A point is a duration in seconds; the profile period is an input constraint;
profiles are an output.**

- `--seconds T` remains the point definition. The physics is time-dependent, not
  profile-dependent: defining a point by profile count would make the observation
  window vary with the configuration and destroy comparability across the matrix.
- `Time between profile` (status bar) is **read and logged per point** — target
  vs achieved — because it constrains the matrix: it is what has to fit under the
  cap, and what decides how many profiles (`= T / period`) a point produces.
- Profiles per point are **derived**: used to size the cap and to sanity-check the
  recorded count, never to define the point.
- **The manual's formula is the expectation; the instrument's own read-out is the
  certificate.** `T_profile ≈ T_tran + T_prf · (16 + N_PRF)`, and the parameter
  block corroborates it structurally: **word 17 = 16 in every file**, i.e. the
  formula's constant term is a real, stored constant of the acquisition. **Keep the
  formula's two terms apart when reading a measurement.** At the sparse pass's
  600 µs PRF the fixed emission term alone is `16 × 600 µs = 9.6 ms`, while the
  ~10.369 ms intercept the 26 committed pass files measure is that 9.6 ms *and* the
  transfer term `T_tran` (~0.77 ms as they imply); the intercept is not the
  16-emission term on its own, and docs that read it that way are wrong. The planner
  implements the whole law (`acquire/plan.py::profile_period_s`). Earlier
  first evidence (`100 emissions × 200 µs PRF` observed at `21.2 ms`) was read as
  a contradiction of the formula; it is not — an earlier revision of this section
  said "measure the period, do not trust the formula", and that line is withdrawn.
  Compute the period from the point's parameters (it is what must fit under the
  cap), then **read `Time between profile` once per configuration and log
  target-versus-achieved as the certificate** — a discrepancy is a finding about
  the point, not a reason to redefine the physics.
- That measured period also sets the *pace*: **~47–50 profiles/s**, so a
  10,000-profile block fills in about **3.5 minutes**, and the status-bar
  `Profile` counter is the less trustworthy of the two read-outs.
- Consequences: assert `T ≤ cap × period` before recording; only a *long* point
  or a *slow* period can cross the cap (§7); and a too-short `T` is not a
  problem, a too-long one is.

---

## 9. Validated points, and the words they pinned

Two sweep points were validated end to end — parameters written, recorded,
stored, decoded — at a constant **100 mm** window, `c = 1460 m/s`, first gate
2 mm, on channel 1:

| point | resolution | word 10 | gates | depth | notes |
|---|---|---|---|---|---|
| `sw100-k1-…` | 0.1217 mm | 0 | 805 | 100 mm | finest rung of the `c = 1460` ladder, exact (139,193 B) |
| `sw100-k2-…` | 0.2433 mm | 1 | 403 | 100 mm | second rung, exact |

Both decode on channel 1 with `burst = 4`, `emissions = 150`, `PRF = 169 µs` and
the physics-driven sampling volume (`0.876 mm` at `c = 1460`), and both confirm
the depth law `depth = first gate + gates × resolution`. Log:
`recon/out/sweep-depth100.jsonl`. The intermediate miss (474 gates for a
requested 805) is §3; it is the reason every point is now read back before it is
recorded.

**Word map — what a labelled point pinned** (the labelled fixture was recorded
through `Record → Stop → Do store` with the UI values enumerated at capture
time, then differenced against a second deliberately-distinctive point):

| word | tracks | status |
|---|---|---|
| 2 | `Depth` = first gate + gates × resolution | verified |
| 3 | velocity scale ×100 | verified |
| 5 | `PRF [µs]` | verified |
| 8 | `Burst length` | verified |
| 9 | first-gate index (moves with `First gate depth`) | verified |
| 10 | 0-based resolution rung index | verified |
| 13 | `Nb of gates` | verified |
| 14 | `Emissions/profile` | verified |
| 15 | velocity scale factor (`3141` = `1.00`) | verified |
| 19 | `Sound speed [m/s]` | verified |
| 20 | `Doppler angle` | verified |
| 27 | `Sampling volume` **index** (`3` = `0.900 mm` at `c = 1500`) | verified |
| 42 | `Tgc [dB]` (`40`) | probable |
| 18 | `Sensitivity parameter` | ambiguous — it moved together with TGC in the diff; settle it with one file that changes only sensitivity |
| 84 | `Number of skipped profiles` | identified (value `0`, with an `Apply skip profile` checkbox); *semantics* unconfirmed |

Unresolved: words 33/61/80 all read `10000`, the value of the block cap set
before the recording at the time — consistent with tracking the cap, unproven
(one deliberately odd cap settles it).

---

## 10. Consequences for this repository

A stored `.BDD` is only a usable sweep log if a reader can recover the point from
it. The required operation words are now exposed as stored integers by
`io/dop/bdd.py`; the physical sampling-volume length and wall filter remain
unresolved:

| need | word | state |
|---|---|---|
| `Emissions per profile` (`N_PRF`) — the primary variance axis | 14 | identity verified; decoded as `ChannelConfig.emissions_per_profile` |
| `Sampling volume` — identity verified *and* an index into a physics-driven list | 27 | decoded as `ChannelConfig.sampling_volume_index`; `sampling_volume_mm` remains unset because no reviewed index → length law exists |
| `Number of skipped profiles` | 84 | decoded as `ChannelConfig.skipped_profiles`; semantics remain unconfirmed |
| wall filter | 16 | `ChannelConfig.wall_filter` remains unset |
| achieved profile period per point (`Time between profile`) | — | not stored as a parameter; log it instrument-side (§8) |

The decode follows the existing metadata gate: word-level evidence (above), a
destination domain field, propagation and fixture tests. The resolution law of
§3 is the other useful addition — it makes a point's gate geometry checkable
from `word 10 + word 19` alone.

---

## 11. Open questions

1. **Block behaviour past the cap.** The cap-crossing run suggests the block kept
   accepting profiles past the cap; whether it wraps (ring, last
   `cap × period` seconds retained) or truncates is not settled, and either way
   the stored file looks valid. Until it is settled, the driver asserts
   `T ≤ cap × period` and invalidates any point that saw a memory warning.
2. **The shared-memory-pool question.** Whether blocks that accumulate toward a
   large total draw on one pool (and therefore interact) was not established; the
   small-block and single-cap runs never reached that regime.
3. **The identity of the at-cap warning.** The text raised when the cap is
   crossed was never captured — the cycle wedged before it could be read. The
   driver currently answers *any* unexpected overlay structurally (§6) rather
   than recognising this one.
4. **Burst ↔ sampling-volume acceptance sets.** The instrument chooses the
   sampling volume from the burst (and from `c` and `f_e`), and refuses a volume
   below what the burst allows. The accepted `(burst, sampling volume)` pairs per
   `(c, f_e)` are measured, not documented; a burst sweep has to read them back
   and record them per point.
5. **`New acquisition` vs `Clear and restart`** under a long sweep — both are
   single-press actions here, and their exact semantics over many points are
   untested.
6. **The external-trigger / `Auto record` path is unexercised.** It remains the
   better design — it takes the strip out of the critical path entirely, and one
   arming can produce several files — but only the rig can exercise it.
7. **The earlier 25-requested / 50-decoded profile gap remains unexplained.** On
   2026-10-20 the operator stated a 25-profile request, but the saved block decoded
   to 50 profiles per channel. The separate 2026-10-21 run requested **50** and
   decoded to **50** (§12.6); it does not reproduce or explain the earlier mismatch.
   No conversion factor or multiplicity rule is inferred.

---

## 12. Roadmap and standing decisions

The stage this work is at, and the decisions that are settled rather than open —
they are here so a later reader does not re-litigate them from the mechanism in
§§1–10 alone.

### 12.1 Stage: the simulation application only

In order, and until each step is done the next one does not start:

1. **The simulation application only.** Everything measured in §§1–10 was
   measured on the simulator; nothing above is claimed for the connected
   instrument.
2. **Then a repo review** — what these points and this mechanism imply for the
   code that consumes them (§10 is the first half of that; it is not the review).
3. **Then the connected UDV box**, and the first thing to do there is **verify
   how the UI elements map**: the same roles, the same top-to-bottom order, the
   same view structures, or a documented difference. Nothing in §3 or §5 may be
   assumed to carry over on the strength of the simulator alone.
4. **Only then matrix construction.** The sweep matrix is planned against a
   mechanism that is verified on the box it will run on.

### 12.2 The external trigger is out of scope

**All synchronization is done at the software level.** The driver holds the
record window with its own clock and reads the achieved period back per point
(§8); the instrument is never asked to start a recording on its own. The
external-trigger / `Auto record` path of §11.6 stays unexercised and is **not**
part of this plan: it is a separate decision to be taken deliberately, never a
fallback the driver may switch to silently.

### 12.3 PRF and the profile period

- **PRF sets the maximum resolvable fluid velocity, and it is the operator who
  chooses it, by observation.** It therefore stays a **runtime parameter** — it
  is not derived from the matrix and must not be hard-coded.
- **Minimum emissions per profile is 8.** Read that as the floor of the axis, not
  as a default.
- **The period target is not fixed yet.** It will be tuned during live tests,
  aiming for a measurement period of at most roughly **100–150 ms**. Minimizing
  the period matters because of the turbulent flow: the shorter the measurement
  period, the more of the flow's structure survives into the recorded block.
- **A fixed period target must therefore not be hard-coded** anywhere in the
  driver. The period is measured and logged per point (§8), and every check that
  needs it takes the measured value, not a constant.

### 12.4 The block cap is not a planning limit

The cap is **not** the constraint that shapes a point: the UI accepted more than
a million profiles in one block (§7), so it is not a limit to plan the sweep
around. The real constraint is this:

> **A `memory full` condition must never silently corrupt a point.** The
> recording does **not** stop at the cap, and the accumulated block is deposited
> on save — so a stored file can look entirely valid while no longer covering the
> intended window.

A point that sees such a condition is therefore treated as **invalid** — reported
as failed, not stored, not decoded, and not compared with its neighbours.
Invalid is the only safe reading: the file gives the checker nothing to
distinguish it from a good point (§7, §11.1).

### 12.5 Point lengths

While the mechanism is being stabilised, points are deliberately **short — 1–2 s
— for fast iteration**: a point that is wrong is discovered in seconds and the
whole chain can be re-run cheaply. **Production points will be 10–20 s.** Nothing
in the driver may depend on the short duration: a point stays a duration in
seconds (§8), the cap assertion stays `T ≤ cap × period`, and the period stays
whatever the instrument reports for that configuration.

### 12.6 Acceptance, 2026-10-21 — the MPX store path, scoped

One live acceptance covered the **store half** of the chain on the instrument, and only that half.
It is a record of one run, not a general MPX result, and it changes no rule in §§1–11 or the staging
in §12.1:

- **The recording was the operator's, in manual mode.** Rolling MPX was *enabled and idle* — the
  enabled row the operator left it in. Which entry path produced it (roll-over on: enable leaves the
  ready row; roll-over off: enable auto-arms) was not recorded, and the toggle state at that enable
  is unmeasured (§12.13). Nothing here establishes the armed or rolling recording path.
- **The store was automated.** The recording had ended naturally in the two-button `Do store` /
  `Clear and restart` store row. A store-only probe — it starts no recording — pressed `Do store` on
  the strip **once**, then the Store dialog's own `Do store` **once**. One press each, and the
  application raised **no** warning.
- **Stored artifact:** `mpx12-50profiles-manual-01.BDD`, **41,526 B**, SHA-256
  `f9124cd24f886a923bb31f2fcc7ba51056de5743d9487ea8022d6bbde90379f0` (it was written under the
  repository's generated-output tree, not committed). It is a local output and **not** a fixture:
  the name and digest record what was written, they do not make the bytes available from this
  repository.
- **The decode is independent of the store path**, taken with the public `uv run udv-inspect`:
  sequential channels **1** and **2**, axial velocity, **50 profiles × 80 gates each**, 1.98 s.
  `WordFacts`: gates 80, resolution 0.74 mm, PRF 600 µs, emissions 50, sound speed 1480 m/s,
  burst 4.
- **The post-save screen was clean, but its mode was not read.** The same root screen came back
  with a three-button ready row, no slider, no overlay, and no layout-shape reason reported. **No
  positive post-save MPX-mode read exists**, so nothing here says a store disarms, clears or
  preserves the MPX configuration — that question stays open.
- **One number is unexplained.** A request of 25 profiles and a decode of 50 per channel are still
  unreconciled — the stored file's own name records `50profiles`. No factor is inferred from one
  file; it stays unexplained (§11) and must not be normalised into a multiplier.

**Accepted:** real manual recording → automated store → commit once → independent decode of both
channels. **Not accepted:** the MPX stop gesture, armed/rolling recording, the 25→50 profile
relationship, and any post-save MPX-mode state.

The historical live run used a **store-only probe**, not the subsequently integrated command.
The package now exposes `udv-acquire store-completed NAME --channel 1 2 --profiles 50
--stated-by operator --store-dir DIR --json` (or the same verb through
`python -m udv_echo_process.cli acquire`). It requires an existing directory and a measured
completed multiplexer store row — the two-button row, or the repeated-run three-button row whose
geometry selects `REPEATED_MPX_COMPLETION` (the legacy `New acquisition`-first three-button row, an
unmeasured three-button row and every four-button row are refused) — refuses collisions, and issues
no Record, Stop or Clear. Channels/profiles
are attributed **operator declarations**, not independently decoded facts in the command's report.
It may rewrite the Store dialog's remembered directory to the explicitly selected one.
**Package-command acceptance, 2026-10-21:** after a second operator-recorded block completed
naturally, the supported CLI stored `mpx12-50profiles-cli-01.BDD` with exit 0, one commit,
zero warnings, and no working-directory rewrite. The file is **41,526 B**, SHA-256
`3a980cd7adbe3efdc5037ec117f7cdc35911fed9d3823f09abc141df7dc3cc6e`.
Independent `udv-inspect` and per-channel `acquire decode` reads established sequential acquisition,
channels 1 and 2, axial velocity, **50 profiles × 80 gates each**, approximately 1.98 s per channel,
and the same decoded configuration as the earlier probe run. These are decoded observations,
not merely the CLI's operator declaration. The post-store read returned Ready, no overlay and
no layout error. The command also refused a preceding Ready-state attempt with exit 2 and no
requested file created. This accepts the real CLI store path, not automated recording or a
post-save multiplexer-mode claim. Both recordings remain generated local outputs, not fixtures.

### 12.7 Acceptance, 2026-10-21 — automated MPX Record to store

After the operator freshly confirmed rolling multiplexing active for channels 1 and 2,
50 acquisition profiles each, `acquire record-multiplexed` completed one real instrument run
with exit 0. The pre-read showed Ready (three buttons, no slider), no popup/dialog, and the
instrument caption. The hidden parameter sidebar produced a full-layout warning; this strip-only
workflow performed no sidebar writes and did not relax that gate.

The workflow sent **one Record**, observed the one-button/no-slider active row without pressing
it, waited for natural completion into **Store / two buttons / slider**, then sent one Do store
and committed once on the original binding. No Stop, Clear, Disable, channel selection or parameter
write was requested. No warning was answered and the structured directory readback reported
unchanged before/after text. The post-read showed the same root handle, instrument caption, Ready,
no overlay and no layout error. Post-save multiplexing mode was not positively read.

Artifact: `mpx12-50profiles-auto-01.BDD`, **41,526 B**, SHA-256
`475785c06dee0bfaa6d1d983c6e967e0c5d5bd4f83d02f119f636f06eb4e2b25`.
Independent `udv-inspect` and per-channel `acquire decode` reads established sequential acquisition,
exactly channels 1 and 2, axial velocity, **50 profiles × 80 gates each**, approximately 1.98 s
per channel, resolution 0.74 mm, PRF period 600 µs, emissions/profile 50, sound speed 1480 m/s
and burst length 4. The declaration matches these decoded counts; no 25→50 mapping is inferred.
The file and raw logs remain generated local evidence, not committed fixtures.

Two boundaries belong to the command rather than to this one run. **The enable flag is a
declaration.** `--mpx-enabled` is required and is taken as the caller's statement that the
multiplexer is enabled; nothing in this workflow reads the mode back (no passive MPX
discriminator exists, and no Disable is pressed), so the flag is never reported as a post-run
fact and the mode-unknown obligation is carried on every stored run. **The post-store check
reports stored blocks, not visits.** The file's own block/sequence numbers partition the stored
rows, and that partition is compared with a repeated declaration; the word is a block/sequence
number, never a visit identity, so `partition-consistent` means the stored blocks split the rows
as declared, not that M visits ran (see `docs/mpx-artifact-verification.md`).

The completion row accepted by the press is not limited to the two-button row this run ended in:
`record-multiplexed` and `store-completed` share one predicate that accepts the two-button row and
the repeated-run three-button row **only** when its measured `477x123` geometry selects
`REPEATED_MPX_COMPLETION`. The repeated-run row is accepted from a read-only capture; no live run
of `record-multiplexed` has yet ended in it, and the legacy `New acquisition`-first three-button
row stays refused.

**Accepted scope:** one operator-configured finite MPX Record → natural completion → store cycle.
**Not established:** repeatability, automated mode enable/configuration, armed/external-trigger
operation, a multi-point campaign, physical signal quality, live timeout/failure cleanup, or
post-save mode. Failure paths are tested offline; the command never stops or clears a timed-out
recording. Root/child handle lifetime limitations remain those of the existing driver.

### 12.8 Acceptance, 2026-10-21 — read-only Channels inspection

With the operator-opened full Channels popup left visible, the public
`acquire channels-read --json` command returned exit 0 and the measured eight-band settings
signature. Bounded `WM_GETTEXT` queries read **repeat `1`**, **start channel `1`**,
**apply-from `1`**, **profiles `50`**, and **seconds `2.01`** as raw field texts and parsed values.
The existing `GetWindowText` snapshot alone does not retrieve those cross-process edit values;
queries supply them before the same normalized tree is interpreted. No button press, hover,
selection, commit, mode change, popup open or popup close was performed by the command.

The numeric amount's channel remains **UNKNOWN** (its identity is painted in the group caption).
The driver takes several internal resolves and then queries edit texts; this is a sequential
inspection of one bound root, not an atomic snapshot. Root identity is checked around the text
queries, but child-handle reuse and a concurrent operator edit remain existing limitations.
All channel ticks and enable/rolling/display states remain **UNKNOWN**, and the report always
states `setup_verified: false`. The successful read is not full configuration verification or
permission to write settings. A prior closed-popup read returned exit 2 with the explicit absent
surface. The raw live report remains generated local evidence, not a committed fixture; portable
de-identified projected capture shapes cover the resolver offline.

### 12.9 Acceptance, 2026-10-21 — supervised `Repeat` round trip, and the reporting defect it found

One instrument, one operator, the full Channels popup left open by the operator; every popup
close and reopen between steps was the operator's. `acquire channels-repeat` did the writes only.
Two invocations, at most one commit each:

| step | command | popup stated before | committed | post-write reading (same open popup) |
|---|---|---|---|---|
| 1 | `channels-repeat` | repeat `1` | `2` | `2`, stage `written` |
| 2 | `channels-repeat` (restore) | repeat `2` | `1` | `1`, stage `written` |

- **Acceptance is the reopened read.** After the forward write the operator closed and reopened
  the popup, which stated repeat **2**; after the restore, a second reopen stated **1**. Each
  command's own post-write read came from the still-open popup and therefore reported
  `persisted: "unknown"` — correctly, because an open surface is not an acceptance read.
- **Nothing else moved.** `start channel 1`, `apply-from 1`, `profiles 50`, `seconds 2.01` read
  the same before and after both writes; the only changed fact was the repeat field.
- **The multiplexer-off state was the operator's declaration** (`--mpx-disabled`), not a passive
  mode read, and the popup's ticks stay unread.
- **Not exercised:** an application restart, anything downstream of the setting (acquisition
  behaviour), more than two writes in one trial, or a value that already equalled the target —
  the equal-value no-write path is covered offline only.

**The defect this run exposed, and its correction.** The restore invocation was given
`--expect 2 --value 1`. The command had one numeric argument for two different facts, so it
recorded `baseline: expect` and `restore_to: expect`: the 2→1 record at the time demanded
"restore repeat == 2", the value the run had *just left*, and its stated obligation contradicted
the field it had just set back to `1`. The trial's real origin (`1`) existed only in the earlier
record. The pre-fix records are preserved verbatim as history; the current shape is:

- `--expect` is **this invocation's** precondition and nothing else;
- `--baseline` is the trial's **original** value — declare it on every invocation of one trial.
  `restore_to` is that value, and the record names its source (`declared-trial-baseline` or
  `this-invocation`), never an alias of `expect`;
- a write whose target equals the declared baseline records `restores_baseline: true` and renders
  its obligation as "returned to the trial baseline, so no further restoration is owed";
- with no `--baseline` the record carries `baseline: null` and names only the command's own
  starting value as the possible undo, rather than calling it the baseline;
- a raised commit, a closed popup and a field that did not take the value keep the same declared
  target and never claim a restoration; `restored_baseline` is true only when the post-write read
  states the baseline. Those outcomes no longer ask the operator to *confirm* the committed value
  (the reading just contradicted it): they ask them to reopen the popup, read the repeat as it
  actually states, and then restore the trial baseline.
- **one record per invocation, not a ledger.** Each run claims its own `--trial-record` file
  exclusively, so this sitting's forward write and its restore are two records; every invocation
  of one trial declares the same original `--baseline`, and reconciliation is reading the trial's
  records in order (the newest names what is still owed). A second invocation with the same path
  refuses rather than appending or overwriting.
- `written_at`/`completed_at` are timezone-aware ISO 8601 wall-clock stamps, matching the other
  persisted manifests; a monotonic counter value would not be a timestamp once read from disk.
- a record update that fails leaves the file at phase `obligation` and the result reports
  `trial_record_phase: "obligation"` with the failure under `restoration_owed`, so a run never
  claims its outcome reached disk when it did not.

The run's own outputs (the two structured records, the baseline and reopened reads, and the two
dispatch logs, all named `repeat-*20261021.*`) are generated local evidence and are not committed
fixtures. The offline suite in `tests/test_acquire_channels_repeat.py` holds the argument
separation, both write directions, the undeclared-baseline record, the unknown-failure
instructions, the failed-record-update phase and the timestamp shape.

### 12.10 Acceptance, 2026-10-21 — capture evidence for the Channels popup (`--capture-dir`)

One public invocation on the same operator-opened full Channels popup:
`acquire channels-read --capture-dir DIR --json` returned **exit 0** with `readable: true`,
`surface: settings_popup`, the measured eight-band signature, and repeat `1` / start channel `1` /
apply-from `1` / profiles `50` / seconds `2.01`. Its additive `capture` record stated
`status: "ok"`, `stable: true`, `directory: …/capture-001`, `frames:` the two saved
`channels-roi-frame-{1,2}.png` crops of the popup's own rect, and `unknown_reasons: []`; all five
amounts bracketed consistently — same text, value, edit handle and owning widget before and after
the frames. The caption is **`UNKNOWN`** with `recognition: NOT_PERFORMED`: nothing in this path
reads glyphs, so the record says *this is that popup, the screen was still, these numbers did not
move* and never what the caption says. `setup_verified` stays `false`; an operator's stated
caption is not promoted to a native fact.

**3 and 2 are different failures.** **3** is a capture that could not be attributed: the
structural read succeeded but a frame was blank or one colour, the two frames differed, a guard
failed (target handle/rect, foreground, not-minimised, same popup handle and rect across the
capture) or an amount moved — the reasons are printed to stderr and the frames stay on disk as
evidence. **2** remains an unreadable structural report (measured by the same command with the
popup closed: exit 2, `surface: absent`, no image taken). A capture failure is therefore never
reported as a bad reading, and a bad reading is never reported as a capture failure.

**Not established:** alignment between cropped screen coordinates and pixels under display
scaling (the default backend reads the virtual-screen origin/size from `win32api` and refuses a
frame whose bitmap size disagrees, but 100 % scaling is the only case measured as 1:1); atomic
sample stability (two frames of the same ROI — a screen that changed and changed back between the
grabs is indistinguishable from a still one); and any action authority (no press, commit, mode
change, popup open or close). The report and the two PNGs are generated local evidence, not
committed fixtures; `tests/test_acquire_channels_capture.py` covers the workflow, both exit
codes and the guards offline against an injected image backend.

---

### 12.11 Supervised `Profiles` writer (`channels-profiles`)

**Status: OFFLINE VERIFIED, AND LIVE ACCEPTED FOR ONE SCOPE** — one operator-declared channel
(channel 1), `50 → 51 → 50`, with the popup closed and reopened before each acceptance read.
Everything below that is offline is established by the source and by
`tests/test_acquire_channels_profiles.py` (67 focused tests pass across it and
`tests/test_acquire_channels_repeat.py`; `ruff check src tests` clean) against injected surfaces.
The live scope is narrow on purpose: **one channel, one temporary count, one restoration, three
reads**. It does not accept the writer generally — the operator's channel stays a declaration, and
another channel, the coupled `seconds` on the real application, an application restart and any
downstream acquisition effect remain unestablished (see the live block below). The `Repeat`
acceptance in §12.9 and the capture acceptance in §12.10 do **not** transfer: a different field, a
different coupled amount, and a different obligation.

Exact interface, from `uv run udv-acquire channels-profiles --help` (and the same command through
`./tools/live/dispatch.sh -m udv_echo_process.cli acquire channels-profiles`):

```
--expect N              the profiles count the popup must state before any write (required)
--value M               the profiles count to commit, once (required)
--operator-channel C    the operator's declaration of which channel the amounts belong to (required)
--baseline B            the trial's original profiles count (optional; omitted = none stated)
--mpx-disabled          the operator's declaration that the multiplexer is disabled (required)
--trial-record PATH     a path claimed exclusively; a directory gets channels-profiles-trial.json
--json                  machine-readable report
```

- **The operator's channel is a declaration, never a proof.** The group box's channel lives in a
  painted caption (`For the current channel (channel N)`) and the control tree states nothing for
  it, so `per_channel.channel` stays `UNKNOWN`. `--operator-channel` is recorded verbatim, is
  checked only against the channel numbers the popup itself paints (a number it does not offer is
  refused with zero writes), and can never become `channel_verified` — that field is
  `Literal[False]` by construction. The module reads no picture, so nothing here attributes the
  amounts to a channel.
- **`seconds` is coupled, not preserved.** Changing the profile count makes the application
  recompute the neighbouring `… during seconds` amount, so it is **not** part of the verdict:
  it is reported before and after, and the fresh post-write amount must be valid and strictly
  positive, otherwise the stage is `write_unverified`. `repeat`, `start_channel` and `apply_from`
  are the preserved facts; a movement there is reported (`written_other_facts_changed`) and is not
  exit-0 evidence.
- **`--baseline` is the trial's original count and is never defaulted from `--expect`.** This is
  the defect §12.9 fixed for the repeat writer, carried over by construction: a restore run
  (`--expect 8 --value 7 --baseline 7`) records `restores_baseline: true` instead of owing an undo
  of itself. Each invocation claims its own record file exclusively (no ledger, no overwrite), so a
  forward write and its restore are two records, both naming the same original baseline and
  reconciled by reading them in order.
- **Only the operator's reopened popup can close the obligation.** The post-write read comes from
  the still-open popup, so `persisted` is `unknown` on every write and `obligation_open` stays
  `true`. The command never opens, closes, presses, records, retries or repairs; the acceptance read
  and any restoration are the operator's, by hand, after a close-and-reopen.
- **Zero-write refusals** (raised `AcquisitionError`, nothing committed): not exactly one visible
  instrument window; caption/overlay/stopped-row clauses at the binding; absent, clipped, dialog-
  covered or unreadable popup; a profiles text that is not an integer count; a missing owning value
  button; a channel argument the popup does not paint; a count that differs from `--expect`; an
  invalid pre-write `seconds`. The caption/overlay/row/window clauses are then asked **again on a
  fresh enumeration immediately before the commit**, so a recording or modal that appeared between
  the reads refuses rather than being written through.

**Autonomy blocker, stated precisely.** There is **no verified automatic non-mutating route to
reopen the Channels popup and take the acceptance (and restoration) read**; that missing
verification — not a claim that no such route can exist — is what keeps this workflow supervised.
Two things must not be overclaimed in either direction: the operator has repeatedly closed and
reopened this popup by hand with success, so manual reopening is a working step rather than an
obstacle; and the capture path now yields the popup's own cropped frames (§12.10), so a caption
*image* exists, but visual caption recognition is **evidence only** — `recognition: NOT_PERFORMED`,
the caption stays `UNKNOWN`, and nothing in this repository reads glyphs to decide which channel or
which state is on screen. Closing the gap would need a measured, non-mutating reopen/read-back
route and a validated reader for those captions; neither has been established. No autonomy
predicate, gate service or "go" framework is introduced for this, and no staleness threshold is
invented: the observed limits are the ones the code and its tests state (one supervised binding, a
popup closed and reopened between reads indistinguishable from the one read, child handles not
identities after the tree changes, `setup_verified: false`).

**Live acceptance, 2026-10-21 — channel 1, `profiles 50 → 51 → 50`.** Two supervised invocations of
`acquire channels-profiles` on the operator-opened popup, one record each, with the popup closed and
reopened between every read; the operator declared channel 1, and a separate visual-caption reading
corroborated it for this trial only (`channel_verified` stays `false`, by construction). Facts, from
the two records and the three reads:

- **baseline** `50` profiles / `2.01` s (reopened read), `repeat 2`;
- **forward write** committed `51`; `restore_to 50`, `restore_to_source: declared-trial-baseline`;
  the reopened read stated `51` / `2.05` s — the coupled `seconds` moved, as the coupled-amount
  rule above predicts;
- **restoration write** (a second invocation of the same command, `--expect 51 --value 50
  --baseline 50`) committed `50` and recorded `restores_baseline: true`, so no further restoration
  is owed; the reopened read stated `50` / `2.01` s and `repeat 2` — the trial's original readable
  state is back;
- `persisted` stayed `unknown` and `obligation_open` stayed `true` on both records: closing it was
  the operator's reopened read, quoted in the acceptance record
  (`profiles-channel1-roundtrip-acceptance.json`, local generated evidence, not a committed
  fixture), which is what states `restoration_owed: false`.

**What this acceptance does and does not establish.** It establishes the writer's live forward and
restore path for **one operator-declared channel and one pair of counts**, including the coupled
`seconds` recomputation and retention across a popup close-and-reopen. It establishes nothing
globally: the channel is still a declaration (never a native readback), no second channel was
written, no application restart was tried, and no acquisition was run against the changed count, so
no downstream effect is claimed. The popup was reopened by the operator — the automation route that
would remove that step remains unverified (§12.11, "Autonomy blocker").

**Not established:** a persisted value the command can read itself; `seconds` on a channel other
than 1; the coupled amount beyond the two observed values (`2.01` / `2.05`); behaviour when the
popup is reopened between the write and the post-write read (the live trial closed and reopened
*before* each read, which is the operator's step, not the command's); more than one forward write in
one trial; an application restart; or any downstream acquisition effect of the changed count.
Generated reports from an offline run are test evidence, not fixtures.

---

### 12.12 Live acceptance, 2026-10-21 — supervised channel selection `1 → 2 → 1`

`acquire channels-select` was run twice against the real instrument, one press per invocation, on
one bound window and one popup that stayed open throughout (`popup_hwnd` and `row_hwnd` identical in
both records; the cell handle is the ordinal's own). Arms: `--expect-channel 1 --channel 2` then
`--expect-channel 2 --channel 1`, both with `--restore-channel 1 --expect-start-channel 1
--mpx-disabled` and their own record.

- **Both invocations:** `stage: pressed`, `presses: 1`, `press: attempted`, `posted: unknown`,
  `selection: UNKNOWN`, `native_proof: false`, `press_error` empty, `post_error` empty.
- **The readable facts did not move:** before and after each press `repeat 2`, `start_channel 1`,
  `apply_from 1`, `profiles 50`, `seconds 2.01`; `facts_moved: []`, `facts_unreadable: []`.
  **`50` profiles and `2.01` s with `repeat 2` are preserved by the selection**, which is the
  whole reason the trial was run — a channel switch here is not a profile or repeat change.
- **Exit `1` on both, and that is the expected result.** Only the settled `no_op` exits `0`; an
  attempted press is a gesture whose selection and delivery are unknown, so a zero would read as a
  result. A caller must treat `1` with `stage: pressed` as *done, unproven*, not as a failure.
- **Caption corroboration, no native proof.** After each press a `channels-read --capture-dir`
  captured the popup's own crops, and the tick was read **visually** from them: `1` at baseline,
  `2` after the forward press, `1` after the restore. The reader's own answer stayed
  `per_channel.channel: UNKNOWN` in all three reads, so this is a post-hoc visual observation and
  not a measured state. Note the provenance precisely: the two trial records carry
  `visual_corroboration: ""`, so the corroboration lives in the separate acceptance record
  (`select-channel-roundtrip-acceptance.json`), **not** in the command's records. Nothing here
  reads glyphs, and no evidence of a checked radio exists in the control tree.
- **The restoration was the automation's own second invocation** — the command was never restricted
  to hands. Two reporting defects the trial exposed were corrected in the same change, with no new
  authority: the owed line used to instruct "select channel 1 again on the top radio row **by
  hand**", which misdescribed a gesture a further supervised invocation takes (and did take, 40 s
  later), so it now names the gesture and its two possible takers; and `press_evidence` used to read
  "one **posted** held press" while `posted` is `unknown` on every path, so it now states the
  attempt, the recipe, and that delivery is unknown. **The two accepted records were not edited**:
  they are the evidence of what the command said at the time and keep the old wording, so a reader
  comparing them with today's output should expect that difference, and only new records carry the
  corrected wording.
- **Not established:** that a tick survives a popup close-and-reopen or an application restart (the
  popup stayed open); channel `10`, or any channel outside the measured press set; where the lower
  `Use channels` tick row's cells would land (never a target); behaviour with a recording or the
  multiplexer enabled (the mode was the operator's declaration only); what a raised press leaves
  selected; and any downstream acquisition effect of the newly selected channel. The switched-to
  channel's own per-channel amounts were **not** read as a change, because they did not move here —
  a trial where they do move would be reported as `facts_moved`, not as an error.

Generated logs, records and captures for §12.11 and §12.12
(`profiles-channel1-*`, `select-channel*`, `select-live-baseline*`) are local evidence under a
git-ignored scratch directory and are not committed fixtures.

### 12.13 MPX mode entry and exit, 2026-10-21 — operator semantics, read-only evidence

One disabled → enabled → disabled round trip, **every mode gesture the operator's**; automation
only read the tree and captured popup crops. This subsection is the single home for MPX mode-entry
semantics; the skill and the surface model point here rather than restating it.

| state | what the surface shows | provenance |
|---|---|---|
| disabled | Channels popup unclipped (full settings surface); the mode toggle's painted caption is `Enable multiplexer` | visual caption on the measured build; the toggle's state is not in the tree (ledger B15) |
| **enable with `Roll over the channels` ON** | three-button ready row — `Pause` / `Record` / `Clear and restart`, no slider: *enabled and idle*, awaiting a manual `Record` | captured operator trial (entry capture + crops); strip structure from the tree, captions painted |
| `Record` from that row | one-button, no-slider active row; **no `Stop`** | operator report; the same one-button active row was observed in §12.7; the role stays unbound (B21) |
| **enable with `Roll over the channels` OFF** | the acquisition **arms and records on enable** and runs on its own to the Save/Reset store row (`Do store` / `Clear and restart`) | **operator report only** — not exercised, not captured, not automation-measured; no evidence of the transition exists |
| active acquisition, any entry path | `Clear and restart` and the Channels menu's disable entry are the only routes out; nothing in the strip is a `Stop` | operator report + §12.7/§12.13 reads |
| exit while enabled | Channels popup clipped to a single entry, painted caption `Desable multiplexer` (**exact spelling, sic**) | capture + operator attribution |

**Paired restoration evidence (same sitting).** After the operator re-disabled multiplexing, the
captured state was: painted caption back to `Enable multiplexer`, roll-over mark a red cross (the
trial's recorded roll-over-off state; the mark is a visual reading, not a tree fact), channel `1`,
profiles `50`, seconds `2.01`, repeat `2`. Restoration owed: **none**. The
automation pressed no mode control, issued no `Record`, and performed no restoration gesture of
its own — the captures are read-only.

**What this does not establish.** The captions are painted pixels read visually, not native state:
no `IsWindowEnabled`-style or checkbox fact for enable, roll-over or the tick strips exists in the
tree, and an empty widget text is not an "off". The `profiles`/`seconds` pair is attributed to
channel `1` only by the group's painted caption. The whole table is one build
(`UDOP DOP3010.43`), one window geometry and one sitting, so it is **not** a universal geometry or
caption law; a different build, scale or layout must be re-measured, not inferred. Nothing here
covers relay behaviour, post-save mode, repeat>1 multi-block behaviour, or a `Stop` binding for MPX.

Evidence: `.hermes/scratch/multiplexer-development/mode-entry-roundtrip-acceptance.json` with
`mode-disabled-baseline.log`, `mode-enabled-entry-capture.log`, `mode-enabled-entry-crop-a.png`,
`mode-enabled-entry-crop-b.png` and `mode-disabled-restored.log` — git-ignored local evidence, not
committed fixtures; the JSON states its own limits, including "not native checked state" and "no
automated mode press recipe was exercised".

**Guarded enable command (`acquire enable-multiplexed`), 2026-10-22 — offline only.** One
command now exists for the entry row: it binds exactly one window, requires a **fresh
same-invocation** two-frame capture of the full settings popup whose conjunction reads
`VISUAL_DISABLED` + `ON_PROVEN` with `live-bracketed` / `capture-digest-verified` evidence (a
retained `mpx-mode-read` pair or a bare `enable_precondition` boolean is not a precondition), and
presses the `Enable multiplexer` toggle **once** with the held press recipe. Rolling
`OFF_PROVEN` is refused with zero presses and no cleanup, because that path auto-arms and records.
The target is resolved by the reader's 8-band signature and toggle-role provenance, and the
action boundary re-resolves the binding, popup, signature and exact toggle handle before posting.
It never presses `Record`, `Disable`, `Stop`, `Clear` and never retries.

**Post-press readback (offline verified, 2026-10-22).** After its one press the command reads the
screen again. Only when that read resolves the clipped one-entry popup does it take a **fresh**
post-press capture pair under its own run directory and hold it to the explicit
`entry_no_numeric` contract: two still 158x43 frames of the measured entry shape, the exact
`Desable multiplexer` template match on both, re-derived pair digests, and before/after guards
naming the original bound window and the licensed popup panel. Only that conjunction reports
`post_mode: VISUAL_ENABLED` and lets the CLI exit `0`. If no clipped entry is visible (the popup is
closed, full, or a different surface) the mode stays `UNKNOWN` **explicitly** — it is not inferred
from the press, a ready strip or any other surface — and nothing is retried. The clipped entry
structurally carries no rollover row, so `post_rolling` stays `UNKNOWN`.

The settings capture's contract is unchanged: `settings_numeric` still requires all five amounts
bracketed consistently. The entry shape is a separate, explicit `capture_kind`; it neither
loosens that check nor reuses a retained directory.

**Guarded disable command (`acquire disable-multiplexed`), 2026-10-22 — offline only.** The
clipped popup's one entry is now reachable from the CLI. It binds exactly one window, takes a
**fresh same-invocation** 158x43 `entry_no_numeric` pair, and requires the reader's own
`Disable multiplexer` attribution with `live-bracketed` / `capture-digest-verified` evidence,
plus a structural target: the popup is the measured clipped size and exactly one **direct**
`TSp_Button` owns the entry label band. Caption order, an ordinal, a stored handle and the Enable
toggle's coordinates are not identity. `entry_no_numeric` is **mandatory** for every entry pair:
a `settings_numeric` capture can never licence this press, and the two contracts are never
interchanged.

Both pairs are the reader's own exclusive `capture-NNN` runs **under this invocation's
`--capture-dir` root**: a pair claimed outside that root, or the decision's run reused as the
licence, is refused with zero presses. The licensing pair must also resolve the **same popup
handle** the decision capture bound, and its two digests must be its own frames. At the press the
popup and entry rectangles are read **then**, from the same win32 enumeration owner the resolver
uses — the licensing read's rects are not taken as an assertion — and the entry's live
popup-relative rect must equal the licensed one, so a moved, resized or repainted row refuses
with nothing posted and zero presses recorded.

The durable obligation is claimed (`O_EXCL` + `fsync`) before that second licensing capture at
the action boundary, and only the fresh binding is pressed once. The pre-press record says
`phase: obligation`, `action: pending`, `obligation_open: true`, `press: not_attempted`, and
`press_state_as_of` states that `not_attempted` is **as of that write** — a press may follow and
is not reflected there. If the post-press rewrite fails, that pre-press record is what remains on
disk; it is never rewritten as a success and must not be read as "no press happened". The CLI
then exits `1`.

After the press the module re-reads the screen and takes a **fresh settings** pair only when the
operator's full popup is visible; only a `settings_numeric` pair whose guards name the original
window and whose exact `Enable multiplexer` line reads `VISUAL_DISABLED` reports
`post_mode: VISUAL_DISABLED`. The CLI exits `0` only for that fresh pair with two re-derived
digests, one attempted press and **no** press, post or trial-record error — a raised press or a
boundary refusal can never be reported as a verified post. Any other surface, an absent capture
or a supplied-but-unproved capture leaves the post mode `UNKNOWN` and exits `1`.

**What `ready` means here.** The strip's three-button ready row is the only store fact the command
reads: it states that the strip reports no recording and no held/stored data. Data the strip does
**not** report — an invisible historical store, a block scrolled out of view, a recording started
elsewhere — may still exist and is not inspected. The command takes no destructive action: it
never presses `Enable`, `Record`, `Stop` or `Clear`, never opens the popup and never retries.
**No live acceptance:** the press and its readback have not been exercised on the instrument; the
source test uses authentic entry/settings fixtures and a Win32 double.

The new enable post-press readback above is likewise **offline verified only**; neither command's
post-press readback has been exercised live.

**Live press observed once, 2026-10-22.** The guarded enable was exercised once on the instrument
from a verified `VISUAL_DISABLED` + `ON_PROVEN` full popup: one press, `posted: unknown`. Under
the build of that run the command took no post capture and therefore exited `1`; the operator's
separate read-only top-level capture of the clipped popup (158x43) then showed its painted caption
`Desable multiplexer` on two stable frames, and the operator restored the previous state
(`VISUAL_DISABLED`, rolling off) with their own gestures. That is an observed visual
corroboration, not a native checked state, and **no physical relay behaviour was measured** — the
relay warning stands. The automatic post readback above has **not** yet been exercised live.
Source: `.hermes/scratch/multiplexer-development/enable-live-01-acceptance.json` and its
`enable-live-01*.log` / entry PNGs (git-ignored local evidence).

**Label-band correction (pre-live), 2026-10-22.** The `ENABLE_MULTIPLEXER` raster was learned from
the full popup's first ink band, rows 14–26 — which is the separate `Use only channel` control's
caption, not the Enable line (true letter bounds rows 48–60, `(29,48,138,61)`). The template is a
semantic false mode proof in that state: a popup with the Enable row absent, repainted or swapped
for `Desable multiplexer` still matched and read `VISUAL_DISABLED`, which the guarded enable would
have accepted. The raster has been relearned from the committed authentic disabled-rolling-ON/OFF
frames at the Enable band and the generator, constants and bind now carry per-surface bands with no
first-band default. The fixtures were not modified; the retained captures and their digests are
untouched. See `docs/dop3000/mpx-mode-read.md` §"Label provenance".

---

## Live validation (simulator)

Three points were executed by the committed driver (`Win32Actuator`) on the
running simulation application — **unattended, no operator action, no application
wedge** — and the strip returned to a known-good startable state after every
point *(measured)*. They change nothing in §§1–10; they change what the runner
must do *between* points.

| point | stored | what it showed |
|---|---|---|
| 1 | **8,272,897 B** | ~6,045 implied profiles at 805 gates — a stale buffer, ~60× the expected size |
| 2 | 87,281 B | ~64 profiles at 805 gates, 1.5 s — clean, after `Clear and restart` |
| 3 | (write-path point) | 403 gates at resolution index 1, depth 100 mm |

**A stale buffer is the contamination, not accumulation per point.** Point 1 was
recorded into a buffer that still held roughly 6,000 profiles from earlier work:
while it ran, the application's own status bar showed large **negative**
`Time between profile` values — average and maximum — and the store wrote
8,272,897 B where ~90–140 KB was expected. That is about **60×**, i.e. roughly
**6,045 implied profiles at 805 gates**, and the file is valid-looking: nothing in
it announces the corruption, so a sweep would have logged the point as good and
corrupted itself silently.

**The reset is the fix.** Point 2 pressed `Clear and restart` first: same 805
gates, 1.5 s, and the store wrote **87,281 B** (~64 profiles) with the negative
timing values gone. The 60× case was therefore entirely stale *buffer content*,
not something a point accumulates — `Clear and restart` before a point removes it
(press it in the no-slider view, then poll for `Record`, §4).

**Point 3 exercised the parameter WRITE path.** `RESOLUTION` then `GATES` were
written and read back as requested (`'0.243'`, `'403'`), and the stored file
decoded to **403 gates**, resolution **index 1** (0.2433 mm at `c = 1460`),
**depth 100 mm**, burst 4, emissions 150, PRF 169 µs — the depth law of §3,
confirmed from the file's own words on a point the *driver* wrote.

**The size signature catches the 60× case.** It is the BDD's own structure, not a
payload-only rate: **31,268 fixed bytes**, one depth block of `19 + 2×gates` bytes, then
one signal block of `19 + gates` bytes per profile. The two clean 1.5 s points are **79 and
78 profiles** at 805 gates (`31,268 + 1,629 + 79×824 = 97,993 B`, and 78 for the 97,169 B
file) — the earlier "~71 profiles" was the request-derived estimate, and the earlier
"1.7 bytes per gate-profile" was a rate that only happened to fit because those files
carried many profiles. The complete sparse pass reproduces the structural equation
**byte-for-byte on 26/26 files**; the payload-only rate was wrong by 23 % at 50 gates, 50 % at
145 gates and 5 % low at 31 gates, and it falsely rejected the four valid emissions-128
points at 3.14× when their 144 profiles made the fixed bytes dominant
(`data/sparse-mixer-first-pass/README.md`). The band stays a gross factor of two, because
the profile count before storage is the requested period's estimate while the file's
timestamps establish the achieved count only afterwards.

**Consequence for the runner:**

1. **Reset the block before every point** — `Clear and restart`, then poll until
   `Record` is present again. Never record into whatever the previous point left
   behind.
2. **Refuse a point that fails the size signature.** A contaminated point that is
   logged as valid is the worst failure mode available: not a crashed run, but a
   wrong number in the matrix that nothing downstream can detect.

**Unresolved.** The text of the warning the application raises when the per-block
profile cap is crossed was still not captured — the state clears before it can be
read (§11.3).
