# SA2.4 — committed-data spectral characterization: implementation contract

**Status: PLAN, not started.** The contract for SA2.4, written before any code. It implements the
design's own sentence — SA2.4 is *committed-data spectral characterization. Low-frequency structure,
support near ~1 Hz, the supported 8.333-Hz configurations, depth dependence. Descriptive and per
sitting — no cross-sitting statistical inference*
([`sa2-spectral-design.md`](sa2-spectral-design.md) §Sequence, 618-620) — against the settled contract
(§A–§J), the merged SA2.1/SA2.2 backends, and the sparse plan's publish point
([`sparse-signal-analysis-plan.md`](sparse-signal-analysis-plan.md), 249-253).

> **SA2.4 adds no new estimator, no new admission rule, no threshold and no verdict change.**

It re-uses `analysis.sparse_periodogram.periodogram_of_view` (`sparse_periodogram.py:417-482`), the
admission already carried inside every `SpectralEstimate`, and `analysis.sparse_target_support`'s own
cell rule. It adds orchestration across the committed gates, **one prespecified descriptive
reduction** of an already-published density (§2), a scalar report (§5), and the tests that hold both
to their definitions.

Out of scope, verbatim from the contract (`sa2-spectral-design.md:622-628`): whether the ~1 Hz feature
is a vortex, whether rotor speed was measured, whether the CFD discrepancy is explained, whether one
UDV setting is superior, whether two sittings are statistical replication. SA3 (spatial/modal
description) is optional and only after a usable explorer (`sparse-signal-analysis-plan.md:178-190,
264`); cross-sitting and condition contrasts are SA5 (`:212-228`) and are **not** questioned here.

## 1. The row set, fixed before any computation

- A **cell** is one `recording × view`. The default sweep is `committed_spectral_capability()`'s own
  scope — the passes the catalog marks as reproducibility sittings, campaign excluded
  (`sparse_spectral_capability.py:233-270`, `:255-259`): **52 recordings × {`primary-comparison`,
  `full-record`} = 104 cells**. No hand-built sweep; the campaign stays a deliberate act with its own
  ref.
- **Detrending is `Detrending.MEAN` on both views**, the design's default
  (`sa2-spectral-design.md:325-332`) and SA1's ACF default. `mean+linear` is not mixed in; if wanted
  it is a second, separately labelled table (§12, D2).
- **Gates are all supported gates**, enumerated by the accessor that owns the question —
  `WindowView.supported_columns` (`_sparse_view.py:190-197`) — never a re-derived mask, never a
  hand-picked subset. `gate_index` is the view's column index; `depth_mm` is
  `view.depths_mm[column]`, the instrument's native coordinate (`_sparse_view.py:135-152, 199-214`).
- One window decision, one label: a spectrum labelled `primary-comparison` comes from exactly the view
  that label owns (`sa2-3-notebook-preview-plan.md:54-57`). The probes are the design's names,
  `recurrence-1hz` (1.0 Hz) and `rotor-8.333hz` (25/3 Hz) (`sparse_spectral_capability.py:55-61`).
- Within a cell every gate shares **one** time axis (`WindowView.time_s` is per view), so `N`, span,
  `dt_eff`, `fs_eff`, Nyquist, `Δf` and `max_relative_timing_error` are identical across that cell's
  gate rows, and a report check asserts equality. Read N, span, effective rate, Nyquist and Δf
  through `SpectralEstimate`'s properties (`sparse_periodogram.py:294-332`); read the duration scale
  and maximum relative timing error from `estimate.characterization`, and the uniformity tolerance
  from `estimate.admission`. No notebook or writer recomputes them.

## 2. The one new metric: low-frequency band power fraction

**Prespecified, never tuned after seeing a number (`sa2-spectral-design.md:234-239`).** For one
`(cell, supported gate)` and a declared edge `f_low = 1.0 Hz`, with `N`, `fs_eff`, `Δf` and `psd` from
the returned `SpectralEstimate` and every bin **cell** from the repository's single cell definition:

