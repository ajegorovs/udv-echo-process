# SA2 — spectral and sampling support: design and backend contract

> **Status:** the contract is settled and its first two stages have **landed**.
>
> | stage | what it delivered | where |
> | --- | --- | --- |
> | SA2.0 | the contract below | this document |
> | SA2.1 | timebase characterization, the calibrated spectral-uniformity admission (`max_relative_timing_error`, operational tolerance `0.09`), target-frequency support, the committed capability matrix | merged `0f4eb46` |
> | SA2.2 | the admitted uniform-grid periodogram/PSD backend and the stored-timestamp oracle | merged `9ba46c4` |
> | SA2.3 | the notebook spectral preview — **planned, not started** | [`sa2-3-notebook-preview-plan.md`](sa2-3-notebook-preview-plan.md) |
> | SA2.4 | committed-data spectral characterization | see §Sequence below |
>
> What remains here is the *contract*: this document still contains no FFT, periodogram, Welch, PSD
> or resampling code — the estimators live in `analysis.sparse_spectral_*`,
> `analysis.sparse_periodogram` and `analysis.sparse_target_support`, and they are authoritative
> where they and this document ever disagree. It fixes what SA2 must satisfy, so the estimator is
> chosen to fit the axis rather than the axis bent to fit the estimator.

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
recording. SA2.1 supplies it and publishes the verdicts — see §J *SA2.1 outcome* at the end.

### Corrections carried by SA2.1 (three, none of them cosmetic)

1. **`Δf ≠ 1 / span`.** Under the adopted `fs_eff = (N - 1) / span` the bin spacing is
   `Δf = fs_eff / N = (N - 1) / (N · span)`, smaller than `1 / span` by exactly `(N - 1) / N`. The
   duration scale is reported separately as `duration_resolution_scale_hz = 1 / span`. §F, §G, §I.
2. **Hann's ENBW is derived from the taper's coefficients, not hard-coded as 1.5 bins**, and the
   periodic/symmetric conventions differ by `N / (N - 1)`. §I.
3. **The uniformity rule's operand is the timing error, not the interval deviation.** `§A`'s
   `max_relative_interval_deviation` does not order the distortion — measured, in the same regime
   at the same target, an axis with interval deviation 0.182 breaks the declared bound while an
   axis with 0.222 stays inside it — so the calibrated threshold is on
   `max_relative_timing_error`, the quantity that bounds a uniform DFT's phase error. The interval
   deviation is still reported, with its non-operand role stated. §B, §J.

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
| uniformity | `max_relative_timing_error <= SPECTRAL_UNIFORMITY_TOL` (calibrated per §J) |
| estimator specifics | any further requirement the chosen estimator states |

Outcomes: `admitted`, or a **typed refusal naming the failed condition and its threshold**. The
only alternative to refusal is an *explicitly named* irregular-sampling estimator with its own
admission policy — and per §C that estimator is **not implemented in SA2 v1**.

**No admission verdict was published for any committed recording in this design.** The uniformity
rule's threshold is selected by §J's calibration, and in SA2.0 that did not exist. SA2.1 has since
carried it out; the outcome — the calibrated tolerance, the committed verdicts and the operand
correction it forced — is recorded in §J *SA2.1 outcome*. The fragments below that said
"pending calibration" are kept as the record of what SA2.0 could and could not assert.

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
gives ~0.0833 Hz of resolution in the sense of `1 / span`, and ~0.0833 Hz again as an actual
bin spacing `Δf = fs_eff / N` — which are *not the same number* under the adopted rate (they
differ by the factor `(N - 1) / N`; see §F), so both targets sit many resolution bins above DC.
That says nothing whatsoever about Nyquist support. The separate fields keep that visible.

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
one-sided spectrum of `N` samples with bin spacing

```
Δf = fs_eff / N = (N - 1) / (N · span)
```

