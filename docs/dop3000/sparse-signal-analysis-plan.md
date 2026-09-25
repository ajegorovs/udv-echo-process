# Sparse UDV signal characterization — proposed work plan

> **Status:** proposal only; no scientific analysis or parameter decision is made by
> this document. The committed `sparse-mixer-live-2` recordings are available;
> SA0 is the first implementation gate. The frozen WP0–WP5 results for
> `sparse-mixer-live-1` remain authoritative and unchanged; do not clone them
> wholesale for live-2 or silently revise their decision table. Stage-2 E20/E64
> is a separate, explicitly identified design.

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

## Physical question and preview contract

The vessel is approximately 100 × 100 × 50 mm (width × length × height).
The ultrasonic beam enters orthogonally to a wall at approximately three-quarters
of the way along that wall and mid-height, traversing the vessel depth. It measures
**one signed line-of-sight velocity component**, not the in-plane speed or a
reconstruction of the central circulation and corner vortices. Preserve the
instrument's native gate-depth coordinate; document the entry wall, beam sign,
physical mapping of gate zero and CFD sampling line before overlaying CFD. Do
not infer those conventions from the dimensions or silently relabel gate depth.

The observed profile resembles a CFD profile qualitatively, with a reported
20–40% velocity-magnitude difference. The central vortex may wander or oscillate
on an approximately 1 s timescale, but that period is a hypothesis, not a
measurement. The first questions are whether its motion is detectable on this
beam, and whether burst, pitch or emissions change measured profile shape,
magnitude, fluctuation level or apparent timescale enough to matter relative to
same-settings variation. A moving flow crossing a fixed beam, acquisition-order
drift and instrument sensitivity are distinct explanations. Do not attribute
the CFD discrepancy to UDV settings unless a like-for-like projected CFD profile,
coordinate alignment, time averaging and an effect of comparable magnitude and
spatial pattern support that attribution. No CFD overlay is a prerequisite for
previewing the committed recordings.

**Preview-first delivery:** every analysis slice that produces inspectable results
ends with a runnable marimo checkpoint using the committed recordings, not a
large notebook added after all estimators are finished. The notebook is a thin
view over tested functions in `src/`; provide a default selection from the
second mixer-enabled sitting, show selected file/job/condition and units, and
make QC and unsupported metrics visible rather than silently empty. Distinguish
exploratory controls from the fixed 12 s comparison. Keep a usable checkpoint
at each PR boundary: ingest/selection first, then basic time–depth views,
then temporal/spectral views, then cross-sitting contrasts. Publish deterministic
reviewer-readable evidence alongside notebook views; notebook state is not the
sole record of a result.

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

### SA0 — second-pass ingest and first notebook checkpoint

Parameterize WP0's dataset/plan identity and output root without changing
live-1 defaults or its frozen bytes. Reuse the existing `_sparse_pass` keyword
path and WP0's plan-point binding/refusals. Produce
`reports/sparse-mixer-live-2/points.csv` and `qc-summary.json` under the same
schema, with the plan and source hashes. Gate: live-1 artefacts byte-identical;
live-2 binds 26/26 planned recordings with nine expected jobs, decoded settings,
content and 12 s coverage; explicit failure rows/refusals. Do not regenerate
WP1–WP5 or move their decision table. Add a minimal `signal_explorer.py` notebook
checkpoint: dataset → job → recording → channel selection, selected provenance,
QC table and a native time–depth heatmap from existing reader/view helpers.
The selected live-2 recording must load and render in an executed HTML export;
changing selection in a live session must read back the chosen record. Do not
make SA0 depend on unimplemented SA1–SA3 estimators.

### SA1 — single-record baseline and time domain

