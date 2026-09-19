# The mixer sensitivity analysis — the sparse point set (2026-09-16)

Forty `.BDD` recordings and nothing else: one **reference point** and five *sparse* sweeps taken
around it. They were **picked roughly and measured by hand**, one point at a time, and **none of them
has been analysed** — the manual procedure was tedious enough that measurement automation became the
route instead (`src/udv_echo_process/acquire/`, `docs/dop3000/`). Nothing here is a result, and the
point set claims no effect: it is the raw material a first sparse parameter matrix is built from,
with the settings each recording carried decoded from the file itself.

## The rig, as the operator states it

- a **magnetic pill mixer** stirring **water** in a **rectangular vessel** — square base,
  **10 x 10 cm**, **5 cm** tall;
- the measurement is **~2.5 cm off centre horizontally, perpendicular to the wall, at a height of
  ~2.5 cm** (i.e. at half the water depth);
- the flow is **circular**, with **eddies in the corners**.

What that geometry looks like in the recorded numbers, read off the files: the window runs **10.16 →
100.81 mm** of `c` = 1480 m/s path from the transducer face — from roughly 1 cm in front of the probe
out to ~10 cm, the vessel's own width. *(That sentence is our reading of the numbers; the rig
description above is the operator's and is the authority.)*

## The reference point, and the base state

The base state every sweep holds is the run's own note of 2026-09-16: *sensitivity medium, emitting
power medium, TCG 20, emissions/profile 20, resolution 1.85 mm, gates 50, PRF 600, burst length 10*.
`4MHz/0500RPM/001/prf/600.BDD` is that state recorded, and its header confirms every value the reader
decodes (`docs/dop3000/parameter-sweep-matrix.md` §8). **`Emissions/profile` is the one base-state
value no file decodes** — it is word 14, the decode §9 of that document lists as missing — but the
*recorded time base still measures it*: the median profile interval divided by `T_prf` is **37.3 on
every one of the forty points** (22.4 ms at 600 µs, 15.0 ms at 400 µs, 29.8 ms at 800 µs), which is
C5's `16 + N_PRF` with roughly 0.6–1.0 ms of transit overhead — i.e. **N_PRF = 20**, the note's own
value, recovered without the word. A recording at a second `N_PRF` would separate the application's
constant from that overhead and make the axis readable from the file alone. The operator reads the
parameter as **time averaging** and may set it to the smallest the instrument allows (~8) for the
sweep — undecided; it is recorded here because it moves the stored step (to ~15 ms at 600 µs, a 1.5x
faster profile rate), not because it blocks anything.

## The 40 points, decoded from the files

