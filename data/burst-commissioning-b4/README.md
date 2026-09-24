# B4 live commissioning — burst length (2026-09-24)

**Status: partial pass, word-27 relation unresolved. B5 remains gated.** This was an instrument-mode, channel-1 acquisition with a connected sensor but no active experiment. All four velocity payloads are zero; they are evidence for the control and stored-parameter path, not signal quality.

The app initially stated burst `10`, Sampling volume `1.850` mm. The supported `burst-length` command selected `4 → 10 → 18 → 10`; each command returned `verified` after Accept, reopening, and checking dialog identity, channel and both rows. The four corresponding 2-second `acquire point` runs stored the files below. The final dialog returned to burst `10`, volume `1.850` mm; the status command then reported a clean, ready measurement screen. The preflight recorded, stopped and cancelled the Store dialog without storing; its working directory matched `outputs/live/store/` when the points ran. The first attempt to invoke `point` without the mandatory `--expect-mode instrument` flag exited with usage code 2 and stored nothing; the corrected command ran once per file.

| Sequence | Reopened burst | Reopened volume (mm) | Stored word 8 | Stored word 27 | Profiles × gates | File |
|---|---:|---:|---:|---:|---:|---|
| 10 → 4 | 4 | 1.776 | 4 | 1 | 30 × 50 | `b4_burst_4.BDD` |
| 4 → 10 | 10 | 1.850 | 10 | 1 | 29 × 50 | `b4_burst_10_a.BDD` |
| 10 → 18 | 18 | 3.330 | 18 | 1 | 30 × 50 | `b4_burst_18.BDD` |
| 18 → 10 | 10 | 1.850 | 10 | 1 | 29 × 50 | `b4_burst_10_b.BDD` |

The four matching `b4-record-*-readback.log` files preserve the CLI's JSON and completion marker for each transition. `manifest.json` binds each recording to its SHA-256, decoded words, row reading and sample count. The two burst-10 BDDs are byte-identical; do not count them as independent signal replicates. The decoder's `ChannelConfig.sampling_volume_index` publishes raw operation word 27, while `sampling_volume_mm` stays unset. Every other decoded configuration field was identical across the four files (including channel, 1480 m/s sound speed, 4000 kHz transmit frequency, 600 µs PRF, 128 emissions/profile, 50 gates and 1.85 mm resolution). No claim is made about unrecorded or unreadable settings.

**Interpretation boundary:** Word 8 confirms the commanded burst in every stored file. Word 27 stayed `1` while the *effective* dialog volume changed. This is not proof of a second hidden dependent effect, nor proof that word 27 is wrong: it may be a retained selection/index whose effective millimetre value is raised by the burst-dependent floor. The B4 plan's assertion that the stored index must be the index *implied by* each displayed volume is not yet supported by a measured conversion. Do not promote a strict word-27-to-mm check or integrate the burst transition into a campaign (B5) on this evidence alone.

**Next decision, offline first:** check the manual's word-27 definition, the reader's index semantics and earlier paired captures against this constant-index observation. Specify what each candidate mechanism predicts for the *raw stored word*, the selected combo slot and the displayed volume. If existing evidence cannot distinguish them, design one bounded live contrast with pre/post readbacks, one short recording per discriminating state, and restoration to the operator's starting values. No active flow or useful Doppler signal is required for that control test. Review that contrast before using more device time.

Reproduce the decoded configuration, shape and digest from the committed files (from the repository root):

```bash
uv run python -c 'from pathlib import Path; import hashlib, json, numpy as np; from udv_echo_process.io.dop.bdd import read; p=Path("data/burst-commissioning-b4"); m=json.loads((p/"manifest.json").read_text()); [(lambda f,r: print(f.name, hashlib.sha256(f.read_bytes()).hexdigest()==r["sha256"], r["op_word_8"]==read(f).recording.streams[0].config.burst_length, r["op_word_27"]==read(f).recording.streams[0].config.sampling_volume_index, read(f).recording.streams[0].data.values.shape, int(np.count_nonzero(read(f).recording.streams[0].data.values))))(p/r["file"],r) for r in m["rows"]]'
```

The command checks the stored evidence, not the independent fact of what the dialog stated; that fact is in the paired CLI logs. There is no committed whole-screen image from this sitting and no active-signal conclusion.
