# B4 live commissioning — burst length (2026-09-24)

**Status: B4 passes for burst control; word-27 bandwidth-index promotion remains B6 work.** This was an instrument-mode, channel-1 acquisition with a connected sensor but no active experiment. All four velocity payloads are zero; they are evidence for the control and stored-parameter path, not signal quality.

The app initially stated burst `10`, Sampling volume `1.850` mm. The supported `burst-length` command selected `4 → 10 → 18 → 10`; each command returned `verified` after Accept, reopening, and checking dialog identity, channel and both rows. The four corresponding 2-second `acquire point` runs stored the files below. The final dialog returned to burst `10`, volume `1.850` mm; the status command then reported a clean, ready measurement screen. The preflight recorded, stopped and cancelled the Store dialog without storing; its working directory matched `outputs/live/store/` when the points ran. The first attempt to invoke `point` without the mandatory `--expect-mode instrument` flag exited with usage code 2 and stored nothing; the corrected command ran once per file.

| Sequence | Reopened burst | Reopened volume (mm) | Stored word 8 | Stored word 27 | Profiles × gates | File |
|---|---:|---:|---:|---:|---:|---|
| 10 → 4 | 4 | 1.776 | 4 | 1 | 30 × 50 | `b4_burst_4.BDD` |
| 4 → 10 | 10 | 1.850 | 10 | 1 | 29 × 50 | `b4_burst_10_a.BDD` |
| 10 → 18 | 18 | 3.330 | 18 | 1 | 30 × 50 | `b4_burst_18.BDD` |
| 18 → 10 | 10 | 1.850 | 10 | 1 | 29 × 50 | `b4_burst_10_b.BDD` |

The four matching `b4-record-*-readback.log` files preserve the CLI's JSON and completion marker for each transition. `manifest.json` binds each recording to its SHA-256, decoded words, row reading and sample count. The two burst-10 BDDs are byte-identical; do not count them as independent signal replicates. The decoder's `ChannelConfig.sampling_volume_index` publishes raw operation word 27, while `sampling_volume_mm` stays unset. Every other decoded configuration field was identical across the four files (including channel, 1480 m/s sound speed, 4000 kHz transmit frequency, 600 µs PRF, 128 emissions/profile, 50 gates and 1.85 mm resolution). No claim is made about unrecorded or unreadable settings.

**Adjudicated interpretation (manual §§8.4, 10.7; reviewed against this pass):** Word 27 is the stored *receiver-bandwidth definition*, not an effective thickness in millimetres. The manual says bandwidth and/or burst determine longitudinal thickness, and the burst determines it when longer than the bandwidth-associated thickness. With sound speed `1480 m/s` and transmit frequency `4 MHz`, the burst-length expression `1000·c·N/(2·f)` gives `0.740`, `1.850`, `3.330` mm for N=`4`, `10`, `18`. Taking the observed burst-4 value `1.776 mm` as the bandwidth-associated thickness predicts `max(1.776, burst length)` = `1.776 / 1.850 / 3.330 / 1.850 mm`—exactly the four reopened reads. The constant stored word 27 (`1`) is compatible with a retained bandwidth definition while burst length raises the *effective* displayed thickness. This is strong support for the manual's two-quantity model, **not** a measurement of the entire word-27-to-bandwidth ladder or proof of a unique inverse from displayed mm. The combo's slot 0 repeats current effective state (at burst 18, `3.330` is absent from the fixed tail), so `item_index=0` is not stored word 27.

**B4 verdict:** the verified transition, dependent readback, independent word-8 agreement, decoded-setting invariance and restoration meet the burst-control gate. B5 job-level integration may proceed without another B4 live test, provided it keeps the effective mm as observed dialog provenance and never derives it from word 27 or writes Sampling volume to “restore” it. The old criterion `word 27 == the index implied by displayed mm` conflated the bandwidth definition with effective thickness and is withdrawn. B6 separately decides how to carry/check the stored bandwidth index; `sampling_volume_mm=None` in the BDD reader remains correct. Manual semantics do not replace a future end-to-end live acceptance of B5 itself.

An earlier volume-*write* probe changed First gate depth despite restoring the two edited fields (`docs/dop3000/acquisition-campaign-compilation-plan.md` §19.4); burst-only writes in this pass did not change the decoded gate geometry. Do not spend device time on explicit volume writes to settle word 27 as part of this burst-control feature: that is a separately coupled capability study.

Reproduce the decoded configuration, shape and digest from the committed files (from the repository root):

```bash
uv run python -c 'from pathlib import Path; import hashlib, json, numpy as np; from udv_echo_process.io.dop.bdd import read; p=Path("data/burst-commissioning-b4"); m=json.loads((p/"manifest.json").read_text()); [(lambda f,r: print(f.name, hashlib.sha256(f.read_bytes()).hexdigest()==r["sha256"], r["op_word_8"]==read(f).recording.streams[0].config.burst_length, r["op_word_27"]==read(f).recording.streams[0].config.sampling_volume_index, read(f).recording.streams[0].data.values.shape, int(np.count_nonzero(read(f).recording.streams[0].data.values))))(p/r["file"],r) for r in m["rows"]]'
```

The command checks the stored evidence, not the independent fact of what the dialog stated; that fact is in the paired CLI logs. There is no committed whole-screen image from this sitting and no active-signal conclusion.
