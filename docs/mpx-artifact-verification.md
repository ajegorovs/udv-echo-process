# Multiplexed artifact verification (`acquire mpx-check`, `record-multiplexed`)

`acquire mpx-check` verifies one **already-stored** multiplexed `.BDD` against the
operator's completed-block declaration. `acquire record-multiplexed` runs the same
check automatically on the file its own store just produced. Both are offline from
the instrument's point of view: no window, no instrument, no network, and nothing
written. Both reuse the existing reader (`io.dop.bdd.read_with_containers`, which returns the
same `ArtifactBundle` plus the reader's own per-container evidence) and the existing
`CompletedBlockDeclaration`; no word parser is added to this command. The plain
`io.load` / `bdd.read` path is untouched: evidence is opt-in, so an ordinary decode builds
no per-container models and parses no footer word beyond the rows it needs.

Measured plain-read cost on this host (CPython 3.14.3, `time.perf_counter` +
`tracemalloc` peak, seven warm runs per file, median; **traced peak, not process-family
memory**):

| file | before (evidence always built) | after (opt-in, not requested) |
| --- | --- | --- |
| `data/4-sensor-velocity/200RPM.BDD` (150184 B) | 316.0 ms, 5647 KiB | 214.7 ms, 3013 KiB |
| `data/echo/200.BDD` (219439 B) | 493.9 ms, 13328 KiB | 224.8 ms, 6441 KiB |

Decoded rows, artifact ids, `recording_id` and the timestamp clock are identical before and
after (asserted in `tests/test_bdd_block_evidence.py`); the evidence itself is not free —
`read_with_containers` on the same two files measured 307.6 ms / 5574 KiB and
433.4 ms / 12060 KiB.

```bash
uv run python -m udv_echo_process.cli acquire mpx-check FILE.BDD \
  --channel 1 2 --profiles 50 --json
```

- `--channel` accepts the declared channels (same spelling as `store-completed`).
- `--profiles` is the declared profile count per channel.
- `--stated-by` defaults to `cli`; `--statement` keeps the caller's raw words.
- `--json` prints the typed report and nothing else on stdout.

The declaration is validated **before** the file is read or decoded, by the same pure
clause function `store-completed` uses. An invalid one (e.g. one channel, zero profiles,
no attribution) exits 2 with one concise refusal line on stderr — not pydantic's
multi-line validation dump — and decodes nothing.

## What is compared

Exactly two facts, because they are the two the declaration states:

- the exact decoded channel set;
- the decoded profile count for each declared channel.

A declaration that states its count as a per-visit count plus a repeat count adds a third
comparison — the stored container partition, described under *Repeated declarations*.

Each result is a typed clause with status `consistent`, `contradicted`, `unverifiable`
or `unreadable`. Exit codes: 0 consistent, 1 contradicted, 2 invalid declaration,
3 unverifiable, 4 unreadable. The report also carries the file SHA-256, byte size, the
decoded acquisition mode, and one summary per stream: channel, quantity, unit, profiles,
gates, time start/end/span, finite and non-finite cell counts, nonzero samples and values,
and `abs_max` over finite cells.

`time_span_s` is the last decoded sample time minus the first. It is a **span, not
coverage**: it is not the requested block duration and it makes no claim that no profile
is missing or that the sampling rate was honoured.

## Automatic post-store check (`record-multiplexed`)

After `record-multiplexed`'s one store returns a path, that **exact** returned path is
decoded with the same verifier and compared with the **original validated
declaration** the run began with — its channels, its per-channel profile count, and
its own `stated_by` / `stated_at` / `statement` provenance. The run's result carries
this as a separate typed `artifact_verification` report next to `stored_path`,
`store` and the declaration.

The stored fact does not depend on the verdict:

- `consistent`, `contradicted`, `unverifiable` and `unreadable` are all reported on a
  run whose `stage` is `stored`;
- a verifier that raises is reported as an explicit verification unknown
  (`artifact_verification: null` with `artifact_verification_error` set), never as a
  store failure and never as a pre-press refusal (exit 2);
- nothing is re-recorded, re-stored, retried or cleaned up, whatever the check says.

CLI exit codes for `record-multiplexed`: `0` only when the block was stored **and**
the artifact was `consistent`; `1` stored but `contradicted`; `3` stored but
`unverifiable`, or the verification itself failed; `4` stored but `unreadable`. The
nonzero messages name the saved path and state that the file was stored once and is
neither rewritten nor re-stored. The existing mode-unknown obligation is still
reported on every stored run.

`store-completed` (the store-only sibling) is unchanged: its legacy workflow returns
one store result, and its CLI contract was not asked to grow an exit-code
interpretation of the stored bytes.

## Limits

- **No ordering, rolling or visit claim.** `sequential` is the decoded multiplexer-enable
  bit, not a channel order, and roll-over is a runtime option the file does not store.
  The reader now reports each stored container's own vendor block/sequence word, but the
  manual documents that word **only** as a block/sequence number: no round, visit or roll
  identity is derived from it, from timestamps, or from decode order. It is a stored word,
  not proof that a physical acquisition event happened.
- **A "block" in the report is a run, not an instrument block.** The report calls a run of
  *contiguous* containers sharing one stored word a block. Containers are never counted as
  "N blocks stored" from a histogram over the raw words.
- **Truncation is a count, not a corruption verdict.** The existing decoder keeps every
  complete container, so a truncated file decodes fewer profiles and is reported as a
  contradicted count. The command does not brand the file as corrupt.
- **`unreadable` is one status for several causes.** The existing decoder has no typed
  decode error: `ValueError` covers "these bytes are not a DOP3000 `.BDD` file", a failed
  gate/depth integrity cross-check and pydantic validation alike, and `struct.error` /
  `IndexError` can escape the fixed-header buffer on a truncated file. This command keeps
  the decoder's own words as the reason rather than classifying them, so an `unreadable`
  verdict does **not** distinguish an unsupported format from a failed integrity check
  from an internal decoder failure — and it is never proof of corruption.
- **Zero is signal.** An all-zero stream reports `abs_max: 0.0`; this is not a failure,
  a quality grade, or a claim that the target produced "no returns".
- **No quality grade** is computed or implied by the value summary.
- **Streams are never merged.** Streams are keyed by channel and quantity; no profile
  count is merged or overwritten. A channel with two streams is `unverifiable`, and the
  reason distinguishes two different quantities from a **repeated same quantity** (the
  decoder did not report one stream per channel).
- **Identity is the streamed content digest.** The file is hashed through one open handle
  before and after the existing decoder reads it (`hashlib.file_digest`, no whole-file
  buffer), the `fstat` identity (device, inode, size, mtime_ns) of both reads is reported,
  and the decoder's own content digest and byte size must equal the streamed digest and
  size. Disagreement reports the actual digest on both sides. If the bytes changed, the
  verdict is `unreadable` and no clause is called consistent. This is content identity,
  not proof the file was never rewritten with the same bytes.
- This is an artifact check only. `record-multiplexed` runs it after its own store; it is
  never a recording, stopping, re-storing or cleanup step, and `store-completed` does not
  run it.

## Live acceptance records (2026-10-21)

Three operator-authorized runs of the automatic path, on the real instrument. Each is one
invocation by one operator, not concurrent or unattended certification; the raw command
logs and captures are kept locally. All three stored one block under one `Record` press
and one `Do store` commit, and exited `0`; each run's own `notes` record that it pressed
no Stop, Pause, Clear and restart, New acquisition, Remove current block, Disable
multiplexer, Channels menu or parameter write. The asymmetric run's channel-2 count was
changed by a separate Channels trial before it (and restored after, below), not by the run.

| run (in `outputs/live/store/`) | declared | stored per channel | gates | verdict | artifact |
| --- | --- | --- | --- | --- | --- |
| `mpx12-50profiles-verified-01` | `--channel 1 2 --profiles 50` | 50 / 50 | 42 | `consistent` | 37574 B |
| `mpx12-50profiles-repeat2-auto-01` | `--channel 1 2 --profiles-per-visit 50 --repeats 2` | 100 / 100, two runs of 50 | 42 | `consistent`, `partition-consistent` | 43674 B |
| `mpx12-50-75profiles-repeat2-auto-01` | `--channel 1 2 --channel-profiles 1=50 2=75 --repeats 2` | 100 / 150, runs 50+50 and 75+75 | 42 | `consistent`, `partition-consistent` | 46724 B |

Common to all three: `stage: stored`, with `artifact_verification` carried as a
**separate** report beside `stored_path`, `store` and the declaration — the store result
does not contain or derive from the verdict; `identity_verified: true` (both streamed
reads agree with each other and with the decoder's own digest and size);
`acquisition_mode: sequential` (the multiplexer-enable bit only); both channels
`axial_velocity` / `mm/s`; 0 non-finite cells; 0 nonzero samples; `abs_max 0.0`.

SHA-256 of each retained artifact, as reported by the verifier and confirmed by re-hashing
the file on disk (the artifacts are git-ignored, not published):

- `20195ac66088abf4355f904d61df458f98a96c28b94cd8b399ac72b1be7295d5` (37574 B)
- `cca9bcefe09a843d988a758c250a1d7e50fa48e49afbabebacd1119115a11b52` (43674 B)
- `9ecc5bd08dabb642f9e5bd1c556dfac7f8320bc67bcfd53fa1fff6ce3ad614e0` (46724 B)

After the asymmetric run, a separate `acquire status` read reported the strip in view
`ready` with the measurement surface active, no menu popup and 0 dialog panels: the run
left the application Ready rather than in the Store dialog or a store view.

### Asymmetric run: channels 1=50, 2=75, repeats 2

`acquire record-multiplexed mpx12-50-75profiles-repeat2-auto-01 --channel 1 2
--channel-profiles 1=50 2=75 --repeats 2 --stated-by operator --mpx-enabled
--completion-timeout 60 --statement
operator-confirmed-channels-1-2-pervisit-50-75-repeats2-rollover-on-mpx-enabled`.

- Every clause `consistent`: channel set `[1, 2]`; `profiles:channel 1` expected `100`
  (`2 x 50` for that channel), decoded 100; `profiles:channel 2` expected `150`
  (`2 x 75`), decoded 150; `repeats` `partition-consistent` — stored words `1, 2` on both
  channels, channel 1 holding `[50, 50]` profiles and channel 2 `[75, 75]`.
- Streams: 100 and 150 profiles of 42 gates (4200 and 6300 finite cells), 0 non-finite,
  0 nonzero samples, `abs_max 0.0`; spans 7.0393 s and 8.0551 s, which are spans, not
  coverage, not the requested duration and not a roll or ordering claim.
- Artifact retained: 46724 bytes, SHA-256
  `9ecc5bd08dabb642f9e5bd1c556dfac7f8320bc67bcfd53fa1fff6ce3ad614e0`,
  `identity_verified: true`.

The trial changed one setting (channel 2, 50 → 75 profiles) and had to put it back. The
profile field's duration is the application's own arithmetic over the profile count, so it
moves with the write rather than measuring an acquisition:

| step | channel 2 profiles | channel 2 seconds | state |
| --- | --- | --- | --- |
| baseline, before the trial | 50 | 2.01 | popup read |
| trial setting (write 50 → 75) | 75 | 3.02 | `persisted: unknown`, obligation open |
| restoration (write 75 → 50) | 50 | 2.01 | `restored_baseline: true`, obligation still open |
| after the operator reopened the dialog | 50 | 2.01 | the read that closes the obligation |

- Both writes recomputed the seconds (`seconds_recomputed: true`); 2.01 s and 3.02 s are
  the field's derivation from 50 and 75 profiles, not measured durations.
- A write proves the field, not that the application kept it. Only a read from a reopened
  dialog counts here, and the operator took it: `restoration_owed: false`, no restoration
  obligation remains.
- Final state: channel 1 selected, repeat `2`, channel 1 at 50 profiles / 2.01 s — the
  trial's selection and repeat were preserved.
- The popup paints the channel it belongs to in its caption and states nothing in its
  tree, so channel identity in these reads is operator-declared with caption
  corroboration, not a native checked-state proof; and restoration was verified after
  reopening the popup, not after an application restart.

### What these records do not say

- **The zeros are expected here and prove nothing physical.** After the asymmetric run the
  operator stated the sensors had been removed and would remain disconnected for days; no
  removal time was established. Zero-valued samples are compatible with that context, and
  the `0 nonzero` counts are evidence about the artifact and the decode only — not a
  statement that the target produced no returns, not a failure, and not a quality grade.
  See [Zero is signal](#limits) above, which still applies unchanged.
- **The multiplexer's final state is unknown.** The run's own `owed` note stands: no
  passive MPX discriminator exists, the command presses no Disable, and the operator's
  declaration is the only statement of the mode. Nothing here reads back whether the
  multiplexer is still enabled, so `--mpx-enabled` is a caller claim, not a post-run fact.
- **The stored partition is not a visit count.** A matching per-channel total and a
  matching run split are not proof that two visits were stored; the footer word is a
  block/sequence number.

## Not setting-free: the remembered Store directory

`record-multiplexed` writes the Store dialog's **Working directory** field to the
caller's `--store-dir` and commits it, because the application resolves the stored path
itself and a relative path would verify in this process while storing elsewhere. That
write is not reverted: the dialog keeps the caller's directory, so a later store — from
this tool or from the operator's hands — starts from the repository's output directory
instead of whatever the dialog remembered before. On this run the field held a previous
experiment folder and was rewritten; the result reports it as
`store.directory_rewritten: true` with the before/after texts in
`store.directory_verification` and one `driver_notes` line.

So the run **changes persistent application state**: it is an artifact check with a
GUI-state side effect, not a read-only operation. Treat the reported before/after as the
record of it, and do not describe a stored run as leaving the instrument untouched
merely because it pressed no Stop or Disable.

## Repeated sequences: `--profiles-per-visit` with `--repeats`

`--profiles` keeps its original meaning: the operator's stated **total** per channel for
the whole stored file. A repeated sequence is stated explicitly instead, and the two
bases are mutually exclusive:

```bash
uv run python -m udv_echo_process.cli acquire mpx-check FILE.BDD \
  --channel 1 2 --profiles-per-visit 50 --repeats 2 --json
# same flags exist on `record-multiplexed`; --profiles 100 is refused beside either
```

- `--profiles-per-visit N` and `--repeats M` must be given together and both are positive
  strict integers. The expected total (`N × M`) is normalized once, in
  `CompletedBlockDeclaration.expected_total_profiles`, and reported as
  `expected_total_profiles`.
- Stating `--profiles` together with either half, or only half of the pair, exits `2` with
  one refusal line before the file is opened or any window is read. The same holds for
  `record-multiplexed`, where the refusal precedes every device action.
- The report retains the operator's own numbers as such —
  `declared_profiles_per_visit`, `declared_sequence_repeats`, `count_basis`
  (`stated-total` or `per-visit-times-repeats`) — and never presents them as decoded facts.

**What a repeat declaration is compared with.** On request (`read_with_containers`) the
reader keeps every profile container and reports, per container, its 0-based source ordinal,
its raw vendor block/sequence word and how many profile rows of each quantity it holds
(`ProfileContainerEvidence` in `io/dop/bdd.py`). The `repeats` clause projects those facts
per channel and per quantity into **runs**: maximal stretches of *contiguous* containers in
the channel's own container order that share one stored word. Other channels' containers
between them do not break a run — that interleave is the normal multiplexer visit pattern —
but a word that reappears after a different word opens a new run and is **never** merged
with the earlier one. The stated `M x N` split is compared with that partition:

- `consistent` — the channel has exactly `M` runs, each holding exactly `N` profile rows,
  every stored word appears in exactly one run, and the ordered run sequence is the same on
  every declared channel (`repeat_verification: partition-consistent`, exit not forced by
  this clause);
- `contradicted` — the runs settle the partition and disagree with `M x N`
  (`partition-contradicted`);
- `unverifiable` — the file cannot settle it: only **one** run with `M > 1` (a single run
  cannot show the per-visit split), a container whose own footer does not yield a word (a
  `0` word, or a container shorter than its 12-byte footer), a **reused** word that appears
  in more than one non-contiguous run, a channel whose containers carry more than one
  quantity, or declared channels whose ordered run sequences differ. The partial
  per-container counts, source ordinals and run lengths are still reported.

The clause always states that the footer word is a block/sequence number, not a visit
identity, so even `consistent` means "the stored containers split the rows as declared",
never "M visits ran", and never a claim about physical acquisitions. The **configured**
values are reported beside the partition and never substituted for it: op word 53 ("Nb
blocks in multiplexer mode") and op word 51 ("Nb profiles in block in multiplexer mode")
appear as `configured_containers_in_mode` / `configured_profiles_per_container` on every
channel, and the clause says explicitly that configuration is not evidence that those
containers or runs exist. Word 51 is configuration only and is never used as a divisor.

Measured on stored artifacts (each figure is the reader's own walk, 0 trailing bytes):

- `outputs/live/store/mpx12-50profiles-repeat2-01.BDD`, 43674 bytes, SHA-256
  `bc79760cdc9cd91e22334db713feea3ca95e4d8eb9a6d15ac8d3a274e00dfbc8` (git-ignored, not
  published): **202 profile containers** — one depth-only container plus 100 single-row
  velocity containers per channel. Channels 1 and 2 each hold 100 velocity rows of 42
  gates in **two runs** of 50 rows, with stored words `1` and `2`; op 53 = 2, op 51 = 50.
  `--channel 1 2 --profiles-per-visit 50 --repeats 2` reports every clause `consistent`,
  `repeat_verification: partition-consistent`, and runs `[(1, 50, 50), (2, 50, 50)]`
  (word, rows, containers) per channel.
- `data/4-sensor-velocity/200RPM.BDD` (tracked authentic multiplexed capture, 150184 bytes,
  400 rows per channel): **1604 profile containers** — one depth-only container plus 400
  single-row velocity containers per channel, four contiguous containers per stored word.
  `--profiles-per-visit 4 --repeats 100` reports 100 runs of 4 rows per channel with the
  same ordered words `1..100` on all four channels, `partition-consistent`; op 53 = 100,
  op 51 = 4; `--profiles 400` remains `consistent` exactly as before.
- `outputs/live/store/mpx12-50profiles-verified-01.BDD` (the single-cycle accepted run):
  102 profile containers; one depth-only container plus 50 single-row velocity containers
  per channel, all with stored word `1`, op 53 = 1 — the single-run case, `unverifiable`
  for any `M > 1` and consistent with `--profiles 50`.

A crafted mutation of the authentic capture (its 400 velocity containers per channel
rewritten to alternate `1,2` every two containers, so 200 runs of 2 rows) is the
regression for the partition rule: a histogram that summed every `1` and every `2` would
see "2 blocks of 200 rows" and call `2 x 200` consistent, and the reader instead reports
the reused words and `repeat_verification: unknown`. That case is covered in
`tests/test_bdd_block_evidence.py`.

These are offline decodes of already-stored files. The `mpx12-50profiles-repeat2-01.BDD`
artifact has no operator-stated declaration attached to its own acquisition, so its
`repeats` clause is evidence about the stored container partition only; the live repeat-2
acceptance on this host is the auto row in the records above. Whether a repeat>1
acquisition stores one word or several is settled for these artifacts (both words were
stored) and remains unmeasured elsewhere; the word is a block/sequence number and is not
proof of the physical acquisitions behind it.

## Per-channel counts: `--channel-profiles` with `--repeats`

The multiplexer's channels need not be configured for the same profile count, so the
operator can state one per-visit count **per channel** instead of one uniform number:

```bash
uv run python -m udv_echo_process.cli acquire mpx-check FILE.BDD \
  --channel 1 2 --channel-profiles 1=50 2=75 --repeats 2 --json
# same flags exist on `record-multiplexed` and `store-completed`
```

- `--channel-profiles CHANNEL=COUNT ...` states each channel's profiles for **one visit**
  and requires `--repeats`. Each channel's expected stored total is that channel's own
  count times the one repeat count — `100` for channel 1 and `150` for channel 2 above.
- The grammar is one grammar, with no repair: `CHANNEL=COUNT` with positive decimal
  integers and no sign, whitespace or leading zero. `1=050`, `+1=50`, `1 = 50` and `1`
  are refused by name, and a channel stated twice is refused.
- The mapping must name **exactly** the declared channels once each. A duplicate key, a
  declared channel with no stated count, and a key the declared channels do not include
  are all refused; nothing is filled in, copied from a neighbour or dropped to make the
  mapping fit.
- It is a third count basis, mutually exclusive with `--profiles` and
  `--profiles-per-visit`. Stating it beside either, or without `--repeats`, exits `2` with
  one refusal line **before** the file is opened (`mpx-check`, `store-completed`) or any
  window is read (`record-multiplexed`), so an invalid statement produces no decode, no
  claim and no device action. `--profiles` and `--profiles-per-visit` keep their existing
  meanings unchanged.
- **One owner normalizes the mapping.** `CompletedBlockDeclaration` re-orders the pairs to
  the caller's channel order exactly once and exposes `count_for_channel(channel)` and
  `expected_profiles_by_channel`; the uniform bases delegate to the same method, so there
  is no second multiplication anywhere. Because an asymmetric statement has no single
  total, `expected_total_profiles` is `None` for it — a consumer that needs a total asks
  the owner per channel rather than presenting one channel's number as a uniform one.
- The report keeps the operator's pairs as `declared_channel_profiles` and adds
  `expected_profiles_by_channel` (normalized totals, in declared channel order). Each
  `profiles:channel N` clause compares against that channel's own expectation and names
  the per-channel derivation; the `repeats` clause compares each channel's run size with
  that channel's per-visit count.

Measured on the real repeat-2 capture (git-ignored, not published —
`outputs/live/store/mpx12-50profiles-repeat2-01.BDD`, SHA-256
`bc79760…e00dfbc8`): channels 1 and 2 each hold 100 rows in two runs of 50.
`--channel 1 2 --channel-profiles 1=50 2=75 --repeats 2` on that uniform file reports
channel 1 `consistent` (`100 = 2 x 50`), channel 2 `contradicted` (`150` expected, `100`
stored), and the run split contradicted for channel 2 only — a **correct negative**. The
real asymmetric acquisition is the accepted `mpx12-50-75profiles-repeat2-auto-01` run in
the records above (100 and 150 profiles, runs 50+50 and 75+75, every clause `consistent`).
The tracked `data/4-sensor-velocity/200RPM.BDD` still reports `consistent` for
`--profiles 400`, and also for an explicit mapping whose counts agree (four channels at
`4` per visit x `100` repeats).
