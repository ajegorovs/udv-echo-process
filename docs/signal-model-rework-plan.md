# Signal model rework — authoritative execution plan

> **Status: OPEN · authoritative for this rework.** This document is the
> execution authority for the signal-model rework and supersedes conflicting
> architecture text in older design documents for this work. In particular,
> pre-convergence `Recording`, `SensorSeries`, mutable `ChannelSeries`, bundled
> all-method parameter, and pandas-backed examples are not implementation
> instructions. Do **not** edit those older documents until Phase 9.
>
> **Executor rule:** follow the phases and stop/go gates in order. Do not fill
> semantic gaps with a convenient default. If reality contradicts a contract
> below, stop, add a focused failing test and request a decision before changing
> the contract. Do not commit or push unless the user explicitly asks. Optional
> checkpoints mentioned here are user-authorized only when the user says so.

## 1. Goal

Replace the current weakly validated, mutable-array `ChannelSeries` model with
an execution-safe scientific signal model that:

- distinguishes acquisition identity, scientific meaning, payload, support,
  quality, artifact identity and provenance;
- owns read-only NumPy arrays and validates their complete cross-field contract;
- keeps processing state closed as `ChannelBundle -> ChannelBundle` (and
  recording-level state as `ArtifactBundle -> ArtifactBundle`);
- preserves observed/interpolated/extrapolated/missing semantics through every
  transform;
- represents recording mechanism and acquisition rounds/visits explicitly;
- records normalized derivation DAGs without copying unbounded history into
  every signal; and
- persists arrays without JSON expansion using a versioned JSON manifest plus
  integrity-checked NPY files.

Tech stack: Python >=3.14, Pydantic v2, NumPy, existing SciPy/scikit-image,
pytest and ruff, all run through `uv`. Use Pydantic models; do not introduce
`dataclasses`.

## 2. Why the rework is required

The current models and transforms are useful prototypes but unsafe as a
scientific interchange boundary:

1. `models/base.py::Model` enables arbitrary ndarray fields but defines neither
   ownership nor mutability. Caller-owned arrays can change a validated model;
   `frozen=True` alone would not freeze array buffers.
2. `ChannelSeries` accepts weak dtype/finiteness/time semantics, stores gate
   depths as a mutable list, allows empty defaults, and cannot distinguish raw
   measurements from derived values.
3. Missingness is currently inferred from NaN or rejected ad hoc. There is no
   support kind, valid mask, quality reason, long-gap policy, or protection
   against re-interpolation laundering synthetic samples into observations.
4. There is no stable source/channel/acquisition identity, nor row-level round
   or visit identity. Synchronization can therefore erase actual acquisition
   timing.
5. `MultiplexedMeasurement.is_multiplexed` infers acquisition mechanism from
   channel count. Channel count does not prove sequential acquisition.
6. `FilterParams` and `InterpParams` carry irrelevant fields for the selected
   method, allowing impossible or misleading recipes.
7. Transform implementations manually reconstruct models or use unchecked
   `model_copy(update=...)`; neither route centralizes derivation IDs,
   validation, support propagation or operation records.
8. A full operation history on each signal would grow without bound, while no
   normalized provenance graph exists today.
9. Raw ndarrays do not serialize through ordinary Pydantic JSON. Persistence
   has no protocol, integrity hash, completion marker or independent versioning.

## 3. Mandatory architecture decisions

These are requirements, not suggestions.

1. **Two base classes.** `ValueModel` is frozen, forbids extra fields and
   validates defaults; it is for JSON-serializable metadata/specs. `ArrayModel`
   extends it with arbitrary ndarray support and array ownership helpers.
2. **Stable identity is explicit.** Use `ChannelKey`, `SignalDescriptor`,
   `SourceAsset` and `AcquisitionRef`; never derive identity from list position,
   file path, array equality or display labels.
3. **Scientific payload is `SignalData`.** It owns read-only `float64` arrays
   `time_s: (T,)`, `gate_depths_mm: (G,)`, `values: (T,G)`, plus
   `SampleSupport` and optional row-level `AcquisitionIndex`.
4. **Support is data.** `SupportKind` is `MISSING`, `OBSERVED`,
   `INTERPOLATED`, or `EXTRAPOLATED`. Support and quality are `(T,G)`; acquisition
   identity is row-level `(T,)`. NaN is a storage consequence, never the source
   of truth for support.
5. **Closed processing state is explicit.** `ChannelArtifact` wraps acquisition
   identity, descriptor, config and `SignalData`; `ChannelBundle` pairs the
   current artifact with its normalized provenance graph. Per-channel public
   transforms are `ChannelBundle -> ChannelBundle`; recording-level transforms
   are `ArtifactBundle -> ArtifactBundle`. Every transform must call the central
   `derive()` constructor. Do not use `model_copy(update=...)` to create
   transformed scientific data.
6. **Provenance is normalized.** `OperationRecord` nodes and artifact-parent
   edges live in an `ArtifactGraph`/bundle. A signal carries IDs, not a copied
   history list.
7. **`Recording` is mechanism-neutral.** It has explicit `AcquisitionMode`, a
   non-empty tuple of streams and optional declared acquisition order. It does
   not infer multiplexing from stream count. Statistical products use a
   separate `ProfileStatistics` result model.
8. **Transforms propagate semantics.** Filters preserve support kind and add
   `FILTERED`; interpolation classifies exact ancestral knots separately from
   synthetic samples, enforces bracket-span/gap policy, and never launders
   synthetic support; synchronization retains actual acquisition times and
   uses matched round/visit identity.
9. **Specs are discriminated unions.** Each method receives only its relevant
   validated fields. Do not retain bundled all-method parameter bags.
10. **Persistence is separate from domain models.** Start with NPY files and a
    versioned JSON manifest containing `ArrayRef`s, integrity hashes and an
    atomic `COMPLETE` marker. Do not add Zarr now. Domain, operation and storage
    schema versions advance independently.
11. **Migration is incremental and test-driven.** Keep the legacy parser,
    `.ADD`, visualization and CLI surfaces outside initial scope unless a test
    proves a migration dependency. Do not perform a big-bang rewrite.

## 4. Explicit non-goals

- No Zarr dependency, chunked/lazy execution, database, cloud object store or
  remote URI protocol.
- No `.ADD` parser rewrite, parser enum unification, legacy visualization
  redesign, CLI redesign, notebook redesign, RPM rewrite, geometry model,
  spatial interpolation, aliasing removal or new processing feature.
- No pandas/xarray conversion and no live SciPy interpolant stored in a model.
- No automatic unit conversion. A transform that changes units must explicitly
  emit a new descriptor and operation record; this rework only preserves units.
- No compatibility promise for undocumented pre-1.0 constructors. Compatibility
  is deliberate and temporary as specified in Section 12, never accidental.
- No embedded raw arrays in JSON, pickle, `allow_pickle=True`, object-dtype
  arrays, hidden mutation, or history list copied into every artifact.
- No edits to the older architecture/design documents before the final docs
  phase; this file is the superseding authority during implementation.

## 5. Target package tree

Create only when its phase begins. Keep modules below roughly 400–500 lines;
split by the shown concerns rather than inventing generic utility packages.

