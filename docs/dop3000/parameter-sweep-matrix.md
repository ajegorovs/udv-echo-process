# DOP3010 parameter sweep matrix

Planning note for a **sensitivity analysis**: hold a reference flow, vary the
instrument's measurement parameters one at a time, and analyse the recorded
data. This document says *which* parameters are worth sweeping, *which are
mathematically tied to each other*, and *which must never be swept*.

> **Status:** analysis/planning for the campaign — no code change yet. The
> parameter *identities and write behaviour* marked *(measured)* below are now
> verified on the instrument; [`udop-automation.md`](udop-automation.md) carries
> the actuator recipes, the store chain, the failure modes and the validated
> points. Those measurements are evidence for this plan, not a substitute for
> running it.
> **Control surface:** the 15 parameters directly settable in UDOP — US
> frequency, burst length, emitting power, TGC, PRF, first-gate depth, number of
> gates, resolution, sampling volume, emissions per profile, Doppler angle,
> sensitivity, velocity scale factor, sound speed, skipped profiles.
> **Sources:** `docs/dop3000/manual-reference/` (chapters cited inline as
> *Ch. N*), the `.BDD` parameter table (§10.7, source PDF page 70), the decoded
> settings of the committed fixtures
> (`src/udv_echo_process/io/dop/bdd.py`), and — for the items marked
> *(measured)* — the instrument-side measurement records of
> [`udop-automation.md`](udop-automation.md).

---

## 1. The rule that organises everything

Every relationship between these parameters is one of three **kinds**, and
conflating them is what makes a UDV sweep look harder than it is:

| Kind | Meaning | Example |
|------|---------|---------|
| **Mapping** | The parameter changes *which physical point* you measure or *how the recorded number is scaled*. | `depth = c·t/2`; `v_real = v_us / cos θ` |
| **Constraint** | The parameter sets a *feasibility limit* — outside it the value is ambiguous, not merely different. | `P_max = c·T_prf/2`; `V_max = c/(4 f_e T_prf)` |
| **Timing** | The parameter changes *when* samples arrive, not their value. | `T_profile ≈ T_tran + T_prf·(16 + N_PRF)` |

**The single most important structural fact for this experiment:** with
**assisted mode OFF**, the depth window is a *mapping* that does **not** contain
the PRF at all (see C4 below) — PRF only contributes a *constraint* on how far
the window may extend, plus velocity range and timing. PRF and depth are
therefore **separable axes**. Turn assisted mode **ON** and that separation
disappears: UDOP then derives PRF, emissions/profile and velocity scale as a
*compromise* to satisfy a requested depth/velocity/quality triple (Ch. 4.2,
Ch. 8.3) — you would be sweeping an input while three outputs chase it. **A
meaningful sweep requires assisted mode disabled.**

---

## 2. Governing relations

Numbered so the matrix below can reference them.

| # | Relation | Manual | Consequence for the sweep |
|---|----------|--------|---------------------------|
| **C1** | `P_max = c·T_prf/2` | Ch. 1.3, 8.1 | PRF caps reachable depth (constraint, not a remapping) |
| **C2** | `V_max = c/(4·f_e·T_prf·cosθ)` | Ch. 1.3, 8.1 | PRF, `f_e`, `c`, θ together set the unaliased velocity limit |
| **C3** | `P_max·V_max = c²/(8·f_e)` | Ch. 8.1 | Reach and speed range cannot both be maximised; `f_e` sets the product |
| **C4** | `depth_i = c·[(g1 + (r+1)(i−1))/(2·rate) − t_hw/2e6]` | §10.7, Ch. 8.5 | Window geometry is set by **first-gate index, resolution, gate count, `c`, acquisition rate, hardware delay** — *not* by PRF or `f_e` |
| **C5** | `T_profile ≈ T_tran + T_prf·(16 + N_PRF)` | Ch. 8.8 | PRF × emissions/profile × skipped profiles set the time base and its jitter |
| **C6** | `pitch = c·(r+1)/(2·rate)`; `thickness = max(burst-implied, sampling-volume)` | Ch. 8.4, 14 | Gate **pitch** ≠ sample-volume **thickness**; the two sample-volume knobs are one physical quantity |
| **C7** | `f_D = 2·f_e·v·cosθ/c`; byte→velocity span `= V_max·s`, step `= V_max·s/128` | Ch. 8.2, 5.6 | Emitting frequency, sound speed, angle and scale factor are all multipliers on the recorded mm/s |
| **C8** | `δf_d/f_d = k·λ/D·tanθ` (k = 2–3) | Ch. 15 | Intrinsic spectral width ⇒ variance floor of the velocity estimate |
| **C9** | receive gain needed `≈ 2·α(f)·z` | Ch. 8.10–8.11 | TGC is a *function of depth and frequency*, so it is a per-point covariate, never a constant |
| **C10** | `τ_burst = N_cycles/f_e ≪ T_prf` | Ch. 8.4, 14 | Burst length and frequency bound the shortest usable PRF period |
| **C11** | `resolution_mm = (word 10 + 1) · c / 12000`; word 10 is the **0-based** resolution rung index | §10.7 row 10 — stated there as a time pitch — plus measurement | The mm ladder is `c`-dependent, so the rung a sweep asks for depends on the **read-back** `c`, never on the intended one |