Every recording shares `f_e` = 4 MHz, `c` = 1480 m/s, `sensitivity` *medium*, TCG *uniform* → 40 dB,
and a window that begins at 10.16 mm; only the columns below move. `T_prf` is the PRF period the file
states (the axis' own value), `res` the **decoded** resolution in mm, `window` the gate 1 → last-gate
depth, and `V_max` the unaliased velocity limit the file declares.

| axis | point (`<axis>/<name>.BDD`) | profiles x gates | `T_prf` | burst | `res` | window (mm) | `V_max` (mm/s) | TCG start (dB) | power / sens |
|---|---|---|---|---|---|---|---|---|---|
| `prf` | `400` | 545 x 50 | 400 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±231.21 | 19.9 | medium / medium |
| `prf` | `500` | 543 x 50 | 500 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±184.97 | 19.9 | medium / medium |
| `prf` | `600` | 669 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `prf` | `700` | 557 x 50 | 700 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±132.12 | 19.9 | medium / medium |
| `prf` | `800` | 539 x 50 | 800 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±115.6 | 19.9 | medium / medium |
| `burst_len` | `12` | 521 x 50 | 600 µs | 12 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `14` | 585 x 50 | 600 µs | 14 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `16` | 497 x 50 | 600 µs | 16 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `18` | 524 x 50 | 600 µs | 18 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `2` | 529 x 50 | 600 µs | 2 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `20` | 518 x 50 | 600 µs | 20 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `24` | 545 x 50 | 600 µs | 24 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `28` | 510 x 50 | 600 µs | 28 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `32` | 520 x 50 | 600 µs | 32 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `4` | 536 x 50 | 600 µs | 4 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `6` | 512 x 50 | 600 µs | 6 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `burst_len` | `8` | 517 x 50 | 600 µs | 8 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `res` | `0-2` | 540 x 365 | 600 µs | 10 | 0.247 mm | 10.16 → 99.95 | ±154.14 | 19.9 | medium / medium |
| `res` | `0-4` | 501 x 240 | 600 µs | 10 | 0.37 mm | 10.16 → 98.59 | ±154.14 | 19.9 | medium / medium |
| `res` | `0-6` | 548 x 145 | 600 µs | 10 | 0.617 mm | 10.16 → 98.96 | ±154.14 | 19.9 | medium / medium |
| `res` | `0-8` | 514 x 120 | 600 µs | 10 | 0.74 mm | 10.16 → 98.22 | ±154.14 | 19.9 | medium / medium |
| `res` | `1-0` | 502 x 90 | 600 µs | 10 | 0.987 mm | 10.16 → 97.98 | ±154.14 | 19.9 | medium / medium |
| `res` | `1-2` | 521 x 74 | 600 µs | 10 | 1.233 mm | 10.16 → 100.2 | ±154.14 | 19.9 | medium / medium |
| `res` | `1-4` | 565 x 65 | 600 µs | 10 | 1.357 mm | 10.16 → 96.99 | ±154.14 | 19.9 | medium / medium |
| `res` | `1-6` | 553 x 55 | 600 µs | 10 | 1.603 mm | 10.16 → 96.74 | ±154.14 | 19.9 | medium / medium |
| `res` | `1-8` | 517 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | medium / medium |
| `res` | `2-0` | 524 x 45 | 600 µs | 10 | 1.973 mm | 10.16 → 96.99 | ±154.14 | 19.9 | medium / medium |
| `res` | `2-2` | 515 x 40 | 600 µs | 10 | 2.22 mm | 10.16 → 96.74 | ±154.14 | 19.9 | medium / medium |
| `res` | `2-5` | 519 x 37 | 600 µs | 10 | 2.467 mm | 10.16 → 98.96 | ±154.14 | 19.9 | medium / medium |
| `res` | `3-0` | 517 x 31 | 600 µs | 10 | 2.96 mm | 10.16 → 98.96 | ±154.14 | 19.9 | medium / medium |
| `tgc` | `0` | 516 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 0.2 | medium / medium |
| `tgc` | `10` | 522 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 9.9 | medium / medium |
| `tgc` | `15` | 494 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 14.9 | medium / medium |
| `tgc` | `25` | 614 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 24.9 | medium / medium |
| `tgc` | `30` | 517 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 30 | medium / medium |
| `tgc` | `35` | 418 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 35 | medium / medium |
| `tgc` | `40` | 492 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 40 | medium / medium |
| `tgc` | `5` | 496 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 4.9 | medium / medium |
| `em_pow` | `high` | 520 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | high / medium |
| `em_pow` | `low` | 556 x 50 | 600 µs | 10 | 1.85 mm | 10.16 → 100.81 | ±154.14 | 19.9 | low / medium |

## What the set says about itself (measured, not analysed)

- **Every file is the base state except its own axis.** That is what makes this a designed sparse
  matrix rather than forty unrelated recordings, and it is the property any re-derivation can lean on.
- **The `res` axis holds the ~100 mm window and the gate count follows the resolution** — which is the
  operator's own account of that folder: *"res folder is where I change gate resolution, and tweak
  number of gates so that last gate is at ~ 100 mm depth"*. 365 gates at
  0.247 mm down to 31 at 2.96 mm, so it is a resolution ladder across the same vessel span rather
  than a window sweep.
- **The `res` folder names are the instrument's rung labels, not millimetres.** `1-8` decodes as
  1.85 mm, `2-0` as 1.97 mm, `0-2` as 0.247 mm: label and decoded value are not the same number, and
  the base state's 1.85 mm sits on rung `1-8`. (C11 in the matrix document makes the ladder
  `c`-dependent, which is why the two disagree.)
- **The `prf` axis moves `V_max` exactly as the manual's C2 requires** — 231.21 / 184.97 / 154.14 /
  132.12 / 115.60 mm/s at 400 / 500 / 600 / 700 / 800 µs. That is a check on the axis, not a finding
  about the flow.
- **`burst_len` (2…32) and `tgc` (0…40 dB) hold the window exactly**; `em_pow` has two points (low,
  high) against the base's *medium*; the recording lengths differ (418–669 profiles), so the
  reference point is also the longest recording in the set.

## Provenance

Copied **byte for byte** on 2026-09-19 from the operator's own sweep tree
(`experiment_data/mixer/sensitivity-analysis/4MHz/0500RPM/001`, recorded 2026-09-16), which remains
the source of truth; each file's SHA-256 is below, so a copy can be checked rather than trusted. Only
the `.BDD` points were taken — the `v1` / `v2` / `v3` folders are 33 GB of camera frames and the
`_test*` folders are camera test frames, neither of which is instrument data.

