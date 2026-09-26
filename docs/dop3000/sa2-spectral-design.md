# SA2 — spectral and sampling support: design and backend contract

> **Status:** design for review. No spectral estimator is implemented in this slice, and this
> document deliberately contains no FFT, periodogram, Welch or PSD code. It fixes the contract
> SA2 must satisfy before any of that exists, so the estimator is chosen to fit the axis rather
> than the axis being bent to fit the estimator.

## The governing rule

**Characterize the timestamps first; choose or refuse the estimator second. Never interpolate.**

Every other decision below follows from that one. SA1 established the pattern — a
`WindowView` carries its own provenance and its own timebase verdict, and a quantity the window
does not define is refused by name rather than substituted. SA2 inherits it unchanged.

## What this slice inherits from SA1 (do not re-cut)

| SA1 artefact | SA2's use |
| --- | --- |
| `analysis._sparse_view.SparseView` | the view label and rule on every spectral result |
| `WindowView` | the **only** cut. SA2 must not slice time or depth independently |
| `ViewProvenance` | the shared source identity, window, extents and view rule |
| `native_depth_extent_mm` / `pass_support_mm` / `participating_depth_extent_mm` | inherited as the three differently-meant extents |
| `classify_timebase` + `TimebaseVerdict` | the axis verdict SA2's admission policy consumes |
| `recurrence_of_view` | the precedent: `view → select gate → estimate` |

**SA1's `TIMEBASE_REGULARITY_TOL = 2e-2` is explicitly *not* inherited as a spectral
threshold.** SA1 uses it to decide whether the ACF's lag axis may be read in seconds. What
sampling irregularity a *spectral* estimator tolerates is a different question with a different
answer, and SA2 must decide it on its own evidence (see §B).

## A. Timebase characterization — typed result for one `WindowView`

`TimebaseCharacterization`, computed from the view's own `time_s` with no interpolation:

- profile count; start / end / span;
- full-span effective interval (`span / (n - 1)`) and median adjacent interval;
- interval min / max / IQR;
- maximum relative deviation from the median;
- duplicate count (exact ties);
- gap statistic (longest interval ÷ median);
- effective sample frequency `1 / median interval`;
- strictly increasing: yes / no;
- **`accepted_by`** — which spectral methods this axis admits, and which it refuses, each by name.

The last field is the point of the type: an axis is not "good" or "bad" in the abstract, it is
accepted or refused *by a named estimator with a stated tolerance*.

## B. Spectral method admission policy

A conventional uniformly-sampled FFT/periodogram/Welch is admitted only when **all** hold:

1. `n >= MIN_SPECTRAL_SAMPLES` — enough profiles for the chosen transform;
2. strictly increasing, no duplicates (a repeated stamp is not a sample);
3. `max relative deviation <= SPECTRAL_UNIFORMITY_TOL` — **a policy SA2 sets from its own
   synthetic validation (§I), not by importing SA1's `2e-2`**;
4. the requested band lies below Nyquist with margin (§E).

If any fails:

- either use an **explicitly named irregular-sampling estimator** (Lomb–Scargle and friends),
  declared as such on the result, with its own admission policy; or
- **return a typed refusal naming the failed condition and its threshold.**

Never silently interpolate, never pad, never resample to make a transform convenient.

## C. No default resampling

Resampling may exist only as a **named transform with provenance**, carrying: input grid,
output grid, interpolation method, gap policy, support policy, whether anti-alias filtering
occurred, how many samples were synthesized, and which frequencies remain admissible after it.
A resample that exists to make an FFT convenient is not a transform, it is a fabrication with
provenance-shaped paperwork. Default answer for SA2: **no resampling**.

## D. Spectral result contract

For a defined spectrum, at minimum:

shared `ViewProvenance`; selected depth/gate; detrending and windowing settings; spectral
estimator name; sample interval and sample rate; observation span; Nyquist frequency; bin
spacing / frequency resolution; the frequency axis; amplitude or PSD values; units; the
normalization convention; and the one-sided/two-sided rule.

**A result may not be called a PSD unless its normalization and units actually make it a
spectral density.** `PSD` is a claim about units (per Hz), not a synonym for "spectrum".

## E. Target-frequency support as a typed result

`TargetFrequencySupport`, analogous to SA1's `SupportedQuantity` — the physical targets are the
subject, so they get a type rather than notebook prose. Initial targets: **≈1 Hz** (recurrence
scale) and **500 RPM / 60 ≈ 8.3333 Hz** (nominal rotor reference).

For each requested target, report: the requested frequency; whether it is inside the measurable
band; the Nyquist margin; the bin spacing; the nearest bin or estimator evaluation frequency;
whether enough cycles fit the selected window; descriptive local spectral evidence **if
supported**; and otherwise the explicit refusal reason.

**Wording is part of the contract.** `unsupported at 8.333 Hz` must never be readable as
`no 8.333-Hz component exists`. The first is a statement about the instrument and the window;
the second is a measurement claim, and a refusal never makes one.

## F. The E64/E128 constraint — measured, and it decides the reference

This was inspected before deciding anything, as required. Measured over all 52 committed live
recordings (`data/sparse-mixer-live-{1,2}`, read through the public `.BDD` reader; intervals and
spans only, no spectral code):