```text
src/udv_echo_process/
├── models/
│   ├── base.py                 # ValueModel, ArrayModel, array helpers
│   ├── identity.py             # ChannelKey, SignalDescriptor, SourceAsset,
│   │                           # AcquisitionRef
│   ├── support.py              # SupportKind, QualityFlag, SampleSupport
│   ├── acquisition.py          # AcquisitionIndex, AcquisitionMode
│   ├── signal.py               # SignalData, ChannelArtifact
│   ├── recording.py            # Recording, ProfileStatistics
│   ├── channel_config.py       # serializable frozen channel metadata
│   ├── io.py                   # existing source enums/spec during migration
│   ├── channel_series.py       # temporary compatibility type; remove Phase 9
│   ├── measurement.py          # temporary compatibility type; remove Phase 9
│   └── __init__.py
├── process/
│   ├── derive.py               # operation construction + validated derivation
│   ├── specs.py                # discriminated filter/interpolation spec unions
│   ├── filter.py               # artifact filters and support propagation
│   ├── sync.py                 # artifact resampling and synchronization
│   └── __init__.py
├── provenance/
│   ├── models.py               # ImplementationRef, OperationRecord,
│   │                           # ArtifactGraph, ChannelBundle, ArtifactBundle
│   └── __init__.py
├── storage/
│   ├── models.py               # ArrayRef and manifest models
│   ├── npy.py                  # store/load protocol
│   └── __init__.py
├── io/
│   └── dop/bdd.py              # migrate reader only in Phase 6
└── __init__.py                 # public surface switched at controlled gates

tests/
├── test_model_base.py
├── test_identity.py
├── test_support.py
├── test_signal_data.py
├── test_derive.py
├── test_artifact_filter.py
├── test_artifact_resample.py
├── test_recording.py
├── test_io_bdd_artifacts.py
├── test_provenance.py
├── test_storage_npy.py
├── test_models.py              # legacy until Phase 9
├── test_process_filter.py      # legacy until Phase 5/9
└── test_process_sync.py        # legacy until Phase 5/9
```

## 6. Exact model contracts

### 6.1 Base configuration and array ownership

`ValueModel(BaseModel)` has exactly:

```python
model_config = ConfigDict(
    frozen=True,
    extra="forbid",
    validate_default=True,
)
```

It must not enable `arbitrary_types_allowed`. Every field in a `ValueModel`
must round-trip through `model_dump(mode="json")` unless it is explicitly a
manifest path represented as a POSIX relative string.

`ArrayModel(ValueModel)` adds
`arbitrary_types_allowed=True` while retaining all three settings above.
Every ndarray field validator must call one shared helper that:

1. rejects object, string, structured and complex dtype;
2. converts with the field's exact dtype and C order;
3. always owns a copy (`OWNDATA` true and no memory shared with caller input);
4. marks the resulting buffer non-writeable; and
5. reports field name, expected dtype/rank/shape and actual dtype/rank/shape.

A transformed output must not share memory with any parent scientific array.
A loader may use a temporary memory map internally but must return owned,
read-only arrays before closing the file. `model_copy(update=...)` is forbidden
for `ArrayModel` data changes because Pydantic does not validate updates.

### 6.2 Identity/value models

All strings below are stripped and non-empty. Hashes are lower-case 64-character
SHA-256 hex. IDs are opaque lower-case `sha256:<hex>` strings. Store source file
names only, never machine-specific absolute paths.

```text
ChannelKey(ValueModel)
  device_channel: int >= 0

SignalQuantity(str, Enum)
  ECHO_AMPLITUDE = "echo_amplitude"
  AXIAL_VELOCITY = "axial_velocity"

SignalDescriptor(ValueModel)
  quantity: SignalQuantity
  unit: str
  Rules: echo unit is explicit (currently "module"); velocity unit is "mm/s".
         Quantity/unit mismatches are rejected; no implicit conversion.

SourceAsset(ValueModel)
  asset_id: str                 # sha256:<content_sha256>
  content_sha256: str           # 64 lower-case hex
  byte_size: int >= 0
  file_name: str                # basename only, no separators
  source: SourceSpec
  Rules: asset_id must equal "sha256:" + content_sha256.

AcquisitionRef(ValueModel)
  recording_id: str             # stable reader-issued opaque ID
  source_asset_id: str          # equals SourceAsset.asset_id in a bundle
  channel: ChannelKey
  Rules: identity is unchanged by processing.
```

Reader-issued `recording_id` is deterministic:
`sha256(canonical_json({source_asset_id, reader_recording_ordinal: 0}))`. The
ordinal is reserved for future multi-recording containers and is `0` for the
current DOP BDD reader. Channel identity comes from the BDD channel number, not
list order.

`ChannelConfig` and `SourceSpec` migrate to `ValueModel`; all existing optional
metadata remains JSON-serializable. Validation may become stricter only with a
focused failing test and a reader fixture proving the expected value.

### 6.3 Support and quality

Use integer enums so arrays are compact and stable on disk:

```text
SupportKind(IntEnum; uint8 representation)
  MISSING = 0
  OBSERVED = 1
  INTERPOLATED = 2
  EXTRAPOLATED = 3

QualityFlag(IntFlag; uint32 bit mask)
  NONE = 0
  DEVICE_INVALID = 1 << 0
  LOW_SIGNAL = 1 << 1
  SATURATED = 1 << 2
  OUT_OF_RANGE = 1 << 3
  TIMESTAMP_ANOMALY = 1 << 4
  ALIASED = 1 << 5
  OUTLIER = 1 << 6
  GAP_TOO_LONG = 1 << 7
  FILTERED = 1 << 8
  EDGE_AFFECTED = 1 << 9
  EXTRAPOLATED = 1 << 10
  REINTERPOLATED = 1 << 11
  TIME_ALIGNED = 1 << 12
  ALIGNMENT_UNCERTAIN = 1 << 13
```

`SampleSupport(ArrayModel)` fields are:

```text
kind: ndarray[uint8]       # shape (T,G), values in SupportKind
valid: ndarray[bool]       # shape (T,G): current numeric value is usable
quality: ndarray[uint32]   # shape (T,G), only declared QualityFlag bits
```

Invariants:

- all three shapes are identical;
- `MISSING` always has `valid=False`; `INTERPOLATED` and `EXTRAPOLATED` always
  have `valid=True`; `OBSERVED` may be valid or invalid because an acquisition
  can occur while its value is unusable;
- `SupportKind` records whether/where acquisition support exists; `valid`
  records whether the current numeric value is usable; quality says why a value
  is invalid or what was done to it. These axes must not be collapsed;
- invalid `OBSERVED` cells carry at least one acquisition-quality reason
  (`DEVICE_INVALID`, `LOW_SIGNAL`, `SATURATED`, `OUT_OF_RANGE`, `ALIASED`, or
  `OUTLIER`); `NONE` is valid for clean usable observations/estimates;
- unknown support values or quality bits are rejected on construction/load;
- quality flags accumulate by bitwise OR and are never cleared by a transform;
- `EXTRAPOLATED` support always includes the `EXTRAPOLATED` quality flag;
- `FILTERED` does not change support kind; re-interpolation adds
  `REINTERPOLATED`, and synchronization that changes the analysis coordinate
  adds `TIME_ALIGNED`.

### 6.4 Row-level acquisition index

`AcquisitionIndex(ArrayModel)` fields:

```text
sample_id: ndarray[int64]                  # (T,), -1 means no exact ancestor
acquisition_time_s: ndarray[float64]       # (T,), NaN iff sample_id == -1
round_id: ndarray[int64] | None = None     # (T,), -1 means unmatched/unknown
visit_id: ndarray[int64] | None = None     # (T,), -1 means unmatched/unknown
profile_in_visit: ndarray[int64] | None = None  # (T,), -1 means unknown
```

