# Plan — close the acquisition refactor on the device, then run the experiment

**What this plan is.** The work list for the stretch that follows the observation/interpretation/action
refactor (`refactor/acquire-foundation`, [PR #10](https://github.com/ajegorovs/udv-echo-process/pull/10)):
land the open stack, close the refactor's **device-pending** items in a fixed and safe order, and ask the
one question that unblocks the experiment. It plans **no new acquisition architecture** — the batch review's
stop condition (campaign plan §9.1) already bound that, and re-opening it needs evidence (a real campaign
failed, evidence came back ambiguous, or the analysis cannot establish a condition), not another
improvement.

**What it is not.** It carries **no verification checklist**. The items, their pass criteria, the stop
condition and the promotion rules are [`device-verification.md`](device-verification.md), which is their one
authoritative copy; this plan only decides **the order they are run in, what each one unblocks, and what
must not be attempted before which**. Its "where the work stands" section supersedes the running chronology
in `acquisition-campaign-compilation-plan.md` §11.1, which was written before the refactor and before the
2026-09-18 freeze and is now historical.

**Revision this plan was written against.** `refactor/acquire-foundation` @ `b007278`, `master` @ `40d7cb2`,
`agent-context-handoff` @ `db9656a`, `feat/acquire-stated-process-mode-layout-shape` @ `8edd589`
(all measured with `git rev-list --count origin/master..<branch>` on 2026-09-19).

---

## 1. Where the work stands

The three pull requests that carried everything not on `master` **landed on 2026-09-19**, in the order §2
recommended; their relationship is not guessable from the PR list, so it is stated rather than implied:

| PR | branch | commits past the `master` it was written against | what it was | as landed |
|---|---|---|---|---|
| [#8](https://github.com/ajegorovs/udv-echo-process/pull/8) | `feat/acquire-stated-process-mode-layout-shape` | 1 (`8edd589`) | the stated process mode and the layout gate (§24): a shape check that needs no total, `--expect-mode` on every record path | **merged second** — `e8fe2ac`, with both live findings disclosed in [a comment](https://github.com/ajegorovs/udv-echo-process/pull/8#issuecomment-5740415089) that names each finding's fixing commit |
| [#9](https://github.com/ajegorovs/udv-echo-process/pull/9) | `agent-context-handoff` | 9 (`aec22dd`..`db9656a`) | docs, skills and tools: the forked skill reconciled and renamed, the crop set indexed, its checker added | **merged first** — `b2f74ea` |
| [#10](https://github.com/ajegorovs/udv-echo-process/pull/10) | `refactor/acquire-foundation` | 53 | the refactor, plus the ten device-driven corrections it forced | **merged last** — `5f74b8f`, after `9260d9c` merged `master` into it |

**Two facts about that stack carried the landing decision.**

- **`#10` was based on `#9`, not on `master`** (`bfbbb10`'s parent is `db9656a`), so merging `#9` is what
  made `#10` belong on `master`.
- **`#10`'s history contains `#8`'s head as a merge commit** — `bfbbb10`, *merge(acquire): PR #8 head
  (stated process mode + layout gate) as the refactor base*. `8edd589` is an ancestor of `b007278`, which
  is what made it safe to land `#8` first with its findings fixed only downstream.

### 1.1 As landed — and the two things the platform did that this plan did not predict

The recommendation held end to end: the gate landed as its own reviewed slice with its findings **disclosed
rather than carried silently**, and nothing was backported into the code the refactor replaced. Two platform
behaviours are worth keeping, because both cost time and neither is about this repository's code:

- **Deleting a merged base branch *closes* its dependent PR; it does not retarget it.** Merging `#9` with
  its branch deleted left `#10` in state `CLOSED` — not `MERGED` — instead of moving it onto `master`. The
  recovery: recreate the base ref at its own commit (`db9656a`, already an ancestor of `master`), reopen
  `#10`, retarget it to `master`, then delete the resurrected ref again. **The rule this yields: retarget a
  dependent PR before deleting the base branch it points at** — which is why `#11`'s base was moved to
  `master` before `#10`'s branch was deleted.
- **A reported merge conflict can be stale.** Right after `#8` landed, the API reported `#10` as
  *conflicting*; a local `git merge --no-commit --no-ff origin/master` into that branch was **clean**, with
  nothing to resolve. The branch took the merge commit (`9260d9c`), the API recomputed `MERGEABLE/CLEAN`,
  and the merge went through unchanged. **Check a reported conflict locally before engineering around it** —
  here, a rebase or a hand resolution would have been work done to satisfy a race.

**What is verified, and at which revision** (the distinction the whole page exists to keep):

| claim | revision | evidence |
|---|---|---|
| the cloud suite is green | `b007278` | re-run on 2026-09-19: `1843 passed, 22 skipped in 93.98s`; `ruff check src tests` → `All checks passed!` |
| **V0** — the read-only inventory on the instrument | instrument, refactor head | `device-verification.md` §Session record 2026-09-18 |
| **V2**, precondition and read-only gesture halves | `7de790c` | `device-verification.md` §Session record 2026-09-19: hover → topmost entry → the measured dialog → channel `1` → safe close → an identical post-run status |
| the review fixes are **not** device-verified | `00fd6a0` + | the same bracket stopped *before* the hover because UDOP was not foreground; nothing opened, nothing was stranded |
| V1, V2's write half (`ensure_channel`), V3–V8 | — | device-pending |

So the honest sentence today is: **the refactor is cloud-verified at its final head and device-verified at
`7de790c`**, one read-only gesture short of its own head. Closing that gap is sitting A.

**One live state fact a reader of this plan must not trip over.** UDOP was in *either* build at any point;
the window caption (`UDOP Simul` / `UDOP DOP3010.43`) is the only discriminator, every geometry measurement
is per-mode, and the instrument's strip rect is `[343,414,695,454]` where the simulation rect is the one the
repo still asserts. Nothing here has been run in the other build.

---

## 2. Landing the stack — the one decision this plan makes

**Recommended order: `#9` → `#8` → retarget `#10` → `#10`** — executed on 2026-09-19 (§1.1 records what the
platform did that this plan did not predict) — with one disclosure comment posted on `#8` before it merged.

- **`#9` first** because it is independent, unreviewed-but-mechanical (docs, skills, tools), and it is
  `#10`'s base — merging it is what retargets `#10` onto `master`.
- **`#8` next, with the two findings disclosed rather than fixed.** The findings' fixes exist **only on the
  refactor branch**: `849381b` (never read a channel mode out of an absent parameter column — §26.12's
  finding), `51db063` + `00fd6a0` (classify the active surface before resolving press targets; the guards
  and the popup distinction restored — the overlay-open clause order), and `d04a88c` (a four-button row
  without a slider binds nothing, and refuses — V4's "refuse before mapping" half). Backporting them into
  `#8`'s flat `driver.py` would be duplicate work on the code the refactor deleted, so the disclosure is a
  **PR comment naming each finding and the commit that fixes it**, plus a line in `#8`'s description stating
  that its review findings are closed on `#10`. Both open findings are *refusal-path* misdiagnoses, not
  silent damage, and no device run is scheduled in the window between the merges.

  **One measured correction to carry into that comment.** `acquisition-campaign-compilation-plan.md` §11.1
  says *two* live findings are posted on `#8`; read from the repository's own API on 2026-09-19, `#8` carries
  **one** issue comment (the absent column, 2026-09-18 15:07) and **no** review submission, and the
  overlay-open clause order is recorded only in `#10`'s body and in that bullet. The disclosure comment had
  to state both findings rather than link the one that was there — otherwise `#8` would have merged under a
  reviewed-sounding summary with an empty discussion behind it. It was posted before the merge:
  [`#8`'s second comment](https://github.com/ajegorovs/udv-echo-process/pull/8#issuecomment-5740415089).
- **`#10` last**, as one reviewed change: it already contains `#8`'s commit, so nothing is lost by the
  order, and `#10`'s diff shrinks by one commit when `#8` lands first.

**The alternative, recorded rather than hidden: close `#8` as superseded by `#10`.** Its single commit is
already an ancestor of `#10`'s head, so the outcome on `master` is identical and it is one fewer merge — at
the cost of retiring the slice label the plan's §24 created and moving a reviewed slice's findings into
another PR's history. Recommended against only because the gate is a coherent, independently reviewed slice
that costs one merge, not because the alternative is wrong.

**Not part of the decision:** the ordering of `#10`'s own commits. It is one reviewed change, its internal
phase order was reviewed (`f4137bc` … `b007278`), and this plan does not re-open it.

---

## 3. The device sittings — four, in this order

Each sitting is bounded by the precondition set in `device-verification.md` §0, and the **stop condition**
there (§Stop condition) applies to every one of them: no new automation, a device-forced fix is its own
commit, and if the application's state becomes unverified the sitting stops and the operator restarts it
rather than any speculative recovery.

**Why this order, in one sentence:** read-only before gestures, gestures before writes, refusals before
writes, and **one state-changing item per sitting** — so that a stranded popup (nothing this driver sends
dismisses one, ledger B20) costs one item rather than a sitting.

### Sitting A — the refactor's own gap, read-only (~15 min, no state change)

1. **The exact V2 bracket on `#10`'s merge head** — `acquire status` → `w1_fixed_facts.py` →
   `acquire status`, with UDOP already in the foreground, the revision recorded, `PROBE_TIMEOUT_S=240` on
   the probe. This is the one item standing between "the review fixes are device-verified" and "cloud only";
   it moves a cursor, opens a popup and a dialog, and presses the topmost entry and the dialog's left
   button — nothing else.
2. **The `89` test** (`ui-element-index.md`, campaign plan §26.6): read each edit's tree text and compare it
   against the *painted* text in the same moment. It is a read-path rule — *an edit's tree text is not
   evidence of a displayed parameter unless it is painted* — and it settles a value that has appeared in
   three separate measurements.
3. **The cursor info box** (campaign plan §26.9): does its depth and value exist in the tree, or only in
   paint? This decides whether an app-side readout is available to the experiment *at all*, or whether the
   analysis stays post-processing (which is where §26.11 already decided it lives).

**Sitting A changes nothing on the instrument.** It passes when the pre- and post-run status readings are
identical field for field and the probe reports no stranded popup and no error key — the same pass shape as
the successful `7de790c` run, now with UDOP in front.

**Outcome, 2026-09-19.** Item 1 **passed on the merge head** (`5a36b40`, `is_foreground: true`, so the
guard the earlier attempt tripped on was satisfied): the two status readings are identical field for field
**except the `cursor` field the gesture moved** (`[1874,0]` → `[453,0]`), the dialog resolved live at
`(655,364,1282,748)` with 21 direct children and its own channel `1`, the three dialog-only fields read
`source: read` while the same snapshot *not* handed a reading calls them `unreadable`, no error key names
anything, no popup was stranded, and the close is answered by the screen (`0 dialog panel(s)`). Item 2
**confirmed the `89` rule on the pixels**: the four dialog edits read `89` while their combos paint
`1.776` / `4` / `medium` / `Medium` (crop `UI-OVERLAY-24`), and two sidebar combos do the same in the same
screen read. Item 3 **sharpened rather than closed**: with no cursor placed the monitor side carries
exactly two controls — the plot `[200,65,1910,1006]` and the bottom bar's `Exit` — and no text anywhere,
but the info box was not up in this sitting, and a window this application spawns over the plot need not
descend from `TMain_Scr`, so the read that settles it is a **top-level window enumeration** with the box
up; it joins sitting B, which already asks the operator to reach a state by hand. V5's cap is untouched by
all of it. Full record: `device-verification.md`, *2026-09-19 — the V2 bracket on the merge head*.

### Sitting B — V4, the four-button strip role map (the critical one, operator-driven)

The operator reaches the **block-held / grown-strip** state by their normal workflow; **the automation
presses nothing on the strip**. One moment is captured: the strip panel rect, every visible top-row button's
handle, class and rect, slider existence and visibility, all strip descendants, a screenshot of the same
moment, and the block/status indicators. Then the two questions a crop cannot answer are answered by the
operator and the tree together:

- **is the button at index 1 one control that relabels, or two different buttons?** (the contradiction
  between `UI-STRIP-01` and `UI-STRIP-02`), and
- **does the grown row report a slider, and is the row `STORE` or `READY`-with-block?** — the state question
  that stands beside `campaign plan §26.13`'s four-button identification.

**What this sitting cannot reopen:** on the final head the ambiguous row already **binds nothing and
refuses** (`d04a88c`), so the procedure's "pass before mapping" half holds today. What the sitting converts
is a refusal into a **map**, and the procedure requires all three witnesses — tree, pixels, and a safe
observed transition — before the code may gain one. The same visit is the best chance to identify the
**"two caption-less buttons below the strip"** (`ui-element-index.md`'s outstanding unknown): it wants a
tree read in the state that paints them, not a photograph, because a camera cannot name a control.

**Outcome, 2026-09-19 — the map exists, and it is not one mechanism.** The operator reached the block-held
state by hand, left the monitor paused and placed a cursor at 45 mm; the capture ran on the **same process**
the V2 bracket had read two minutes earlier (hwnd `3935144`), which is what makes the handle comparison below
a measurement rather than an inference. Nothing on the strip was pressed by the automation.

- **The row is four visible `TSp_Button`s in the strip's own grown panel** (`3149132`, `[343,414,894,537]`,
  551x123, ten direct children — against the `ready` strip's `[343,414,695,454]`, 352x40): `1574908`
  `Resume`, `2821164` `Do store`, `1641666` `Clear and restart`, `7867344` `Remove current block`, each
  caption bound to its handle by position.
- **The row is drawn from a pool of five button controls, not one slot per position** — measured across
  three states in one process: `1574908` is the **one** control that relabels (`Pause` → `Resume`);
  `4787852` keeps `Record` and is hidden when a block is held; `2821164` keeps `Do store`; `1641666`
  keeps `Clear and restart` in every state; `7867344` (`Remove current block`) appears only with a held
  block. The intermediate state shows `Record` **and** `Do store` side by side, so the two are not
  competing for one slot, and `ui-element-index.md`'s finding 20 is corrected accordingly.
- **The grown row does report a slider**: `TSp_Sliding_Bar 3344390` `[465,449,897,499]`, a direct child of
  the strip panel, painted as a two-handle range (`1513` … `8297`, `6785` under the track) — with a second,
  hidden one elsewhere in the tree, so the class alone does not identify it. The combo `1967830`
  (`Show block`) reading **`2`** is the one app-readable value in the state.
- **The two caption-less buttons are the `Profiles history in second / profile` selector pair**
  (`2690436` `[350,467,401,482]`, `1967842` `[409,467,453,482]`, the green tick on `profile`) — that unknown
  is closed, and the read it needed is the one taken here.
- **Two false diagnoses on the state, both safe and both wrong.** The strip resolver returned
  `view: "unknown"`, `button_count: 0` and named **the cursor info box** as the strip (nothing was pressed;
  the refusal is `d04a88c`'s designed behaviour, but the diagnosis misdirects a caller). And the layout
  classifier reported **"a dialog is up"**, naming the strip's own grown panel, with the active surface
  reading `dialog` and **50 visible controls in 5 panels** against the clean 44 in 4 — so the `>400 px`
  predicate that admits the `Define TGC` overlay admits **the strip itself**, in the state a held block puts
  the screen in. That is the boundary sitting C was going to inspect for the overlay; it is now a measured
  fact about the strip, and it is the more important of the two.
- **The cursor info box is in the tree but its numbers are paint only**: two caption-less panels
  (`131916` + `131920`), and no control text in any of the process's 46 top-level windows carries a depth or
  a velocity. Sitting A's third item **closes** on that: the analysis stays post-processing, as §26.11
  decided, and those two numbers come from pixels or not at all.
- **The intermediate state was read too** (11:55, same process): panel 453x40, four buttons — `Pause` /
  `Record` / `Do store` / `Clear and restart` — and it paints nothing below the row while the tree still
  reports the slider hidden and the `Show block` combo and the toggle pair `visible`; the `Show block`
  value is **`1`**, i.e. no block held. **And the fourth combination is read too**: UI-STRIP-04's state
  (three buttons and a slider) was reached live at 12:03 and is the strip's `store` view — the pool's
  predicted handle row, panel rect and `Show block` came out exact, so all four states of this row are
  read rather than inferred. **Left open:** the `STORE` versus `READY`-with-block naming, and V5's cap.
- **The slider's own arithmetic, measured** (12:11): its painted numbers are the **displayed block's** profile
  range with the range's length between them — `1` … `4772` with `4772` in the store state, `4773` … `16381`
  with `11609` once block 2 is held (`16381 - 4773 + 1 = 11609`). So the **block boundary is legible from
  pixels alone**, and the store state is the only one whose strip resolves. The step's prediction was ten of
  eleven exact (the miss was the slider's left end), and the block-held state reproduced a **third** time
  byte-identically (`+0 / -0 / moved 0 of 273`).
- **The buffer model, measured on three blocks** (12:19): the `Show block` combo selects which block the
  strip's slider paints, and the slider is that block's profile range with its length between the numbers —
  `1` … `4772` (4772), `4773` … `16381` (11609), `16382` … `26771` (10390). The ranges are **contiguous over
  one monotonic profile counter**, i.e. sequential partitions of a single global buffer, and the pause that
  ends a block puts the slider's right end at exactly the profile the bottom band's counter stands at — two
  independent painted surfaces agreeing. `Show block` is the *selected* block and need not be the one being
  acquired (at 12:14 the combo read `2` while the band read `Block : 3`). Each pause/resume cycle opens a new
  block, so one cycle costs one block. `Memory : Filling` stays painted after the pause (it describes the
  buffer), and the band's painted `22.4 ms` per profile still disagrees with the observed rate (~16-31
  profiles/s across two windows) — an unreconciled timing item for §16.4.
- **The block-held state reproduces exactly** (read again at 11:59 after the operator passed through the
  intermediate state): `compare_reads.py` gives **tree delta `+0 / -0 / moved 0 of 273`**, the same ten strip
  children at identical handles and rects, the same `Show block` = `2`, and the same two misdiagnoses — so
  neither the state nor the wrong diagnoses are one-off. The four transitions between the states are now
  **observed** by the operator (the third witness V4 wanted), with three of the four states read.
- **The model was tested by prediction, and it holds — and the test found a third false positive.** From the
  `Pause` / `Record` / `Clear and restart` state the operator was asked to press `Pause`, with the outcome
  predicted in advance: the row's handles, their rects, the panel's rect (`[343,414,713,537]`, from a sizing
  rule derived from the three measured states), the slider's presence and `Show block` = `1` all came out
  **exact** — as did the prediction that the `>400 px` dialog predicate would stop firing at 370 px
  (`0 dialog panel(s)`). What the prediction missed is that **another** wrong readout takes its place: the
  screen reports `open_popup: True` and the surface reads `popup`, because the **cursor info box** (`131916`)
  directly owns one `TSp_Button` (`131918` — the control recorded as visible while painting nothing) and the
  popup predicate is "a panel that is not the menu, not the status bar, not the strip and not a dialog, and
  that hosts a button" (`driver.py:1102`). The three wrong readouts **hide each other**: while the strip
  resolver named the info box as the strip and the classifier named the strip a dialog, the popup test had
  no candidate and printed "no menu popup". So the popup false positive appears **only once the other two
  classify correctly** — which is the argument for naming the box's identity once, rather than each symptom.

Full record, with the rects, the handles and the two refusal texts: `device-verification.md`, *2026-09-19 —
the four-button strip, block-held*.

### Sitting C — the refusals, three cheap items (~20 min)

1. **V3 — the overlay refusal, with the overlay the refactor is unsure about.** Open `Define TGC` by hand
   (**without modifying it**), run status/compile, confirm the refusal names an active overlay /
   non-measurement surface **before** blaming the strip or the sidebar, and that no press was attempted
   against overlay state; cancel by hand; re-read a clean status. This is also the device evidence for
   `#10`'s one deliberately-open item: the canonical `>400 px` dialog predicate also accepts the measured
   `Define TGC` overlay class, actions now refuse when that union is non-empty, but `_close_any_dialog` can
   still treat an operator-opened panel in that class as a dialog. The sitting should capture whether any
   cleanup path *tried* to press it — that reading is what decides whether the boundary needs code or only a
   sentence.
2. **V1 — the sidebar preference, now cheap and known.** Untick `Show fast access parameters panel`, run
   status/compile, confirm the run refuses a manual channel **and does not claim `assisted`**, naming the
   preference; tick it back; re-read a clean status (44 visible controls in 4 panels). The 2026-09-18
   incident (§26.12) measured this state **and its recovery** by accident, so the item's cost is two
   `Preferences` interactions and its risk is bounded — and it is now the *only* item that requires
   deliberately reproducing a configuration this experiment otherwise forbids touching.
3. **V5's declaration-only half.** Compile the matching definition and make one **declaration-only** mismatch
   without touching the instrument: the run must refuse before `Record` and write no `.BDD`. Confirm the
   block cap stays **explicitly unproven** — it is a `Preferences` value, not a parameter, so a painted
   number is evidence, not a read path.

### Sitting D — the writes, and the milestone

1. **V2's write half: `ensure_channel`.** The routing route presses the dialog's **accept** end and writes
   the channel before it reads — a different path from the read the `7de790c` session ran. Run it on the
   channel the instrument already stands on, or with the operator standing by to restore the channel; the
   pass criterion is that the dialog's own channel, the routed channel and the run's configuration agree
   afterwards, and that the screen reads clean.
2. **V6 — the six-point campaign through the compiled path, on the instrument.** This is the milestone, not a
   verification chore: the same campaign the simulation run already passed, now with the instrument's own
   frame declared and compiled. Pass: exactly the expected files, every point verified (channel,
   gates/resolution, covariates, retained window, verdict), and no unexplained overlay or popup afterwards.
3. **V7 and V8** — resume identity, and post-run recovery (intended frame, no popup/dialog/overlay, the
   cursor not clipped, the expected store directory, the device outputs preserved with the session record).

**Why V6 is last and not first:** every item above it either proves the refusal that precedes a write or
proves the state a write stands on. A campaign run before those is a run whose failure could not be
attributed — and the review of this batch exists precisely because that attribution was missing.

---

## 4. The one question that unblocks the experiment

The acquisition architecture stops growing here (campaign plan §9.1), so what remains is the **matrix** — and
it is the only thing left that measurement cannot settle. `§26.13` landed one question on the operator's
desk, and this plan makes it the gate for the next stretch:

> **Is `experiment_data\mixer\sensitivity-analysis\4MHz\0500RPM\001\burst_len` the experiment this work is
> for?** It was read off the application's own compare picker: a mixer, under a folder named
> *sensitivity-analysis*, organised by emitting frequency, RPM, run and burst length, with a file series
> (`2, 4, 6, 8, 12 … 32.BDD`) that looks like a burst-length sweep.

- **If yes:** the matrix's first line is already answered — the target is a mixer at a stated RPM, the axes
  are the ones the operator's own tree already names, `§26.9`'s flat monitor is explained by nothing on the
  bench turning, and items 3–5 of `§11.1` collapse from a design job into a **confirmation plus a gap
  analysis** against the axes that tree names (which axes already have a write path: resolution and gate
  count do, through the sidebar).
- **If no:** the matrix is a design decision and needs the operator's sweep note, not more reconnaissance.

**What hangs on the answer, and what does not.** Nothing in §2 or §3 depends on it — the landing order and the
four sittings are the same either way. What depends on it is **everything after V6**: which writers are
funded (campaign plan §11.1 item 5 — only the ones an axis requires), whether the application's own
`Sweep PRF` search is an axis or a curiosity (`§26.7`), and whether an app-side readout is needed at all
given that the comparison of record is done in post-processing (`§26.11`).

---

## 5. Not in this plan

- **No new acquisition architecture.** §9.1 binds; re-opening needs evidence from a real run.
- **No writers before the matrix names the axes.** The five unturned knobs stay candidates, not a work list
  (`§11.1` item 5). The four-button role map is the one mapping exception, because a strip press is what a
  batch of points needs and the ambiguity is already refusing.
- **No assisted mode, ever, as a test case** — it is a refusal case (the procedure's own precondition).
- **Nothing presses that changes state** outside the four sittings above, and no modal is left open while a
  probe runs.
- **Housekeeping stays behind the work:** `tools/live/README.md` is stale, the `udv-live-gui-probe` skill
  wants review, and the sampling-volume rejection modal stays uncropped deliberately (§26.11) — provoking it
  means a write of exactly the class this work refuses to make for a picture.

---

## 6. Picking this up cold

```bash
cd C:/Repos/udv-echo-process
git fetch origin
# the stack, in the order §2 recommends
git switch agent-context-handoff      # PR #9
git switch feat/acquire-stated-process-mode-layout-shape   # PR #8
git switch refactor/acquire-foundation                     # PR #10, head b007278

# the cloud gate, at the revision under test
uv run --no-sync --extra dev ruff check src tests
uv run --no-sync --extra dev pytest -q

# the device sittings: the items and their pass criteria are device-verification.md;
# the read-only probes are tools/live/dispatch.sh <bare file name>
```

Read, in this order: this page → [`device-verification.md`](device-verification.md) (the items and the
pass criteria) → [`acquisition-ui-model.md`](acquisition-ui-model.md) §6 (the blind-spot ledger, and what
each item moves) → [`acquisition-architecture.md`](acquisition-architecture.md) §1 (the evidence levels a
result has to reach) → `acquisition-campaign-compilation-plan.md` §23, §26.12, §26.13 (the live findings
the refactor's corrections came from).

**Evidence that cannot be committed.** The readings a live session leaves live under `outputs/`, which is
git-ignored. Their authority is the session record that quotes them — name the file and quote what it
printed — because the external reviewer cannot see them and a claim that only exists on this machine
verifies nothing.