| configuration | achieved rate | Nyquist | 1 Hz | 8.333 Hz |
| --- | --- | --- | --- | --- |
| `emissions-8` (burst 10, PRF 1667 Hz) | 65.789 Hz | 32.895 Hz | yes (13 cycles) | **yes** (104 cycles) |
| `emissions-20` — burst 4 / burst 18 / common-reference | 44.4–44.6 Hz | 22.2–22.3 Hz | yes (13 cycles) | **yes** (104–105 cycles) |
| `emissions-64` (burst 10) | 20.492 Hz | 10.246 Hz | yes (13 cycles) | **yes** (104–105 cycles), margin thin |
| `emissions-128` (burst 10) | **11.468 Hz** | **5.734 Hz** | yes (12–13 cycles) | **NO — above Nyquist** |

Achieved rate spans **11.468–65.789 Hz** across the sweep; Nyquist spans **5.734–32.895 Hz**.
The interval spread is a property of the acquisition, not of the analysis: the profile period
follows `emissions × PRF + 10.369 ms`, so raising `emissions_per_profile` lowers the sample rate.

**Consequences, all of them binding:**

1. The 8.333-Hz rotor reference is **refused on all eight `emissions-128` recordings** (four per
   sitting) by the Nyquist condition. This must be a **backend refusal**, not a notebook warning.
2. The 8.333-Hz reference may be compared across `emissions-8`, `emissions-20` and
   `emissions-64` **only** — and the `emissions-64` margin is thin (10.246 Hz Nyquist against an
   8.333 Hz target, ~1.23×), so its own admissibility is stated on its result rather than implied.
3. **`emissions-128` must never contribute a spectral amplitude at 8.333 Hz** to any comparison,
   and nothing may be interpolated to make it appear able to.
4. The E128 recordings are not useless — they sample *slower*, so they resolve the ≈1 Hz
   recurrence scale with the most margin of any configuration. The constraint is specific to the
   8.333-Hz target, and the design must not over-generalize it into "E128 is bad".

The trap this table exists to catch: every `emissions-128` recording holds **104–105 cycles** of
the 8.333-Hz target inside its window, so a policy that screened only *"are there enough
cycles?"* would report the target as well supported. Support requires **band and cycles
together**, and the band test is the one that refuses.

## G. Primary vs full-record spectra

Both views, kept distinct and labelled from SA1's vocabulary:

- **`primary-comparison`** — the same designed ≈12 s exposure for every recording, comparable
  across the sweep, coarser frequency resolution (1/12 s ≈ 0.083 Hz; measured full-record
  resolution is ≈0.080 Hz, so the two differ by little here, but that is a property of these
  recordings and must not be assumed).
- **`full-record`** — recording-dependent span, better exploratory resolution.

They are **not interchangeable**, and every spectral result carries the view label *and* rule
inherited from SA1, so a `primary-comparison` spectrum cannot be presented as a full-record one.

## H. Detrending and windowing — decided here, not defaulted

To be fixed explicitly before implementation, with each choice stated on every result:

- mean removal (default on, matching SA1's ACF default) and optional linear detrending, named;
- the taper/window function, named, with its amplitude/power correction;
- whether DC is retained;
- the noise-power-bandwidth correction **whenever PSD units are claimed** (ties back to §D).

No arbitrary signal-processing default is inherited, and the chosen normalization must be
demonstrated by the synthetic tests in §I rather than asserted in prose.

## I. Synthetic validation suite — before any committed-data interpretation

Synthetic traces: exact single sinusoid; two sinusoids; sinusoid + DC; sinusoid + linear trend;
constant; noise-only; target below resolution; target above Nyquist; too-short record; duplicate
timestamps; irregular timestamps; one missing/gap interval.

The tests must establish: recovered peak location; normalization and units; Nyquist refusal;
resolution refusal; timebase refusal; and **no invented peak through resampling**.

## J. Committed-data characterization — the first result

The §F table is the first instalment: per pass/job/configuration, achieved sample rate, Nyquist,
frequency resolution on the primary view and on the full record, the timebase regularity metric
(measured **1.15e-03 to 6.58e-03** against SA1's `2e-2` band, so every recording is `regular`),
and whether 1 Hz and 8.333 Hz are supported.

It answers *"what can this acquisition configuration resolve?"* before anyone inspects peak
amplitudes. That ordering is the point: the table tells us which scientific questions each
configuration is capable of answering, so a later plot cannot flatter a configuration that was
never able to answer the question.

## Out of scope for SA2 (and why)

SA2 answers: *"what frequencies can this recording resolve, and what descriptive spectral
structure is present?"* It does **not** answer whether the ≈1 Hz feature is a vortex, whether
rotor speed was measured, whether the CFD discrepancy is explained, whether one UDV setting is
scientifically superior, or whether two sittings constitute statistical replication. Those belong
to SA3/SA4 and to cross-sitting synthesis.

## Known limitation carried into SA2

Issue **#49** (`ArrayModel.model_dump(mode="json")` raises for every ndarray-bearing model) is
unresolved, so an array-bearing spectral result **cannot yet be assumed to round-trip through
JSON**. In-memory analysis is unaffected. This is recorded here so SA2 does not discover it by
losing a spectrum.
