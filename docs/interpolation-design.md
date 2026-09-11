# Channel-signal interpolation & resampling — grounding + design state

> **Superseded — 2026-09-11 (signal-model rework, Phase 9).** The interpolation
> layer was re-expressed on the bundle-closed model. The landed API is
> `process/sync.py::resample(bundle: ChannelBundle, spec: InterpSpec, *, times |
> dt_s) -> ChannelBundle`, with the discriminated `InterpSpec` union in
> `process/specs.py` (`LinearInterpSpec` / `MonotoneInterpSpec` /
> `CubicInterpSpec` / `BsplineInterpSpec`). **`InterpMethod`, the bundled
> `InterpParams` and the `nan_policy` field were RETIRED (plan §14)** — validity
> is now carried by `SignalData.support`, and `extrapolation` is
> `"error" | "missing" | "nearest"` (`"missing"` replaces the old `"nan"`
> spelling). The `dt_s` grid is now **exactly uniform** (ruling D6): the §8
> "inclusive span / shortened final interval" rule is retired. Everything below
> (§1–§8) is a **historical design record**; the rework plan §7.3 and the landed
> modules are authoritative.

Status: **decisions landed and implemented, 2026-09-09.** §7 records the
settled interpolation design; **§8 records the implementation-level
clarifications** agreed at the start of the implementation session. The Stage 3
implementation landed the same day in `process/sync.py` (`InterpMethod`,
`InterpParams`, `InterpSpec`, `resample`) with its §7/§8 test set — 45 tests,
full suite + ruff green. Docs checkpoints: `2ce6671` (design), `d5db721`
(clarifications).

This note persists the grounding obtained so far for the interpolation /
resampling stage of the pipeline rebuild (architecture
[`pipeline-architecture.md`](pipeline-architecture.md) Stage 3,
`process/sync.py`), so later work stays anchored in *what the data actually
is*. It feeds the interpolation-layer brainstorm (issue b below); nothing
here is a final convention yet.

Domain authority:
[`dop3000/measurements-and-recordings.md`](dop3000/measurements-and-recordings.md)
(the instrument explainer). All numbers below were re-verified on the
committed fixtures on this date via `io.load()`.

---

## 1. What a measurement is (grounding)

**Single-sensor recording** — one transducer, one acoustic chain:
profiles are emitted continuously at the channel's own cadence. A **velocity
profile is a statistical estimate**: the instrument combines ~`N_PRF`
successive emissions (auto-correlation of the Doppler signal) into one value
per gate, so a velocity profile carries inherent temporal smoothing at roughly
the profile-cadence scale. An **echo profile** is closer to a per-emission
snapshot. File-wise: one row = one profile, one column per gate.

**Multiplexed recording (blocks/rounds)** — one instrument, several probes,
relays: it can only measure *one probe at a time*, so it time-shares:

1. visit channel *k*, acquire **N consecutive profiles** (the channel's own
   parameters, own cadence);
2. switch (sub-ms relay) to the next enabled channel, acquire its N profiles;
3. one complete pass over all enabled channels = a **sequence / round**; in
   multiplexed mode **one block = one round** (all channels' profiles for that
   round).

So per (block, channel) the file holds N consecutive profiles; across blocks a
channel is revisited every round period. In the canonical model each channel is
one `ChannelSeries` whose `time_s`/`values` flatten its blocks in time order —
the per-channel series is therefore *bursty*, but only because the other
channels are being measured during the "gaps".

**`.ADD` vs `.BDD`:** same profiles; `.BDD` keeps raw values + full per-channel
instrument parameters (PRF, gates, TGC, sound speed, …); `.ADD` is the
calibrated, parameter-less export.

## 2. Verified fixture facts (2026-09-09)

`data/4-sensor-velocity/200RPM.BDD` (velocity, multiplexed, channels 6–9):

| Fact | Value |
|------|-------|
| Rounds (blocks) | 100 |
| Profiles per channel per round (visit) | **4** (N=4) |
| Profiles per channel total | 400 |
| Intra-visit profile cadence | **25.4 ms** (very stable, ~25.3–25.4) |
| Channel revisit period | **~448 ms** (inter-visit gap ≈ 364–373 ms) |
| Per-channel stagger within a round | ch7 ≈ +112 ms, ch8 ≈ +224 ms, ch9 ≈ +336 ms |
| Per-round lag stability | medians 111.6 / 223.1 / 334.6 ms; jitter σ ≤ 1.6 ms, \|residual\| ≤ 6.5 ms, **no drift** first vs second half |
| Gates | 55, depths 20.00 → 79.13 mm, identical across channels |
| Values | velocity mm/s; range −54.6 … +245.9 (config `velo_max` ±152.05 → **aliasing present**) |