**C11 is additionally verified on the instrument** *(measured, 2026-09-17)*:
word 10 = `4` reads 0.6083 mm at `c = 1460`, word 10 = `1` reads 0.250 mm at
`c = 1500`. It is what makes a point's gate geometry checkable from `word 10`
and `word 19` alone, and it is why a sweep table must be recomputed from the
file's `c` before a run.

**Verified against the committed fixtures** (both directions agree):
`4 MHz / T_prf = 600 µs / c = 1460` ⇒ C2 gives 152.08 mm/s, the decoded
`velo_max_ms` is 152.05; `10 MHz / T_prf = 125 µs / c = 2740` ⇒ C2 gives
548.0 mm/s, decoded 547.9. C4 reproduces every fixture's stored gate row to
≤ 0.05 mm. So these equations are safe to design the sweep on.

---

## 3. Table 1 — the parameter matrix

`sweep class` — **Axis**: a genuine physical degree of freedom.
**Conditioning**: sets whether a measurement is possible/valid, not what it
reads (when energy is sufficient). **Window**: geometry of *what* you compare.
**Scale**: a pure multiplier. **Data-rate**: changes when you store samples.

| # | Parameter | Stored as | What it physically changes | Class | Verdict |
|---|-----------|-----------|----------------------------|-------|---------|
| 1 | **US emitting frequency** `f_e` | word 0 (kHz); 0.45–10.5 MHz w/ option, else fixed 0.5/1/2/4/8/10 | λ (⇒ sample-volume length, C8 width), attenuation α(f), backscatter, `V_max` ∝ 1/`f_e` (C2, C7); sets the reach×speed product (C3) | Axis | **SWEEP** |
| 2 | **Burst length** (emitted cycles) | word 8 *(measured)*; 2–32 step 2/4 w/ Extended resolution, else fixed 4. Dialog-only write (no sidebar field), and changing it auto-selects the sampling volume | Pulse duration τ: depth resolution `c·τ/2`, spectral width ∝ 1/τ, pulse energy, near-probe ringing/dead zone | Axis | **SWEEP — paired with 9** |
| 3 | **Emitting power** | word 7; 3 levels (≈0.5 / 5 / 35 W) | Transmitted energy ⇒ backscattered amplitude, ringing, cavitation risk, saturation | Conditioning (also scales echo data) | **SWEEP once, then freeze** |
| 4 | **TGC / amplification** | words 23–25; −40…+40 dB, 256 levels / 80 dB, uniform·slope·custom·auto *(measured: word 42 = 40 is plausibly the `Tgc [dB]` value — the same ambiguity as word 18)* | Receive gain vs depth, compensating `2αz`; too high ⇒ A/D saturation ⇒ wrong values | Conditioning, depth-shaped (C9) | **SWEEP once per window, then freeze** |
| 5 | **PRF** (period) | word 5 (µs); 64–100 000 µs w/ option, else 10 000–64 µs | Unambiguous depth (C1) and velocity (C2); where multiple-echo artifacts land; profile timing (C5) | Axis | **SWEEP** |
| 6 | **First-gate depth** | word 9, a gate *index* → mm via C4 *(measured: it moves with `First gate depth`; 31 at first gate 2 mm)*; ≥ end of burst, ≳3 mm | Near end of the window; exclusion of dead zone / ringing / wall echo | Window | **FIX** (co-set with 7, 8) |
| 7 | **Number of gates** | word 13; 4–1000 (4–100 without option) | Far end of the window; profile size, transfer time and jitter, memory | Window | **FIX** (sweep only as a data-rate axis) |
| 8 | **Resolution** (gate pitch) | word 10, `(n+1)·0.166 µs`; 0.166–20 µs w/ option, else coarse/fine per `f_e` *(measured: word 10 is the 0-based rung index, rung length = C11)* | How finely the window is sampled; overlap when pitch < thickness (C6) | Window + spatial sampling | **FIX** (bridge to 2/9) |
| 9 | **Sampling volume** (longitudinal thickness) | word 27, an **index** into the bandwidth list (6 bandwidths, 50–300 kHz) *(measured: index 3 = 0.900 mm at `c` = 1500; the allowed set is physics-driven, so read the combo and never hard-code a mm value)* | Acoustic averaging length — the *real* depth resolution; sets overlap/gap regime with 8 (C6) | Axis | **SWEEP — paired with 2** |
| 10 | **Emissions per profile** `N_PRF` | word 14; 512–8 (DOP3010) | Number of emissions averaged per velocity estimate: variance ∝ 1/√N, temporal averaging window | Axis | **SWEEP** |
| 11 | **Doppler angle** θ | word 20 (deg) | Pure scale `v_real = v_us/cos θ` (C7); also feeds flow-rate conversion | Scale | **FIX — never sweep** |
| 12 | **Sensitivity** | word 18 *(measured, but soft: it moved together with TGC in the fixture diff, so one recording that changes only sensitivity is still owed)*; 5 levels (> −100 dBm) | Detection threshold on Doppler energy: below it the value is **replaced by zero** | Validity gate | **SWEEP once (diagnostic), then freeze** |
| 13 | **Velocity scale factor** `s` | word 15 = `1000·π·s` (3142 ⇒ s = 1 in every fixture) | Fraction of the Nyquist span the signed byte covers ⇒ quantisation step `V_max·s/128`; must equal 1 for alias auto-correction | Scale / quantisation | **FIX** (or sweep deliberately as a quantisation study) |
| 14 | **Sound speed** `c` | word 19 (m/s) | Pure scale on **depth** (`c·t/2`) *and* **velocity** (C7); errors transfer 1:1 | Scale | **FIX — measure it, never sweep** |
| 15 | **Number of skipped profiles** | word 84 ("skip profile") *(measured: the `Operating parameters` field `Number of skipped profiles`, next to an `Apply skip profile` checkbox — the identity is settled, the semantics are not, see §9)* | Decimation of the acquired profile stream ⇒ effective time resolution and decorrelation of the stored series, without touching PRF or `N_PRF` | Data-rate axis | **SWEEP last** |

