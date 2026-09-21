# Agenda — udv-echo-process

The current, action-oriented backlog for this repository. Keep this file short:
when a status entry is superseded or no longer actionable, fold its durable
outcome into the appropriate design/reference document and add a compact row to
[`agenda-history.md`](agenda-history.md). Do not use this file as a session
transcript.

**Authorities:**

- Signal-model contract and acceptance checklist:
  [`signal-model-rework-plan.md`](signal-model-rework-plan.md)
- Current module/pipeline conventions:
  [`pipeline-conventions.md`](pipeline-conventions.md)
- Prioritized hardening work:
  [`hardening-plan.md`](hardening-plan.md)
- Marimo integration plan and evidence:
  [`marimo-integration-plan.md`](marimo-integration-plan.md) /
  [`marimo-integration-log.md`](marimo-integration-log.md)
- Historical timeline and superseded concepts:
  [`agenda-history.md`](agenda-history.md)
- The sparse pass's analysis work plan (WP0–WP5):
  [`dop3000/sparse-pass-analysis-plan.md`](dop3000/sparse-pass-analysis-plan.md)

---

## Current status — signal-model rework accepted

The Phases 1–9 implementation and post-landing hardening are **accepted**.
Source-root registration now replays source artifact identity, and
`OperationRecord` construction replays operation identity from its canonical
recipe. The final gate passed with 785 tests, Ruff check/format check, static
notebook validation, executed HTML exports for both notebooks, 67 focused
BDD/store tests, `git diff --check`, two independent counterfeit-ID probes, and
a fresh independent review.

The accepted boundaries remain those in the rework plan: five-field frozen
artifacts, one derivation constructor, normalized provenance, and no legacy
adapter.

### Settled synchronization contract

Cross-channel synchronization matches explicit `round_id`; every participating
row must have a non-duplicate `(round_id, visit_id)` identity, and a stream may
have only one visit in a matched round. A round groups cross-stream visits;
`visit_id` records within-round acquisition order. See
[`signal-model-rework-plan.md`](signal-model-rework-plan.md) §7.4.

---

## Active work — `udv-analysis` retirement

The absorption architecture is approved and implementation Phases 0–3 are
complete: the private reproducible retirement baseline, calculated BDD depth and
inspection work, typed operating-state detection, robust median/unscaled-MAD
profiles, the private 2-D TV-L1 preprocessing used only by that terminal
analysis chain, and the small terminal-result JSON/CSV/NPZ export boundary
(`udv_echo_process/export.py`). See
[`udv-analysis-absorption-plan.md`](udv-analysis-absorption-plan.md).

Implementation is complete. Retirement evidence is now bounded rather than
open-ended:

- **Predecessor provenance** (§8.2) is unrecoverable. The source cites an unnamed
  Python `QuantileRegression` dependency and earlier “State 5” output that do not
  exist locally; its single-commit history and removed public upstream offer no
  earlier artifact. The echo Mathematica notebook is a confirmed same-campaign
  relative, but contains no quantile LP or state segmentation and is not claimed
  as the direct predecessor. Its `QuantileRegression.m` import points to an
  absent Windows-local file.
- **Dependency audit** (§8.3) is clear within `~/Repos`: no sibling dependency
  declaration, source import, CI job, or notebook consumes `udv-analysis`.
  External machines remain outside the auditable scope.
- There is no real multi-state velocity fixture; multi-transition equivalence is
  therefore proven against the retiring implementation on synthetic topology,
  while all archived real runs are steady single-state cases.

The source checkout and private retirement pack remain in place; deleting them
requires a separate explicit decision — upstream is unreachable, so the pack is the
only remaining copy. The pack was re-verified on 2026-09-12 (git bundle records a
complete history, 167/168 files match their recorded sha256, 26 archived-baseline
tests run and pass against it). The **standing file-level register** — every tracked
source file's disposition, the unported items, and the verify/reconstruct recipe —
is [`udv-analysis-reference.md`](udv-analysis-reference.md).

Open decisions from that register:

- Trace attribution for the absorbed MIT-licensed source: this repo carries no
  `LICENSE`/`NOTICE`, and the pack's `licenses/` copies are the only surviving
  statement of terms.
- Re-seal the pack's `inventory.json`, whose recorded hash for
  `baseline/validation_report.json` is stale (the report was rewritten ~1 min after
  the seal).
- Decide whether the unported register items are wanted: the exclusive depth rule,
  `ChannelConfig` metadata coverage, and the visualization intents.

---

## Active work — sidebar notebook: time/gate selection

