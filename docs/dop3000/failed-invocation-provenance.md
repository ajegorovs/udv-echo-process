# Design — durable provenance for a mutation in a refused invocation

**Status: proposal only.** No file under `src/`, `tests/` or `acquire/` changes on this branch.
The gap is stated with `path:line` evidence read from merge commit `7209609`; every option is
written down with what it buys, what it costs and what it cannot guarantee, and one is
recommended for review **before** any code is written.

**Framing, and it decides where this work belongs:** this is an acquisition
**transaction/audit** question. It is not a `word 8` / `word 27` interpretation question, and it
is not part of the stored-artifact verification slice — [`burst-length-control-plan.md`](burst-length-control-plan.md)
§B6 stays exactly as it is.

---

## 1. The gap, with the evidence

The boundary runs `write → verify → compile → record`
([`burst-length-control-plan.md`](burst-length-control-plan.md) §1). The write is real the moment
the application accepts it; the durable record of it is written at the **end** of the invocation.
Anything that refuses in between loses the record of a mutation that already happened.

The sequence, as the code orders it:

| # | step | where | durable effect |
|---|---|---|---|
| 1 | static plan — pure, touches no instrument | `acquire/campaign.py:1574` | none |
| 2 | the resume's **definition** proof — a pure refusal | `acquire/campaign.py:1581`, refusal at `:1778` | none |
| 3 | route the channel, read the dialog, take the reading | `acquire/campaign.py:1611`, `:1614`, `:1615` | channel routing may write (§6) |
| 4 | the mode rung — a **pure** refusal, before any write | `acquire/campaign.py:1624` | none |
| 5 | **the boundary write** | `acquire/campaign.py:1630` → `:1368`; driver transaction `acquire/udop/parameters.py:642` | **the instrument is moved** |
| 6 | re-read the dialog and the reading (the post-write state) | `acquire/campaign.py:1636`, `:1637` | none |
| 7 | **the post-write compile** — its refusal propagates untouched | `acquire/campaign.py:1644`; entry `:931`; a refusal e.g. `:1292` | none — no manifest is written |
| 8 | **the resume identity** — `_validate_resume` raises | `acquire/campaign.py:1655`, refusal at `:1868` | none — no manifest is written |
| 9 | run the points; one log entry per point, valid or not | `acquire/campaign.py:1711`; `acquire/runner.py:1015` → `acquire/log.py:432` | the log, append-only |
| 10 | **the job manifest is written** | `acquire/campaign.py:1752` (`write_manifest` `:721`, path `:716`) | `burst_transitions` |
| 11 | the pass row is folded in and the pass record rewritten | `cli.py:1216`, `:1217`; `acquire/run_plan.py:1624`, `:1807` | the pass row |

The smallest decisive fragment for each claim.

**The boundary write** — `acquire/campaign.py:1368`:

```python
result = actuator.write_dialog_burst_length(requested, routed_channel=routed)
```

**The pure refusals come before it** — the two that read only the reading, the definition and the
previous manifest, and therefore precede the write by construction. `acquire/campaign.py:1581`:

```python
previous = _previous_manifest_for(definition, log) if resume else None
```

and `acquire/campaign.py:1624`, immediately before the write call at `:1630`:

```python
refuse_process_mode(snapshot, expected_mode)
```

**The post-write compile refusal** — `acquire/campaign.py:1644`, after the write and *before*
the runner exists (`:1695`) and the manifest is written (`:1752`):

```python
compiled = compile_campaign(definition, snapshot, strict_facts=strict_facts)
```

**The resume-identity refusal** — `acquire/campaign.py:1655`, in the same position; the raise is
`acquire/campaign.py:1868`:

```python
unproven_resume = _validate_resume(
```

**Where the job manifest is written** — `acquire/campaign.py:1752`, the only `write_manifest`
call on the run path, after the runner has returned (`:1711`):

```python
write_manifest(manifest_path_for(log), manifest)
```

