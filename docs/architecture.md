# Architecture and contributor guide

This is the current, user-facing map of `udv-echo-process`: which pipeline to
use, where new code belongs, and how to verify a change. It is deliberately an
overview; the enforceable signal-model contract is
[`signal-model-rework-plan.md`](signal-model-rework-plan.md), and module rules
are in [`pipeline-conventions.md`](pipeline-conventions.md).

> **Current status:** the signal-model implementation landed through Phase 9,
> but acceptance is pending two provenance-identity fixes. Do not mark the
> artifact pipeline complete until the unchecked items in the rework plan §15
> pass.

## Two pipelines, by design

The project intentionally supports two distinct paths. Do not introduce an
adapter that pretends they are the same model.

| Path | Input and result | Purpose | Main entry points |
|---|---|---|---|
| `.ADD` legacy path | `parser.extract()` → `ExtractedData` | Existing ASCII parsing, plots, single-channel echo RPM, and CLI workflows | `parser.py`, `viz.py`, `analysis/rpm.py`, `cli.py` |
| `.BDD` artifact path | `io.load()` → `ArtifactBundle` | Content-sniffed binary reading, scientifically typed transformations, normalized provenance, and durable storage | `io/`, `models/`, `process/`, `provenance/`, `storage/` |

The `.ADD` route remains intentionally separate and stable while the artifact
pipeline matures. The reader dispatches by magic bytes rather than filename
extension; a misnamed binary is still recognized by its content.

## Package map

```text
src/udv_echo_process/
├── models/       domain data: immutable Pydantic values and owned read-only arrays
├── provenance/   ArtifactGraph, ChannelBundle, ArtifactBundle, operation records
├── process/      bundle-closed filtering, interpolation, synchronization, derive()
├── storage/      schema-v1 NPY arrays plus JSON manifest persistence
├── io/           reader registry and DOP BDD reader
├── parser.py     independent .ADD parser returning ExtractedData
├── viz.py        independent .ADD visualization layer
├── analysis/     terminal domain algorithms, currently echo RPM
├── run_all.py    batch `.ADD` echo-RPM + visualization flow
└── cli.py        udv-inspect, udv-viz, and udv-run-all entry points
```

### Dependency boundaries

- `models/` owns the scientific nouns and must not import `process/`,
  `provenance/`, `storage/`, or reader code.
- `io/` creates source artifacts from decoded bytes; it does not infer
  acquisition topology from channel count.
- `process/` contains pure transformations, not I/O or plotting.
- `provenance/` owns the graph and the supported bridges between a recording and
  one channel.
- `storage/` persists the artifact graph and arrays; it is not another domain
  model.
- `analysis/` contains terminal `T -> U` results; it is not an intermediate
  transform layer.

## Artifact-model flow

```text
BDD bytes
  │  content sniff + decode
  ▼
io.load(path)
  │
  ▼
ArtifactBundle
  ├── Recording: source asset, acquisition mode, channel artifacts
  └── ArtifactGraph: roots, operations, and derived-artifact links
  │
  ├── select_channel(bundle, ChannelKey(...))
  ▼
ChannelBundle
  │
  ├── filter(bundle, FilterSpec)
  └── resample(bundle, InterpSpec, *, times | dt_s)
  │
  ▼
new ChannelBundle
  │  replace_channel(...) or synchronize(...)
  ▼
ArtifactBundle
  │
  └── store_bundle(...) / load_bundle(...)
```

### The contracts that matter

- `ValueModel` is frozen, validates defaults, and forbids unknown fields.
- `ArrayModel` takes an owned, C-contiguous, read-only copy at its boundary.
  Scientific transformations must never share parent arrays.
- `SignalData` carries time, gate depths, values, support, quality, and optional
  row-level acquisition identity. NaN is not the source of truth for support.
- Per-channel transforms are **`ChannelBundle -> ChannelBundle`**; recording
  transforms are **`ArtifactBundle -> ArtifactBundle`**.
- A transformation computes arrays and calls `derive()` (or `derive_many()` for
  recording-level multi-output work). It must not hand-build a derived artifact
  or use `model_copy(update=...)` for scientific data.
- `SampleSupport` distinguishes `OBSERVED`, `INTERPOLATED`, `EXTRAPOLATED`, and
  `MISSING`. Transformations must not relabel synthetic data as observed.