Rules:

- every present array has shape `(T,)`;
- `sample_id` is unique and nonnegative for acquired source rows; `-1` marks a
  wholly synthetic row. `sample_id == -1` iff `acquisition_time_s` is NaN;
- finite acquisition times are strictly increasing within each channel stream;
- optional IDs are independently optional because a source may expose actual
  acquisition times without round/visit structure. Present IDs are `>= 0` or
  exactly `-1`; `profile_in_visit` requires `visit_id`;
- every row containing an `OBSERVED` gate has a nonnegative `sample_id` and a
  finite actual acquisition time, even when all observed cells on that row are
  invalid. It need not have round/visit IDs when the source cannot prove them;
- a wholly synthetic row has `sample_id=-1`, NaN acquisition time and `-1` in
  every optional index array that is present; do not invent identity or time;
- synchronization may retain a source row's sample/round/visit IDs while
  `SignalData.time_s` holds a reference/aligned coordinate, but
  `acquisition_time_s` remains the channel's actual measured time. Such a row
  is only `OBSERVED` where the value is the original value at that actual time;
  sampling it at a different time is `INTERPOLATED`.

For a mixed-support row, the row index is retained when any gate is an exact
ancestral observation (valid or invalid); otherwise use the synthetic sentinel.

### 6.5 Scientific payload

`SignalData(ArrayModel)` fields:

```text
time_s: ndarray[float64]             # (T,)
gate_depths_mm: ndarray[float64]     # (G,)
values: ndarray[float64]             # (T,G)
support: SampleSupport               # (T,G)
acquisition: AcquisitionIndex | None # row-level (T,), optional by source
```

Invariants, all enforced at construction and load:

- `T >= 1`, `G >= 1`;
- every array is owned, C-contiguous and read-only;
- `time_s` and `gate_depths_mm` are one-dimensional, finite and strictly
  increasing; duplicates are rejected with the first violating index;
- `values.shape == (T,G)` and support shape equals `(T,G)`;
- `support.valid=True` requires a finite value; `support.valid=False` requires
  NaN. Infinity is always rejected. This value/validity relation is independent
  of support kind, so an invalid observation is represented as
  `OBSERVED + valid=False + NaN + an acquisition-quality flag`;
- if `acquisition` is present it has length `T`; every row containing an
  `OBSERVED` gate has a real sample ID/acquisition time; rows with no observed
  gate use the synthetic sentinel as specified above;
- no empty defaults exist. Construction always supplies all payload fields.

NaN is not an alternate validity channel: it mirrors `support.valid` and the
quality bits explain invalidity. A NaN with `valid=True`, or a finite value with
`valid=False`, is invalid.

### 6.6 Artifacts

ChannelArtifact(ArrayModel) fields:

```text
artifact_id: str
acquisition: AcquisitionRef
descriptor: SignalDescriptor
config: ChannelConfig
data: SignalData
```

Source artifacts use a deterministic artifact ID over acquisition ID,
descriptor/config canonical JSON and hashes of every scientific/support/index
array. Derived artifact IDs use the canonical operation ID plus parent artifact
IDs plus output array hashes. IDs are content-addressed and reproducible; wall
clock, path and object address never participate.

Artifact invariants:

- acquisition identity and channel key are stable across transforms;
- config/descriptor changes require an operation that explicitly records the
  change; current filter/resample operations preserve both;
- `artifact_id` is recomputed and checked by constructors/loaders, not trusted
  from callers;
- equality of scientific data is explicit (`np.array_equal` or
  `np.allclose`); do not rely on model `==` for ndarray-bearing models.

### 6.7 Recording and statistical products

```text
AcquisitionMode(str, Enum)
  SIMULTANEOUS = "simultaneous"
  SEQUENTIAL = "sequential"
  ROLLING = "rolling"
  UNKNOWN = "unknown"

Recording(ArrayModel)
  recording_id: str
  source_asset: SourceAsset
  acquisition_mode: AcquisitionMode
  streams: tuple[ChannelArtifact, ...]
  acquisition_order: tuple[ChannelKey, ...] | None = None
```

Validation:

- `streams` is non-empty;
- all stream `AcquisitionRef.recording_id` values equal `recording_id` and all
  source asset IDs equal `source_asset.asset_id`;
- channel keys and artifact IDs are unique;
- if `acquisition_order` is supplied, it is a duplicate-free exact permutation
  of stream channel keys;
- mode is never inferred. A one-stream recording can still be `SEQUENTIAL`;
  a multi-stream recording can be `SIMULTANEOUS`;
- BDD decoding sets the mode from decoded acquisition topology. If the file
  cannot prove it, use `UNKNOWN`, never channel count;
- decoded `(round_id, visit_id)` pairs must be unique within a stream. Across
  streams, a round groups visits known to belong together; visit IDs reflect
  acquisition order within that round. Missing visits stay missing and are not
  renumbered.

`ProfileStatistics(ValueModel)` is a terminal result, not a `Recording`:

```text
artifact_id: str
source_artifact_id: str
descriptor: SignalDescriptor
gate_depths_mm: tuple[float, ...]
count: tuple[int, ...]
mean: tuple[float | None, ...]
std: tuple[float | None, ...]
minimum: tuple[float | None, ...]
maximum: tuple[float | None, ...]
```

All tuples have gate length; count is nonnegative; a zero count requires all
four statistic values to be `None`. This JSON-oriented result intentionally
contains no ndarray.

## 7. Exact transform/support propagation rules

### 7.1 Common rules

- Transform bodies accept a validated `ChannelBundle` and a discriminated spec,
  compute new owned arrays, then call `derive()`. They do not manually
  instantiate a derived artifact or call `model_copy(update=...)`.
- Provide pure bridge helpers
  `select_channel(bundle: ArtifactBundle, key: ChannelKey) -> ChannelBundle` and
  `replace_channel(bundle: ArtifactBundle, channel: ChannelBundle) ->
  ArtifactBundle`. Selection safely reuses the deeply immutable graph;
  replacement requires
  the same `recording_id`/channel identity, replaces exactly one stream, and
  adopts the returned validated graph. These are the only supported bridge
  between per-channel and recording-level processing state.
- Parent arrays and metadata remain unchanged. Output arrays share no memory
  with parent arrays.
- Quality bits are ORed, never replaced. Unknown bits are an error.
- A transform operates independently per gate. Spatial gate interpolation is
  not part of this plan.
- Invalid/missing cells divide a gate into processing segments. A time gap
  greater than the method spec's `max_gap_s` also divides segments. No filter
  window or interpolator may cross a segment boundary.
- A segment that cannot satisfy a method's minimum sample count is copied
  unchanged for filters and becomes missing for requested synthetic
  interpolation points; add `GAP_TOO_LONG` where interpolation failed.

### 7.2 Filter specs

Use a Pydantic discriminated union on `method`:

```text
MedianFilterSpec: method="median", window odd int >=1, max_gap_s float >0
MeanFilterSpec:   method="mean", window int >=1, max_gap_s float >0
SavgolFilterSpec: method="savgol", window odd int >=3,
                   polyorder int >=0 and < window, max_gap_s float >0,
                   uniform_rtol float in [0, 0.05] default 0.01
TvFilterSpec:     method="tv", weight float >0, iterations int >=1,
                   max_gap_s float >0,
                   uniform_rtol float in [0, 0.05] default 0.01
FilterSpec = Annotated[MedianFilterSpec | MeanFilterSpec |
                       SavgolFilterSpec | TvFilterSpec,
                       Field(discriminator="method")]
```

