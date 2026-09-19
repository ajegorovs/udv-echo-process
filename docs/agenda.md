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

**Sitting B, same day.** The operator reached the block-held state by hand and the map is taken, on the same
process as sitting A: the grown row is four visible buttons (`Resume` / `Do store` / `Clear and restart` /
`Remove current block`) **whose slot 1 is two different controls** — the `ready` state's second button is
merely hidden — while slot 0 genuinely relabels; the row does carry a slider (`TSp_Sliding_Bar`, two handles,
`1513` … `8297`) and a `Show block` combo reading `2`; the two caption-less buttons below it are the
`Profiles history in second / profile` selector. Two refusals on the state are **safe but misdiagnosed**: the
strip resolver named *the cursor info box* as the strip, and the layout classifier reported **"a dialog is
up"** naming the strip's own grown panel — so the `>400 px` predicate admits the strip itself when a block is
held. The cursor info box is in the tree but its `Depth` / `Velocity` numbers are **paint only**, which closes
sitting A's third item. The intermediate state (UI-STRIP-03) is photographed, not read: one more read with it
on screen finishes the map.

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
