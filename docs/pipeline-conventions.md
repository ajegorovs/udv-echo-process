# Pipeline & module conventions — udv-echo-process

Status: **agreed 2026-09-08 · authoritative for the ground-up rebuild.**
Consult this before adding any module, function, class, or model once the
`io/` / `models/` / `process/` / `analysis/` / `viz/` layers are built. These
rules refine (and where they conflict, supersede) the flat-era AGENTS.md
conventions, which are placeholders until this repo has evolved enough to draw
practical conclusions.

> ## Revision 2 — 2026-09-08 (Stage 1–2 landed + discussion round 1)
>
> Stage 1–2 of the rebuild **landed after this text was agreed** (commit
> `f2482f2`): `models/` + `io/` + the DOP3000/3010 `.BDD` reader, 58 tests.
> The **converged type names differ from the examples below**: the canonical
> unit is **`ChannelSeries`** (own real `time_s`, `(T,G)` values, nested
> `ChannelConfig`) composed into a **`MultiplexedMeasurement`** box. There is
> **no `Recording`/`SensorSeries` model** and no `models/raw.py`+`dataset.py`
> split — the model layer is `base.py` (`Model` base + `shape_2d`), `io.py`
> (`MeasType`/`SourceFormat`/`SourceSpec`, the latter frozen), `channel_config.py`,
> `channel_series.py`, `measurement.py`.
>
> What this revision changes here:
> - **§§1–3, §5, §7–8 (structural rules) are confirmed by the landed code**:
>   Pydantic-not-dataclass (`models.base.Model` carries
>   `arbitrary_types_allowed` for numpy fields); frozen `SourceSpec` keys the
>   reader registry; the T2 shape/time invariants of §5 are implemented as a
>   `model_validator` on `ChannelSeries`; no dataclasses anywhere.
> - **The type-level closure rule (§4) and templates (§6) still name the
>   pre-convergence `Recording` type and are NOT yet re-expressed or
>   ratified** on the new types — treat them as illustrations of *shape*
>   (pure transform, `Spec` params, ordered composition), not of type names.
>   Re-expression is pending the sync-design discussion
>   (`pipeline-architecture.md` §15.2) — see §10 below.
> - **Discussion round 1 outcomes** (ChannelSeries-first build, legacy surface
>   untouched, deferrals) are captured in §10.

---

## 1. Dataclasses vs Pydantic: **Pydantic, not dataclasses**

- **Data structures are Pydantic models; behaviour is functions.**
- Dataclasses add nothing Pydantic doesn't already give (runtime validation,
  coercion, `model_dump`/JSON, forward refs) — so do not introduce them.
- Fixed sets use `Enum`.
- If a genuinely validation-free value object is ever needed, use a
  `NamedTuple`, not a dataclass — and keep even those rare.

## 2. Three kinds of thing (and which file they live in)

| Kind | What | Examples | File |
|------|------|----------|------|
| **Data model** (Pydantic) | the nouns — input/output/config/result | `Recording`, `SensorSeries`, `ResampleSpec`, `RpmResult`, `Layout`, `SourceSpec` | `models/` |
| **Transform** (plain typed function) | the verbs — `T -> T` steps | `resample_to_common_grid`, `shift_channels` | `process/` |
| **Pipeline** (ordered composition) | the sentences | `Pipeline.run` | `process/pipeline.py` |

One module = one concern, and may hold a model *plus* the functions that act on
it (e.g. `models/geometry.py` holds `Layout` + its world-position helpers;
`process/sync.py` holds `SyncSpec` + the sync transforms). Split a module when it
mixes unrelated concerns or crosses ~400–500 lines.

## 3. Where models are used — four roles

1. **Domain containers** — data carried through the pipeline (`Recording`,
   `SensorSeries`, `ExtractedData`, `Layout`).
2. **Stage parameters** — validated config for one transform, with defaults and
   a `Spec` suffix (`ResampleSpec`, `SyncSpec`).
3. **Results** — terminal outputs (`RpmResult`).
4. **Source descriptors** — where data came from (`SourceSpec`, `SourceFormat`).