No irrelevant parameter is accepted. `extra="forbid"` means, for example,
`weight` on a median spec is an error.

Filter propagation for each cell:

| Input | Output value/support | Output quality |
|---|---|---|
| `MISSING` | NaN, `MISSING`; excluded and segment boundary | unchanged |
| invalid `OBSERVED` | NaN, `OBSERVED`; excluded and segment boundary | unchanged acquisition-quality reason(s) |
| valid `OBSERVED` | filtered finite value, `OBSERVED` | input OR `FILTERED`; add `EDGE_AFFECTED` where the method uses padded/truncated edge context |
| valid `INTERPOLATED` | filtered finite value, `INTERPOLATED` | input OR `FILTERED`; add `EDGE_AFFECTED` as applicable |
| valid `EXTRAPOLATED` | filtered finite value, `EXTRAPOLATED` | input OR `FILTERED` OR `EXTRAPOLATED`; add `EDGE_AFFECTED` as applicable |
| valid segment too short | original value and support, unchanged | unchanged (not falsely `FILTERED`) |

MEDIAN and MEAN use time-contiguous valid segments and never cross
`max_gap_s`. SAVGOL and TV additionally require every processed segment to be
truly uniform: all adjacent `dt` values must satisfy
`np.allclose(dt, median(dt), rtol=uniform_rtol, atol=0)`. Do not exclude a final
short interval. The old special-case that ignored the final interval is
superseded. Non-uniform segments raise a method/channel/segment-specific error;
they are not silently skipped. SAVGOL minimum length is `window`; TV minimum is
2. MEDIAN/MEAN windows are clipped only at segment edges by their documented
nearest-edge behavior, never across gaps.

### 7.3 Interpolation specs

Use a discriminated union on `method`. Shared fields are explicit on each
branch:

```text
extrapolation: "error" | "missing" | "nearest"
max_bracket_span_s: float > 0
long_gap: "missing" | "error"

LinearInterpSpec:   method="linear" + shared fields
MonotoneInterpSpec: method="monotone" + shared fields
CubicInterpSpec:    method="cubic" + shared fields,
                    uniform_rtol in [0,0.05] default 0.01
BsplineInterpSpec:  method="bspline" + shared fields,
                    order int in [1,5],
                    uniform_rtol in [0,0.05] default 0.01
InterpSpec = Annotated[...four branches..., Field(discriminator="method")]
```

`nearest` applies only outside the overall valid domain and still yields
`EXTRAPOLATED`; it does not bridge an internal long gap. CUBIC and BSPLINE
require truly uniform valid source segments using the same all-interval rule as
SAVGOL/TV. MONOTONE has no uniformity requirement. Capacity errors identify
method, required samples and actual segment size.

For target time `x` and gate `g`, compare times using exact source `float64`
values (target grids that intentionally reuse source times must reuse the array
values, not tolerance-match nearby times):

| Condition | Output support/value | Quality/index |
|---|---|---|
| Exact valid source knot | copy source value and its support kind | copy quality; preserve row acquisition index |
| Exact invalid observed knot | NaN, `OBSERVED`, `valid=False` | copy acquisition-quality reasons and preserve row acquisition index |
| Exact missing source knot | NaN, `MISSING` | copy quality; row sentinel unless another gate on that row is an exact observation |
| Between two valid knots, bracket span `<= max_bracket_span_s` | finite interpolation; `EXTRAPOLATED` if either ancestor is extrapolated, otherwise `INTERPOLATED` | OR both quality masks; add `EXTRAPOLATED` when applicable; add `REINTERPOLATED` if either ancestor is synthetic; row acquisition sentinel |
| Either bracket endpoint invalid or missing | NaN, `MISSING` | OR endpoint quality + `GAP_TOO_LONG`; row sentinel |
| Bracket span `> max_bracket_span_s`, `long_gap="missing"` | NaN, `MISSING` | OR ancestors + `GAP_TOO_LONG`; row sentinel |
| Same long gap, `long_gap="error"` | raise before artifact creation | error names channel, gate, bracket times/span/limit |
| Outside valid domain, `extrapolation="error"` | raise | count and source bounds in error |
| Outside, `extrapolation="missing"` | NaN, `MISSING` | existing edge quality OR `OUT_OF_RANGE`; row sentinel |
| Outside, `extrapolation="nearest"` | finite nearest-edge value, `EXTRAPOLATED` | edge quality OR `EXTRAPOLATED` OR `OUT_OF_RANGE`; row sentinel |

Re-interpolation rule: an exact synthetic knot keeps its existing
`INTERPOLATED`/`EXTRAPOLATED` support and receives `REINTERPOLATED`. Between
knots, synthetic ancestry cannot produce `OBSERVED`; extrapolated ancestry
dominates interpolated ancestry and `REINTERPOLATED` is added when any
contributor is synthetic. Thus no transform can turn synthetic data into
observations.

### 7.4 Synchronization

Synchronization consumes a `Recording`, but performs all sampling through the
same artifact resampling primitive and emits a new `Recording` plus operation
records in the bundle.

- Match channels by explicit `(round_id, visit_id)`, never by row position,
  channel-count arithmetic, first-time offsets, or whole-series correlation.
- A synchronization target row is keyed by a matched round and the selected
  reference visit/time policy. Missing channel visits remain missing.
- Keep `SignalData.time_s` as the aligned/reference grid. Keep each stream's
  actual source time in `AcquisitionIndex.acquisition_time_s`; never overwrite
  it with the reference time.
- An unchanged exact sample remains `OBSERVED`. Any value evaluated at a time
  other than its actual acquisition time is `INTERPOLATED`, subject to bracket
  and gap rules above.
- Duplicate `(round_id, visit_id)` in one stream, ambiguous matches, or
  nonmonotonic actual times are hard errors. Unmatched visits may be represented
  as missing only under an explicit sync policy and receive
  `ALIGNMENT_UNCERTAIN`.

## 8. Provenance and operation rules

### 8.1 Models

```text
ImplementationRef(ValueModel)
  package: str                    # "udv-echo-process"
  version: str                    # installed project version
  callable: str                   # fully-qualified public callable
  revision: str | None            # git SHA only when available; never required

OperationRecord(ValueModel)
  operation_id: str               # deterministic sha256 ID
  kind: str                       # stable verb, e.g. "filter.median"
  schema_version: int >= 1
  params_json: str                # canonical JSON object, resolved defaults
  implementation: ImplementationRef
  parents: tuple[str, ...]        # ordered, non-empty parent artifact IDs
  warnings: tuple[str, ...] = ()

ArtifactDerivationLink(ValueModel)
  artifact_id: str
  operation_id: str

ArtifactGraph(ValueModel)
  operations: tuple[OperationRecord, ...]
  derivations: tuple[ArtifactDerivationLink, ...]
  root_artifacts: tuple[str, ...]     # source/external artifact IDs

ChannelBundle(ArrayModel)
  artifact: ChannelArtifact
  graph: ArtifactGraph

ArtifactBundle(ArrayModel)
  recording: Recording
  graph: ArtifactGraph
```

`ChannelBundle` is the canonical per-channel processing state. It prevents a
transform from returning data while silently dropping the operation record.
`ArtifactBundle` is the equivalent recording-level state. Both are immutable;
a transform returns a new artifact and a new graph value without mutating its
input. Do not expose a public tuple-returning transform as the final API.