`data/echo/650.BDD` (echo, single channel 4):

| Fact | Value |
|------|-------|
| Profiles | 4630, **uniform 3.2 ms** cadence (no gaps) |
| Gates | 26, depths 43.00 → 54.4 mm |

Same structure in the `.ADD` twins (`200RPM_v2.ADD`: 400 `Gate Depth` sections
= 100 blocks × 4 channels; TBD column shows the 25.4 ms intra-visit cadence and
the ~112 ms channel stagger; trailing columns = `TBD, No block, Channel`).

## 3. Consequences for the pipeline

- **The object is the per-sensor time series across all blocks.** Collecting
  "all measurements from each sensor, from all blocks into one time series"
  is exactly what `ChannelSeries` already is (the reader flattened the blocks);
  interpolation then operates on that series. Round structure is *data
  semantics* needed for alignment later, not a different product.
- **Temporal resolution is set by the revisit cadence, and is time-varying
  along the series.** Inside a visit: ~40 Hz local samples (4 × 25.4 ms);
  between visits (~448 ms apart) only the slow component of the signal is
  recoverable. Events with period smaller than the revisit cadence cannot be
  reconstructed — an acquisition-level limit the user can tune by changing the
  number of profiles per visit (fewer/shorter visits → shorter rounds → faster
  revisit). Post-hoc interpolation cannot beat this; it must only be honest
  about it (consumers doing spectral work should know where values are bridged
  vs measured).
- **The multiplex stagger is a near-constant per-channel offset**, not a
  drift: per-round lag is stable to ≤ ~6.5 ms across all 100 rounds. A
  constant shift (offset derived from data) is therefore a good alignment
  model; per-round refinement is a possible later refinement, not a
  prerequisite.
- **Velocity profiles are pre-smoothed** (statistical estimate over
  ~N_PRF emissions): the estimator is the low-pass; interpolation need not
  (and cannot) out-resolve the profile cadence.
- **Correction recorded (2026-09-09):** earlier discussion suggested treating
  the round as the sync atom and refusing to interpolate across inter-visit
  gaps ("never bridge"). Per the task as agreed below, the deliverable is a
  continuous per-sensor series reconstructed as-if-simultaneous, so bridging
  across gaps is the *point* (reconstructing the resolvable component), not a
  defect. Hole-marking stays useful as an *option* for frequency-domain
  consumers, not the default.