**Why nothing is recovered afterwards.** The next invocation seeds its history from the manifest
*before* it gestures at anything — `acquire/campaign.py:1589`:

```python
carried_transitions: tuple[BurstWriteResult, ...] = (
    () if previous is None else previous.burst_transitions
)
```

and appends only its own transition — `acquire/campaign.py:1680`:

```python
burst_transitions: tuple[BurstWriteResult, ...] = (
    (*carried_transitions, transition) if transition is not None else carried_transitions
)
```

The refused invocation wrote no manifest, so `previous` is the **earlier** invocation's manifest
and the refused transition is in no source the accumulation reads. On the pass's own record the
copy is equally blind — `acquire/run_plan.py:1698`:

```python
burst_transitions=_accumulated_transitions(
    record.burst_transitions, job_manifest.burst_transitions
),
```

### 1.1 The partial mitigation already in place, and its exact scope

The refusals are worded so they do not claim the application was untouched, and the two scopes are
different on purpose:

- the **compile** refusal names only what the compile did — `acquire/campaign.py:1293-1296`:
  *"…so nothing was stored and no point was recorded (the compile writes nothing to the
  instrument; a burst transition at the job boundary, if the job needed one, is the only write
  this refusal can follow)"*;
- the **resume-identity** refusal is scoped to the points — `acquire/campaign.py:1870`:
  *"No point of this job was run and nothing was stored."*

The same limitation is already written down as a **pending limitation** on the B5 slice
([`burst-length-control-plan.md`](burst-length-control-plan.md) §B5, the paragraph beginning
*"Pending limitation — a verified write in an invocation that never reaches the manifest…"*).
This document is the authority for that gap; the plan points here rather than restating it.

---

## 2. What is truly lost, and what is merely inconvenient

**Truly lost — durable evidence of a real mutation.** For an invocation that performs a verified
boundary write and is then refused, no artifact in the tree records the move:

- the **job manifest** is not rewritten (it is written only at `acquire/campaign.py:1752`);
- the **pass row** is not rewritten either, because the pass record is only updated after
  `run_campaign` returns (`cli.py:1216-1217`) and the refusal is raised out of it (`cli.py:1219`);
- the **next invocation cannot recover it**, because the accumulation reads the earlier manifest
  (`acquire/campaign.py:1589`);
- and there is **no other durable artifact**: the run's `notes` are an in-memory list printed at
  the end of the CLI call (`cli.py:1529`, `:1627-1628`), and the driver writes no log at all — its
  transaction *returns* the evidence (`acquire/udop/parameters.py:642`, model at
  `acquire/actuator.py:602-657`).

So the instrument was moved, the move was verified, and the record of the pass says it was not.

**Merely inconvenient, and not this gap.**

- **The notes being caller-owned.** A note was never the record; the manifest and the pass row
  are. A caller-owned list that a caller may print is not a weaker record than a caller-owned
  list that a caller may write to a file — neither is claimed as durable here.
- **The job log holding no entry for a refused invocation.** The log holds a *header* and *point
  records* (`acquire/log.py:413-418`: the entries are `SweepLogHeader | SweepPointRecord`), and a
  refused invocation has no point. Losing no point record gives up nothing: the log is complete
  about what it is for.
- **The `UNCHANGED` / `UNVERIFIED` outcomes.** Neither kept anything
  (`acquire/actuator.py:586-594`), so neither is a mutation that needs a record; the refusal that
  raises on them (`acquire/campaign.py:1369-1419`) already names the state and the reason.

**Unestablished, and deliberately not assumed.**

- **Whether an append is durable across a crash.** `acquire/log.py:440-442` opens the file in
  append mode (`"a"`) and closes the handle, so the bytes reach the operating system; no `fsync`
  is performed anywhere in the module, and what survives a power loss is a property of the
  platform this repository does not establish. Every option below shares this limit.
