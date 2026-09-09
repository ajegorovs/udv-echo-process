# Per-gate time-wise filtering — design & review handoff

Status: **reviewed 2026-09-09 — direction settled, re-planned; implementation
pending (handoff to another agent).** The review round, settled decisions,
and target design live in **§7** — read that first. §1–6 are the original
handoff (what was built, why, and the questions that prompted the review);
**§7 supersedes the open questions of §5.** Companion to
`interpolation-design.md` (the resampling layer this filter composes with).

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

---

## 7. Review round + re-plan — 2026-09-09

Status: **reviewed; direction settled with the user; implementation pending
(handoff).** This section supersedes §5's open questions — read it before
writing any code.

### 7.1 Findings (verified 2026-09-09, not assumed)

| Claim (§) | Result |
|---|---|
| `weight` is data-scale dependent (§5.2) | **Confirmed.** Same `weight=1.0` → relative change `‖Δ‖/‖x‖` = **0.45%** on echo (`650.BDD`, std 298, range 0–2048) vs **3.8%** on velocity ch6 (`200RPM.BDD`, std 23, range −55…246). The velocity signal is ~13× smaller, so a fixed default is ~8× more aggressive there. |
| TV not idempotent (§5.3) | **Confirmed** — 2nd-pass max-Δ = 0.066, 3rd = 0.030 (bounded decay, no fixed point). |
| scikit-image heavy (§5.1) | **Confirmed** — pulls `imageio`, `networkx`, `tifffile`, `lazy_loader`. (Now moot — see §7.2.2.) |
| Wolfram "TV" ≠ what was ported (§5.2 Q2) | **Confirmed** in `references/wolfram/UDV_Data_Analysis_Echo.txt` (L106, 182–188, 221–222): Wolfram's `TotalVariationFilter` is a **2-D image** filter on `Image@Transpose@velocityDataGatesMm` (coupling *all* gates), parameterized by `constraintRelax` (0.25–0.5) + `Method -> "Laplacian" | "Poisson"` (a *noise model*), on `Rescale`d data. `skimage.restoration.denoise_tv_chambolle` implements only the ROF (Gaussian/L2) model — it cannot express Wolfram's Poisson/Laplacian modes. The per-gate-1-D choice is a **deliberate, physically-motivated divergence**, not a closer approximation; the `references/wolfram/README.md` port row already says "not a line-port", which is the honest wording to keep. |
| Aliasing in velocity | **Confirmed present** (ch6 max 245.9 > `velo_max` 152.05), but **out of scope by decision §7.2.1** — recording parameters are configured to minimise it. |

### 7.2 Settled decisions (user, 2026-09-09)

1. **Purpose = pre-interpolation smoothing + outlier removal, not aliasing.**
   The flow is so turbulent the current sampling rate cannot resolve it;
   interpolating without smoothing/relaxation yields non-physical data. The
   working order is **average / remove outliers *first*, then interpolate.**
   Consequence: the filter layer runs **before** `resample` on the *raw
   measured (gappy) series* — inverting §1's "`denoise` follows `resample`"
   assumption. Both stages are closed `ChannelSeries -> ChannelSeries`
   transforms, so order stays caller-chosen; nothing is baked into either.
2. **Keep scikit-image.** There is no thin-repo mandate — the §5.1 "dependency
   footprint" framing is withdrawn. scikit-image stays for TV and future work
   (its earlier removal in hardening §P1 was only because the optical clients
   that used it left; it is now a used dependency again).
3. **Native sequence support, simple.** A single filter suffices to start, but
   the architecture must express a *sequence of filters* without a framework.
   This is just the closure rule applied n times (§7.3) — not a new `Pipeline`.

### 7.3 Target design — the filter *sequence* platform

Reshape `src/udv_echo_process/process/filter.py` (today: single `TV` method +
`denoise`) into a sequence-capable layer, mirroring the settled `sync.py`
shape (`InterpMethod` / `InterpParams` / `InterpSpec` / `resample`):

- **`FilterMethod`** gains `MEDIAN` (outlier-robust — the "remove outliers"
  tool) and `MEAN` (boxcar — the "average the signal" tool) on scipy
  (`ndimage.median_filter1d` / `uniform_filter1d`), plus `SAVGOL`
  (`signal.savgol_filter`). `TV` stays on skimage.
- **`FilterSpec`** = `method` + bundled `params: FilterParams` (defaults valid
  for every method — the `InterpParams` pattern, §8 of
  `interpolation-design.md`).