- **Heads-up for the alignment stage (not now):** cross-correlating two
  *whole-series* envelopes to estimate lag has a **one-round (~448 ms)
  ambiguity** (both series' burst patterns are round-periodic). Alignment must
  use matched rounds (per-round reference times or explicit round identity in
  the model), not the flat series.

## 4. Task decomposition (settled direction)

1. **Per-sensor interpolation** (this stage's core): from one `ChannelSeries`
   (all blocks, real `time_s`) produce a pre-calculated **interpolation
   model** — function/parameters + argument (time) bounds — that can be
   sampled at arbitrary time values afterwards. Method is *swappable*
   (linear, cubic, spline/Bezier, …), i.e. an interpolation **layer/module**,
   not a hard-coded `np.interp` call.
2. **Sampling downstream** uses that model: any time values / time series,
   within or (explicitly) beyond the argument bounds.
3. **Re-interpolation happens only in two places**: (a) a notebook, to assess
   interpolation quality against the original signal; (b) **sensor
   re-alignment**, where the sampling bounds are the extremes of the
   time-overlap of all channel series. Alignment strategy itself stays a
   later, separate stage.

Open questions of the *common-grid* kind (uniform dt vs reference grid vs …)
largely fall away under this framing: a common grid is just one particular
sampling of the per-sensor models.

## 5. Requirements carried into the brainstorm (issue b)

As stated by the user, to be designed in discussion (not settled here):

- interpolation as a **module/block** with swappable method — linear → cubic →
  bezier/splines;
- **strong interpolation implementation** (e.g. build on `scipy`) — note:
  scipy is **not currently a dependency** of this package (runtime deps:
  numpy, matplotlib, pydantic, marimo, plotly); adding it is a decision;
- model output = interpolation model (parameters + argument bounds);
  downstream samples the pre-calculated function, extrapolation possible but
  explicit;
- concerns: where the layer lives (`process/`), the model shape
  (`ChannelSeries -> interp model -> sampled series`), per-gate 1-D vs 2-D
  handling, dtype/bounds/extrapolation semantics, tests (echo fixture =
  uniform easy case; 4-sensor = gaps/stagger hard case), and how it composes
  with the alignment stage.

---

## 6. Checkpoint — end of 2026-09-09 session (restart with fresh context)

**Status:** discussion-only session, no code, nothing committed beyond doc
state below. The user takes a review round; work restarts in a new session.
This section is the restart anchor — read §1–5 first, then here.

### 6.1 Decisions / directions reaffirmed this session

1. **Interpolation operates on `ChannelSeries` alone**; `MultiplexedMeasurement`
   is out of scope for this layer (orchestration belongs to a later stage).
   No friction in scoping this way.
2. **numpy-content validation via `@model_validator(mode="after")` is fine and
   already the landed pattern** (`ChannelSeries._check_shapes`). There is no
   Pydantic limitation here — array contents can be validated like any field
   (verified live: a wrong-shaped `values` raises a clean `ValidationError`).
3. **Layer output = pre-calculated interpolation model**: parameters/recipe +
   argument (time) bounds; downstream samples it at arbitrary times;
   extrapolation possible but explicit.
4. **Method swappable** (linear, cubic, spline/Bezier, …); strong
   implementation wanted (scipy candidate — *not currently a runtime dep*).

### 6.2 Empirical findings (2026-09-09, live probes on landed models)

- `model == model_copy(deep=True)` **raises `ValueError`** (ndarray elementwise
  `==` → ambiguous truth). Tests must use `np.allclose`/helpers, never `==`
  on models carrying arrays.
- `model_copy()` (shallow) **shares the ndarray fields** — mutating the copy
  mutates the original. `model_copy(deep=True)` copies arrays. The
  conventions' "transforms return new objects / never mutate input" is
  convention-only for arrays; transforms should deep-copy or construct fresh
  models.
- The landed T2 validator rejects wrong shapes cleanly; adding content checks
  (dtype, finiteness, NaN policy, gap structure) there is straightforward.

### 6.3 Friction analysis (in answer to "where are the friction points?")

1. **ChannelSeries-only focus** — no friction for interpolation (see 6.1.1);
   alignment later needs round identity + cross-sensor collection (§3
   heads-up), out of scope here.
2. **numpy validation** — no obstacle; the real caveats are: hand-written
   checks (coarse, model-level errors), no `==` on models, array mutability
   on shallow copy.
3. **Interpolant object vs recipe as a model field** —
   - *Live scipy interpolant stored in a Pydantic model*: rejected — field
     type becomes untyped/heterogeneous across methods (linear/cubic/spline),
     interpolants are mutable/identity-compared/non-serializable, and a
     fitted interpolant is behaviour bound to one source grid (data models
     here are nouns; behaviour lives in functions/`process/`).
   - *Recipe as a model field*: preferred direction — typed (method as
     constrained enum), serializable, comparable, swappable; the scipy
     object is materialized lazily at the sampling call site (fit cost at
     our sizes, T ≤ few k, is microseconds — "pre-calculate once" buys ~
     nothing).
   - *Full OOP conversion ("move to OOP to ease Pydantic pains")*: rejected —
     it would discard the coercion/validation/serialization this repo
     deliberately bought ("Pydantic, not dataclasses", conventions §1, 58
     tests). Allowed hybrid: a small behaviour class inside `process/` when
     a transform genuinely needs identity/state (conventions §6.2), scoped
     to the layer, not a framework change.

### 6.4 Open questions for the restart (brainstorm b)

1. **Where the recipe lives**: as a field on `ChannelSeries` (data+recipe
   hybrid) vs pure-data `ChannelSeries` + `ChannelSeries -> InterpRecipe` +
   `sample(recipe, times[, source]) -> ChannelSeries`. Author lean: pure-data
   `ChannelSeries` + separate recipe model (keeps the model a noun, re-apply
   trivially legal, no field to confuse). **This is the opening question.**
2. **What the recipe references**: source knots *copied in* (self-contained,
   duplicates arrays) vs *references to* the `ChannelSeries` (staleness /
   mutability risk, §6.2) vs *spec-only + source passed at sample time*
   (author lean: no knot duplication, no staleness).
3. **Method typing**: constrained `Enum` on the spec for dispatch — never
   string `if/elif`.
4. **Output object**: Pydantic recipe model (serializable / testable /
   convention-consistent) vs live scipy interpolant wrapped in a small class
   (ergonomic repeated sampling, outside the model system). Both can expose
   `.at(t)`/`sample(times)`.
5. **scipy dependency decision**: add as a runtime dep? (currently runtime
   deps = numpy, matplotlib, pydantic, marimo, plotly.)
6. **Tests**: echo fixture (uniform → round-trip/idempotency), 4-sensor
   (gaps/stagger policy); comparison via `np.allclose`, not `==` (§6.2).
7. **Placement & composition**: where in `process/`, and the seam to the
   later alignment stage (bounds = time-overlap extremes of all channel
   series).

### 6.5 Restart reading order (fresh context)

`docs/interpolation-design.md` (§1–8; §7 = decisions landed, §8 = implementation
clarifications) → `docs/agenda.md` session statuses
(2026-09-09 entries) → `docs/pipeline-architecture.md` (§11 Stage 3, §15) →
`docs/pipeline-conventions.md` (§2, §4, §6, §10) →
`docs/dop3000/measurements-and-recordings.md` → landed code
`src/udv_echo_process/models/{base,channel_series,channel_config,
measurement,io}.py`. Working tree state at checkpoint: docs only
(`docs/agenda.md` modified, `docs/interpolation-design.md` new).

---

## 7. Decisions landed — 2026-09-09 review round (brainstorm b concluded)

**Status:** the review/brainstorm round concluded; these are settled for the
implementation session. Read §1–6 first, then here. No code was written this
session; the only live decision still to be *wired* (not designed) is adding
scipy to the dependency list.

**API = a closed transform, not a two-phase fit/sample.** Primary:

```python
resample(
    series: ChannelSeries,
    spec: InterpSpec,
    *,
    times: np.ndarray | None = None,
    dt_s: float | None = None,
) -> ChannelSeries
```

This matches the conventions closure rule (`pipeline-conventions.md` §4) and
makes re-interpolation simply "apply it again". A separate `fit()` / `sample()`
pair is **not** built now — it is added only if a later consumer genuinely needs
to pre-fit once and sample many grids (at our sizes fit cost is microseconds,
so "pre-calculate once" buys ~nothing).

**The "recipe" is a `Spec`, not a domain model.** With knots not copied and no
live interpolant stored, the recipe reduces to *method + extrapolation + NaN
policy + per-method params* — i.e. a `*Spec` stage-param (conventions §2/§6.2)
living in `process/`, not `models/`. Resolution of §6.4:

- **Q1** (recipe-as-field on `ChannelSeries`): **dropped** — conflates a noun
  with a verb's config. Pure-data `ChannelSeries` stands.
- **Q2** (knots copied vs referenced vs spec-only): **spec-only** — source
  passed at sample time; no knot duplication, no staleness.
- **Q3** (method typing): **constrained `Enum`** on the spec — never `str`
  `if/elif`.
- **Q4** (output object): **`InterpSpec` model + a typed function** (the §6.2
  pattern), no live-interpolant wrapper class.
- **Q5** (scipy): **adopted as a runtime dependency.** Rationale: future work
  (filtering, spectral analysis, alias unwrapping) will very likely need scipy,
  and it supplies `PchipInterpolator` / `CubicSpline` / B-splines instead of
  hand-rolling. **Not yet wired into `pyproject.toml` / `uv.lock`** — do that
  at the start of the implementation session.
- **Q6** (tests): see *Testing* below.
- **Q7** (placement/composition): `process/sync.py` now (Stage 3 home); split
  out `process/interp.py` only when `sync.py` mixes lag/grid/interp concerns.

**Method regimes (honest, not "one best method").** The inter-visit gap is
~372 ms ≈ **14.6 native steps** (re-verified this session); a cubic across it
overshoots the local endpoint envelope (measured ~+0.3 units even on a shallow
ramp). So:

- **`LINEAR` (default)** — hard no-overshoot guarantee across gaps; this is the
  "honest about what is recoverable" contract.
- **`MONOTONE`** (PCHIP-style shape-preserving) — for the bursty velocity case
  when C1 smoothness is wanted *inside* visits.
- **`CUBIC` / `BSPLINE`** — reserved for the uniform, gap-free echo fixture
  (and future dense data), where they add value.

Enum: `InterpMethod = LINEAR | MONOTONE | CUBIC | BSPLINE`.

**Interpolation is per-gate 1-D, vectorized.** `values` is `(T, G)`; the
transform interpolates along axis 0 (time) independently per gate over the
single shared knot vector `time_s`; `gate_depths_mm` / axis 1 are untouched
(spatial interpolation is out of scope).

**`InterpSpec` fields (draft — implementation may refine):**

- `method: InterpMethod = InterpMethod.LINEAR`
- `extrapolation: "error" | "nan" | "nearest" = "error"` (never the silent
  endpoint clamp `np.interp` does by default)
- `nan_policy: "error" | "propagate" = "error"`
- per-method params (e.g. spline order / knots) as needed.

**Output carries `channel` + `config` through.** The resampled output is a new
`ChannelSeries` (uniform `time_s`, `(T', G)` values); the T2 `shape_2d` check
already accepts it, `channel`/`config` are preserved, and the input is never
mutated (deep-copy discipline, §6.2).

**Hole-marking seam (deferred, but the seam is fixed now).** No mask field is
added to `ChannelSeries` yet. The seam: a companion boolean `measured` mask
from the sample call, or a later optional `mask: np.ndarray | None` field on
`ChannelSeries` — decided when a frequency-domain consumer needs it.

**Testing (implementation session):** knot round-trip (sampling at the original
`time_s` reproduces `values` exactly — method-agnostic, works on both fixtures);
overshoot guard on the 4-sensor gaps; uniform-echo idempotency; extrapolation
and NaN-policy behaviour; non-mutation of input. All comparisons via
`np.allclose`, never `==` on models (§6.2).

---

## 8. Implementation clarifications — 2026-09-09 (implementation session)

Settled in discussion with the user at the start of the implementation session,
before any code. These refine §7 within its "implementation may refine"
latitude; they do **not** change the landed API shape.

- **Grid argument (exactly one of `times` / `dt_s`).** Passing both, or
  neither, raises `ValueError`. `times` must be **strictly increasing and
  finite** — never silently sorted; empty `times` errors.
- **Duplicate source knots: not a DOP concern (uniform strict rule).**
  DOP-series instruments write one timestamp per stored profile and never emit
  repeats (re-verified: all five fixture channels are strictly increasing), and
  the reader cannot manufacture duplicates. `resample()` therefore requires
  **strictly increasing `time_s` for every method** (clear `ValueError` naming
  the first duplicate otherwise). Duplicate-tolerant handling (aggregate /
  keep-last) is a *deliberate policy for non-DOP devices* — future work, noted
  here and in the docstring, not built now.
- **`dt_s` grid geometry: inclusive span.** Target grid =
  `[time_s[0], time_s[-1]]` at step `dt_s`; if the span is not an exact
  multiple, the final interval is shorter so the last sample is always the
  series' last time (idempotent across re-resamples). `dt_s <= 0` and
  `dt_s` larger than the whole span error.
- **Per-method params are bundled (not a flat grab-bag).** `InterpSpec`
  carries a typed nested model `params: InterpParams` (Pydantic), today holding
  `spline_order: int = 3`, owned by `BSPLINE` (other methods ignore it;
  documented). Params are defaulted and typed; adding a parameter later never
  changes the `resample(series, spec)` call site. Some params are
  **data-count dependent** (spline order k needs ≥ k+1 knots) — such
  constraints are validated at **apply time**, because spec construction
  cannot know the series length; noted in the docstring. A discriminated
  per-method spec union is deferred until a *second* parameterized method
  exists.
- **Extrapolation: per-sample row semantics.** `error` raises `ValueError` if
  *any* requested time is out of range; `nan` NaNs only the out-of-range rows
  (in-range rows interpolate normally); `nearest` fills out-of-range rows with
  that gate's edge value (scipy `fill_value="nearest"` naming). Never a silent
  endpoint clamp under the default `error`.
- **NaN policy.** Non-finite `time_s` / `times` always error.
  `nan_policy="error"` (default) rejects NaN source values up front with a
  clear message; `"propagate"` carries NaN through LINEAR (the segment between
  finite knots goes NaN, per `np.interp`) and raises a clear
  "spline methods cannot fit through NaN knots" error instead of leaking
  scipy's internal failure.
- **Exports.** `InterpMethod`, `InterpSpec`, `InterpParams`, `resample`
  exported from `process/__init__.py` and re-exported at package top level
  (`udv_echo_process.resample`, …), per AGENTS.md's export convention and the
  precedent set by `models/`/`io`/`analysis`.

