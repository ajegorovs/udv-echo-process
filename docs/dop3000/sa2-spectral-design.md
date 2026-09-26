# SA2 — spectral and sampling support: design and backend contract

> **Status:** design for review, revised after the first review round. This slice is
> **documentation only** — it contains no FFT, periodogram, Welch, PSD or resampling code. It
> fixes the contract SA2 must satisfy before any estimator exists, so the estimator is chosen to
> fit the axis rather than the axis bent to fit the estimator.

## The governing rule

**Characterize the timestamps first; admit or refuse the estimator second; ask the target
question third. Never interpolate.**

The review's central correction is in that third step: **estimator admission and target-frequency
support are different questions**, and conflating them was the first version's main defect. A
recording can perfectly well support a valid uniformly-sampled spectrum while a *particular
requested target* lies above Nyquist. The two answers must be able to differ, and the types must
show it:

```
assuming the view passes the eventual SA2 spectral-uniformity admission:
    E128 periodogram   = ADMITTED
    8.333-Hz target    = UNSUPPORTED     (both can be true at once)
```

That first verdict is **conditional at the design stage**: `SPECTRAL_UNIFORMITY_TOL` does not exist
yet (§A, §J), so nothing in this document claims a measured admission verdict for any committed
recording.

## What this slice inherits from SA1 (do not re-cut)

| SA1 artefact | SA2's use |
| --- | --- |
| `analysis._sparse_view.SparseView` | the view label and rule on every spectral result |
| `WindowView` | the **only** cut. SA2 must not slice time or depth independently |
| `ViewProvenance` | shared source identity, window, extents, view rule |
| `native_depth_extent_mm` / `pass_support_mm` / `participating_depth_extent_mm` | inherited as the three differently-meant extents |
| `classify_timebase` + `TimebaseVerdict` | the axis verdict SA2's admission policy consumes |
| `recurrence_of_view` | the precedent: `view → select gate → estimate` |

**SA1's `TIMEBASE_REGULARITY_TOL = 2e-2` is explicitly *not* inherited as a spectral
threshold.** SA1 uses it to decide whether an ACF lag axis may be read in seconds; what
irregularity a *spectral* estimator tolerates is a different question. SA2's own tolerance is
chosen by the procedure in §J.

## A. `TimebaseCharacterization` — typed result for one `WindowView`

Computed from the view's own `time_s`, no interpolation. **Two intervals, never conflated:**

| field | meaning |
| --- | --- |
| `median_interval_s` | median adjacent interval — a **diagnostic** of the timestamp structure |
| `median_interval_rate_hz` | `1 / median_interval_s` — diagnostic only, **not** the sample rate |
| `full_span_interval_s` | `(t[-1] - t[0]) / (N - 1)` — the **adopted** effective interval |
| `effective_sample_rate_hz` | `1 / full_span_interval_s` |
| `nyquist_hz` | `effective_sample_rate_hz / 2` |

Plus: profile count; start / end / span; interval min / max / IQR; maximum relative deviation from
the median; duplicate count (exact ties); gap statistic (longest interval ÷ median); strictly
increasing yes/no; and `admitted_by` — which spectral methods this axis admits and which it
refuses, each by name and threshold.

**Why the median is not the rate.** SA1's own `LAG_GRID_RULE` already states this: the effective
lag step is `(t[-1] - t[0]) / (N - 1)`, the *full-span effective interval*, "as the echo-RPM step
documents (a quantized DOP timebase makes the median interval the dominant timestamp quantum
rather than the period)". SA2's spectral grid therefore derives its rate and Nyquist from the same
full-span effective interval. `median_interval_rate_hz` is reported because the difference between
the two is itself informative about quantization — but it is **never** called the sample rate, and
the two must not be used as though interchangeable without proving equivalence.

On the committed recordings the two agree to ~1 part in 10⁴ (11.469 vs 11.468 Hz at one end,
65.819 vs 65.789 Hz at the other), which is reassuring and **not** a licence to pick the cheaper
one: the adopted definition is the full-span one because it is the one with a stated justification.

## B. `SpectralAdmission` — may this view be analyzed by this estimator at all?

**Target-independent.** It may not consult whether 8.333 Hz was requested.