`notebooks/channel_preview_sidebar.py` is the sandbox for the live-sidebar
pattern (the selection cascade hosted in `mo.sidebar`; the pattern itself is
written up in the provider repo's examples tree).

**Landed 2026-09-12** — the four-control cascade is in place: recording →
channel → **time** (`time_cursor`, a profile-index slider) → **gate**
(`gate_cursor`, the old trace-view dropdown promoted into the sidebar). Both
cursors drive the views, and the **heatmap crosshair** draws them on the
time×gate map (vertical line = time, horizontal line = gate). `TraceScrubber`
was **removed**: its scrub index is browser-local, so a second time cursor
could only ever disagree with `time_cursor`. New `time_slice` (one profile
across gates) and `cursor_readout` cells; `interp_trace` / `filter_gate_trace`
now consume `gate_cursor`. Gates passed: `marimo check` (clean) and
`marimo export html` — 5 sidebar blocks in cascade order, with the heatmap
carrying both line shapes at the selected t / depth.

**Landed 2026-09-12 (second pass) — time step buttons.** The time cursor now
carries `−page / −1 / +1 / +page` buttons (`page = max(1, n_profiles // 10)`, so
±40 on a 400-profile fixture). Three cells, because it must be: `time_picker`
creates the slider, a buttons cell declares them, and a composition cell renders
`mo.sidebar(mo.vstack([...]))` — shelling the two halves into one sidebar block
(two `mo.sidebar` calls stack as separate blocks). The buttons write the **same**
`mo.state` the slider's own `on_change` already wrote (`cursor_stores`'s
`time_default`), so slider and buttons cannot disagree — no new state, no custom
anywidget, and the frontend slider follows. The handler uses the functional
updater (`State.__call__` accepts a callable), so the index is read at click time
and a rapid double-click cannot lose a step. Verified live through MCP: `+1`
200 → 201, `+40` → 241, `−1` → 240 with the readout following each time, and a
`−1` at index 0 stayed at 0. Coarse jumps remain mandatory — the time axis is 400
profiles in one fixture and 4193–4927 in another.

**Next pass — gate slider and cleaner cursor text** (requested 2026-09-12).

- **Promote the gate cursor from a dropdown to a slider** over the gate index,
  labelled with the depth in mm, and give it the same
  `−page / −1 / +1 / +page` button set as the time cursor. The gate is the last
  control still on `mo.ui.dropdown`, so this is what makes all four cascade
  levels uniform — and it makes the gate step-drivable from MCP exactly like the
  time cursor. Sized separately from time: the gate axis is 26–55 entries
  (200RPM.BDD ch6: 55 gates, 20.00 → 79.13 mm; 200.BDD ch4: 26 gates,
  42.97 → 54.39 mm), so a tenth of the gates is only 2–5 — a fixed ±5 and
  `±(n // 10)` are both defensible, but the number belongs in the button label
  either way.
- **Format the cursor state text more cleanly, showing min, max AND current for
  both cursors.** Today the information is split awkwardly: the time slider's
  label carries the range only (`t 0.000 → 44.211 s`, no current), while the
  readout crams everything into one dense line
  (`t = 22.2891 s (profile 200/399) · gate 27 = 49.57 mm · value 52.27`).
  Wanted: a compact per-cursor line — range first, then current — that reads well
  side by side, e.g. `time  0.000 – 44.211 s   now 22.289 s (200/399)` and
  `gate  20.00 – 79.13 mm   now 49.57 mm (27/54)`, with the sampled value kept
  separate and the 4-decimal readouts trimmed to one consistent precision.

**Open**

- Cursor **reactivity is observed** (2026-09-12): switching the recording to an
  echo file re-derived the channel dropdown and rebuilt the time slider for the
  new profile count, and a cursor change re-runs its dependents — once the step
  buttons landed, every click moved the cursor and the readout followed with no
  manual run (`200 → 201 → 241 → 240`). Still unverified: the *rendered*
  crosshair following a cursor — the plotly output payload truncates before
  `layout.shapes`, so it is only export-verified, not session-verified — the
  per-recording cursor memory as an actual *return* visit to a file, and sidebar
  stickiness.
- Heatmap click-to-set (`mo.ui.plotly` selection events → set both cursors) is
  the nicer interaction if 0.24.x supports it; the crosshair rebuild on every
  step was accepted for now.
- `channel_preview.py` still carries `TraceScrubber`, so the two notebooks are
  no longer cell-for-cell identical (as `AGENTS.md` previously asserted):
  decide whether to port the cursor cascade back or keep the sidebar file as
  the deliberately divergent sandbox.

**Design constraints** (still binding)

- The time-slice profile answers the case the old notebook warns about: the
  echo is a travelling wave whose peak sweeps across gates, so a *time-averaged*
  gate profile mixes phases, while a single time slice is phase-coherent.
- **`mo.sidebar(...)` renders only as a cell's final expression.** A mid-cell
  call — e.g. a readout placed beside the figure it annotates — is dropped
  silently (no error, no warning), and two calls in one cell keep only the last.
  A sidebar readout therefore needs its own cell, ordered after its dependencies
  so it stacks in the right place.
