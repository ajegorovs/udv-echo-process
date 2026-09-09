# Per-gate time-wise filtering — design & review handoff

Status: **implemented 2026-09-09, pending a reviewer round.** Companion to
`interpolation-design.md` (the resampling layer this filter is meant to
follow). This doc is the handoff: what was built, why it is shaped as it is,
and the specific questions to reassess.

## 1. Where this sits

The sync pipeline grows stage by stage. Stage 3 (`process/sync.py`) puts a
channel onto a uniform time grid (`resample(series, InterpSpec, *, times |
dt_s) -> ChannelSeries`). This stage adds the next transform: **filter each
gate's time series along axis 0 (time)**. The first filter is
**total-variation (ROF) denoising** — remove noise while preserving sharp
jumps (a travelling echo peak, a step in velocity), which a `mean`-type
smoother would smear.

Scope (agreed with the user before implementing): **module + tests only**; no
notebook preview yet (the user wires that separately). `denoise` is intended
to run on an **already-resampled, uniform-cadence** series — it follows
`resample` in the pipeline.

## 2. Public API (`src/udv_echo_process/process/filter.py`)

```python
class FilterMethod(str, Enum):
    TV = "tv"

class FilterSpec(Model):
    method:     FilterMethod = FilterMethod.TV
    weight:     float = 1.0      # TV λ, must be > 0; larger = smoother
    iterations: int = 200        # Chambolle solver cap

def denoise(series: ChannelSeries, spec: FilterSpec) -> ChannelSeries: ...
```

Closed transform, per the conventions closure rule (`pipeline-conventions.md`
§4): returns a **new** `ChannelSeries` on the same time grid/gates; metadata
(`channel`/`meas_type`/`gate_depths_mm`) carried, `config` deep-copied, input
never mutated. A *sequence of filters* = re-apply (or compose `FilterSpec`s in
order). Exported from `process/__init__.py` and the package top level.

Implementation: `skimage.restoration.denoise_tv_chambolle`, applied **per gate
as an independent 1-D problem along the time axis** (loop over the `G` gates)
— deliberately not as a 2-D image (which would couple neighbouring gates).

Validation: rejects fewer than two time samples, no gates, or any non-finite
`values` (no NaN policy yet — mirror `resample`'s default `error`).

## 3. Decisions & rationale

| Decision | Why |
|----------|-----|
| TV (ROF), not moving-average | preserves sharp steps — the point of the filter for echo/velocity steps. |
| skimage `denoise_tv_chambolle` (added dep `scikit-image>=0.26.0`) | the standard off-the-shelf ROF solver; user directive was "use existing implementations, add dependencies if needed". Verified a cp314 wheel exists for Python 3.14.7. |
| Per-gate independent 1-D | a gate's neighbours are spatially distinct sensors; coupling them would smear the time signal with the wrong physics. |
| Closed `ChannelSeries -> ChannelSeries` | the repo frozen interpolation decision (§7 of `interpolation-design.md`): the config lives in a `*Spec` in `process/`, *not* as a field on the model — "filtered data attribute" was raised by the user and rejected in favour of this. |
| `weight` semantics | == λ in ROF (`0.5‖u−f‖² + λ·TV(u)`), 1:1 with skimage's `weight`. |

## 4. Verified behaviour (13 tests, `tests/test_process_filter.py`)

- clean step → near-identity (TV doesn't churn flat regions); noisy step →
  residual noise cut ~4× (at `weight=0.5` on a unit step with σ=0.2 noise)
  while the edge jump stays ~0.9 (preserved);
- heavier `weight` ⇒ lower total variation (smoother);
- gates filtered **independently** (no bleed between a clean and a noisy gate);
- purity (input unmutated, config deep-copied, metadata carried, same grid);
- spec validation (`weight > 0`, `iterations >= 1`);
- too-few-samples / non-finite rejection;
- fixtures: echo `data/echo/650.BDD` denoises to a valid series; the pipeline
  flow `resample(gappy 4-sensor) → denoise` works.

## 5. Open / invite reassessment

This is the reason for this handoff — the user explicitly wants a reviewer to
**reassess whether this approach is optimal**. The knobs worth pulling:

1. **Dependency weight.** scikit-image is a heavy dep for one function (it
   pulls imageio, networkx, tifffile, lazy-loader on top of numpy/scipy; only
   pillow was already present). Alternatives to weigh: (a) hand-rolled
   ~30-line Chambolle/projected-gradient solver (dependency-free, per-gate
   vectorized in numpy) — the accuracy is comparable; (b) an exact 1-D TV
   solver (Condat, O(n)) if per-visit cost ever matters; (c) keep skimage.
   Trade-off: proven/audited code vs. dependency footprint. This repo already
   removed scikit-image once (hardening §P1) because its optical clients went
   to the sibling repo — re-adding it for one function reverses that leaning.
2. **`weight` is data-scale dependent, with no sane default.** Echo runs
   0→2000 (module scale); velocity is tens of mm/s. A single default `1.0`
   is arbitrary across recordings. Options: normalize the signal before TV
   (scale-invariant `weight`), expose a *relative* weight, or accept
   per-recording tuning (the notebook preview — not yet written — is the
   tuning tool). Also: how does skimage's `weight` map to the semantics of
   the Wolfram `TotalVariationFilter` the backlog originally cited — is the
   Wolfram parameterization even analogous?
3. **Solvers' convergence / idempotency.** TV is genuinely **not idempotent**:
   re-applying continues smoothing a bounded amount (verified constant drift
   ~0.066 regardless of iterations — intrinsic, not solver error). The
   contract here is *re-applicability* (§4 closure), not a fixed point. Is
   that the right contract, or should a filter stage also expose a
   `n_passes`/stop-when-converged knob?
4. **Uniform-grid assumption is documented, not enforced.** `denoise` does
   not check that `time_s` is actually uniform — TV is defined over sample
   *indices*, so feeding it a raw gappy cadence would silently bridge gaps.
   Should it reject non-uniform input (measure spacing spread), or is
   "documented precondition, follow `resample`" enough?
5. **Solver parameters are under-exposed.** Only `iterations` is surfaced;
   skimage's `eps` convergence tolerance is left at its default. Fine for now,
   but if convergence quality ever matters it should be a field.
6. **Placement: `ChannelSeries`-level, matching interpolation.** Consistent
   with the sync-design scope decision, but the `MultiplexedMeasurement`-level
   "apply to all channels" wrapper does not exist yet. Intended later.
7. **Sanity of the whole design vs. a simpler filter.** Is per-gate
   independent 1-D TV actually the right first filter for this signal, or
   would a Savitzky–Golay / median (edge-preserving, more tunable, no solver)
   serve the preview use better while the signal is still being understood?

## 6. Verify / reproduce

```
uv sync --extra dev                 # brings scikit-image (note: clobbers the
                                    #   editable marimo-inspect — reinstall
                                    #   editable for the notebooks)
uv run --no-sync --extra dev pytest tests/test_process_filter.py   # 13 pass
uv run --no-sync --extra dev pytest -q                             # 116 pass
uv run --no-sync --extra dev ruff check src tests
```