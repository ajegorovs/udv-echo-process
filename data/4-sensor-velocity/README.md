# The four-sensor velocity recordings — a 2x2 orthogonal mounting (2026-07-23)

Four-channel UDV velocity recordings of the mixer rig: **two orthogonal pairs of probes** (hence
"2x2") looking into the same stirred vessel. `200RPM.BDD` and `200RPM_v2.BDD` are two takes of the
same run; the `.ADD` files are the instrument's own text exports of each take (raw, and the
`_Stat` statistics twin).

| file | bytes | sha256 |
|---|---:|---|
| `200RPM.BDD` | 150184 | `643d5d56b173c00c20d7691f464d3dc6a1cb43b5ced72f7ce1d2f8ed20537b52` |
| `200RPM_v2.BDD` | 150184 | `fda67014f9bcc411be68679eecd5e0a3c5ee6d919581edee09dec5d2913025b2` |
| `200RPM.ADD` | 899136 | `9ee3a564fb03389be4e808f3fea7a4a6da4a6558c4a481363792dbd578a048f7` |
| `200RPM_Stat.ADD` | 822291 | `fd128e623f16ed8111fc775e5e0e9b07b4df155036f0edf47f20a8d763e5bf71` |
| `200RPM_v2.ADD` | 899609 | `e9eb46b5051d811bf495151562c92230d6c66c34641c9ff9a16a42e497a15e37` |
| `200RPM_v2_Stat.ADD` | 822922 | `458dfb8485514266778b4d2bc0ec34dccc07ece1c13180aeeff70c4f2204dff7` |

The four decoded device channels are **6, 7, 8 and 9** in both takes (`sequential` acquisition,
400 profiles × 55 gates each).

## The rig, as stated (not inferred)

`comments (1).txt` is the operator's own note and is the authority:

> 4 sensors x2 x-dir, x2 y-dir. 10 mm centers apart. elevation 2 mm + sensor radius (different
> mounts). position and channels see photo. 4 Mhz.

The vessel, the pill and the water are the *mixer rig* and are described once, in
[`../mixer-sensitivity-analysis/README.md`](../mixer-sensitivity-analysis/README.md) § *The rig, as
the operator states it* — a magnetic pill mixer stirring water in a rectangular vessel, square base
about 100 × 100 mm, 50 mm tall. That description is not repeated here.

**Flow (operator, 2026-10-16):** a **vortex combined with a toroid** — an azimuthal swirl about the
vertical axis plus a toroidal (poloidal) recirculation — in a vessel whose square plan is what
makes the two mounts geometrically equivalent. Corner eddies and any difference between the two
mounts are the obvious ways that equivalence is broken.

## Sensor positions and the channel map

Operator-stated geometry (2026-10-16), which replaces the guesswork this section first carried:

- Vessel **100 mm square**; sensors **8 mm diameter, 70 mm long**.
- **Two mounts, orthogonal** to each other. Within a mount both beams are **parallel and perpendicular
  to that mount's wall**, offset **laterally from the vessel centre line** — **inner 20 mm, outer
  30 mm** — so the pair's centres are 10 mm apart and their 8 mm faces sit 2 mm apart. The pair is
  **staggered to one side of the centre line**, not symmetric about it.
- **Channels 6 and 7 are one mount (6 outer at 30 mm, 7 inner at 20 mm); channels 8 and 9 are the
  other, the same offsets replicated by a 90° rotation** — a rotation, not a mirror, so both mounts
  carry their pair the same way round.
- **Positioning height is not a factor here** (operator): the earlier elevation note is not an open
  question for this comparison, and vertical placement is left out of it.
- The **photo is the authority** for which channel sits where ("position and channels see photo"): the
  committed frames in this folder show tape labels reading `6,7` beside one pair and `8,9` beside the
  other. Which mount faces which vessel wall is still unrecorded — and by the 90° equivalence it does
  not change the comparison, only the drawing.
- All four channels in both takes share the **same gate grid**: 55 gates from **20.002 → 79.132 mm**
  at 1.095 mm spacing, so the same gate index is the same depth from each probe face.
- **Radius mapping, derived from that geometry.** A beam at lateral offset `b` runs across the vessel,
  so a point at depth `d` from the probe face sits at radius `r = sqrt((50 − d)² + b²)` from the
  vessel axis. The outer beam (b = 30 mm) therefore sweeps **58.31 mm at the wall → 30 mm where it
  crosses the centre plane**, and the inner beam (b = 20 mm) **53.85 mm → 20 mm**. The crossing is at
  d = 50 mm, i.e. **gate 27 (49.57 mm)** — and that is where the measured along-beam mean is largest,
  a first sign that the radial structure is real.
- Because the mapping is the same for both beams of a pair, **6's depth axis corresponds to 8's gate
  for gate** (and 7's to 9's): the depth dimension can be compared with no time alignment at all.

## The symmetry the pair comparison will test