- Widget values cannot be **assigned** from Python — `UIElement.value`'s setter
  raises, and its message directs you to `mo.state()`. That is not a dead end: a
  shared `mo.state` plus a re-created `value=` gives full programmatic control
  (see the step-button note above), and a kernel-initiated `set_ui_value` can
  move a widget as well.
- A control is created and displayed in one cell and its `.value` is never read
  there; extra `mo.sidebar` calls stack in cell order; `full_width=True` avoids
  a clipped value; the sidebar is hidden below the `lg` breakpoint.
- Time-index cardinality varies by an order of magnitude between fixtures, so
  the heatmap stays strided for display.

---

## Active work — DOP3010 acquisition: stabilize before extending

> **Outstanding — next on this workstream (2026-09-21). The nine-job pass has run and is complete:** 26
> points across nine jobs, all stored, under the frozen plan in `examples/sparse-mixer-first-pass/` and
> [PR #25](https://github.com/ajegorovs/udv-echo-process/pull/25) (draft, `feat/acquire-sparse-run-plan`).
> Its review's five changes are all landed (the pass raises `emissions_per_profile` to a refusal, the
> block cap is a declared retention requirement, the trial's gates come from the stored files, and the
> `scientific → reference → … → scientific` sequence has its own test). The pass's own record is
> committed: [`../data/sparse-mixer-first-pass/`](../data/sparse-mixer-first-pass/README.md) carries the
> 26 `.BDD` recordings, the nine job logs, the nine job manifests, the pass manifest and the verdict with
> its reproduction commands.
>
> **Two findings came out of the run.** First, `emissions-128` was logged `invalid: 0/4` and **the guard
> was wrong, not the files**: the size signature modelled bytes as `1.7 × gates × profiles` (the payload
> alone) while a `.BDD` is `31,268 + (19 + 2 × gates) + profiles × (19 + gates)` — container, one depth
> block, one signal block per profile. That equation reproduces **all 26 recordings byte-for-byte**; the
> four refused files are structurally exact at 144 profiles (`41,323 B`), carry emissions 128 in their own
> `word 14`, span 12.4651 s and end their block chain at EOF. `acquire/log.py` now models that structure
> and the regression reads every committed recording back. Second, and **measured but deliberately not
> landed on `feat/acquire-sparse-run-plan`: the profile period is `emissions × PRF + 10.369 ms` —
> 151.689 / 223.688 / 487.690 / 871.685 ticks (0.1 ms each) at emissions 8 / 20 / 64 / 128 — against the
> retired `emissions × PRF + 1 ms` form, which was ~1.6× high on profiles at emissions 20 and worse as
> emissions rose. The intercept's two terms are separate: the manual's `T_prf × (16 + N_PRF)` is 9.6 ms at
> 600 µs and the transfer term is the remaining ~0.77 ms. `acquire/plan.py::profile_period_s` computes the
> whole law for both the runner's size expectation and the campaign's profile count, so it moves every
> `--sheet` estimate; **the sparse parameter set itself is untouched**, so no plan re-freeze follows. The
> guard's own margin moved with it and is now safe: the emissions-8 ratio goes from 0.508 (1.6 % inside its
> lower band, the level the review named as a false-rejection risk) to 1.037.
>
> **The rig was not producing signal for that pass, and the operator has since run the same design live.**
> Every stored profile in the first pass's 26 recordings is zero; the historical reference is not
> (`4MHz/0500RPM/001/res/1-8.BDD`: 25,594 of 25,850 samples non-zero). The zero payload is written down in
> the data README so a later reader does not mistake it for a file defect.
>
> **The mixer-enabled realization ran 2026-09-21 (nine jobs, 26 points, 16 min 43 s)** under a derived copy
> of the same frozen plan (own name, own root `sparse2`, own run record), so nothing in the first pass was
> overwritten: `examples/sparse-mixer-live-1/` and [`../data/sparse-mixer-live-1/`](../data/sparse-mixer-live-1/README.md).
> Every point stored and verified; **zero-payload recordings: 0** (non-zero fraction 0.9864–0.9939 per
> recording); spans 12.4686–12.5888 s; word 14 matches each point's own request; the structural size law is
> exact on 26/26 and the regression now reads both passes back. The measured period law is confirmed at all
> four emission levels on a live rig (15.2 / 22.4 / 48.8 / 87.2 ms), and the emissions-8 size-guard ratio
> that sat at 0.508 (1.6 % inside its lower edge, the level a review flagged as a false-rejection risk)
> verified as the guard's own arithmetic, not the files: it is 1.037 once the period law is corrected.
>
> **The review of the whole delta is in and it accepts it** (2026-09-21, `b9043db..9d6706c`): the
> mixer-enabled 26-point rerun, the separate run identity, the corrected profile-period model, the
> closed E8 and E128 guard findings, and the unchanged scientific design. **The acquisition phase for
> the first sparse pass is complete, and acquisition logic stops changing here** — it re-opens only if
> the analysis exposes a real problem, never because an abstraction looks improvable.
>
> **What a fresh session does next: the scientific analysis, and nothing else.** It reads committed files
> and needs no instrument, so it is unblocked the moment a session starts. **WP0 of it has landed**
> (`analysis/sparse-pass-ingest`): the ingest table and its gate —
> [`reports/sparse-mixer-live-1/points.csv`](../reports/sparse-mixer-live-1/points.csv) (26 rows: identity,
> order, condition, requested and stored window, decoded settings, the achieved period from the stored
> timestamps, retention, signal statistics on the common window and support, and the provenance of both
> sides) plus `qc-summary.json`, produced by `python -m udv_echo_process.cli sparse-inventory` and pinned by
> 23 tests to the pass's own record, the plan, and the two provenance rules. Two measured facts it hands the
> later work packages: the three windows are co-located on one physical interval (10.138–98.938 mm at three
> pitches, the 1.85 mm window's last gate outside the cut), and the planner's transfer term measures
> ~0.77 ms here — the law sits 0.21–0.22 ms above the achieved period at every emission level, in one
> direction. **WP1 and WP2 have landed beside it** (cleared in parallel by the review of WP0, which is
> frozen): [`reports/sparse-mixer-live-1/anchor-floor.md`](../reports/sparse-mixer-live-1/anchor-floor.md)
> gives each scientific job's own anchor floor — drift (`M - B`, `E - M`, `E - B`) and spread (`max - min`
> over the three) kept apart, with the scientific rows bracketed in acquisition order — and
> [`reference-floor.md`](../reports/sparse-mixer-live-1/reference-floor.md) gives CR1–CR4 as four runs in
> campaign order with their six pairwise depth-resolved differences and both floor endpoints. **The floors,
> measured:** the burst jobs' anchors move 9.646 and 11.980 mm/s (burst-18's *turns*, so its range is not
> its drift), the emissions jobs' 1.521 / 2.829 / 3.304, and the between-run reference floor is 4.235 mm/s
> depth-averaged (14.603 mm/s per depth at 21.238 mm). Two consequences bind what follows: a burst contrast
> under ~10 mm/s cannot be separated from its own controls, and the between-run floor is not ordered by
> elapsed time (the two runs 5.3 minutes apart differ most), so it is not a rate. **WP3 and WP4 have now
> landed too**: `reports/sparse-mixer-live-1/pitch-burst.md` (the 2x2 on 31 common knots no finer than
> 2.960 mm, `I(z) = -7.922 mm/s` depth-averaged, 9/31 knots over the depth-resolved endpoint and 10/31 over
> burst-18's own anchor spread, so no depth-averaged pitch x burst effect is separable) and
> `reports/sparse-mixer-live-1/emissions-ladder.md` (achieved periods 15.200 / 22.400 / 48.800 / 87.200 ms,
> Nyquist 32.895 / 22.321 / 10.246 / 5.734 Hz, 2 s physical-duration blocks of 132 / 89 / 41 / 23 profiles,
> and the e128 observation measured at 1.007x / 1.421x its own job's anchor spread). **Next: WP5, the
> Stage-2 decision table, which consumes all four measured floors and is the only thing that may justify a
> second acquisition.** **WP5 has now landed too**:
> [`reports/sparse-mixer-live-1/decision-table.md`](../reports/sparse-mixer-live-1/decision-table.md)
> reads the four frozen slices rather than recomputing anything and carries the seven outstanding
> questions with their evidence, floor, observed effect, interpretation, verdict and overturning
> measurement — the pitch x burst interaction `defer` (not resolvable with this design and not
> evidence of absence), E8 against E20 `keep`, E64 against E20 `defer`, E128 against E64 `replace`,
> the PRF `keep`, a dense second pass refused, and D1 `requires diagnostic` outside the Stage-2
> scope. Its one recommendation is the smallest set that can settle that last distinction: **eight
> run-level jobs sampling both levels alternately in one campaign** (`E20-A E64-A ... E64-D`), with
> emissions per profile the only setting that differs and the decisive comparison screened against a
> between-run floor measured **inside that campaign**. An emissions-64-only top-up was rejected in
> review and by the analysis itself: new emissions-64 runs compared against this pass's emissions-20
> runs would be separated by a campaign as well as by an emission level, which is the nuisance
> variation WP2 exists to warn about. It refuses a broad sweep on the pass's own evidence. **Next: the review's freeze, then whatever Stage-2 campaign that decision
> justifies — and nothing else.** The work order and the acceptance gates are in
> [`dop3000/sparse-pass-analysis-plan.md`](dop3000/sparse-pass-analysis-plan.md); the review's own sequence
> is its steps 3–7. Two facts about the dataset the ingest already enforces: the period comes from the
> **stored timestamps** (the logs' `timing.target_s` records the retired expectation — provenance, checked
> as such, never to be rewritten), and the two plans are pinned equivalent by a test, so the repeat cannot
> silently become another experiment. The live-dependent suites stay the first preflight at any sitting that
> touches the instrument (`uv run --extra dev pytest -q tests/test_acquire_live.py tests/test_acquire_dialog.py`):
> any failure that is not an understood live-state prerequisite stops the sitting before a recording is spent.

>
> Everything else in this workstream is closed: the identity change and its device ladder
> ([#17](https://github.com/ajegorovs/udv-echo-process/pull/17)) passed, the panel-identity work is merged, and
> sittings A–D verified **V1–V8** on the instrument, so nothing below is device-pending.

An independent repository-wide review of the acquisition subsystem was assessed
against the checkout on 2026-09-18: **all eight findings verified, the direction
accepted, the refactor roadmap accepted only in part**. Decision record, review
text and evidence lines:
[`dop3000/acquisition-review-and-verdict.md`](dop3000/acquisition-review-and-verdict.md).

**The first slice is merged:**
[PR #2](https://github.com/ajegorovs/udv-echo-process/pull/2) (`262b6ea`, 16 commits,
`29278c8`..`28ad7f9`) — the correctness baseline below, plus the `_fsync_dir` fix, which
the baseline needed for its own gate to mean anything. Two review rounds on it are
recorded in that PR's body and in
[`dop3000/acquisition-review-and-verdict.md`](dop3000/acquisition-review-and-verdict.md)
§7a–§7b.

**The next slice is planned, and its first implementation slice is in review:**
[PR #3](https://github.com/ajegorovs/udv-echo-process/pull/3) (draft) carries
[`dop3000/acquisition-campaign-compilation-plan.md`](dop3000/acquisition-campaign-compilation-plan.md)
— read the instrument's state, compile the campaign against it, and refuse before the
first recording when the two disagree; plus the cap-provenance and period-law items the
review of the first slice carried forward. It has been reviewed once: the direction was
approved and the four document-level changes it asked for are in (§10 of the plan lists them
with their commits, and the six decisions in §5 are still open).
[PR #4](https://github.com/ajegorovs/udv-echo-process/pull/4) (draft, based on #3's branch)
is the plan's **slice P1 = W2**: `acquire/snapshot.py` — an instrument reading whose every fact
carries its source, and the identity a resume compares — the additive
`SweepActuator.instrument_snapshot(*, routed_channel)`, and the fakes' answer. It changes no
recording path, so nothing in a campaign behaves differently yet; the plan's §12 records what the
slice decided.
Its first review approved the direction and returned three changes to the identity and the
channel's provenance — provenance without the diagnostic prose, the buffer-dependent button count
out of the identity, and routing as its own source that only the router can claim — all landed,
one commit each, and §12 of the plan carries them.
[PR #5](https://github.com/ajegorovs/udv-echo-process/pull/5) (draft, based on #4's branch) is
**slice P3 = W3**: `compile_campaign(definition, snapshot)` — reconcile the definition against the
reading, or refuse before the first recording, with a per-fact `refuse`/`warn`/`accept` policy
derived from the stored-file verifier's own table. It is the step the review of #3 asked for by
name, and it also changes no recording path; the plan's §13 records what it decided.

**Slice P2 = W1 (the live reconnaissance) is landed** on `feat/acquire-w1-recon` (stacked on #4's
head): the sound speed, the first gate and the burst length now have a supported read path, verified
against the running application — five of the six fixed facts are read from the instrument, and the
block cap stays `unreadable` with its reason because the surface that holds it cannot be opened
safely (the popup's second entry selects the assisted mode). The plan's §14 records the measurement,
the three checks that stand between a positional binding and a value, and two facts about the
application that any future gesture has to respect: **Escape closes nothing**, and a hover-opened
popup cannot be dismissed programmatically, so a failed gesture can strand the application until it
is restarted.

**All three slices are merged into the plan branch** (#4, #5, #6), and the review of the
batch is answered: two corrections landed — `686d4f4` (the cap and the first gate refuse for
their own reasons, not because the planner refuses those windows) and `0ba86ec` (the
choice-over-read-out invariant, with the guard that shows it bites) — and the one policy
change the review asked for is W4's: a campaign must refuse when a fact with a *supported*
read path could not be read, keeping "supported but this attempt failed" distinct from
"genuinely unsupported" (the cap stays unproven).

**P4 = W4 is implemented** on `feat/acquire-w4-integration` (cut from that merged tip), in four
commits — `00ff9c9` (the decisions: §9.1's stop condition, §9.2's read-path table, §9.3's recovery
rule), `a356d68` (a fact with a supported reader that did not read refuses), `b2743f4` (§4's order in
`run_campaign`, the resume identity proof, the manifest's three new fields), `accc682` (`acquire
compile` and the two flags). §15 records what each settled, and discloses the two behaviour changes
on purpose: a compiled run opens the channel dialog twice (step 3, then the runner's own idempotent
guard) and `plan_campaign` runs twice (pure, and it keeps step 2 gesture-free). Two things are **not**
finished: the live rehearsal still needs the operator — the first attempt stopped at the driver's own
foreground guard *before* any hover (nothing opened, nothing stranded), so UDOP has to be in front
and `acquire compile` re-run — and §14's own obligation, comparing the dialog's channel field against
the routed channel, stays open until that field survives into `InstrumentSnapshot` — it cannot fire in the planned experiment, which runs one channel with the dialog on that channel.

**The review's milestone is met, live (plan §15.1).** `acquire compile` accepted the machine's own configuration (five facts read and agreeing, the cap declared-not-verified, nothing written); a deliberately wrong declaration *and* a deliberately wrong instrument each refused with exit 2, the fact named with both sides, nothing stored; the existing six-point campaign ran unchanged — 6/6 ok, six `.BDD` files, a manifest carrying the compiled identity — and `--resume` skipped 6/6 only after proving that identity. Per §9.1 the acquisition architecture **stops growing here**: the next work is the parameter-sensitivity experiment, and re-opening the architecture needs evidence (a real campaign failed, ambiguous evidence, or a downstream analysis that cannot establish an essential condition).

**PR #7's review came back with one change request and one defect the live run exposed** (both planned in
§16). The request: compare the dialog's own channel field against the routed channel before attributing its
three facts to that channel's snapshot — the wrong-channel trap in the one place the system cannot see it,
cheap to close, so it closes before W4 is called complete. The defect: a driver refusal (`AcquisitionError`
is not a `ValueError`) reaches the operator as a **traceback** with exit 1 rather than one
`udv-acquire: <message>` line — measured live, the first `acquire compile` refusing on a non-foreground
application. Everything else in the review was approval: the read policy, the resume split, the two
duplicate calls as preflight redundancy rather than recipe drift, and the assessment that #7 is a closure
PR rather than an expansion. §16.4 is the experiment that follows — a scientific plan needing the
operator's input, with the W6 predicted-timing caveat flagged as experimentally relevant.


**Next work is planned, ordered, and pinned to a revision:**
[`dop3000/acquisition-closeout-plan.md`](dop3000/acquisition-closeout-plan.md) (2026-09-19). It landed the
open stack — `#9`, then `#8` (whose two live findings are fixed **only** on the refactor branch, so they go
to `#8` as a disclosure comment naming the fixing commits), then `#10` retargeted onto `master` — and runs
the refactor's remaining device items as **four sittings**: the read-only V2 bracket on the final head, then
V4's four-button role map (the row already refuses, so the sitting converts a refusal into a map), then the
refusal paths (V3's overlay, V1's sidebar preference, V5's declaration-only mismatch), then the writes (V2's
`ensure_channel`, V6's six-point campaign on the instrument, V7/V8). It also puts the one question only the
operator can answer — is `experiment_data\mixer\sensitivity-analysis\4MHz\0500RPM\001\burst_len` the
experiment? — in front of every later decision. It adds no architecture (§9.1 binds) and carries no
checklist ([`dop3000/device-verification.md`](dop3000/device-verification.md) owns the items and their pass
criteria).

**Status, 2026-09-19.** The stack is **merged** — `#9` `b2f74ea`, `#8` `e8fe2ac`, `#10` `5f74b8f`, `#11`
`5a36b40`; `master` is at `5a36b40`, cloud-green (`1843 passed, 22 skipped`, ruff clean) — and **sitting A
passed** on that merge head: the V2 bracket ran with UDOP in front (`is_foreground: true`, the precondition
the failed attempt lacked), its two status readings are identical field for field except the `cursor` field
the gesture itself moved, the dialog resolved live at the measured rect with its own channel and the three
dialog-only fields `source: read`, no error key names anything and no popup was stranded. The `89` rule the
index could not settle is now **confirmed on the pixels** — the four dialog edits read `89` while their
combos paint `1.776` / `4` / `medium` / `Medium` (crop `UI-OVERLAY-24`). The cursor-info-box item is
**sharpened, not closed**: the monitor side carries no text-bearing control, but the box was not up and it
need not descend from `TMain_Scr`, so it wants a top-level window enumeration with the box up — that joins
sitting B. V5's cap is untouched. V4's four-button role map, the refusal paths, and the write path
(`ensure_channel`, V6) remain device-pending.

**The strip's state tree is closed, same day.** Six states, every one read in one process and every
transition pressed by the operator: `ready` / `store` / intermediate / block-held / block-held-after-a-removal,
and back to `ready`. Two destructive exits (`Remove current block`, `Clear all`) share **one** reused guard
panel whose two messages differ only on the pixels, neither is identified by the dialog predicate, and the
strip resolver names the guard as the strip in both cases. `Clear all` returns the screen to the reference
reading (44 controls in 4 panels, no refusal), with the profile counter back to 0 — so the counter is the
buffer's extent. Full record: `device-verification.md`, *2026-09-19 — the four-button strip, block-held*.

**Sitting B, same day.** The operator reached the block-held state by hand and the map is taken, on the same
process as sitting A: the grown row is four visible buttons (`Resume` / `Do store` / `Clear and restart` /
`Remove current block`) **whose slot 1 is two different controls** — the `ready` state's second button is
merely hidden — while slot 0 genuinely relabels; the row does carry a slider (`TSp_Sliding_Bar`, two handles,
`1513` … `8297`) and a `Show block` combo reading `2`; the two caption-less buttons below it are the
`Profiles history in second / profile` selector. Two refusals on the state are **safe but misdiagnosed**: the
strip resolver named *the cursor info box* as the strip, and the layout classifier reported **"a dialog is
up"** naming the strip's own grown panel — so the `>400 px` predicate admits the strip itself when a block is
held. The cursor info box is in the tree but its `Depth` / `Velocity` numbers are **paint only**, which closes
sitting A's third item. The intermediate state was read too (11:55, same process): four buttons —
`Pause` / `Record` / `Do store` / `Clear and restart` — painting nothing below the row, with `Show block`
= `1`; and the row turns out to be drawn from a **pool of five button controls** of which two (`Pause`/`Resume`, and `Clear and restart`/`Clear all`) relabel, the rest being visibility — and all four combinations are now **read**,
with the pool model having predicted the last one (UI-STRIP-04, the strip's `store` view) exactly
before it was reached.

Binding outcomes:

- **The acquisition stop condition** (from the review of the batch, now recorded in the plan's
  §9.1 and binding): once a campaign routes the target channel, snapshots the fixed settings, and
  refuses a deliberate mismatch *before* recording — and the existing six-point campaign still runs
  **unchanged** through the compiled path — the acquisition architecture **stops growing** and the
  work moves to a real parameter-sensitivity experiment. After that it re-opens only on evidence (a
  real campaign failed, produced ambiguous evidence, or a downstream analysis cannot establish an
  essential acquisition condition), never because another abstraction looks improvable. The one
  policy change the review asked for while getting there is §9.2: a fact with a *supported* read
  path that failed to read **refuses** a normal campaign, keeping "supported but this attempt
  failed" distinct from "genuinely unsupported" (the block cap stays unproven). §9.3 records what
  recovery is allowed from a stranded popup: operator restart while commissioning, abort plus
  "state unverified" for an unattended campaign — no automatic recovery, no speculative press.
- **First slice — acquisition correctness baseline** (no Win32 reorganization):
  the channel now reaches `verify_stored_point` (it verified channel 1 while the
  decode read the run's channel) with a channel-2 regression case; verification is
  fail-closed, so a point nobody checked is refused instead of passing on its size;
  the settled covariates (words 19/5/8) are enforced while word 14 stays
  recorded-but-unenforced; and `ProfileTiming` plus the retained window (profile
  count, span, the effective interval, the at-cap/wrap distinction, retained
  fraction) are derived from the stored profile
  timestamps rather than from the request. The preflight fingerprint in the run
  record is **not** in this slice — it needs an `Actuator` protocol extension and
  belongs with campaign compilation.
- **Also open, independent of the review:** `storage/npy.py::_fsync_dir` opens a
  directory with `os.open`, which raises `PermissionError` on Windows for any
  directory — `store_bundle` cannot complete on this platform, and ~35
  `test_storage_npy.py` failures are that defect, not environment noise. A
  Linux CI would mask it. **Fixed on `master`** (`ec957e1`, merged in `262b6ea`).
- **Deferred behind a trigger:** splitting `acquire/driver.py` (149 kB of
  live-proven gestures — split only when a change forces the file open, and
  mechanically); the explicit UDOP state machine in code; replacing rather than
  wrapping the `Actuator` surface.
- **Carried into Phase 6 by the review of the first slice:** `block_cap_profiles` is a
  declared setting rather than a verified instrument fact, so `block_wrapped` is an
  inference under a declared cap — read or verify the cap from live state (and consider
  the `block_at_declared_cap` / `block_wrapped` split) when campaigns compile against a
  snapshot. Acquisition must **not** adopt the RPM path's `uniform_rtol`: acquisition QC
  and estimator eligibility are different questions.
- **Rules that constrain the work:** the decoded-metadata gate in
  [UDV product backlog](#visualization-and-acquisition-support) (evidence,
  destination field, propagation, storage implications — word 14/27 decoding is
  already gated there), and the verbatim-port rule for `acquire/` and
  `tools/live/` (move a proven gesture, never re-derive it).

---

## UDV product backlog

### Pre-processing and filtering

- Total-variation filtering port, when a UDV use case requires it.
- Peak detection port for echo analysis.
- Velocity aliasing removal / unwrapping, with fixture-backed validation before
  any destructive correction.
- Quantile-regression de-trending / baseline estimation if an experiment needs
  it.

### Analysis

- **Multi-channel / burst-sampled echo RPM.** The single-channel artifact-model
  port **landed 2026-09-15** (`rpm_from_channel`, `run_artifact_rpm_sweep`; the
  contract is `docs/architecture.md` §"Echo RPM: two entry points, one kernel").
  What remains open needs decoded visit/burst boundaries, an irregular-sampling
  or visit-aware estimator, and a fixture with independently known RPM ground
  truth; the four-channel `data/echo-4-sensors-2x2/` recording is a **refusal**
  fixture, so do not compact it onto the median intra-burst interval to make it
  produce a plausible number, and do not compare it against the uniform-cadence
  FFT method.
- Velocity RPM / spectral-peak analysis on velocity fixtures.
- Rotating-machinery analysis: unwrapped velocity, per-gate Doppler power, and
  blade-pass harmonics.

### Visualization and acquisition support

- Velocity-field/time-depth contour visualizations beyond the current heatmap.
- Additional decoded BDD metadata only when byte-level evidence, a destination
  domain field, propagation rules, and storage implications are all specified.
- **Sweep-automation rules are verified on the instrument**
  ([`dop3000/udop-automation.md`](dop3000/udop-automation.md)). Actionable here,
  under the decoded-metadata gate above: decode `Emissions per profile` (word 14)
  and `Sampling volume` (word 27), settle `skip profile` (word 84), and log the
  achieved profile period per point, so a stored `.BDD` identifies its sweep
  point on its own.
- `.ADD` migration or redesign only when a dependency proves it necessary; the
  parser/viz path remains intentionally separate. The 2026-09-15 echo-RPM port
  respected that boundary: the artifact entry point reads `.BDD` through the
  artifact model directly and no `.ADD` → bundle adapter was added.

---

## Marimo consumer follow-ups

- Re-check the consumer pin when a provider release carries a fix relevant to
  this project; use the documented `marimo` extra and execute both notebooks.
- Decide whether a repeatable consumer-side provider verification harness is
  warranted before adding one to this repository.
- Keep unreleased `marimo-inspect` development in its sibling repository; do
  not turn a temporary editable override into normal consumer setup.

- Provider-side findings from driving a live notebook through MCP (2026-09-12)
  live in the provider's own agenda, not here — `marimo-inspect` →
  `docs/agenda-udv-consumer-findings.md` §Round 2 (**T15–T22**): no run-all
  execution, session-identity churn, app-mode invisibility, the recipe gotcha
  that decides which session a browser lands on, plus three *reporting* gaps —
  a button click `set_ui_value` cannot confirm (T20), a cell output restored from
  cache with no staleness marker (T21), and a session whose owner is not named
  (T22). Two of them bit here directly: **T21** caused the duplicate sidebar
  slider (an `edit_cell` that removed a `mo.sidebar(...)` call left the previous
  block still rendered), and **T22** forced a manual "take over" in the browser
  once a session had been materialized agent-side. The **sidebar blind spot
  (T16) no longer reproduces** — `get_cell_outputs` returned the composed sidebar
  cell's whole block — so it is marked revised upstream and is no longer a
  blocker for verifying the sidebar here.

---

## Deferred boundaries

- Optical/camera processing belongs in `python-image-processing-notebooks`.
- Geometry/spatial interpolation needs an experiment-specific need and evidence;
  do not create a generic framework in advance.
- Remote notebook/MCP hosting and provider implementation work belong outside
  this repository.
- Do not infer BDD acquisition topology from channel count; use `UNKNOWN` where
  the bytes cannot prove it.

---

## Maintenance

- Before committing public docs/configuration, run the privacy scan required by
  `AGENTS.md`.
- Keep source-domain models as Pydantic models; do not introduce a mutable
  compatibility model.
- Update this file only for active work, current decisions, or a new acceptance
  blocker. Fold resolved detail into its authority document and
  `agenda-history.md`.