| condition | rule |
| --- | --- |
| sample count | `N >= MIN_SPECTRAL_SAMPLES` for the chosen transform |
| monotonicity | strictly increasing; a repeated stamp is not a sample |
| duplicates / gaps | counted and reported; duplicates refuse |
| uniformity | `max relative deviation <= SPECTRAL_UNIFORMITY_TOL` (chosen per §J) |
| estimator specifics | any further requirement the chosen estimator states |

Outcomes: `admitted`, or a **typed refusal naming the failed condition and its threshold**. The
only alternative to refusal is an *explicitly named* irregular-sampling estimator with its own
admission policy — and per §C that estimator is **not implemented in SA2 v1**.

**No admission verdict is published for any committed recording in this design.** The uniformity
rule's threshold is selected by §J's calibration, so until that exists the committed data's
spectral admission status is *pending calibration*. This document reports their SA1 regularity and
their measured irregularity, and nothing more.

## C. No resampling — strengthened for v1

The requirements a future resampler must meet stay on the record: a **named transform with
provenance** carrying input grid, output grid, interpolation method, gap policy, support policy,
whether anti-alias filtering occurred, how many samples were synthesized, and which frequencies
remain admissible after it.

**But SA2 v1 contains no resampling API at all** — not even a dormant general framework. A
resampler that exists to make an FFT convenient is a fabrication with provenance-shaped paperwork,
and one that exists merely because the architecture has a slot for it is the same mistake with
better manners. Uniform estimator when admitted; typed refusal otherwise.

## D. Spectral result contract

For a defined spectrum, at minimum: shared `ViewProvenance`; selected depth/gate; detrending and
window settings; estimator name; `full_span_interval_s` and `effective_sample_rate_hz`; span;
`nyquist_hz`; bin spacing / frequency resolution; the frequency axis; PSD values; units; the
normalization convention; and the one-sided/two-sided rule.

**A result may not be called a PSD unless its normalization and units really make it a spectral
density.** `PSD` is a claim about units (per Hz), not a synonym for "spectrum".

**Amplitude caveat, stated now rather than discovered later:** a PSD's peak height is taper- and
bin-dependent. If a physical sinusoid *amplitude* at a target frequency is ever needed, it must
come from a **separately named amplitude estimator or a band-integrated power**, never from
reading a raw PSD peak height as a sinusoid amplitude.

## E. `TargetFrequencySupport` — can this admitted spectrum answer at `f_target`?

Asked only of an already-admitted spectrum. Fields:

`target_hz` · `supported` · `reason` · `nyquist_hz` · `distance_to_nyquist_hz` · `nyquist_ratio`
· `frequency_resolution_hz` · `resolution_bins_to_target` · `cycles_in_view` · `nearest_bin_hz` ·
`bin_offset_hz` · `bin_offset_in_bins` · and descriptive local PSD/band power **only when
supported**.

Dependencies: target > 0; target inside the estimator's supported band (§F policy); the target's
evaluated cell — defined concretely in §F — remaining inside the band; observation duration /
resolution; enough cycles if the interpretation requires them; and any explicit target-margin rule
— of which there is currently none by design (§F).

**Resolution and cycles are separate checks and must not duplicate one another.** A 12 s window
gives ~0.0833 Hz nominal resolution, so both targets sit many resolution bins above DC — which
says nothing whatsoever about Nyquist support. The separate fields keep that visible.

**Wording is part of the contract.** `unsupported at 8.333 Hz` must never be readable as
`no 8.333-Hz component exists`. The first describes the instrument and the window; the second is a
measurement claim, and a refusal never makes one.

**Probe target vs search band.** `1.0 Hz` is a **probe target** for support diagnostics, not an
encoded hypothesis: SA1 established that the ~1 s recurrence is *sought, not assumed*, and SA2
preserves that posture. Later peak discovery runs over a **declared low-frequency band**, never by
selecting the bin nearest 1 Hz and calling it the vortex.

## F. Nyquist policy: one hard condition, and reported proximity

Two different things, kept apart:

**Hard frequency-band support** (a refusal condition, and the only one):

```
f_target < nyquist_hz
```

