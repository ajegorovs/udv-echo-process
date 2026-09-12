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

**Next pass — step buttons.** ±1 plus coarse (±1 %/±10 %) jumps per cursor,
mirroring the removed `TraceScrubber` button set. **Unblocked 2026-09-12.** The
"read-only widget" note was right about the *assignment rule* and wrong about the
achievable result, so no custom anywidget is needed. A paired block — buttons and
slider over one shared `mo.state`, the slider created as `value=get_state()` — is
a single usable value, and the frontend slider *follows* the buttons. Verified
three ways on a throwaway probe notebook: a real
browser click moved `state=2 → 3` **and** the rendered slider's displayed value
`2 → 3`; an MCP `set_ui_value` on the slider moved the state `2 → 7`; and
`set_ui_value` on a button fired its `on_click` (`state 7 → 8`), so buttons are
drivable from MCP with no browser at all. Coarse jumps are still mandatory — the
time axis is 400 profiles in one fixture and 4193–4927 in another.

**Open**

- Cursor **reactivity is now observed** (2026-09-12): switching the recording to
  an echo file re-derived the channel dropdown and rebuilt the time slider for
  the new profile count, and a cursor change re-ran its dependents (the readout
  follows). Still unverified: the *rendered* crosshair following a cursor — the
  plotly output payload truncates before `layout.shapes`, so it is only
  export-verified, not session-verified — the per-recording cursor memory (needs
  a *return* visit to the file), and sidebar stickiness.
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

## UDV product backlog

### Pre-processing and filtering

- Total-variation filtering port, when a UDV use case requires it.
- Peak detection port for echo analysis.
- Velocity aliasing removal / unwrapping, with fixture-backed validation before
  any destructive correction.
- Quantile-regression de-trending / baseline estimation if an experiment needs
  it.

### Analysis

- Multi-channel echo RPM: per-channel estimates plus cross-channel agreement.
- Velocity RPM / spectral-peak analysis on velocity fixtures.
- Rotating-machinery analysis: unwrapped velocity, per-gate Doppler power, and
  blade-pass harmonics.

### Visualization and acquisition support

- Velocity-field/time-depth contour visualizations beyond the current heatmap.
- Additional decoded BDD metadata only when byte-level evidence, a destination
  domain field, propagation rules, and storage implications are all specified.
- `.ADD` migration or redesign only when a dependency proves it necessary; the
  current parser/viz/RPM path remains intentionally separate.

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
  `docs/agenda-udv-consumer-findings.md` §Round 2 (T15–T19): no run-all
  execution, session-identity churn, app-mode invisibility, and the recipe
  gotcha that decides which session a browser lands on. The one item that bears
  on this repo directly is the **sidebar blind spot** (T16): a `mo.sidebar(...)`
  cell reports no output, so the sidebar notebook's central mechanism cannot be
  verified through the MCP surface at all.

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