Reuse existing `gate_metrics` (mean, median, IQR, RMS, zero fraction).
First deliver per-gate mean and variability profiles, representative gate traces,
time slices and distributions in the SA0 notebook, with native depth, signed
velocity and a visible primary/exploratory-view label. Compare observed profile
magnitude and shape with same-settings controls before reducing to one number.
Then add per-gate standard deviation, MAD (state its scaling), min/max,
q05/q25/q50/q75/q95, skewness and kurtosis with explicit degenerate/constant-
trace behavior. Define depth reductions and their weighting; keep gate profiles
rather than collapsing them prematurely.

For temporal recurrence, subtract the trace mean by default before normalized
ACF; name any additional detrending method and show raw traces alongside it.
A constant or effectively zero-variance trace has undefined normalized ACF,
not an all-zero correlation curve. Report first zero crossing, 1/e decay,
integral time and descriptive recurrence peaks only when supported by the
window; seek but do not assume an approximately 1 s feature. Twelve seconds
contains only about twelve candidate cycles, so report frequency/lag resolution
and avoid a precise period claim from a weak peak. Test on constant,
intermittent, correlated and known-period synthetic traces and on the
committed reader path. No pseudoreplicate confidence intervals. Each accepted
backend increment extends the executed notebook preview in the same PR.

### SA2 — spectral and sampling support

Estimate effective sample rate from actual timestamps; declare a jitter/gap
threshold and refuse or document resampling before applying evenly sampled
Welch/STFT methods. Express segments and overlap in **seconds**, derive sample
counts per recording, and report rate, Nyquist, bin spacing, achieved segment
length and segment count. Add bandpower and a shared-frequency-support mask;
refuse bands outside a participant's Nyquist instead of interpolating them into
existence. Test known tones, noise, jitter/gaps and the E8/E20/E64/E128 rate
regime, including the all-four support boundary. Preview a plausible near-1 Hz
vortex-motion band alongside the raw trace and ACF, but specify its band limits
before comparing conditions; a selected peak is exploratory, not a detected
forcing frequency. Compare fixed physical-duration segments, not fixed profile
counts, across different sampling rates. Extend the notebook with PSD,
spectrogram and explicit unsupported-band labels in this slice.

At nominal 500 RPM, 8.33 Hz and harmonics are **nominal rotor reference
markers**, distinct from the hypothesized near-1 Hz vortex motion, not measured
RPM, phase or vortex frequency. Approximately 65.8/44.6/20.5/11.5 profiles/s
for E8/E20/E64/E128 imply Nyquist near 32.9/22.3/10.2/5.7 Hz; E128 cannot
resolve a nominal 8.33 Hz rotor fundamental, while comparisons across all four
must stay below their shared Nyquist. Aliasing cannot be ruled out merely by
excluding frequencies above Nyquist.

### SA3 — optional spatial and modal description, after the first usable explorer

Only advance when the native profiles and traces suggest a question it answers.
Compute native-grid depth covariance/correlation, with an explicit rule for
constant gates, and estimate correlation versus physical separation and length
only when the support and estimator are meaningful. Add centered per-recording
SVD/POD: singular values, energy shares, spatial modes and temporal coefficients.
A single-beam mode is a pattern of projected velocity along that line, not a
resolved vortex shape or the corner-vortex field. Test low-rank synthetic fields
and degenerate matrices; fix the sign convention or compare modes sign-
invariantly. Cross-grid mode comparisons require a declared common-grid
projection and must not claim fine structure created by upsampling. Add these
views to the notebook only alongside the corresponding tested estimator.

### SA4 — single-record explorer acceptance checkpoint

Harden the `notebooks/signal_explorer.py` started in SA0, using the sidebar
recording → channel → time → gate interaction in
`channel_preview_sidebar.py`. Show QC/metadata, heatmap, time slice, gate trace,
native mean/variability profiles and distributions; expose ACF and Welch PSD
only once SA1/SA2's estimator tests and sampling guards pass. Spectrogram,
spatial correlation and POD are conditional on the corresponding accepted
backend slices, not prerequisites for the first useful preview. Label the
selected record, physical units, view/window and nominal-versus-observed
markers; failed/undefined estimates get an explanation, not zero curves.
Controls for analysis windows and methods call backend functions only.
Accept every checkpoint with `marimo check` **and executed HTML export** against
a real committed file; static validation alone does not run cells. For live
widget behavior, change dataset/job/recording and time/gate selections, then
read their values and outputs back. Export cannot prove widget transitions.
When the optional inspection provider is available, use its live-state read-back;
otherwise verify those interactions in a live browser session and state which
checks were not automated.

