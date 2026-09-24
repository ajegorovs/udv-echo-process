# Sparse UDV signal characterization — proposed work plan

> **Status:** proposal only; no scientific analysis or parameter decision is made by
> this document. Depends on the committed `sparse-mixer-live-2` recordings in PR #34.
> The frozen WP0–WP5 results for `sparse-mixer-live-1` remain authoritative and
> unchanged; do not clone them wholesale for live-2 or silently revise their
> decision table. Stage-2 E20/E64 is a separate, explicitly identified design.

## Question and unit of evidence

Characterize velocity versus time and native depth, measure how burst length,
spatial pitch and emissions affect the *observed* signal, and ask whether
condition effects recur in the two mixer-enabled sittings. Treat the hierarchy
as sitting → job → recording → profiles × gates: profiles and gates are
correlated samples, **not independent realizations**. Report each sitting's
contrast separately before any cross-sitting comparison. Two sittings permit a
reproducibility check, not a population-level confidence claim. The first
zero-signal sparse pass remains acquisition evidence, not a third live replicate.
No tachometer, echo or energy channel is present in these velocity files; do not
infer measured mixer speed, SNR or receiver saturation.

## Boundaries and shared views

Read `.BDD` with `udv_echo_process.io.load` and reuse
`analysis.sparse_inventory`, `analysis._sparse_pass`,
`analysis._native_grid`, and the frozen WP floor/contrast artefacts rather
than rebuilding their binding, refusals or reductions. `decode_pass` already
accepts `dataset_root`, `plan_path` and `plan_name`; inspect its callers and
WP0's hard-coded live-1 defaults before generalizing the remaining ingest.
Keep scientific functions in `src/udv_echo_process/analysis/`, returning typed,
unit-bearing results with provenance (source identity, view, time/depth support,
method settings). Notebooks select inputs and display those results; they do
not implement estimators. Exports must be deterministic and reviewer-readable
without a live notebook.

* **Primary comparison:** each recording's stored timestamps over the designed
  leading 0–12 s. Refuse insufficient coverage; never widen it to the
  instrument's extra retained fraction of a second.
* **Full record:** all valid stored profiles for ACF, spectra and stationarity
  diagnostics; label it separately from the primary view. Duration varies.
* **Exploration:** explicitly selected time/depth bounds in the notebook. These
  must never silently replace the primary comparison.
* **Depth:** gate-local metrics on native positions; between-grid effects on
  common physical support and knots no finer than the coarsest participating
  pitch. Compute spatial derivatives/correlation lengths on native grids before
  projection. Record interpolation and invalid/zero-sample policy.

QC records finite/zero fractions, timestamps and gaps, native pitch, decoded
settings, actual period and Nyquist, retention, and common support. A valid
file is not necessarily a valid physical observation; compare content with
same-condition controls and label limits of unobserved rig state.

## Incremental slices and acceptance gates

### SA0 — second-pass ingest (after PR #34 lands)

Parameterize WP0's dataset/plan identity and output root without changing
live-1 defaults or its frozen bytes. Reuse the existing `_sparse_pass` keyword
path and WP0's plan-point binding/refusals. Produce
`reports/sparse-mixer-live-2/points.csv` and `qc-summary.json` under the same
schema, with the plan and source hashes. Gate: live-1 artefacts byte-identical;
live-2 binds 26/26 planned recordings with nine expected jobs, decoded settings,
content and 12 s coverage; explicit failure rows/refusals. Do not regenerate
WP1–WP5 or move their decision table.

### SA1 — single-record baseline and time domain

Reuse existing `gate_metrics` (mean, median, IQR, RMS, zero fraction) and add
per-gate standard deviation, MAD (state its scaling), min/max, q05/q25/q50/
q75/q95, skewness and kurtosis with explicit degenerate/constant-trace behavior.
Define depth reductions and their weighting; keep gate profiles rather than
collapsing them prematurely. Add trace extraction, optional detrending with a
stated method, normalized ACF, first zero crossing, 1/e decay, integral time
when defined, and descriptive recurrence peaks. Test on constant, intermittent,
correlated and known-period synthetic traces and on the committed reader path.
No pseudoreplicate confidence intervals.

### SA2 — spectral and sampling support

