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

Binding outcomes:

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