`params_json` is produced only from the validated branch-specific spec using
`model_dump(mode="json", exclude_none=False)`, then encoded as a canonical JSON
object (UTF-8 semantics, sorted keys, compact separators, `allow_nan=False`).
Reject NaN/Infinity, ndarray, Path, callable and arbitrary Python values before
encoding. Readers parse `params_json`, require a JSON object, resolve
`(kind, schema_version)` through the operation registry, and revalidate it with
the registered spec. Storing the canonical string rather than a mutable nested
`dict` preserves `ValueModel` immutability while retaining exact recipes.

### 8.2 DAG invariants

- An operation has one or more ordered parent artifact IDs. Source artifacts
  have no operation mapping.
- Every derived artifact has exactly one `ArtifactDerivationLink`; every link
  references an existing operation; operation IDs, derived artifact IDs and
  links are unique.
- Parent references resolve either through `derivations` or exactly once in
  `root_artifacts`. No dangling reference, root/derived overlap or
  cycle is allowed. Every artifact carried by `ArtifactBundle.recording` must
  resolve by one of those two routes.
- Topological order is deterministic: parent operations precede children; ties
  retain insertion order. Validation performs cycle detection.
- `warnings` records scientifically meaningful fallbacks/counts, not logs or
  timestamps. Empty warnings are `()`.
- Operation IDs hash canonical JSON of kind, operation schema version, resolved
  params, implementation and ordered parents. Derived artifact IDs additionally
  hash output payload/support/index arrays. Same inputs, implementation and
  output produce the same IDs.

### 8.3 Central `derive()`

`process/derive.py::derive` is the only constructor for transformed artifacts:

```python
def derive(
    parent: ChannelBundle,
    *,
    kind: str,
    spec: ValueModel,
    implementation: ImplementationRef,
    data: SignalData,
    warnings: tuple[str, ...] = (),
    descriptor: SignalDescriptor | None = None,
    config: ChannelConfig | None = None,
) -> ChannelBundle: ...
```

It validates resolved JSON params, preserves acquisition identity, uses parent
metadata unless an explicit replacement is supplied, computes operation and
artifact IDs, creates fully validated output, inserts the record into a new
validated graph, and returns the new closed bundle. It never mutates the input
bundle or graph. Graph insertion remains a separate pure helper called by
`derive()` so failed operations cannot partially update provenance.

Phase 7 adds `derive_many()` for an `ArtifactBundle` recording-level operation
with multiple ordered parents and one or more output artifacts. It uses the
same canonical operation and graph-insertion path as `derive()`; all output
artifacts map to that one operation, and each output ID hashes the shared
operation ID plus its own payload. Synchronization must use `derive_many()`
rather than inventing a second provenance constructor.

## 9. Persistence protocol (storage version 1)

### 9.1 On-disk layout

```text
<bundle>/
├── manifest.json
├── arrays/
│   ├── <artifact-id-safe>/time_s.npy
│   ├── <artifact-id-safe>/gate_depths_mm.npy
│   ├── <artifact-id-safe>/values.npy
│   ├── <artifact-id-safe>/support_kind.npy
│   ├── <artifact-id-safe>/support_valid.npy
│   ├── <artifact-id-safe>/support_quality.npy
│   ├── <artifact-id-safe>/sample_id.npy                 # only when acquisition index present
│   ├── <artifact-id-safe>/acquisition_time_s.npy        # only when acquisition index present
│   ├── <artifact-id-safe>/round_id.npy                 # only when present
│   ├── <artifact-id-safe>/visit_id.npy                 # only when present
│   └── <artifact-id-safe>/profile_in_visit.npy         # only when present
└── COMPLETE
```

Artifact IDs must be converted to a safe deterministic directory component by
removing only the literal `sha256:` prefix; never accept caller path fragments.
All manifest paths are normalized relative POSIX paths with no absolute path,
`..`, empty segment or symlink traversal.

### 9.2 `ArrayRef` and manifest

```text
ArrayRef(ValueModel)
  path: str
  dtype: "float64" | "int64" | "uint8" | "uint32" | "bool"
  shape: tuple[int, ...]
  nbytes: int >= 0
  sha256: str

BundleManifestV1(ValueModel)
  storage_schema_version: Literal[1]
  domain_schema_version: int >= 1
  operation_schema_version: int >= 1
  recording: StoredRecordingV1     # typed metadata projection with ArrayRefs
  graph: ArtifactGraph
```

`StoredRecordingV1` and its typed nested stream/data/support/index manifest
models mirror the runtime structure but replace every ndarray with `ArrayRef`.
They use tuples and frozen `ValueModel` children—never untyped `dict`/`list`
containers—so the manifest is deeply immutable after validation. The manifest
contains no inline scientific/support/index array and no absolute source path.
JSON is UTF-8, sorted keys, compact separators, `allow_nan=False`,
and ends in one newline.

### 9.3 Write/read protocol

Write:

1. Validate the complete `ArtifactBundle` before I/O.
2. Create a unique sibling staging directory on the same filesystem; refuse an
   existing destination (no implicit overwrite).
3. Write each owned array with `np.save(..., allow_pickle=False)`, flush/fsync,
   stream SHA-256 from the bytes on disk, and create its exact `ArrayRef`.
4. Write and fsync canonical `manifest.json`; compute its SHA-256.
5. Write and fsync `COMPLETE` last with exactly
   `<manifest_sha256>  manifest.json\n`; fsync the staging directory.
6. Atomically rename staging to the requested destination and fsync the parent.
7. On any failure, remove only the staging directory created by this call; do
   not damage an existing destination.

Read:

1. Reject missing/malformed `COMPLETE` before reading arrays.
2. Verify the manifest hash, strict manifest schema and all three independent
   versions. Unsupported versions get a clear migration-required error.
3. Resolve every `ArrayRef` safely inside the bundle, reject symlinks, verify
   file hash, NPY header dtype/shape, `nbytes` and `allow_pickle=False` loading.
4. Reject missing, extra referenced, duplicate-path or unreferenced files under
   `arrays/`.
5. Reconstruct the domain bundle, taking owned C-order copies and marking them
   read-only; run all domain and DAG validation again.
6. Recompute artifact/operation IDs and reject mismatch.

Storage, domain and operation versions must never be collapsed into one
`version`. Version 1 has no migration-on-read; reject unknown versions with the
three found/supported values. Add a migration function only when version 2
exists.

## 10. Execution phases (strict dependency order)

Every code-producing phase uses red-green-refactor. “Expected PASS” means exit
code 0, not a fabricated count. If a test expected to fail passes for the wrong
reason, correct the test before implementation. At every stop gate, inspect
`git diff --name-only` and do not proceed with unrelated changes.

Use this environment prefix for all Python/test/lint commands:

```bash
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg
```

### Phase 0 — baseline and contract fixture inventory

**Files:** no modifications.

1. Read this plan, `AGENTS.md`, current model/process modules and their tests.
2. Run the full baseline:
   ```bash
   UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev pytest
   UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev ruff check src tests
   UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev ruff format --check src tests
   ```
   Expected: each exits 0. Record actual output; do not repeat a historical pass
   count from the agenda.
3. Inventory BDD fixture channel IDs, array dtypes/shapes, timing, source file
   identity and decoded visit/round information without modifying files.