### SA5 — sitting-level effects and agreement

Bind each condition to its planned job and controls through the shared ingest.
Compute burst and pitch corner contrasts, pitch × burst difference-of-differences,
E8/E64/E128 relative to E20, and reference/anchor changes **within each
sitting**, retaining acquisition order and comparable physical support. Orient
contrasts identically across sittings; use the appropriate sitting's and metric's
own floor (a mean-profile floor does not bound ACF or PSD). If same-condition
replication cannot support a metric-specific floor, show its effect as
**descriptive / not resolvable**, with its missing comparison named: do not
borrow another metric's floor, treat profiles/gates as independent runs or call
an apparent difference a UDV-induced bias. Screen magnitude and profile-shape
changes against comparable controls before discussing whether they approach the
reported CFD gap. Existing WP artefacts remain frozen: reuse their definitions
and published evidence, compute new metrics separately and name any changed
endpoint. Stage-2 E20/E64 is a separate contextual comparison, not another
interchangeable sitting.

Publish depth-resolved effects for live-1 and live-2 side by side, then their
difference, sign agreement, profile correlation (if nonconstant), RMS difference,
signed depth average and peak-location difference where defined. Avoid one
opaque reproducibility score or p-values over gates/profiles. Optional block
bootstrap gives **within-record conditional uncertainty** only; choose blocks
using estimated correlation time and no shorter than the nominal 0.12 s
revolution, with the assumption stated.

### SA6 — comparison notebook; SA7 — synthesis

Add `notebooks/sparse_signal_comparison.py` only when SA5 has tested
comparable metrics: realization/axis/metric/depth selectors, condition matrix
with QC, native and aligned profiles, each sitting's oriented effect and its
applicable floor or explicit unavailability, the between-sitting difference,
and sampling-aware temporal/spectral comparisons. Label unavailable frequency
bands rather than plotting them as zero. Gate as for SA4, including a real
two-sitting selection and read-back of widget state. Until then, the single-
record explorer remains the working preview; do not block it on SA5/SA6.

After review of SA0–SA6, publish `reports/sparse-signal/` with deterministic
CSV/JSON (NPZ for documented arrays as needed), figures and a README giving
source digests, units, view/estimator settings and regeneration commands. This
is where evidence can support *proposed* parameter choices; moving the frozen
WP decision table is a separate reviewed change.

## Delivery split and non-goals

Milestone 1 (preview sweep #2): SA0 delivers a selection/QC/heatmap notebook
from the committed files; SA1 adds native profiles, traces and a tested
near-1 s recurrence view; SA2 extends that same notebook with sampling-aware
spectra. The user can run and inspect the notebook at **each** checkpoint,
without waiting for the full milestone. SA4 is an acceptance/hardening pass,
not the first notebook delivery. Milestone 2 (sensitivity): SA5 adds
sitting-specific contrasts, SA6 presents them in a comparison notebook, then
SA7 follows evidence review. SA3 is optional after the first useful preview.
Make small reviewable PRs with backend tests and a working notebook checkpoint
in the same slice; preserve deterministic non-notebook evidence for external
review. Existing SciPy/NumPy/Plotly cover the proposed primitives; check actual
dependencies before adding any. Defer wavelets, DMD, entropy/recurrence methods,
classifiers, elaborate inference, gate-wise significance tests and automatic
velocity de-aliasing. A quantitative CFD comparison is a separately gated slice
once geometry, projection, coordinates and simulation outputs are available.
