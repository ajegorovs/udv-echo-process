# SA2.3 — notebook spectral preview

**Status: PLAN, not started.** This document is the contract for SA2.3, transcribed from the
SA2.2 final review. It is the authority for what may and may not be built; the design record it
implements against is [`sa2-spectral-design.md`](sa2-spectral-design.md) (§A–§J), and the merged
backend it exposes is `analysis.sparse_periodogram` (SA2.2, merged at `9ba46c4`).

> **SA2.3 adds no new spectral estimator or scientific interpretation.**

Everything below follows from that one sentence. The notebook's job in this stage is **exposure
and inspection of already-reviewed backend results** — not new signal-processing methodology.

Rejected at review time and not to be reintroduced: peak finding, automated frequency bands,
low-frequency integrated-power metrics, condition-comparison tables, depth–frequency maps,
cross-gate spectra, cross-sitting comparison, Welch, coherence, modal/SVD analysis, serialization
(`#49`). Those belong to SA2.4 or SA3. SA2.3 also adds **no new estimator and no new admission
rule** — no threshold, tolerance or verdict changes, and the committed diagnostic differences of
SA2.2 stay diagnostics.

## The shape of the notebook stays

```text
selection
→ backend call
→ display
```

not:

```text
selection
→ notebook arithmetic
→ plot
```

Concretely: no `np.fft`, no taper construction, no PSD normalization, no frequency-grid
construction and no admission arithmetic in a notebook cell. The notebook calls the backend and
draws what it returns. Every number the notebook *states* comes from a field of a backend result.

## The surface SA2.3 builds on

It reuses the SA1 selection path already in `notebooks/signal_explorer.py` — no second,
independent time-window selector is introduced:

| what | where it already lives | SA2.3 reuses |
| --- | --- | --- |
| pass / job / recording | `dataset_picker` → `job_picker` → `recording_picker` | unchanged |
| view | `sa1_view_controls.gate_view` (options are `VIEW_LABELS`, labels carry `VIEW_RULES`) | unchanged |
| the one window decision | `sparse_view_checkpoint` → `sparse_view` / `sparse_view_error` | `sparse_view` directly |
| gate / depth | `gate_stats` → `gate_picker` → `gate_position` (`position`, `position_note`) | `position` + `position_note` |
| detrending | `detrending_picker` (`sparse_recurrence.Detrending`) | the same vocabulary |
| figures | `mo.ui.plotly` / `go` | the same |

**One `WindowView`, one spectrum.** A spectrum labelled `primary-comparison` must come from
exactly the same `WindowView` the heatmap, gate statistics and recurrence used for that label —
likewise `full-record` and `exploration`. This is why the notebook keeps a single view checkpoint
and SA2.3 hangs off it rather than computing a window of its own.

## A. Reuse the existing view selection

No independent spectral time-window selector. `sparse_view` is the input; if it is `None` because
the view module refused the selection, every spectral display shows that refusal and nothing else.

## B. Spectral backend call

Only the equivalent of:

```python
periodogram_of_view(
    selected_view,
    depth_mm=selected_depth,
    quantity=point.quantity,
    unit=point.unit,
    detrending=selected_detrending,
)
```

with `selected_depth = float(gate_stats.depths_mm[position])` — the same depth resolution SA1
already performs — and `selected_detrending = detrending_picker.value`. The `quantity` and `unit`
are passed explicitly, exactly as SA1's recurrence call already passes them
(`recurrence_of_view(..., quantity=str(point.quantity), unit=str(point.unit), ...)`), so the
spectrum names its own measured quantity instead of relying on the signature defaults. No spectral
arithmetic in cells; no re-derived grid, taper, normalization or verdict.

## C. Detrending control

The SA1 `Detrending` vocabulary, unchanged: `mean` (default), `mean+linear`, `none`. The displayed
PSD states which one produced it, because the backend result carries it
(`SpectralEstimate.detrending`) rather than the cell remembering it.

**The coupling question is decided explicitly, not by convenience.** SA1's recurrence control is
its own display's control; SA2.3 does not silently re-point it. If the PSD and the recurrence are
shown for the same gate, each display names the detrending *it* used, and the notebook does not
quietly change SA1 recurrence semantics for UI tidiness. If the shared `detrending_picker` is used
for both, that is stated in the cell and shown next to both results — an intentional coupling, not
an accident.

## D. Timebase / admission summary

Backend-derived, stated above or beside the PSD, every value read from the result (none
recomputed):

```text
N · actual span · dt_eff · fs_eff · Nyquist · delta_f · 1/span duration scale
max relative timing error · spectral-uniformity tolerance · admission verdict
```

`max_relative_timing_error` and the tolerance come from `SpectralAdmission` /
`TimebaseCharacterization`; the diagnostic interval-deviation and gap information stays
accessible but secondary. For the committed datasets the reader must be able to see **why** the
estimator was admitted.

## E. PSD plot