4. Confirm `ruff format --check` exists in the installed pinned range. If the
   command itself is unsupported, stop and report the exact version/error; do
   not substitute `ruff format` because that mutates files.

**Acceptance:** clean baseline; fixture facts needed for Phase 6 are measured.

**STOP/GO:** stop on any baseline failure or pre-existing change. Proceed only
when the failure/change is understood and user-approved; do not fold unrelated
repairs into this rework.

### Phase 1 — value/array bases and stable identities

**Create:**
- `tests/test_model_base.py`
- `tests/test_identity.py`
- `src/udv_echo_process/models/identity.py`

**Modify:**
- `src/udv_echo_process/models/base.py`
- `src/udv_echo_process/models/io.py`
- `src/udv_echo_process/models/channel_config.py`
- `src/udv_echo_process/models/__init__.py`

1. Write failing tests for frozen/extra/default behavior, JSON dump of value
   models, copy+read-only array ownership, unsupported dtypes, error text,
   hash/ID formats, basename rejection, quantity/unit pairs and deterministic
   acquisition IDs.
2. Run:
   ```bash
   UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev pytest tests/test_model_base.py tests/test_identity.py -q
   ```
   Expected: FAIL because new classes/modules do not exist.
3. Implement the minimum base helpers and identity models. Migrate
   `SourceSpec`/`ChannelConfig` to `ValueModel` without changing reader output.
4. Re-run the targeted command. Expected: PASS.
5. Run legacy model and BDD tests. Expected: PASS; adjust constructors explicitly
   if freezing exposes mutation in tests, but do not weaken freezing.
6. Refactor only after green; run ruff check/format-check on touched source/tests.

**Acceptance:** caller mutation cannot alter an array field; all metadata dumps
as strict JSON; current BDD reader behavior remains covered.

**STOP/GO:** no downstream model until ownership tests include both direct ndarray
input and list-like input and assert `OWNDATA`, C-contiguous, non-writeable and
no shared memory.

### Phase 2 — support, acquisition index and `SignalData`

**Create:**
- `src/udv_echo_process/models/support.py`
- `src/udv_echo_process/models/acquisition.py`
- `src/udv_echo_process/models/signal.py`
- `tests/test_support.py`
- `tests/test_signal_data.py`

**Modify:**
- `src/udv_echo_process/models/__init__.py`

1. Add failing parameterized tests for every shape/dtype/range/finiteness/time,
   NaN-valid, support-quality-bit and acquisition sentinel invariant in Section
   6. Include first-index details in error assertions.
2. Run targeted tests; expected FAIL on missing symbols.
3. Implement enums and array models, then the smallest valid observed-signal
   fixture helper. Provide explicit factory functions for all-observed input and
   all-missing allocation; factories still invoke model validation.
4. Run targeted tests; expected PASS.
5. Add mutation and memory-sharing tests across every nested array, then run the
   full model subset:
   ```bash
   UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev pytest tests/test_model_base.py tests/test_identity.py tests/test_support.py tests/test_signal_data.py tests/test_models.py -q
   ```
6. Refactor duplicated validation/error formatting only while green.

**Acceptance:** all Section 6.3–6.5 invariants are executable tests; valid models
cannot change through retained caller references or direct writes.

**STOP/GO:** do not create `ChannelArtifact` until missingness is represented
only by the enforced support/value relation and unknown quality bits fail.

### Phase 3 — source artifacts and central derivation

**Create:**
- `src/udv_echo_process/provenance/models.py`
- `src/udv_echo_process/provenance/__init__.py`
- `src/udv_echo_process/process/derive.py`
- `tests/test_derive.py`
- `tests/test_provenance.py`

**Modify:**
- `src/udv_echo_process/models/signal.py`
- `src/udv_echo_process/models/__init__.py`
- `src/udv_echo_process/process/__init__.py`

1. Write failing tests for deterministic source artifact IDs, acquisition
   preservation, output no-sharing, resolved default params, warning tuples,
   operation ID sensitivity, array-content sensitivity, explicit descriptor
   change, invalid data rejection and forbidden `model_copy(update=...)` usage
   in transform modules (AST/source scan limited to `process/`).
2. Add failing graph tests for root registration, pure insertion, parent
   resolution, duplicate operation/artifact rejection and immutable input graph.
3. Run targeted tests; expected FAIL.
4. Implement `ChannelArtifact`, `ChannelBundle`, canonical JSON/hash helpers,
   `ImplementationRef`, `OperationRecord`, the minimal validated
   `ArtifactGraph`, and `derive()` exactly as Sections 8.1–8.3.
5. Run targeted tests; expected PASS. Run Phase 1–2 tests; expected PASS.
6. Refactor after green. Defer cycle detection, full bundle validation and
   multi-parent `derive_many()` to Phase 7; do not defer the graph required by
   closed per-channel transforms.

**Acceptance:** one source bundle and one no-op derived bundle have stable IDs,
owned arrays, a complete operation record and a resolvable graph edge; changing
one value changes the artifact ID.

**STOP/GO:** every later public transform must accept and return `ChannelBundle`
and call `derive()`; stop if it can drop provenance or must manually copy
identity/config or assemble an operation record.

### Phase 4 — discriminated specs and filter migration

**Create:**
- `src/udv_echo_process/process/specs.py`
- `tests/test_artifact_filter.py`

**Modify:**
- `src/udv_echo_process/process/filter.py`
- `src/udv_echo_process/process/__init__.py`
- `src/udv_echo_process/__init__.py`
- `tests/test_process_filter.py` only to retire tests made obsolete by the
  controlled signature switch; preserve behavioral coverage in the new file.

1. Write failing spec tests: branch parsing, relevant fields, forbidden
   irrelevant fields and every branch invariant.
2. Write table-driven failing tests covering every row of Section 7.2, gap
   segmentation, exact quality OR, no false `FILTERED`, strict SAVGOL/TV
   uniformity, metadata/acquisition preservation, operation record and memory
   ownership. Include synthetic signals first and one current BDD-derived source
   artifact fixture through a test adapter.
3. Run new tests; expected FAIL against the old API.
4. Implement specs. Convert `filter` to the closed
   `filter(bundle: ChannelBundle, spec: FilterSpec) -> ChannelBundle` API;
   convert `filter_sequence` to fold bundles in order. Keep numerical kernels
   private and independently testable.
5. Run new tests; expected PASS. Move every still-relevant numerical assertion
   from the legacy test before deleting/changing it.
6. Run all filter, model and BDD tests; expected PASS. Run ruff checks.

**Acceptance:** no bundled `FilterParams` public API remains in the new surface;
every support propagation row and segment boundary is tested; old numerical
behavior remains covered where compatible with the stricter scientific rules.

**STOP/GO:** inspect public exports. There must be one unambiguous `FilterSpec`
union and no transform path that returns a bare `ChannelSeries` as derived data.

### Phase 5 — interpolation/resampling migration

**Create:**
- `tests/test_artifact_resample.py`

**Modify:**
- `src/udv_echo_process/process/sync.py`
- `src/udv_echo_process/process/specs.py`
- `src/udv_echo_process/process/__init__.py`
- `src/udv_echo_process/__init__.py`
- `tests/test_process_sync.py` only under the same coverage-transfer rule as
  Phase 4.

1. Write failing branch/capacity tests for all four interpolation specs.
2. Write table-driven tests for every Section 7.3 row, including exact observed
   knots, exact interpolated/extrapolated knots, mixed ancestry,
   missing brackets, long-gap missing/error, three extrapolation policies,
   strict uniform splines and row-index sentinels.
