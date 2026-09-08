# Pipeline architecture — udv-echo-process

Status: **proposal → partially landed.** Original proposal 2026-09-08
(planning-only). **Revision 2 (2026-09-08):** Stage 1–2 of the ground-up
rebuild landed after the original text below was written (commit `f2482f2`),
and discussion round 1 re-derived the direction (capture only — no code in this
doc revision, no final conventions committed).

> ## Revision 2 delta — read these sections as follows
>
> **Landed (Stage 1–2, commit `f2482f2`):** the `models/` + `io/` layers and
> the **DOP3000/3010 `.BDD` reader** (`io/dop/bdd.py`; all 22 `data/` fixtures
> load; 58 tests, ruff clean). Canonical types **converged** to
> **`ChannelSeries`** (atomic channel unit with its own real `time_s`) inside a
> **`MultiplexedMeasurement`** box — *not* the `SensorSeries`/`Recording` model
> sketched in the original §§4/7/8 below. Consequences recorded in place:
> - **No `models/raw.py` / `models/dataset.py` split** and **no pandas
>   dependency**: canonical storage is numpy arrays inside Pydantic models
>   (`models.base.Model`); the earlier "pandas backend" decision is superseded
>   (pandas was only ever an optional *derived* view, and is not built).
> - **§3 (IO), §4 (canonical model), §6 (target layout), §7 (deconstruction),
>   §8 (walkthrough), §10 (open decisions), §11 (staged rollout)** are revised
>   in place below; everything not marked keeps its original proposal value but
>   may name pre-convergence types.
> - **§12 (migration map)** stays as the "where old code lives" reference; its
>   destination cells predate convergence — the legacy modules stay put for now
>   (see §15.1).
> - **§15** records discussion round 1: decisions, deferrals, and the sync
>   experiment that must happen before `process/` design is final.

---

## 1. Driving use case — the rolling-sync pipeline

1. **Import + standardize** — ingest a **sequential/rolling** measurement into
   a canonical, time-indexed, per-sensor, per-gate layout.
2. **Time-synchronize** — the instrument samples sensors round-robin, so sensor
   *k* lags sensor 0 by *k·DT*; shift each sensor back by its offset and
   interpolate every sensor onto one common time grid so all sensors read "the
   same instant".
3. **Visualize** — (a) individual sensor data (time × gate), and (b) the
   **measurement lines** drawn on the real sensor geometry.
4. **Spatial interpolation** — *future / out of scope now*.

**Domain note (echo semantics).** UDV data is a **velocity projection**
(`mm/s`) or an **echo amplitude** (`Amp`). An echo peak at a gate depth means
"at this distance along the sensor's measurement line there is an object with
strongly different acoustic impedance" (vessel wall, mixer pill). This is why
geometry-aware visualization matters: it turns a per-gate amplitude spike into a
*spatial feature*. Wall/pill **tracking** is a future analysis concern, not part
of this pipeline task.

### What the data looks like (verified from committed fixtures)

`data/4-sensor-velocity/200RPM_v2.ADD` (raw, channels 6–9, `P=4` profiles/block,
~25.4 ms/profile). The `.BDD` twins of the same recordings show the identical
staggering as **real timestamps** — ch *k*'s first sample at ≈ `k·DT`:

| Channel | Block-1 first `TBD [ms]` | Offset vs ch 6 |
|--------:|-------------------------:|---------------:|
| 6 | 0.0 | 0 |
| 7 | 111.5 | ≈ `DT` |
| 8 | 222.1 | ≈ `2·DT` |
| 9 | 333.6 | ≈ `3·DT` |

The per-channel offset `DT` must be **derived from the data** (first timestamp
of each channel), never hard-coded — consistent with the earlier removal of the
`DT_S` magic constant (hardening §P0). In the landed model every channel *has*
its own real `time_s`, so sync derives lags from actual timestamps, not from an
assumed `k·DT`.

---

## 2. Layered architecture

The package splits into **layers with one-way dependencies** (`→` = imports):

