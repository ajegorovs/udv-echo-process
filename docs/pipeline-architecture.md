# Pipeline architecture proposal — udv-echo-process

Status: **proposal** (2026-09-08, planning-only — no code changes). This revision
incorporates the 2026-09-08 planning decisions: **finer granularity (split into
sub-packages now)**, a **data-source (IO) layer** that represents *where the data
comes from*, **pandas** for the canonical dataset, and **explicit per-experiment
geometry config**. The `.BDD` binary format will be read via the sibling
**DOPpy** parser.

---

## 1. Driving use case — the rolling-sync pipeline

1. **Import + standardize** — ingest a **sequential/rolling** measurement into a
   canonical, time-indexed, per-sensor, per-gate layout (pandas-backed).
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
~25.4 ms/profile):

| Channel | Block-1 first `TBD [ms]` | Offset vs ch 6 |
|--------:|-------------------------:|---------------:|
| 6 | 0.0 | 0 |
| 7 | 111.5 | ≈ `DT` |
| 8 | 222.1 | ≈ `2·DT` |
| 9 | 333.6 | ≈ `3·DT` |

The per-channel offset `DT` must be **derived from the data** (first `TBD` of
each channel in the first block), never hard-coded — consistent with the earlier
removal of the `DT_S` magic constant (hardening §P0).

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
  model. (New this revision — see §3.)
- **`models/`** — shared Pydantic models. Single home for types → no import
  cycles, `io` and `process`/`viz` both depend on it.
- **`process/`** — pure, typed transforms (`A → B`): time-sync, resampling,
  pipeline composition, future spatial interpolation.
- **`analysis/`** — domain algorithms (RPM today; wall/pill tracking later).
- **`viz/`** — thin matplotlib wrappers, split by *what* is visualized.

**Granularity rule (finer, but still one module = one concern):** a sub-package
groups *layers*; within a layer, a module still holds **one domain concern with
a stable typed contract**, and a function is one atomic transform. The two
extremes are avoided the same way: no "one pipeline = one module" monoliths, no
per-`scipy`-call wrapper files. A *pipeline* is an explicit ordered composition
of named steps carrying no logic of its own.

---

## 3. Data-source (IO) layer

The requirement: *"there might be different data sources and we have to
implement different data parsers."* So **source = (vendor/device, format)**, and
the IO layer owns source *discovery* and *per-source parsing*.

```python
# io/base.py
class SourceFormat(str, Enum): ADD = ".ADD" ; BDD = ".BDD" ; ...

class SourceSpec(BaseModel):          # identifies where data comes from
    vendor: str                       # e.g. "Signal Processing SA"
    device: str                       # e.g. "DOP 3010"
    format: SourceFormat

class Reader(Protocol):
    def read(self, path: Path) -> ExtractedData: ...   # raw canonical frames

def load(path: Path) -> Recording: ...      # sniff source → dispatch → standardize
def register_reader(spec: SourceSpec, reader: Reader) -> None: ...
```

- **Sniffing is content-based, not extension-based** (the repo already does this
  for `.ADD` via the `ASCUDOPV` magic line): `load()` sniffs the magic, picks
  the registered reader, and returns the standardized `Recording`.
- **Adding a new device = `register_reader(...)`, not editing a dispatch
  `if/elif`.** Downstream (`process`/`analysis`/`viz`) is untouched.

**Current source — Signal Processing SA, DOP 3010 (DOP-series).** Assumption to
validate: *all DOP-series devices emit the same data layout*, so `.ADD` and
`.BDD` are two formats of one source family and map onto the same
`ExtractedData`/`Recording`.

```
io/dop/
├── __init__.py   # registers the DOP-family readers under one SourceSpec
├── add.py        # .ADD ASCII reader  → ExtractedData   [≈ today's parser.py logic]
└── bdd.py        # .BDD binary reader → ExtractedData   [DOPpy-backed — future]
```

- `add.py`: today's `parser.py` logic moves here; the models it returns move to
  `models/raw.py`.