```text
grid   = one_sided_frequency_grid(N, fs_eff)            # sparse_spectral_support, the one grid
cell_k = frequency_cell(k, grid=grid)                   # sparse_target_support, the one cell rule
w_k    = clip( length(cell_k ∩ [0, f_low]) / length(cell_k) , 0, 1 )
B      = Σ_k   w_k · psd[k] · Δf                        # units: (mm/s)^2
T      = estimate.integrated_psd_power                  # units: (mm/s)^2, READ, never recomputed
Φ      = B / T                                          # dimensionless
```

**Why 1.0 Hz.** It is the design's declared recurrence *scale/probe target*, not a peak
(`sa2-spectral-design.md:170-175`); the design permits a band-integrated power as the honest
alternative to a raw peak height (`:143-146`), and this slice already carries bandpower
(`sparse-signal-analysis-plan.md:154-168`). A different band is a different prespecified band in a new
labelled table. The band is **closed**, `[0, f_low]`, measured by intersection length: a cell edge
exactly on `f_low` adds zero length (a point has zero measure), so the closed/open question changes no
value and no tie rule is needed.

**The DC cell is a half-width cell with a whole bin weight.** `frequency_cell`
(`sparse_target_support.py:116-148`) opens the DC cell at `0.0`, so `length(cell_0) = Δf/2` and `w_0`
is `1` whenever `f_low ≥ Δf/2` — true for every committed view (`Δf/2 ≲ 0.042 Hz`). DC enters at its
full `psd[0]·Δf`. This is not a doubled count: `w_k` is an overlap *fraction of the cell*, not a
count of bins. The overlap rule states explicitly how a bin straddling the band edge contributes;
it does not make a finite-grid estimate independent of resolution.

**Request validity is an input check, not an admission rule.** `f_low` must be positive, finite and
at most the axis's Nyquist frequency `f_N` (the physical support edge); a band edge above the support
is a caller error. `f_low = f_N` is permitted solely as a **boundary-arithmetic test**: every
weight is then `1` and `Φ = 1` by construction, not an informative measurement. Above-Nyquist
edges are invalid requests outside the declared domain. This changes no axis verdict.

**Units and denominator source.** `B` and `T` are `(mm/s)^2`, `Φ` dimensionless in `[0, 1]`; a
percentage is display only. `T` is the result's own `integrated_psd_power`, which by `PARSEVAL_RULE`
(`sparse_periodogram.py:142-148`) equals `window_normalized_mean_square_power` — the design's required
quantity, *not* the raw variance of the detrended trace (`sa2-spectral-design.md:343-366`). Reading it
removes a second computation that could disagree with the invariant the estimator already checks on
construction.

**Three states, never conflated** (`BandFractionState`):

| state | when | carried |
| --- | --- | --- |
| `refused-axis` | `estimate.verdict is REFUSED_AXIS` | state + admission reason; `Φ`, `B` are `None`; **no gate row**, no zero synthesized (`sparse_periodogram.py:388-412`) |
| `defined-zero-power` | `DEFINED` and `T == 0.0` | `Φ is None` (0/0 undefined), `B == 0.0` recorded as a **defined zero** (`sparse_periodogram.py:571-576`) |
| `defined` | `DEFINED` and `T > 0.0` | `Φ = B / T` |

**Invariants asserted before publication:** `Φ` finite and `0 ≤ Φ ≤ 1 + 1e-9`; `B ≤ T·(1 + 1e-9)`;
`T` within the carried `parseval_relative_error` of `window_normalized_mean_square_power`; and `Φ = 1`
at `f_low = f_N` for a `defined` spectrum, because the cells tile `[0, f_N]` exactly — for even `N` the
top bin sits at Nyquist and for odd `N` it sits `Δf/2` below it while its cell still reaches `f_N`
(`sa2-spectral-design.md:210-216`), so every weight is `1` either way. A violation is a report failure,
never a clamped number. No cell on the committed row set is refused — §J records 104/104 admitted (`sa2-spectral-design.md:496-513`) —
so `refused-axis` is fixture-exercised only, and `defined-zero-power` must likewise be implemented and
tested: a constant gate is a measurement, a refused axis was not measured.