```
io/  →  models/  ←  process/ analysis/ viz/
            ↑           │
            └───────────┘   (process/analysis/viz consume and produce models)
```

- **`io/`** — *where the data comes from*. A **source** is a first-class
  concept; each source has its own parser, all ending in the same canonical
  model.
- **`models/`** — shared Pydantic models. Single home for types → no import
  cycles, `io` and `process`/`viz` both depend on it.
- **`process/`** — pure, typed transforms: time-sync, resampling, pipeline
  composition, future spatial interpolation.
- **`analysis/`** — domain algorithms (RPM today; wall/pill tracking later).
- **`viz/`** — thin matplotlib wrappers, split by *what* is visualized.

**Granularity rule (finer, but still one module = one concern):** a sub-package
groups *layers*; within a layer, a module still holds **one domain concern with
a stable typed contract**, and a function is one atomic transform. The two
extremes are avoided the same way: no "one pipeline = one module" monoliths, no
per-`scipy`-call wrapper files. A *pipeline* is an explicit ordered composition
of named steps carrying no logic of its own.

---

## 3. Data-source (IO) layer — landed

The requirement: *"there might be different data sources and we have to
implement different data parsers."* So **source = (vendor/device, format)**, and
the IO layer owns source *discovery* and *per-source parsing*. Landed shape
(commit `f2482f2`):

```python
# io/base.py
class Reader(Protocol):
    def read(self, path: Path) -> MultiplexedMeasurement: ...

_REGISTRY: dict[SourceSpec, Reader]                  # keyed by frozen SourceSpec
def register_reader(spec: SourceSpec, reader: Reader) -> None: ...
def sniff(head: bytes) -> SourceSpec | None: ...     # content-based (magic)
def read_path(path: Path) -> MultiplexedMeasurement: ...  # sniff → dispatch
def load(path: Path | str) -> MultiplexedMeasurement: ... # convenience alias
```

- **Sniffing is content-based, not extension-based**: `load()`/`read_path()`
  read the magic bytes and dispatch to the registered reader. A misnamed file
  (this repo has a genuine `.BDD` misnamed `.jpg`) is caught by its bytes.
- **Adding a new device = `register_reader(...)`, not editing a dispatch
  `if/elif`.** Downstream (`process`/`analysis`/`viz`) is untouched.
- **`SourceSpec` is `frozen`** (hashable) so it can key `_REGISTRY`; `SourceFormat`
  and `MeasType` live in `models/io.py` (`SourceFormat`: `.ADD` / `.BDD`).
- A reader registers itself by **module** (module-level `sniff` + `read`),
  via `io/dop/__init__.py::install()` — idempotent, run at package import.

**Current source — Signal Processing SA, DOP 3010 (DOP-series).**

```
io/dop/
├── __init__.py   # DOP3000_SPEC + install(): registers the .BDD reader
└── bdd.py        # .BDD binary reader → MultiplexedMeasurement   [LANDED]
```

- **`bdd.py` (landed):** DOP3000/3010 `.BDD` reader — per-channel
  operation-parameter blocks at `548 + (k-1)·1024`, measurement blocks from
  `31268` with nested profile sub-blocks, overflow-corrected µs→s time,
  velocity→mm/s, echo→module-scale amplitude, per-channel depth grid → one
  `ChannelSeries` + `ChannelConfig` per channel. `BINUDOPV` magic; `BINWDOPV`
  (DOP2000) and 2-D/3-D modes are recognised but unsupported. The decode is a
  **cherry-picked DOPpy rewrite** (clean-room, no runtime dep — NumPy-2
  breakage, no packaging; see `docs/doppy-analysis.md`).
- **`add.py` (NOT migrated — by decision, §15.1):** the legacy `.ADD` logic
  stays in flat `parser.py` until the new stack reaches capacity; old code is
  inspiration only.

**Discovery.** Content-based `discover_data_files()` **landed in `io/__init__.py`**
(sniffs every file under each `data/<experiment>/` subdir). Note the current
transitional duplication: the top-level `__init__.py` still re-exports
`viz.discover_data_files` (the `.ADD`-listing version the notebook/legacy
surface uses) — resolved when `.ADD` support lands in `io/` (§15.1). Discovery
is about finding valid *source* files, not plotting.

