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

**Status: the acquisition phase is closed and the analysis phase is complete.**
The nine-job first sparse pass, the mixer-enabled 26-point rerun, the frozen
WP0–WP5 analysis slices, and the eight-job counterbalanced Stage-2 campaign have
all run and are committed. The acquisition architecture **stops growing here**;
the secondary first-run sensitivity reading is recorded beside the Stage-2 report.

**Authoritative record — read these, not this file:**

- Pass data, job logs, manifests and reproduction commands:
  [`data/sparse-mixer-first-pass/`](../data/sparse-mixer-first-pass/README.md)
  (its stored profiles are zero — the rig produced no signal, written down there so
  a later reader does not mistake it for a file defect) and
  [`data/sparse-mixer-live-1/`](../data/sparse-mixer-live-1/README.md)
  (the mixer-enabled rerun: 26 points, all stored, zero-payload recordings 0).
- The frozen analysis slices WP0–WP5 and the four measured floors:
  [`reports/sparse-mixer-live-1/README.md`](../reports/sparse-mixer-live-1/README.md),
  with the decision table itself at
  [`decision-table.md`](../reports/sparse-mixer-live-1/decision-table.md).
- The work plan and its acceptance gates:
  [`dop3000/sparse-pass-analysis-plan.md`](dop3000/sparse-pass-analysis-plan.md).
- The acquisition review, its verdict, and the refactor/closeout plans:
  [`dop3000/acquisition-review-and-verdict.md`](dop3000/acquisition-review-and-verdict.md),
  [`dop3000/acquisition-closeout-plan.md`](dop3000/acquisition-closeout-plan.md),
  [`dop3000/acquisition-campaign-compilation-plan.md`](dop3000/acquisition-campaign-compilation-plan.md).
- Sweep-automation recipes and the measured `.BDD` word map:
  [`dop3000/udop-automation.md`](dop3000/udop-automation.md),
  [`dop3000/parameter-sweep-matrix.md`](dop3000/parameter-sweep-matrix.md).

**Constraints on re-opening acquisition (still binding).** Once a campaign routes
the target channel, snapshots the fixed settings, and refuses a deliberate
mismatch *before* recording — and the existing six-point campaign still runs
**unchanged** through the compiled path — the acquisition architecture **stops
growing** and the work moves to a real parameter-sensitivity experiment. It
re-opens only on evidence (a real campaign failed, produced ambiguous evidence, or
a downstream analysis cannot establish an essential acquisition condition), never
because another abstraction looks improvable. A fact with a *supported* read path
that failed to read **refuses** a normal campaign, keeping "supported but this
attempt failed" distinct from "genuinely unsupported" (the block cap stays
unproven). Recovery from a stranded popup is operator restart while commissioning,
or abort plus "state unverified" for an unattended campaign — no automatic
recovery, no speculative press. Full statement: campaign plan §9.1–§9.3 and
[`dop3000/acquisition-closeout-plan.md`](dop3000/acquisition-closeout-plan.md).

### The one re-opening so far: burst length, as a verified transition

**Its evidence is the sparse pass's own procedure:** burst length is not a sidebar
parameter, so every job that recorded at a different burst needed an **operator
hand-change** through `Parameters → Operating parameters` — an essential
acquisition condition the campaign cannot establish on its own.

**In PR #35:** the typed contract, the Win32 transaction
(`write_dialog_burst_length`: select by value → let the application re-derive →
`Accept` → **re-open** → re-identify the dialog and read both rows back), the live verb
(`uv run udv-acquire burst-length <N>`), and the coupled fake/refusal matrix.

**B4 burst-control commissioning passed (2026-09-24):** the four
transitions verified `4 / 10 / 18 / 10`; four short BDDs store those values in word 8,
with other decoded settings unchanged. Dialog effective Sampling volume was
`1.776 / 1.850 / 3.330 / 1.850 mm`, while word 27 remained `1` throughout. At
`1480 m/s` and `4 MHz`, burst lengths `10` and `18` predict exactly `1.850` and
`3.330 mm`. The manual defines word 27 as the receiver-bandwidth definition,
not an index inferable from the effective millimetres when burst dominates. The
inactive rig's payloads were all zero; this is control-path evidence, not signal
analysis. The initial `10 / 1.850 mm` was restored. Raw files, digests, logs,
interpretation and limits: [`../data/burst-commissioning-b4/`](../data/burst-commissioning-b4/README.md).

