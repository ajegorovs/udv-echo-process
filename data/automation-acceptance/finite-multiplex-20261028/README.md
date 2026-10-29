# Finite two-channel instrument-control fixture

`mux-finite-01.BDD` is the application's unmodified output from the operator-authorized
2026-10-28 finite trial. It contains sequential axial-velocity streams for channels 1 and 2,
five profiles per channel, 80 gates, with the existing 4 MHz / 600 µs PRF / 50-emission
configuration. This is a control, storage and timing fixture, **not validated flow data**;
channel 2 is entirely zero in this file.

The [evidence manifest](../../../docs/dop3000/evidence/finite-multiplex-live-20261028.json)
binds the bytes to the request and decoded stream facts. Re-derive those artifact facts with:

```bash
uv run --no-sync --extra dev python -m pytest tests/test_finite_multiplex_evidence.py -q
```

The raw file SHA-256 and the model's recording ID are distinct identifiers. The test checks
both. Native/UI/restoration observations in the manifest are derived from private captures;
their hashes are published, but those live observations cannot be remeasured from this fixture.
The [execution plan](../../../docs/plans/background-multiplex-recording.md) owns acceptance
and the remaining tooling/restoration limitations.

## Second operator-assisted trial

`mux-finite-02.BDD` is the unmodified output of the second authorized finite trial. It again
contains channels 1 and 2, five axial-velocity profiles × 80 gates each. The block was stored
once after two producer-start refusals, with no second Run or explicit Record/Stop. A real
clean helper shutdown and a separate restoration tail were verified; this is **not** an accepted
one-command workflow. Channel 2 is entirely zero; no physical-flow validity is claimed.

[Derived sitting evidence](../../../docs/dop3000/evidence/finite-operator-sitting-20261028.json)
records the owner-retained settings, failed/recovered stages, decoded file and cleanup/restoration.
Re-derive artifact facts and check the summary with
`uv run --no-sync --extra dev python -m pytest tests/test_finite_operator_sitting_evidence.py -q`.