---

## 4. Canonical model (models layer) — landed

*Original proposal (below this section) chose a pandas-backed
`SensorSeries`/`Recording` with a `models/raw.py` + `models/dataset.py` split.
The 2026-09-08 model convergence (Option B — full new model) replaced it:
canonical storage is **numpy arrays inside Pydantic models**, one per channel,
with no `raw`/`dataset` split. This section describes the landed model.*

```
models/
├── __init__.py        # re-exports; imports nothing from io/process/analysis/viz
├── base.py            # Model (numpy-capable BaseModel), shape_2d()
├── io.py              # MeasType, SourceFormat, SourceSpec (frozen)
├── channel_config.py  # ChannelConfig — static per-channel instrument config
├── channel_series.py  # ChannelSeries — the atomic channel unit (T2 checks)
└── measurement.py     # MultiplexedMeasurement — ordered box over channels
```

```python
# models/base.py
class Model(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)  # numpy fields OK
def shape_2d(time_s, values, n_gates) -> bool: ...   # shared T2 shape check

# models/io.py
class MeasType(str, Enum):  ECHO = "echo"; VELOCITY = "velocity"
class SourceFormat(str, Enum): ADD = ".ADD"; BDD = ".BDD"
class SourceSpec(Model):            # frozen → hashable, keys the reader registry
    vendor: str = "Signal Processing SA"   # defaults = the DOP family
    device: str = "DOP 3010"
    format: SourceFormat

# models/channel_config.py
class ChannelConfig(Model):         # static per-channel op config: all-optional,
    ...                             #   dense defaults (acoustic, gate geometry,
                                    #   medium/physics, TGC/filter/trigger, ADC)

# models/channel_series.py
class ChannelSeries(Model):         # the atomic pipeline unit
    channel: int
    meas_type: MeasType
    gate_depths_mm: list[float]     # per-gate measurement-line positions (mm)
    time_s: np.ndarray              # (T,) THIS channel's own real timestamps (s)
    values: np.ndarray              # (T, G) T profiles × G gates
    config: ChannelConfig           # nested static config
    # @model_validator (T2): values.shape == (len(time_s), len(gate_depths_mm))
    #   and time_s monotonic non-decreasing; .describe() one-liner

# models/measurement.py
class MultiplexedMeasurement(Model):  # the "box" over one recording
    file_path: Path
    source: SourceSpec
    header: str = ""; comment: str = ""
    channels: list[ChannelSeries]   # ordered (round-robin) — list, not dict
    # .meas_type (None if channels disagree) · .is_multiplexed ·
    # .by_channel() -> dict[int, ChannelSeries] · .describe()
```

Key properties of the landed model:

- **`ChannelSeries` is the atomic, self-contained unit** — it carries its own
  gate depths, its own **real** `time_s` (no assumed `k·DT`; DT can fluctuate
  per measurement — sync later derives offsets from actual timestamps) and its
  own static `ChannelConfig`.
- **`MultiplexedMeasurement` is a *view of a rolling/multiplexed file***: an
  ordered `list[ChannelSeries]` preserving multiplex order; a single-channel
  recording is just the box with one element. No sync/geometry fields live here
  — sync produces derived, re-timed `ChannelSeries` at call time; geometry is
  deferred (§5).
- **Storage vs views.** Each `ChannelSeries` is the store. Merged/cross-sensor
  layouts (tidy long, wide) were *derived* conveniences in the original
  proposal and are **not built** — add them only when a concrete consumer (a
  plot, a table export) needs one.
- **`MeasType` duplication is transitional:** `models.MeasType` is canonical
  for the new stack; flat `parser.py` keeps its own copy for the legacy `.ADD`
  surface. Unify when `.ADD` moves under `io/` (§15.1).

---

## 5. Geometry (explicit per-experiment config) — deferred