bin `k` has centre `f_k = k · Δf`; its cell is the interval between the midpoints to its
neighbours, clipped to the physical support `[0, f_N]`:

```
cell(k) = [ max(0, (f_{k-1} + f_k) / 2) ,  min(f_N, (f_k + f_{k+1}) / 2) ]
```

**`Δf` is not `1 / span`, and the two must not be equated** (corrected in SA2.1). They differ by
exactly `(N - 1) / N`, which is 0.999 for `emissions-8` and 0.993 for `emissions-128` — small, but
this stage is definition-sensitive and the two answer different questions. `Δf` is the spacing of
the grid a DFT of this axis actually produces; `1 / span` is the usual observation-duration
resolution *scale*. Where the duration matters it is reported under its own name,
`duration_resolution_scale_hz = 1 / span`, and stated to be an approximate scale rather than the
bin spacing. On the committed data the two are e.g. 0.083314 vs 0.083470 Hz on an
`emissions-8` primary view.

**The endpoint bins have explicit rules, because `f_{k+1}` does not exist at the top of the
grid.** The DC cell's lower edge is exactly `0`; the highest represented bin's upper edge is
exactly `f_N` (`min` clips `(f_k + f_{k+1}) / 2` there for either parity). The two parities are
not the same shape: for even `N` the last bin *is* `f_N` (bin `k = N/2`), while for odd `N` the
last represented bin is `floor(N/2) · Δf`, which lies `Δf/2` **below** mathematical Nyquist — its
cell reaches `f_N` while no bin sits there. No cell edge is therefore ever read from a bin that
does not exist, and `N = 138` and `N = 145` are both pinned by tests.

The **evaluated cell** is the cell of the nearest bin centre to the target, with a stated
half-up tie rule (a target exactly halfway between two bins goes to the upper one). The condition
is: the target lies inside that cell (`|bin_offset_hz| <= Δf / 2`) **and** that cell lies inside
`[0, f_N]`. A target is therefore reported with its nearest bin centre, its cell edges, its offset
in Hz and in bins, and whether the evaluated cell lies inside the physical spectral support. For a
target at or above Nyquist the nearest *existing* bin is the top one and the reported offset is its
distance above it — greater than half a bin, which is the arithmetic statement that the grid has
no cell for that target; the cell test is not consulted for such a target at all.

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
a statement about **SA1's ACF-lag criterion**, and SA1's tolerance is *not* the spectral one. SA2.1
has since calibrated the spectral rule and published the verdicts: the table above reports measured
irregularity and band support, and §J *SA2.1 outcome* reports the spectral admission counts.

### Target support is a property of `target × WindowView`

Not of `target × recording`. Cycle counts differ between the views, so both are stated:

| configuration | view | `Δf` Hz (measured) | `1/span` Hz | cycles @1 Hz | cycles @8.333 Hz | band @1 Hz | band @8.333 Hz | `nyquist_ratio` @8.333 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `emissions-8` | `primary-comparison` | 0.083315 | 0.083420 | 11.99 | 99.90 | yes | **yes** | **3.95** |
| `emissions-8` | `full-record` | 0.079683 | 0.079780 | 12.53 | 104.45 | yes | **yes** | **3.95** |
| `emissions-20` | `primary-comparison` | 0.083314 | 0.083470 | 11.98 | 99.84 | yes | **yes** | **2.68** |
| `emissions-20` | `full-record` | 0.079459–0.079601 | 0.079601–0.079744 | 12.54–12.56 | 104.50–104.69 | yes | **yes** | **2.68** |
| `emissions-64` | `primary-comparison` | 0.083311 | 0.083651 | 11.95 | 99.62 | yes | **yes** (close) | **1.23** |
| `emissions-64` | `full-record` | 0.079129 | 0.079436 | 12.59 | 104.91 | yes | **yes** (close) | **1.23** |
| `emissions-128` | `primary-comparison` | 0.083107 | 0.083714 | 11.95 | 99.55 | yes | **NO** | **0.69** |
| `emissions-128` | `full-record` | 0.079645 | 0.080201 | 12.47 | 103.91 | yes | **NO** | **0.69** |