The remaining word identities above were confirmed by the same labelled point:
**5** `PRF [µs]`, **13** `Nb of gates`, **14** `Emissions/profile`, **19**
`Sound speed [m/s]`, **20** `Doppler angle`, **15** velocity scale factor
(`3141` = `1.00`) — that is, the "Stored as" column of this table is measured,
not manual-derived, for every sweep parameter except `f_e` (word 0), emitting
power (word 7) and the TGC words. The full word map is
[`udop-automation.md`](udop-automation.md) §9.

Two manual inconsistencies to settle **on the instrument**, not from the text:
§8.4 gives the sampling-volume lengths as ≈0.64–3.19 mm in water, while the
§21/§22 specification tables list 3.9 / 2.9 / 1.3 / 1.1 / 0.8 / 0.7 mm at
c = 1500 m/s. Word 27's "Bandwidth definition" is the knob either way.

---

## 4. Table 2 — coupling map

The matrix is sparse: 15 knobs collapse into five groups plus two cross-links.
Parameters in the same group **must be set together** or the comparison is not
like-for-like.

### Co-set groups

| Group | Members | Coupled by | Why they travel together |
|-------|---------|-----------|--------------------------|
| **W — window** | 6 first gate, 7 gate count, 8 resolution | C4, C6 | These three (with the fixed `c`, acquisition rate, hardware delay) *define* the measured volume. Change one alone and you move or crop the window — every other axis then compares different fluid. |
| **A — acoustic resolution** | 2 burst length, 9 sampling volume | C6 | Effective thickness = the **larger** of the two. Sweeping either alone when the other dominates produces a flat, misleading result. Fix one, sweep the other — then swap. |
| **T — time base** | 5 PRF, 10 emissions/profile, 15 skipped profiles | C5 | Multiplicative in `T_profile` and in the stored sample interval. Two of them changed at once leaves the time axis unidentifiable. |
| **E — energy / validity** | 3 power, 4 TGC, 12 sensitivity | C9 + Ch. 8.6, 8.10 | Mutually compensatory: any one of them can supply the missing Doppler energy. They act at *different places* (transmit energy / receive gain / post-detection threshold), which is exactly why they must not be swept simultaneously. |
| **S — frozen scales** | 11 Doppler angle, 13 velocity scale factor, 14 sound speed | C7 | Pure multipliers on the recorded mm and mm/s. Sweeping a multiplier measures the multiplier, not the flow. |

