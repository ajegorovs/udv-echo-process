# Probing what a control actually accepts

Documented ranges are aspirational. A shipped build snaps a typed number to a discrete ladder,
clamps it, or silently reduces it to satisfy a constraint it never reports. Measure the domain
before designing a sweep or a batch run around it.

## Procedure

1. **Probe only where a wrong value is harmless**, and prefer the app's own idle/simulation state.
   If the app is mid-measurement on real hardware, stop, or do not probe at all.
2. **Hold every other knob at a known value** (a `--hold` list), because the answer to "what is
   this limit?" depends on the rest of the configuration.
3. **Write a ladder, read back each value, keep the accepted one.** Record
   `(target, accepted, neighbouring fields afterwards)` — the neighbours catch a write that
   quietly recomputed something else.
4. **Restore** every field touched, held ones included, and confirm the restore by reading back.
   Report which fields were touched and what they held before.
5. **Save the scan as JSON** with the app version and the mode. A domain measured once is
   reusable; re-probing an instrument for an answer you already have wastes measurement time.

## What the numbers mean

- **Snapping.** The accepted values *are* the ladder. Find the rungs, then find where the
  transitions happen: if they sit at the arithmetic midpoints between adjacent rungs, the rule is
  *nearest rung* — not floor, not round-up, not "the safest value".
- **Silent clamping.** Out-of-range requests come back changed, not rejected. Distinguish
  *reduced* from *refused*: a refusal leaves the field holding its previous value, a computed
  clamp moves it to a different value that satisfies a constraint. Never read a clamp as a
  capability limit — a count that came back as `9` was bounded by another knob's coarse setting,
  not by the app's ceiling.
- **One variable at a time.** A limit measured while another knob sits at whatever the previous
  scan left behind measures that combination, not the limit. Re-measure from a known baseline
  before concluding, and record which values were held.
- **A ladder can expose a hidden constant.** When the accepted steps are one internal constant
  times an integer index, the constant *is* the hidden quantity (rungs of `c/12000` mm expose the
  sound speed the app is using; the top of that ladder is its `c/100`). This is often the cheapest
  way to verify a setting the UI never shows — and the only way to catch one that is wrong, since
  such a constant scales the data rather than corrupting it.

## Where the result goes

A scanned domain is an input to the plan, not a curiosity: record the accepted ladder, the
constraint it must satisfy, and the chosen combination in the run's metadata, and have the driver
re-read every written value instead of trusting the request it made.

## Tooling

- `scripts/win_param_scan.py` — the scan, with `--hold`, JSON output and automatic restore.
- `scripts/win_control_io.py` — single-value read/write/restore when the domain is already known.
