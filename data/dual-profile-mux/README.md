# `dual-profile-mux` — a two-plot (velocity + echo) multiplexed capture

`4MHz.BDD` (244,028 bytes, SHA-256 `7270664aa1793a51b8959da35f617368b21e705407e4c85c76f3636c5864d825`)
is a DOP3010 recording made with **two plots displayed** on the instrument, so
every measurement block stores one profile of *each* quantity. It is the fixture
behind plan §6.7's dual-quantity stream amendment: every `.BDD` committed before
it was single-quantity, and the reader used to keep a block's velocity profile
and silently drop its echo profile.

**Provenance.** Captured in the six-sensor multiplexed campaign (four channels at
4 MHz, two at 10 MHz); this is `4MHz.BDD` from the campaign's first recording
set. The `10MHz.BDD` of the same set has the same structure on channels 9–10 and
is deliberately not committed — it would duplicate the coverage at 300 KB.

**Measured structure** (raw block walk; every row is asserted in
`tests/test_io_bdd_artifacts.py`):

| Property | Value |
|---|---|
| Header version | `BINUDOPV6.07.4` |
| Header comment | `Memo_Comments` (otherwise empty) |
| Measurement blocks | 2004 |
| Channels with data | 1, 2, 3, 4 |
| Blocks per channel | 501 — 1 depth-only, 500 with signal |
| Profiles per signal block | 2: type 0 velocity (`int8`), type 1 echo (`uint8`) |
| Samples × gates per stream | 500 × 42 (gate 0 = 10.039 mm, pitch 2.220 mm) |
| Emit / PRF / sound speed | 4000 kHz / 941.6 Hz (word 5 = 1062 µs) / 1480 m/s |
| Module scale (echo decode) | 2048 |
| Multiplexer | enabled; word 51 = 50 profiles per channel per visit, word 53 = 10 blocks |
| Per-channel timeline | 50 samples at 71.4 ms, then a 10.83 s hole while the multiplexer serves the other three channels; ~143 s of acquisition |

Both profiles of a block carry that block's single footer timestamp, so for one
channel the velocity and echo streams share `time_s` and `gate_depths_mm`
exactly — the two plots are row-aligned, not two interleaved acquisitions. The
two quantities are *distinct profile payloads* (deterministically checked cell by
cell in `tests/test_io_bdd_artifacts.py`); their absolute correlation is below
0.5 across all 21,000 cells, which additionally rules out a simple rescaling but
is not a test of statistical independence and is not offered as one.

`uv run udv-inspect data/dual-profile-mux/4MHz.BDD` lists all eight streams
(four channels × two quantities).