### Cross-links

- **1 (`f_e`) ↔ 5 (PRF)** through **C3**: `f_e` sets the reach×speed *product*, so
  PRF alone cannot be swept "at constant capability". Decide `(f_e, PRF)` as a
  feasibility pair first (§5, Tier 0).
- **1 (`f_e`) ↔ 4 (TGC)** through **C9**: attenuation grows with frequency, so a
  TGC conditioned at 4 MHz under-gains at 10 MHz. TGC is re-conditioned **per
  sweep point** and the conditioning value recorded, never held blindly.
- **1 (`f_e`) ↔ 9 (sampling volume)** through λ: at fixed cycles, thickness ∝ 1/`f_e`.
- **2 (burst) ↔ 5 (PRF)** through **C10**: a long burst at low `f_e` may not fit a
  short PRF period — check before pushing either extreme.
- **2/9 ↔ 10 (`N_PRF`)** through **C8**: spectral width sets a variance floor that
  more averaging cannot beat. The `1/√N` improvement therefore *saturates*;
  finding where it saturates is a result, not a nuisance.
- **8 (resolution) ↔ 5 (PRF)** only indirectly: the pitch in mm is
  PRF-independent, but a fine pitch near `P_max` can push the last gates into
  the ambiguous zone implied by C1.

### Explicitly *not* coupled

- PRF ↔ window geometry (C4 contains no PRF) — **provided assisted mode is off**.
- `f_e` ↔ window geometry (same reason).
- Emissions/profile ↔ velocity *bias*, for steady flow. It changes variance; a
  bias appearing here means the flow is unsteady within the averaging window,
  which is itself a finding.
- Sensitivity ↔ measured value, when Doppler energy is high — this is the
  manual's own claim (Ch. 8.6) and it is the built-in pass/fail test for a
  valid sweep point.

---

## 5. Table 3 — the sweep plan

### Tier 0 — feasibility pair (before anything is swept)

Build the `(f_e, PRF)` map from C1–C3 against your rig: the deepest gate you
need and the fastest flow you expect. Fix the pair that satisfies both with
margin, and only then start Tier 1. Without this, a PRF sweep will silently
walk part of your window past `P_max`.

### Tier 1 — science axes (one at a time, everything else at baseline)