## 3. Per-cell descriptive scalars (no new verdict)

For each cell, read from the objects that own them, never recomputed:

- **axis** — `N`, span, `dt_eff_s`, `fs_eff`, Nyquist, `Δf`, `duration_resolution_scale_hz`,
  `max_relative_timing_error`, the uniformity tolerance, the admission verdict and its reason
  (`sa2-spectral-design.md:585-591`; `sa2-3-notebook-preview-plan.md:98-111`); taper/normalization
  names and ENBW in Hz (`sparse_periodogram.py:255-266`);
- **the two probe target rows** from `target_frequency_support(estimate.admission, …)` —
  `band_supported`, `analysis_supported`, `supported`, reason, Nyquist, nearest bin, bin offset,
  `cycles_in_view`, cell edges (`sparse_target_support.py:151-246`). A restatement of §J at the
  gate-resolvable level, **not** a second verdict. Target rows are per **cell**, not per gate, since
  one view supplies one axis;
- **`parseval_relative_error`** as a QA field only — not a headline, not compared across jobs
  (`sa2-3-notebook-preview-plan.md:170-174`; `sa2-spectral-design.md:604-612`).

No peak, no dominant frequency, no inferred recurrence label, no condition contrast enters any field
(`sa2-3-notebook-preview-plan.md:176-181, 260-264`).

## 4. Within-sitting repeat spread — descriptive, never a floor

Where a condition repeats inside a sitting (`common-reference` runs, the block anchors), the report
carries the descriptive spread of `Φ` across those cells as its own row set. It is descriptive only:
not a screening floor, not a resolvability threshold, not a condition or sitting comparison
(`sparse-signal-analysis-plan.md:16-19, 219-224`). The exploratory observation that this spread is
*substantial* is itself uncommitted; the report states the measured spread, derives no threshold from
it, and calls no condition better or worse.

## 5. Report artefacts, provenance and digests

New directory `reports/sparse-signal/` — the plan's designated publish root
(`sparse-signal-analysis-plan.md:249-253`) — with SA2.4-named files and **scalar content only**:

| file | content |
| --- | --- |
| `sa2-4-spectral-characterization.csv` | one row per `cell × supported gate`; §2 and §3 scalars only; per-cell target rows live in JSON and are not duplicated per gate |
| `sa2-4-spectral-characterization.json` | `ok`, `checks`, `plan_fingerprint`, `analysis_commit`, `table_sha256`, the prespecified constants (`low_band_hz`, detrending, views, gate rule, precision), per-cell target rows and summary |
| `README.md` | definitions, units, digests, view/estimator/detrending settings, reproduction command, §10 no-go list |

- **No PSD array is serialized and SA2.4 ships no NPZ.** The plan's "NPZ for documented arrays as
  needed" (`:249-253`) is not needed: `Φ`, `B`, `T` and §3's fields are all scalars. This does
  **not** waive the design's #49 prerequisite for committed machine-readable spectral artifacts (§6).
- Provenance is read, not rebuilt: `ViewProvenance` (`_sparse_view.py:305-364`) supplies
  `relative_path`, `source_sha256`, `job`, `point_label`, `order`, view and view rule. The pass is the
  sweep's own `PassRef.name`, stated as the selection, never as a provenance field
  (`sa2-3-notebook-preview-plan.md:229-233`).
- Digests follow one rule: `table_sha256` is the canonical LF-normalized digest of the CSV beside it
  (`analysis._floor_documents.table_digest`, `_floor_documents.py:66-73`). Numbers use a stated
  fixed precision (Φ at six decimals, recorded in the document), UTF-8/LF, one trailing newline —
  two runs at one revision are byte-identical.
