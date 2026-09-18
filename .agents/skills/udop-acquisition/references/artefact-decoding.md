# Decoding the artifact a run produces

The stored file is the read-back that proves a run used the parameters you asked for: a field echo
proves only that a text buffer changed, a status readout only that a display updated, the artifact
that the acquisition path actually consumed the value. Two jobs — locate the parameter table, and
prove the decode.

## 1. Prove the shape before you trust a single number

Wrong shape assumptions produce a complete table of plausible numbers, which is the worst failure
mode available: nothing looks broken, so nothing gets checked.

- **Confirm the word size against a value you already know.** A table read as unsigned 16-bit when
  it is 32-bit yielded a full, plausible parameter table in which every entry was wrong; the same
  table decoded correctly the moment the dtype changed. Pin one field whose value you set yourself
  (emitting frequency, sound speed, gate count) before reading any other entry.
- **Confirm the stride.** A guessed record stride made one block reappear under consecutive channel
  indexes, with padding reading as zeros. Check that consecutive channel blocks differ where they
  should, and that each block's first field holds a value you expect.
- **Confirm the channel indexing.** One file holds several configurations: edits apply to the
  channel selected in the UI, so the others keep whatever they held before (measured — a file whose
  channels 6-10 matched the live readout while 1-5 carried a stale, different point). Read the block
  for the channel the run used, and treat a block that is byte-identical across unrelated files as a
  leftover, not a measurement.
- **Take the data offset from the format's own header** (a vendor helper, or the magic/offset fields
  the file declares) instead of hard-coding a guess.

## 2. Pin fields by differencing two LABELLED fixtures

The cheap way to learn what a field means is not to interpret one file — it is to produce two whose
inputs you know and difference them.

1. Run once at a known configuration, store the artifact, and write down every value you set.
2. Change a **deliberately distinctive** set — e.g. 37 gates, PRF 333, 44 emissions, 7 degrees, burst
   length 2 — chosen so that a match cannot be coincidence, and store a second artifact.
3. Difference the two parameter tables field by field. The entries that moved are the ones your
   inputs control, and each now has two known points, which pins it.

Rules that make it work:

- **Distinctive, not realistic.** A field that moved `4 → 2` when you asked for burst length 2 is
  pinned. A field that read `40` in both tells you nothing.
- **One point is a hypothesis; two are a mapping.** Record next to each entry the labelled value it
  tracked, so a later session can see what the evidence was.
- **Vary one family at a time.** Two knobs that move together leave an ambiguity that survives the
  analysis (two candidate fields moved together because the fixture changed both) — pick the next
  fixture to separate them, or park the ambiguity explicitly instead of guessing.
- The second fixture is also the cheapest end-to-end test of the **write** path: it proves the value
  you set in the UI, or by message, reached the engine, which no field read-back can establish.

## 3. Cross-check against a relation, never against plausibility

A decode is verified when it reproduces something independent of the bytes just read:

- a **derived quantity** the app itself computes and displays (a depth equal to first gate + gates x
  pitch; a resolution law `pitch = (n+1) c/12000`);
- a **ratio** between the two fixtures (a velocity-scale field whose change matched the PRF ratio
  between the two points);
- a **round trip**: write a value, store, read it out of the artifact, write the original back, and
  confirm the artifact returns to its first reading.

Label each entry `verified` / `from documentation` / `unverified` and say which cross-check backs it.
A field merely consistent with a paragraph of the manual is not verified.

## 4. Keep the fixtures, and name them for their point

Store labelled fixtures beside the decoder. A future session re-derives the whole mapping from them
in minutes; without them it re-runs the instrument to ask the same questions again.

## 5. What the artefact proves about the run's duration, and about per-item state

Two questions the file is asked to settle, and neither is answered by one file alone.

- **Requested duration is not stored duration.** A cycle that presses record, holds `T` seconds and
  presses stop has set an exact delay — verify that from the run's own stage notes or per-stage
  timestamps, never from the file. What the file *holds* is separate: measured on one instrument at a
  single configuration, a 3 s delay stored ~3 s, 6 s stored ~4.4 s, 12 s stored ~8.4 s, so the
  shortfall grows with the length. Settle it with a **two-duration linearity run** — two points,
  identical settings, one delay double the other, the buffer reset before each and nothing else
  varied. If the stored quantity doubles, the delay sets the window; if it does not, the instrument is
  truncating, and a duration-based comparison needs the *achieved* window on each point's own record.
  A size calculation cannot tell a ring cap from a slower rate, so do not name the cause from it.
- **Count records, not only bytes.** Where the file carries repeating records, the record count *is*
  the profile/frame count and is read directly (difference two files to find the stride). A bytes-per-
  unit **signature** calibrated on a different configuration yields a number rather than a measurement:
  report it as an inference, and prefer the instrument's own counter wherever one exists — and check
  that the read you are relying on exists in the code, since a docstring can promise a counter read
  that was never implemented.
- **A per-item configuration word dates a state change.** When a per-item mode or state is suspected
  of having been changed by your own step, read the field the file records for that item across the
  *older* files on disk before touching the driver: measured, that flag read the same in files written
  hours before the suspected step, and predicting the state of an item the run had never touched — then
  checking it on the instrument — settled the question. The state was long-standing configuration; the
  suspicion was the error. Read the *same word index per item*: one word read at each item's own offset
  is a different field for every item, which is how a per-item flag first looks like a constant.
