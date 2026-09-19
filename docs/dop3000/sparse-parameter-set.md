# The first sparse measurement set — draft for review

> **Status:** proposal for review. This PR carries a **document**, not code and not a campaign
> definition: the intended outcome is agreement on a small explicit list of complete parameter sets.
> Encoding that list and adding whatever writers it needs is the *next* PR.
>
> **What it answers.** [`acquisition-closeout-plan.md`](acquisition-closeout-plan.md) §4 makes the
> matrix question the gate for the next stretch: *is
> `experiment_data\mixer\sensitivity-analysis\4MHz\0500RPM\001\burst_len` the experiment this work is
> for?* This document answers **yes at the axis level** and says which axes the first sparse set is
> built from, so §4's dependent decisions (which writers are funded, whether the application's own
> `Sweep PRF` search is an axis) can be settled against a named list instead of a principle.
>
> **Grounded in:** the DOP3000/3010 manual (`manual-reference/`, cited as *Ch. N* through
> [`parameter-sweep-matrix.md`](parameter-sweep-matrix.md)); the 4 MHz reference acquisition and the
> 40-point hand-measured sparse set committed in
> [`data/mixer-sensitivity-analysis/`](../../data/mixer-sensitivity-analysis/README.md); the relations
> of [`parameter-sweep-matrix.md`](parameter-sweep-matrix.md) §2–§3 and its §9 reader gaps; and the
> write surface of [`src/udv_echo_process/acquire/`](../../src/udv_echo_process/acquire/).

---

## Purpose

Define and review the **first sparse DOP3010 measurement parameter set** for the mixer sensitivity
experiment.

The output of this PR is not intended to be the final dense design of experiments. Its purpose is to
converge on a small, physics-grounded list of complete acquisition parameter sets that can be measured
first, analysed, and then used to design a denser second-stage sweep.

The proposal is grounded in:

- the DOP3000/3010 manual;
- the existing 4 MHz reference acquisition;
- the 40-point hand-measured sparse sweep under `data/mixer-sensitivity-analysis`;
- the parameter relationships documented in `docs/dop3000/parameter-sweep-matrix.md`;
- the capabilities and present limitations of the acquisition automation under
  `src/udv_echo_process/acquire/`.

## Experimental reference

Initial reference condition:

| Parameter | Reference |
|---|---:|
| emitting frequency | 4 MHz |
| PRF period | 600 µs |
| sound speed | measured/read-back value; existing mixer data ≈1480 m/s |
| first gate | ≈10.16 mm |
| far end of window | ≈100 mm |
| resolution | 1.850 mm |
| gates | 50 |
| burst length | 10 cycles |
| emissions/profile | 20 |
| emitting power | medium |
| TGC | ≈20 dB uniform (the file states uniform 19.9 → 40 dB, matrix §8) |
| sensitivity | medium |
| velocity scale | 1 |
| assisted mode | OFF |
| filtering during acquisition | OFF |
| alias auto-correction | OFF |

The stored `.BDD` file remains the authority for the achieved parameter values.

## Candidate Stage-1 sparse set

The first pass should avoid a Cartesian product. Parameters are sufficiently coupled that a full
factorial design would spend many acquisitions on combinations that do not answer independent
questions.

### A. Spatial-sampling axis

Keep the physical observation window approximately 10–100 mm while changing gate pitch and
compensating with gate count.

| ID | resolution | gates | role |
|---|---:|---:|---|
| R1 | 0.247 mm | 365 | strongly overlapping / very fine |
| R2 | 0.617 mm | 145 | near lower acoustic-volume scale |
| R3 | 1.233 mm | 74 | intermediate |
| REF | 1.850 mm | 50 | current reference |
| R4 | 2.960 mm | 31 | coarse |

These are already demonstrated accepted DOP3010 rungs in the committed mixer dataset.

Recommended acquisition order should contain reference repeats, e.g.

`REF → R1 → R2 → REF → R3 → R4 → REF`

with the non-reference points optionally randomized.

The reference repeats are part of the design rather than duplicates: they provide a direct measure of
mixer/seeding/temperature/coupling drift.

### B. PRF axis

At 4 MHz, candidate sparse PRF periods:

`250, 400, 600, 800 µs`

Approximate unaliased velocity limits for `c ≈ 1480 m/s`:

| PRF period | Vmax |
|---:|---:|
| 250 µs | ±370 mm/s |
| 400 µs | ±231 mm/s |
| 600 µs | ±154 mm/s |
| 800 µs | ±116 mm/s |

All remain comfortably compatible with the ≈100 mm measurement depth.

Do not include 1000 µs in the first screening set; reserve it as a possible intentional
aliasing-challenge point after the observed velocity distribution is known.

### C. Emissions/profile axis

Candidate sparse values:

`8, 20, 64, 128`

These span:

- near-minimum averaging / high temporal resolution;
- the current reference;
- moderate averaging;
- strong temporal averaging.

This axis is important because the manual explicitly ties emissions/profile to estimator variance and
acquisition time.

### D. Burst-length axis

Candidate sparse values:

`4, 10, 20, 32 cycles`

At 4 MHz and `c ≈ 1480 m/s`, their approximate burst-implied axial lengths are:

| burst | axial length |
|---:|---:|
| 4 | ≈0.74 mm |
| 10 | ≈1.85 mm |
| 20 | ≈3.70 mm |
| 32 | ≈5.92 mm |

This spans the receiver-bandwidth-limited region through clearly burst-dominated spatial averaging.

Sampling volume should initially be treated as an **achieved/read-back covariate coupled to burst
length**, not as an independent sweep axis.

### E. Sensitivity diagnostic

Sensitivity is not initially treated as an optimisation axis.

Use a small three-level diagnostic spanning the available scale, including the present `medium`
setting and at least one higher-sensitivity condition.

Manual criterion:

> if changing sensitivity changes the measured velocity distribution, Doppler energy is insufficient.

Such a result should trigger investigation of transmitted power, TGC, seeding or coupling rather than
selection of a "better" sensitivity value.

## What the committed set already demonstrates

The candidate rows are not all new. Checked against
[`data/mixer-sensitivity-analysis/README.md`](../../data/mixer-sensitivity-analysis/README.md) and the
matrix document's §8/§9, so a reviewer can check them the same way:

- **The spatial axis is already measured, rung for rung** — `res/0-2` = 0.247 mm × 365 gates,
  `res/0-6` = 0.617 mm × 145, `res/1-2` = 1.233 mm × 74, `res/1-8` = 1.850 mm × 50 (the reference
  point), `res/3-0` = 2.960 mm × 31, all holding the window at ≈10.16 → ≈100 mm. So R1–R4 ask the
  instrument for rungs it has already accepted, at gate counts it already accepted.
- **The rung labels are the instrument's, not millimetres** (README; matrix §2 C11): the mm value of a
  rung is `c`-dependent, so R1–R4 must be *requested* in mm and *read back* from the file's word 10.
  Nothing in this set may be identified by a folder name.
- **PRF 400 / 600 / 800 µs are committed**; the set also holds 500 and 700 µs. Reproducing their
  `V_max` from C2 at `c` = 1480 m/s gives 231.25 / 154.17 / 115.62 mm/s against the files' own decoded
  231.21 / 154.14 / 115.60.
- **250 µs is new** (the committed floor is 400 µs) but feasible on both bounds: C2 gives ±370 mm/s and
  C1's `P_max = c·T_prf/2` gives 185 mm, against a window that ends at ~100 mm.
- **Burst 4 / 10 / 20 / 32 are measured rungs** of the committed `burst_len` sweep (2…32 in 2-cycle
  steps); 10 is the reference. The axial lengths above follow from `τ = N/f_e` and `c·τ/2`.
- **Emissions/profile is the axis with no committed variation at all**: all 40 points carry
  `N_PRF` = 20, recovered from the recorded time base rather than from the file (matrix §9 — word 14 is
  the decode gap). 8 / 64 / 128 are inside the manual's `512…8` range and would make the axis readable
  from the file alone — which is itself an argument for keeping this axis in Stage 1.
- **The sensitivity diagnostic is the one candidate with nothing behind it**: every committed point is
  `sensitivity` *medium*, and matrix §3 row 12 records its word identity as *soft* (it moved together
  with TGC in the fixture diff). One recording that changes only sensitivity is still owed, which is
  what makes it a Stage-1 candidate rather than a Stage-2 one — see review question 6.

## Parameters deliberately excluded from the first sparse set

### Emitting frequency

Keep at 4 MHz for Stage 1.