plus the **spectral-cell condition**, defined concretely so that "cell" is not left informal. For a
one-sided spectrum of `N` samples with bin spacing `Δf = fs_eff / N` (= 1 / span), bin `k` has
centre `f_k = k · Δf`; its cell is the interval between the midpoints to its neighbours, clipped to
the physical support `[0, f_N]`:

```
cell(k) = [ max(0, (f_{k-1} + f_k) / 2) ,  min(f_N, (f_k + f_{k+1}) / 2) ]
```

The **evaluated cell** is the cell of the nearest bin centre to the target. The condition is: the
target lies inside that cell (`|bin_offset_hz| <= Δf / 2`) **and** that cell lies inside
`[0, f_N]`. A target is therefore reported with its nearest bin centre, its cell edges, its offset
in Hz and in bins, and whether the evaluated cell lies inside the physical spectral support.

This matters precisely at `emissions-64`, where the target sits closest to the upper edge.

**Reported proximity** (never an admission criterion):

`nyquist_hz` · `target_hz` · `nyquist_ratio = nyquist_hz / target_hz` ·
`distance_to_nyquist_hz` · distance in spectral-resolution units.

**No arbitrary margin ratio becomes a scientific threshold.** An earlier draft treated "~1.23×
spacing" as caution and a `0.9 × nyquist` guard as policy. That was inventing a cutoff because it
sounded careful. Proximity is now *reported* — so a reader sees that `emissions-64` sits close to
its band edge — while the only refusal is the Nyquist impossibility itself. If a stricter
admissibility criterion is ever needed it must be derived from an actual estimator/measurement
question, not from synthetic FFT recovery looking acceptable.

## G. Measured capability (all 52 committed live recordings)

Measured through the public `.BDD` reader — intervals and spans only, no spectral code. Effective
rate and Nyquist use the **adopted** definition `(t[-1] - t[0]) / (N - 1)`.

| configuration | N | span s | median int s | effective int s | `fs_eff` Hz | `f_N` Hz | regularity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `emissions-8` (burst 10) | 826–829 | ~12.54–12.58 | 0.01520 | 0.01519 | **65.819** | **32.909** | 6.58e-03 |
| `emissions-20` (burst 4/18, common-ref) | 558–563 | ~12.52–12.59 | 0.02240 | 0.02239 | **44.66** | **22.33** | 4.44–4.46e-03 |
| `emissions-64` (burst 10) | 257–259 | ~12.49–12.59 | 0.04880 | 0.04879 | **20.495** | **10.247** | 2.05e-03 |
| `emissions-128` (burst 10) | 144–145 | ~12.47–12.56 | 0.08720 | 0.08719 | **11.469** | **5.734** | 1.15e-03 |

Effective rate spans **11.469–65.819 Hz**, Nyquist **5.734–32.909 Hz**. The spread is a property
of the acquisition, not the analysis: the profile period follows `emissions × PRF + 10.369 ms`, so
raising `emissions_per_profile` lowers the sample rate.

**All 52 recordings are `SA1-regular`** — worst measured relative interval deviation 6.58e-03
against SA1's `TIMEBASE_REGULARITY_TOL = 2e-2`, with no duplicate or decreasing timestamps. That is
a statement about **SA1's ACF-lag criterion** and it is *not* a spectral admission verdict:
**spectral admission is pending `SPECTRAL_UNIFORMITY_TOL` calibration** (§J), which this design
cannot supply. The table above therefore reports measured irregularity, and no row in this document
asserts an admission verdict for a committed recording.

### Target support is a property of `target × WindowView`

Not of `target × recording`. Cycle counts differ between the views, so both are stated:

| configuration | view | resolution Hz | cycles @1 Hz | cycles @8.333 Hz | band @1 Hz | band @8.333 Hz | `nyquist_ratio` @8.333 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `emissions-8` | `primary-comparison` (12 s) | 0.0833 | 12.0 | 100.0 | yes | **yes** | **3.95** |
| `emissions-8` | `full-record` (~12.5 s) | ~0.0798 | ~12.5 | ~104.5 | yes | **yes** | **3.95** |
| `emissions-20` | `primary-comparison` (12 s) | 0.0833 | 12.0 | 100.0 | yes | **yes** | **2.68** |
| `emissions-20` | `full-record` | ~0.0797 | ~12.5 | ~104.4 | yes | **yes** | **2.68** |
| `emissions-64` | `primary-comparison` (12 s) | 0.0833 | 12.0 | 100.0 | yes | **yes** (close) | **1.23** |
| `emissions-64` | `full-record` | ~0.0797 | ~12.5 | ~104.5 | yes | **yes** (close) | **1.23** |
| `emissions-128` | `primary-comparison` (12 s) | 0.0833 | 12.0 | 100.0 | yes | **NO** | **0.69** |
| `emissions-128` | `full-record` | ~0.0799 | ~12.5 | ~104.5 | yes | **NO** | **0.69** |

Refusal counts under the hard band condition: **1 Hz — zero band refusals** across all 52
recordings in either view. **8.333 Hz — 8 recordings refused** (every `emissions-128` recording,
four per sitting), `nyquist_hz = 5.734`. These band verdicts are independent of the pending
uniformity tolerance: they follow from `f_target < f_N` on the measured stamps.

**The trap this table exists to catch**, and the reason the two checks are separate: every
`emissions-128` recording holds ~104 cycles of the 8.333-Hz target in its full-record window and
exactly 100 in its primary window — so a policy screening only *"are there enough cycles?"* would
report the target as well supported. Support requires **band and cycles together**, and the band
test is the one that refuses here.

### What each configuration can answer

- **8.333-Hz rotor reference:** band-supported in `emissions-8` (ratio 3.95) and `emissions-20`
  (2.68); band-supported in `emissions-64` (1.23) **on its own stated proximity**, reported rather
  than smoothed over. `emissions-128` is **refused by the band condition** — and that refusal is a
  hard Nyquist fact which does **not** depend on the pending uniformity tolerance.
- **~1 Hz recurrence scale:** inside the measurable band of **every** configuration and **both**
  views, with 12.0 cycles in the primary view. Like every target verdict here it is conditional on
  the view passing the eventual spectral admission. `emissions-128`'s band still clears 1 Hz
  (ratio 5.73) even though it cannot support 8.333 Hz. It is **not** the *best* configuration for
  1 Hz: by Nyquist margin it has the **smallest** ratio of the four (5.73 against `emissions-8`'s
  32.9), and the fewest samples per cycle. Its fundamental frequency resolution is not better
  either — the span is the same, so 1/T is the same. **`emissions-128` is the slowest sampler that
  still clears 1 Hz, not the one that resolves it best.**

## H. Primary vs full-record spectra

Both views, kept distinct and labelled from SA1's vocabulary:

- **`primary-comparison`** — the same designed ≈12 s exposure for every recording, comparable
  across the sweep, resolution 0.0833 Hz.
- **`full-record`** — recording-dependent span (~12.5 s here), marginally finer resolution
  (~0.0797 Hz).

They are **not interchangeable**, and the difference is exactly why §G's cycle counts are stated
per view. Every spectral result carries the view label *and* rule inherited from SA1, so a
`primary-comparison` spectrum cannot be presented as a full-record one.

## I. Detrending, taper and normalization — pinned, not left open

| choice | default |
| --- | --- |
| mean removal | **on**, matching SA1's ACF default |
| linear detrending | optional, named, SA1's `Detrending` vocabulary |
| taper | **Hann**, `w[n]` |
| spectrum | **one-sided** (real-valued traces) |
| DC | retained and reported explicitly, with its own DC bin identified |

### The exact normalization

```
Pxx(f_k) = |FFT(w * x)[k]|^2 / ( fs_eff * sum_n w[n]^2 )
```

with the conventional **one-sided doubling of every bin except DC and Nyquist** (only where those
bins exist for the given `N`). Bin spacing `Δf = fs_eff / N`. The units are **(mm/s)²/Hz**, which is
what makes the result a density rather than a "spectrum" (§D).

### What the PSD integral actually reproduces

The one-sided integral reproduces one specific time-domain quantity **exactly**, for any trace:

```
sum_k Pxx(f_k) * Δf  =  sum_n (w[n] * x[n])^2 / sum_n w[n]^2
```