- **`filter(series, spec)`** — the generic verb, a rename of `denoise` (which
  already dispatched on `spec.method`, so the name was already lying).
  Closed `ChannelSeries -> ChannelSeries`; touches `values` only, carries
  `time_s`/`channel`/`meas_type`/`gate_depths_mm` + a deep copy of `config`.
- **`filter_sequence(series, specs)`** — the sequence entry point; a plain
  fold: `filter_sequence(s, [a, b]) == filter(filter(s, a), b)`.

**Cadence rule (resolves §5.4).** Index-window methods (MEDIAN/MEAN/SAVGOL)
operate over *consecutive measured profiles*, so they are well-defined on the
raw gappy series — that is the point (smooth the measurements, not the
interpolated fiction). TV (ROF) is defined over sample *indices* and assumes
uniform spacing, so it is a **post-`resample`** filter (or rejected on
non-uniform input). The rule is per-method, not per-layer.

### 7.4 Implementation snippet (target module)

```python
"""Per-gate time filtering — a sequence-capable smoothing/outlier layer.

Filters each gate's time series along axis 0 (time). Driving need (settled
2026-09-09): pre-process turbulent velocity fields — smooth / remove outliers
on the *measured* samples first, then interpolate across gaps. Not aliasing
correction (recording params are configured to minimise that).

Sequence is native: ``filter`` is a closed ``ChannelSeries -> ChannelSeries``
transform and ``filter_sequence`` is a plain fold. Per-gate, independent 1-D
along time (never coupling gates); only ``values`` is transformed.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
from pydantic import Field
from scipy.ndimage import median_filter1d, uniform_filter1d
from scipy.signal import savgol_filter
from skimage.restoration import denoise_tv_chambolle

from udv_echo_process.models.base import Model
from udv_echo_process.models.channel_series import ChannelSeries


class FilterMethod(str, Enum):
    """Fixed set of filter methods (never a bare ``str``)."""

    MEDIAN = "median"  # outlier-robust — the "remove outliers" tool
    MEAN = "mean"      # boxcar average — the "average the signal" tool
    SAVGOL = "savgol"  # Savitzky–Golay (smooth, preserves higher moments)
    TV = "tv"          # ROF total-variation (edge-preserving; uniform cadence only)


class FilterParams(Model):
    """Bundled per-method knobs, defaulted for every method (cf. InterpParams)."""

    window: int = Field(default=5, ge=1)          # MEDIAN/MEAN/SAVGOL, samples
    polyorder: int = Field(default=2, ge=0)        # SAVGOL (< window)
    weight: float = Field(default=1.0, gt=0)       # TV lambda (larger = smoother)
    iterations: int = Field(default=200, ge=1)     # TV solver cap


class FilterSpec(Model):
    """Parameters for one filtering pass over a ChannelSeries along time."""

    method: FilterMethod = FilterMethod.MEDIAN
    params: FilterParams = Field(default_factory=FilterParams)


def filter(series: ChannelSeries, spec: FilterSpec) -> ChannelSeries:
    """Apply one filter to each gate of ``series`` along time (axis 0).

    Pure transform: returns a *new* ``ChannelSeries`` on the same grid/gates
    with ``values`` filtered per gate; input never mutated; metadata + a deep
    copy of ``config`` carry through.
    """
    _require_filterable(series, spec)
    values = _apply(series.values, spec)
    return ChannelSeries(
        channel=series.channel,
        meas_type=series.meas_type,
        gate_depths_mm=list(series.gate_depths_mm),
        time_s=series.time_s,
        values=values,
        config=series.config.model_copy(deep=True),
    )


def filter_sequence(
    series: ChannelSeries, specs: list[FilterSpec]
) -> ChannelSeries:
    """Apply ``specs`` in order — the sequence-of-filters entry point.

    A plain fold over ``filter``; composes freely with ``resample`` in either
    order (e.g. smooth the raw series, then interpolate across gaps).
    """
    for spec in specs:
        series = filter(series, spec)
    return series


def _apply(values: np.ndarray, spec: FilterSpec) -> np.ndarray:
    p = spec.params
    if spec.method is FilterMethod.MEDIAN:
        return median_filter1d(values, size=p.window, axis=0, mode="nearest")
    if spec.method is FilterMethod.MEAN:
        return uniform_filter1d(values, size=p.window, axis=0, mode="nearest")
    if spec.method is FilterMethod.SAVGOL:
        return np.column_stack(
            [
                savgol_filter(values[:, g], p.window, p.polyorder)
                for g in range(values.shape[1])
            ]
        )
    # TV — per-gate 1-D (never a 2-D image coupling gates)
    out = np.empty_like(values, dtype=np.float64)
    for g in range(values.shape[1]):
        out[:, g] = denoise_tv_chambolle(
            values[:, g], weight=p.weight, max_num_iter=p.iterations
        )
    return out


def _require_filterable(series: ChannelSeries, spec: FilterSpec) -> None:
    if series.time_count < 2:
        raise ValueError(
            f"filter: channel {series.channel} has {series.time_count} sample(s); "
            "need at least two time samples"
        )
    if series.gate_count == 0:
        raise ValueError(f"filter: channel {series.channel} has no gates")
    if not np.isfinite(series.values).all():
        n_bad = int(np.count_nonzero(~np.isfinite(series.values)))
        raise ValueError(
            f"filter: channel {series.channel} values hold {n_bad} non-finite "
            "entr(y/ies); clean the source before filtering"
        )
    p = spec.params
    if spec.method is FilterMethod.SAVGOL and p.window <= p.polyorder:
        raise ValueError(
            f"filter: SAVGOL window ({p.window}) must exceed polyorder "
            f"({p.polyorder})"
        )
    if spec.method is FilterMethod.TV and not _is_uniform(series.time_s):
        raise ValueError(
            "filter: TV is defined over sample indices and needs uniform "
            "cadence; run resample() first (or use MEDIAN/MEAN/SAVGOL)"
        )


def _is_uniform(t: np.ndarray, rtol: float = 1e-3) -> bool:
    dt = np.diff(t)
    return dt.size == 0 or bool(np.allclose(dt, np.median(dt), rtol=rtol))
```