Changing frequency simultaneously changes wavelength, Doppler conversion, attenuation, beam field,
acoustic resolution and transducer response. Frequency should therefore be studied later as a separate
probe/frequency campaign.

### Sound speed

Measure/read back and fix. It directly scales both distance and velocity.

### Doppler angle

Fix. It is a geometric conversion parameter rather than a useful instrument-sensitivity axis.

### Velocity scale factor

Fix at 1 unless a later experiment explicitly studies quantisation.

### First gate / measurement window

Fix approximately 10–100 mm for the first comparison. A near-field/dead-zone experiment can be designed
separately.

### Skipped profiles

Defer until acquisition parameters are settled. It primarily changes temporal subsampling of the stored
series.

### Power and TGC

Do not immediately reacquire dense sweeps.

The existing 40-point dataset already contains:

- a broad TGC sweep;
- low / medium / high emitting-power conditions;
- a dense resolution ladder;
- a broad burst-length sweep;
- PRF 400–800 µs.

Analyse those recordings before deciding whether additional energy-envelope measurements are
necessary.

## Candidate unique conditions

Ignoring repeated reference controls, the proposed first screening design currently contains:

- 5 spatial-resolution conditions, including the reference;
- 4 PRF conditions, including the reference;
- 4 emissions/profile conditions, including the reference;
- 4 burst-length conditions, including the reference;
- 3 sensitivity diagnostic conditions, including the reference.

Because the same reference belongs to every axis, this is **17 unique candidate conditions at most**,
and fewer if review decides to postpone sensitivity or reuse information from the existing dataset.

Reference repetitions are then inserted into acquisition order independently of the unique-condition
count.

The PR should converge on this list before it is converted into an executable campaign definition.

## Current automation constraint

The desired scientific parameter matrix is ahead of the current per-point writer surface.

At present:

- `resolution_mm` and `gates` are the established per-point writes
  (`acquire/actuator.py::PARAMETER_WRITE_ORDER` is exactly `(resolution, gates)`);
- PRF, emitting frequency and emissions/profile exist in the measurement parameter column but are
  currently treated as shared campaign covariates — `acquire/campaign.py` carries `prf_us` and
  `emissions_per_profile` as run-wide values that a point may not disagree with, and emitting frequency
  is not a campaign field at all;
- burst length, first-gate depth, TGC and related values use the operating-parameters dialog
  (`acquire/actuator.py::DIALOG_ONLY_PARAMETERS`, and `acquire/campaign.py`'s own list of the
  five facts a point cannot write);
- sampling volume is currently read back rather than independently written — its word (27) is not
  decoded either, so the achieved value is not currently available at all (matrix §9).

Therefore this PR defines the **scientific target set**, not a claim that every row can already be
executed by one unattended campaign.

Implementation work should follow the accepted matrix rather than allow present automation limitations
to determine the physics experiment.

## Analysis required before Stage 2

The first sparse dataset should be evaluated using at least:

- velocity bias/reference consistency;
- velocity variance versus depth;
- zero/rejected-value fraction;
- aliasing margin `|v| / Vmax`;
- achieved profile interval and profile count;
- temporal spectra / autocorrelation where meaningful;
- spatial smoothness and resolved-gradient behaviour;
- sensitivity to reference-repeat drift;
- echo amplitude/saturation where available.

The second-stage dense sweep should be concentrated around transitions found by this analysis rather
than uniformly filling the parameter domain.

## Review questions

1. Is the ≈10–100 mm observation window the correct invariant window?
2. Should the finest spatial point be 0.247 mm, or is 0.617 mm sufficient for the first pass?
3. Accept PRF periods `250/400/600/800 µs`?
4. Accept emissions/profile `8/20/64/128`?
5. Accept burst lengths `4/10/20/32`?
6. Include the three-level sensitivity diagnostic in Stage 1, or defer it until after analysis of the
   existing dataset?
7. Should power/TGC be considered already screened by the existing 40-point dataset?
8. What fixed duration should each acquisition use?
9. How many reference repeats are needed per axis/campaign?
10. Which currently unsupported parameter writers are required before the accepted sparse set can be
    executed unattended?

## Intended outcome of this PR

Merge only once there is agreement on a **small explicit list of complete parameter sets** suitable for
the first sparse automated measurement campaign.

The following PR should then encode that accepted list in the campaign-definition format and add
whatever acquisition writers are still required.