The `Δf` and `1/span` columns are here side by side on purpose: they are *different numbers* and
differ by the `(N - 1) / N` factor (0.999 for `emissions-8`, 0.993 for `emissions-128`). `Δf` is
what the grid does; `1/span` is the duration scale. Values measured in SA2.1 from the committed
stamps; the `emissions-20` full-record rows vary slightly because their spans do.

Refusal counts under the hard band condition: **1 Hz — zero band refusals** across all 52
recordings in either view. **8.333 Hz — 16 of the 104 recording × view cases refused**, being the
eight `emissions-128` recordings (four per sitting, each in both views), `nyquist_hz = 5.734`.
These band verdicts are independent of the uniformity tolerance: they follow from
`f_target < f_N` on the measured stamps.

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

Hann's equivalent noise bandwidth belongs to **interpretation and conversion**: reading a noise
floor, or converting between a bin power and a spectral density.

**It is derived from the taper actually used, never hard-coded as `1.5` bins** (corrected in
SA2.1). For the exact coefficients `w[n]` of the chosen window,

```
ENBW_bins = N · sum_n w[n]**2 / (sum_n w[n])**2
ENBW_hz   = ENBW_bins · Δf
```

and `1.5` is a *result* of one convention, not a constant of the method. The two conventions
differ by more than a rounding: measured on the committed grid sizes, the **periodic** Hann
`w[n] = 0.5 - 0.5·cos(2πn/N)` gives exactly `1.5` bins at every `N`, while the **symmetric** Hann
`w[n] = 0.5 - 0.5·cos(2πn/(N-1))`, which has a different `Σw` and `Σw²`, gives
`1.5 · N / (N - 1)` exactly — `1.5109` at `N = 138` (the `emissions-128` primary view) and
`1.5018` at `N = 826`. That is a 0.73 % difference in a *conversion factor* at the smallest
committed `N`, which is why the convention must be pinned rather than assumed.

**SA2.2 states which convention it uses, and its ENBW test recomputes the value from the
coefficients it actually applies rather than asserting `1.5`.** SA2.2 pins the **periodic Hann**
(`w[n] = 0.5 - 0.5 cos(2 pi n / N)`, the endpoint not repeated), which is the spectral-estimation
convention and the one the SA2.1 calibration harness already assumed, so the calibration oracle and
the estimator are tapers of the same shape. It is stated in the result itself
(`taper_name` / `taper_convention`) and measured there from its own coefficients: `1.5` exactly at
every committed `N` (138, 144, 246, 259, 536, 561, 790, 826), against `1.5 · N / (N - 1)` for the
symmetric convention. Both halves are asserted in `tests/test_sparse_periodogram.py`, so the choice
cannot be inferred later from this document alone.

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

### SA2.1 outcome — the calibration, carried out

**The tolerance, and what it rests on.** The four distortion bounds were declared *before* any
measurement was read off: peak-frequency error `<= 0.05` bins; integrated band-power error
`<= 1 %`; total (windowed) power error `<= 1 %`; target-cell response error `<= 5 %`. The
calibration then sweeps five perturbation constructions — a quantized clock, independent jitter, a
reversing per-interval error, one interval error early and the opposite late, and a single
isolated gap — over the four committed rate regimes, two probe regions (~1 Hz, ~8.333 Hz), bin-
centred and off-bin tones, and 12 deviation levels: **770 cases**, of which 742 are axes the other
admission conditions do not already refuse.

```
measured clean boundary                  0.09918      <- largest clean measurement
first measured violation                 0.09923      <- 1 % bound first broken
operational admission tolerance          0.09         <- the measured clean boundary quantized
                                                        downward by UNIFORMITY_TOL_QUANTUM = 0.01,
                                                        i.e. the largest value that is both a
                                                        whole hundredth and strictly inside the
                                                        clean region. Never rounded up.
violations at or below the tolerance     0
```