Original decision: **explicit config**, not free-text parsing of `comments.txt`
(which says things like "order dont remember"). Proposed:
`data/<experiment>/layout.toml` describing each channel's pose (position,
measurement-axis direction, gate spacing, probe diameter), so
`models/geometry.py` (`SensorPose`, `Layout`) loads it deterministically.
`comments.txt` remains a human-readable note, not an input.

**Convergence note (2026-09-08): geometry is deferred.** It is an add-on used
only far downstream (`viz/lines.py`, spatial interpolation, wall/pill
tracking); no `layout.toml` work yet.

---

## 6. Target layout

Landed tree (commit `f2482f2`) with planned additions marked:

```
src/udv_echo_process/
├── __init__.py            # public re-exports (legacy + new surface coexisting)
├── cli.py / run_all.py    # legacy entry points / batch drivers — untouched
│
├── models/                # ── LANDED (Stage 1–2) ──────────────────────────
│   ├── __init__.py        #   re-exports; one-way dependency rule
│   ├── base.py            #   Model (numpy-capable), shape_2d()
│   ├── io.py              #   MeasType / SourceFormat / SourceSpec (frozen)
│   ├── channel_config.py  #   ChannelConfig — static per-channel config
│   ├── channel_series.py  #   ChannelSeries — atomic channel unit (T2 checks)
│   └── measurement.py     #   MultiplexedMeasurement — ordered box
│
├── io/                    # ── LANDED (Stage 1–2) ──────────────────────────
│   ├── __init__.py        #   load/sniff/read_path + discover_data_files()
│   ├── base.py            #   Reader registry, register_reader, sniff
│   └── dop/               #   Signal Processing SA — DOP-series
│       ├── __init__.py    #   DOP3000_SPEC + install() (registers reader)
│       └── bdd.py         #   DOP3000/3010 .BDD reader   [LANDED]
│       └── add.py         #   [deferred — .ADD stays in legacy parser.py, §15.1]
│
├── process/               # ── skeleton ────────────────────────────────────
│   ├── __init__.py        #   placeholder (docstring still says Recording)
│   ├── sync.py            #   [NEXT — ChannelSeries primitives, §11/§15]
│   └── pipeline.py        #   [later — box-level step composition]
│
├── analysis/              # legacy rpm.py (untouched); future ports here
├── viz.py                 # legacy flat viz (untouched); viz/ split deferred
└── parser.py              # legacy .ADD parser (untouched until capacity)

data/<experiment>/layout.toml     # [deferred — geometry, §5]
```

Original proposal additionally split `viz/` into `heatmap.py` / `profile.py` /
`lines.py` and gave `analysis/` a sub-package of its own — those moves are
**deferred** (viz is last priority; old modules stay until the stack replaces
them).

---

## 7. Deconstruction map (does it generalise to other tasks?)

| Module | Contract | Reused by |
|--------|----------|-----------|
| `io/base.py` + `io/dop/bdd.py` | source → `MultiplexedMeasurement` | `.BDD` today; `.ADD` (deferred); future vendors/devices via `register_reader` |
| `models/channel_series.py` | atomic `ChannelSeries` (T2-validated) | every layer; the unit every transform will operate on |
| `models/measurement.py` | `MultiplexedMeasurement` box | rolling-sync, single/multi-channel RPM, future wall/pill tracking |
| `models/channel_config.py` / `io.py` | static config + source descriptors | readers, `describe()`, dispatch |
| `process/sync.py` *(future)* | channel primitives → box step | any rolling array (velocity **and** echo); feeds spatial |
| `process/pipeline.py` *(future)* | ordered box steps → result | every mini-pipeline; replaces ad-hoc drivers |
| `viz/*` *(future)* | `MultiplexedMeasurement` → figs | single/multi-sensor views; measurement lines (geometry, deferred) |
| `analysis/spatial.py` *(future)* | aligned measurement + `Layout` → 2D field | future step 4 |

No new module is rolling-sync-specific — the "does the deconstruction map to
other tasks" test passes.

---

## 8. End-to-end walkthrough (rolling-sync)