| Axis | Suggested levels | Expected signature | Reference check |
|------|------------------|--------------------|-----------------|
| 1 `f_e` | 1 / 2 / 4 / 8 MHz (probe permitting) | `V_max` ∝ 1/`f_e`; thickness ∝ 1/`f_e`; attenuation ↑ with `f`; spectral width ↓ with `f` | decoded `V_max` vs C2 |
| 5 PRF | `T_prf` 125 → 1000 µs in ×2 steps, **window held** | aliasing onset (fold-over vs reference); artifact depth shifts; jitter in `T_profile` | mean ± min/max "time between profiles" (Ch. 8.8) |
| 10 `N_PRF` | 8 / 16 / 32 / 64 / 128 / 256 | σ ∝ 1/√N until C8's floor, then flat | σ across profiles at a fixed gate |
| 2 burst length | 2 / 4 / 8 / 16 / 32 cycles | thickness vs spectral-width trade; dead zone grows | first valid gate (zeros at profile start) |
| 9 sampling volume | the bandwidths the instrument offers (physics-driven; read the combo, do not hard-code a mm value), burst fixed | same trade-off, resolved independently of 2 | pulse profile sharpness across a known interface |
| 15 skipped profiles | 0 / 1 / 2 / 3 / 7 | stored sample interval grows; inter-profile correlation drops | `TBD` column of the `.ADD` / timestamp deltas |

Run Tier 1 in **randomised order with the baseline point repeated at the start,
middle and end** of each axis, so rig drift is separable from the parameter
effect.

### Tier 2 — energy/detection envelope (once per window, then frozen)

`power {low, medium, high}` × `TGC (uniform, then verify slope vs uniform)` ×
`sensitivity {5 levels}`, at fixed flow. Read out: echo-profile saturation,
zero fraction, σ across profiles, and bias vs reference. **Pass/fail:** bias must
not move with sensitivity — if it does, the Doppler energy is marginal (Ch. 8.6)
and every Tier-1 point measured in that regime is a detection result, not a
physics result. Condition against the *worst* case (deepest gate, highest `f_e`)
and record the conditioning values per point.

### Tier 3 — frozen (must not be swept)

`sound speed`, `Doppler angle`, `velocity scale factor`, and — for a like-for-like
comparison across Tier 1 — the whole **W** group. Also keep **OFF/disabled**:
assisted mode, real-time filters (a moving average masks aliasing so subtly that
the manual forbids it during PRF selection, Ch. 8.1; the median filter is
recommended *because* low-energy spikes exist, Ch. 6.2), and aliasing
auto-correction (it changes the recorded file structure, Ch. 9.3, and requires
`s = 1`).

---

## 6. Per-point recording protocol

Every sweep point must store enough to prove the point was valid:

1. **Velocity *and* echo profiles in the same recording.** The echo profile is
   the only display that reveals receiver saturation (Ch. 8.11) — i.e. the only
   evidence that a velocity value is trustworthy; and it is the quantity the
   repo's RPM analysis consumes.
2. **The parameter block itself.** The `.BDD` op-parameter table (§10.7, words
   0–95) already stores every knob in this matrix — it is the sweep's log, and
   the only trustworthy read-back: a field's displayed text can disagree with the
   application's model, so a point is accepted or rejected by decoding its stored
   file, naming the channel it read *(measured — see*
   [`udop-automation.md`](udop-automation.md)*, §2, §6, §9)*. `.ADD` carries none
   of it.
3. **Timing statistics**: mean / min / max time between profiles. A red
   "time between profiles" label means the acquisition is not constant — reduce
   gate count, curves, or raise `T_prf` (Ch. 8.8). *(Measured):* `Time between
   profile` is an **input constraint**, not a derived curiosity — it decides how
   many profiles a point produces and therefore what the block cap must be, and
   it must be measured per point rather than trusted from C5: `100 emissions ×
   200 µs` was reported as **21.2 ms** (≈ 47–50 profiles/s), against C5's 23.2 ms
   plus transfer time. Seconds stay the specification; profiles are an output.
4. **Validity counters**: zero fraction per gate (sensitivity + energy envelope),
   and the dead-zone extent (first gate with non-zero values).
5. **An independent reference of the flow, on a shared clock.** The rig's own
   drive setpoint/encoder is ideal; for a periodic reference use the external
   trigger (TTL, delay 0–32 s, words 34/47) rather than assuming clock alignment.

Derived metrics that make the analysis "deep" rather than comparative:
bias vs reference at a fixed gate and area-averaged; σ between profiles; axial
edge sharpness across a known interface (acoustic resolution); aliasing margin
`V_measured/V_max`; effective decorrelation time of the stored series
(skipped profiles); spectral width where a gate FFT is available.

---

## 7. Pre-flight checklist