The three numbers are distinct and none stands for another: the shipped constant is deliberately
*inside* the measured clean region, not equal to its edge. A test reproduces the quantization from
the matrix (`floor(boundary / 0.01) * 0.01`), pins the two measured values, and refuses a shipped
tolerance that is the boundary itself.

**Three results of the calibration are worth more than the number.**

*The operand had to change* (correction 3 above). Mapping distortion against the design's
`max_relative_interval_deviation` **does not order it**: on `emissions-8` at the 8.333-Hz target,
an alternating axis with interval deviation 0.1818 breaks the 1 % windowed-power bound at 2.46 %,
while a ramp axis with a *larger* interval deviation of 0.2222 — and a timing error of 41
intervals — stays at 0.964 %. Worse, on a two-level axis the *median* reference makes the same
statistic swing 22 % (0.1818 vs 0.2222) on nothing but the parity of the sample count. The
operand is therefore `max_relative_timing_error`, which does bound the distortion the estimator
actually suffers: a timing error `T` places every sample within `T · dt_eff` of the assumed grid,
so the phase error at any frequency up to Nyquist is at most `π · T`. The interval deviation stays
on the record, and its non-operand role is a named string on every verdict.

*The gap needs no separate guard, and that is now proved rather than asserted.* For an isolated
gap of ratio `g` the interval errors sum to a step, so
`max_relative_timing_error >= (g - 1) · (N - 1) / (N - 2 + g)`: a gap cannot slip under a
timing-error threshold unnoticed. A test checks that inequality across gap ratios and positions,
and the calibration's matrix contains no gap case that breaks a bound while its timing error is
inside the tolerance. The gap ratio is therefore diagnostic — reported, and named in the refusal
when it is the pathology — not a second threshold on the same axis.

*The committed data's irregularity is a bounded clock quantum, not an accumulating warp.* Every
committed stamp is an exact multiple of `1e-4 s`, and the largest deviation of any stamp from its
own view's adopted uniform grid is `1.8e-4 s` (worst relative value `8.3e-3`). The interval
deviation of `6.58e-3` is that same quantum expressed per interval; on a *shorter* interval it
grows without the axis being any worse, which is a third reason it is not the operand.

**Committed verdicts (104 `recording × view` records, both sittings, both views).**

| quantity | value |
| --- | --- |
| records | 104 (52 recordings × `primary-comparison` + `full-record`) |
| **spectrally admitted** | **104 / 104** (worst timing error `8.3e-3`, 10.8× inside the tolerance) |
| 1-Hz band-supported | 104 / 104 |
| 1-Hz overall supported | 104 / 104 |
| 8.333-Hz band-supported | 88 / 104 |
| 8.333-Hz overall supported | 88 / 104 |
| 8.333-Hz refusals | 16 — every `emissions-128` view, reason *above Nyquist* |
| primary vs full-record | no view changes any admission verdict; refusal counts are view-independent |

