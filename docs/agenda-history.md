# Agenda history — udv-echo-process

This is a compact historical index for the former session diary in
[`agenda.md`](agenda.md). The live agenda now contains only actionable work,
current decisions, and the latest status. Detailed evidence remains in the
specialist documents linked below; the verbatim pre-consolidation entries remain
recoverable from Git history.

## How to use this archive

- Read the **live** [`agenda.md`](agenda.md) before selecting work.
- Read the linked design/implementation document before acting on a historical
  item; historical names and APIs are not current contracts.
- Treat historical test counts, pins, environment workarounds, and commit IDs as
  evidence from that session—not current state.

## Timeline index

| Period | What landed or changed | Durable source of truth |
|---|---|---|
| 2026-09-07 | Initial hardening: parser magic checks, plot figure-return mode, ruff, optical-tool retirement, first `.ADD` notebook. | `docs/hardening-plan.md`, `AGENTS.md`, parser/viz/tests |
| 2026-09-07 | Initial marimo consumer setup and live-notebook evidence. | `docs/marimo-integration-plan.md`, `docs/marimo-integration-log.md` |
| 2026-09-08 | Early BDD reader/model and pipeline-architecture discussions. The `ChannelSeries` / `MultiplexedMeasurement` design that appears in this period was superseded. | `docs/signal-model-rework-plan.md`, `docs/pipeline-conventions.md` Revision 3 |
| 2026-09-08–09 | Signal-preview notebook, interpolation, and filter design/implementation rounds. Early bundled specs and legacy transform signatures were superseded by the landed discriminated bundle API. | `docs/interpolation-design.md`, `docs/filter-design.md`, `docs/signal-model-rework-plan.md` |
| 2026-09-10–11 | marimo-inspect consumer-onboarding, provider verification, and version-pin discussions. | `docs/marimo-integration-plan.md`, `docs/marimo-integration-log.md`, `README.md`, `AGENTS.md` |
| 2026-09-11 | Signal-model rework Phases 1–9 landed: artifact bundles, support/provenance, BDD reader migration, NPY/manifest storage, legacy retirement, and notebook migration. | `docs/signal-model-rework-plan.md`, `docs/pipeline-conventions.md`, source/tests |
| 2026-09-11 | Post-landing review found two provenance-identity acceptance blockers; synchronization terminology was clarified. | `docs/agenda.md` current status, `docs/signal-model-rework-plan.md` §15 |
| 2026-09-11 | Source-root and operation identities gained canonical replay at public construction; the full post-fix gate and independent review passed, so the signal-model rework was accepted. | `docs/signal-model-rework-plan.md` §15, `docs/pipeline-conventions.md` Revision 3, provenance tests |
| 2026-09-11 | `udv-analysis` absorption Phases 0–1 preserved a private reproducible retirement baseline, adopted calculated BDD depths and grounded metadata, and made `udv-inspect` content-aware. | `docs/udv-analysis-absorption-plan.md`, BDD/CLI tests |
| 2026-09-11 | The 93-column `.ADD` mux defect was fixed using units-driven velocity/echo groups; visualization now separates `(channel, quantity)` and echo RPM rejects mixed inputs. | parser, viz, RPM tests |

## Superseded concepts and where to find the replacement

| Historical concept | Status | Current authority |
|---|---|---|
| `ChannelSeries`, `MultiplexedMeasurement`, mutable `Model`, `shape_2d` | Removed, not adapted | `docs/pipeline-conventions.md` Revision 3; `tests/test_package_surface.py` |
| Bundled `FilterParams` / `InterpParams`, `FilterMethod` / `InterpMethod` | Removed | `process/specs.py`; `docs/signal-model-rework-plan.md` §§7–8 |
| `Recording -> Recording` examples using pre-convergence types | Historical illustration only | `ChannelBundle -> ChannelBundle`; `ArtifactBundle -> ArtifactBundle` rules in `docs/pipeline-conventions.md` |
| BDD mode inferred from channel count | Rejected | `AcquisitionMode` and byte-evidence reader rules in `AGENTS.md` and `io/dop/bdd.py` |
| Editable sibling `marimo-inspect` as normal consumer install | Development-only | `README.md` and `AGENTS.md` marimo setup guidance |

## Historical investigations retained for context

- Fixture cadence and filter/interpolation probe results were folded into the
  current implementation contracts and tests; consult `references/` and the
  relevant design document rather than reviving session conclusions.
- BDD header version/comment loss and unavailable round/visit bytes are reviewed
  limits, not untracked defects; see `AGENTS.md` and the reader documentation.
- Optical/camera work belongs to the sibling
  `python-image-processing-notebooks` repository and was intentionally removed
  here.
- The marimo provider is consumed as an external dependency. Provider feature
  work belongs in `marimo-inspect`; only consumer configuration and notebook
  evidence belong here.