1. **Verify `c`.** Sound speed is a 1:1 multiplier on *both* depth and velocity
   (C4, C7). Measure it in place (Ch. 7: reflector 15–50 mm, longest burst).
   ⚠ **Anomaly to resolve first:** the committed fixtures do **not** agree —
   `data/echo/*.BDD` decode `c = 2740 m/s` (ch 4, 10 MHz) while
   `data/4-sensor-velocity/*.BDD` and the 4-sensor echo fixture decode
   `c = 1460 m/s`. Both reproduce their own stored gate rows exactly, so the
   *value used at recording time* was 2740 for the echo series. Since 2740 is
   ~1.85× water, confirm what was actually entered on the rig before sweeping
   anything else — otherwise every depth and every mm/s in that series carries
   that factor.
2. **Assisted mode OFF** (else PRF / `N_PRF` / velocity scale are outputs).
3. **Filters OFF**, aliasing auto-correction OFF.
4. **Echo profile unsaturated** at baseline; dead zone mapped (first gate ≥ end
   of burst, ≳3 mm).
5. **Sensitivity bias test** at baseline: no change ⇒ energy is sufficient.
6. **Single-channel** acquisition (`Use only channel`) unless the sequence is
   itself the object of study — after a multiplexer switch the first profile is
   noisier (Ch. 11.3), so either drop it or never compare across the switch.
7. **Confirm the optional packages installed** on this unit: variable frequency,
   variable gates, extended resolution, variable TGC, additional compute mode.
   Without them, `f_e`, resolution, first gate, gate count and `N_PRF` are not
   freely settable at all (Ch. 21/22).
8. **Write order and read-back** *(measured).* Write the structure-determining
   parameters (resolution, first gate) **before** the one the application derives
   (gate count) and read the set back **before** recording: this channel's
   per-channel auto-resolution and auto-gate-selection flags (words 11/12) make
   the application silently recompute the gate count whenever the resolution
   changes, which trimmed a requested 805 gates to 474 in the first sweep run.
   The recomputation is visible in the control's own text, so a pre-record check
   costs nothing; the decisive check stays the stored file (§6.2).

---

## 8. What the rig already covers (baseline)

Both pilot rigs currently sit at fixed settings — a useful `Tier-0` baseline,
and evidence that none of Tier 1 has been explored yet:

| Fixture | `f_e` | PRF period | burst | window | `c` | power / sens / TGC |
|---|---|---|---|---|---|---|
| `data/4-sensor-velocity/200RPM.BDD` (ch 6–9, velocity) | 4 MHz | 600 µs | 12 cycles | 20.00 → 79.13 mm, 55 gates @ 1.095 mm | 1460 | low / medium / uniform 40 dB |
| `data/echo/*.BDD` (ch 4, echo) | 10 MHz | 125 µs | 8 cycles | 42.97 → 54.39 mm, 26 gates @ 0.457 mm | 2740 | medium / medium / uniform 40 dB |
| `data/echo-4-sensors-2x2/` BDD (ch 9, echo) | 4 MHz | 250 µs | 2 cycles | 45.43 → 70.25 mm, 35 gates @ 0.73 mm | 1460 | medium / medium / 24.9 → 40 dB |
| `data/mixer-sensitivity-analysis/4MHz/0500RPM/001/prf/600.BDD` (ch 1, velocity) | 4 MHz | 600 µs | 10 cycles | 10.16 → 100.81 mm, 50 gates @ 1.85 mm | 1480 | medium / medium / uniform 19.9 → 40 dB |

The fourth row is the **reference point of the sensitivity analysis** — the base state that `001`'s
axis folders hold while varying one parameter at a time (recorded 2026-09-16). The run's own note
states that base state — *sensitivity medium, emitting power medium, TCG 20, emissions/profile 20,
resolution 1.85 mm, gates 50, PRF 600, burst length 10* — and the file's header agrees on every
value the reader decodes: `f_e` = 4000 kHz, `T_prf` = 1666.67 Hz (600 µs), burst length 10,
`emit_power` / `sensitivity` *medium*, gate 1 = 10.16 mm with 50 gates at 1.85 mm, `c` = 1480 m/s,
TCG *uniform* 19.9 → 40 dB, `V_max` = ±154.14 mm/s, 669 profiles over 14.96 s.