- `bdd.py`: uses the sibling **DOPpy** parser. Per AGENTS.md, **cherry-pick**
  the reader rather than vendoring it (NumPy-2 breakage, no packaging; see
  `docs/doppy-analysis.md`). `.BDD` also carries metadata `.ADD` drops (PRF,
  burst length, TGC, sound speed, Doppler angle, filter settings, trigger state)
  and interleaved velocity+echo profiles.
- A genuinely *different* vendor/device later → `io/<other>/` with its own
  parser, still emitting the same canonical model.

`discover_data_files()` (currently in `viz.py`) moves here: discovery is about
finding valid *source* files, not plotting.

---

## 4. Canonical dataset (models layer, pandas-backed)

Decision: **pandas** backs the standardized layout; the repo is currently
pandas-free, so this adds a dependency. The canonical **store** is **one 2D
series per sensor, each carrying its own timestamps** — *not* one merged N-D
array. This keeps interpolation and retrieval per-sensor (each sensor is
interpolated against its own `time_s`, and read back as
`recording.sensors[ch]`); any cross-sensor merge is a *derived view*, never the
store of record.

- **Keep** `models/raw.py` = the *raw* layer (`MeasType`, `ChannelFrame`,
  `ExtractedData`) — the contract every reader emits.
- **Add** `models/dataset.py` = the *standardized* layer:

```python
class SensorSeries(BaseModel):      # one sensor's own 2D series
    channel: int
    gate_depths_mm: list[float]     # per-gate measurement-line positions
    time_s: np.ndarray              # (T,) this sensor's OWN timestamps (s)
    values: np.ndarray              # (T, G)  T profiles × G gates

class Recording(BaseModel):         # the whole standardized measurement
    file_path: Path
    meas_type: MeasType
    source: SourceSpec
    layout: Layout                  # from models/geometry.py
    sensors: list[SensorSeries]     # primary store: per-sensor 2D series

    @classmethod
    def from_extracted(cls, d, source, layout) -> Recording: ...
    def common_time_s(self) -> np.ndarray | None: ...  # derived, post-sync
    def to_pandas(self) -> pd.DataFrame: ...   # derived tidy long form (optional)
    def to_wide(self) -> pd.DataFrame: ...     # derived wide (channel, gate) view
```

- **Storage vs views.** Each `SensorSeries` is self-contained (own `time_s` +
  `(T, G)` `values`). Before sync, `time_s` is the sensor's native timestamps;
  after sync, it is the sensor's shifted/interpolated timestamps on the common
  grid. `common_time_s()`, `to_pandas()`, `to_wide()` are *derived*
  conveniences that merge across sensors — handy for one plot or a wide table,
  but never the store.

---

## 5. Geometry (explicit per-experiment config)

Decision: **explicit config**, not free-text parsing of `comments.txt` (which
says things like "order dont remember"). Proposed: `data/<experiment>/layout.toml`
describing each channel's pose (position, measurement-axis direction, gate
spacing, probe diameter), so `models/geometry.py` (`SensorPose`, `Layout`) loads
it deterministically. `comments.txt` remains a human-readable note, not an input.

---

## 6. Target layout

```
src/udv_echo_process/
├── __init__.py            # public re-exports (keep the parity discipline)
│
├── io/                    # ── data-source layer ──────────────────────────
│   ├── __init__.py        #   load()/sniff() dispatch, discover_data_files()
│   ├── base.py            #   SourceFormat, SourceSpec, Reader, register_reader
│   └── dop/               #   Signal Processing SA — DOP-series (DOP 3010 today)
│       ├── __init__.py    #     registers DOP readers (one source family)
│       ├── add.py         #     .ADD ASCII  → ExtractedData   [≈ parser.py]
│       └── bdd.py         #     .BDD binary → ExtractedData   [DOPpy; future]
│
├── models/                # ── shared Pydantic models ─────────────────────
│   ├── __init__.py
│   ├── raw.py             #   MeasType, ChannelFrame, ExtractedData  [from parser.py]
│   ├── dataset.py         #   SensorSeries, Recording (+ to_pandas/to_wide)
│   └── geometry.py        #   SensorPose, Layout
│
├── process/               # ── pure, typed transforms ─────────────────────
│   ├── __init__.py
│   ├── sync.py            #   estimate_channel_offsets / shift / resample_common_grid
│   ├── pipeline.py        #   Pipeline = ordered named steps; run()
│   └── spatial.py         #   [future] spatial interpolation across sensors
│
├── analysis/              # ── domain algorithms ──────────────────────────
│   ├── __init__.py
│   └── rpm.py             #   existing (unchanged contract)
│
├── viz/                   # ── thin matplotlib wrappers ───────────────────
│   ├── __init__.py
│   ├── heatmap.py         #   per-sensor time×gate heatmaps  [≈ plot_recording]
│   ├── profile.py         #   gate profiles mean±std         [≈ plot_channel_stats]
│   └── lines.py           #   measurement-line cross-sections [geometry-aware]
│
├── run_all.py             # batch drivers
└── cli.py                 # entry points

data/<experiment>/layout.toml     # explicit sensor geometry per experiment
```

