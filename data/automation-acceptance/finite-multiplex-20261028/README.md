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