**Not** models: raw numpy arrays inside a hot loop, and throwaway internal
pairings — those stay `np.ndarray` / `tuple` / scalar.

## 4. The closure rule (interpolation, re-interpolation, …)

A processing step is typed **`Recording -> Recording`** (closed over the
canonical type). Because every step returns the *same* model it consumed, steps
chain arbitrarily and re-apply safely:

```python
r2 = resample_to_common_grid(r, ResampleSpec(dt_s=0.001))    # interpolate
r3 = resample_to_common_grid(r2, ResampleSpec(dt_s=0.0005))  # re-interpolate — legal
```

Interpolation → re-interpolation is just applying the transform twice; the
output is a valid `Recording` again, so the next step's input validation holds.

**Consequence: do not invent a new model per stage.** The universal intermediate
is `Recording`; per-stage *parameters* are models, per-stage *output* is the
same `Recording`.

**Terminal stages** are the exception, typed `T -> U` (`Recording -> RpmResult`,
`Recording -> Field`): they *end* a pipeline rather than sitting in the middle.
Keep them in `analysis/`, called explicitly — never mixed into a
`Recording -> Recording` pipeline.

## 5. Validation tiers (validate at boundaries, trust inside)

- **T1 — untrusted boundary (`io/`).** Full validation: magic/content sniffing,
  dtype, shapes, value ranges, cross-field consistency. Bad files or bad
  hand-built models are rejected here.
- **T2 — stage entry (cheap, structural).** Model construction enforces types
  and (via a `model_validator`) shape consistency — e.g. `SensorSeries` asserts
  `values.shape == (len(time_s), len(gate_depths_mm))`. No re-scan of elements.
- **T3 — inner loop.** Raw numpy, zero per-call validation; correctness comes
  from the stage's unit tests.

Rule of thumb: heavy validation lives in `io/` and in the `model_validator`s of
domain models; transform bodies do **not** re-validate — they rely on the type
contract.

## 6. Templates

### 6.1 Atomic transform (a function)

```python
# process/sync.py
from __future__ import annotations
from udv_echo_process.models.dataset import Recording

def estimate_channel_offsets(recording: Recording) -> dict[int, float]:
    """Channel -> time offset (s), from each sensor's first timestamp.

    Args:
        recording: standardized rolling measurement.

    Returns:
        Offset in seconds per channel (channel-0 sensor = 0.0). Derived from
        the data (first TBD of each channel in the first block), never
        hard-coded.
    """
    ...
```

### 6.2 Configured step (params model + function)

> **Interpolation note (2026-09-09):** the interpolation stage is now designed —
> see `docs/interpolation-design.md` §7. There, `method` is a constrained `Enum`
> (`InterpMethod`), not a bare `str`, and the spec carries explicit
> `extrapolation` / `nan_policy` fields. The example below is illustrative of
> *shape* only (its types still name pre-convergence `Recording`).

```python
from pydantic import BaseModel
from udv_echo_process.models.dataset import Recording

class ResampleSpec(BaseModel):
    """Parameters for resampling every sensor onto a common time grid."""
    dt_s: float | None = None    # target spacing; None = keep native step
    method: str = "linear"       # interpolation method passed to numpy/scipy
    grid: str = "union"          # "union" | "uniform" | "reference"

def resample_to_common_grid(recording: Recording, spec: ResampleSpec) -> Recording:
    """Resample each SensorSeries onto one shared time grid.

    Returns a new Recording whose sensors all share common_time_s(). Pure: does
    not mutate the input. Re-applying with the same grid is idempotent.
    """
    ...
```

Prefer a **plain function + a `Spec` model** over a callable object; a `Step`
class is warranted only when a transform needs a stable name/identity for a
registry or introspection — and then it is a small class, not a dataclass.

### 6.3 Pipeline (composition)

```python
# process/pipeline.py
from collections.abc import Callable
from udv_echo_process.models.dataset import Recording

Step = Callable[[Recording], Recording]

class Pipeline:
    """Ordered composition of Recording -> Recording steps. No logic of its own."""

    def __init__(self, steps: list[tuple[str, Step]]) -> None:
        self.steps = steps

    def run(self, recording: Recording) -> Recording:
        for _name, step in self.steps:
            recording = step(recording)
        return recording
```