**B5 is merged — live acceptance passed 2026-09-25 (PR #38, merge `7209609`).** Four job
boundaries of a nine-job `run-plan --next` pass — `burst-4` → `common-reference-1` →
`burst-18` → `common-reference-2` — transitioned `10 → 4 → 10 → 18 → 10` automatically, with
the effective Sampling volume read back as `1.776 / 1.850 / 3.330 / 1.850 mm`, word 27 still
`1`, and 12 stored BDDs whose word 8 matches each job. No burst was set by hand; the other five
jobs of that plan were deliberately not run (they request a manual emissions change), and the
equal-burst/no-write path is **offline-verified only** — the review accepted that boundary
because the unexercised branch performs *less* device interaction, not an unknown gesture.
Portable plan, hashes and an instrument-free verifier:
[`../data/burst-commissioning-b5/`](../data/burst-commissioning-b5/README.md).

**Mutation provenance across a refused invocation: design direction accepted, nothing implemented
(PR #40, merge `426dd5a`).** A verified boundary write followed by a compile or resume-identity
refusal writes no new job manifest, so that invocation's write is absent from
`burst_transitions` — a general acquisition transaction/audit gap rather than a word-8/word-27
question, deliberately not folded into B6. The accepted recommendation is to append the verified
transition to the **job's own log at the boundary**, under an explicit occurrence identity (never a
content key: two identical `10 → 18` mutations are two events), with a failed append **aborting the
invocation before it records**, an unknown log entry type **refusing the log**, and a pipeline-wide
journal deferred until a *second* independently owned instrument mutation enters the automated
path. Statement with `file:line` evidence, the rejected options and the trigger to revisit:
[`dop3000/failed-invocation-provenance.md`](dop3000/failed-invocation-provenance.md).

**B6 is merged (PR #39, merge `33dbb44`).** Stored word 8 becomes an
**unconditional burst oracle**: when a request declares a burst, word 8 is compared on
**every** verification call, so a mismatch invalidates the point and no
caller's covariate switch can skip it — an escape hatch removed rather than strictness newly
introduced, since at B6's base the runner already verified stored points with
`check_covariates=True`; stored word 27 is carried as the
receiver-bandwidth-definition index on the verification facts and the point record, compared
with nothing, with no millimetre derivation and never written. The 16 committed B4/B5
recordings pin it: index `1` throughout while word 8 reads `4/10/18` and the dialog's effective
Sampling volume read `1.776/1.850/3.330` mm, so the withdrawn `word 27 == the index the
displayed mm implies` criterion is refuted by the bytes. That readback stays a dependent
covariate, never inferred from word 27 and never written. **Still open:** which bandwidth
another selection stores (no committed evidence moves the field off `1`), any index-to-mm
relation (none reviewed), and a second hidden dependent effect in a live run, which still
stops the campaign. Authority:
[`dop3000/burst-length-control-plan.md`](dop3000/burst-length-control-plan.md).

**Next actions on the acquisition track (2026-09-25, reordered by an external direction review
that judged the direction sound).** SA1 (per-gate profiles, traces and recurrence diagnostics on both
committed mixer sittings) runs **first and in parallel** — the review's strongest counter-argument is
that provenance machinery must not gate the science the two datasets can already pay back; then the
provenance recommendation of PR #40 (offline); then **B7** — a miniature automated burst campaign
(`4 / 10 / 18 / 10`, recordings and restoration verified) — before **B8**, the next sparse
experimental run using it; then the five remaining jobs of the portable nine-job plan
(`emissions-8/64/128` plus two references), which need a manual emissions change at the instrument.
The order flips back to provenance-first only if SA1 finds nominally identical common-reference
records differing in a state-dependent way that the existing manifests and logs cannot trace. **In flight** (Draft, reviewed by nobody, offline-verified only): PR #44 implements the
provenance recommendation of PR #40, and PR #45 carries SA1 — the per-gate statistics, the
trace-recurrence estimator and the executed notebook preview. Durable
version, with the guardrails and the per-package verification boundary:
[`dop3000/handoff-dop3010-acquisition.md`](dop3000/handoff-dop3010-acquisition.md) §Current state.

**The Stage-2 campaign ran on 2026-09-21 and its analysis has landed.**
four counterbalanced pairs, emissions per profile the only hand-changed setting, 8/8 stored with
every job's own stored word 14 matching its declaration and every other decoded setting identical
across the eight; the artefacts are committed at
[`../data/stage2-e20-e64/`](../data/stage2-e20-e64/README.md)
([#29](https://github.com/ajegorovs/udv-echo-process/pull/29)). The paired analysis
([#30](https://github.com/ajegorovs/udv-echo-process/pull/30),
[`reports/stage2-e20-e64/`](../reports/stage2-e20-e64/README.md)) publishes the four contrasts each
oriented `E64 - E20` whatever order its pair was acquired in — A `+7.2256`, B `-1.5733`,
C `+0.3448`, D `+1.3418` mm/s — against the variation that campaign measured for itself
(**9.4044** mm/s depth-averaged, **28.5481** mm/s depth-resolved), and returns **unresolved
overlap** (*not detected*): no contrast exceeds the campaign's own variation and the directions are
not consistent, which section 4b states is itself the answer and ends the question. The earlier
pass's 4.235 / 14.603 mm/s are context only: it measured four E20 references and one E64
recording in the same campaign, but its floor describes the E20 runs alone and cannot screen
this campaign's paired contrasts. The screen is set by the campaign's first job (`e20-a`,
`+22.6053` mm/s against `+29.83 .. +32.01` for the other three emissions-20 runs); the report names
it rather than excluding it. **That workstream is now closed, one step further than this entry
first recorded:** the frozen decision table's E64-vs-E20 row
([`../reports/sparse-mixer-live-1/decision-table.md`](../reports/sparse-mixer-live-1/decision-table.md))
has been updated to this outcome in its own reviewed slice — `replace` / not detected at this
design's floors, citing the campaign's own slice as evidence, with the state it moved from
(`defer` / not resolvable with the earlier design) retained inside the row. The
explicitly **secondary** sensitivity reading omits the entire first pair, not just
its low E20 run: the remaining three contrasts stay inside their recalculated
three-run floor, so the post-hoc reading leaves the primary verdict unchanged
([`first-run-sensitivity.md`](../reports/stage2-e20-e64/first-run-sensitivity.md)).
Nothing else is open in this workstream.

**Open decision — the store path a run's records carry.** The `sparse-mixer-live-2`
sitting started with the absolute `--store-dir` that §6 of
[`dop3000/sparse-run-plan.md`](dop3000/sparse-run-plan.md) documents, so its logs,
manifests and run record carry the clone's own absolute path where the three earlier
datasets record `outputs\live\store\…`. The committed copies of that pass are
normalized to the relative form (see
[`../data/sparse-mixer-live-2/README.md`](../data/sparse-mixer-live-2/README.md)), which
is a per-sitting fix, not the rule. Decide once: either the run records the
store-relative path while the CLI keeps accepting the absolute form, or §6 documents
the relative `--store-dir` the live run should pass. Nothing depends on it before the
next sitting, and no recorded digest covers a path either way.

**The instrument side is verified; nothing in this workstream is device-pending.**
Sittings A–D on `UDOP DOP3010.43` passed **V1–V8** — the V2 bracket, the
four-button strip role map and its measured state tree, the refusal paths,
`ensure_channel`, the unchanged six-point campaign through the compiled path,
resume identity and post-run recovery. The items, their pass criteria and the full
session records are [`dop3000/device-verification.md`](dop3000/device-verification.md);
the surface/widget ledger is
[`dop3000/acquisition-ui-model.md`](dop3000/acquisition-ui-model.md) and the
committed caption crops are
[`dop3000/ui-element-index.md`](dop3000/ui-element-index.md). The identity change and
its device ladder ([#17](https://github.com/ajegorovs/udv-echo-process/pull/17))
and the panel-identity work are merged. The review/refactor chronology that
produced them — the eight-finding review of 2026-09-18 and PRs #2–#11 with slices
P1–P4 — is recorded in
[`dop3000/acquisition-review-and-verdict.md`](dop3000/acquisition-review-and-verdict.md)
and [`dop3000/acquisition-closeout-plan.md`](dop3000/acquisition-closeout-plan.md),
not here.

Binding rules that outlive that work:

- **The decoded-metadata gate** in
  [UDV product backlog](#visualization-and-acquisition-support): additional BDD
  metadata (word 14/27 decoding is already gated there) lands only when byte-level
  evidence, a destination domain field, propagation rules and storage implications
  are all specified.
- **The verbatim-port rule** for `acquire/` and `tools/live/`: move a proven
  gesture, never re-derive it.
- **Acquisition must not adopt the RPM path's `uniform_rtol`**: acquisition QC and
  estimator eligibility are different questions.

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
