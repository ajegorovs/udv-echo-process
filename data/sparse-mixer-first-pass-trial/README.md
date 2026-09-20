# The bounded trial's own recordings — 2026-09-20

The six points the operator-attended trial of `sparse-mixer-first-pass` stored on the instrument,
committed so the trial's claims can be checked from the files instead of from a summary. What the trial
is, the gates it answers, and its verdict are in `docs/dop3000/sparse-run-plan.md` §5; what each file
carries is also frozen in `retention.json` beside them, written from the files themselves.

| stored file (all `20260920`, names as the pass wrote them) | job / point | profiles | span | window and burst |
|---|---|---:|---:|---|
| `sparse1-burst-4-ctrl-begin-…T222516.BDD` | `burst-4` ctrl-begin | 562 | 12.549 s | 50 gates / rung 14 / 1.85 mm / depth 101 / burst 4 |
| `sparse1-burst-4-cc1-…T222516.BDD` | `burst-4` cc1 | 562 | 12.566 s | 145 / rung 4 / 0.6167 / 99 / burst 4 |
| `sparse1-burst-4-ctrl-mid-…T222516.BDD` | `burst-4` ctrl-mid | 562 | 12.549 s | 50 / rung 14 / 1.85 / 101 / burst 4 |
| `sparse1-burst-4-cc3-…T222516.BDD` | `burst-4` cc3 | 562 | 12.545 s | 31 / rung 23 / 2.96 / 99 / burst 4 |
| `sparse1-burst-4-ctrl-end-…T222516.BDD` | `burst-4` ctrl-end | 563 | 12.571 s | 50 / rung 14 / 1.85 / 101 / burst 4 |
| `sparse1-common-reference-1-cr1-…T222916.BDD` | `common-reference-1` cr1 | 562 | 12.549 s | 50 / rung 14 / 1.85 / 101 / **burst 10** |

Every file: sound speed 1480 m/s, PRF 600 µs, emissions 20 per profile, and the achieved period is
22.37 ms — so a 12 s window holds ~562 profiles, not the ~924 the plan's estimate assumed. The spans
above are what the retention gate reads (the pass asks for ≥ 11.52 s of usable physical time).

The three configurations' window words are the same ones the committed sweep's own files carry
(`data/mixer-sensitivity-analysis/4MHz/0500RPM/001/res/1-8.BDD`, `res/0-6.BDD`, `res/3-0.BDD`), which is
what "CR1 restores the reference condition" means here: `cr1`'s stored words equal that reference file's
on all eight fields, including `burst 10`.

## Reproducing either half from the files

Words — the certificate; it needs no application:

```bash
uv run --no-sync udv-acquire decode \
    data/sparse-mixer-first-pass-trial/sparse1-burst-4-ctrl-begin-20260920T222516.BDD --channel 1
```

Retention — profile count and first→last stamp span, from the package's own reader:

```bash
uv run --no-sync python - <<'PY'
from udv_echo_process.io.dop.bdd import read
path = "data/sparse-mixer-first-pass-trial/sparse1-burst-4-ctrl-begin-20260920T222516.BDD"
times = read(path).recording.streams[0].data.time_s
print(f"{len(times)} profiles, span {float(times[-1] - times[0]):.3f} s, "
      f"period {(times[-1] - times[0]) / (len(times) - 1) * 1000:.3f} ms")
PY
```

`retention.json` records the same two numbers for all six, in the form this repository's review reads.
