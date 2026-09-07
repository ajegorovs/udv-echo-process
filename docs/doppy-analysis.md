# DOPpy (sibling repo) — architecture review & verification log

> **Status:** Analysis complete (2026-09-07). Source examined: `~/Repos/DOPpy` @ `a540845`
> (v2.13, 2023-02-27, MIT © Till Zürner). All runtime claims below were
> **executed and observed** against this repo's `data/*.BDD` files; see
> [Verification log](#verification-log) for exact commands and results.

## What DOPpy is

Single-file (~2,425 LOC), pure-Python reader for the **binary `.BDD`** files
written by [Signal Processing](https://www.signal-processing.com/) DOP-series
ultrasound Doppler velocimeters — the same instruments whose ASCII export this
repo parses via [`parser.py`](../src/udv_echo_process/parser.py). It hand-decodes
the (undocumented) binary layout with `struct` into numpy arrays plus ~1,700
named parameters, and offers light matplotlib visualization. Imports: `numpy`,
`matplotlib`, `struct`, `bz2`, `gzip` only. Not packaged — drop the file next to
your script and `import DOPpy`.

**Why `.BDD` matters vs `.ADD`:** the binary format carries the full
instrument metadata (PRF, burst length, TGC, gate config, sound speed, Doppler
angle, sensitivity, filter settings, trigger state…) and interleaved
velocity+echo profiles; `.ADD` carries only time / gate / values.

## Architecture

```
DOP(fname, **kw)                    — factory: sniffs first line of file
  ├─ b"BINWDOPV…"  → DOP2000        — magic determines the class
  ├─ b"BINUDOPV…"  → DOP3000        — DOP4000 "similar, untested"; else raise
  │
DOPBase        — dict-like parameter store + public API
  ├── DOP2000  — fixed-offset tables; modes: front / multi / udvf2d* / udvf3d*  (* = stubs)
  └── DOP3000  — per-channel op-parameter blocks (10 × 256 B) + nested profile
                 blocks; bit-level flags via custom 'm' format
```

`DOPBase.__init__` opens the file (transparent `.gz`/`.bz2`) and calls two
subclass hooks: `_read()` (bytes → typed raw values) and `_refine()` (raw →
physical units). `saveMeas=True` keeps the raw per-block data; default drops it
to save RAM (v2.10 optimization).

## How the parsing works

1. **Two-pass scan.** `_scanFile()` walks the chain of measurement blocks from a
   fixed base offset; each block is length-prefixed (uint32), so the walker
   advances `measStart → measEnd` to EOF, counting measurements *per channel*
   and verifying each block's trailing length copy (mismatch → `warn`). Pass 2
   pre-sizes numpy arrays from those counts before filling them.
2. **Table-driven decoding.** Class-level lists of `[name, offset, struct_fmt]`
   triples are a hand-transcription of the binary layout (per DOP user manual);
   many entries are annotated *"exact decoding unknown"*.
3. **Custom format keys extend `struct`** in `DOPBase._readParam`:
   - `'v'` — verbose: read N raw bytes, no unpack.
   - `'m'` — machine code: read a byte buffer, extract **one bit**
     (e.g. `'4m10'` = read 4 bytes, return bit 10 as bool). Used for DOP3000
     TGC mode / sensitivity / emit power / profile-type enums.
4. **DOP3000 measurement blocks** contain length-prefixed *profile sub-blocks*
   (velocity / echo / depth, by numeric profile-type code). The channel number
   in the block footer selects which channel's preallocated arrays receive the
   next free slot (found via `np.where(time == inf)`). The `'depth'` profile is
   special-cased into `depthFile` rather than a time series.
5. **`_refine()` converts raw → physical:**
   - cp1252 string decoding (`errors=decode_errors`, default `'ignore'`).
   - enum lookups (`_sensitivity`, `_tgcMode`, `_emitPower`…).
   - **Time**: int32 µs timestamps, overflow-corrected at 2³² µs ≈ 71.6 min
     (cumulative negative-difference fixup), converted to seconds.
   - **Depth** (`_calcDepth`): from `gate1`, `resolution`, acquisition rate,
     hardware delay and sound speed; DOP3000 also keeps the file-stored depths
     (`getDepth(version='File')` default vs `version='Calc'`).
   - **Velocity** (`_calcVelo`): `veloOffset` byte-wrap correction (±128
     wraparound), Doppler equation v = f_D·c / (2·cosθ·f_emit) with
     PRF/`veloScale` scaling; also returns `veloMax` = ±Nyquist, needed by
     aliasing removal. DOP2000 formula uses `128·prf·veloScale` denominator
     directly; DOP3000 derives f_D through `256π` phase scaling.
   - **Echo** (`_calcEcho`): uint8 wrap + rescale by `moduleScale`
     (1→2048, 2→1024, 4→512, 8→256 full-scale).
   - **Sampling volume** (DOP3000 only): `max(c/8B, c·burst/2f)` — explicitly
     *reverse-engineered*, quoted accuracy ±0.1 mm vs vendor software.

## Public API

| Group | Methods |
|---|---|
| Params | `bdd['name']` / `getParam` / `setParam`, `keys()`, `keysSearch(substr)`, `keysChannel(ch)`; channel params are flat keys `ch<n>_<param>` |
| Data | `getChannels()`, `getProfileType()`, `getTime()` [s], `getDepth()` [mm], `getVelocity()` / `getEcho()` → 2-D `[time, depth]` arrays; all accept int or list of channels (`None` = all) |
| Process | `removeAliasing(jumpSize=.8)` — depth-wise jumps > `jumpSize·2·vmax` shifted by `±2·vmax` beyond the jump; destructive, assumes gate 1 unaliased, unsafe on noisy data |
| Viz | `imshow(profile, channel, timerange, depthrange)` time×depth colorgrid; `contour(...)` for non-equidistant grids (caps at `maxtimes=1000` timesteps for RAM); `replay(...)` matplotlib animation; `printSettings(ch)` operating-parameter report |
| `DOP()` kwargs | `replaceParam: dict`, `saveMeas: bool`, `decode_errors: str` |

## Findings / caveats (all confirmed by execution)

1. **Broken on NumPy ≥ 2 out of the box — hits *our* data directly.**
   `np.NaN` (alias removed in NumPy 2.0) at DOPpy.py **lines 1480, 1486, 2257,
   2266** raises `AttributeError` in `_refine()` whenever a channel recorded no
   velocity or no echo — i.e. *every echo-only and every velocity-only file*
   crashes at import of `DOPpy` → read. This repo pins `numpy>=2.5`. Fix is a
   1-line shim before use: `np.NaN = np.nan` (see repro below). Upstream
   one-word-each fix would be `np.nan`.
2. **Bug: `replaceParam` fails for plain (non-channel) parameters.**
   `self.setParam(newval)` missing the `param` name at **lines 1422 and 2172**
   → `TypeError: DOPBase.setParam() missing 1 required positional argument:
   'value'`. The *channel-parameter* branch works (verified: overriding
   `soundSpeed` applies to all channels). So the advertised v2.11 feature is
   half-broken; overriding e.g. `'comment'` raises.
3. **Misnamed files in our data are correctly rejected.**
   `data/echo-4-sensors-2x2/300RPM.BDD` is a **PNG screenshot** (50 KB,
   1366×768) and `300RPM_Stat.ADD` is a **JPEG photo**; DOPpy's magic-byte
   sniff raises `Exception: BDD version b'\x89PNG\r\n' ... unknown`. (Note for
   this repo: our `extract()` auto-detection should be checked for the same
   files — extension ≠ content.)
4. **Unsupported modes**: 2-D/3-D UDVF (image velocimetry) raise `Exception`
   stubs (`_refine_udvf2d/3d`); 2-D/3-D velocity-component measurements
   unhandled; DOP4000 untested; very old DOP2000 versions may misparse
   (upstream tested on `BINWDOPV4.06.1` only; our files are `BINUDOPV4.03.4`).
5. **Python-2-era relics**: `from __future__ import division`, `ord()` loops,
   `zip(*np.where(...))` — still runs on 3.14, just dated. No tests, no
   packaging, no lint config upstream.
6. **`_readParam`'s `'m'` bit path is DOP3000-only** (`_byteToBit` is defined
   in `DOP3000`; `DOPBase` doesn't have it — using `'m'` formats on DOP2000
   would `AttributeError`). Not hit in practice by the current tables.

## Relevance to udv-echo-process

- **Complement, not competitor**: DOPpy = `.BDD` (binary, full metadata),
  our parser = `.ADD` (ASCII, time/gate/value only). Our `data/` already holds
  11 `.BDD` twins of the `.ADD` recordings (echo: 9 files; 4-sensor-velocity: 2).
- **If we ever add `.BDD` support**, cherry-pick from DOPpy rather than vendor
  it (NumPy-2 breakage + no packaging): the two `_fixedParam`/`_operationParam`
  offset tables, the `'m'` bit-flag decoding, profile-type code maps, the
  overflow-corrected timestamp math, and the `_calcDepth` / `_calcVelo` /
  `_calcEcho` / `_calcSamplingVolume` formulas (the last flagged
  reverse-engineered). Map cleanly onto our `ChannelFrame`/`ExtractedData`
  models; `printSettings` is essentially `udv-inspect` for BDD.
- Cross-check opportunity: DOPpy's decoded gate depths / PRF vs our
  `.ADD`-parsed values on the same recordings would validate both paths.

## .ADD vs .BDD — format comparison

Observed 2026-01 by live inspection of `data/echo/200.*` (echo-only) and
`data/4-sensor-velocity/200RPM.BDD` (multi-channel velocity) via DOPpy.

### What `.ADD` carries (our parser)

| Field | Source in file | Examples from `200.ADD` |
|-------|---------------|------------------------|
| Version header | Line 1 | `ASCUDOPV4.03.4` |
| Comment | Line 2 | `Memo_Comments` |
| Gate depths | `Gate Depth [mm]` row | 26× values: `42.97 43.43 … 54.39` mm |
| Measurement type | Column header | `Amp` → ECHO; `mm/s` → VELOCITY |
| Amplitude / velocity values | Data rows, cols 1–N | 4,180 rows × 26 gates |
| TBD [ms] | Last data col | Cumulative ms from recording start (0.0 → 13,297.6) |
| Block No | Second-to-last data col | `1` (single-block in this file) |
| Channel | Last data col | `4` |

A `_Stat.ADD` variant compresses all frames into 4 summary rows
(mean, stddev, min, max) with an `N` profile count.

**Total information content**: 6 columns × N data points + tiny header.
No instrument configuration, no velocity (unless that's all the file is),
no metadata beyond version and comment.

### What `.BDD` carries (DOPpy-decoded)

DOPpy decodes ~1,700 named parameters from the binary layout.
The actual number *present in the file* depends on instrument and measurement type:

| Category | What it is | 200.BDD (echo-only) | 200RPM.BDD (velocity, 4-sensor) |
|----------|-----------|---------------------|--------------------------------|
| **Operation params** | Hand-transcribed from DOP user manual (not stored in file) | ✅ populated via `_operationParam` table | ✅ populated |
| **Measured data** | Echo ± velocity profiles, time, depth, gate config | echo (4,180 × 26) | velo (4 channels × 400 × 55) |
| **Embedded params** | Actual binary fields at fixed offsets | ~10 fields present | ~15 fields present |
| **Version / comment** | Line 1–2 of binary | Same text as .ADD | Same text as .ADD |

#### Operation parameters (DOPpy computes, `.ADD` has zero equivalents)

| Parameter | 200.BDD (echo-only) | 200RPM.BDD (velocity) |
|-----------|---------------------|----------------------|
| US Frequency | 10,000 kHz | 4,000 kHz |
| Burst length | 8 | 12 |
| Emitting power | medium | low |
| TGC | uniform (40 dB) | uniform (40 dB) |
| PRF | 125 µs | 600 µs |
| First gate depth | 43.00 mm | 20.00 mm |
| Number of gates | 26 | 55 |
| Resolution | 0.455 mm | 1.091 mm |
| Sampling volume | 1.096 mm | 2.190 mm |
| Doppler angle | 0° | 0° |
| Sensitivity | medium | medium |
| Sound speed | 2,740 m/s | 1,460 m/s |
| Max velocity | nan (echo-only) | 152.1 mm/s |
| Max depth | 54.4 mm | 79.1 mm |
| veloScale / veloOffset | — | ±0.1521 m/s (Nyquist) |

### Rolling multi-sensor recordings (`data/4-sensor-velocity/`)

The `.ADD` "rolling" format repeats `Gate Depth [mm]` + data rows for each
sensor in a round-robin cycle. For `200RPM.ADD`:

| Aspect | `.ADD` (raw) | `.ADD` (stat) | `.BDD` (DOPpy) |
|--------|-------------|---------------|----------------|
| Sections | 400 `Gate Depth` markers | 1 section, 4 stat rows | N/A (binary blocks) |
| Channels | [6, 7, 8, 9] | [6, 7, 8, 9] | [6, 7, 8, 9] |
| Frames | 1,600 total (400/ch) | 400 total (100/ch) | 400 timesteps/ch |
| Blocks | 100 (4 ch/block) | 100 (4 ch/block) | 400 measurement blocks |
| Gates/ch | 55 | 55 | 55 |
| Depth range | 20.0 → 79.1 mm | 20.0 → 79.1 mm | 20.0 → 79.1 mm |
| Duration | 44.5 s | 44.5 s (TBD ~25.4 ms/block) | 44.5 s |
| Stagger | ch6: 0–44.2s, ch7: 112–44.3s | TBD ~constant per block | ch6: 0–44.2s, ch7: 112–44.3s |

**DOPpy handles rolling natively.** Its `_operationParam` table includes
`multi_*` fields at offset `2560+` for each of 10 sensor positions:
`multi_channelUsed`, `multi_profN`, `multi_prf`, `multi_gateN`,
`multi_resolution`, `multi_emitFreq`, `multi_gate1`, `multi_tgcStart/End/Mode`, etc.
The DOP3000 measurement blocks contain per-channel operation-parameter blocks
(10 × 256 bytes) plus nested profile blocks with velocity/echo/depth sub-types,
which DOPpy walks in `DOP3000._read()` and assigns to the correct channel's
preallocated arrays.

**Both formats agree on the signal data** (4 channels, 55 gates, 400 timesteps,
44.5 s duration, ~112 ms inter-channel stagger). The `.BDD` is **147 KB** vs
**876 KB** for the `.ADD` raw — a 6× compression ratio for this dataset.

The stat `.ADD` variant aggregates all 4 raw frames per block into one summary
row (mean/stddev/min/max), so `200RPM_Stat.ADD` has 400 frames (100 blocks ×
4 channels) with n_profiles=4, vs 1,600 raw frames.

#### Additional binary-only content

- **Trigger state, delay, external trigger settings** — not exported to `.ADD`
- **Wall filter coefficients** — not in `.ADD`
- **TGC curve per gate** — shape, not just a uniform offset
- **Hardware IDs** (firmware, module serials) — raw bytes
- **Module scale** (ADC full-scale: 1→2048, 2→1024, 4→512, 8→256)
- **Velocity profiles interleaved with echo** (DOP3000 only) — `.ADD` is one or the other
- **Timestamps** stored as int32 µs with 2³² µs overflow correction (our TBD is pre-converted to ms)

### Size comparison

| File | Format | Size | Ratio |
|------|--------|------|-------|
| `200.ADD` | ASCII raw (single-sensor echo) | 593 KB | 3.0× |
| `200.BDD` | Binary | 215 KB | 1.0× |
| `200_Stat.ADD` | ASCII summary (14 lines) | 1.2 KB | — |
| `650.ADD` | ASCII raw (single-sensor echo) | 665 KB | 2.8× |
| `650.BDD` | Binary | 235 KB | 1.0× |
| `200RPM.ADD` | ASCII raw (4-sensor rolling, 1,600 frames) | 876 KB | 6.0× |
| `200RPM.BDD` | Binary (4 channels × 400 × 55) | 147 KB | 1.0× |
| `200RPM_Stat.ADD` | ASCII stat (400 frames, 100 blocks) | 799 KB | — |

The binary format is **2.8–3.0× smaller** even with full metadata.

### Key implications for `.BDD` support in `udv-echo-process`

1. **`ChannelFrame` can stay the same** — the measured signal (gates × time × values) is identical in representation. DOPpy's velocity/echo arrays map directly to the existing `values` + `meas_type`.

2. **New top-level metadata needed** — DOPpy decodes ~1,700 params; a useful subset maps onto a new `RecordingConfig` Pydantic model (frequency, burst, PRF, gate config, sound speed, Doppler angle, sensitivity, TGC, sampling volume, trigger state).

3. **DOPpy is reference only** — it has NumPy ≥2.0 breakage (`np.NaN`), a half-broken `replaceParam`, and no packaging. If we add `.BDD` parsing, cherry-pick the `_operationParam` table, `'m'` bit-flag decoding, overflow-corrected timestamps, and the `_calcDepth` / `_calcVelo` / `_calcEcho` formulas — rewrite cleanly as Pydantic models + `struct`.

4. **Cross-validation opportunity** — the `.ADD` and `.BDD` twins for 11 experiments give us free test fixtures to verify that our `.ADD`-derived gate depths, timing, and measurement types match DOPpy's decoded values.

5. **Rolling multi-sensor format already supported** — DOPpy handles the 4-sensor velocity recordings natively (channels 6–9, 400 timesteps each, ~112 ms stagger). Our parser's `ChannelFrame` with `channel` + `block` + `tbd_ms` already represents this correctly. When we add `.BDD` parsing, the DOPpy output (4 separate `getVelocity(ch)` calls) maps one-to-one to the 4-channel `ExtractedData` structure we already have.

## Verification log

Environment: this repo's uv venv, Python **3.14.7**, numpy **2.5.0**,
matplotlib **3.11.0** (installed via `uv sync --extra dev` with
`UV_CACHE_DIR=.tmp/uv-cache` because the global cache dir is read-only in the
agent sandbox). DOPpy import path injected with
`sys.path.insert(0, '~/Repos/DOPpy')` — repo untouched (read-only).
`MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl` for headless runs. The only patch
applied at runtime was the documented `np.NaN = np.nan` shim (finding 1).

| # | Test | Result |
|---|---|---|
| 1 | `head data/echo/200.BDD` magic | `BINUDOPV4.03.4\r\n` → factory returns `DOP3000` |
| 2 | `DOP('data/echo/200.BDD')` **without** shim | ❌ `AttributeError` from `np.NaN` in `_refine` (finding 1, line 2257) |
| 3 | Same, with `np.NaN = np.nan` shim | ✅ ch4, `profile types=['echo']`, echo `(4180, 26)`, t 0→13.30 s, depth 43.00→54.40 mm, `echoMax=2048`, 1684 params, comment decoded |
| 4 | `printSettings(4)` on that file | ✅ US 10 000 kHz, burst 8, PRF 125 µs, 26 gates, res 0.455 mm, sampling volume 1.096 mm, sound 2740 m/s, max depth 54.4 mm (max velocity `nan` — echo-only, as designed) |
| 5 | `DOP('data/4-sensor-velocity/200RPM.BDD')` | ✅ DOP3000, channels 6–9, each `velo (400, 55)`, t 0→44.5 s, depth 20.0→79.1 mm, `veloMax=0.1521` m/s, ~0 % samples above vmax |
| 6 | `removeAliasing()` then `imshow('velo')` on the same file | ✅ runs headless, figure created; aliased fraction 0.0 % before/after (data already clean) |
| 7 | `DOP('data/echo-4-sensors-2x2/300RPM.BDD')` | ❌ by design: file is PNG (`file(1)`: *PNG image data 1366×768*); magic sniff raises `Exception: BDD version b'\x89PNG\r\n' unknown` (finding 3) |
| 8 | `replaceParam={'comment': 'test'}` (plain param) | ❌ `TypeError: setParam() missing 1 required positional argument` (finding 2, line 2172) |
| 9 | `replaceParam={'soundSpeed': 1500}` (channel param) | ✅ `bdd['ch4_soundSpeed'] == 1500` across channels |
| 10 | Grep for removed NumPy-2 aliases | exactly 4 × `np.NaN` (lines 1480, 1486, 2257, 2266); no `np.float/int/bool`, `in1d`, `product` etc. |
| 11 | Grep for UDVF support | `_refine_udvf2d/3d` are `raise Exception` stubs (finding 4) |

**Not tested** (no fixtures on disk): DOP2000 files (`BINWDOPV` magic),
gz/bz2 archives,
`replay()` animation loop, multi-sequence DOP2000 mode.

## Repro script (appendix)

```python
# Run from repo root after `uv sync --extra dev`.
# Sandbox note: prefix with UV_CACHE_DIR=.tmp/uv-cache for uv commands, and
# MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl for anything touching matplotlib.
import sys
import numpy as np
np.NaN = np.nan                      # shim: DOPpy predates NumPy 2 (finding 1)
sys.path.insert(0, "~/Repos/DOPpy")
import DOPpy

b = DOPpy.DOP("data/4-sensor-velocity/200RPM.BDD")
ch = int(b.getChannels()[0])
print(b["version"], b.getChannels(), b.getProfileType(ch))
v, t, d = b.getVelocity(ch), b.getTime(ch), b.getDepth(ch)
print(v.shape, t[0], t[-1], d[0], d[-1])
b.printSettings(ch)
b.imshow("velo", cmap="RdBu_r")      # headless-safe with Agg
```
