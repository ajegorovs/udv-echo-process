# How DOP ultrasonic Doppler measurements work

A conceptual explainer for the **DOP3000 / DOP3010** ultrasound Doppler
velocimeters (Signal Processing S.A.): the physics of one measurement, what a
single-sensor recording contains, and how multiplexed (multi-transducer)
recordings are organised on disk.

> **Level:** general idea. We focus on the concepts you need to read and
> interpret `.ADD`/`.BDD` files (and this repo's `ChannelFrame` model), not on
> the full instrument theory.
>
> **Sources:** *DOP3000/3010 Users Manual* v6.6.1 (Signal Processing S.A.) —
> chapter numbers are cited inline as *Ch. N*. Instrument-specific numeric
> details were cross-checked between two machine extractions of the manual;
> where the manual itself is loose or contradictory that is flagged below.
> If an exact figure matters, verify it against the `.BDD` metadata or the
> manual for your device/software version.

---

## 1. How a measurement is done — the basic physics

### 1.1 Sound pulses instead of a needle

A Doppler velocimeter measures flow **without inserting anything into it**:
an ultrasonic transducer (piezoelectric ceramic) is pressed against the fluid
through a coupling medium, emits a very short **burst** of ultrasound, and —
because it is the same element — immediately listens for the returning echoes.

The ultrasound travels through the liquid at the sound speed `c`
(≈ 1480 m/s in water, but strongly medium-dependent). It is scattered back by
small particles carried with the flow (seeds, bubbles, impurities): any object
whose acoustic impedance differs from the liquid reflects part of the wave.
The same scatterers are hit again by every subsequent burst, which is what
makes the measurement repeatable (Ch. 1, 18).

### 1.2 Why the emission is pulsed, and what PRF is

A **continuous** wave would only give you a signal *averaged along the whole
beam*. To get **depth-resolved** information the instrument transmits **pulses**
— short bursts repeated periodically — and selects depth by **time of flight**:
the echo from a scatterer at depth `x` arrives `t = 2x/c` after the burst
(round trip), so listening in a narrow time window selects a narrow depth band.
The whole burst sequence is repeated at a rate called the **PRF** (pulse
repetition frequency, `PRF = 1/T_prf`).

Two consequences follow from sampling periodically (Nyquist):

- **Maximum depth** — the echo of the deepest wanted gate must return before
  the next burst is emitted:
  `d_max ≈ c / (2·PRF)`.
- **Maximum velocity (aliasing)** — velocity is derived from the *change*
  between successive emissions (below), and a sampled signal cannot represent
  Doppler shifts above `PRF/2`; faster flow "folds back" and reads as a wrong
  (often negative) velocity. The unaliased velocity limit is
  `v_max ≈ c·PRF / (4·f_e·cosθ)` (θ = Doppler angle), i.e. the instrument
  *cannot simultaneously measure very deep and very fast* — raising the PRF
  buys velocity range at the cost of depth range, and vice versa (Ch. 1, 8, 9).

### 1.3 From echoes to two kinds of "profile"

Per depth gate the instrument can produce two different quantities:

- **Echo (modulus):** the strength of the returning echo at each depth — the
  envelope of the received signal. This shows *what is there* (moving particles,
  stationary structures, interfaces, bubbles) and is used e.g. to detect
  interfaces or to check that the beam is well coupled. Values are relative
  (unitless, ~1…2048 full scale in the raw format).
- **Velocity:** the component of the flow along the beam. Scatterers moving
  with the flow shift the phase of successive echoes; equivalently the echo is
  Doppler-shifted by
  `f_D = 2·f_e·v·cosθ / c`
  where `f_e` is the emitting frequency, `v` the flow speed, `θ` the angle
  between the beam axis and the flow direction (cos θ = 1 for axial flow).
  Only the **along-beam component** is measured, hence the Doppler angle θ is a
  setup parameter (Ch. 1, 5, 8).

Inside the velocimeter the received echo is amplified with depth-dependent
gain (TGC, compensates attenuation), demodulated to the Doppler-frequency
band, digitised, and high-pass filtered to remove stationary echoes (walls).
The **velocity estimate per gate** is obtained statistically: because scatterers
give a random echo, many emissions are combined (auto-correlation of the
demodulated signal over successive emissions) to estimate the mean Doppler
frequency — and therefore the mean velocity — at that gate (Ch. 2, 16).

### 1.4 Resolution: the sample volume

Each depth band corresponds to a finite **sample volume** on the beam:

- its **axial (depth) length** is set by the emitted burst length and the
  receiver bandwidth/integration time (roughly `c·τ` with the effective pulse
  duration `τ`; shorter bursts → finer depth resolution but less accurate
  velocity, because a long burst has a narrower spectrum);
- its **lateral size** is set by the beam width of the transducer.

The **gates** are the successive sample volumes along the beam. The manual
reports a gate's depth as the distance to the *beginning* of its sample volume
(measured from the transducer surface), while **resolution** is the spacing
between the *centres* of neighbouring sample volumes — the DOP manual is
explicit that resolution is not the sample-volume thickness (Ch. 5, 8, 14).
With dense gates the sample volumes overlap. Near the transducer, the burst and
the ceramic ringing leave a dead zone (in practice the first gate is ≥ ~3 mm)
(Ch. 8).

---

## 2. Single-sensor recordings — burst, profile, gates

This section explains the vocabulary you meet when reading one channel of
measurement. (A single-sensor recording is the special case of §3 with one
active channel.)

### 2.1 The vocabulary, in order of time

| Term | Meaning |
|------|---------|
| **Burst / emission** | One short transmitted pulse — a train of `N` cycles of the emitting frequency `f_e` (e.g. 4 cycles fixed, or 2–32 cycles with the extended-resolution option). One *emission* = one burst. |
| **PRF** | How often bursts are emitted (`1/T_prf`). Acts as the sampling rate of the Doppler signal; sets the depth/velocity envelope of §1.2. |
| **Gate** | One depth window along the beam, defined by a delay after emission. Gates are spaced along depth by the "resolution"; the first gate sits just past the dead zone. |
| **Profile** | One complete measurement along the beam at one instant: one value **per gate** (velocity or echo modulus) → one "line" of data (one data row in a `.ADD` file; a `Gate Depth [mm]` section holds several profiles of one block/channel). |
| **Emissions per profile** | The number of emissions (`N_PRF`) the instrument combines to estimate one velocity profile. More emissions → lower variance, but slower refresh; the rate of profiles is therefore tied to the PRF. |
| **Time between profiles** | The period between two successive profiles of a channel: roughly `T_transfer + T_prf·(16 + N_PRF)` (16 = fixed internal emissions used for the estimator) — at minimum a few ms per profile. This is the instrument's refresh rate for that channel. |

So a *velocity profile* is not one echo: it is a **statistical estimate**
computed over `N_PRF` successive emissions, and each gate contributes its own
mean-Doppler-frequency value, i.e. one velocity number per gate (Ch. 5, 8).
An *echo-modulus profile* is closer to a single-emission snapshot, but the file
layout treats both the same way: **one row = one profile, one column per gate**.
Echo files are labelled `Amp`, velocity files `mm/s`.

### 2.2 What ends up in a file

For one sensor the ASCII export (`.ADD`) is:

```
ASCUDOPV…                  <- format/version magic
<comment>
Gate Depth [mm]            <- one row: gate depths, e.g. 20.00 … 79.13 mm
mm/s  mm/s  …  TBD [ms]  No block  Channel     <- units row
…profile 1 values…          0.00   1   4       <- data rows = successive profiles
…profile 2 values…         25.40   1   4
…                            …               
```

- The **gate depths** (first data line) are the positions of the gates along
  the beam measured from the transducer surface (start of each sample volume).
- Each **data row is one profile**; the value columns are per-gate.
- Three extra columns end each row: the time stamp **TBD [ms]** (the manual
  never expands "TBD"; empirically "time between data" — cumulative from the
  recording start in raw files, a constant per-block acquisition interval in
  statistical files), the **block** number and the **channel** number (§3).
- The **binary twin `.BDD`** keeps the same profiles but *raw* (uncalibrated)
  plus the full instrument parameter set (PRF, burst length, TGC, filters,
  sound speed, Doppler angle, …) — `.ADD` is the calibrated, parameter-less
  export for other software (Ch. 10, 10b; see `docs/doppy-analysis.md`).
- A **statistical variant** (`*_Stat.ADD`) compresses every group of
  `N` consecutive profiles into 4 summary rows — **mean, standard deviation,
  minimum, maximum** — with `N` recorded (Ch. 10).

### 2.3 In this repo

`parser.py` turns each data row (raw) or each 4-row stat group into a
`ChannelFrame`:

- `gate_depths_mm` — the gate positions (the file's first data line);
- `values` — the per-gate row;
- `tbd_ms` — the TBD column;
- `block` / `channel` — from the trailing columns;
- `n_profiles` — `None` for raw rows, the profile count `N` for stat groups
  (with `std_dev`, `min_val`, `max_val` filled).

A single-sensor recording is the degenerate multiplexer case: one channel, and
usually one block spanning the whole file.

---

## 3. Multiplexed recordings — channels, sequences, blocks

### 3.1 Why multiplex, and the hardware

Many experiments need several measurement points (or several beam directions
for multi-component velocity) at once. Instead of buying one velocimeter per
probe, a **multiplexer** lets several transducers share one instrument: the
instrument works through the selected probes one at a time, very quickly.
On the **DOP3010** the multiplexer is built in: up to **10 channels**, each
with its own BNC connector and its **own complete parameter set** (PRF, gates,
TGC, sound speed, … can differ per channel) (Ch. 11, 22). Channel switching is
done by relays inside the instrument (switching time ≈ 0.1–0.5 ms — the manual
quotes both numbers in different places), so the measurement itself is not
continuous while switching; the manual recommends spending at least ~100 ms per
channel per visit.

> Example from this repo's data: `data/4-sensor-velocity/200RPM.ADD` uses four
> channels (6–9) of such a multiplexer.

### 3.2 One cycle: sequence → block

The acquisition loop is:

1. Select the first enabled channel and **acquire a user-defined number of
   profiles** for it (each profile per the channel's own parameters);
2. switch to the next enabled channel and acquire its profiles;
3. repeat until every selected channel has been measured once.

One complete pass over all selected channels is a **sequence** (also the unit
the software calls a *round*). When the last channel is done, the instrument
either closes the recording, **closes the current block**, or rolls over —
and a new sequence starts again at the first channel (Ch. 11).

The manual defines a **block** as a group of contiguous profiles (in time),
and — in multiplexer mode — **one block corresponds to one complete sequence**
(one pass over the selected channels, containing every channel's profiles for
that round). So a multiplexed raw recording looks like:

```
block 1:  channel 6 → N profiles (rows)
          channel 7 → N profiles
          channel 8 → N profiles
          channel 9 → N profiles
block 2:  channel 6 → N profiles
          …
```

This is exactly the repeated `Gate Depth [mm]` structure of a rolling `.ADD`
file: each `Gate Depth` section is one (block, channel) group holding
`N` rows (profiles) (Ch. 10, 11).

### 3.3 The three trailing columns — TBD, No block, Channel

Because rows of different channels are interleaved, every data row of a
multiplexed `.ADD` ends with:

- **TBD [ms]** — time stamp of the profile (raw format: cumulative from the
  recording start; stat format: constant per block);
- **No block** — which block (sequence round) the row belongs to;
- **Channel** — which probe/channel produced it.

Within one (block, channel) group the profiles are consecutive in time; when
the instrument switches channel there is a small gap (the switching time plus
any per-channel calibration), visible as a jump in the TBD values.

### 3.4 Statistical multiplexed files

In a `*_Stat.ADD`, each (block, channel) group is compressed to four rows —
mean, standard deviation, minimum, maximum over its `N` profiles — and the
time column is replaced by statistics of the *time between profiles* instead of
a cumulative stamp (Ch. 10).

### 3.5 Example and repo mapping

`data/4-sensor-velocity/200RPM.ADD` (velocity, 4 sensors):

| Aspect | Value |
|--------|-------|
| Channels | 6, 7, 8, 9 |
| Gates per channel | 55 (depths 20.00 → 79.13 mm) |
| Profiles per channel per block | 4 |
| Blocks | 100 (each block = one full pass over 4 channels) |
| Frames | 1,600 raw rows = 100 blocks × 4 channels × 4 profiles |
| Row cadence | ~25 ms between a channel's consecutive profiles (4 profiles ≈ 76 ms of acquisition); the next channel starts ~112 ms later (~36 ms switch/gap) |
| Recording | ~44.5 s |

`parser.py` reads each `Gate Depth` section as frames grouped by
`(block, channel)`; `ExtractedData.by_block()` therefore returns one list per
sequence round and `by_channel()` one list per probe. The stat twin of the same
recording (`200RPM_Stat.ADD`) yields 100 blocks × 4 channels = 400 frames with
`n_profiles = 4`.

---

## 4. Glossary (quick reference)

| Term | Short definition | Manual | This repo |
|------|------------------|--------|-----------|
| Emitting frequency `f_e` | Carrier frequency of the ultrasonic burst (0.5–10 MHz range) | Ch. 8 | — (metadata in `.BDD`) |
| Burst / emission | One transmitted pulse: N cycles of `f_e` | Ch. 1, 8, 21 | — |
| PRF | Pulse repetition frequency = 1 / period between emissions | Ch. 1, 8 | — (`.BDD`) |
| Gate | One depth sample volume along the beam | Ch. 8, 14 | one column of `values` |
| Gate depth / resolution | Gate position; spacing between gate centres | Ch. 5, 8 | `gate_depths_mm` |
| Profile | One value per gate at one time (velocity or echo) | Ch. 5, 10 | one data row / stat group |
| Emissions per profile | Emissions combined per velocity profile | Ch. 8 | `n_profiles` only for stat groups |
| Time between profiles | Refresh period of a channel | Ch. 8 | from `tbd_ms` diffs |
| TBD [ms] | Time-stamp column; "time between data" (never expanded in the manual) | Ch. 10 | `tbd_ms` |
| Block | Group of contiguous profiles; = one full multiplexer sequence in multiplexed mode | Ch. 10, 11 | `block` |
| Channel | One probe (own parameter set on the multiplexer) | Ch. 11, 22 | `channel` |
| Doppler angle θ | Angle between beam axis and flow; only the along-beam component is measured | Ch. 1, 8 | — |

---

## 5. Known caveats in the source material

- The manual body often writes "DOP3000" even for features that belong to the
  DOP3010's built-in multiplexer (Ch. 11 is the multiplexer chapter; the 10
  channels are specified in Ch. 22). Check which device model you actually have.
- Multiplexer switching time is quoted as ~0.5 ms in one section and 0.1 ms in
  the specification table; treat it as "sub-millisecond".
- TBD is never expanded in the manual; the cumulative-vs-per-block behaviour is
  inferred from real files (see `src/udv_echo_process/parser.py`).
- These notes are distilled from an unproofread machine extraction of the
  manual; prose-level concepts are reliable, but double-check numeric
  specifications (Ch. 21/22 tables) against the manual or `.BDD` metadata
  before relying on them.