---

## 7. Deconstruction map (does it generalise to other tasks?)

| Module | Contract | Reused by |
|--------|----------|-----------|
| `io/base.py` + `io/dop/*` | source → `ExtractedData` → `Recording` | `.ADD` today; `.BDD` via DOPpy; future vendors |
| `models/raw.py` | raw frame types | every reader |
| `models/dataset.py` | standardized `Recording` + pandas | rolling-sync, single/multi-channel RPM, velocity-RPM, wall/pill tracking, future `.BDD` |
| `models/geometry.py` | `Layout` + world positions | sync order/offsets, `viz/lines.py`, spatial interpolation, wall/pill tracking |
| `process/sync.py` | `Recording` → time-aligned `Recording` | any rolling array (velocity **and** echo); feeds spatial |
| `process/pipeline.py` | ordered steps → result | every mini-pipeline; replaces ad-hoc drivers |
| `viz/heatmap.py`, `viz/profile.py` | `Recording` → figs | existing single/multi-sensor views |
| `viz/lines.py` | `Recording` + `Layout` → figs | rolling-sync step 3(b); wall/pill visualization |
| `analysis/spatial.py` | aligned `Recording` + `Layout` → 2D field | future step 4 |

No new module is rolling-sync-specific — the "does the deconstruction map to
other tasks" test passes.

---

## 8. End-to-end walkthrough (rolling-sync)

```
io.load(file)                         # sniff source → io/dop/add.read() → ExtractedData
  → Recording.from_extracted(...)     # models/dataset.py  (standardized)
  → Pipeline([                        # process/pipeline.py
        estimate_channel_offsets,     # process/sync.py  (DT, 2·DT, … from first block)
        shift_channels,               # process/sync.py  (sensor k → t − k·DT)
        resample_common_grid,         # process/sync.py  (per-sensor interpolation)
    ])
  → viz.heatmap.plot_recording(...)   # per-sensor time×gate
  → viz.lines.plot_measurement_lines(...)  # spatial cross-section @ time t
```

---

## 9. Granularity guardrails

- **Sub-packages** group *layers* (io / models / process / analysis / viz) —
  this is now the deliberate structure, not a future split.
- **Within a layer**, a module = one domain concern; merge a transform into its
  module when it shares the module's contract and is used together with its
  siblings (e.g. the three sync functions stay one module).
- **Split** a module only when it mixes unrelated concerns, crosses ~400–500
  lines, or a second pipeline reuses only a subset of its primitives.
- A module is justified only when it adds domain semantics on top of an import
  (e.g. `models/dataset.py` pins the canonical contract + metadata — it is not a
  pandas wrapper). Never wrap a bare `numpy`/`scipy`/`matplotlib` call.

> Note: this supersedes AGENTS.md's "keep modules flat / no pre-emptive
> sub-packages" guidance for *this* pipeline work — AGENTS.md should be updated
> to match when implementation starts.

---

## 10. Open decisions

**Resolved (2026-09-08):** sub-packages now · pandas backend · explicit geometry
config · dedicated IO/source layer with DOP 3010 + DOPpy `.BDD` · **per-sensor
2D series with own timestamps** as the canonical store (no single merged array).

**Still open:**
1. **stat vs raw under sync** — raw has cumulative `TBD` (real times); stat
   stores a per-block constant. Sync is only meaningful for raw; decide whether
   `sync` raises on stat or aligns by block index.