Estimate effective sample rate from actual timestamps; declare a jitter/gap
threshold and refuse or document resampling before applying evenly sampled
Welch/STFT methods. Express segments and overlap in **seconds**, derive sample
counts per recording, and report rate, Nyquist, bin spacing, achieved segment
length and segment count. Add bandpower and a shared-frequency-support mask;
refuse bands outside a participant's Nyquist instead of interpolating them into
existence. Test known tones, noise, jitter/gaps and the E8/E20/E64/E128 rate
regime, including the all-four support boundary.

At nominal 500 RPM, 8.33 Hz and harmonics are **nominal reference markers**,
not measured RPM or phase. Approximately 65.8/44.6/20.5/11.5 profiles/s for
E8/E20/E64/E128 imply Nyquist near 32.9/22.3/10.2/5.7 Hz; E128 cannot
resolve a nominal 8.33 Hz fundamental, while comparisons across all four must
stay below their shared Nyquist. Aliasing cannot be ruled out merely by
excluding frequencies above Nyquist.

### SA3 — spatial and modal description

Compute native-grid depth covariance/correlation, with an explicit rule for
constant gates, and estimate correlation versus physical separation and length
only when the support and estimator are meaningful. Add centered per-recording
SVD/POD: singular values, energy shares, spatial modes and temporal coefficients.
Test low-rank synthetic fields and degenerate matrices; fix the sign convention
or compare modes sign-invariantly. Cross-grid mode comparisons require a declared
common-grid projection and must not claim fine structure created by upsampling.

### SA4 — single-record explorer

Add `notebooks/signal_explorer.py` using the sidebar recording → channel → time
→ gate interaction in `channel_preview_sidebar.py`. Expose QC/metadata,
heatmap, time slice, gate trace, distributions, ACF, Welch PSD with nominal
marker and bandwidth metadata, spectrogram, spatial correlation and POD scree/
mode/coefficient. Controls for analysis windows and methods call SA1–SA3 only.
Accept with `marimo check` **and executed HTML export** plus a real fixture
smoke check; static validation alone does not run cells.

### SA5 — sitting-level effects and agreement

Bind each condition to its planned job and controls through the shared ingest.
Compute burst and pitch corner contrasts, pitch × burst difference-of-differences,
E8/E64/E128 relative to E20, and reference/anchor changes **within each
sitting**, retaining acquisition order and comparable physical support. Orient
contrasts identically across sittings; use the appropriate sitting's and metric's
own floor (a mean-profile floor does not bound ACF or PSD). Existing WP artefacts
remain frozen: reuse their definitions and published evidence, compute new
metrics separately and name any changed endpoint. Stage-2 E20/E64 is a
separate contextual comparison, not another interchangeable sitting.

Publish depth-resolved effects for live-1 and live-2 side by side, then their
difference, sign agreement, profile correlation (if nonconstant), RMS difference,
signed depth average and peak-location difference where defined. Avoid one
opaque reproducibility score or p-values over gates/profiles. Optional block
bootstrap gives **within-record conditional uncertainty** only; choose blocks
using estimated correlation time and no shorter than the nominal 0.12 s
revolution, with the assumption stated.

### SA6 — comparison notebook; SA7 — synthesis

Add `notebooks/sparse_signal_comparison.py`: realization/axis/metric/depth
selectors, condition matrix with QC, native and aligned profiles, each sitting's
oriented effect and its applicable floor, the between-sitting difference, and
sampling-aware temporal/spectral comparisons. Label unavailable frequency bands
rather than plotting them as zero. Gate as for SA4, including a real two-sitting
selection and read-back of widget state.

After review of SA0–SA6, publish `reports/sparse-signal/` with deterministic
CSV/JSON (NPZ for documented arrays as needed), figures and a README giving
source digests, units, view/estimator settings and regeneration commands. This
is where evidence can support *proposed* parameter choices; moving the frozen
WP decision table is a separate reviewed change.

## Delivery split and non-goals

Milestone 1: SA0–SA4 (understand one recording and expose the second sitting's
QC). Milestone 2: SA5–SA6 (repeatability of parameter effects), then SA7 only
after the evidence is reviewed. Slice implementation into small reviewable PRs
with synthetic tests before notebook surfaces. Existing SciPy/NumPy/Plotly
cover the proposed primitives; check actual dependencies before adding any.
Defer wavelets, DMD, entropy/recurrence methods, classifiers, elaborate
inference, gate-wise significance tests and automatic velocity de-aliasing.
