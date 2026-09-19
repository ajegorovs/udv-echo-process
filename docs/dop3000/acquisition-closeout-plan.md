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
