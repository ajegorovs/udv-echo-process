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

## Current status — signal-model rework acceptance pending

The Phases 1–9 implementation landed, but is **not yet accepted**. The full
review baseline passed: 774 tests, Ruff check/format check, static notebook
validation, and executed HTML exports for both notebooks. The `.ADD` and BDD
paths, storage, bundle transforms, public-surface retirement, and notebooks were
exercised.

### Acceptance blockers — do before new pipeline features

1. **Source root identity enforcement.** `source_bundle(ChannelArtifact(...))`
   currently trusts an opaque ID. Choose the narrowest validated boundary that
   recomputes `source_artifact_id(...)`, preserves the frozen five-field
   `ChannelArtifact` contract, and does not add a legacy adapter or a second
   derivation constructor. Add a direct counterfeit-ID rejection test.
2. **Operation identity enforcement.** Public `ArtifactGraph` construction
   currently accepts an `OperationRecord` whose `operation_id` does not replay
   from its canonical recipe fields. Decide whether the invariant belongs on
   `OperationRecord` or graph validation, enforce it, and add a direct
   counterfeit-operation-ID rejection test.
3. **Post-fix acceptance gate.** Run the full test suite, Ruff check/format
   check, both notebook HTML exports, BDD/store round-trip and tamper replay,
   `git diff --check`, and a fresh independent review. Only then mark the
   rework accepted in the plan and conventions.

### Settled synchronization contract

Cross-channel synchronization matches explicit `round_id`; every participating
row must have a non-duplicate `(round_id, visit_id)` identity, and a stream may
have only one visit in a matched round. A round groups cross-stream visits;
`visit_id` records within-round acquisition order. See
[`signal-model-rework-plan.md`](signal-model-rework-plan.md) §7.4.

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