**One base-state value the file cannot state is `Emissions/profile` = 20.** Word 14 is exactly the
decode §9 lists as missing, so this point cannot be identified from its own file alone — the reader
gap measured on a real sweep point rather than argued from the manual. The PRF axis as recorded
beside it is 400 / 500 / 600 / 700 / 800 µs: 100 µs steps around this point, finer than §5 row 5's
×2 ladder.

**And the set it belongs to is committed.** The same visit produced five *sparse* sweeps around
this reference point — `prf` 400…800 µs, `burst_len` 2…32, `res` on the instrument's rung labels
`0-2`…`3-0`, `tgc` 0…40 dB and `em_pow` low/high — forty `.BDD` files in all, copied byte for byte
and listed with their own SHA-256 in
[`data/mixer-sensitivity-analysis/README.md`](../../data/mixer-sensitivity-analysis/README.md),
which also carries the rig's geometry (a magnetic pill mixer, water in a 10 x 10 x 5 cm vessel,
measured ~2.5 cm off centre and ~2.5 cm up, flow circular with corner eddies). The points were
picked roughly and measured by hand, **none of them has been analysed**, and the manual procedure
was tedious enough that acquisition automation became the route instead — so the set is raw
material for this matrix, not evidence about the flow.

Implied by C2 at the velocity baseline: `V_max = 152 mm/s`, quantisation step
`V_max·s/128 ≈ 1.19 mm/s` at `s = 1`. Measured values sit around 30 % of scale,
while Ch. 8.1 recommends ≥ 50 % — a first, cheap Tier-0 improvement.

---

## 9. Reader gaps (what this repo must add before the sweep can be analysed)

`src/udv_echo_process/io/dop/bdd.py::_OP_PARAM` decodes 12 of the 15 sweep
parameters. Missing, and needed to identify a sweep point from the file alone:

| Parameter | Word | Status |
|---|---|---|
| Emissions per profile (`N_PRF`) | 14 | not decoded — the primary variance axis; **identity measured** (it tracks `Emissions/profile`, 100 → 44) |
| Sampling volume / bandwidth | 27 | declared as `ChannelConfig.sampling_volume_mm`, never populated; **identity measured** as an index into the physics-driven bandwidth list (index 3 = 0.900 mm at `c` = 1500) |
| Number of skipped profiles | 84 | not decoded — **identity measured** (`Number of skipped profiles` in `Operating parameters`); its semantics are still unconfirmed (see below) |
| (also) wall filter | 16 | declared as `ChannelConfig.wall_filter`, never populated |

So what is missing is the decode, not the word identification — every identity
above now comes from a labelled recording rather than from the manual's table
([`udop-automation.md`](udop-automation.md) §9).

Word 84's *name* comes from the manual's parameter table ("skip profile"); no
narrative chapter describes its behaviour, so its exact semantics (skip N
between acquisitions vs. discard N at start) must be confirmed on the
instrument before it is used as a sweep axis.

---

## 10. Open items

1. Is `c = 2740 m/s` in the echo fixtures a deliberate entry (a rig-specific
   calibration) or a stale default? Affects every existing conclusion about
   depth and mm/s in that series. *(Measured on the instrument, 2026-09-17: one
   stored file carried `c = 1460 m/s` on channel 1 and `c = 1500 m/s` on
   channel 10 — `c` is a per-channel configuration value, so a read must name
   the channel it read; see [`udop-automation.md`](udop-automation.md) §6.)*
2. Which optional software packages are installed on this unit — the sweep
   surface is smaller without them.
3. `skip profile` (word 84) semantics.
4. Sampling-volume lengths: 0.64–3.19 mm (Ch. 8.4) vs 0.7–3.9 mm (Ch. 21/22).
5. Is the reference flow stable enough over a full campaign, or does each axis
   need interleaved baseline points? (Decides randomised-ofat vs blocked design.)

Instrument-side open questions from the same work — the block's behaviour past
the configured cap, the shared-memory-pool question, the identity of the at-cap
warning, the burst ↔ sampling-volume acceptance sets — are recorded in
[`udop-automation.md`](udop-automation.md) §11; they constrain what a point may
ask for, not which axes are worth sweeping.