- **Frozen reports are untouched.** Every committed file under `reports/` at the SA2.4 base revision
  (`sparse-mixer-live-1/`, `sparse-mixer-live-2/`, `mixer-sensitivity-analysis/`, `stage2-e20-e64/`)
  must be byte-unchanged; only new files under `reports/sparse-signal/` appear
  (`sa2-3-notebook-preview-plan.md:284-292`).
- A bare CLI run records HEAD; a recorded `--analysis-commit` reproduces committed bytes,
  following the stage-2 writer's `--dataset-root/--plan/--plan-name/--report-dir/--analysis-commit`
  shape (`sparse_stage2_pairs.py:1589-1606`).

## 6. Serialization: the design's clause, read deliberately

The design keeps issue **#49** outside SA2 implementation: SA2 v1 does not solve general ndarray JSON
serialization, and *"if SA2 ever needs committed machine-readable spectral artifacts, #49 is resolved
deliberately first — not by assuming `model_dump(mode="json")` is safe because spectra happen to
contain arrays"* (`sa2-spectral-design.md:630-636`); the estimator says the same
(`sparse_periodogram.py:46-47`).

The scalar CSV/JSON in §5 can be generated without serializing an ndarray-bearing model;
`SpectralEstimate.model_dump(mode="json")` still fails and is never called by this writer. The
prerequisite below is therefore **policy from the design's broad "machine-readable spectral
artifacts" clause, not a technical dependency of scalar CSV**. Resolve #49 in a separate reviewed
PR outside SA2 before publishing these artifacts, or have a reviewer explicitly narrow the design
clause in its authority document. Do not quietly read the scalar route as an exemption.

After that external gate, SA2.4 still exports only named scalar reductions. The writer may call
`model_dump(mode="json")` on scalar-only `ValueModel`s, and must build every spectrum row from named
scalars and properties rather than serializing a whole `SpectralEstimate`. No ad-hoc encoder, base64
or `tolist()` blob in the report writer routes around the reviewed array contract. A later request to
commit PSD arrays or whole estimates needs its own schema and review; resolving #49 alone does not
authorize SA2.4 to expand its artifact set.

## 7. Executable stages

Each stage is additive and reviewable; none changes an admission rule, threshold or verdict.

- **External prerequisite before S2 publication — #49 or a reviewed design-clause narrowing.**
  This is not an SA2 estimator change and not an S-stage: resolve the policy gate in §6 in its own
  reviewed PR before committing machine-readable spectral outputs. S1 can be developed independently.
- **S1 — scalar characterization backend.** New module
  `analysis/sparse_spectral_characterization.py`: a per-gate sweep calling `periodogram_of_view` for
  every `supported_columns` entry of one `WindowView`, and
  `low_frequency_power_fraction(estimate, *, low_hz)` returning `(state, Φ, B, T, reason)` as typed
  scalars. Typed records are scalar-only (`ValueModel`): one per gate, one per cell carrying
  provenance, axis scalars, target rows and gate rows. The module holds **no** transform, taper,
  window weights, grid construction, normalization, admission arithmetic or verdict; its only
  arithmetic is §2's weighted band sum and ratio. *Gate:* one estimator call per supported gate; the
  fraction is §2's number.
- **S2 — report writer (S1 does not publish).** Writer module plus the CLI subcommand of §5, writing
  `reports/sparse-signal/` only. *Gate:* scalars only, digests bound, every `checks` entry true, `ok`
  true, frozen trees byte-unchanged.
- **S3 — tests and verifier (§8, §9).** *Gate:* full suite and Ruff clean; byte-for-byte regeneration
  at the recorded revision passes. **Not in SA2.4:** a notebook panel (D3), figures, Welch, coherence,
  resampling, peak search, condition comparison, cross-sitting synthesis, any new file under a frozen
  report tree.

## 8. Tests and refusals

Backend (`tests/test_sparse_spectral_characterization.py`):

1. `supported_columns` drives the sweep: count equals `ViewProvenance.supported_gates`; no
   unsupported column is asked of.