`frequency_hz` against `psd`, the backend arrays used directly:

```text
x: frequency [Hz]
y: PSD [(mm/s)^2 / Hz]
```

Default extent: the full supported frequency range. A low-frequency zoom is a **display-only**
option — it changes plot limits, never the estimator input, and it is labelled as a zoom. The
underlying PSD is never truncated.

## F. Target-frequency rows

For at least the **1.0 Hz** recurrence-scale probe and the **25/3 Hz ≈ 8.333 Hz** nominal rotor
reference, each row is asked of `target_frequency_support(estimate.admission, target_hz, label=...)`
— the admission carried *inside* the returned `SpectralEstimate`, never a second admission derived
in the notebook — and shows: overall supported/refused, band support, analysis/admission support,
the target, Nyquist, nearest bin, bin offset, frequency resolution, `cycles_in_view` for *this*
actual view, and the reason. These rows accompany a **defined (admitted) spectrum**; a
`REFUSED_AXIS` estimate carries no PSD and no admission-granted spectrum, so its target rows report
the estimator refusal instead.

The wording rule is binding:

```text
unsupported at 8.333 Hz        ⇏        no 8.333-Hz signal
```

For E128 the UI **quotes the backend reason** rather than paraphrasing it. The backend's
`TargetFrequencySupport.band_reason` for a target at or above Nyquist is, verbatim,
`"{target} Hz is at or above this axis's Nyquist frequency {nyquist} Hz: band-supported requires
strictly below it"`; for E128's 8.333 Hz rotor reference on the primary-comparison view the row
reads `8.33333 Hz is at or above this axis's Nyquist frequency 5.73438 Hz: band-supported requires
strictly below it` (the Nyquist value is the view's own, ≈ 5.73 Hz for both views). "At or above" is
the backend's wording, and "this axis's Nyquist" is the adopted-rate Nyquist the characterization
published — the UI does not substitute "above" or "this recording's".

## G. Target markers

A target marker is drawn **only inside the measurable band**. For E8/E20/E64: both a 1 Hz and an
8.333 Hz marker. For E128: the 1 Hz marker only — **no 8.333 Hz vertical line inside the PSD axes
as though it were part of the measured range**. The refusal is surfaced in the target-support
panel, and the full axis ending below 8.333 Hz reinforces it visually.

**The Nyquist support a marker rests on is binding-caveated** (design
[anti-alias / transfer-function limitation](sa2-spectral-design.md)). 8.333 Hz below an E8/E20/E64
axis's Nyquist means only that **the sampled profile sequence can represent that frequency without
the basic Nyquist impossibility** — it does **not** mean the amplitude is unbiased, that
higher-frequency content cannot alias into it, or that emissions/profile carries no temporal
averaging at that frequency. Nyquist support is a sampling-support statement for the stored profile
sequence, not a calibrated temporal transfer-function correction and not the instrument's
anti-alias response. This matters most for E64, whose target sits closest to its band edge; no
transfer function is resolved in SA2, and a marker inside the band must not be worded as a
measured, calibrated or anti-aliased amplitude.

## H. Display-only descriptive quantities

Secondary, available but not prominent: integrated PSD power, window-normalized mean-square power,
ENBW, and the Parseval residual. `parseval_relative_error` is a **numerical QA field, not a
scientific observable** — it is not plotted as a headline and not compared across jobs.

## I. Low-frequency preview

A low-frequency zoom around the first few Hz is allowed as inspection. SA2.3 must not introduce
automatic peak picking, a "dominant vortex frequency", recurrence labels inferred from peaks, or
band-power comparison between conditions. A reader may look at a feature near ~1 Hz; the notebook
must not turn that visual feature into a claim.

## J. Relationship to SA1 recurrence

Showing the time trace, the ACF and the PSD for one source/view/depth in one explorer is useful —
it lets a reader ask whether an apparent ~1 s recurrence has corresponding low-frequency spectral
structure. The notebook must not say `ACF confirms PSD` or the reverse: they are two descriptive
estimators of the same trace, and are not numerically fused in this stage.

## K. Refusal rendering

These four display states are exercised:

| state | rendering |
| --- | --- |
| admitted spectrum | PSD visible |
| spectrally refused axis | **no empty or zero plot** — the `SpectralAdmission` refusal and its failed conditions |
| target above Nyquist | PSD visible where the estimator is admitted; the target marked unsupported (E128 / 8.333 Hz is the committed real-data test) |
| constant signal / zero PSD | a valid zero spectrum shown as zero, **not** as an estimator refusal |

The distinction `defined zero` vs `undefined/refused` is preserved in the UI.

**Pre-estimator unavailable states are rendered too, and they are not estimator verdicts.** Before
any `SpectralEstimate` can exist the notebook can hold no spectrum at all: no view (`sparse_view`
is `None` because `SparseViewError` refused the selection — §A), or no resolved gate (`gate_stats`
is `None`, or `position` is `None`). Each is shown as the module's/notebook's own stated absence,
with no PSD, no zero line and no fabricated spectrum — the same "no empty or zero plot" rule as a
refused axis, kept distinct from it so a missing view is never read as a spectral refusal.

**The stale-gate guard is a spectral consumer too.** When a view change leaves the previously
picked gate outside the new view, the `position_note` fallback resolves the position to the middle
supported gate *and says so*; the spectrum is computed at that fallback gate and the note is shown
beside it, rather than silently drawing a spectrum for a different gate than the one named.

## L. Source / provenance display

Every displayed spectrum makes recoverable: job, point/order, source path and digest, view,
gate/depth, detrending, estimator and taper convention. No notebook-side provenance structure is
created — it is `SpectralEstimate` plus the shared `ViewProvenance`, displayed, and each field is
read from the object that already owns it:

- `ViewProvenance` (carried on `SpectralEstimate.provenance`) supplies **job** (`job`), **point
  label and order** (`point_label`, `order`), **source path and digest** (`relative_path`,
  `source_sha256`) and **view** (`view`, with `view_rule`);
- `SpectralEstimate` itself supplies **gate/depth** (`gate_index`, `depth_mm`), **quantity/unit**
  (`quantity`, `unit`), **detrending** (`detrending`), and the **estimator and taper convention**
  (`estimator_name`, `taper_name`, `taper_convention`).

The **pass is not a `ViewProvenance` field** and must not be presented as one: the pass (the
committed dataset) is the notebook's own selection from `analysis.sparse_passes`
(`dataset_picker` → `COMMITTED_PASSES`), a presentation choice the backend records do not carry.
The spectrum's own recording identity is the `job` / `point_label` / `order` / `source_sha256`
above; the pass is stated as the notebook's selection beside it, never as a provenance field.

## M. Primary / full-record honesty

Switching `primary-comparison ↔ full-record` visibly updates N, span, `delta_f`, cycles, the PSD
and the target-support fields. A full-record spectrum is never presented under the
primary-comparison label. The two spans are numerically close, so this is verified by an executed
notebook pass rather than by eye.

## N. SA2.3 tests

The backend estimator tests stay where they are (SA2.2). SA2.3 adds notebook/static checks
sufficient to verify: it imports and calls `periodogram_of_view`; it contains no FFT implementation
and no taper/PSD-normalization arithmetic; target rows call `target_frequency_support`; E128
renders the 8.333-Hz refusal; view switching propagates into spectral provenance; the stale-gate
guard (`position_note`) still holds for spectral consumers; and no spectrum is drawn for a refused
estimator.

Verification runs `marimo check` and an executed HTML export, requiring zero `marimo-error` and
zero Traceback, and — where feasible — a scratch/preconfigured execution exercising primary,
full-record, E128, a changed gate and a changed detrending. Live widget-driving is not claimed if
the shadow DOM prevents it. The executed-notebook evidence must be **reviewable remotely**: the
executed HTML export (or an equivalent captured execution report) is committed at a reviewable
path outside the frozen `reports/` tree — the merge gate's "no changes under frozen `reports/`"
stands, so the evidence is placed where a reviewer without the machine can open it, not left as a
local-only run.

## O. Out of scope

As listed at the top: peak finder, automated frequency bands, low-frequency integrated-power
metrics, condition comparison tables, depth–frequency maps, cross-gate spectra, cross-sitting
comparison, Welch, coherence, modal/SVD analysis, serialization (`#49`). SA2.4 or SA3.

## Interpretation guard (carried from the SA2.2 review)

One **descriptive smoke observation** — recorded in the SA2.2 review, not a committed numeric
artifact (no `reports/` file and no frozen record carries it) — is that **~71.6 % of E128's
integrated PSD lay at or below 1 Hz**. That stays a descriptive observation and nothing more: the
number is not a committed artifact, and SA2.3 must not cite it as one. SA2.3 may **show** it; SA2.4
may **quantify** it; physical interpretation comes later. Wording such as *vortex-dominated*,
*recurrence-dominated*, *stronger low-frequency physics* or *better measurement configuration*
must not enter SA2.3 (or be inferred from the number there): a large low-frequency power fraction
can arise from genuine flow dynamics, slow drift, finite-record structure and the detrending choice
alike, and from that number alone they are not distinguishable.

## SA2.3 merge gate

Before review, report:

1. merged SA2.2 base;
2. exact notebook/backend files changed;
3. static notebook checks;
4. executed HTML result (remotely reviewable, outside frozen `reports/`);
5. primary/full-record state verified;
6. gate switching verified;
7. detrending switching verified;
8. real E128 8.333-Hz refusal rendered correctly;
9. no notebook spectral arithmetic;
10. no changes under frozen `reports/`;
11. full/focused tests and Ruff.

and state explicitly:

```text
SA2.3 adds no new spectral estimator or scientific interpretation.
```