- **Whether the CLI's `note:` stream is kept.** `cli.py:1627-1628` prints to a stream; whether a
  shell, a log collector or an operator retains it is outside the repository.

---

## 3. Options, with their honest costs

| | covers | new durable artifact | covers channel routing / the standalone verb | resume + accumulation impact |
|---|---|---|---|---|
| **O1** write-ahead note before the write | the crash during the write, too | yes (a sidecar file) | no | moderate — an outcome half must be reconciled with the intent |
| **O2** a manifest on the refusal path | the stated gap | no | no | **high** — the resume's proof artifact is written on a path where the job did not run |
| **O3** a separate pipeline-wide mutation journal | every mutation on every path | yes (a journal) | **yes** | moderate — the accumulation must prefer the journal |
| **O4** the verified transition in the job's own log | the stated gap | no — the log already exists | no | moderate — one more source in the accumulation |
| **O5** documentation only | nothing | no | no | none |

### O1 — a write-ahead note beside the job log, written before the write

Append an *intent* record (job, definition fingerprint, the requested burst, the burst the dialog
stated, the routed channel, the moment) to a file beside the job log **before**
`write_dialog_burst_length` is called, and append or rewrite the outcome after it returns.

- **Buys:** the only option that covers the window in which the process dies *during* the write —
  the intent is durable before the mutation, so a trace naming a possible move exists even then.
- **Costs:** two writes per transition, and an artifact a reader must handle in a state that means
  nothing on its own: a request that was never sent (the row did not offer it, the dialog was
  another channel) leaves an intent that is *not* evidence of a move, and a reader who takes it as
  one is worse off than with no record. It needs a defined lifecycle (when is an intent retired?)
  and a rule for an intent whose outcome disagrees with the pre-write read.
- **Cannot guarantee:** what the application kept — only the outcome half states that.
- **Requires of the resume/accumulation:** nothing, if the outcome half is the half folded in; but
  two sources for one fact then have to be reconciled, because the intent is not a transition.

### O2 — write a job manifest on the refusal path

Catch the compile refusal (`acquire/campaign.py:1644`) and the resume-identity refusal (`:1655`)
inside `run_campaign` and write a manifest before re-raising.

- **Buys:** the existing type and the existing read (`acquire/campaign.py:1589`), so the *next*
  invocation recovers the transition with no new reader and no new artifact.
- **Costs:** `JobManifest` is the resume's **proof artifact**, not a log. `_validate_resume` reads
  `compilation_identity` off it (`acquire/campaign.py:1848`), `_previous_manifest_for` refuses on
  its fingerprint (`:1777`), and the pass row is built from its counts (`acquire/run_plan.py:1712`,
  `:1675-1701`). A manifest written on a refusal path has to state something about a job that did
  not run: it carries `planned`, `skipped` and `outcomes`, and a manifest with no outcomes and
  `planned > 0` reads as `FAILED` (`acquire/run_plan.py:1722`) — a statement about the job that the
  refused invocation never made. The refusal is also raised from *inside* `run_campaign`, so a
  handler is needed at each refusal site, and the driver's `AcquisitionError` from a non-verified
  transition (`acquire/campaign.py:1369`) must stay outside it.
- **Cannot guarantee:** that the manifest it writes is the artifact the job would have had. It is
  a partial record whose status field means something stronger than "this invocation was refused".
- **Requires of the resume/accumulation:** a rule distinguishing a refusal record from a job
  manifest, and a revision of the identity comparison, which reads the previous manifest.

### O3 — a separate append-only mutation journal for the whole acquisition pipeline

One file, one entry per instrument mutation, appended by the writer at the moment of the write,
independent of the job and pass structure.

- **Buys:** the strongest audit position and the shape that matches the framing of this problem
  most directly. It covers *every* mutation on *every* path — including the channel routing write
  (`acquire/campaign.py:1611` → `acquire/udop/parameters.py:467`) and the standalone
  `uv run udv-acquire burst-length` verb — and a later manifest rewrite cannot lose it.