Under a flow invariant under 90° rotation — square plan, pill driven on the vessel axis — the two
mounts sample the **same radius profile**: 6 and 8 both run at a 30 mm lateral offset
(58.31 → 30 mm), 7 and 9 both at 20 mm (53.85 → 20 mm). So the expectation (operator, 2026-10-16) is
that **6 and 8 see roughly the same signal, and 7 and 9 likewise**, while within a mount the two
probes sample different radii (30 vs 20 mm) and are *not* expected to match.

**Measured in the depth dimension, where no time alignment is needed** — per-gate mean and RMS profiles
over all 400 profiles (`200RPM.BDD`; `200RPM_v2.BDD` agrees):

| pair | expected | mean-profile r | level ratio | RMS-profile r |
|---|---|---|---|---|
| 6 vs 8 (outer, 30 mm) | equal | +0.94 | **1.31** | +0.56 |
| 7 vs 9 (inner, 20 mm) | equal | +0.95 | **1.24** | +0.59 |
| 6 vs 7 (30 vs 20, one mount) | different | +0.86 | 0.94 | +0.40 |
| 8 vs 9 (30 vs 20, one mount) | different | +0.94 | 0.89 | +0.51 |

The *shapes* do line up within each expected-equal pair, but the **level carries a mount-dependent
factor of 1.2–1.3 — larger than the inner/outer difference the geometry would predict**. The dominant
variation across these four channels is mount-to-mount, not radius, and that factor has to be
accounted for before either pair is called "the same signal": probe sensitivity, coupling or a
mount-dependent axial offset are the plausible causes, and the flow symmetry does not explain it.

Along the beam the mean also changes sign — about **−10 mm/s at the near-wall gates** (20.00 mm depth)
rising to a peak at the centre-plane crossing (**gate 27**: +36.8, +49.0, +29.8, +37.9 mm/s for
6, 7, 8, 9), the shape an azimuthal swirl plus a radial recirculation would produce. The sign
convention of a rotated mount is not decoded, so a raw overlay's *sign* is not evidence by itself;
the two pairs do correlate positively, which is consistent with a shared convention but not proof.

## What the files actually do — and why it decides how a pair may be compared

Measured on both takes (2026-10-16):

- Acquisition is **multiplexed, not simultaneous**: one channel is visited at a time, and a visit
  holds **4 profiles at ~25.4 ms spacing** followed by a **~372 ms gap**. A channel's visit recurs
  every **~448 ms**, giving each channel 400 profiles over ~44.2 s at a mean interval of ~112 ms.
  Both takes show exactly **99 such gaps per channel at the same sample indices**, and after each
  channel's own start is removed the four grids coincide to within **6.5 ms**.
- The four channels' visits are **offset 112 ms apart in the order 6 → 7 → 8 → 9**. So **no two
  channels are ever sampled at the same instant**: comparing 6 with 8 at the same index compares
  instants **~224 ms apart** (half a cycle), and 6 with 7 about 112 ms apart. At the 200 RPM the
  file name claims (300 ms per revolution) neither offset is one flow instant.
- **Consequence for the comparison.** Level, distribution, mean/RMS gate profiles, spectra and
  phase-averaged statistics are all comparable. A **sample-by-sample overlay is not** — it compares
  different instants — and the 448 ms visit cycle is not a multiple of the 300 ms revolution, so a
  phase-averaged comparison has to state the window it averages over. Plotting each channel on its
  **own recorded timestamps** is honest and needs no resampling; interpolating or shifting one
  channel onto another's samples *is* resampling, and that is the open
  [alignment decision](../../docs/agenda.md), not something this dataset settles.
- **Level and spread per channel** (depth-averaged mean / std in mm/s): `27.7 / 22.8`, `29.4 / 30.6`,
  `21.2 / 18.9`, `23.8 / 24.2` for channels 6 / 7 / 8 / 9 in `200RPM.BDD` (`200RPM_v2.BDD` is close:
  27.4, 30.6, 22.1, 26.1). These need no time alignment at all; what their pair structure means is in
  § *The symmetry the pair comparison will test*.

## The photos

`20260723_180510.jpg`, `20260723_180611.jpg`, `20260723_180641.jpg`, `20260723_181113.jpg`,
`20260723_181349.jpg` are frames of the rig as mounted, and `settings.png` is the instrument's
settings screen. The frames carry the `6,7` and `8,9` tape labels that define the channel map. A
frame dated 2026-07-23 is the only date evidence for the sitting, so the recording date is
**inferred** from it, not decoded from the file.

## Open questions

- **What causes the 1.2–1.3 mount-to-mount level factor** — probe sensitivity/coupling, a
  mount-dependent axial offset, or a flow asymmetry the 90° argument misses.
- Whether the two mounts' channels share a sign convention for the rotated axes (not decoded).
- Which mount faces which vessel wall — drawing only; the comparison does not depend on it.
- The pill's real speed and its stability across the 44 s; the file name is the only claim of 200 RPM.
- The 90° equivalence assumes a square plan; the vessel's plan tolerance is unrecorded.
- How the ~224 ms sampling offset between the pairs of a comparison should read on screen.
