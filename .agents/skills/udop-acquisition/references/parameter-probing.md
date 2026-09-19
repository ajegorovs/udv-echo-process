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

## Identifying which control is which knob

A surface of caption-less value fields states values, not names, so the binding has to be established
by measurement before anything can be written by position at all.

1. **Change exactly one knob by hand, then re-read and diff positionally.** One change at a time,
   named with the value the operator set. Derive each field's identity as `(column, row)` from its
   rectangle — never an id — and report which field moved; "nothing in this surface moved" is the
   equally useful answer that the knob lives somewhere else.
2. **Diff against a baseline captured before the change.** One taken earlier and committed as a
   fixture is trustworthy; a read dispatched before the change but landing after it is not, and a
   probe that buffers its output hides exactly that difference.
3. **Keep the read fast and single-purpose.** One surface, one open/close, JSON to stdout, seconds
   rather than minutes: an operator round trip cannot wait on a do-everything probe, and a long read
   holds the very surface they need between steps.
4. **Have the value restored, and confirm the restore.** The machine has to end in the state the plan
   was computed against — a knob left changed silently invalidates the next run's pre-run check.
5. **Expect a knob to be more than one control.** A value field with an enable flag beside it (a tick
   box, an "apply") is one knob: the value is inert until the flag is set, and the flag is usually a
   different control class from the value fields, so it never shows up in a value-field count. Record
   the pair together, write both, read both back.
6. **Do not resolve an ambiguous diff by plausibility.** When two fields move together a coupled
   recompute is the usual cause — re-run with a different value to attribute it, and keep the coupling
   as a write-order constraint.

7. **Bind the cell's own control, and expect the value's class to differ from cell to cell.** Walk the
   *wrapper* the surface draws for each value (a row-per-value grid) and record the class of the child
   that actually states the value: an edit-only scan of fifteen cells found **no** value for one knob at
   all, because that cell's value is held by a combo — and the same scan's count still came out right, so
   nothing flagged it. **A cell can hold two controls stating the same value** (measured: a combo plus an
   inner edit), so "the first thing inside the cell" is luck; bind by class *and* by the value read back.
   **And cells overlap geometrically:** a containment test with a few pixels of tolerance adopted a
   *neighbouring* cell's control and mis-assigned a value to the wrong knob, so confirm a cell's own child
   by its class and rectangle, and treat a control that appears inside several cells as unattributed
   until its real cell is established. A label is the one thing no API read returns — read labels off a
   capture at full resolution, and take the numbers from the control, never from the image.

## Where the result goes

A scanned domain is an input to the plan, not a curiosity: record the accepted ladder, the
constraint it must satisfy, and the chosen combination in the run's metadata, and have the driver
re-read every written value instead of trusting the request it made.

## Tooling

- `scripts/win_param_scan.py` — the scan, with `--hold`, JSON output and automatic restore.
- `scripts/win_control_io.py` — single-value read/write/restore when the domain is already known.
