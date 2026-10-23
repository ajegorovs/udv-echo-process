# Multiplexed first look — do the per-channel sizes reach the bytes?

One recording, taken by the operator at the instrument on **2026-10-19 17:58 (+03:00)** and
stored as `mux-sizes-20261019.BDD` (35,054 bytes,
`sha256:0b0cba36f2908676945203896970a2c68724ba84acdbdf045df92680c2b1d200`). Its purpose was
narrow: the multiplexed workflow the plan maps says the `Acquire [n] Profiles or during [x]
seconds` fields are set **per enabled channel**, one channel at a time, behind the `Use only
channel` row (owner, 2026-10-19). If that is true, a file made with *different* sizes per
channel has to remember them separately. It does.

Nothing here was produced by the driver: this is an operator-recorded file, decoded offline.
No reader, writer or gesture was added for it. It loads through the committed reader unchanged —
`ArtifactBundle`, **3 streams** (channels 1, 2, 10), `acquisition_mode = SEQUENTIAL`,
`acquisition_order = None` (the reader derives no visit identity, as documented).

## What was configured

Read from the `Channels` dropdown at 17:28, then set by the operator:

| setting | value |
|---|---|
| participants (`Use channels`) | **1, 2, 10** |
| `Start the sequence by using channel` | 1 |
| `Repeat the acquisition sequence … times` | 1 |
| `Roll over the channels` | ticked |
| `Enable multiplexer` at record time | **on** (proven by word 52 below) |
| `Acquire` per channel | ch 1 = **5 profiles**, ch 2 = **7 profiles**, ch 10 = **duration 0.05 s** (1 profile) |

The sizes were deliberately unequal so a single run-wide number could not explain them.

## What the file says (measured, this file)

| word | ch 1 | ch 2 | ch 10 | ch 3–9 (unused) |
|---|---|---|---|---|
| **52** — mux flags | `0x00212033` | `0x00212033` | `0x00212033` | `0x00212033` |
| **52 bit 0** — multiplexer enable | **1** | **1** | **1** | 1 |
| **51** — profiles per block in multiplexer mode | **5** | **7** | **1** | 100 (default; no request behind it) |
| **53** — blocks in multiplexer mode | 1 | 1 | 1 | 1 |

- **16 measurement blocks**, channel order `1, 2, 10` then `1×5, 2×7, 10×1` — i.e. one extra
  profile of each channel before the sequence proper.
- **Per-profile block word = `0x01000001` on all 16 blocks** — high byte `0x01`, index 1. With
  `word 53 = 1` there is one roll, so index 1 is the whole story.
- **Timing**: profile period 40.3 ms; ch 1's five profiles span 0.161 s, ch 2's seven span
  0.242 s, ch 10's single profile spans 0.

## The relations this file establishes, with `data/4-sensor-velocity/200RPM.BDD` as the control

| quantity | this file | `200RPM.BDD` |
|---|---|---|
| blocks | 16 | 1,604 |
| distinct block-word indices | 1 | 100 (`1…100`) |
| `word 53` | 1 | 100 |
| `word 51` per channel | 5, 7, 1 | 4 on each of ch 6–9 |
| profiles per channel | 6, 8, 2 | 401 each |
| profiles / (`word 51 × word 53`) | 1.2, 1.143, 2.0 | 1.0025 |

So, on both files:

- **the per-profile block word is `0x01000000 | roll_index`**, with `roll_index` running
  `1 … word 53` and shared by every participant of that roll. Reading the field as a plain
  integer (as the plan's earlier note did: "spans 1..100") loses the constant high byte;
- **profiles per channel = `word 51 × word 53 + 1`** — one profile per channel is written
  before the roll structure begins. It is not part of `word 51`'s count, and a comparison that
  expects exactly `word 51 × word 53` will be off by one per channel.
- **`word 51` is per channel and survives as set.** That is the finding: `5`, `7` and `1` are
  three different channel sizes in one recording, so the size is a property of the channel, not
  of the run.

## What it does not show, and the one thing to re-check

- **Roll-over is not in the bytes.** `AcquisitionMode.ROLLING` is deliberately never emitted
  (`io/dop/bdd.py`), so this file cannot say whether the capture rolled; `Roll over the
  channels` being ticked is a *setting* read off the panel, not a decoded fact.
- **The operator states 0.2 s for ch 1 and ch 2**, and `word 51` stores 5 and 7. At the
  40.3 ms period measured here, five profiles are 0.2 s of acquisition and seven are ~0.28 s —
  so ch 2's stored size is **not** the 0.2 s visit the operator intended (or the field was left
  at an earlier value). The file is authoritative about what the instrument did; the intent
  should be re-read per channel from the panel before the next run, because this is exactly the
  kind of per-channel slip the automation has to make impossible.
- Which of the two fields governs when both hold a value is still open: ch 10 used the
  duration form (0.05 s → 1 profile), ch 1 and ch 2 the profile form. Both are stored as a
  count, so the count is what a run record must carry.