```python
# Today (landed):
from udv_echo_process.io import load
m = load("data/4-sensor-velocity/200RPM.BDD")   # .BDD → MultiplexedMeasurement
m.describe()                                    # 4 channels, real staggered time_s
m.by_channel()                                  # per-channel ChannelSeries

# Target (once sync lands — ChannelSeries primitives first, see §11/§15):
shifted = [shift_channel(c, lag_s[c.channel]) for c in m.channels]   # per-channel
grid    = build_common_grid(shifted, GridSpec(...))                  # strategy TBD (§15.2)
aligned = MultiplexedMeasurement(... channels=[resample_to_grid(c, grid) for c in shifted])

# Later, box-level uplift — Pipeline over MultiplexedMeasurement steps:
Pipeline([
    estimate_lags,        # data-derived, cross-channel
    shift_channels,       # box step composing the channel primitive
    resample_common_grid, # grid as a Spec → swappable strategy
])
```

---

## 9. Granularity guardrails

- **Sub-packages** group *layers* (io / models / process / analysis / viz) —
   this is now the deliberate structure (landed), not a future split.
- **Within a layer**, a module = one domain concern; merge a transform into its
   module when it shares the module's contract and is used together with its
   siblings (e.g. the sync functions stay one module).
- **Split** a module only when it mixes unrelated concerns, crosses ~400–500
   lines, or a second pipeline reuses only a subset of its primitives.
- A module is justified only when it adds domain semantics on top of an import
   (e.g. `models/channel_series.py` pins the canonical contract + invariants —
   it is not a numpy wrapper). Never wrap a bare `numpy`/`scipy`/`matplotlib`
   call.

> Note: this supersedes AGENTS.md's "keep modules flat / no pre-emptive
> sub-packages" guidance for *this* pipeline work — AGENTS.md should be updated
> to match once the rebuild settles (see §15.3).

---

## 10. Open decisions

**Resolved / closed (through 2026-09-08, incl. discussion round 1):**
- Sub-packages now — ✅ landed (`models/`, `io/`, `process/` skeleton).
- Dedicated IO/source layer with DOP 3010 — ✅ landed; **`.BDD` reader cherry-
  picked from DOPpy** (clean rewrite, no runtime dep) — ✅ landed (`bdd.py`).
- Canonical store: **one per-channel 2D series with its own real timestamps** —
  ✅ landed as numpy-backed `ChannelSeries` in Pydantic models; the earlier
  **pandas-backed `Recording`/`SensorSeries` + `raw`/`dataset` split is
  superseded** (no pandas dep).
- Geometry (`layout.toml`, `models/geometry.py`) — **deferred** (§5).
- `.ADD` migration & the legacy surface (`parser.py`, rpm, viz, notebook,
  MeasType/discover duplication) — **deferred: old code untouched until the new
  stack reaches capacity** (§15.1).

**Still open:**
1. **Sync grid & alignment strategy** — how the common grid is built and how
   per-channel lags are applied (constant shift vs adaptive; uniform-overlap vs
   reference vs union grid; endpoint policy). **Deliberately not decided here**:
   it needs an experiment (marimo preview notebook over the real 4-sensor
   `.BDD` signal) — see §15.2, discuss separately.
2. **stat-vs-raw under sync** — deferred (§15.1); `.BDD` has no stat/raw split
   (every profile carries real time), so this only matters for a future `.ADD`
   migration.
3. Later-stage candidates, kept on the table but uncommitted to: `.BDD`-vs-
   `.ADD` cross-validation, DOPpy-independent gate-depth derivation, pandas
   derived views only when a consumer needs them.

---

## 11. Staged rollout

**Stage 1–2 — models + IO + `.BDD` reader: ✅ LANDED** (commit `f2482f2`).
`models/` (base/io/channel_config/channel_series/measurement), `io/` (registry,
content sniffing, discovery), `io/dop/bdd.py`, `process/` skeleton; tests
`test_models.py` + `test_io_bdd.py`; 58 tests pass, ruff clean.