Notes for the implementer:

- `median_filter1d` / `uniform_filter1d` keep the shape (`axis=0`); boundary
  `mode` is an implementation choice — `"nearest"` avoids edge artefacts on
  short bursts; `"reflect"` is scipy's default.
- `savgol_filter` has no `axis` kwarg, hence the explicit gate loop (the code
  above mirrors the existing TV gate loop). Its `window_length` must be odd —
  lock that in a test (and, if convenient, an apply-time check).
- `_is_uniform`'s `rtol` is a tuning knob: the echo fixture is exactly
  3.2 ms uniform; the velocity fixture's intra-visit cadence is 25.4 ms but the
  *whole* series is gappy (inter-visit gaps ~372 ms), so TV on it correctly
  raises unless `resample` runs first.
- The rename `denoise` → `filter` is public-API breaking; the package is
  pre-1.0 with no import-compat promise (pipeline-architecture §12.6), so
  rename cleanly and update the exports (`process/__init__.py`, top-level
  `__init__.py`) + `tests/test_process_filter.py` + `test_package_surface.py`.

### 7.5 Implementation checklist

1. Rewrite `process/filter.py` to §7.4 (or equivalent — keep it no more
   complicated than this).
2. Update exports: `process/__init__.py` and top-level `__init__.py`
   (`FilterMethod`, `FilterParams`, `FilterSpec`, `filter`,
   `filter_sequence`; drop `denoise`).
3. Tests — extend `tests/test_process_filter.py`:
   - spec validation: `window >= 1`, `polyorder >= 0`, SAVGOL `window >
     polyorder`, TV `weight > 0`;
   - MEDIAN removes an outlier spike while preserving a step; MEAN reduces
     Gaussian noise; SAVGOL smooths without the median's stair-step;
   - sequence order matters and equals the fold (`filter_sequence(s, [a, b])`
     == `filter(filter(s, a), b)`);
   - cadence rule: TV raises on the gappy velocity fixture, passes on the
     uniform echo fixture (and after `resample`);
   - purity (input unmutated, `config` deep-copied, metadata carried, same
     grid) — reuse the existing purity test verbatim;
   - composition: `filter_sequence(raw, [MEDIAN])` → `resample` works on
     `data/4-sensor-velocity/200RPM.BDD`.
4. Keep `scikit-image>=0.26.0` in `pyproject.toml` (already there — do not
   remove it).
5. `uv run --no-sync --extra dev ruff check src tests` + `ruff format` +
   `pytest -q` green.
6. Log the landing to `docs/agenda.md` (session-status entry) and note the
   `denoise → filter` rename there.

### 7.6 Verify / reproduce

```
uv run --no-sync --extra dev pytest tests/test_process_filter.py   # 13 pass (pre-landing baseline)
uv run --no-sync --extra dev pytest -q
uv run --no-sync --extra dev ruff check src tests
```