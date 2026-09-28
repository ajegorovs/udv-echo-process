# Emissions-control live commissioning (2026-09-28)

**Scope:** the four-job `run-plan --next` boundary pass that the emissions-control slice needed before
its instrument claims could be made — `e20-a` → `e64-a` → `e64-b` → `e20-b`. This is a **control-path
acceptance**, not a claim about signal quality: nothing here measures the *effect* of emissions per
profile on the UDV signal, which is the sparse plan's job. The running code was PR #44 head `085933da`,
executed **one job per invocation** with `--next`, an absolute `--store-dir` naming the directory the
application's own Store dialog reports, and **no emissions value set by hand at any point** — every value
in the history below was established by the automation itself.

| Step | Job | Requested emissions | Write spent | Durable mutation | Stored word 14 | Stored word 8 | Stored word 27 |
|---|---|---|---|---|---|---|---|
| 1 | `e20-a` | 20 | **no** — the column already read 20 | — | 20 | 10 | 1 |
| 2 | `e64-a` | 64 | yes | `0f84965c8a0b40dab89666e83c3ea70b` — verified `20 → 64` | 64 | 10 | 1 |
| 3 | `e64-b` | 64 | **no** — the column already read 64 | — | 64 | 10 | 1 |
| 4 | `e20-b` | 20 | yes | `ea00225994ec479ea18aa78daec606c2` — verified `64 → 20` | 20 | 10 | 1 |

Each job's accumulated `parameter_mutations` contained **exactly one** entry when it spent a write
(`e64-a`, `e20-b`) and **none** when the requested value was already in place (`e20-a`, `e64-b`); the
pass row copies that history. Each entry carries the requested value, the *writer layer's own read-back*,
the *independent fresh read* of the parameter column, and state `verified`; the event is appended to the
job's log **before** the job's own compile/record records, so the log's first line is the mutation.

**The instrument began the sitting at E20**, read from its own painted parameter column at ×6 glyph
level. There was therefore **no initial-state-establishment transition** — no `X → 20` to keep and label,
and no value was touched to manufacture one. The consequence for reading §6's table is worth stating: its
`e20-a` row describes the write branch, and on this instrument `e20-a` instead exercised the
**equal-value** branch — the boundary read 20, spent no write, appended no event, and still stored a file
whose word 14 is 20. The durable history opens with `e64-a`'s `20 → 64`, which is the first thing the
sitting was asked to prove.

Across the sitting: the two mutation ids are **distinct** (`0f84965c…` at 17:35:51, `ea002259…` at
17:38:17) and in occurrence order; `e64-b` added **no** mutation; both transitions are `verified`; the
final fresh compile against the live screen sees `emissions_per_profile` = **20**, `source: read`, every
fact agreeing; no unexpected modal or overlay was seen, and every point log marks the stored verdict
`ok` with `sound_speed_ms`, `prf_us`, `burst_length` and `emissions_per_profile` enforced and no failure
or advisory.

Every stored file's **word 14 equals the emissions its own job requested** (20 / 64 / 64 / 20). **Word 8
(burst) is 10 in all four**, and the artefacts' decoded configurations are identical apart from the
requested axis — the hold is a property of the stored files, not an assertion: same PRF 600 µs, sound
speed 1480 m/s, 50 gates at 1.850 mm resolution, Doppler angle 0, uniform TGC ≈20 dB, emitting power and
sensitivity medium, gate 1 at 10.138 mm, and `sampling_volume_mm` null. **Word 27 is `1` in every file**,
as in every committed B4/B5 recording: receiver-bandwidth-definition provenance, **never** converted into
a physical sampling volume (the decoded `sampling_volume_mm` stays null, by design, in all four).

The app clipped the pointer while its Operating-parameters dialog was open and the driver released that
clip with `ClipCursor(NULL)` on each write; that is the documented, intended handling of a measured
behaviour, not an anomaly, and it did not alter the fact that the post-write read is independent.