- **Costs:** a new durable artifact with its own path, ownership, rotation and reader; on the
  normal (non-refused) path it records a fact the job manifest already holds, so the two records
  of one transition have to be reconciled; the natural home is the store directory, which would
  make the journal span jobs where every other record is per-job.
- **Cannot guarantee:** anything beyond the flush limit in §2, and it says nothing about *which
  job* a mutation belonged to unless each entry carries the job name and the definition
  fingerprint.
- **Requires of the resume/accumulation:** the journal to be preferred over, or merged with, the
  manifest's `burst_transitions`, with a dedupe rule; and a decision on the journal's path and
  lifetime that no existing document makes today.

### O4 — record the verified transition in the job's own log, at the boundary *(recommended)*

Add one append-only entry type to the log the run already writes, and append the verified
transition **immediately after the write, before the compile and the resume comparison**.

- **Buys:** the durability property with **no new artifact, no new path, no new ownership
  question**. The log is already append-only (`acquire/log.py:432`), already per-job, already
  beside the manifest, and already read on a resume (`acquire/campaign.py:1652` →
  `recorded_points`). The entry is appended before `acquire/campaign.py:1644` and `:1655`, so a
  refusal at either cannot lose it, and a reader of one job's directory finds the move in the file
  that already answers "what happened in this job".
- **Costs:** it **widens the log's schema**. `SweepLogEntry` is
  `Annotated[SweepLogHeader | SweepPointRecord, …]` (`acquire/log.py:413-418`), and every existing
  reader of that union must ignore the new member (`point_records` `acquire/log.py:463`,
  `point_names` `:468`); the discriminator's policy decides whether a log written by a newer build
  is *refused* by an older one, or read as far as it understands — that has to be chosen, not
  inherited. One transition now has two records (the log entry and the manifest field), which need
  a dedupe rule. And it does not cover a mutation made by a verb that writes no job log.
- **Cannot guarantee:** the flush limit of §2, shared with every option; and it does not by itself
  cover the channel routing write or the standalone `burst-length` verb (§6).
- **Requires of the resume/accumulation:** the accumulated history to be assembled from **three**
  sources — the previous manifest (`acquire/campaign.py:1589`), the log's own mutation entries, and
  this invocation's transition (`:1680`) — with a dedupe key; and `_accumulated_transitions`
  (`acquire/run_plan.py:1725-1739`) to be told that a row's history may now include entries no
  manifest ever carried.

### O5 — do nothing beyond widening the documentation

- **Buys:** nothing costs nothing, adds no failure mode, and is honest: what is claimed stays
  exactly what is true.
- **Costs:** the durable record of a real mutation stays absent, and the next reader of the pass
  still cannot see the move.
- **Cannot guarantee:** anything about the move.
- **Requires of the resume/accumulation:** nothing.

---

## 4. Recommendation

**O4 — record the verified transition in the job's own log at the boundary** — with an O5-grade
statement retained for what O4 does not cover (the standalone `udv-acquire burst-length` verb and
the channel routing write; see §6).

**Why O4 and not O3.** O3 is the better long-term shape *if* instrument mutations multiply. Today
the pipeline makes exactly one job-level burst mutation, so a journal would be a second durable
artifact recording one fact that an existing artifact can already carry, plus a path/ownership
question that nothing in the tree answers yet. O4 buys the same durability for the stated gap with
the smallest possible surface: one entry type on an existing append-only file, and one extra read
of that file.

**Why O4 and not O2.** O2 writes the resume's *proof artifact* on a path where the job did not run,
and both the identity comparison and the pass row read that artifact. A refused invocation that
later reads as a `FAILED` job is a correctness problem, not a record-keeping one.