- The graph records operation nodes and parent links instead of copying history
  into every artifact.
- NPY storage writes arrays separately from typed JSON metadata and validates
  integrity before returning owned runtime arrays.

For exact support-propagation tables, ID equations, storage protocol, and
current acceptance blockers, read the rework plan §§6–9 and §15.

## Public entry points

### Python

```python
from udv_echo_process import extract, load, plot_all, rpm_from_echo

# Existing ASCII workflow
add_recording = extract("data/echo/650.ADD")
rpm = rpm_from_echo(add_recording)
plot_all(add_recording)

# Artifact workflow
bundle = load("data/echo/200.BDD")
```

The package root exports the stable convenience surface. Prefer importing model,
process, provenance, or storage details from their own subpackages when writing
new artifact-pipeline code.

### Command line

```bash
uv run udv-inspect <file.ADD>
uv run udv-viz [<file.ADD> ...]
uv run udv-run-all
```

These commands currently serve the `.ADD` workflow. A new CLI is appropriate
only for a stable, repeatable batch pipeline—not for one transform or an
experiment.

### Notebooks

- `notebooks/echo_explorer.py` is a thin interactive wrapper around the `.ADD`
  parser and visualization path.
- `notebooks/channel_preview.py` is a thin wrapper around the artifact API.

Library computation belongs in `src/`; notebooks should only select inputs,
construct validated specs, and display returned figures.

## Where a change belongs

| Need | Put it here | Do not put it here |
|---|---|---|
| New decoded binary fact | `io/dop/bdd.py` plus a domain field only if the evidence and propagation rule exist | An ad hoc reader-only attribute |
| New immutable scientific fact | `models/` | A notebook or transform-local dict |
| New per-channel transform | `process/` with a discriminated spec and `derive()` | `analysis/`, `viz.py`, or a notebook |
| New recording-level operation | `process/` with `derive_many()` where applicable | A loop that loses provenance |
| New terminal domain result | `analysis/` | The middle of a processing chain |
| Durable artifact persistence | `storage/` | Inline JSON arrays or pickle |
| `.ADD` display or batch behavior | `viz.py`, `run_all.py`, or `cli.py` | The artifact pipeline unless migration is explicitly planned |

## Testing and verification

Use `uv`; do not create a separate `venv` or use a `pip` workflow.

```bash
# Core quality gate
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl \
  uv run --extra dev pytest
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl \
  uv run --extra dev ruff check src tests
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl \
  uv run --extra dev ruff format --check src tests

# Notebook changes require execution, not only a static check
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl \
  uv run --extra marimo marimo check notebooks
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl \
  uv run --extra marimo marimo export html notebooks/channel_preview.py -o /tmp/channel-preview.html
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl \
  uv run --extra marimo marimo export html notebooks/echo_explorer.py -o /tmp/echo-explorer.html
```

Test modules mirror the architecture:

- `test_model_base.py`, `test_identity.py`, `test_support.py`, and
  `test_signal_data.py` pin domain boundaries.
- `test_derive.py` and `test_provenance.py` pin derivation and graph behavior.
- `test_artifact_filter.py`, `test_artifact_resample.py`, and
  `test_recording.py` pin transform/support/topology semantics.
- `test_io_bdd_artifacts.py` and `test_storage_npy.py` cover reader and storage
  contracts.
- `test_parser.py`, `test_viz.py`, and `test_analysis.py` protect the separate
  `.ADD` route.
- `test_package_surface.py` prevents removed legacy APIs from returning.

For a change that crosses these layers, test the invariant at the closest model
boundary and add an outside-in probe that does not merely repeat the
implementation's own test fixture assumptions.

## Further reading

| Question | Source |
|---|---|
| What is active right now? | [`agenda.md`](agenda.md) |
| What happened before, and which names are obsolete? | [`agenda-history.md`](agenda-history.md) |
| What exactly is the signal-model contract? | [`signal-model-rework-plan.md`](signal-model-rework-plan.md) |
| How should a new module or transform be structured? | [`pipeline-conventions.md`](pipeline-conventions.md) |
| How does BDD decoding relate to the device? | [`doppy-analysis.md`](doppy-analysis.md) and `docs/dop3000/manual-reference/` |
| How do live notebooks and MCP co-work operate? | [`marimo-integration-plan.md`](marimo-integration-plan.md) and [`marimo-integration-log.md`](marimo-integration-log.md) |