Each step is pure and returns a *new* `Recording` (no in-place mutation), so a
pipeline is trivially re-runnable and its steps individually testable. Terminal
`T -> U` stages (`analysis/`) are called separately, not placed in a
`Recording -> Recording` pipeline.

## 7. Naming & typing

- Functions/transforms: `snake_case` **verbs** (`resample_to_common_grid`,
  `shift_channels`, `estimate_channel_offsets`).
- Models: `PascalCase` nouns; **`Spec` suffix** for stage parameters
  (`ResampleSpec`, `SyncSpec`); result models named for the result (`RpmResult`).
- Enums: `PascalCase` (`MeasType`, `SourceFormat`).
- `from __future__ import annotations` at top; full type hints on all public
  functions; docstring states the contract (`Args` / `Returns` / side-effects /
  what it validates).

## 8. Testing each element

- **Domain models:** construct from valid + invalid inputs; assert validation
  errors (T1/T2). Lock shape/dtype rules.
- **Transforms:** synthetic tiny arrays (fast, exact) **and** the committed
  `data/` fixtures (real formats). Assert the output *re-validates* as a
  `Recording`, is a *new* object (input unmutated), and — where meaningful —
  idempotency/round-trip (resample twice with the same grid ≈ once).
- **Pipelines:** a step-list runs in order and returns a valid `Recording`;
  reorder/replace a step without code changes.

## 9. Relationship to AGENTS.md

This doc is the authoritative statement of module/function/class structure for
the rebuild. AGENTS.md remains the (placeholder) flat-era conventions; once the
`models/` + `process/` layers land, fold this doc's rules into AGENTS.md and
retire this file or keep it as the detailed appendix.

## 10. Revision 2 — landed-code notes & discussion round 1 (2026-09-08)

Companion to `docs/pipeline-architecture.md` §15 (which carries the full
discussion record). Capture only — the banner above is authoritative about
what is confirmed vs pending.

**Confirmed by landed code (Stage 1–2, commit `f2482f2`):** the structural
rules of this doc. Concrete anchors: `models/base.py::Model` = the numpy-
capable `BaseModel` base every domain model subclasses; `shape_2d()` is the
shared T2 helper; `models/io.py::SourceSpec` is `frozen=True` precisely so it
keys the `io.base` reader registry (the §3 "source descriptor" role); the §5
"cheap, structural validation at construction" tier is implemented as a
`model_validator(mode="after")` on `ChannelSeries` (shape + monotonic-time);
`MultiplexedMeasurement.channels` is an ordered `list` (round-robin order is
data), with `.by_channel()` as the derived dict view.

**Pending re-expression (do not copy §§2/4/6 examples as final):** the closure
rule and templates still say `Recording -> Recording` / `SensorSeries` /
`ResampleSpec`. Once the sync-design discussion
(`pipeline-architecture.md` §15.2) concludes, re-express on
`ChannelSeries`/`MultiplexedMeasurement`, update §2's example table, then fold
into AGENTS.md (per §9).

**Round-1 discussion outcomes (2026-09-08):**
- Build sync **bottom-up from `ChannelSeries`** (per-channel transforms first,
  tests + marimo preview), **uplift** to `MultiplexedMeasurement`-level steps
  and `Pipeline` afterwards.
- **`.ADD`/legacy surface untouched until the new stack reaches capacity** —
  `parser.py`, legacy rpm/viz/run_all/cli and the transitional duplications
  (`parser.MeasType` vs `models.MeasType`; viz's vs `io`'s
  `discover_data_files`) all stay; old code is inspiration only.
- **stat-vs-raw under sync: deferred** (`.BDD` has no stat/raw split).
- **Sync grid/alignment strategy: an experiment, not a paper decision** — marimo
  preview notebook comparing candidate implementations on the real signal;
  sync primitives therefore take grid/alignment **as a `Spec`** so strategies
  swap without code churn. Discuss separately.
- **Geometry (`layout.toml`): deferred.** **DOPpy mode: closed** (cherry-picked
  clean rewrite in `io/dop/bdd.py`, no runtime dep).
