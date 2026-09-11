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
profiles, and the private 2-D TV-L1 preprocessing used only by that terminal
analysis chain. See [`udv-analysis-absorption-plan.md`](udv-analysis-absorption-plan.md).

Remaining implementation work is the small terminal-result JSON/CSV/NPZ export
boundary. Retirement itself remains blocked on honest evidence rather than code:

- **Predecessor provenance** (§8.2): neither source nor Git history identifies
  which earlier Mathematica/Python workflow produced the accepted results. The
  local `QuantileRegression.m`/echo notebook is only an unconfirmed candidate.
- **External dependency check** (§8.3): confirm no CI, notebook, or downstream
  consumer outside these two repositories still depends on `udv-analysis`.
- There is no real multi-state velocity fixture; multi-transition equivalence is
  therefore proven against the retiring implementation on synthetic topology,
  while all archived real runs are steady single-state cases.

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