**Stage 3 — `process/sync.py`, ChannelSeries-first (NEXT).** Build the
per-channel sync transforms **bottom-up on `ChannelSeries`** (decision §15.1):
the primitive set, with grid/alignment **passed in as a `Spec`** so strategies
are swappable (this is what makes the §15.2 experiment possible):
- per-channel lag application / time handling and resample-to-grid primitives;
- a thin **marimo preview notebook** (library-first) to compare alignment
  strategies against the original 4-sensor signal before locking the design;
- tests on the committed fixtures: `data/4-sensor-velocity/*.BDD` (real
  staggered starts) and single-channel `data/echo/*.BDD` (trivially aligned).

**Stage 4 — box-level uplift.** `MultiplexedMeasurement -> MultiplexedMeasurement`
steps (`estimate_lags`/`shift_channels`/`resample_common_grid`) + the ordered
`Pipeline` composition in `process/pipeline.py`; re-express the conventions
closure rule and templates on the new types (§15.3) and fold into AGENTS.md.

**Stage 5 — capacity-driven legacy migration (deferred until the stack can
replace the old consumers):** `.ADD` reader in `io/dop/add.py` (real time from
cumulative `TBD`; stat handling decided then), MeasType unify on
`models.MeasType`, top-level `discover_data_files` flips to the `io` version,
analysis ports (RPM on `ChannelSeries`). Viz stays **last priority**.

---

## 12. Migration map — current scripts → new structure

Review of every current module (done 2026-09-08, symbol-level).

> **Ground-up stance.** This is a **reference for where old code lives**, not a
> preservation plan: the rebuild is ground-up, with the current implementation
> as *inspiration*. Nothing below implies keeping import paths, module objects,
> or public names — the map just tells you where to look for the logic to adapt.
>
> **Revision-2 note (2026-09-08):** the *destination* cells below were written
> for the pre-convergence proposal (they name `models/raw.py`, `dataset.py`,
> `viz/heatmap.py`, …). Under the current decisions the legacy modules **stay
> put until the new stack reaches capacity** (§15.1), and the landed model homes
> are exactly as in §4/§6. Use the table to *find* logic; take homes from §4/§6.

### 12.1 `parser.py` (446 lines)

| Symbol | Destination | Notes |
|--------|-------------|-------|
| `MeasType` | (stays here for now) | duplicate of `models.MeasType` — unify at .ADD migration |
| `ChannelFrame`, `ExtractedData` (+ helpers) | legacy `.ADD` containers | consumed by legacy rpm/viz/notebook only |
| `extract()` | (stays here) | becomes `io/dop/add.py::read` **when .ADD migrates** |
| `parse_comma_decimal`, header/stat/magic constants, `_parse_*` internals | (stays here) | move with the `.ADD` reader |
| `list_add_files`, `list_stat_add_files`, `load_all_data` | (stays here) | `.ADD`-specific listing/loading |

### 12.2 `viz.py` (249 lines)

| Symbol | Destination | Notes |
|--------|-------------|-------|
| `plot_recording`, `plot_channel_stats`, `plot_all` | future `viz/{heatmap,profile}.py` | viz deferred (last priority) |
| `discover_data_files` | **landed in `io/__init__.py`** (content-based) | top-level still re-exports this `.ADD` version — transitional |
| private helpers, `DEFAULT_OUTPUT_DIR` | future `viz/_common.py` | move with the split |

### 12.3 `analysis/rpm.py` (85 lines)

Unchanged in place for now. Optional later: port onto `ChannelSeries` /
`MultiplexedMeasurement` (rpm is currently echo-only on `ExtractedData`);
`RpmResult` may later move to `models/`. Both deferred — old code is
inspiration only.

### 12.4 `run_all.py` (113 lines)

Batch glue over `rpm_from_echo`; keep as-is until analysis ports. `plot_summary`
is a viz concern — moves with the viz split.

### 12.5 `cli.py`, `__init__.py`, `analysis/__init__.py`

- `cli.py` / `run_all.py` — untouched until the stack replaces their
  consumers.
