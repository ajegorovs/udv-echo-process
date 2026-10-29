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

## Packaged command with Explorer covering the application

`mux-finite-packaged-02.BDD` is the unchanged 32,616-byte output of the separately
operator-supervised packaged `udv-acquire finite` trial on the same date. SHA-256:
`13b2ae900bd7062b3e35f4e068f737f5a8c2f98717458342cbfc8cd39e64635f`.
It decodes as channels 1 and 2, axial velocity, five profiles × 80 gates each at
4 MHz. It remains a control/storage fixture, not validated flow data.

[Packaged-trial evidence](../../../docs/dop3000/evidence/finite-packaged-covered-20261029.json)
records exit 0, one Run/one Store/no explicit Record or Stop, and independently
observed final equality of native settings and all ten parameter/TGC images.
The application ended disabled and Ready, channel 1/count 10/pending 0.
Independent offline raw-capture review accepted 11 native phases/19 returned
calls, hook removal and clean helper exit without kill. Those private captures
cannot be independently remeasured by the portable fixture tests.

The operator reported full coverage by maximized Explorer. Of 2,387 passive
foreground samples at nominal 50 ms spacing, 2,384 saw Explorer and three saw
brief console windows; none saw UDOP. This is **not** uninterrupted Explorer
foreground, proof of unsampled instants, or a software-abort test. Run the
portable checks with `uv run --no-sync --extra dev python -m pytest
tests/test_finite_packaged_covered_evidence.py -q`.
