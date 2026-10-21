# Multiplexed artifact verification (`acquire mpx-check`, `record-multiplexed`)

`acquire mpx-check` verifies one **already-stored** multiplexed `.BDD` against the
operator's completed-block declaration. `acquire record-multiplexed` runs the same
check automatically on the file its own store just produced. Both are offline from
the instrument's point of view: no window, no instrument, no network, and nothing
written. Both reuse the existing `io.load` decoder and the existing
`CompletedBlockDeclaration`; no word parser is added.

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

- **No ordering or rolling claim.** `sequential` is the decoded multiplexer-enable bit,
  not a channel order, and roll-over is a runtime option the file does not store. No
  round/visit/roll count is inferred from block numbering, timestamps or decode order.
- **Truncation is a count, not a corruption verdict.** The existing decoder keeps every
  complete block, so a truncated file decodes fewer profiles and is reported as a
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