- `__init__.py` — currently re-exports **both** the legacy surface (parser/viz
  names, incl. parser's `MeasType` and viz's `discover_data_files`) and the new
  surface (`load`, `MultiplexedMeasurement`, `ChannelSeries`, …). Whittle the
  legacy half down as the rebuild replaces it.
- `analysis/__init__.py` — unchanged.

### 12.6 Ground-up note (no import-compat promised)

Legacy *submodule paths* are not preserved; consumers are re-pointed as they
are rewritten. The only surface that matters is the rebuilt package's `__all__`.

### 12.7 Test migration

`test_models.py`/`test_io_bdd.py` land for the new layers (12+12 tests). Legacy
tests (`test_parser.py`, `test_viz.py`, `test_analysis.py`, `test_package_surface.py`)
stay green on the legacy surface until it is retired; `test_package_surface.py`
will need a rewrite for the rebuilt `__all__` when that happens.

### 12.8 Dependency direction (the key correctness constraint)

```
io ──► models ◄── process, analysis, viz
```

`models/` imports nothing from `io`/`process`/`analysis`/`viz`; everything else
imports `models`. This one-way rule is what keeps the layers swappable and
cycle-free — enforce it in review (a cheap surface test can assert it). The
landed `models/__init__.py` states exactly this rule.

### 12.9 New config artifacts

Deferred with geometry (§5) — no `data/<experiment>/layout.toml` yet.

### 12.10 Open placement decisions (ground-up)

1. `discover_data_files` home — ✅ resolved by code: `io/__init__.py`
   (content-based). The top-level re-export still points at `viz`'s `.ADD`
   version — a transitional duplication (§15.1).
2. `plot_summary` → `viz/summary.py`, or fold into a batch driver — deferred
   with viz.
3. `RpmResult` → `models/`, or leave in `analysis/rpm.py` — deferred with the
   analysis port.
4. `mean_sample_interval_s` → derive from `ChannelSeries.time_s` — deferred.
5. Split `tests/` into per-layer dirs, or keep flat — undecided; currently flat.
6. Where batch drivers (`run_*.py`) live relative to `process/pipeline.py` —
   see the CLI policy (§13).

---

## 13. CLI policy (draft rules)

The primary interfaces are the **Python API** (`src/` functions) and **marimo
notebooks** (thin interactive wrappers). CLIs are the *last* thing to add, not
the first. Draft rules (supersedes/extends the flat-era `cli.py`):

1. **Default = no CLI.** A console script is not the way to expose a function.
   Library functions are importable; notebooks wrap them interactively.
2. **Add a CLI only when BOTH hold:**
   - a **full, stable pipeline** exists (an end-to-end flow assembled from
     modules, e.g. `io.load → process.Pipeline → viz`), and
   - the run is **repeatable/batch** — over many files or experiments, from the
     shell, in CI/cron, or by non-Python users.
3. **One CLI per pipeline/driver, not per step.** Never `udv-sync`,
   `udv-resample`, `udv-heatmap`. A CLI maps to a whole pipeline or a batch
   driver (`run_*.py`), not to a module or function.
4. **CLIs are pure glue.** `argparse` + `logging` + calls into `src/`; zero
   signal-processing logic in `cli.py`. No new CLI framework (typer/click)
   unless a real need justifies it.
5. **Placement.** `[project.scripts]` in `pyproject.toml` →
   `udv_echo_process.cli.<name>_main`; keep `cli.py` (or `cli/`) the single
   argparse boundary at package top level, alongside batch drivers.
6. **Defer-until-triggered.** As of this plan there is **no full pipeline yet**,
   so **no new CLIs are added now**. The flat-era entry points (`udv-inspect`,
   `udv-viz`, `udv-run-all`) are legacy to be re-evaluated against these rules
   during the rebuild — not carried over automatically.
7. **Reproducibility without a CLI.** For repeatable-but-not-yet-stable steps,
   prefer a marimo notebook or a documented one-liner
   (`uv run python -c "…"`) / a `run_*.py` driver; promote to a CLI only once
   the pipeline is stable and genuinely reused.