3. Add a three-generation test: observed source -> interpolation ->
   re-interpolation. Assert no synthetic cell becomes `OBSERVED` and parent
   arrays remain unchanged.
4. Run targeted tests; expected FAIL against old `ChannelSeries` behavior.
5. Implement the closed
   `resample(bundle: ChannelBundle, spec: InterpSpec, *, times | dt_s) ->
   ChannelBundle` API with segment-aware per-gate sampling through `derive()`.
   Preserve existing method kernels only where they satisfy the new
   segment/support rules. Remove `nan_policy`; support controls validity.
6. Run new tests; expected PASS. Transfer and retain fixture knot/no-overshoot/
   grid behavior tests that remain scientifically valid.
7. Run all model, filter, sync and BDD tests; expected PASS; run ruff checks.

**Acceptance:** interpolation cannot bridge a forbidden gap, infer support from
NaN, or launder synthetic support; output has a deterministic artifact and
operation ID.

**STOP/GO:** stop before recording uplift if any operation can lose actual
acquisition index on an exact ancestral row.

### Phase 6 — `Recording`, acquisition topology and BDD reader migration

**Create:**
- `src/udv_echo_process/models/recording.py`
- `tests/test_recording.py`
- `tests/test_io_bdd_artifacts.py`

**Modify:**
- `src/udv_echo_process/models/acquisition.py`
- `src/udv_echo_process/models/__init__.py`
- `src/udv_echo_process/io/dop/bdd.py`
- `src/udv_echo_process/io/base.py` only if the reader return annotation must
  switch atomically
- `src/udv_echo_process/io/__init__.py` only for the same return-type switch
- `src/udv_echo_process/__init__.py`
- `tests/test_io_bdd.py` only after all equivalent decode assertions exist in
  the new artifact test

1. Write failing recording invariant tests, including nonempty streams,
   duplicate keys/IDs, mismatched recording/source IDs, acquisition-order exact
   permutation and proof that channel count does not determine mode.
2. Write failing synthetic topology tests for unique round/visit pairs, missing
   visits and synchronized actual-time preservation.
3. Write failing BDD fixture tests for content SHA-256 identity, deterministic
   IDs, descriptors/units/config, all-observed support where decoder values are
   valid, owned arrays and explicit acquisition mode/order/index. Measure the
   binary format's round/visit facts; do not infer them from list length.
4. Run targeted tests; expected FAIL because the reader still returns
   `MultiplexedMeasurement`.
5. Implement `Recording`, `ProfileStatistics` and the Section 7.1
   `select_channel`/`replace_channel` bridge helpers, then migrate BDD decode at
   the final construction boundary. The signal-data reader returns an
   `ArtifactBundle` whose graph registers every decoded channel artifact as a
   root; it must not return a bare `Recording` that callers must repair before
   processing. Keep byte decoding and numeric conversions stable. Where the BDD
   format cannot prove topology, emit `UNKNOWN` and no fabricated order/index;
   if that blocks synchronization, stop and document the exact missing format
   fact rather than guessing.
6. Run targeted and legacy BDD tests; expected PASS. Run all tests/ruff.

**Acceptance:** every BDD fixture returns a valid mechanism-neutral
`ArtifactBundle` containing a `Recording`, stable source/acquisition/artifact
identity, and a graph containing all source artifacts as roots, with no path
leakage; prior numeric decode assertions remain covered.

**STOP/GO:** mode/index claims must be tied to decoded file evidence. `len(streams)
> 1` must not occur in mode-selection code.

### Phase 7 — normalized provenance DAG and synchronization uplift

**Create:** none (`provenance/` and `tests/test_provenance.py` exist from Phase 3).

**Modify:**
- `src/udv_echo_process/provenance/models.py`
- `tests/test_provenance.py`
- `src/udv_echo_process/process/derive.py`
- `src/udv_echo_process/process/sync.py`
- `src/udv_echo_process/__init__.py`
- `tests/test_recording.py`

1. Write failing tests for DAG uniqueness, resolution, deterministic topology,
   cycle/dangling rejection, operation mapping, JSON-only params and bounded
   artifact metadata.
2. Write failing matched-round synchronization tests for reference times,
   actual acquisition times, absent visits, ambiguity and support propagation.
3. Run targeted tests; expected FAIL.
4. Implement pure graph insertion/validation and recording-level sync. Reuse
   artifact resampling; do not duplicate interpolation semantics. Add
   `derive_many()` as specified in Section 8.3 for the multi-parent operation.
5. Run targeted tests; expected PASS. Add a long chain test (at least 100
   operations) proving each artifact still stores O(1) provenance IDs rather
   than copied history and the graph stores one node per operation.
6. Run all tests and ruff checks.

**Acceptance:** a multi-stream fixture can be filtered, synchronized and traced
to sources through a validated acyclic graph while retaining per-channel actual
acquisition times.

**STOP/GO:** no persistence work until bundle JSON metadata contains no ndarray
and every derived artifact maps to exactly one operation.

### Phase 8 — NPY + manifest store

**Create:**
- `src/udv_echo_process/storage/models.py`
- `src/udv_echo_process/storage/npy.py`
- `src/udv_echo_process/storage/__init__.py`
- `tests/test_storage_npy.py`

**Modify:**
- `src/udv_echo_process/__init__.py` only if storage APIs are intentionally
  public; otherwise export from `storage` only.

1. Write failing round-trip tests for observed/missing/synthetic data, optional
   acquisition index, multi-generation DAG and exact IDs.
2. Add failure-injection tests for absent/incorrect `COMPLETE`, corrupt
   manifest/array hashes, dtype/shape/nbytes mismatch, unknown versions,
   traversal/symlink, duplicate/unreferenced arrays, existing destination and
   interrupted write cleanup.
3. Assert manifest JSON contains `ArrayRef`s and no inline `values`, support or
   acquisition arrays.
4. Run targeted tests; expected FAIL.
5. Implement storage version 1 exactly as Section 9, using standard-library
   hashing/filesystem operations and NumPy only. Do not add dependencies.
6. Re-run targeted tests; expected PASS. Round-trip one committed BDD fixture
   through a pytest temporary directory and compare metadata, IDs and arrays.
7. Run all tests and ruff checks.

**Acceptance:** corruption and incomplete stores fail closed with actionable
errors; a complete store reconstructs owned read-only arrays and identical
artifact/operation IDs.

**STOP/GO:** reject release if `manifest.json` scales with `T*G`, if pickle is
used, or if a partially written destination can be mistaken for complete.

### Phase 9 — compatibility retirement and documentation cleanup

**Modify only after all prior gates are green:**
- `src/udv_echo_process/models/channel_series.py`
- `src/udv_echo_process/models/measurement.py`
- `src/udv_echo_process/models/__init__.py`
- `src/udv_echo_process/__init__.py`
- tests that still name legacy models
- `docs/pipeline-conventions.md`
- `docs/pipeline-architecture.md`
- `docs/interpolation-design.md`
- `docs/filter-design.md`
- `AGENTS.md`
- `docs/agenda.md` (append status only)

1. Search imports/usages of `ChannelSeries`, `MultiplexedMeasurement`, bundled
   params and pre-convergence closure text across `src`, `tests`, `notebooks`,
   `docs`, `README.md` and `references`.
