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

- Two mounts, **orthogonal** to each other; within a mount the two probes stand **10 mm** apart
  centre-to-centre, so each mount holds one **inner** and one **outer** probe.
- **Channels 6 and 7 are one mount (6 outer, 7 inner); channels 8 and 9 are the other (8 outer,
  9 inner).** Operator-stated, 2026-10-16.
- The **photo is the authority** for the mapping ("position and channels see photo"): the committed
  frames in this folder show white tape labels reading `6,7` beside the vertical pair and `8,9`
  beside the horizontal pair. Measured positions rest on those photos plus the note above; nothing
  else in the repository places these four channels in space.
- **The two mounts are not stated to be identical.** "elevation 2 mm + sensor radius (different
  mounts)" gives an elevation rule, not a shared height, so the two pairs' beam axes may sit at
  different heights as well as at right angles.
- All four channels in both takes share the **same gate grid**: 55 gates from **20.002 → 79.132 mm**
  at 1.095 mm spacing, so the same gate index is the same depth *as measured from each probe face*.

## The symmetry the pair comparison will test

Because the mounting is 90°-rotationally symmetric, the expectation (operator, 2026-10-16) is that
the **outer** probes **6 and 8** see roughly the same signal, and the **inner** probes **7 and 9**
likewise. The within-mount pairs (6/7 and 8/9) sample different radii, so they are *not* expected to
match. This is a stated expectation to test, not a measured result.

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
- **First descriptive numbers** (index-wise, therefore *not* the symmetry test): depth-averaged
  mean / std in mm/s are `27.7 / 22.8`, `29.4 / 30.6`, `21.2 / 18.9`, `23.8 / 24.2` for channels
  6 / 7 / 8 / 9 in `200RPM.BDD` (`200RPM_v2.BDD` is close: 27.4, 30.6, 22.1, 26.1). The 6/7 mount
  reads ~20% higher in level than the 8/9 mount, in both takes. That difference has to be
  explained — mount height, beam direction, mount-to-flow orientation — before either pair is
  called "the same signal". *(The note does not say which mount is the x-direction one, so the
  mounts are named by their channels, not by an axis.)*

## The photos

`20260723_180510.jpg`, `20260723_180611.jpg`, `20260723_180641.jpg`, `20260723_181113.jpg`,
`20260723_181349.jpg` are frames of the rig as mounted, and `settings.png` is the instrument's
settings screen. The frames carry the `6,7` and `8,9` tape labels that define the channel map. A
frame dated 2026-07-23 is the only date evidence for the sitting, so the recording date is
**inferred** from it, not decoded from the file.

## Open questions

- The two mounts' true elevations and beam angles; "elevation 2 mm + sensor radius" is not enough to
  place either beam in space.
- Which mount faces which vessel wall, and at what angle to the pill's rotation.
- The pill's real speed and its stability across the 44 s.
- The 90° equivalence assumes a square plan; the vessel's plan tolerance is unrecorded.
- Whether the ~224 ms sampling offset between the pairs has to be handled explicitly in the intended
  visual comparison, and how that should read on screen.