That quantity is the **window-normalized mean-square power**. It is named here, with its formula,
precisely so that no claim is made about the raw variance of the detrended trace: Parseval is an
identity between the PSD and *that* definition, and it holds whether or not the signal is
bin-centred.

**The integral does *not*, in general, equal `var(detrended_trace)`** on a tapered finite record.
An off-bin sinusoid is the standard counter-example — windowing spreads its energy across
neighbouring bins, so the tapered mean-square power differs from the untapered variance even though
the PSD carries correct density units. **No compensating scalar will be introduced to force those
two numbers to agree**: such a scalar would distort the estimator's actual statistical meaning in
exchange for a cosmetic identity.

They do agree where the statistics say they should. For a white-noise input of variance `σ²`,
`E[sum_n (w[n]x[n])^2 / sum_n w[n]^2] = σ²`, so a white-noise test recovers `σ²` **statistically and
tolerantly** under this normalization (§J level 1) — without any identity being asserted for an
arbitrary deterministic trace.

### Where Hann's ENBW enters — and where it does not

Hann's equivalent noise bandwidth is `ENBW = 1.5` bins. It belongs to **interpretation and
conversion**: reading a noise floor, or converting between a bin power and a spectral density.

It is **not** an extra factor to multiply into the normalization above. That expression is already
energy-normalized by `sum_n w[n]^2`, so applying an ENBW correction on top of it would double-count
the window. The formula is pinned first; ENBW appears only where a conversion genuinely needs it,
and its role is stated at each such use.

### Required tests (§J level 1)

Parseval consistency **against the same tapered and normalized signal definition the estimator
uses** — the window-normalized mean-square power above, never the raw trace variance; correct
`(mm/s)²/Hz` units; correct one-sided folding; correct frequency grid; white-noise power recovering
`σ²` statistically; bin-centred and off-bin sinusoid behaviour under Hann including leakage; and no
claim anywhere that a raw PSD peak height is a sinusoid amplitude (§D).

## J. Synthetic validation — two levels, and where the tolerance comes from

### Level 1 — mathematical estimator tests (exact uniform grids)

Bin-centered sinusoid; off-bin sinusoid; two sinusoids; DC; linear trend; constant; white noise.
Validate: the frequency grid; one-sided scaling; PSD units; **Parseval consistency against the
window-normalized mean-square power (§I)**, never the raw trace variance; taper correction; peak
location; leakage behaviour.

### Level 2 — admission/refusal tests (timestamp pathology)

Duplicate timestamps; decreasing timestamps; controlled jitter sweep; one large gap; too few
samples; target above Nyquist; target immediately below Nyquist; target with too few cycles;
target between bins.

### How `SPECTRAL_UNIFORMITY_TOL` is determined

**Not chosen first and then illustrated by tests.** The jitter sweep measures, against the same
signal on an exact uniform grid, **quantified distortion**:

- peak-frequency error, in bins;
- integrated band-power error;
- total power / variance error;
- target-bin / target-band response error.