2. `Φ = 1` for a `defined` spectrum at `f_low = f_N`, on an even-`N` and an odd-`N` grid; `Φ ≈ 1` for a
   bin-centred low-frequency tone, `≈ 0` for a high-frequency tone; `Φ` monotone in `f_low`.
3. A constant trace is `defined-zero-power` with `Φ is None` and `B == 0.0` — **not** a refusal, and
   **not** a zero fraction (`sparse_periodogram.py:388-412` vs `:571-576`).
4. A duplicate-stamp axis is `refused-axis`: no gate row, `Φ is None`, no zero line.
5. Non-positive, non-finite, or above-`f_N` `low_hz` raises the typed error; an unsupported target still
   returns `band_supported=False` rather than raising.
6. `T` equals `window_normalized_mean_square_power` within the carried `parseval_relative_error`; the
   §2 invariants hold on synthetic and committed spectra.
7. No new estimator: an exact-name AST guard asserts the new module defines no transform/taper/grid/
   normalization name and calls neither `characterize_stamps` nor `spectral_admission` (pattern:
   `tests/test_notebook_spectral_preview.py:85, 661-678`).
8. Real committed: E128's 8.333-Hz rotor row keeps `analysis_supported=True, band_supported=False`
   with the backend's own reason; the 1-Hz row is supported on every cell
   (`tests/test_sparse_spectral_capability.py`).

Report (`tests/test_sparse_signal_report.py`):

9. Exactly 104 cells and Σ`supported_gates` gate rows; axis scalars identical across a cell's rows.
10. Every document `ok is True`, all `checks` true, `plan_fingerprint`/`analysis_commit` match
    (`test_sparse_report_live2.py:97-116`); `table_sha256` bound to the committed CSV by the
    repository digest rule (`:135-142`).
11. Byte-for-byte regeneration at the recorded revision (`:202-226`); every pre-existing file under
    `reports/` hashes as before.
12. Wording guard: no §10 forbidden phrase and no exploratory constant appears anywhere in the report.

## 9. Verifier — independent of the author

A verifier who did not write the module must be able to falsify it without reading it:

- **Independent recomputation.** The test recomputes `B`, `T` and `Φ` literally from
  `estimate.frequency_hz`, `estimate.psd`, `estimate.delta_f_hz` and the cell rule in a second,
  self-contained loop, and asserts agreement. No shared helper may serve both sides.
- **The published table is the record.** The verifier recomputes the table digest and the regeneration
  diff; a digest matching only a freshly generated tree fails.
- **Spot cells are named by label, not index**: E128's 8.333-Hz refusal and 1-Hz support are read from
  the published JSON, and each fraction's *state* is read, not inferred.
- **Stop conditions that halt the change rather than being worked around:** (a) any array or
  whole-`SpectralEstimate` artifact demanded → #49, separate change (§6); (b) any `Φ` outside
  `[0, 1]`, or `B > T`; (c) a cell count other than 104, or a gate count disagreeing with
  `supported_gates`; (d) a refusal rendered as a zero, or a zero as a refusal; (e) a fraction needing
  a value the estimate does not define; (f) any frozen-tree byte change; (g) any need for an
  exploratory number — an expected `Φ`, a floor, a spread — to make a check pass. No exploratory value
  enters the report or its checks.

## 10. No-go interpretations (binding; repeated in the report README)

1. **Refusal ⇏ absence.** `unsupported at 8.333 Hz` must never read as *no 8.333-Hz component exists*
   (`sa2-spectral-design.md:168-170`; `sparse_target_support.py:28-35`).
2. **No peak finding, dominant frequency, or recurrence label inferred from a spectral feature**
   (`sa2-3-notebook-preview-plan.md:176-181`).
3. **No physics words** — *vortex-dominated*, *recurrence-dominated*, *stronger low-frequency
   physics*, *better measurement configuration*: a large `Φ` is indistinguishable, from that number
   alone, across genuine flow dynamics, slow drift, finite-record structure and the detrending choice
   (`sa2-3-notebook-preview-plan.md:271-276`).