2. **DOP-family layout assumption** — confirm `.ADD` and DOPpy-decoded `.BDD`
   share the same `ExtractedData` mapping (the DOPpy cross-check, agenda §1).
3. **DOPpy integration mode** — cherry-pick vs runtime dependency (AGENTS.md
   leans cherry-pick; NumPy-2 breakage, no packaging).

---

## 11. Staged rollout

1. Restructure: `io/` + `models/` (+ pandas dep, `layout.toml` for the two
   committed multi-sensor experiments, tests migrated from `parser.py`/`viz.py`).
2. `process/sync.py` (offset + shift + resample) + tests on
   `data/4-sensor-velocity/200RPM_v2.ADD` (raw rolling) and
   `data/echo-4-sensors-2x2/300RPM.ADD` (stat — per §10.2).
3. `process/pipeline.py` + `viz/lines.py`; wire `__init__.py` + a thin marimo
   notebook wrapper.
4. *(future)* `io/dop/bdd.py` (DOPpy) + `analysis/spatial.py`.

---

## 12. Migration map — current scripts → new structure

Review of every current module (done 2026-09-08, symbol-level).

> **Ground-up stance.** This is a **reference for where old code lives**, not a
> preservation plan: the rebuild is ground-up, with the current implementation
> as *inspiration*. Nothing below implies keeping import paths, module objects,
> or public names — the map just tells you where to look for the logic to adapt.

### 12.1 `parser.py` (446 lines)

| Symbol | Destination | Notes |
|--------|-------------|-------|
| `MeasType` | `models/raw.py` | unchanged |
| `ChannelFrame` | `models/raw.py` | unchanged |
| `ExtractedData` (+ `by_channel`/`by_block`/`describe`/`meas_type`) | `models/raw.py` | unchanged contract |
| `parse_comma_decimal` | `io/dop/add.py` | DOP ASCII comma-decimal helper |
| `extract()` | `io/dop/add.py` | becomes the DOP `.ADD` reader; `io.load()` dispatches to it |
| `GATE_DEPTH_HEADER` / `STAT_PREFIX` / `MAGIC_PREFIX` | `io/dop/add.py` | magic also feeds `io` sniffing |
| `_detect_meas_type`, `_parse_gate_depths`, `_parse_num`, `_parse_section`, `_add_frame`, `_parse_stat_section`, `_parse_stat_row`, `_detect_n_profiles` | `io/dop/add.py` | internal, unchanged |
| `list_add_files`, `list_stat_add_files`, `load_all_data` | `io/dop/__init__.py` (or `add.py`) | `.ADD`-specific listing/loading |
| `parse_add_file`, `parse_stat_add_file` | drop, or keep as thin aliases in `io/dop/add.py` | back-compat shims — see §12.6 |

### 12.2 `viz.py` (249 lines)

| Symbol | Destination | Notes |
|--------|-------------|-------|
| `plot_recording` | `viz/heatmap.py` | per-sensor time×gate heatmaps |
| `plot_channel_stats` | `viz/profile.py` | gate profiles mean±std |
| `plot_all` | `viz/__init__.py` | convenience: both in one call |
| `DEFAULT_OUTPUT_DIR` | `viz/_common.py` | |
| `_channel_time_axis`, `_output_path`, `_figure_for_channels`, `_hide_unused_axes`, `_finish_figure`, `_subplot_layout` | `viz/_common.py` (private) | shared by heatmap + profile |
| `discover_data_files` | `io/__init__.py` (or `io/base.py`) | discovery is source-finding, not plotting |

### 12.3 `analysis/rpm.py` (85 lines)

Unchanged in place (`RpmResult`, `mean_sample_interval_s`, `rpm_from_echo`,
`setpoint_rpm_from_stem`). Optional later: `RpmResult` → `models/`; not required
now. `mean_sample_interval_s` currently derives from `ExtractedData` — can later
read `SensorSeries.time_s`, but that is a refactor, not part of the move.

### 12.4 `run_all.py` (113 lines)

| Symbol | Destination | Notes |
|--------|-------------|-------|
| `plot_summary` | `viz/summary.py` (optional) | it's a viz concern (scatter + error bars) |
| `collect_results` | keep in `run_all.py` | batch glue over `rpm_from_echo` |
| `main` | keep in `run_all.py` | CLI driver |