The `plan/` directory is the **actual portable plan and job definitions used**, copied from the live
scratch location without machine-local paths; its fingerprint is
`33314c215720bbbb5b34d02ca858f1b9f8198eff62e024905126d2b0a1d13027`. The `records/` directory is the
**runtime JSONL of each job as the run wrote it**, sanitized by exactly one rule: every record's
`file_path` value replaced with the repo-relative `outputs/live/store/<name>`. The substitution is
asserted at build time by re-parsing the raw and sanitized forms of every line and comparing every key,
so a record is never reinterpreted — and it makes the **emitted event order portable**: the mutation is
each writing job's first record and its point record follows it, checkable from the committed bytes
rather than from this summary.

`manifest.json` is a **derived, path-sanitized evidence summary**, not the unmodified runtime manifest:
it carries the four jobs' definition fingerprints, their post-transition compile identity, the structured
mutation objects, each job's records-file SHA-256 (over LF-normalized bytes) and line count, the original
runtime-manifest/log SHA-256 values, and each BDD's SHA-256, requested values, decoded configuration and
point label. The unmodified runtime manifests and logs remain in the local `outputs/live/store/` and
contain absolute machine paths, so they are not committed — which leaves exactly one thing the package
cannot demonstrate from itself: that the committed records are byte-identical to those runtime logs. The
recorded original hashes are that link's only trace; the plan, the records, the summary and the BDDs can
all be checked against each other.

Reproduce without instrument access:

```bash
uv run --no-sync python data/emissions-control-live-1/verify.py
uv run --no-sync python data/emissions-control-live-1/mutation_proof.py
uv run --no-sync udv-acquire run-plan --plan data/emissions-control-live-1/plan/run-plan.json --check
```

**What `verify.py` does and does not prove.** It **re-derives**, from the committed files alone: the plan
fingerprint; the four executed jobs' definition fingerprints, conditions and point lists; **the emitted
event order** from `records/` — which jobs appended a `parameter_mutation` and which appended none, that
the mutation is the log's first record and precedes its point record, that it is `verified` with the
writer's own read-back *and* the independent fresh read, that it is stamped before the store it precedes
and inside the job's reported window, and that its definition fingerprint is the committed plan's own
fingerprint for that job; and every recording's SHA-256, size, stored operation words and decoded
configuration. So the BDDs, the records, the summary and the committed plan are tied together, and the
accepted properties are asserted directly (word 14 per job against *each job's own request*, the held
fields identical, the no-write jobs carrying no event at all, the two ids distinct and ordered). It
**cannot** re-derive that the committed records are byte-identical to the runtime logs (those stay
local) or the compilation identities (which live in the runtime job manifests); for those the summary's
recorded original hashes are provenance. Wherever the summary carries a claim this file can check
against the records, the plan or the recordings, it is checked rather than trusted.

**What `mutation_proof.py` does.** It applies each perturbation to a *copy* of the package and requires
`verify.py` to fail on it — the emitted event order reversed, the verified transition dropped, duplicated,
relabelled to another job or fabricated for a no-write job; the plan's definition fingerprint moved; a
stored recording's byte flipped; and the summary contradicting the records or the files — then requires
the untouched package to pass. A verifier that cannot fail proves nothing.

**Stop point:** the pass is **complete — 4/4 jobs and 4 recordings**, the plan's whole point list. The
application was left on its ready measurement screen at emissions 20, burst 10, channel 1. Two of the
four boundaries spent a write and two spent none, so the equal-value/no-write path — **offline-verified
only** when B5's review accepted that boundary — is now exercised live, twice, with the history retained
and no duplicate event. What this does **not** show: that the stored measurements are scientifically
sound, or what emissions per profile does to the signal; and as in B5, the committed BDDs rule out
changes to their decoded fixed settings, not changes to unreadable UI fields. The B4 second-hidden-
dependent-effect stop rule remains in force.