4. **No amplitude from a raw PSD peak height**; `Φ` is a band-integrated power *ratio*, not an
   amplitude (`sa2-spectral-design.md:143-146`).
5. **No anti-alias or transfer-function claim** — Nyquist support is a sampling-support statement for
   the stored profile sequence only, critical for E64 (`sa2-spectral-design.md:525-542`).
6. **No cross-sitting inference, no condition contrast** — SA5/SA6 (`sa2-spectral-design.md:619-620`;
   `sparse-signal-analysis-plan.md:212-228`).
7. **No borrowed floor, no independence claim** for profiles and gates
   (`sparse-signal-analysis-plan.md:16-19, 219-224`).
8. **`parseval_relative_error` is a QA field, not a scientific observable**
   (`sa2-3-notebook-preview-plan.md:170-174`).
9. **No new estimator, admission rule, threshold or tolerance**
   (`sa2-3-notebook-preview-plan.md:15-18`).
10. **The ~71.6 % E128 low-frequency smoke observation is not a committed artifact and not a
    per-recording number.** It is a single-gate descriptive observation from the SA2.2 review
    (`sa2-3-notebook-preview-plan.md:266-276`). SA2.4 produces its own per-`(cell, gate)` `Φ` under §2
    and **must not** quote 71.6 %, assert it as an expectation, or check against it; the exploratory
    per-sitting E128 means sometimes recited beside it are uncommitted and equally unquotable.

## 11. Corrections carried into this contract

The contract rejects these defects of the exploratory outline that preceded it, so a reviewer can hold
the change to the corrected definitions:

| # | defect in the exploratory outline | correction carried here |
| --- | --- | --- |
| 1 | proposed a new `reports/sparse-spectral/` root | the plan designates `reports/sparse-signal/` (`sparse-signal-analysis-plan.md:249-253`); its tension — publication placed after SA0–SA6 — is §12 D1 |
| 2 | recomputed `Σ_k psd[k]·Δf` as the denominator | the estimate's own `integrated_psd_power`, tied by construction to `window_normalized_mean_square_power` (`sparse_periodogram.py:142-148, 569-577`), is **read**, not recomputed |
| 3 | `Σ_{f_k ≤ f_low}` counted whole bins by centre | §2 weights by cell overlap: a straddling bin counts in part, and DC keeps its half-width cell boundary, earning a whole weight only past `Δf/2` — which it always does here |
| 4 | endpoint and units left open | §2 fixes a closed `[0, f_low]` band measured by intersection length, `f_low = 1.0 Hz`, `B`/`T` in `(mm/s)^2`, `Φ` dimensionless |
| 5 | an optional scalar conflated a refused axis with a defined zero | §2 carries three named states: a refusal was not measured, a defined zero was |
| 6 | gate subset left open | §1 enumerates every supported gate through `supported_columns` and records the count, so completeness is checked rather than assumed (D4) |
| 7 | detrending unspecified | §1 fixes `mean` on both views |
| 8 | within-sitting repeats treated as a possibly usable spread | §4 keeps the (substantial) spread descriptive and forbids its use as a floor |
| 9 | exploratory numbers quotable | the 71.6 % datum, any per-sitting mean and any assumed spread stay out of the report, its checks and its wording (§9(g), §10.10) |

## 12. Decisions fixed for this slice (review may revise the contract before implementation)

- **D1 — publish timing:** start the designated `reports/sparse-signal/` root now with explicitly
  SA2.4-named scalar files; SA5–SA7 may add their own synthesis later. This is a staged use of the
  sparse plan's eventual publish root, not a claim that SA0–SA6 synthesis is complete.
- **D2 — detrending:** publish `mean` only. A `mean+linear` sensitivity table requires a separately
  reviewed protocol; it is never averaged with the primary number.
- **D3 — notebook:** no new panel in SA2.4; SA2.3 already gives a usable per-view preview, and this
  slice publishes the descriptive scalar report.
- **D4 — gate scope:** all supported gates (§1); any subset needs a reviewed change of §1, never a
  silent writer-side selection.