**Why not O1.** O1 is the only option that covers a crash *during* the write, and the gap stated
here is *after* verification. Adopting it means two writes per transition and a reader rule for
intent-with-no-outcome. The recommendation is O4 now, with the crash window recorded as an explicit
limit of O4 rather than silently claimed closed.

**Evidence balance, stated plainly.** The evidence for O4 being *implementable* is strong: the log
is append-only, per-job, beside the manifest, and the append point (`acquire/campaign.py:1630-1644`)
is decisive in the code. The evidence for O4 being *sufficient* is weaker than for O3 in exactly one
place — O4 covers the burst boundary write and not every mutation — and that is why §6 lists the
uncovered writers rather than claiming a complete trail.

---

## 5. Implementation sketch (no code is written on this branch)

### 5.1 Where the append goes

Inside `run_campaign`, between the verified transition and the compile:

```text
acquire/campaign.py  run_campaign
  transition = _transit_burst_length(...)        # :1630 — the write, unchanged
  if transition is not None:
      append the mutation entry to `log`         # NEW — before :1644 and :1655
      dialog, snapshot = ... re-read ...         # :1636-:1640, unchanged
  compiled = compile_campaign(...)               # :1644 — may still refuse; the entry is durable
  ...
  unproven_resume = _validate_resume(...)        # :1655 — may still refuse; the entry is durable
```

The append uses the function the runner already uses (`log.append_entry`, `acquire/log.py:432`) and
the path `run_campaign` already holds (`log`), so there is one append path, one JSONL file per job,
and no new directory question.

**Open question in the sketch, and it must not be swallowed:** a boundary append that *fails* leaves
exactly the gap this document is about. The runner's own rule is a `log_errors` list that never
fails a point (`acquire/runner.py:1026-1030`), but that list only reaches a reader through the
manifest — which the refused invocation does not write. The implementer must choose between
surfacing it on the returned/raised refusal (so it is visible at the moment it happens) and
accepting a silent hole of a narrower kind, and must document the choice.

### 5.2 What the new record contains

One new `SweepLogEntry` member in `acquire/log.py`:

| field | source | why it is there |
|---|---|---|
| the `BurstWriteResult` verbatim | `acquire/campaign.py:1630` | the **evidence**, not a boolean: request, state, `dialog_mode`, `channel`, both rows on both sides of the write, `refusal_overlay`, `discarded`, `reason` (`acquire/actuator.py:602-657`) |
| the job name | `definition.job` | which job's boundary moved the dialog |
| the definition fingerprint | `campaign_fingerprint(definition)` | attribution without the manifest |
| the routed channel | `acquire/campaign.py:1611` | the result carries the dialog's own channel field; the routed channel is what the boundary verified against (`acquire/campaign.py:1377`) |
| the moment | `_local_now` | when the move happened, not when the invocation ended |

Only a `VERIFIED` transition is appended. `UNCHANGED` and `UNVERIFIED` kept nothing
(`acquire/actuator.py:586-594`) and must never be recorded as a mutation.

### 5.3 How it interacts with the accumulated `burst_transitions` history

Three sources, oldest first, into one list:

1. **the previous manifest's history** — `acquire/campaign.py:1589`, unchanged;
2. **the job log's mutation entries** — NEW: read beside the manifest in the same step, so a
   refused invocation's transition is recovered;
3. **this invocation's own transition** — `acquire/campaign.py:1680`, unchanged.

Rules the implementer has to state and test:

- **On the job manifest.** The manifest stays the authority for a history it already carries; the
  log is the authority for entries no manifest ever carried. A dedupe key has to be named (the
  request plus the before/after row texts plus the state is the natural one) so that the normal
  case — the transition is in both the manifest and the log — appears once.
- **On the pass row.** `_accumulated_transitions` (`acquire/run_plan.py:1725-1739`) merges the
  row's carried history with the job manifest's; it needs to know that the manifest's list may now
  include entries recovered from the log, or it will report them as this invocation's own.