**Trigger to revisit:** when the rolling-sync pipeline runs end-to-end and is
needed as a repeatable batch step across experiments — then add **one** pipeline
CLI, still per rule 3.

---

## 14. Structure rules — modules, functions, classes, models

The full rules/templates are persisted as the authoritative reference in
[`docs/pipeline-conventions.md`](pipeline-conventions.md) (agreed 2026-09-08;
Revision-2 banner: the *structural* rules are confirmed by the landed code,
the type-level templates await re-expression on the new types — §15.3). In one
line:

- **Pydantic models, not dataclasses** — models are the *nouns* (domain
  containers, `*Spec` stage params, results, source descriptors); **transforms
  are typed functions** (the verbs); **pipelines are ordered compositions**.
- **Closure rule (direction agreed, type re-expression pending)** — processing
  steps are closed over the canonical type so they chain and re-apply; per
  discussion round 1, the rebuild starts **`ChannelSeries -> ChannelSeries`**
  and uplifts to `MultiplexedMeasurement -> MultiplexedMeasurement` later.
- **Validation tiers** — full at the `io/` boundary, structural (shape/dtype)
  at model construction via `model_validator` (landed on `ChannelSeries`), none
  in inner loops.
- **Templates** — atomic transform, `Spec`-configured step, and `Pipeline`
  composition (pending re-expression, §15.3).

---

## 15. Discussion round 1 — 2026-09-08 (captured; no code, no final conventions)

### 15.1 Decisions & directions

- **Build bottom-up from `ChannelSeries`.** Implement and prove the per-channel
  transforms first; **uplift** to the `MultiplexedMeasurement` box level only
  afterwards (box steps + `Pipeline`). Rationale: the atomic unit is where the
  signal math lives; box-level orchestration is a thin, later composition.
- **`.ADD` / legacy surface: untouched until the new stack reaches capacity.**
  `parser.py`, legacy `rpm.py`/`viz.py`/`run_all.py`/`cli.py`, the notebook, and
  the transitional duplications (`MeasType` in `parser` vs `models`; two
  `discover_data_files`) all stay as they are. **Old code is inspiration only.**
  Consequences: no `io/dop/add.py` yet, no top-level `discover_data_files`
  flip, no MeasType unify — all deferred to a capacity-driven migration.
- **stat-vs-raw under sync: deferred.** `.BDD` has no stat/raw split (every
  profile carries real time), so sync only needs to define its behaviour once a
  stat-shaped source actually exists (legacy `.ADD` migration).
- **Geometry: deferred** (§5). **DOPpy integration mode: closed** — cherry-
  picked clean rewrite in `io/dop/bdd.py`, no runtime dependency.
- **Grid/alignment strategy: NOT decided here** — see §15.2.

### 15.2 Open: the sync grid & alignment experiment (discuss separately)

How the common grid is built and how lags are applied is **an experimental
question, not a paper decision**: candidates differ in whether per-channel lag
is a constant shift (round-robin idealisation), whether the grid is a uniform
overlap / channel-0 reference / union, and in endpoint policy. Plan agreed in
discussion:

1. **A marimo preview notebook** (thin wrapper; library code stays in `src/`)
   showing the *original* 4-sensor signal **and** candidate alignment
   implementations side by side, so the different strategies can be judged
   against the real data (velocity-field continuity, echo-wall coherence).
2. Consequently, the **sync primitives take grid/alignment as parameters**
   (a `*Spec`-style model), so the notebook can swap strategies without code
   churn.
3. Re-discuss **separately** once there is a live preview; lock the design from
   what the data shows.

### 15.3 Conventions & AGENTS.md status

`docs/pipeline-conventions.md` keeps its agreed structural rules; its
type-level closure rule and templates still name the pre-convergence
`Recording` type and are **pending re-expression** on `ChannelSeries` /
`MultiplexedMeasurement` (see that doc's Revision-2 banner + §10). AGENTS.md's
flat-era conventions remain placeholders; fold the settled conventions in once
`process/` lands (Stage 4). Minor cleanup then: `process/__init__.py` docstring
still says `Recording -> Recording`.