The tolerance is then **selected at a declared maximum distortion** — the largest jitter whose
distortion stays inside a stated bound — so the number carries a scientific meaning ("irregularity
beyond which a peak moves more than X bins, or a band's power changes more than Y%") rather than a
cautious-looking decimal.

## K. Committed-data characterization — the first result

§G **is** the first instalment: per configuration, `N`, span, both intervals, `fs_eff`, `f_N`,
regularity, and per-view resolution, cycles and band support for both targets, with exact refusal
counts and reasons.

It answers *"what can this acquisition configuration resolve?"* before anyone inspects a peak
amplitude, so a later plot cannot flatter a configuration that was never able to answer the
question.

## Anti-alias / transfer-function limitation (binding)

**SA2's Nyquist support is a sampling-support statement for the stored profile sequence.** It is
not a calibrated temporal transfer-function correction and does not establish the instrument's
anti-alias response.

These UDV profiles are not instantaneous abstract samples: their construction depends on
emissions/profile and the instrument's own processing, and the repository does not currently
establish a complete temporal transfer function or anti-alias filter for the profile output.
Therefore, for `emissions-8/20/64`:

`8.333 Hz < Nyquist` means **the sampled profile sequence can represent that frequency without the
basic Nyquist impossibility.** It does **not** mean the amplitude is unbiased, that higher-frequency
content cannot alias into it, or that emissions/profile carries no temporal averaging at that
frequency.

This matters most for `emissions-64`, whose target sits closest to its band edge. Resolving a
transfer function is **out of scope for SA2** unless independent instrument evidence exists.

## First estimator: single-view periodogram

**Chosen: the single-view periodogram.** Welch is deferred.

Reasons: the primary view is only ~12 s, so frequency resolution is already limited by observation
length; Welch segmentation would reduce per-segment resolution further, working against exactly the
low-frequency questions this stage asks; the goal here is **descriptive spectral structure and
target support**, not low-variance population PSD estimation; and a single-view periodogram is
exactly validatable on synthetic sinusoids (§J level 1). Welch may be added later as an *optional*
exploratory estimator if variance reduction proves demonstrably useful — and if it is, that PR must
state segment length, overlap, taper, effective segment duration, resulting resolution, segment
count, and why that resolution is acceptable for the ~1 Hz and 8.333-Hz questions.

## Irregular-sampling estimator: deferred

Lomb–Scargle and friends are **not** committed to SA2 v1. All 52 committed recordings are regular
by the SA1 ACF-lag diagnostic — and whether they satisfy the *spectral* admission rule is exactly
what the SA2.1 calibration determines. The v1 shape is therefore: uniform estimator when admitted
under the calibrated tolerance, typed refusal otherwise. An irregular estimator
becomes justified when committed data actually fails the admission policy — not because the
architecture has a slot for one.

## Implementation sequence after this design

- **SA2.0 — design finalization.** This PR only. No code before it passes.
- **SA2.1 — admission calibration + capability backend.** In this order, inside one PR:
  (1) implement `TimebaseCharacterization`; (2) implement the synthetic jitter/pathology harness;
  (3) **determine and record `SPECTRAL_UNIFORMITY_TOL`** from the declared distortion limits;
  (4) implement `SpectralAdmission`; (5) run admission across all 52 committed recordings; (6) only
  then implement and run `TargetFrequencySupport`; (7) publish the exact committed-data
  support/refusal counts and reasons. **No PSD in SA2.1.**

  The tolerance is calibrated **before** any committed-data admission verdict is published; SA1's
  `2e-2` band is never substituted as a temporary stand-in. (Chosen over the `SA2.1a`/`SA2.1b`
  split: the calibration is small enough to live at the head of the same PR.)

  Expected table, per `recording × view`: `N`; span; `dt_eff`; `fs_eff`; Nyquist; timestamp
  irregularity metrics; **spectral admission + reason**; **1-Hz support + reason**; **8.333-Hz
  support + reason**.
- **SA2.2 — validated periodogram/PSD backend.** `WindowView → selected gate → spectral estimate`
  with §I's choices. Synthetic tests first, then committed-data smoke tests.
- **SA2.3 — notebook spectral preview.** Extend `signal_explorer.py` with the timebase/admission
  summary, a PSD plot, target-support rows and refusal wording. No calculations in cells.
- **SA2.4 — committed-data spectral characterization.** Low-frequency structure, support near
  ~1 Hz, the supported 8.333-Hz configurations, depth dependence. Descriptive and per sitting — no
  cross-sitting statistical inference.

## Out of scope

SA2 answers *"what frequencies can this recording resolve, and what descriptive spectral structure
is present?"* It does **not** answer whether the ~1 Hz feature is a vortex, whether rotor speed was
measured, whether the CFD discrepancy is explained, whether one UDV setting is scientifically
superior, or whether two sittings constitute statistical replication. Those belong to SA3/SA4 and
to cross-sitting synthesis.

## Known limitation carried in

Issue **#49** (`ArrayModel.model_dump(mode="json")` raises for every ndarray-bearing model) stays
outside SA2 implementation. **SA2 v1 does not solve general ndarray JSON serialization:** typed
in-memory result, notebook display, tests. If SA2 ever needs committed machine-readable spectral
artifacts, #49 is resolved deliberately first — not by assuming `model_dump(mode="json")` is safe
because spectra happen to contain arrays.