- **On the row's `note`.** `_job_note` currently distinguishes "N added by this recording" from
  "none added by this recording (carried from earlier invocations)"
  (`acquire/run_plan.py:1765-1780`). With a log source, "added by this recording" can be **false**
  for an entry recovered from a refused invocation, so the sentence needs a third case, or the
  history needs to name each entry's source.
- **No new field on the pass row** is required: `RunJobRecord.burst_transitions`
  (`acquire/run_plan.py:880`) already carries the ordered history and the copy already exists.

### 5.4 Tests that would have to be added

- `tests/test_acquire_log.py` — round-trip of the new entry type; `point_records` and
  `point_names` ignore it; the discriminator policy for a log carrying an entry an older build does
  not know.
- `tests/test_acquire_campaign_burst.py` — a verified transition followed by a **compile** refusal
  appends exactly one mutation entry and writes **no** new manifest; the same for a
  **resume-identity** refusal; `UNCHANGED` / `UNVERIFIED` append nothing; the next invocation folds
  the log entry into `burst_transitions`; no duplicate when the manifest already carries it; a
  manifest that predates the log entry; the append-failure path of §5.1.
- `tests/test_acquire_run_plan.py` — a pass row for a job whose invocation was refused shows the
  recovered transition; a resumed row does not duplicate it; the `note`'s third case.
- If the standalone verb is covered later (a separate decision): `tests/test_acquire_live.py` for
  `uv run udv-acquire burst-length`.

All of them run headless against the fakes; none needs the instrument.

---

## 6. Out of scope, and what this document does not claim

- **Nothing is implemented here.** No change to `src/`, `tests/` or the `acquire` package is part of
  this branch, and none should be read into it.
- **No claim of a complete audit trail** until a mechanism lands. O4 closes the gap for the
  job-level burst transition. It does **not** close it for:
  - the **channel routing write** — `acquire/campaign.py:1611` → `acquire/udop/parameters.py:467`,
    which writes only when the requested channel differs from the instrument's; a refusal after it
    (the mode rung at `:1624`, or the compile) leaves the channel moved and unrecorded, and the
    channel only reaches a record inside `compilation_identity` on the manifest
    (`acquire/campaign.py:1848`);
  - the standalone `uv run udv-acquire burst-length` verb, which has no job log to append to.
  Each is its own decision.
- **No claim of durability across a power loss.** No option here adds a flush or an `fsync`;
  whether the log's append survives a crash is unestablished (§2).
- **No claim about a crash during the write itself.** That window is O1's; closing it is a second
  decision, not part of this one.
- **Not a `word 8` / `word 27` question.** This is transaction/audit ordering.
  [`burst-length-control-plan.md`](burst-length-control-plan.md) §B6 remains the authority for
  stored-artifact verification and is untouched by this proposal.
- **No change to the driver.** The driver returns its evidence and writes no log
  (`acquire/udop/parameters.py:642`); a driver-level log is not established as a durable place and
  none is proposed.
- **No half-landed journal.** If the reviewer prefers O3's shape, that is a different proposal —
  it should land as one, not as an O4 that happens to be named after a journal.

---

## 7. Re-checking the evidence in this document

The line numbers are from merge commit `7209609`. Each claim can be re-checked directly:

```bash
git grep -n "write_dialog_burst_length(requested" -- src/udv_echo_process/acquire/campaign.py
git grep -n "refuse_process_mode(snapshot" -- src/udv_echo_process/acquire/campaign.py
git grep -n "_previous_manifest_for(definition, log)" -- src/udv_echo_process/acquire/campaign.py
git grep -n "compiled = compile_campaign" -- src/udv_echo_process/acquire/campaign.py
git grep -n "unproven_resume = _validate_resume" -- src/udv_echo_process/acquire/campaign.py
git grep -n "write_manifest(manifest_path_for" -- src/udv_echo_process/acquire/campaign.py
git grep -n "No point of this job was run" -- src/udv_echo_process/acquire/campaign.py
```