### 12.5 `cli.py`, `__init__.py`, `analysis/__init__.py`

- `cli.py` — **import updates only** (`extract` from `io`, `plot_all` /
  `discover_data_files` from new homes, `DEFAULT_OUTPUT_DIR` from `viz`).
- `__init__.py` — re-export from the new sub-packages but **keep the same public
  names** so `from udv_echo_process import extract, ExtractedData, plot_all,
  rpm_from_echo, …` and the notebook stay working.
- `analysis/__init__.py` — unchanged.

### 12.6 Ground-up note (no import-compat promised)

The old `parser.py`/`viz.py` *submodule paths* (`udv_echo_process.parser`,
`udv_echo_process.viz`) are **not** preserved — the rebuild re-homes them and
consumers (`cli.py`, `run_all.py`, tests, the notebook) are re-pointed as they
are rewritten. Public names can change too; the only surface that matters is
whatever new top-level `__all__` we choose for the rebuilt package.

### 12.7 Test migration

- `test_parser.py` — behavior unchanged (imports top-level names). Optionally
  split to mirror the packages (`tests/io/`, `tests/models/`, …); not required.
- `test_viz.py` — update `from udv_echo_process.viz import discover_data_files`
  → `from udv_echo_process.io import discover_data_files`.
- `test_package_surface.py` — **rewrite** for the new surface: top-level ↔
  `io`/`models`/`process`/`analysis`/`viz` parity instead of `parser`/`viz`
  module objects.
- `test_analysis.py` — unchanged (`analysis.rpm` and `run_all` paths survive).

### 12.8 Dependency direction (the key correctness constraint)

```
io ──► models ◄── process, analysis, viz
```

`models/` imports nothing from `io`/`process`/`analysis`/`viz`; everything else
imports `models`. This one-way rule is what keeps the layers swappable and
cycle-free — enforce it in review (a cheap surface test can assert it).

### 12.9 New config artifacts

- `data/4-sensor-velocity/layout.toml` — 4 sensors, 10 mm centers (from
  `comments (1).txt`).
- `data/echo-4-sensors-2x2/layout.toml` — 4 sensors (2×2), 20 mm centers,
  pointing at mixer pill, sensor bottom 3 mm from vessel bottom, d=8 mm.

### 12.10 Open placement decisions (ground-up)

1. `discover_data_files` home: `io/__init__.py` vs `io/base.py`.
2. `plot_summary` → `viz/summary.py`, or fold into a batch driver.
3. `RpmResult` → `models/`, or leave in `analysis/rpm.py`.
4. `mean_sample_interval_s` → derive from `SensorSeries.time_s` (defer).
5. Split `tests/` into per-layer dirs, or keep flat.
6. Where batch drivers (`run_*.py`) live relative to `process/pipeline.py` —
   see the CLI policy (§13).

*(Back-compat aliases and `parser.py`/`viz.py` shims are deliberately not listed:
under the ground-up stance there is nothing to preserve.)*

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

**Trigger to revisit:** when the rolling-sync `Pipeline` runs end-to-end and is
needed as a repeatable batch step across experiments — then add **one** pipeline
CLI (e.g. `udv-run-pipeline`), still per rule 3.

---

## 14. Structure rules — modules, functions, classes, models

The full rules/templates are persisted as the authoritative reference in
[`docs/pipeline-conventions.md`](pipeline-conventions.md) (agreed 2026-09-08) —
consult it before adding any module. In one line:

- **Pydantic models, not dataclasses** — models are the *nouns* (domain
  containers, `*Spec` stage params, results, source descriptors); **transforms
  are typed functions** (the verbs); **pipelines are ordered compositions**.
- **Closure rule** — processing steps are `Recording -> Recording`, so they
  chain and re-apply (interpolation → re-interpolation = apply the step twice);
  terminal `Recording -> U` stages live in `analysis/`.
- **Validation tiers** — full at the `io/` boundary, structural (shape/dtype)
  at stage entry via `model_validator`, none in inner loops.
- **Templates** — atomic transform, `Spec`-configured step, and `Pipeline`
  composition.