2. Decide from actual consumers whether to remove the legacy models or retain a
   one-release explicit adapter. The default is removal because the package is
   pre-1.0 and prior docs chose a ground-up rebuild. An adapter, if proven
   necessary, must copy arrays, mark all finite legacy cells `OBSERVED`, reject
   legacy NaNs without explicit support, emit a warning, and be tested; it must
   not masquerade as the new domain model.
3. Make public exports unambiguous and remove dead bundled specs only after all
   call sites move.
4. Update old architecture documents to point to this landed model and mark
   superseded examples historical. Do not rewrite agenda history; append a
   dated completion/deviation entry.
5. Run the full Definition of Done commands in Section 15.

**Acceptance:** no stale executable example directs users to the old scientific
model; legacy code is either removed or isolated behind an explicit tested
adapter; agenda history remains append-only.

**STOP/GO:** no “done” status until the full repository search and verification
commands are clean.

## 11. Error-message contract

Errors are part of the scientific API. Tests must assert stable diagnostic
fragments, not complete Pydantic formatting.

- Model errors name the model field and include expected versus actual
  dtype/rank/shape/value relation.
- Time/gate ordering errors include the first violating index and adjacent
  values.
- Support/value errors include mismatch count and first `(time, gate)` index.
- Unknown support/quality values include the offending integer and first index.
- Transform errors begin with the public operation name and include channel
  key. Gap errors add gate index, bracket endpoints, measured span and limit.
- Uniformity errors include method, segment row range, median `dt`, worst `dt`
  and configured tolerance.
- Acquisition errors include recording/channel and conflicting round/visit.
- Store errors include bundle-relative path, expected/actual hash/dtype/shape/
  version as applicable, never an absolute machine path in persisted output.
- Do not expose full arrays, credentials or local absolute source paths in an
  error. Counts and first offending index are sufficient.

## 12. Migration, rollback and compatibility policy

1. New models coexist with `ChannelSeries`/`MultiplexedMeasurement` through
   Phases 1–5. Do not partially change `io.load()` return type.
2. Switch BDD construction and its public return type atomically in Phase 6,
   only after equivalent numeric decode tests exist for `Recording`.
3. Transfer tests before removing an old assertion. A new test file passing is
   not permission to lose old numerical/fixture coverage.
4. No in-place persisted-data migration exists in storage v1. New writers create
   a new destination; readers reject unknown/incomplete versions.
5. A phase rollback reverts that phase's source/tests/exports together. Because
   each stop gate begins green, reverting must restore the preceding full-suite
   state. Never “roll back” by loosening validation or relabeling support.
6. Keep operation/domain schema changes explicit. Any semantic change after v1
   increments the relevant version and adds a migration plan before code.
7. The package is pre-1.0: deliberate public breaks are allowed, but they must
   be atomic, documented and searched across all consumers. Do not add aliases
   whose names imply old semantics over new data.
8. Optional commits may be made only when explicitly authorized by the user,
   preferably one green phase per checkpoint. Never push unless explicitly
   asked.

## 13. Performance and resource limits

- Domain construction/load performs one O(T*G) validation scan and one owned
  copy per input array. Transform stage entry does not repeat parent scans;
  output construction validates the new output once.
- Numeric kernels operate per gate or vectorized on axis 0. No Python object per
  sample, no pandas frame and no nested list conversion of `values`.
- Fixed support overhead is 6 bytes/cell (`uint8 kind` + `bool valid` + `uint32
  quality`), in addition to `float64 values`; row acquisition overhead is 24
  bytes/row when present. Tests assert these exact dtypes.
- A transform may allocate parent + output + one algorithm workspace. Do not add
  unconditional extra full-size copies beyond the ownership copy; use tests
  with `np.shares_memory` and profiling before optimizing away safety.
- Hash arrays/files incrementally in chunks; do not call `.tobytes()` on a full
  production array solely for hashing.
- Manifest size is O(number of artifacts + operations + arrays), not O(T*G).
  Add a test comparing two equal-topology signals with very different `T` and
  assert manifest growth is bounded to changed decimal shape/hash metadata, not
  payload size.
- Do not introduce hard wall-clock assertions in CI. Add a benchmark only after
  a measured regression; correctness and bounded allocation are the current
  gates.

## 14. Do not do

- Do not use dataclasses, mutable Pydantic models, object arrays or writeable
  scientific buffers.
- Do not trust `frozen=True` to freeze an ndarray.
- Do not use `model_copy(update=...)` for scientific transformations.
- Do not infer validity solely from NaN, infer acquisition mode from channel
  count, or infer rounds by array position.
- Do not hard-code rolling offsets such as `k * DT` or use whole-series lag
  correlation to pair rounds.
- Do not call interpolated/extrapolated output observed, including exact knots
  inherited from an earlier interpolation.
- Do not let a filter/interpolator cross invalid cells or `max_gap_s`.
- Do not ignore a shortened final interval when a method requires true uniform
  cadence.
- Do not keep irrelevant method fields in a common parameter bag.
- Do not append a full provenance history to each artifact.
- Do not serialize ndarray payloads into JSON or enable NumPy pickle loading.
- Do not add Zarr “for later,” a generic pipeline framework, or unrelated
  parser/viz/CLI/notebook work.
- Do not edit old design docs before Phase 9, rewrite agenda history, fabricate
  test counts, commit, or push without explicit instruction.

## 15. Definition of Done

The rework is done only when all items are true:

- [ ] `ValueModel`/`ArrayModel` policies and owned read-only arrays are tested.
- [ ] Stable channel/source/acquisition/artifact identities are deterministic
      and independent of path/object address.
- [ ] `SignalData`, support, quality and optional acquisition index enforce all
      field, shape, dtype, time, finiteness and relation invariants.
- [ ] Filter and interpolation specs are discriminated unions with no irrelevant
      accepted fields.
- [ ] Every transform is bundle-closed, uses `derive()`, cannot drop its graph,
      does not mutate/share parent arrays and emits exactly one operation record
      per logical operation.
- [ ] Table-driven tests cover every support propagation row, long gaps,
      segmentation, true uniformity and re-interpolation ancestry.
- [ ] `Recording` carries explicit mechanism/topology; BDD fixture claims are
      decoded evidence, not channel-count inference.
- [ ] Synchronization matches rounds/visits and preserves actual acquisition
      times separately from aligned time.
- [ ] Provenance is a validated normalized DAG and a 100-operation chain does
      not copy history into artifacts.
- [ ] NPY store v1 round-trips a real BDD-derived bundle and fails closed on
      incomplete/corrupt/unsafe stores.
- [ ] Legacy surfaces are removed or isolated by an explicit tested adapter;
      documentation and exports are internally consistent.
- [ ] No out-of-scope dependency/feature or private absolute path was added.
- [ ] No commit or push occurred unless separately authorized.

Run exactly from the repository root:

```bash
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev pytest
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev ruff check src tests
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra dev ruff format --check src tests
git grep -nE '/home/[a-z]+|api[_-]?key|password|secret|BEGIN .*PRIVATE|tailscale|vllm' -- . ':!uv.lock'
```

The privacy scan passes when every match is either absent or reviewed as
non-secret/non-local documentation; do not silently accept a new private-path or
credential match. Run this only if a notebook was touched:

```bash
UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp/mpl MPLBACKEND=Agg uv run --extra marimo marimo check notebooks
```

Finally run:

```bash
git status --short
git diff --check
git diff --name-only
```

Review the complete diff for internal links, exact public names and stale
pre-convergence instructions. Report actual command output without inventing
pass counts. If any command fails, the rework remains open.