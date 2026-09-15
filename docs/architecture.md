# Architecture and contributor guide

This is the current, user-facing map of `udv-echo-process`: which pipeline to
use, where new code belongs, and how to verify a change. It is deliberately an
overview; the enforceable signal-model contract is
[`signal-model-rework-plan.md`](signal-model-rework-plan.md), and module rules
are in [`pipeline-conventions.md`](pipeline-conventions.md).

> **Current status:** the signal-model implementation and post-landing
> provenance-identity hardening are accepted. The artifact pipeline's enforced
> contracts are summarized below and specified in the rework plan §15.

## Two pipelines, by design

The project intentionally supports two distinct paths. Do not introduce an
adapter that pretends they are the same model.

| Path | Input and result | Purpose | Main entry points |
|---|---|---|---|
| `.ADD` legacy path | `parser.extract()` → `ExtractedData` | Existing ASCII parsing, plots, single-channel echo RPM, and CLI workflows | `parser.py`, `viz.py`, `analysis/rpm.py` (`rpm_from_echo`), `cli.py` |
| `.BDD` artifact path | `io.load()` → `ArtifactBundle` | Content-sniffed binary reading, scientifically typed transformations, normalized provenance, durable storage, and terminal echo RPM | `io/`, `models/`, `process/`, `provenance/`, `storage/`, `analysis/rpm.py` (`rpm_from_channel`), `run_all.py` |

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
├── analysis/     terminal domain algorithms: echo RPM, operating states, robust profiles
├── export.py     terminal-result JSON/CSV/NPZ serialization (not bundle storage)
├── run_all.py    batch echo-RPM flows (`.ADD` and artifact-model) + visualizations
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
  ├── detect_operating_states(...) → OperatingStateDetection
  │      └── extract_robust_profiles(...) → RobustVelocityProfiles
  │             └── export_terminal_results(...) → JSON + CSV + NPZ
  │
  ├── rpm_from_channel(bundle, EchoRpmSettings()) → EchoRpmEstimate
  │      (terminal scalar/trace result; no derived artifact, no graph node)
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

## Echo RPM: two entry points, one kernel

Echo RPM exists on both pipelines and both call the same private FFT kernel
(`analysis/rpm.py::_echo_rpm_spectrum`), so the numerical algorithm cannot drift
between them:

| Path | Entry point | Result |
|---|---|---|
| `.ADD` / `ExtractedData` | `rpm_from_echo(extracted, dt_s=None)` | `(rpm, peak_freq_hz, n_samples)` tuple |
| artifact model | `rpm_from_channel(bundle, settings=None)` | `EchoRpmEstimate` |

`rpm_from_channel` is a **terminal** `T -> U` product like the state/profile
detectors: it adds no `SignalData` field, no `SupportKind`/`QualityFlag`, no
provenance node and no storage payload, and it never mutates the source bundle.
The five contract points that make it reproducible:

- **Spectrum.** Unnormalised `mean(|rfft(values, axis=0)|)` across depth gates —
  a magnitude spectrum, not a power/PSD estimate.
- **DC exclusion.** Bin 0 is always excluded from the peak search, so a large
  DC offset (which is the global maximum on real echo data) cannot be reported
  as a 0 RPM result. There is no raw bin-index setting: a raw index is
  recording-length-dependent.
- **Frequency calibration.** The axis is calibrated by the **full-span effective
  interval** `(t[-1] - t[0]) / (N - 1)`, i.e. the mean adjacent interval, never
  by the median. The DOP timebase is quantized: the committed echo recordings
  alternate 3.1/3.2 ms, so the median is the dominant *quantum* (3.2 ms) while
  the effective period is 3.182 ms. Calibrating on the median shifts every
  recovered RPM by ~0.6% (650 → 645.92 instead of 649.58).
- **Quasi-uniformity guard.** `rfft` assumes uniform samples, so the worst-case
  relative deviation of the adjacent intervals from their median is measured
  before the transform and compared against
  `EchoRpmSettings.uniform_rtol` (default `0.05`, hard ceiling `0.05`; the
  committed echo recordings measure 3.125%). A structurally sampled
  (burst/visit) axis is refused with `EchoRpmInputError` instead of being
  compacted onto its median cadence — the four-channel
  `data/echo-4-sensors-2x2/` fixture deviates by ~46x and is a refusal fixture.
  A caller who wants a different time basis must resample through the artifact
  process layer (``resample``) and estimate the derived bundle. Resampling is
  not a way around the guard, though: a uniform grid is asserted, not created.
  With the default long-gap policy the burst fixture still arrives with
  ``MISSING`` cells (which this terminal step refuses too), and a caller who
  forcibly bridges the inter-burst gaps only gets the acquisition structure
  back as a spectral peak — that regime needs a visit-aware estimator, not a
  resampled rFFT.
- **The `/2` factor is rig-specific.** This campaign's echo amplitude modulates
  at twice the rotor frequency (two echo features per revolution). It is not a
  universal Doppler identity, so it is fixed in the estimator contract rather
  than exposed as a setting.

The original single-channel sweep is reproduced by
`run_artifact_rpm_sweep()` in `run_all.py`: it sniffs the immediate files of an
experiment directory (content, not extension), requires exactly one recording
stream per file, derives the commanded setpoint from the filename and returns
sorted `RpmResult` rows after writing the setpoint-vs-recovered summary plot.
Multi-stream recordings raise instead of silently using stream 0. All 19
`data/echo/*.BDD` recordings reproduce their paired `.ADD` estimates to
floating-point precision and land within 2% of the filename setpoint.

**Still open:** multi-channel/burst-sampled echo RPM. It needs decoded
visit/burst boundaries, an irregular-sampling or visit-aware estimator, and a
fixture with independently known RPM ground truth — not a concatenation of
bursts at the median intra-burst interval.

## Public entry points

### Python

```python
from udv_echo_process import extract, load, plot_all, rpm_from_channel, rpm_from_echo
from udv_echo_process.models import ChannelKey
from udv_echo_process.provenance import select_channel

# Existing ASCII workflow
add_recording = extract("data/echo/650.ADD")
rpm = rpm_from_echo(add_recording)
plot_all(add_recording)

# Artifact workflow: one channel -> terminal echo-RPM estimate
bundle = load("data/echo/650.BDD")
channel = select_channel(bundle, ChannelKey(device_channel=4))
estimate = rpm_from_channel(channel)
print(estimate.rpm, estimate.peak_freq_hz)

# Batch: reproduce the single-channel sweep and its summary plot
from udv_echo_process.run_all import run_artifact_rpm_sweep

rows = run_artifact_rpm_sweep("data/echo", "outputs/summary-artifact-rpm.png")
```

`ChannelKey` is a models-layer name and `select_channel` is provenance-layer
(`load`, `rpm_from_channel`, `rpm_from_echo` and the specs are root-level); the
artifact RPM sweep is a Python entry point only — `udv-run-all` stays on the
`.ADD` path because it also writes legacy heatmaps/profiles.

The package root exports the stable convenience surface. Prefer importing model,
process, provenance, or storage details from their own subpackages when writing
new artifact-pipeline code.

### Command line

```bash
uv run udv-inspect <file.ADD-or-BDD>
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
  `.ADD` route; `test_echo_rpm.py` pins the artifact-model RPM estimator, the
  shared kernel, and the 19-recording batch sweep against its paired `.ADD`
  results.
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
