# Finite 1+2 one-command control fixture

`mux-finite-01.BDD` is the application's unmodified output from the operator-supervised
October 29, 2026 trial. One command configured the existing manual 1+2 pair, invoked Run
once, awaited finite completion, stored the block once, closed the helper and restored
settings. No separate Store/restoration recovery script was needed; no explicit Record
or Stop was sent.

The file contains two sequential axial-velocity streams, five profiles × 80 gates each,
using 4 MHz / 600 µs PRF / 50 emissions per profile. It is a control/storage fixture,
**not validated flow data**: channel 2 is entirely zero.

[Derived evidence](../../../docs/dop3000/evidence/finite-one-command-20261029.json)
binds the original bytes, decoded configurations, same-command stages, cleanup and
independent final read. Rederive artifact facts and check the derived observations:

```
uv run --no-sync --extra dev python -m pytest tests/test_finite_one_command_evidence.py -q
```

Execution/UI/restoration/cleanup facts derive from retained private captures and cannot
be remeasured from this repository. The two false legacy carrier aggregate verdicts
(Run and routing) remain recorded; the composed workflow checked native call/return
receipts and fresh postconditions. This sitting did not test window occlusion or a
software abort, and the machine-bound command is not a promoted public CLI. The
[execution plan](../../../docs/plans/background-multiplex-recording.md) owns the verdict.
