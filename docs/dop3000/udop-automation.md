# UDOP automation — driving a DOP3010 sweep unattended

How a sweep point is **set, recorded, stored and validated** with nobody at the
console: the write recipes that actually commit, the order they must be written
in, the record strip's state machine, the store chain, and the failure modes
that silently invalidate a point.

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
> (`~/Repos/dop-control`) — `docs/14-input-methods.md`,
> `docs/15-labelled-fixture.md`, `docs/16-record-strip-automation.md`, and the
> `recon/` scripts those documents cite (`recon/05`, `08`, `14`, `30`,
> `33`–`35`, `40`–`42`) with their JSONL logs and captures. Nothing below is
> inferred from the manual alone, and nothing below should be re-derived from
> the manual instead of read here.

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
| injected real input (`SetCursorPos` + `mouse_event`) | — | **no** |
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
- The app writes its own derived window to **word 2 (`Depth`)**, so
  `depth = first gate + gates × resolution` can be checked inside the file
  without re-deriving the physics.

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
4. **`Stop`** — the panel grows to the store view (413x123) and a
   `TSp_Sliding_Bar` child appears.
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

**Strip buttons outside the record cycle:**

- `New acquisition` — dismisses the store prompt and returns to the recording
  view; it can raise a data-loss warning.
- `Remove current block` — deletes the selected block, guarded by
  `WARNING — All data contained in the current block removed from memory`, whose
  `[Cancel]` is the left of its button pair.
- `Clear and restart` — the release valve between points. Pressed in the
  no-slider view, the operator sees `Record` disappear and the strip collapse to
  two buttons for **~3–4 s** while the buffer is rebuilt, so the loop must
  **poll until the `Record` button is present again** before pressing `Record`.
  Pressed from the *store* view it produced no visible change here, so its effect
  is view-dependent: press it in the no-slider view, then poll.

---

## 5. The strip's view states — recognise structurally, press by order

The strip is a **draggable floating panel**, and its own rectangle changes with
the view (`352x40` → `98x40` → `413x123`). Locate it **structurally** (the parent
of the recording widgets), never by remembered coordinates, and re-resolve after
every press.

| view | how to recognise it | buttons, left → right |
|---|---|---|
| recording | 1 top-row button, no slider | `[Stop]` |
| stopped, no data | fewer than 3 buttons | `[Record]` |
| **stopped with data** | 3 top-row buttons, **no** `TSp_Sliding_Bar` child | `[Pause] [Record] [Clear and restart]` |
| **store view** (after `Stop`) | 3 top-row buttons **+** a `TSp_Sliding_Bar` child | `[New acquisition] [Do store] [Clear and restart] [Remove current block]` |

- **Identify buttons by their ORDER in the view, never by width.** 134 px vs
  138 px was the difference that once produced a data-loss warning.
- The strip's child list is **not** the three buttons you can see — it is up to
  ten windows, including state-specific buttons, the store slider, two combos
  and two never-painted buttons below the panel's rect.
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
- **Measure the period per point; do not trust the formula.** First evidence:
  `100 emissions × 200 µs PRF` was observed as `Time between profile = 21.2 ms`,
  i.e. roughly `emissions × PRF + ~1 ms`, with depth and sound speed also
  contributing ("the deeper we sample, the more it depends"). The manual's
  `T_profile ≈ T_tran + T_prf·(16 + N_PRF)` gives 23.2 ms + transfer for the same
  setting — close, but not the number the instrument reported.
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
it. Words 14, 27 and 84 are **not decoded** by `io/dop/bdd.py`, and
`ChannelConfig.sampling_volume_mm` / `wall_filter` are declared but never
populated, so a point cannot yet be identified from the file alone:

| need | word | state |
|---|---|---|
| `Emissions per profile` (`N_PRF`) — the primary variance axis | 14 | identity verified, not decoded |
| `Sampling volume` — identity verified *and* an index into a physics-driven list | 27 | identity verified, not decoded |
| `Number of skipped profiles` | 84 | identity identified; semantics unconfirmed |
| achieved profile period per point (`Time between profile`) | — | not stored as a parameter; log it instrument-side (§8) |

Adding them stays inside the existing agenda gate on extra decoded metadata:
word-level evidence (above), a destination domain field, propagation and storage
rules. The resolution law of §3 is the other useful addition — it makes a
point's gate geometry checkable from `word 10 + word 19` alone.

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
