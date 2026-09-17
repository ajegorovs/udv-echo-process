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
| 2026-09-12 | Typed terminal operating-state detection and robust velocity profiles were absorbed with private 2-D TV-L1 preprocessing and a deterministic JSON/CSV/NPZ export boundary; archived steady runs and synthetic multi-state differential oracles match the retiring package exactly. A local dependency audit found no consumers; forensics bounded the immediate predecessor as unrecoverable without inventing lineage. | `docs/udv-analysis-absorption-plan.md`, state/profile/export tests |
| 2026-09-15 | Single-channel echo RPM gained an artifact-model entry point (`rpm_from_channel(ChannelBundle) -> EchoRpmEstimate`) on the shared private FFT kernel, calibrated by the full-span effective interval after a quasi-uniformity guard instead of the timestamp-increment median, plus `run_artifact_rpm_sweep()` reproducing the 19-recording setpoint-vs-recovered summary plot; all 19 artifact estimates equal their paired `.ADD` results. Multi-channel/burst echo RPM stays open. | `docs/architecture.md` §"Echo RPM: two entry points, one kernel", `analysis/rpm.py`, `models/rpm.py`, `run_all.py`, `tests/test_echo_rpm.py` |
| 2026-09-17 | UDOP sweep automation verified end-to-end on the instrument: the posted held-click recipe drives the record strip; the sidebar and `Operating parameters` write recipes and the order they must be written in were measured; the record → stop → store chain, its overlay and overwrite-warning handling, the cap/block hazard and the profile-period constraint were recorded; two 100 mm points (805 gates @ 0.1217 mm, 403 gates @ 0.2433 mm at `c` = 1460) were validated by decoding the stored `.BDD`, which also pin the `.BDD` word map the sweep read-back depends on. | `docs/dop3000/udop-automation.md`, `docs/dop3000/parameter-sweep-matrix.md` (measured word map and write rules) |

## Superseded concepts and where to find the replacement

| Historical concept | Status | Current authority |
|---|---|---|
| `ChannelSeries`, `MultiplexedMeasurement`, mutable `Model`, `shape_2d` | Removed, not adapted | `docs/pipeline-conventions.md` Revision 3; `tests/test_package_surface.py` |
| Bundled `FilterParams` / `InterpParams`, `FilterMethod` / `InterpMethod` | Removed | `process/specs.py`; `docs/signal-model-rework-plan.md` §§7–8 |
| `Recording -> Recording` examples using pre-convergence types | Historical illustration only | `ChannelBundle -> ChannelBundle`; `ArtifactBundle -> ArtifactBundle` rules in `docs/pipeline-conventions.md` |
| BDD mode inferred from channel count | Rejected | `AcquisitionMode` and byte-evidence reader rules in `AGENTS.md` and `io/dop/bdd.py` |
| Editable sibling `marimo-inspect` as normal consumer install | Development-only | `README.md` and `AGENTS.md` marimo setup guidance |
| Echo RPM as an `.ADD`-only capability (FFT peak /2 reachable from `ExtractedData` alone) | Superseded 2026-09-15 | `rpm_from_channel` in `analysis/rpm.py`; `docs/architecture.md` §"Echo RPM: two entry points, one kernel" |
| Calibrating the echo-RPM FFT by the median timestamp increment (and the Wolfram cell's literal `3.2` ms step) | Superseded 2026-09-15 | full-span effective interval `(t[-1] - t[0]) / (N - 1)`; `references/wolfram/README.md` note |

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