```
# path (relative to this directory)                                        sha256
prf/400.BDD              2e1a0316b2be4c134512f7d15794d15b926002018a50f2e02cf49f5ed334718e
prf/500.BDD              ec836da40022c5d895cd200681538eb6be36460fb8d0d328a6abb54a5e930c8a
prf/600.BDD              cd47a0dded66bb879acc8f177fe263ccf2fcc8b665d23468c4c185a47b59a8de
prf/700.BDD              368c29e8d55e0ed521e403d4d6d673784c3c763ead6668f4a499d51bfc5aa9ba
prf/800.BDD              29308430cb2a7704771210c7d14043d3705640d854df68ffb5f7a6bbd844f5f9
burst_len/12.BDD         8b3f7b91932b65a1c82da122db3bb2160f286d7aa8e5f0fa7b35eb108acf6c56
burst_len/14.BDD         7644a56d24b2c13b8d1b96abd53c672a3e33adea7acaa21ee3113895877b2b09
burst_len/16.BDD         86ff4f89738f35d458d6a4176e0f4a87880f46722eeda520b9c1fbcb28f2f493
burst_len/18.BDD         e1598263277fa58b4802dd3779ddb29ee6dc034e0cb0853083327ddb050e85dc
burst_len/2.BDD          bc5804498dd734dbe4acc72bcd2a3028b0581a3c88bc2a424bc0e7a97e47ef5c
burst_len/20.BDD         a7aa7814f5832d34a33538ad4745718bacca5c0af0d5ab8979094a8e23b48abd
burst_len/24.BDD         9786ebfaf5fea60108552af761e41d7eb9480ed4453580a2e476341451d214b6
burst_len/28.BDD         cc8156ac2287ac20de9c2e3850885e5cca020c87851e9cfb05c72ff03dfdb6aa
burst_len/32.BDD         a29e78dc6dcfc890d49e7c14d8f525675a67c19ae8f7b5f7f0aa68b66bdcf2fe
burst_len/4.BDD          dd38dc77ed3d442852e48a8d18e1019e95ce48d9008d6ed47c6d9534ac9b9482
burst_len/6.BDD          d493b9cdea2d818323969ef4455a5ef387eb715ecab979180bf61674ff504a32
burst_len/8.BDD          48e5b680a9b78da74038b63e90ed79bc950ae58a88d683544517516d0097f170
res/0-2.BDD              85dc6e5152914c33f336571303a29ba76d852768aa7fd08a0abc46702a2a28fd
res/0-4.BDD              923fa2ea5cdb75d0479c84d071d6cfb55529b36559f23e5e183a1c9f83c3d12d
res/0-6.BDD              ada06d27f56acd5436ce23e77aa7525f60e422d18294fe3e19b68348eaef0e4d
res/0-8.BDD              5877a45686549e11b51dfb9315169b2209e7dbc54f66b463317629822d803aee
res/1-0.BDD              c8afe466119a1b1e0bcca069fac0b1e1ca418d6e5f4aabf36e76a3c5a622497d
res/1-2.BDD              de9841e6a7c46763f2ba899303cf5351e2d404031b7a066b167da3113d9a27ae
res/1-4.BDD              0c508f7067a1b04cffad48ead21e825d1108c50c6f64c7cfbdf8849b1fbc9796
res/1-6.BDD              10455df3aaffbae3916e95e97cc739a1017e9ff203edca57e7408c9e716d9396
res/1-8.BDD              92ef87e3df57b443d37d62ed6cb84a99a5a4173c3b3c646e1a4d6c50b0fb67de
res/2-0.BDD              b1e7063443dbc8dd27f8d17fa7d578e699d50f2bc5b21b4acc5fffce62525d46
res/2-2.BDD              94d88329c3e7b8e89c334c3102188193999a85a184c33519c040684c8bf8c211
res/2-5.BDD              00cb6e09c34a0cce4fad706494b2bb0194e36a572c1354150f97426136384964
res/3-0.BDD              46bbe2a82e6af90e6c1c47391029ab754c0dbef958dcfd00f3ccbd9e14349291
tgc/0.BDD                4f936ff8751593313a621d0cbf4ea322ae7fb5e23e12ea7d109ce683a613b72e
tgc/10.BDD               d15a4ce74bae1640ff017dcec17e497c4b7b7270928ddb9f582e32bf2d1f3f81
tgc/15.BDD               05c6f63a67b087be9c56d547cb748f5fbc43cf7cedacf44f768ce6e0ea3abc9f
tgc/25.BDD               c90c19e57f565253de44a029f923eb703138e0f01db3223d14205ef949376c1e
tgc/30.BDD               083f2df703f787a275eb544df8b7cf21d2315c4bca2ccfc8fba8ce9ecbd5324e
tgc/35.BDD               dbc6d7d4a5300e86d4e64f6c76236da90bd934c25d3f0e28db577d0c464a4be1
tgc/40.BDD               07c90296fdf8572599be1aedfbf715886fd952af52e35f77cb1764a3ca49dd64
tgc/5.BDD                64f571f427fe38c292df962f50744dbd6293690304b46ccb5ebe355dd0f9272c
em_pow/high.BDD          9e02546ba83b86842ddeb7bb9516b4a21d5eff9412c57c6f827cff655c437b5d
em_pow/low.BDD           40b1de33bbaee4e3654d9ab00f20ef740e16b517efc8e40bec56f6d340df6144
```