The estimator is admitted for `emissions-128` while the 8.333-Hz target is refused on the same
axis: the two verdicts are independent by construction, which is what §B's headline example asks
for. No PSD or periodogram is computed by any of this — the calibrated number comes from a
test-only reference calculation, and the production surface stops at characterization, admission
and target support.

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
- **SA2.1 — admission calibration + capability backend. LANDED.** Delivered as, in this order:
  `analysis.sparse_spectral_support` (`TimebaseCharacterization`, `characterize_timebase`, the
  frequency grid and the cell rules); the synthetic calibration harness
  (`tests/_spectral_calibration.py`, test-only); the recorded `SPECTRAL_UNIFORMITY_TOL`;
  `analysis.sparse_spectral_admission` (`SpectralAdmission`, per-condition verdicts);
  `analysis.sparse_target_support` (`TargetFrequencySupport`, `band_supported` /
  `analysis_supported`); and `analysis.sparse_spectral_capability`
  (`committed_spectral_capability`, one record per `recording × view`). **No PSD, no periodogram,
  no Welch, no resampling, no Lomb–Scargle, and no notebook change.** The §J *SA2.1 outcome*
  subsection above carries the calibrated tolerance, the declared bounds it came from, the worst
  measurements either side of it, and the committed support/refusal counts.

  The tolerance was calibrated **before** any committed-data admission verdict was published;
  SA1's `2e-2` band was never substituted as a temporary stand-in. (Chosen over the
  `SA2.1a`/`SA2.1b` split: the calibration is small enough to live at the head of the same PR.)

  Delivered table, per `recording × view`: `N`; span; `dt_eff`; `fs_eff`; Nyquist; `Δf`;
  timestamp irregularity (timing error and interval deviation) and the gap ratio;
  **spectral admission + reason**; **1-Hz band/overall support + reason**; **8.333-Hz band/overall
  support + reason**. One correction to the original plan for this bullet: the calibration had to
  measure a reference spectral calculation to quantify distortion at all. It lives in the test-only
  harness, is never imported by `src/`, and SA2.2 remains the PR that implements the reviewed public
  estimator contract.
- **SA2.2 — validated periodogram/PSD backend. LANDED.** `WindowView → selected gate →
  characterize → admit → spectral estimate`, delivered as `analysis.sparse_periodogram`
  (`SpectralEstimate`, `periodogram_of_view`, `SpectralVerdict`, `periodic_hann`,
  `taper_enbw_bins`). **The estimator makes the approximation the admission granted:** the
  transform is the ordinary one-sided `rfft` of the tapered, detrended trace, over the adopted
  uniform grid (`dt_eff = span/(N-1)`), as `|rfft(w * x)[k]|^2 / (fs_eff * sum w^2)` at SA2.1's own
  `one_sided_frequency_grid` - the stored stamps supply `dt_eff`/`fs_eff`/`delta_f`, are what the
  admission tested, and are what the optional linear detrending is fitted against, but they are not
  the Fourier sampling coordinates. DC is never doubled, the interior bins are doubled, the top bin
  is halved for even `N` only. The nonuniform evaluation at the stored times is kept **as the
  test-only oracle** (`tests._spectral_calibration.reference_spectrum`), and one committed-data
  diagnostic records what taking the approximation costs against it: over 18 committed views
  (9 jobs × 2 views, one sitting) the integrated difference is 1.8e-5 … 2.9e-4 and the normalized
  L2 difference 1.8e-4 … 6.7e-4, ordered by the axis's own timing error (9.1e-4 … 5.8e-3, all far
  inside the 0.09 tolerance). Those are recorded diagnostics, **not** new admission thresholds. A
  refused axis returns a refusal carrying its admission rather than a density; the fold's
  `sum_k Pxx[k] * delta_f == sum_n (w x)^2 / sum_n w^2` is now a pure implementation invariant and
  holds to floating-point accuracy for every defined spectrum (worst 8.6e-16 over the committed
  views), which is why `parseval_relative_error` is not a measure of timestamp irregularity -
  `admission.characterization.max_relative_timing_error` is that. The estimator stays an `src/`
  module: no notebook, no peak interpretation, no Welch, no resampling.
- **SA2.3 — notebook spectral preview. PLANNED.** Extend `signal_explorer.py` with the
  timebase/admission summary, a PSD plot, target-support rows and refusal wording. No calculations
  in cells, no new estimator, no scientific interpretation: the notebook is
  `selection → backend call → display`, reusing SA1's one `WindowView` and its gate/detrending
  selection. The contract is [`sa2-3-notebook-preview-plan.md`](sa2-3-notebook-preview-plan.md).
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
