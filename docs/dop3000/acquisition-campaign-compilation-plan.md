# Plan — compile campaigns against live instrument state (the review's Phase 6)

**Status: plan only. Nothing in this document is implemented.**
It is the first commit of the PR that carries it, which is the branch the implementation
continues on. The slice before it — the acquisition correctness baseline — is merged
(`262b6ea`, PR #2), and its decision record is
[`acquisition-review-and-verdict.md`](acquisition-review-and-verdict.md), whose §6 Phase 6
and §7a–§7b are the authority for what follows. The two reviews of that slice are the
source of the carried-forward items in W5 and W6.

## 1. The goal

Today a campaign is a JSON definition that **describes** the instrument, and the only
check that the instrument actually was in that state happens *after* the file is stored,
when `verify_stored_point` compares the stored words against the request. A campaign can
therefore spend live recordings on an instrument configured differently from its own
declaration, and nothing notices until each point is refused — or, for word 14, notices
only as an advisory.

The end state this plan works toward:

```
CampaignDefinition                (what the experiment wants)
        |
        v  static validation        plan_campaign() — pure, unchanged
        |
        v  UDOP session snapshot    read the instrument: layout, channel, mode, settings
InstrumentSnapshot                (what the DOP3010 actually is, right now — evidence)
        |
        v  identity                 the stable projection of that reading, and only it
CompilationIdentity               (what a resume may compare; volatile UI facts excluded)
        |
        v  compile                  reconcile the two, or refuse
ExecutableCampaign                (per-point expectations + fixed configuration + policy)
        |
        v  for each point           reset → apply → readback → acquire → store
        |                           → canonical decode → acceptance → durable record
        v
    (Phase 7 owns the certificate; this plan leaves the seams for it)
```

Phase 6 is the box between "static validation" and "for each point": **the snapshot, the
reconciliation, and the refusal before the first recording.** It is the largest remaining
item of the review's roadmap that is not decomposition, and it is what makes the
scientific claims (what stayed fixed) checkable rather than declared.

## 2. Current state — verified, with pointers

What happens on a campaign run today (`campaign.run_campaign`, `campaign.py:640`):

1. `plan_campaign(definition)` (`campaign.py:522`) validates and expands the points —
   pure arithmetic from the JSON, no I/O.
2. The store directory, the log path and the effective channel are resolved; the channel
   is range-checked (`MIN_CHANNEL..MAX_CHANNEL`) but **not read from the application**.
3. `resume` drops the points the log already holds as successful, keyed by
   `record_identity` (`campaign.py:432`).
4. `SweepRunner` (`runner.py`) runs each remaining point: it verifies the channel once per
   run (`runner.py:323`, through `ensure_channel`), resets the block, applies the window,
   reads it back, records, stops, stores, decodes the stored file, sizes it, verifies its
   words and appends the log entry — valid or not.
5. `JobManifest` (`campaign.py:362`) is written with
   `fingerprint=campaign_fingerprint(definition)` (`campaign.py:470`) — a hash of the
   **definition**, so two runs of one definition on two differently-configured instruments
   are indistinguishable in the record.

The facts that gap leaves:

- **The declared fixed facts are never read.** `CampaignDefinition` (`campaign.py:201`)
  requires `prf_us` and `emissions_per_profile`, optionally `burst_length`, and declares
  `max_profiles_per_block`; its own docstring says of the cap "State it explicitly and
  check it against the instrument" — and no code does. The published evidence for the cap
  is that the tested install accepted `1000000` while the block was measured to stop at
  ~257 profiles (docs/16 §15b, `handoff-dop3010-acquisition.md` §4).
- **Most of them cannot be read through the existing roles.** `ParamRole`
  (`actuator.py:107`) covers `us_frequency`, `prf`, `gates`, `resolution`,
  `velocity_scale_factor`, `emissions_per_profile`, `doppler_angle`. Sound speed, first
  gate and burst length are **not** roles — so of the campaign's fixed facts only PRF and
  emissions are readable today, through `read_parameter`.
- **The port does not expose the screen.** `Actuator` (`actuator.py:398`) has eleven
  primitives (`layout_note`, `read_parameter`, `write_parameter`, `strip_state`,
  `wait_for_view`, `press`, `answer_overlay`, `set_store_name`, `commit_store`,
  `wait_for_stored_file`, `record_and_store`); `SweepActuator` (`runner.py:180`) adds
  `apply_point`, `ensure_channel` and `try_record_and_store`, and the runner casts to it
  (`runner.py:303`). `screen_fingerprint()` (`driver.py:2245`) and `preflight()`
  (`driver.py:2315`) are **driver-only** and called directly by `live.py` — which is why
  the run record cannot carry a `ScreenFingerprint` today. `ScreenFingerprint` already
  says it "belongs in the job log beside the point it preceded" (`actuator.py:306`) — but it
  is **evidence, not identity**: of its twelve fields (`class_name`, `hwnd`, `rect`,
  `maximized`, `screen`, `panels`, `visible_controls`, `strip`, `overlay`, `layout_note`,
  `cursor`, `is_foreground`), six are session-volatile (`hwnd`, `rect`, `maximized`,
  `screen`, `cursor`, `is_foreground`), and an HWND changes on every UDOP restart. Hashed as
  it stands, a restarted but identically configured instrument would read as a different
  instrument (W2).
- **The channel mode is known to the driver but not to the campaign.** Assisted-mode
  channels show 21 controls in 3 panels against the clean 43 in 4
  (`ScreenFingerprint`'s docstring), the driver records which mode a channel's dialog
  showed (`driver.py:2103`), and nothing refuses a manual-mode campaign against an
  assisted channel before recording.
- **The period law uses the plan's emissions.** `_profile_period_s` (`campaign.py:910`)
  and the runner's law are fed `emissions_per_profile` from the definition; the committed
  point is the case where that declaration is wrong (plan 52, file 150), so `timing.
  target_s` is 0.0098 s against a measured 0.030007 s.

## 3. Acceptance criteria for this slice

Checkable, and each becomes a test:

1. A campaign aimed at an instrument whose configuration contradicts it **refuses before
   the first recording**, naming the fact that disagreed, with no file stored and the
   application left in a clean state.
2. A run record can answer, offline: which channel and mode were active, which fixed facts
   were **read from the instrument**, which were only declared, and what the compiled plan
   asked for.
3. The compiled plan is deterministic and hashable **on a stable projection of the
   snapshot, not on the raw reading**: two snapshots that differ only in session-volatile
   diagnostics — a new `hwnd` after a restart, the cursor, `is_foreground`, window geometry
   — compile to the **same** identity, while a change to any fact that campaign
   compatibility depends on (channel, mode, PRF, emissions, burst, sound speed, first gate,
   the cap and its provenance, the layout signature) compiles to a **different** one. A
   resume must be able to tell a configuration change from a restart.
4. Nothing in the acquisition path claims an instrument fact that was not read: an unread
   fact is `None` or explicitly `declared`, never presented as verified.
5. **No recipe changes.** With the instrument in its expected configuration, the stored
   files, their names and the log entries are what they were before this slice. No Win32
   gesture is re-derived (verbatim-port rule), and no existing test changes for a reason
   other than the seams this plan adds deliberately.
6. **A job that predates this slice cannot silently resume.** Every pre-existing manifest
   carries a definition fingerprint and no compilation identity, so compatibility cannot be
   demonstrated for any of them; the new resume refuses by default, proceeds only under an
   explicit declaration-only flag, and marks the decision on the manifest and on every point
   it skipped that way. No point leaves the todo set on the strength of an unproven
   identity.

## 4. Work items

Each item states what changes, where, and what makes it done. Ordered so that the
independent reconnaissance (W1) never blocks the model work (W2–W4).

### The order, which is load-bearing

The steps are not commutative, and the plan has to say so, because the existing system
already *selects* a channel rather than merely reading one: `ensure_channel`
(`driver.py:2136`) opens `Operating parameters`, reads the channel, **writes the selection
if it differs**, accepts the dialog and reads it back from the re-opened one. The driver's
own contract says it is called before every point (`driver.py:2139`); the runner deliberately
calls it **once per run** instead (`_verify_channel_once`, `runner.py:323`), because nothing
inside a run changes the channel and re-opening the same modal once per point proved nothing
new. That once-per-run call is exactly where the snapshot belongs: after the routing, before
the first recording, and beside it in the record.

So the supported behaviour when a campaign targets channel 1 and the UI sits on channel 4
is to **select channel 1**, not to refuse. Establishing the target channel is a *routing*
action, not a silent change of a scientific setting: it is not the same thing as moving PRF
or sound speed, and the plan must not conflate them.

```
1.  load the definition            what the experiment wants
2.  static plan                    plan_campaign() — pure, touches no instrument
3.  establish the target channel    routing: ensure_channel() — writes only if it differs
4.  snapshot                       read that channel's fixed state (W2)
5.  compile                        reconcile definition against snapshot, or refuse (W3)
6.  validate the resume identity   against the previous manifest and log (W4)
7.  determine todo / skipped       only after 1–6 have agreed
8.  per point                      the existing cycle, unchanged
```

Steps 3 and 4 are separate on purpose. One combined "read the instrument" step would either
snapshot whichever channel happened to be open — and an assisted channel is a different
parameter surface entirely — or leave the plan unable to say whether the channel was *read*
or *changed*.

The repository already works this way one layer up: `live.select_channel()` (`live.py:69`)
returns `(verified, actuator.screen_fingerprint())` — the routing action and the read,
paired in that order, today.

The consequence for W2 is a wording that matters: `instrument_snapshot()` is read-only with
respect to the **configuration** — it writes no parameter, accepts no dialog, selects no
channel — but it runs *after* a step that did select one. The record must show both, and a
channel write at step 3 belongs in the run log beside the snapshot that followed it.

### W1 — Read the instrument's remaining fixed facts (reconnaissance, independent)

**What.** Establish where a running UDOP shows the sound speed, the first gate and the
burst length for the selected channel, and **expose a supported read path for each**. The
plan deliberately does not decide the abstraction before reconnaissance has seen the UI:
`ParamRole` (`actuator.py:107`) models the measurement screen's *parameter column*, so it is
extended **only** for facts that actually belong to that surface. A fact that lives inside a
dialog gets its own reader — whether that becomes a second role model or snapshot-local
readers is the reconnaissance's answer, not this plan's (D6). A fact that is not readable at
all is recorded as a fact about the instrument and left declared; do not invent a read.

**Where.** A probe under `tools/live/probes/` (the directory that exists for exactly what a
supported command does not cover) plus the manual corpus in `docs/dop3000/` for the
semantics. `PARAM_COLUMN_ORDER` (`actuator.py:126`) fixes a field's identity as its
top-to-bottom position, so a *column* role must be placed by evidence, never by guess.

**Done when.** The probe prints all five fixed facts from a running application, one
control-tree snapshot per screen state is committed as a JSON fixture (`tests/data/`), and
each newly readable fact has a named read path whose docstring says which screen it comes
from and which surface it belongs to.

**Settled by the review of P1 (§12):** the ready row's 3-vs-4 button count is the *buffer's* state
rather than the layout's, so it is not in the `CompilationIdentity` and this fixture is no longer
needed for that question. Re-open it only if reconnaissance finds the count encoding something
other than a leftover block — a count that changes the *view* still moves the identity, and that
is pinned by test.

**Risk.** Needs the live machine and the interactive session (`tools/live/README.md`). If
the machine is unavailable, this item waits and W2–W4 proceed with the three unreadable
facts explicitly marked unreadable — which is the honest state either way.

**Landed (§14).** Reconnaissance ran against the running application in simulation mode, and the
three facts turned out to be readable: they are stated in the ``Operating parameters`` dialog's own
value table, which the read opens through the routing step's gesture, binds **by position**, checks
against the screen's own seven shared facts, and closes again in a ``finally`` (Escape closes
nothing in this application — §14). The fourth fact, the block cap, is still `unreadable` with its
reason, which is the outcome this item allowed for: "a fact that is not readable at all is recorded
as a fact about the instrument and left declared; do not invent a read".

### W2 — `InstrumentSnapshot` (evidence) and `CompilationIdentity` (what a resume compares)

**What.** Two models, because two different questions are asked of the same reading.

*Evidence* — what the instrument is, kept whole, for diagnosis and for the record:

```python
def instrument_snapshot(self) -> InstrumentSnapshot:
    """Read the instrument's current state, pressing nothing that changes it.

    Read-only with respect to the configuration: it writes no parameter, accepts no
    dialog and selects no channel. Routing to the requested channel is a separate step
    that happens before it (W4), and is recorded as such.
    """
```

`InstrumentSnapshot` carries the `ScreenFingerprint` **as it is** — all twelve fields,
including the volatile six — because a fingerprint that has been trimmed is no longer the
diagnostic it exists to be. Plus the channel, the mode (`manual`/`assisted`), and every
fixed fact that was readable, each as an `InstrumentFact` — value *and* source (W5) — and —
as named fields, not omissions — the facts that were not readable.

`CompilationIdentity` is that same reading **projected onto the facts campaign compatibility
depends on**, and nothing else: no `hwnd`, no window geometry, no cursor, no foreground
state, no free-text layout note, no transient modal state.

| in the identity | why |
|---|---|
| channel, mode | a channel's mode is not a detail: an assisted channel has its own parameter surface entirely |
| every fixed fact with its provenance (PRF, emissions, burst, sound speed, first gate, the cap) | this is what "did we run the experiment we think we did" means |
| the layout signature: `class_name` + `panels` + `visible_controls` + `strip` | a changed layout means the reads themselves are suspect |
| the application's identity, where a read for it exists | a different build is a different instrument |

**`overlay` is deliberately not in the identity**: a modal being up is a precondition
failure — refuse (W3) — not a property of the instrument's configuration.

**A third case that is neither: a minimised window.** The counts are read through
`_visible_children` (`driver.py:420`), which filters on `win32gui.IsWindowVisible` — a Win32
style flag, and one that requires the window *and every ancestor* to be visible. A minimised
UDOP therefore reports **zero** visible controls in **zero** panels for its children. Left
alone, that would compile as an instrument whose layout differs and refuse — or resume — for
the wrong reason, with the wrong diagnosis. Zero counts are a precondition failure of the
same kind as a modal overlay: *the application is not showing its measurement screen.*

The same filter is what makes the counts usable in an identity at all: `IsWindowVisible`
plus a non-empty area of the control's **own** rect (`driver.py:427-429`) depend on neither
the window's position, its maximised state, the screen nor the foreground. The one residual
doubt is that area filter — a control the application collapses below 2px would drop out —
which is why W1 captures the counts restored **and** maximised rather than assuming.

Then one additive method on `SweepActuator`. It has the precedent for a composed call
(`try_record_and_store`, `runner.py:198`), and `Win32Actuator` already computes every piece:
`screen_fingerprint()` (`driver.py:2245`), the parameter column read that `ensure_channel`
performs, and the mode. `live.status()` and `live.select_channel()` (`live.py:64`, `:69`)
are the same composition at the live layer, running today — so the new part is the port
boundary and the models, not the gesture. It must be **additive**: no existing protocol
method changes signature, so every existing fake keeps working with one added stub.

**Where.** New `src/udv_echo_process/acquire/snapshot.py` (both models, the projection, the
reading helpers); one method on `SweepActuator` (`runner.py:180`) and its implementation in
`driver.py`; the port docstring says which facts are read and which are not.

**Done when.** A fake port returns a snapshot and both models round-trip through JSON; a
snapshot captured from the real machine parses as a committed fixture; a test asserts that a
fact that was not read appears as unread rather than as a value (criterion 4); and the
criterion-3 test passes in **both** directions — volatile-only differences compile to the
same identity, and every fact in the table above changes it.

### W3 — `compile_campaign(definition, snapshot) -> ExecutableCampaign`

**What.** The step the review asked for by name: reconcile the definition against the
snapshot and produce an explicit executable plan, or refuse. The compiled plan carries:

- the per-point expectations the static planner already computes (`PlannedPoint`,
  `campaign.py:275`);
- the **fixed configuration** as the snapshot read it, with each fixed fact marked `read`
  or `declared`;
- the acceptance policy, per fact: `refuse` / `warn` / `accept`, with `refuse` the default
  for the settled covariates and for a channel-mode mismatch.

The rule, stated so it can be implemented without further interpretation: **a fact the
snapshot read must agree with the definition, or the campaign refuses before the first
recording; a fact the snapshot could not read stays declared and is marked as such on
every record.** Word 14 keeps its special case — the known-wrong declaration means a
snapshot disagreement is recorded against both values rather than refusing, until the
declaration's derivation is fixed (W6).

**Where.** `campaign.py`, next to `campaign_fingerprint` (`campaign.py:470`) and
`plan_campaign` (`campaign.py:522`); the refusal is a `CampaignError` (`campaign.py:150`)
carrying the fact and both values, matching how a foreign channel is refused today.

**Done when.** One test per case: PRF mismatch (refuse), emissions mismatch (record both,
proceed, advisory), burst mismatch (refuse), assisted-mode channel against a manual
campaign (refuse), an unreadable fact (marked declared, proceed), and the happy path
(nothing changes). Plus the criterion-3 test: volatile-only differences compile to the same
`CompilationIdentity`; every compatibility fact changes it.

### W4 — Wire the snapshot into the campaign run, the manifest and the resume

**What.** `run_campaign` (`campaign.py:640`) implements §4's order literally: the snapshot
is taken once per run, immediately after `_verify_channel_once` (`runner.py:323`) and before
the first recording; the compile follows; the resume identity is validated **before** the
todo/skipped set is computed; and only then does the first point run. It carries the result:
`JobManifest` gains the snapshot and the compiled identity; `resume` compares both, so a job
resumed against a different instrument or a different fixed configuration says so instead of
quietly continuing (the review's Phase 8, first half). A **new `compile` verb** prints the
compiled plan, the reconciliation result and the refusals with nothing recorded, which is
also how the live acceptance sequence is rehearsed. `--no-snapshot` exists for the operator who must run
without a snapshot; the manifest and every record from such a run are marked `declared
only`.

**Legacy logs and manifests — the rule, not an improvisation.** Every manifest written
before this slice carries `fingerprint` only, and that is `campaign_fingerprint(definition)`
(`campaign.py:470`): a hash of the *definition*. It can prove that a log answered that
definition, and it can prove nothing whatever about the instrument — so for a job recorded
before this slice, compatibility **cannot be demonstrated**, and the absence has to be a
declared outcome rather than an accident of implementation. The rule:

- **Fail closed.** A resume of a job whose manifest carries no compilation identity refuses,
  naming the missing identity, and the refusal is the default.
- **One explicit way through.** `--resume-declaration-only` (the same family as
  `--no-snapshot`) lets the operator proceed anyway; the manifest and every point that the
  resume skipped on that basis are marked as having been decided **without instrument
  evidence**. Silence is not one of the options.
- **It runs at step 6, before step 7.** Identity is validated *before* the todo/skipped set
  is computed, so no point can be dropped on the strength of an identity that was never
  proven. A resume that skipped points and only then discovered the instrument was
  incompatible would have skipped them for nothing, and the operator would have to reason
  about which points were valid.

This follows the repository's existing direction rather than inventing a new one:
`record_identity` (`campaign.py:432`) returns an unrecognised name unchanged *on purpose*, so
that a point "whose identity is in doubt" is **re-run rather than skipped**. Phase 6 applies
the same principle one level up, to the job.

**Naming — three verbs, three meanings.** `acquire plan` already exists, and its help says
"touches no instrument" (`cli.py:506`); so `--plan-only` on `campaign` would name a live
operation after an offline one. The distinction the CLI already implies is worth keeping
explicit:

```
acquire plan       definition → points                 touches no instrument
acquire compile    + live snapshot → reconciliation    touches it, records nothing
acquire campaign   compile, then acquire               the run
```

`compile` is therefore the new verb, and `campaign` is `compile` + acquisition. Its help
string joins `plan` and `report` in saying which side of the instrument boundary it is on.

**Where.** `campaign.py` (`run_campaign`, `JobManifest`, `ManifestPoint`,
`campaign_fingerprint` usage), `cli.py`'s `acquire_main` (`cli.py:422`) for the flags and
the `compile` verb, and `docs/dop3000/live-bringup.md` for the operator-facing sequence.

**Done when.** `acquire compile` against a deliberately-wrong instrument refuses with the
named fact and the store directory still empty; a real run writes the snapshot into the
manifest; a resume against a changed snapshot reports the difference; and the end-to-end
campaign tests pass with the fake's snapshot in place.

### W5 — Cap provenance (carried forward from the review of the correctness slice)

**What.** `max_profiles_per_block` is a declared setting, and the wrap classification is
currently an inference under that declaration — even `SweepPointRecord.block_wrapped`'s
`False` branch is conditional (200 stored against a declared 257 could be a block whose
actual cap was 200, which wrapped). Read or verify the cap from the application where it
can be, and split the vocabulary as the reviewer asked: `block_at_declared_cap` for what is
observed today, `block_wrapped` reserved for a cap whose provenance is verified.

**A fact is a value *and* its provenance, as a type.** Storing `max_profiles_per_block = 257`
and keeping the provenance in a separate flag, or in a docstring, is exactly what lets
downstream code read the presence of a number as proof. One small shared model carries every
fixed fact:

```python
class FactSource(StrEnum):           # Enum for fixed sets, per AGENTS.md:106
    READ = "read"
    DECLARED = "declared"

class InstrumentFact(ValueModel):
    value: int | float | str | None
    source: FactSource
    detail: str | None = None        # which screen it came from, or why it could not be read
```

so `value=None, source=DECLARED` and `value=257, source=READ` are different statements that
cannot be confused, and the same mechanism covers sound speed, first gate and burst length
if W1 finds them unreadable. Convenience accessors are fine; a bare number in an
evidence-bearing position is not.

**Where.** `log.py` (`SweepPointRecord`, `block_at_cap` at `log.py:319`, `block_wrapped`
at `log.py:335`, `block_cap_profiles`), `snapshot.py` (the read, when the app exposes one),
`campaign.py` (the declared value's provenance).

**Done when.** The record distinguishes a read cap from a declared one; `block_wrapped`
answers `None` when the cap's provenance is unverified; the rename or the split is done
one way and documented one way; and the test that asserts `True`/`None`/`False` says which
provenance it is under.

### W6 — Feed the period law the instrument's own emissions, without erasing the declaration

**What.** `_profile_period_s` (`campaign.py:910`) and the runner's law use the declaration.
On the committed point the definition says 52 while the instrument — and the stored file's
own word 14 — say 150, so `timing.target_s` is 0.0098 s against a measured 0.030007 s. With a
snapshot available, the law should use what the instrument says.

The trap is *how*. Writing `point.parameters.emissions_per_profile = 150` would make the
record agree with itself by destroying the evidence it exists to hold. Four facts have to
survive, and they are four, not two:

```
definition declared      52     what the experiment asked for
instrument read         150     what the application was configured to do
effective timing used   150     what the law was actually fed
stored file confirmed   150     what the acquired block's own word 14 says
```

So the compiled plan carries the fixed configuration in three named projections —
`declared_fixed_configuration`, `observed_fixed_configuration`,
`effective_fixed_configuration` — each fact keeping its value **and its provenance**, and the
rule is:

- the timing law uses the **effective** value, which for emissions is the observed one;
- the **declared** value stays exactly as the definition wrote it, on the campaign and on
  every record from it;
- the **reconciliation result** stays on the record too, so the 52-vs-150 disagreement is
  still visible *as* a disagreement after this fix rather than edited into agreement.

**Where.** `campaign.py:910` and the definition-to-effective resolution; the runner's period
computation; `ExecutableCampaign` (W3) for the three projections; the record's `ProfileTiming`
(already carries `target_s` and `achieved_s`).

**Done when.** On the committed point, `timing.target_s` is computed from the effective 150
while the record still shows the declaration as 52 and the disagreement as a disagreement —
**one test asserts all three together**, so no later change can collapse them back into a
single number. This is also what makes Phase 7's certificate possible.

## 5. Decisions to make before coding

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | How the snapshot reaches the caller | add `instrument_snapshot()` to `SweepActuator`; or introduce the review's separate `InstrumentSession` port now | **Add the method.** Additive, precedented by `try_record_and_store`, and it keeps the fakes single-protocol. A separate port is the review's Phase 5, and belongs with the `driver.py` extraction, not before it. |
| D2 | Snapshot cadence | once per run; or per point | **Once per run**, beside the existing once-per-run channel check. Per point costs modal dialogs an operator watches open and close, for facts that do not change within a run. |
| D3 | No snapshot available | refuse the run; or `--no-snapshot` with the records marked `declared only` | **Both**: refuse by default, allow the explicit flag. Silence is the only unacceptable option (criterion 4). |
| D4 | Mismatch policy | refuse before the first recording; or record and continue | **Refuse for the settled facts and the channel mode**; record-and-continue only for word 14, whose declaration is known wrong until W6. |
| D5 | Where the compiled plan lives | a frozen model in `campaign.py` with its own fingerprint; or new fields on the JSON definition | **A separate model.** The definition expresses experimental intent and is authored by a human; the compiled plan is instrument-specific and machine-generated. Merging them would put the instrument into the campaign file. |
| D6 | Where the read path for a newly discovered fact lives | extend `ParamRole`; a second role model for the dialog surface; snapshot-local readers | **Decide after W1's reconnaissance, not before.** `ParamRole` is the measurement screen's column and a dialog fact must not be forced into it. Default to a snapshot-local reader until a second fact needs the same surface. |

## 6. Constraints and gates this work is subject to

- **Verbatim-port rule** for `acquire/` and `tools/live/` (agenda, "Rules that constrain
  the work"): move a proven gesture, never re-derive it. W1's new reads must be captured
  from the live application, not inferred from the manual.
- **Decoded-metadata gate**: a new decoded word needs byte-level evidence, a destination
  domain field, propagation rules and storage implications. W5/W6 add no new word decoding
  beyond what the correctness slice already landed (words 5/8/14/19 via `verify.py`).
- **Models** (`AGENTS.md:106`): Pydantic `BaseModel`; the frozen `ValueModel` pair; "Do not
  add dataclasses." `InstrumentSnapshot` and `ExecutableCampaign` are `ValueModel`s, never
  dataclasses.
- **No CI**: `uv run --no-sync --extra dev ruff check src tests` and `pytest -q` are the
  gate, run locally. `ruff format --check` is dirty in 14 files at baseline — format only
  what was clean and what you touched.
- **Never claim an unread instrument fact.** This is the rule the correctness slice's
  review settled, and W2–W4 exist to enforce it structurally.
- **Acquisition must not adopt `EchoRpmSettings.uniform_rtol`** (verdict §7b): acquisition
  QC and estimator eligibility are different questions.
- **The instrument's recipes are not to be touched.** No change to `driver.py`'s gestures,
  press holds, dialog rules or control resolution in this slice.

## 7. Verification plan

- **Fakes first.** `FakeActuator` (`tests/test_acquire_runner.py`) and the campaign fakes
  gain `instrument_snapshot()` returning a scripted snapshot, so every run-logic test
  keeps running without the instrument. The fake's default snapshot is the expected
  configuration, so existing campaign tests keep passing unchanged (criterion 5).
- **Real-machine fixtures.** Serialized control-tree and fingerprint JSON for the states
  the review listed — manual-ready, assisted-ready, recording, store view, store dialog,
  manual parameters, assisted parameters, warning — committed under `tests/data/` as they
  are captured. Binding and mode tests then run without Windows.
- **The identity test, both directions** (criterion 3). Take a snapshot captured from a real
  session, then perturb only `hwnd`, `rect`, `maximized`, `screen`, `cursor` and
  `is_foreground`: the `CompilationIdentity` must be unchanged. Then vary each fact in W2's
  table: each must change it. This is the test that keeps a restart from reading as a
  different instrument, and it is the reason the two models exist. Three cases the fixture
  set must hold on the same channel: counts with the window **restored**, counts
  **maximised** (same identity), and the **minimised** window (a precondition refusal,
  naming the state, not an identity change).
- **A deliberately negative hardware case** (criterion 1, the central promise, proved on the
  real application rather than only in fakes): set one fixed parameter deliberately wrong by
  hand, run `acquire compile`, and verify that the campaign **refuses, names the
  fact, starts no recording and leaves no file** in the store directory; then restore the
  parameter and verify the same compile succeeds. This belongs in the acceptance sequence
  below, not only in the unit suite.
- **Red before green**, per repo convention: the failing assertion's real output goes in
  the commit body.
- **The live acceptance sequence** (manual, on the machine owning the screen, dispatched
  through `tools/live/`): status → snapshot → preflight → one short stored point →
  canonical decode → certificate → clean READY, **plus the negative case above**: one fixed
  parameter wrong on purpose, a refusal with no file, then the parameter restored and the
  same compile accepted. This is the gate that the fake cannot be.
- **Gate numbers in the PR body as a comparison**: `pytest -q` on the branch against
  `master` at `abf2ead` (**1568 passed, 22 skipped, 0 failed**).

## 8. Sequencing, as PR-sized slices

| slice | content | depends on | can land alone |
|---|---|---|---|
| P1 | W2 — snapshot model, port method, fake stub, docstrings | — | yes (no behaviour change) |
| P2 | W1 — reconnaissance, `ParamRole` extension, fixtures | the live machine | yes |
| P3 | W3 — `compile_campaign` + refusals + policy, no run-path change | P1 | yes |
| P4 | W4 — wire into `run_campaign`, manifest, resume, the `compile` verb | P1, P3 | yes |
| P5 | W5 + W6 — cap provenance, period-law source | P1 | yes |

P1 and P3 change no recording path, so they can land and be reviewed before anything
touches a real campaign. P4 is the first slice that changes how a campaign behaves, and
its tests are the ones that must show the recipe is untouched (criterion 5).

## 9. Out of scope — do not re-open without a decision

- The review's Phase 1–5 items: `io/dop/operation.py`, splitting `acquire/driver.py`,
  the explicit UDOP state machine in code, replacing rather than wrapping `Actuator`, and
  the separate `InstrumentSession` port. Deferred with triggers in the decision record §6.
- Phase 7 (the per-point acceptance certificate): the next milestone after this one. The
  pieces this plan must leave for it are the compiled plan's policy, the snapshot on the
  record, and the per-fact `read`/`declared` provenance.
- **Migrating the record's existing provenance fields onto `InstrumentFact`** —
  `block_cap_profiles`, `covariates_enforced`, `covariates_advisory`, `SizeSignature`. P1
  introduces the type (the two models cannot be typed against a type that does not exist) and
  uses it for the reading it adds; reshaping fields the analysis already reads is a log-schema
  change, and it belongs with Phase 7, where the certificate decides what the record must
  carry. Deciding it here would grow this slice into a restructuring no consumer has asked for
  yet. (Round 1 endorsed the mechanism, not a migration.)
- Phase 8's log-schema versioning beyond the resume fingerprint; Phase 9's
  hardware-in-the-loop gate beyond the fixtures W1 captures.
- Anything touching `outputs/` (gitignored live evidence) or the reconnaissance probes
  under `tools/live/probes/`.

### 9.1 The stop condition — binding, from the review of the batch

Once a campaign can route the target channel, snapshot enough fixed settings, refuse a deliberate
mismatch before recording, and then run the existing six-point campaign **unchanged**, *stop
expanding the acquisition architecture* and use it for a real parameter-sensitivity experiment.
This is W4's exit criterion, adopted verbatim from the review.

After that point the acquisition architecture is re-opened by **evidence**, not by an abstraction
that could be improved: a real campaign failed; a real campaign produced ambiguous evidence; or a
downstream analysis cannot establish an essential acquisition condition.

### 9.2 Read paths, once a fact has one — W4's one policy change

Reconnaissance (W1, §14) gave the burst length, the sound speed and the first gate a supported read
path, which splits what `unreadable` can mean:

| state | consequence in a normal campaign |
|---|---|
| read, and it agrees with the declaration | proceed |
| read, and it disagrees | refuse, per the fact's own acceptance (§13) |
| **a supported read path exists, and this attempt failed** | **refuse before recording** |
| genuinely unsupported (the block cap) | carry as declared, marked unproven |

Before W1 the third row did not exist: "this driver cannot establish the fact" and "this attempt
failed" were the same statement, so a campaign could proceed on a fact nobody had read. They are now
different claims about the instrument and they get different consequences — demoting a supported
read back to `declared` would mean knowingly proceeding when the check that exists was not
performed. The inventory of which facts have a supported read path is declared where the readers
live; the refusal is the campaign's.

### 9.3 A stranded popup — what recovery is allowed

Measured (W1, §14): Escape closes nothing in this application, a cursor move does not dismiss a
hover-opened popup, and a posted `WM_CANCELMODE` does not either; the only clean exit is a press.

- **Commissioning and testing** (the live acceptance sequence below): abort the test, **never press
  an unknown popup entry** (the second entry selects the assisted mode), restart the application,
  verify the configuration, restart the sequence. Documented operator recovery, not a program.
- **An unattended campaign**: abort the campaign, mark the application state unverified, require the
  operator. No automatic restart, no speculative menu press, no silent continuation.

Both rest on the principle the rest of this plan already follows: do not invent a Win32 gesture the
live application has not demonstrated. If a stranded popup becomes a recurring operational problem,
*that* is the evidence a recovery primitive would be budgeted against.

## 10. Review round 1 — what changed in this document

The plan was reviewed before any implementation. The direction was approved — including all
five recommended decisions, and explicitly *not* requiring `InstrumentSession`, the explicit
state machine, the canonical operation decoder or the `driver.py` decomposition first — with
four document-level changes requested before coding, and four smaller observations. All eight
are in this revision, one commit each:

| # | review point | where it now lives | commit |
|---|---|---|---|
| 1 | do not compile on the raw `ScreenFingerprint` | §3 criterion 3, W2 — two models, `InstrumentSnapshot` and `CompilationIdentity` | `d85883f` |
| 2 | make the order explicit: routing before reading | §4 "The order", W2's narrowed docstring, W4 | `f28e4a5` |
| 3 | define resume against a pre-Phase-6 log | W4 "Legacy logs", criterion 6 | `c7fec27` |
| 4 | W6 must not overwrite the declaration it explains | W6 — declared / observed / effective | `cb983cd` |
| 6 | `--plan-only` names a live step after an offline one | W4 "Naming" — `acquire compile` | `f8d72eb` |
| 7 | W1 must not assume every fact belongs in `ParamRole` | W1 reworded, decision D6 | `95a09bc` |
| 8 | provenance is a value *and* a source, as a type | W5 — `InstrumentFact` / `FactSource` | `95a09bc` |
| 10 | prove the refusal on real hardware, negatively | §7 and the acceptance sequence | `d85883f` |

Point 5 (the decisions) was agreed with one qualification — D2's "take the snapshot after
the intentional target-channel selection" — which is now the order in §4 rather than an
implementation choice. Point 9 (`uniform_rtol` stays out of acquisition) was already a
constraint in §6 and is unchanged.

Point 10 landed inside the commit for point 1 rather than its own; the acceptance sequence
carries it either way, and it is listed here so the record is not silent about it.

One further change in this revision is **not** from the review and is listed here for the same
reason: the **minimised-window precondition** (`331db35`). Checking the identity's own layout
signature against `_visible_children` (`driver.py:420`) showed that `IsWindowVisible` requires
every ancestor to be visible, so a minimised UDOP reports zero controls in zero panels — which
would have compiled as "the layout differs" and refused for the wrong reason.

## 11. Picking this up cold

```bash
cd C:/Repos/udv-echo-process
git fetch origin && git switch feat/acquisition-campaign-compilation

# read, in this order: this plan  →  the decision record's §6/§7a/§7b
#   docs/dop3000/acquisition-review-and-verdict.md
#   src/udv_echo_process/acquire/campaign.py      (run_campaign:640, plan_campaign:522,
#                                                  compile_campaign — §13)
#   src/udv_echo_process/acquire/actuator.py      (ParamRole:107, Actuator:398)
#   src/udv_echo_process/acquire/snapshot.py      (the reading and the identity — §12)
#   src/udv_echo_process/acquire/runner.py        (SweepActuator:180)
#   tests/test_acquire_campaign.py                (the campaign-level behaviour to keep)
#   tests/test_acquire_snapshot.py                (the reading's own contract, and §12's)
#   src/udv_echo_process/acquire/driver.py        (the dialog read path — §14)
#   tests/test_acquire_dialog.py                  (the binding, the checks, §14's evidence)
#   tests/data/udop-parameters-dialog-tree.json   (the measured dialog the binding is pinned to)
#   tests/test_acquire_compile.py                 (the compile's contract, and §13's)

uv run --no-sync --extra dev ruff check src tests
uv run --no-sync --extra dev pytest -q
```

The measured facts a fresh session would otherwise re-derive are at the end of
`docs/dop3000/acquisition-review-and-verdict.md` §8 and in the committed fixtures; the
live-run evidence is in the gitignored `outputs/live/*.jsonl`.

## 12. P1 (W2) as landed

Slice P1 is implemented and green; the plan above is unchanged, and this is what it turned
into, so a later session does not have to re-derive it.

| where | what |
|---|---|
| `acquire/snapshot.py` | `FactSource` (`read` / `routed` / `declared` / `unreadable`), `InstrumentFact` (+ `unreadable()` / `declared()` / `routed()`), `Provenance` (the identity's value+source, no prose), `InstrumentSnapshot`, `CompilationIdentity` (+ `from_snapshot`), `identity_digest`, `FIXED_FACT_FIELDS` |
| `acquire/actuator.py` | `ChannelMode` — the mode vocabulary, moved out of `driver.py` (`MODE_*` are now its values, the same strings as before) |
| `acquire/driver.py` | `screen_mode(roles)`, `Win32Actuator.instrument_snapshot(*, routed_channel)`, `_channel_fact(routed_channel)`, `_column_fact()` |
| `acquire/runner.py` | `SweepActuator.instrument_snapshot(*, routed_channel)` — additive; `Actuator` gained nothing |
| tests | `tests/test_acquire_snapshot.py` (the reading's contract), a mode section in `tests/test_acquire_driver.py`, the fakes' stub + default reading in `tests/test_acquire_runner.py`, the port-surface case in `tests/test_acquire_actuator.py` |

Five things W3 should know before it compiles, each a decision this slice made rather than an
accident of the code:

1. **The channel is `routed` — and only because the caller says so.** Reading it means opening
   `Operating parameters`: a menubar hover with the operator's real cursor, which is the routing
   step's gesture (`ensure_channel`), and on an assisted channel there is no combo to read at
   all. The reading presses nothing, so the channel is *handed over* —
   `instrument_snapshot(*, routed_channel)` takes the value `ensure_channel` verified, or `None`
   for "nothing established one", which yields `unreadable` with that reason.
   `FactSource.ROUTED` exists so neither can be confused with a `declared` value (a caller's
   claim) or a `read` one (this reading's own answer). **W3 must see a `routed` channel; a
   channel that is not routed is a refusal**, not a declaration to be trusted. The parameter is
   required and keyword-only precisely so that no cycle can leave a verification implied.
2. **The mode is read, and is `None` rather than a guess.** A resolved sidebar parameter column
   is `manual`; a measurement screen with no column is `assisted`; a dialog, a popup or an
   unrecognised layout gives `None`, which the caller carries. `mode=None` is not "assisted":
   nothing may compile a mode out of an absent column on a screen that is not the measurement
   screen. (Same class of mistake as the minimised window, one surface over.)
3. **Two facts are read, four are not.** `prf_us` and `emissions_per_profile` come off the
   column; the burst length, sound speed, first gate and block cap are `unreadable` with their
   reasons until W1 finds read paths. W3's policy has to be written against that state: a fact
   that is `unreadable` is never silently skipped, and criterion 4 is what the policy is for.
4. **The identity is the strip's *view*, and nothing of the buffer.** `strip_view` and
   `strip_has_slider` are in; `slider_max` and `strip_button_count` are out, and neither is a
   judgement call: the slider's range is the selected block's profile count, and the ready row's
   count is 3 or 4 depending on whether a leftover block is held (`STRIP_BUTTON_ORDER` documents
   both rows, and `classify_strip_view` puts both in `READY`). Both are properties of the *run's
   own progress* in the application's buffer, so an identity carrying either would call one
   instrument two and re-run a job that was already measured. The view stays because it is what a
   press is bound against, and the binding is resolved live at press time (`press_index` with the
   count it has just read), so nothing about the driving depends on the projection. (This
   supersedes the argument P1's own pull-request body first made for keeping the count.)
5. **`identity_digest` hashes provenance and values — never the prose.** Each fact contributes a
   `Provenance` (value + source) and nothing else, because a `reason` is written to be rewritten
   for a human reader: hashing it would make a documentation improvement look like a different
   instrument and re-run points already measured. A fact that moved from `read` to `unreadable`
   between two runs *is* a weaker claim about the same instrument, so the **source stays in** and
   the two identities still differ. `campaign_fingerprint`'s recipe (canonical JSON, SHA-256) is
   reused deliberately.

Resume compatibility, which §4's step 6 needs: an identity is comparable only against another
identity. Every manifest that predates this slice carries a definition fingerprint and no
identity at all, which is §3's criterion 6 and W4's fail-closed default — unchanged by landing
P1, and P1 records nothing yet, so no job has one.

### The review of P1 — what it asked for, and what changed

The review approved the slice and the split between the reading and the identity, and asked for
three changes before W3 compiles against it: two that could cause false resume mismatches on the
same instrument, and one that let the reading say more than it could prove. One commit each, with
the failing evidence in the commit body.

| # | finding | what changed | commit |
|---|---|---|---|
| 1 | `identity_digest` hashed `InstrumentFact.reason`, so rewording a diagnostic sentence produced a "different instrument" | `Provenance` (value + source, no field for a reason at all) and `InstrumentFact.provenance()` as the one mapping; a test asserts every fact field of the identity *is* a `Provenance` | `ad3d2f2` |
| 2 | `strip_button_count` is buffer state — the ready row gains `Do store` when a block is held — so it could differ on one instrument | the count is out of the identity and stays in the reading; the **view** remains, and still moves the identity when it changes | `a7e9172` |
| 3 | `DECLARED` implied "the router already verified this", which a standalone `instrument_snapshot()` cannot claim | `FactSource.ROUTED`, `routed()`, and `instrument_snapshot(*, routed_channel)` — required and keyword-only; nothing established yields `unreadable` | `6f9567a` |

Point 3 is the one W3 must not lose, and point 1 above is where this document now carries it: the
compiler's precondition is a **routed** channel, not a declaration to be trusted. The direction
that had to keep moving is pinned in exchange — the identity still changes with each fact's value,
with each fact's source, with a channel that is *routed* rather than *declared*, and with a strip
view the run did not bind against.

## 13. P3 (W3) as landed

Slice P3 is implemented and green, in its own pull request on top of P1's branch (§8: it can land
alone). It changes **no recording path** — nothing in a run calls it until P4 wires it in — so
criterion 5 still holds trivially rather than by testing.

| where | what |
|---|---|
| `acquire/campaign.py` | `Acceptance`, `COVARIATE_ACCEPTANCE`, `FactCheck`, `ExecutableCampaign`, `compile_campaign`, and the rules it applies (`_refuse_unusable_screen`, `_routed_channel`, `_declared_fixed_fact`, `_check_fact`, `_refuse_disagreements`) |
| tests | `tests/test_acquire_compile.py` — one case per rule in W3's "Done when" list, plus the policy table and the identity the compiled plan carries |

Five things W4 has to know before it wires this into the run, each a decision this slice made:

1. **The acceptance policy is the verifier's own table, not a second opinion.**
   `COVARIATE_ACCEPTANCE` is *derived* from `verify.ADVISORY_COVARIATES`: the three enforced
   covariates (sound speed, PRF, burst) refuse, the emissions per profile warns, and the first gate
   and the block cap refuse for reasons of their own: the first gate moves the *spatial* window
   (`first_gate + gates × resolution`), and the cap decides the *retention* semantics a campaign was
   compiled under — how much of the requested window can be kept, whether the block wraps, and what
   `retained_fraction` means. **Not** "the planner refuses those windows": `plan_campaign`
   deliberately does the opposite for the cap, planning the window and attaching a note that the
   block wraps and covers only its last `cap × period` seconds (pinned by
   `tests/test_acquire_campaign.py`), because the near-term goal is a 10–15 s recording the
   instrument honours. The cap refusal cannot fire while the active cap is unreadable (W1, §14) —
   the fact is carried unproven — and it is about the *instrument* disagreeing with the definition,
   which is a different question from whether the plan is runnable. W6
   moves the emissions row and nothing else. The comparison keeps the verifier's tolerance
   (`PRF_TOLERANCE_US`; the app stores integer microseconds) and is exact elsewhere — a pre-run
   check stricter than the post-run one would refuse jobs that would have passed with a recording
   already spent.
2. **A refusal names every fact that disagreed**, in one message, because the comparison is cheap
   and the instrument is in front of the operator. W4 must not catch and re-wrap it: the message
   *is* the operator's instruction.
3. **The order is: the definition's own laws, then the screen, then the channel, then the facts.**
   An unplannable file is refused for *that* reason and not for a screen state the next poll would
   change. A test asserts the ordering, not just the messages.
4. **The channel comes from the router, through the snapshot.** W4 calls
   `instrument_snapshot(*, routed_channel=<what ensure_channel returned>)`, and the compile refuses
   anything that is not `routed` — so a cycle that forgets to hand it over fails closed instead of
   recording under an assumed channel.
5. **What the run carries forward**: `ExecutableCampaign.advisories` (the disagreements it proceeds
   despite) onto every record, `unproven` (the facts no surface could state) onto the manifest, and
   `identity` + `definition_fingerprint` together as the resume's comparison — the pair is what
   makes a compiled plan auditable after the fact, and criterion 2's "which channel and mode were
   active" is answered by the identity.

Deliberately **not** owned by the compile: the strip's view. Starting a point cycle from a
recording view is refused by the runner with its own message *before* anything is stored, so a
second refusal here would give one cause two diagnoses. The view is still in the compiled plan's
identity, which is where a resume needs it.
## 14. W1 as landed — the dialog's three facts, read by position and checked against the screen

Reconnaissance ran on the live machine (the application in simulation mode, restarted before the
pass; `tools/live/probes/w1_fixed_facts.py`), and it answered the two questions the plan left to it:
**where** these facts are stated, and whether a read path exists at all.

**Where.** In the ``Operating parameters`` dialog's own value table. Not in the parameter column —
which is why these facts stay out of `ParamRole` and `PARAM_COLUMN_ORDER` and why the read path has
its own vocabulary (`DialogField`, `DIALOG_FIELD_ORDER` in `actuator.py`). The table is three
columns of `TSp_Value_Button` widgets; the columns are the x bands of the value edits' left edges
(786 / 987 / 1187 px in a 627x384 dialog at 655,364), and inside a column a field's identity is its
top-to-bottom position. A row's value is the **combo** when the row offers one — the burst length,
the sensitivity and the sampling volume are chosen from lists — and the `TSp_Edit` beside it
otherwise: at `burst = 4` the row states a combo `'4'` *and* an edit `'89'`, and the 89 is the
sampling-volume read-out the manual describes (the corpus' own value at 1460 m/s is 0.876 mm), not
the parameter.

**Which facts came out.** Five of the six fixed facts are now read from the instrument:
`prf_us '212'`, `emissions_per_profile '150'`, `burst_length '4'`, `sound_speed_ms '1460'`,
`first_gate_mm '2'`, with `mode 'manual'`. The sixth — `max_profiles_per_block` — is **still
`unreadable` with its reason**, which is the outcome W1 allowed for: the cap is an application
Preference, and the surface that holds it (`Record settings`) is not reachable by a gesture
reconnaissance could establish safely — the `Parameters` popup's entries are caption-less even
through `WM_GETTEXT`, and the second one is `Default parameters`, which *selects the assisted mode*
when pressed (manual doc 04, and the driver's own note records the assisted-mode word flipping in a
stored file after a retry walked down that popup). Nothing invented a read; the fact is carried as
unread.

**What stands between the binding and a value** (`Driver.read_dialog_parameters`, and the tests in
`tests/test_acquire_dialog.py`):

1. the table **filled** — a freshly started application builds it empty (or not at all) the first
   time it is opened and states it afterwards (measured: the first open read 2 stating controls,
   the next 22); the read polls for `DIALOG_FILL_TIMEOUT_S` and then says *which* of the two it saw,
   because an empty field is not a value;
2. the table's **shape** is the measured one (`DIALOG_COLUMN_ROWS`) and it states the channel it is
   showing in its header combo — a reading that cannot say whose parameters these are is not
   something a compile may compare (the channel trap, docs/16 §12);
3. every **anchor** agrees with the screen — seven of the dialog's fields are facts the column also
   states, and all seven must read the same text on both surfaces before a dialog-only fact is
   believed. A re-laid-out dialog would put a different value in `(column, row)` while still reading
   like a value, so this is what makes a positional binding evidence instead of habit. An anchor
   neither surface states is refused as *uncheckable* — a different reason from disagreement, and a
   run record has to be able to tell them apart.

**The hand-over rule holds.** `instrument_snapshot(*, routed_channel, dialog_parameters=None)`: the
reading still presses nothing, and the three facts become `read` only when a caller hands over what
`read_dialog_parameters` read. Verified live in one pass: two snapshots, identical except that one
was handed the reading, and only one carries the three facts.

**Two facts about the application that this slice measured, and that outlive it.**

- **Escape closes nothing.** No popup, no dialog, no overlay (operator-reported, and noted before
  this slice). A driver that leaves a dialog or a popup open therefore *traps the operator* — there
  is no key they can press. That is why the reader closes the dialog in a `finally` and why the
  probe restores the cursor in one.
- **A hover-opened popup cannot be dismissed programmatically.** Moving the cursor off the menubar
  does not close it; moving it past the last entry does not; a posted `WM_CANCELMODE` does not. The
  only clean exit is the *press* the driver already makes (which selects an entry and closes the
  popup), and a gesture that hovered and then failed strands the application until it is restarted.
  This is a real gap in the driver's failure path and is recorded here rather than worked around: a
  probe run during this slice did exactly that to the operator's desktop, and the recovery was a
  restart.

**What W4 must carry from here.** (a) The compile path has to *call* the reader — the snapshot will
not read the dialog on its own, by design — and today's live state is the good case: five facts
read, the cap unread, and the compile's existing rule that an unread fact is a refusal (or a
warning, per the covariate table) then decides. (b) The reading carries the dialog's own channel
field; comparing it against the routed channel is a refusal W4 owns, not this slice — a dialog
showing channel 2's parameters while the run routed channel 1 is exactly the channel trap in a new
place.

## 15. W4 as landed — the snapshot and the compile reach the run, the manifest and the CLI

Slice P4 is implemented on `feat/acquire-w4-integration` (cut from this branch's tip after the three
earlier slices merged), in four commits:

| commit | what |
|---|---|
| `00ff9c9` | the decisions, as decisions: §9.1's stop condition, §9.2's read-path table, §9.3's recovery rule |
| `a356d68` | the one policy change: `SUPPORTED_READ_FACTS` + `_refuse_failed_reads` |
| `b2743f4` | §4's order in `run_campaign`, the resume identity, the manifest's three new fields |
| `accc682` | the `compile` verb and the two flags |

**The order is literal** (`run_campaign`): the static plan (so an unplannable file costs nothing, not
even a dialog) → `ensure_channel()` (routing, not a scientific setting; `SweepRunner` now keeps that
call's return and exposes `routed_channel` instead of discarding it) → `instrument_snapshot(routed_channel=…,
dialog_parameters=read_dialog_parameters())`, once per run → `compile_campaign`, whose `CampaignError`
propagates untouched (§13.2) → the resume identity, validated before the todo/skipped sets exist → the
existing per-point cycle, over the **compiled** points. `SweepActuator` gains
`read_dialog_parameters()`: the snapshot will not open that dialog by design, so a caller that wants
the three dialog facts has to have paid for the step. The primitive `Actuator` still has no dialog
reader, which the dialog tests pin.

**Two behaviour changes are disclosed rather than hidden** (both deliberate, both in the commit body):
a compiled campaign opens the channel dialog **twice** — step 3, then the runner's own pre-record
guard, which is idempotent (it writes only when the channel differs) — and `plan_campaign` runs twice,
once as step 2 and once inside the compile, where it is pure and the duplicate keeps the step-2
refusal free of any gesture.

**The resume is fail-closed, and the flag that bypasses it says so on the record.** A manifest whose
definition fingerprint differs refuses and is *not* bypassable; a manifest with no compilation
identity (every manifest written before this slice), or no manifest while the log holds successful
records, refuses; a different identity refuses naming the fact that moved, with both sides.
`--resume-declaration-only` turns those identity refusals into a proceed and records the authorisation
in `skipped_without_evidence`. `--no-snapshot` takes no reading, compiles nothing and marks the
manifest `declared_only`. `JobManifest.compilation_identity` carries the §3.3 stable projection, never
the raw snapshot: the volatile half (hwnd, cursor, `is_foreground`, geometry) is not compatibility
evidence, which is the distinction §3.3 exists to draw.

**The live rehearsal stops at a precondition, and that is worth recording.** `acquire compile` against
the running application refused with the driver's own foreground guard — "the `TMain_Scr` window is
not the foreground window, so its menubar cannot be hovered: the foreground window is
`Windows.UI.CoreWindow`" — before any hover, so nothing was opened and nothing was stranded. The verb
therefore needs the application in front, which the operator's sequence has to say out loud (a console
window opened by the launcher is the usual thief). The good case is otherwise available as-is: this
machine reads exactly what `examples/campaign-single-channel.json` declares.

**Still open, and named as W4's own obligation in §14:** the reading carries the dialog's own channel
field, and comparing it against the routed channel is *not* implemented yet — the dialog's channel
does not survive into `InstrumentSnapshot`, so neither the compile nor the run can see it. A dialog
showing channel 2's parameters while the run routed channel 1 is exactly the channel trap in a new
place (§14, "The channel trap in the one place this system cannot see"), and it stays open until the
reading carries that field and something refuses on it. It cannot fire in the planned experiment,
which runs one channel with the dialog on that channel, so it does not hold the experiment back.

### 15.1 The live acceptance run, on the real application

Dispatched through `tools/live/` against UDOP in simulation mode, the application foreground (the
first attempt refused at the driver's own foreground guard, before any hover, with nothing opened and
nothing stranded — that guard is the reason the operator sequence now states the precondition).

1. **The good case** — `acquire compile --definition examples/campaign-single-channel.json` → exit 0,
   channel `1` **routed**, mode `manual` **read**, and `prf_us 212`, `emissions_per_profile 150`,
   `burst_length 4`, `sound_speed_ms 1460`, `first_gate_mm 2` all **read** and all agreeing with the
   declaration. `max_profiles_per_block` is carried `unreadable` with its reason and marked `agreed:
   None`, so the record says "declared, not verified" instead of pretending. Nothing was recorded —
   the verb has no store path and `compile_campaign` takes no actuator.
2. **A deliberate mismatch, definition side** — a copy declaring `burst_length 5` against an
   instrument reading `4` refused with exit 2: "the instrument disagrees with the campaign before the
   first recording, so nothing was stored and the application is untouched: burst_length: the campaign
   declares 5, the instrument states '4'".
3. **A deliberate mismatch, instrument side** (the operator moved the burst one step in the dialog,
   which the combo took to `6`) — the unmodified definition refused the same way, naming `4` against
   `6`. Both directions of criterion 1 proved on the application, not in a fake.
4. **The six-point campaign, unchanged** — `acquire campaign --definition
   examples/campaign-single-channel.json --store-dir <the application's own Record settings directory>
   --log outputs/live/w4-acceptance.jsonl` → `6/6 point(s) ok`, six `.BDD` files stamped
   `20260918T113607` in the application's capture directory, six log entries all `ok`, and a manifest
   carrying `compilation_identity` with `channel ('1','routed')`, `burst ('4','read')`, `sound speed
   ('1460','read')`, `first gate ('2','read')` and the cap `(None,'unreadable')` — plus
   `declared_only: false`, `skipped: []`, `skipped_without_evidence: []`.
5. **The resume** — the same command with `--resume` → `0/6 point(s) ok; 6 skipped as already
   recorded`, exit 0. The identity was proved **before** any point left the todo set: this is §4's
   step 6 doing its job on a real manifest, and it is the check that did not exist before this slice.

With that, §9.1's stop condition is satisfied: the campaign routes the target channel, snapshots the
fixed settings, refuses a deliberate mismatch before recording, and ran the existing six-point
campaign unchanged. **The acquisition architecture stops growing here** — what comes next is the
parameter-sensitivity experiment this was all built for.

## 16. Closing W4 — the one change request, one live defect, then the experiment

### 16.1 The dialog-channel attribution check (the review of #7's single request)

**Why.** The dialog's own channel field is already read (`DialogParameters.channel`, W1) and the routed
channel is already to hand (`ensure_channel()`), so a dialog stating channel 2 while the run routed
channel 1 would attach channel 2's burst, sound speed and first gate to a channel-1 snapshot. That is the
wrong-channel trap in the one place the system cannot see it (§14), and it is a known hole, cheap to
close, so it does not cross the stop boundary.

**Where.** `Win32Actuator.instrument_snapshot` (driver.py) — the single point where both values meet, so
every caller is covered (the run path, `acquire compile`, and whatever comes later) without touching the
snapshot model. The reviewer asked for no broader model change and none is needed.

**Rules.** Compare only when a channel was routed (`routed_channel is not None`) *and* the reading is a
successful one (empty `reason`, non-empty `channel`). A *refused* reading must keep its own reason for
`_refuse_failed_reads` to report: replacing a precise reader diagnostic with a vaguer attribution error
would be a worse record.

**Refusal.** The driver's `AcquisitionError`, naming both channels, before any fact is attributed — which
is why 16.2 comes with it.

**Evidence.** Red before green, in `tests/test_acquire_dialog.py` with the measured dialog fixture:
`FakeDialogDriver(channel="2")` against `routed_channel=1` refuses with both channels named and attributes
nothing; the mirror case (`channel="2"`, `routed_channel=2`) is accepted; a *refused* reading still reports
the reader's own reason rather than the attribution error. Live: the same `acquire compile` on the machine
(whose dialog is on channel 1) must still be accepted — and, because the mismatch cannot be staged on a
one-channel instrument without disturbing it, the fake cases are the evidence for the refusal itself.

**Not done:** no `InstrumentSnapshot` field, no new port method, no policy table, no second inventory.

### 16.2 The CLI error path (found by the live run, narrow)

The first live `acquire compile` on a non-foreground application printed a **traceback** and exited 1.
`AcquisitionError` is not a `ValueError`, so the acquire handlers' `except (ValueError, OSError)` never
sees the driver's own refusals — the foreground precondition, a dialog that will not open, a control that
is not there. Fix at the CLI boundary (catch the driver's error in the acquire handlers and report it as
one `udv-acquire: <message>` line with the documented exit code), *not* by re-parenting the exception:
that hierarchy is what lets callers tell a refused point from a broken instrument.

**Exit code.** `2`, decided rather than inherited: every other refusal in the acquire surface returns 2
(the compile's own refusals, argparse's usage errors), and a driver refusal is a refusal — the run did not
happen and nothing was written — not a crash and not a partly completed job. The current traceback exits 1
only because nothing caught it.

**Evidence.** One case per affected verb driving a driver refusal through `acquire_main`, plus the live
re-run of `acquire compile` with the application *not* in front — one line, exit 2, no traceback.

### 16.3 Then the milestone closes

With 16.1 and 16.2 green, the sequence is: commit both to `feat/acquire-w4-integration` and post the green
evidence as a comment on #7 (the review asked for no second pass — "once that channel attribution check is
in and green" is their condition); merge #7 into the plan branch; then mark PR **#3** ready and merge the
plan branch to master — #3 is still a **draft**, and it is the only route the plan document has to master.
#4, #5 and #6 are already MERGED on GitHub, so no housekeeping remains for them. The working branches are
then deleted locally and on the remote, and the next work starts from a clean master.

§9.1 governs from there — the acquisition architecture re-opens on evidence only (a real campaign failed,
ambiguous evidence, or a downstream analysis that cannot establish an essential acquisition condition).

### 16.4 The experiment — the reason all of this exists

This is not a slice. It needs the operator's scientific input before any code, and the questions to settle
are, in order:

1. **Which knob, and what hypothesis?** One parameter with a physically expected effect and a measurable
   signature. The ladder already varies resolution/gates; the burst, the sound speed and the first gate are
   the other knobs — and all three are now *checkable before* a run, which is what W4 bought.
2. **What is the response quantity?** That decides the analysis, and therefore whether the stored `.BDD`
   files carry enough. The decode path yields gates, depth, sound speed, PRF, emissions and burst, and
   `ProfileTiming` yields profile count, span, the effective interval, the at-cap/wrap distinction and the
   retained fraction. Anything outside that set is a decoder question, not an acquisition question — and
   it has to be answered *before* the campaign runs, not after the recordings are spent.
3. **Repeats and variance.** A sensitivity claim needs the instrument's own spread at one fixed setting, so
   the design needs repeats rather than one sample per setting; the existing six-point file is a frame, not
   a design.
4. **The predicted-timing caveat (W6).** The 52-vs-150 emissions disagreement the review raised is
   experimentally relevant, not architectural: if any part of the experiment depends on *predicted* profile
   timing, the period law must first be fed the instrument's own emissions (W6). Narrow, motivated by the
   experiment, and not a reopening.
5. **Where the results live, reproducibly.** A stored point now ties to the instrument state that produced
   it through the manifest's compiled identity (§3.2), so the analysis can cite the acquisition condition
   instead of re-deriving it.


### 16.5 §16 as landed

Both items are in, on `feat/acquire-w4-integration`, each red-first and each with its evidence in the commit
body.

- **16.1** — `Win32Actuator.instrument_snapshot` now refuses a dialog reading that states a channel the run
  did not route, as the method's **first statement** (before the screen is read), through the private
  `_require_same_channel`. The two values are compared only when a channel was routed *and* the reading
  succeeded, so a refused reading keeps the reader's own reason — the campaign turns that into its refusal,
  and a vaguer attribution error would replace a precise diagnostic. The driver's existing `AcquisitionError`
  names both channels. No snapshot field, no port method, no policy table. Red first: `DID NOT RAISE
  AcquisitionError`, 1 failed / 24 passed. The two arms that must **not** refuse (the mirror case and the
  refused reading) cannot be red before the fix, so they were proved to have teeth by mutating the check one
  guard at a time. `FakeDialogDriver` gained a *stated* `screen_fingerprint` (never read), which is how
  "refused before anything was read" is asserted.
- **16.2** — `driver.AcquisitionError` now reaches the operator as one `udv-acquire: <message>` line with exit
  code 2 from **every** acquire verb. The spec named the handlers; measuring showed `status`, `channel` and
  `preflight` leaking identically with no handler of their own, so `acquire_main`'s dispatch catches it too
  — fixing only the handlers would have left the defect half-closed. The exception hierarchy is untouched.
  Red first: five verbs escaping as tracebacks; green after: 84 passed in those two modules.
- **Gates at the head:** `ruff check src tests` clean; `pytest -q` **1701 passed, 22 skipped** (baseline
  1693).
- **Live, on the machine:** the acceptance `acquire compile` re-run against the unmodified example returned
  **exit 0** — channel 1 routed, manual read, PRF 212 / emissions 150 / burst 4 / sound speed 1460 / first
  gate 2 all read and agreeing, the cap still `unreadable` with its reason, the wrap note on every point,
  nothing written. The new guard does not over-refuse on the real instrument. (The non-foreground refusal was
  proved through `acquire_main` in the tests rather than staged live, because the application was in front.)
- **Found and named rather than quietly fixed:**
  `tests/test_acquire_live.py::test_a_fingerprint_reads_the_screen_without_pressing_anything` is not
  hermetic — it passes only where a real `TMain_Scr` window is running. The new fake override should make it
  cheap to fix.

## 17. The next slice: launching a batch of recording parameters

**Why this reopens the architecture, on the record.** §9.1 stops the acquisition architecture from growing
until evidence says otherwise. The operator's own statement of the need is that evidence: what exists today
is a campaign that *repeats* one recorded configuration — the fixed facts are campaign-level constants,
verified once before the first point — and the next thing needed is a **batch of recording parameter sets**,
several configurations acquired in one pass. That is not a refinement of the milestone; it is the next
capability. It is written down here so that reopening is a decision with a reason rather than drift.

**This slice has its own planning document, and it is not this one.** The batch's *design* — which
parameters are worth sweeping, which are tied to each other, and which must never be swept — is
[`parameter-sweep-matrix.md`](parameter-sweep-matrix.md), which is planning only ("no code change yet": its
status line). §17 is the code side of that document and nothing more. Two of its conclusions are already
load-bearing here:

- **burst is sweep axis 2** (2 / 4 / 8 / 16 / 32 cycles, observable "first valid gate", tied to PRF through
  `τ_burst = N/f_e ≪ T_prf` and paired with sampling volume through the acoustic-resolution rule) — so burst
  is the knob this slice gives a writer;
- **sound speed is in group S, the frozen scales** (with Doppler angle and velocity scale factor): "pure
  multipliers on the recorded mm and mm/s — sweeping a multiplier measures the multiplier, not the flow".
  So it is *never* swept, and the writer this slice builds must not be pointed at it.

**Out of scope on purpose.** How the batch is *produced* — the matrix, a design of experiments, a generator —
is another matter and stays out. This slice is about *launching* a batch the operator has already written
down, and it does not touch the acquisition recipe itself. It also comes **before** §16.4's experiment,
because that experiment cannot be expressed yet: see 17.1.

### 17.1 What exists, measured against that need

| piece | state |
|---|---|
| the container | **exists** — a batch is a campaign whose points carry their own parameter sets; the definition format, the compile, the per-point loop, the log and the manifest are all in place |
| writing the seven column parameters | **exists** — `ParamRole` covers us frequency, PRF, gates, resolution, velocity-scale factor, emissions/profile and Doppler angle, and the port already has `write_parameter(role, value)` with `apply_point(parameters)` in the runner |
| writing the parameter the batch will actually vary — **burst** | **missing** — burst is read by position out of the Operating-parameters dialog (W1) but has no writer, so a batch that varies it cannot be applied at all |
| writing sound speed | **not wanted, and not a gap** — sound speed is a property of the medium, not a recording parameter. No batch parametrizes it. It stays a *fixed fact*, read and verified before a recording as W4 does now |
| writing first gate | **read-only for now** — same dialog, same mechanism as burst; a writer for burst gives one for this too (a combo on the same panel), so it is a small follow-on when a study needs it rather than part of this slice |
| declaring per-point recording parameters | **missing** — the fixed facts are campaign-level, so a point cannot state its own burst, and the compiled identity records one value for the whole campaign |
| verifying per point | **partly** — reading and comparing exist, but once per campaign, before the first point; a batch that sets a parameter per point has to read it back *after* setting it, on that point |
| surviving a batch | **exists, and matters far more now** — resume proves the identity before skipping, so a batch that dies at point 27 of 40 is resumable; but a batch needs a stopping rule and a per-point record of which parameter set produced which file, or forty recordings become forty unattributable files |

### 17.2 The slice, in order

1. **A writer for burst** — the mirror of W1's read: locate the field by position (its anchors are already
   frozen for reading), write it, then read it back. A write that does not read back as written refuses that
   point, exactly as a disagreement does today. One trap is already measured and must be handled: the burst
   combo steps **past** a value — one step up from `4` landed on `6` — so the writer must select by reading
   the options back, never by counting steps.
2. **Per-point recording parameters** — a point may carry its own values for the facts that have writers; an
   absent value keeps the campaign default. The compiled identity then has to be *per point* (that point's
   values and their sources), because that is what makes two files from one batch distinguishable afterwards.
3. **Per-point verify-then-record** — set, read back, compare, record. The campaign-level check stays as the
   pre-flight, so an invalid definition or a wrong instrument still costs zero points.
4. **A stopping rule and a batch record** — stop at the first refusal (the operator's recovery policy after a
   stranded popup is a restart, so running on past a failure would mean recording into an unverified
   application), and record per point: the parameter set, its sources, the stored file, the outcome.

**Acceptance for the slice.** A batch of at least three parameter sets differing in **burst** (the one
parameter the operator named, and the one that has no writer) runs to completion in one unattended pass; every point's own values are read back and verified before its
recording; every stored file is attributable to its parameter set from the log and manifest alone; and a
deliberately wrong declaration of one point's value refuses **that point** and stops the batch with the
earlier points intact and resumable.

**Still out of scope:** writing any parameter the instrument cannot read back; **parametrizing sound speed**
(a property of the medium, not a setting: it is verified as a fixed fact, never swept); the batch generator; the
analysis; and any new vocabulary — the facts and roles already exist, so this slice gives three of them a
writer and moves an existing check inside the loop.

**Order.** §16.1 and §16.2 come first. A batch multiplies the channel-attribution risk — every point's facts
have to belong to the routed channel — and a traceback per point is unusable in an unattended run, which is
exactly what those two close.


## 18. Turning every knob — the write coverage, measured against the matrix's fifteen

The operator's requirement, stated: before a sweep is worth designing, the tool must be able to *turn every
knob* the matrix can name. This section is the coverage inventory, and it is deliberately keyed to the
matrix's own list (`parameter-sweep-matrix.md`, the control-surface note) rather than to any new vocabulary.

**Three mechanisms exist, and between them every knob has a home.**

| mechanism | state |
|---|---|
| the parameter **column** on the measurement screen | **read *and* written** — `write_parameter(role, value)` over `ParamRole`, with the measured write-order rule (resolution before gates, because this channel has auto-resolution set: 805 gates requested → 474 accepted in the wrong order, 805 in this one) |
| the `Operating parameters` dialog's **positional value table** | **read only** — three columns of caption-less value buttons with their own edits; 15 value fields, of which 10 are bound: the three dialog-only facts `(0,1) burst`, `(1,1) first gate`, `(2,4) sound speed`, and the seven anchors that make those bindings safe to trust. The mechanisms to *write* one already exist and are private: `_combo_select(hwnd, index)` and `_set_text_commit(hwnd, text)`, both taking the field's own hwnd |
| `Record settings` | **neither read nor written.** No path has been exercised to this dialog. It holds the one thing the operator named — `Do not keep in a block more profiles than` — and its in-force value on this machine is what truncates a long point |

### 18.1 The fifteen, and where each one stands

| # | knob | mechanism | read | written |
|---|---|---|---|---|
| 1 | US emitting frequency | column | yes | **yes** |
| 2 | burst length | dialog `(0,1)` | yes | **no** — the slice's first writer |
| 3 | emitting power | not identified | no | no |
| 4 | TGC / amplification | not identified | no | no |
| 5 | PRF | column | yes | **yes** |
| 6 | first-gate depth | dialog `(1,1)` | yes | **no** — same mechanism as burst, one combo over |
| 7 | number of gates | column | yes | **yes** |
| 8 | resolution | column | yes | **yes** |
| 9 | sampling volume | not identified | no | no |
| 10 | emissions per profile | column | yes | **yes** |
| 11 | Doppler angle | column | yes | **yes** |
| 12 | sensitivity | not identified | no | no |
| 13 | velocity scale factor | column | yes | **yes** |
| 14 | sound speed | dialog `(2,4)` | yes | **no** — and per the matrix's group S it is never swept |
| 15 | number of skipped profiles | not identified | no | no |

Five are written today, three more are read and need only the write half of a mechanism that already exists,
and **five are unaccounted for — which is exactly the count of dialog value fields not yet bound** (15 fields
minus the 10 above). The likely mapping is emitting power, TGC, sampling volume, sensitivity and skipped
profiles, and 15 says at least one of them is in this dialog. **That mapping is a hypothesis to confirm by
reading, not an assumption to code against**: the identification method is the one the matrix itself used —
change one knob by hand, re-open the dialog, and see which field moved.

### 18.2 The work, in order

1. **Identify the five unbound dialog fields** — read the table, vary a knob by hand, read it again, and pin
   each field to a knob the way the three dialog-only facts were pinned (with the measured tree committed as
   a fixture, so a re-layout refuses rather than mis-reads).
2. **Give the dialog knobs a writer**, starting with burst: position the field from the same frozen anchors,
   write, then **read back** and refuse if the field does not state what was written — the mirror of W1, and
   the same discipline the column already uses. Measured trap, already paid for: the burst combo steps *past*
   a value (one step up from `4` landed on `6`), so selection must be by value read back from the options,
   never by counting steps.
3. **Decide the cap's status**, because it is the one knob with no path: whether a batch needs the value
   *before* a point (so a long point cannot silently lose its first seconds to the wrap), or whether the
   after-the-fact evidence already in the record — `block_at_cap` / `block_wrapped` on a stored point — is
   enough. If it must be read before, the work is a proven open/close path for `Record settings`, which is
   where the caption-less popup hazard of §9.3 lives; if after-the-fact is enough, this is a sentence in the
   operator notes rather than code.
4. **Then, and only then, the batch** (§17): a batch is only as good as the number of knobs it can set, and
   per-point declaration needs a writer to declare *with*.

### 18.3 The identification pass, as it stands

The method works and is now cheap: `tools/live/probes/dialog_fields.py` — fast, dialog-only, read-only
(opens the dialog through the driver's own gesture, dumps every control, closes it with its left button;
measured 2.5 s, `dialog_closed: true`, no driver notes) — against a **committed** baseline, the measured tree
in `tests/data/udop-parameters-dialog-tree.json`. The operator changes one knob, the probe is re-run, and the
control that moved is the knob.

**First knob pinned — `Number of skipped profiles`.** With the operator's field set from `0` to `2`, exactly
one control in the whole dialog differed from the baseline:

    TSp_Edit (989, 661, 1059, 677) '2'     # column 1, its bottom row, inside the value button
                                           # (808, 653, 1067, 685)

**And the knob is not one control.** Immediately right of it, on the same row, sits `TSp_Button`
`(1077, 660, 1204, 680)` — the operator's "apply skip profile" checkbox, unticked. It is a `TSp_Button`, not
a checkbox class (the dialog contains no `TSp_CheckBox` at all), and the repository already held that exact
rect: `tests/test_acquire_driver.py` names it `HWND_DIALOG_CHECKBOX`, and `docs/dop3000/udop-automation.md`
records "with an `Apply skip profile` checkbox". The knowledge existed in a test fixture and had never
reached the read or write model. Two consequences, and they generalise to every dialog knob:

- **the enable flag is part of the knob** — the writer must set both, and the *reader* must carry the flag as
  well as the value, because a value's source says nothing about whether a second control has it in force;
- with the flag unticked the value is **inert**: the application behaved identically, exactly as the operator
  observed. A run that read `2` and reported "2 skipped profiles" without the flag would be claiming a
  recording this instrument was never configured to make — the channel-mismatch failure in a different
  costume.

### 18.4 Power is coupled to TGC mode — and this machine's TGC is in auto

Moving `Emitting power` from Medium to High raises a modal warning on the application itself:

> The TGC is in auto mode. Changing the emitting power will modify the TGC mode and amplification.
> Cancel / Continue

Three things follow, and the first is the one that matters for the matrix.

- **A power sweep on this instrument is not a one-knob sweep while TGC is in auto.** Changing power rewrites
  the TGC mode *and* the amplification, so a recorded amplitude difference across power levels would carry
  the TGC change with it and the comparison would measure both at once. The operator's own practice is to run
  manual TGC; the machine is presently in auto (a fresh install's default, or the AI/assisted mode — to be
  inspected). This is a *design* consequence for `parameter-sweep-matrix.md`, not a code one: a power axis
  needs TGC mode fixed and recorded first, exactly as the matrix already requires for co-set parameters.
- **The coupling is itself a fact worth reading.** The warning is the application *telling us* that two more
  quantities are about to move. A pre-run reading that captured TGC mode and amplification would let a compile
  refuse a power change made while the machine is in a state the definition does not declare — the same shape
  as the fixed-fact refusal, one surface further out.
- **A modal dialog is a hazard for the identification harness.** The driver's guard checks that the main
  window is foreground; it knows nothing about a modal sitting in front of it, so a probe that opens the
  parameters dialog by gesture could press into the wrong surface. The rule for the pass: **nothing modal is
  ever left open while a probe runs** — cancel or commit first, then read.

Recorded here rather than in the code because nothing in this slice should act on it until the matrix says
which axis it belongs to and the operator has settled the TGC mode question (auto vs manual, and whether the
assisted mode forces auto).

### 18.5 What the first knob taught the reader and the writer

Pinning `Number of skipped profiles` produced two rules worth more than the field itself.

**A dialog value field needs an explicit commit keystroke.** The operator typed `0` over the `2` and the
field kept its old value until they pressed **Enter**; with Enter, the next read shows `0` and *only* that
control differs from the baseline — twice over, once each direction (`0 → 2` and `2 → 0`, one control in the
whole dialog moving each time). So the reader is exact, and the writer must commit the text, not merely set
it. The driver already has that discipline for the measurement screen's own fields
(`_set_text_commit`), which is the name to look for when the dialog writer is built.

**The dialog's value fields are not where every fact comes from.** The fifteen `TSp_Edit` cells carry
`4000 | 89 | 89 | 40` (column 0), `212 | 2 | 797 | 0.122 | 89 | 0` (column 1) and
`150 | 0 | 89 | 0.68 | 1460` (column 2) — and **no `4` anywhere**, even though the run reports burst length
`4` with source `read`, and the burst field is bound to `(0,1)`. Since the dialog also contains five
`TComboBox` controls and burst is a combo (the combo-steps-past-a-value measurement), the likely explanation
is that burst is a **combo**, not an edit, and therefore never appears in the edit table at all — with the
consequence that the `(0,1)` binding's comment and the edit at `(0,1)` (which reads `89`) describe different
things. Open until the operator reads the dialog's painted labels, which are invisible to every API read in
this repo.

### 18.6 The dialog, cell by cell — the five unaccounted knobs are accounted for

Drop the edit-only view (18.5): a cell's **value may be held by a combo**, not an edit, so the table has to be
built from the `TSp_Value_Button` cells and whatever controls sit inside them. Done that way, the whole dialog
is identified, and every knob in the matrix's fifteen now has a home and a control class:

| cell `(col,row)` | knob | value now | control the value lives in |
|---|---|---|---|
| (0,0) | US emitting frequency | `4000` | edit |
| (0,1) | **burst length** | `4` | **combo** — the operator reads its entries as 2,4,6,…,20,24,28,32 |
| (0,2) | **emitting power** | `Medium` | **combo** (three levels, as the matrix says) |
| (0,3) | **TGC / amplification** | `40` | edit |
| (1,0) | PRF | `212` | edit |
| (1,1) | first-gate depth | `2` | edit |
| (1,2) | number of gates | `797` | edit |
| (1,3) | resolution | `0.122` | edit |
| (1,4) | **sampling volume** | `0.876` | **combo** (the bandwidth list — read it, never hard-code a mm value) |
| (1,5) | **number of skipped profiles** | `0` | edit (+ the `TSp_Button` "apply skip profile" enable, 18.3) |
| (2,0) | emissions per profile | `150` | edit |
| (2,1) | Doppler angle | `0` | edit |
| (2,2) | **sensitivity** | `medium` | **combo** |
| (2,3) | velocity scale factor | `0.68` | edit |
| (2,4) | sound speed | `1460` | edit |

Plus one control *above* the value table that the table does not contain: a combo stating the **channel**
(`1` on this machine) — the field the §16.1 attribution check reads.

**Consequences for the writer (18.2), and they are now concrete.**

- **Four of the fifteen are combos** (burst, power, sampling volume, sensitivity), so the dialog writer is two
  writers, not one: `_combo_select`-style selection by value for those, `_set_text_commit`-style text with its
  commit keystroke for the rest (18.5). Both private helpers already exist for the measurement screen.
- **The combo traps apply directly**: select by the value read back from the options, never by counting steps
  (one step up from burst `4` landed on `6` on this machine, and the operator's own reading shows the entries
  are not contiguous — 2,4,6,…,20,24,28,32).
- **`(0,1)`'s binding was right all along** and 18.5's puzzle is resolved: the binding addresses the *cell*, and
  the value is in the cell's combo, so an edit-only scan could never see the `4`.
- **A cell can contain more than one child**, so the reader must bind the specific control it means rather than
  "the first thing inside the cell": several cells also carry a `TSp_Edit` reading `89` that is not the cell's
  own value. Which of those is the sampling volume's own thickness readout is still open — cheap to settle,
  but it must be settled before any reader binds by containment alone.

**Still unanswered by eye:** the painted labels. Values and classes now agree well enough to identify every
cell, but only the operator can confirm that the cell at (0,2) says "emitting power" beside its `Medium` and
that the `40` at (0,3) is the TGC — the two assignments this table infers from value shape rather than label.

### 18.7 What the recon archive already established

The private instrument-side archive (`C:\Repos\dop-control`, read-only, another repository) worked this
surface for a day before this plan did, and it already answers three of §18's open items. Its documents are
claims, its captures and logs are evidence; both are named below. **Most of it has already landed in this
repository** as `docs/dop3000/udop-automation.md` §§2, 3, 6, 9 — the write recipes, the write order and the
word map — which §18.1–§18.8 above never cite. Read that file rather than re-derive a recipe from the manual.

Sources: `docs/13-dialogs-operating-and-trigger.md` (the painted dialog), `docs/14-input-methods.md` (what input
commits), `docs/15-labelled-fixture.md` (a word map from a labelled recording), `docs/16-record-strip-automation.md`
§§12–14 (write order, the burst coupling, the record cycle), `docs/10-stable-binding.md`, `docs/03-ui-control-map.md`,
`docs/06-open-questions.md`, `docs/07-landing-in-udv-echo-process.md`; probes `recon/04`, `05`, `11`–`15`, `23`,
`24`, `40`–`41`, `50`–`63`; captures, JSON and logs in `recon/out/`.

**The labels, from a second and independent capture.** `recon/out/dialogs/operating-panel.png` (2026-09-17
14:21) renders the dialog with its painted labels; read again for this digest it is §18.6's grid, cell for cell,
and it agrees row for row with §18.8's vision pass — including the two assignments §18.6 could only infer from
value shape: **(0,2) is `Emitting power` beside its `Medium`, (0,3) is `Tgc [dB]` beside its `40`**. Column order
left → `US Frequency` / `Burst length` / `Emitting power` / `Tgc [dB]`, middle → `PRF` / `First gate depth` /
`Nb of gates` / `Resolution` / `Sampling volume` / `Number of skipped profiles`, right → `Emissions/profile` /
`Doppler angle` / `Sensitivity` / `Velocity scale factor` / `Sound speed`. The same capture shows the header's own
channel combo (`for channel [10 ▼]`), the green painted note `Sampling volumes overlapped`, a **greyed**
`[ ] Apply skip profile` beside the count at `0`, and the two crossed indicators the band also carries. Two
independent readings of the same labels now exist, which is why the label question can be closed.

**The dialog's geometry is this machine's geometry. Three sessions, identical rectangles.** The archive's panel
is `(655, 364, 1282, 748)` with the skipped-profiles edit `(989, 661, 1059, 677)` inside its cell
`(808, 653, 1067, 685)` and the enable button `(1077, 660, 1204, 680)`; the committed
`tests/data/udop-parameters-dialog-tree.json` and §18.3 carry exactly the same three rects. The *ids* in the same
dumps are fresh on every launch — `docs/10` measured **1 of 43** control ids surviving a relaunch (the inner edit
of a combo), everything else a per-instance handle. **Positions are reusable; ids are not**; that is why §18.6's
cell grid is the right binding and a stored id is not.

**The fifteen, and what the archive established about writing each.** Confidence vocabulary: *measured* — a log,
capture or stored file backs it; *operator-reported*; *mechanism-level* — the recipe is measured on a sibling
control of the same class, this field never exercised; *documented only* — nothing was ever written.

| # | knob | archive's painted label · class · where | what the archive established about WRITING it | confidence |
|---|---|---|---|---|
| 1 | US emitting frequency | `US Frequency [kHz]` · edit · column | text recipe (`WM_SETTEXT` + `WM_COMMAND(EN_CHANGE)` + `WM_KEYDOWN`/`WM_KEYUP VK_RETURN`), then read back; this field itself never written | mechanism-level |
| 2 | burst length | `Burst length 4 ▼` · **combo** · dialog (0,1), **no column field** | **dialog-only write**; combo recipe (`CB_SETCURSEL` + `CBN_SELCHANGE`, no Enter) then `Accept`; **coupled** — writing burst re-selects the sampling volume by itself (up: raises it; down: selects the minimum entry); never select by counting steps | dialog-only + coupling are **operator-reported** (`docs/16` §13): `recon/41`, written to confirm it, has **no output in `recon/out/`** |
| 3 | emitting power | `Emitting power Medium ▼` · combo · dialog (0,2) **and** the column (`Emitting power`, items `Low`/`Medium`/`High`, `sel=1`) | the column combo's identity and item list are measured (`recon/15`, `recon/out/combo/combo-probe-20260917-142827.json`); write = combo recipe + `Accept` | identity + options measured; write mechanism-level |
| 4 | TGC / amplification | `Tgc [dB] 40` · edit · dialog (0,3) | text recipe; read-back target `word 42` (`probable`; `40` also appears in word 96) | documented only |
| 5 | PRF | `PRF [us]` · edit · column | text recipe; `word 5` tracks it exactly in both labelled files | measured (in file) |
| 6 | first-gate depth | `First gate depth [mm] 2` · **edit** (no ▼) · dialog (1,1) | text recipe; `word 9` is a gate **index** (`31` at 2 mm → `57` at 5 mm, the two labelled fixtures); written with the structure pair (see the order rule) | word identity measured; write unexercised |
| 7 | number of gates | `Nb of gates` · edit · column (+ dialog cell (1,2)) | **the archive's best-measured write.** `WM_SETTEXT` + `EN_CHANGE` + `VK_RETURN` commits; `WM_CHAR` Enter does **not** (requested `50`, the dialog kept reporting `100`/`Depth 27 mm` under `WM_CHAR` and `50`/`Depth 14 mm` under `VK_RETURN` — `recon/23`, captures `recon/out/commit/verify-200-*.png`). And the column write lands in **channel 1** while the status bar read `CH: 10` | measured, twice, against the app's derived `Depth` and the stored file |
| 8 | resolution | `Resolution [mm]` · edit · column | text recipe; the app **snaps** to its ladder rung and shows 3 decimals (`0.121667` → `0.122` — the app's rounding, not a failure); achieved rung from `word 10`: `resolution_mm = (word10 + 1) · c / 12000` | measured (file) |
| 9 | sampling volume | `Sampling volume [mm] 0.900 ▼` · combo · dialog (1,4) | **not ours to choose**: write burst, read the volume back; `word 27` is the **index** (`3` = 0.900 mm at `c = 1500`); the option list is physics-driven (`c`, `f_e`, burst) so never hard-code an mm value; a volume below the burst's floor raises `Warning — The burst length should be reduced [Continue]` = a rejection, not a crash | index↔mm pair measured at `c = 1500` only; the option list was **never dumped**; coupling operator-reported |
| 10 | emissions per profile | `Emissions/profile` · edit · column | the archive's *first* measured write: written, then verified through the derived status-bar `Time between profile` (24.9 → 44.8 ms for 200 µs × 200), then restored (24.7 ms) | measured, with the archive's own caveat: simulation build (`docs/03` §4, `docs/06` item 4) |
| 11 | Doppler angle | `Doppler angle 0` · edit · column | text recipe; `word 20` moves with it (`0` → `7` in the diff) | word measured; write unexercised |
| 12 | sensitivity | `Sensitivity medium ▼` · combo · dialog (2,2) **and** the column | **write measured**: `CB_SETCURSEL(0)` + `CBN_SELCHANGE` → the application read `sel=0 item='very high'`, **no Enter needed**; restore `sel=2 item='medium'`. Trap: writing it *back* set the control while the app kept painting the old value — `CB_GETCURSEL` reports the control's belief, not the model's. Column options measured: `very high, high, medium, low, very low` (`sel=2`) | recipe + options measured; `word 18` (`8` = medium, `12` = low) is **ambiguous with TGC** (`docs/15` §3) |
| 13 | velocity scale factor | `Velocity scale factor 1.00` · edit · column | text recipe; `word 15` (`3141`/`3142` both = 1.00). On the archive's machine the factor printed `1.00` beside the derived `Velocity scale 468.7 mm/s` — the factor is the input, the mm/s readout is derived | word measured; write unexercised |
| 14 | sound speed | `Sound speed [m/s] 1500` · edit · dialog (2,4) | text recipe; `word 19` verified; the dialog "confirms the resolution ladder law `rung = c/12000` independently of the snapping experiment" | word measured; write unexercised; never swept (matrix group S) |
| 15 | number of skipped profiles | `Number of skipped profiles 0` + greyed `[ ] Apply skip profile` · edit + `TSp_Button` · dialog (1,5), enable at `(1077, 660, 1204, 680)` | `word 84` confirmed by label; **no write**: the archive has nothing on the enable's own enabling condition | identity measured both sides; write unexercised |

**Bindings worth reusing, with the archive's own paths.**

- `recon/udop_roles.py::resolve()` — roles → live handles from *class + position inside the client area*;
  `click_hold` = posted `WM_LBUTTONDOWN` / ~180 ms / `WM_LBUTTONUP`. Re-resolve at attach; ids are per-launch
  (`docs/10`).
- **The dialog's open gesture**: `recon/41_burst_sampling_volume.py::open_operating_parameters` (lines 109–135) —
  `SetCursorPos(204, 40)` onto `Parameters` plus one short real `mouse_event` move (the overlay opens on hover
  *only*), then a **held posted press** on the entry whose screen `top` is smallest. Entry tops `[61, 95, 130,
  165, 205]`; entry 0 is `Operating parameters`, entry 1 at `(190, 95)` is `Default parameters` — pressing it by
  enumeration order is what raised a modal panel (`docs/16` §13a). Ported already (`handoff-dop3010-acquisition.md` §2).
- **Close/commit**: sort the dialog's bottom-band `TSp_Button`s by `left` → `row[-2]` = `Cancel`, `row[-1]` =
  `Accept`. The band holds **four** buttons: `(663, 712)` and `(862, 712)` are the wide *indicators*, the pair is
  narrow (`Cancel (1091, 703)`, `Accept (1183, 702)`) — never press the leftmost (`task-52`, `task-54` logs).
- **The channel combo is the dialog's header** (`(1083, 373)`, items `1`…`10`), and **writing it replaces the
  dialog**: measured `(655, 364) → (713, 364)`, "every handle taken before the write is dead"
  (`recon/out/menu-probe-20260917-213139.json`). Read it for §16.1's attribution; treat a channel *change* as a
  re-open, not a same-dialog write.
- Read-back oracles, in order of strength: the dialog's derived `Depth` (`first gate + gates × resolution`) and
  `Velocity scale`; then the stored file's words — `2` depth, `5` PRF, `8` burst, `9` first-gate index, `10` rung
  index, `13` gates, `14` emissions, `15` scale factor, `18` sensitivity, `19` sound speed, `20` Doppler angle,
  `27` sampling-volume index, `42` TGC, `84` skipped. **Name the channel in every read**: the column wrote
  channel 1 while the status bar said `CH: 10`.
- The trigger dialog's painted values land in the file too (`Pre Trigger 0` → word 35, `and record 10` → 48,
  `Repeat the sequence 1 times` → 49; capture `recon/out/dialogs/tigger-panel.png`) — the same painted-value →
  file-word chain, on the axis `docs/16` puts out of scope for the sweep.

**Where the archive and today's measurements disagree — ruled, not averaged.**

| # | disagreement | ruling |
|---|---|---|
| D1 | `docs/10` orders combos "by top → sensitivity, emitting power"; today's cells put the four dialog combos in different columns | **Both are right, scoped differently, and the rule is what travels.** `docs/10` describes the *column's* two combos (both at `x ≈ 12`, rows 352 and 377). The dialog holds five, and ordered by `top` they are channel `373`, burst `488`, sensitivity `522`, power `526`, sampling volume `600` — so the column's ordering must **not** be used to bind the dialog's combos; the dialog's are bound to *cells* (§18.6). What to reuse from `docs/10` is its measurement (ids die per launch, 1 of 43 survives) and its rule (resolve by role at attach time), not its list. |
| D2 | the archive's dialog prints `Sound speed 1500`, `Sampling volume 0.900`, `Nb of gates 100`, `Resolution 0.250`, PRF `200`, emissions `100`, scale factor `1.00`, channel `10`; today's prints `1460 / 0.876 / 797 / 0.122 / 212 / 150 / 3.168 / 1` | **Same dialog, different channel and medium configuration** — the archive's own record explains it: the operator changed `c` to 1460 m/s and the *column* edits channel 1, while the archived point was configured on channel 10 (`docs/16` §§12, 12a; `docs/15` §1). Consequence for the bindings: bind cells by `(col,row)` **geometry**, never by value; the sampling volume must be selected by its painted mm value and **not by index** (index `3` = `0.900` at `c = 1500`; the index↔mm pair was only ever pinned at `c = 1500`); the resolution ladder follows `c` (0.125 rung at 1500 vs 0.1217 at 1460). |
| D3 | the archive contradicts itself: `docs/14` §1's matrix row says sidebar numeric fields **do not commit**, while `docs/14` §5 and `docs/16` §12a say they do | **§12a supersedes** — the "disproof" had decoded the wrong channel's block. The stale row is why every rule here reads "verify against the app's model or the file, never a control's text". |
| D4 | the archive's provenance: `docs/03` says the captured instance had **no instrument attached** (simulation mode) and `docs/06` item 4 / `docs/15` §4 leave "does the instrument accept a message-written parameter" **open**, while this repo's `udop-automation.md` header calls its rules "verified on a live DOP3010" | **Neither is wrong, and the distinction still matters.** Same executable choosing its mode at runtime (`docs/03`), so the recipes transfer; but the archive never closed the rig-acceptance question, so today's live session is what closes it (or the item stays open — it is not closed by the archive). |
| D5 | inside §18: §18.1 lists first-gate depth as "same mechanism as burst, one combo over" | **Wrong, and §18.6 supersedes it**: first gate is an **edit** (no ▼ in the archive's capture; a `TSp_Edit` reading `2` in today's tree). Also §18.1's "five are unaccounted for" was already answered before the live pass — the archive had identified power, sensitivity, sampling volume and TGC by their painted labels and by option lists; the live pass's genuine addition is the **class per cell** and the skip-profile enable. |

**Stale in the archive, so do not port it.** `docs/07`'s proposed `acquire/` tree (`control_map.py`, `watch.py`,
`health.py`, `plan.py`) is not what landed here — reference it for the reasoning, never for the module list.
`docs/03`/`docs/06` item 1's `recon/control-map.json` bindings are one-process-lifetime only (`docs/10`) and were
built in simulation mode; `docs/06` items 3, 5 and 9–12 (auto-record filenames, archive-by-content policy, the
`Record settings` questions) are still open here as well. The archive's `recon/15` combo probe also needs one
correction: the **first `TComboBox` inside the dialog is the channel selector** (`sel=9` = `10`), not sensitivity
(`docs/14` §5) — the same trap today's tree warns about.

**What each side has that the other does not.**

| | archive | today's §18 |
|---|---|---|
| has | painted labels (the capture), measured option lists for the column's power/sensitivity combos, the measured commit recipes for both classes, the burst ↔ sampling-volume coupling and its rejection warning, the write-order rule with its 474-vs-805 evidence, the word map (i.e. write-verification targets for the fifteen knobs), the four-button band + indicator hazard, the dialog-rebuild-on-channel-write hazard, the trigger dialog ↔ words 35/48/49 cross-check, the derived `Depth`/`Velocity scale` read-backs | the TGC-auto × power coupling and its modal warning (§18.4), `Apply skip profile` as a control with an inert value (§18.3), the class-per-cell table and a committed dialog tree (§18.6), `Record settings`'s cap as the one knob with no path, and the code: `write_parameter(role, value)` over `ParamRole`, `_combo_select` / `_set_text_commit`, the `(0,1)`-cell insight, the "one step up from burst `4` landed on `6`" measurement, §16.1's channel-attribution check, the vision pass (§18.8) |

**What genuinely still needs measuring live** (each is one probe run; none needs a recording except where noted).

1. Whether each dialog-cell **edit** write commits *and survives `Accept`* — `Tgc` (0,3), first gate (1,1),
   sound speed (2,4). Only `Number of skipped profiles` is operator-measured today.
2. The dialog's **combo option lists** (burst, power, sampling volume) by `CB_GETCOUNT`/`CB_GETLBTEXT`, and whether
   the strings are identical to the column's for the two knobs that exist twice (`Medium`, `medium`).
3. The accepted `(burst, sampling volume)` pairs at `c = 1460`, `f_e = 4000`, and what the
   `burst length should be reduced` warning does to the pending burst — rejected, or applied anyway.
4. `Apply skip profile`'s own enabling condition (greyed at `0` in the archive's capture) and the count → enable
   order.
5. Whether a `Tgc [dB]` write sticks while TGC is in auto, whether it raises the TGC modal, and `word 42` as the
   oracle (§18.4's open question).
6. Which surface is authoritative for the two knobs that exist twice — the column combo or the dialog cell. The
   archive wrote only the column; §18.2's writer plans only the dialog.
7. `word 1` = `assisted Mode` (`recon/58`, `recon/59`, the manual's table) as a **readable** form of the state
   §18.4 wants captured before a power change — one stored file per channel settles it.
8. `word 18` vs `word 42` (one recording that moves only sensitivity — `docs/15` §3's own cheapest experiment).

### 18.8 The labels, read off the pixels — and which source to trust for what

Screenshot-plus-vision — the route the earlier prototyping used and dropped when vision detoured through a
lossy auxiliary path — is back, because it is the only way to see a painted label. `tools/live/probes/dialog_shot.py`
captures the dialog's own rect and the full screen as lossless PNGs in about four seconds, asserts both images
are non-blank, checks the frame is stable, reports the DPI status, and closes the dialog; with
`model.supports_vision: true` the parent reads the actual pixels.

**The dialog, as printed** (channel 1):

| column | rows, top to bottom |
|---|---|
| 1 | `US Frequency [kHz]` 4000 · `Burst length` 4 ▼ · `Emitting power` Medium ▼ · `Tgc [dB]` 40 |
| 2 | `PRF [us]` 212 · `First gate depth [mm]` 2 · `Nb of gates` 797 · `Resolution [mm]` 0.122 · `Sampling volume [mm]` 0.876 ▼ · `Number of skipped profiles` 0  +  `[ ] Apply skip profile` |
| 3 | `Emissions/profile` 150 · `Doppler angle` 0 · `Sensitivity` medium ▼ · `Velocity scale factor` 3.168 · `Sound speed [m/s]` 1460 |

Header: `Operating parameters for channel 1` — the channel combo of §16.1. Read-only readouts above the table:
`Depth = 99 mm`, `Velocity scale = 292.1 mm/s`. A green note under sampling volume: `Sampling volumes
overlapped`. At the foot, two items marked with a red X and not enabled (`No emission on Probe In/Out`,
`Use US coupling parameters`), and the buttons `Cancel` / `Accept`.

**Two source rules, both earned in this comparison.**

- **Labels exist only in the pixels.** Every text read through this repo's APIs returns empty for these
  controls, so the label map could only come from an image. It confirms §18.6 row for row, including the two
  assignments that could only be inferred from value shape there: TGC `40`, emitting power `Medium`.
- **Neither source is sufficient alone, and a scaled-down reading fails in a specific way.** A vision
  transcription of this image reported `Tgc 10`, `Resolution 3.122`, `Doppler angle 3` and `Sound speed 1450`
  — four misread digits, all four contradicted by the API read. The same failure then caught this document's
  own author: the `Velocity scale factor` box was read as `3.168`, and the operator's check says `0.68`.
  Zoomed to full resolution the box plainly prints `0.68` — the `0` is clipped by the edit's frame, and at
  627x384 the clipped glyph reads as a `3`. So the rule is: **values from the API, labels from the pixels, and
  any number that matters either zoomed to full resolution or cross-checked**. The API was right about every
  disputed value in this dialog, including this one.

**Open item, carried into the writer slice.** The stray `TSp_Edit` controls reading `89` (three of them)
correspond to no value printed in the dialog and remain unexplained — though they are **not** implicated in the
`Velocity scale factor` error, which was a reading artifact rather than a binding error. A reader must still
bind the specific control it means, never "the first thing inside the cell", and pinning each cell's own
control is the first thing the writer must settle.

**Harness trap, paid for once.** `./tools/live/dispatch.sh tools/live/probes/<probe>.py` does **not** run the
probe: the launcher joins its argument onto the probe directory, finds nothing, and returns without writing a
log — so the dispatcher polls for a line that can never appear. The working form is the bare name:

    PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_fields.py

Two "probe runs" were lost to this, including a dialog read that never happened, so a baseline taken that way
is not trustworthy (and, being a non-run, it also never touched the application).

**Acceptance for the knob work.** Every knob the sweep matrix names is either written by the tool or
explicitly recorded as unreachable with the reason; every dialog-written knob is read back and verified on the
point that used it; and a wrong write (a value the combo does not offer, a field that is not there) refuses
the point rather than proceeding.

### 18.9 The first dialog write, measured

`tools/live/probes/dialog_write.py` (committed with this record) is the first thing in this
repository that *changes* the instrument through the dialog. Three modes on the driver's own steps —
`dump` (inventory + photograph), `write --burst N [--volume V]` (select the cell's combo entry, then
`Accept`, then re-open and dump), `compare` (diff two dumps control by control and cell by cell).
It refuses rather than presses: a value the combo does not offer, a cell whose class is not the one
bound to it, a modal warning, and the header channel combo are all off its path.

**The round trip, measured.** Channel 1, `c = 1460`, `f_e = 4000`, dialog `(655, 364, 1282, 748)`
with 42 controls — the same geometry as §18.6/§18.8, unchanged by every write below.

| step | what was pressed | what the dialog said |
|---|---|---|
| baseline | nothing (closed with its left button, `Cancel`) | burst `4` (index 1), sampling volume `0.876` (index 0), 14 other cells as §18.8 |
| write | point `(0,1)`'s combo → the entry whose own text is `2` (index 0) | *same dialog, before* `Accept`: burst `2`; **every other cell identical** |
| commit | the band's rightmost `TSp_Button` `(1183, 702, 1263, 727)` | dialog closed, nothing raised |
| read back | re-open | burst `2`; **sampling volume still `0.876`, index 0**; all 14 other cells as baseline |
| restore | `(0,1)` → the entry `4` (index 1), `Accept`, re-open | burst `4`; nothing else moved |
| proof | one more independent `dump` | 42/42 controls identical to the baseline **in the same order**, every cell identical, and the dialog-rect PNG **byte-identical** (`sha256 617e23cf…`) |

Two controls moved for the burst write and both are the knob's own widgets: the cell's `TComboBox`
`(783, 488, 861, 509)` and its inner `Edit` `(786, 491, 841, 506)`, each `4` → `2`. Nothing else in
the dialog changed — no unrequested value, no rebuilt control, no new or missing cell.

**The message sequence that worked** — the archive's combo recipe, unchanged: `CB_SETCURSEL(index)`,
then a posted `WM_COMMAND` carrying `CBN_SELCHANGE << 16 | control id` and the combo's handle **to
the combo's parent** (the cell's value button). **No `WM_SETTEXT`, no Enter, no cursor, no
keystroke.** The `Accept` is the driver's ordinary button press: a posted `WM_LBUTTONDOWN` held
~180 ms then released on `row[-1]`; the band held four `TSp_Button`s and the two wide indicators were
never touched. `CB_SETCURSEL` on its own would have set the control's belief and left the model
alone — the same shape as the archive's column-combo trap — so the notification is what this rests
on.

**Coupling: measured NOT to move, and the operator rule that did not reproduce.** §19.2 and the
archive (`docs/16` §13) both predict that writing burst re-selects the sampling volume. At
`c = 1460`, `f_e = 4000` it did not, in either direction:

| burst | sampling volume before | after the write (same dialog) | after `Accept` + re-open | the volume's option list |
|---|---|---|---|---|
| `4 → 2` | `0.876` (index 0) | `0.876` (index 0) | `0.876` (index 0) | unchanged |
| `2 → 4` | `0.876` (index 0) | `0.876` (index 0) | `0.876` (index 0) | unchanged |

"Reducing burst selects the minimum entry" did **not** reproduce here: the minimum on this list is
`0.584` and the selection never left `0.876`. The downward direction was run twice (a first run that
put the state back after an earlier write, and the restore this round trip ends with) with the same
result, and the accepted pairs are therefore `(4, 0.876 @ index 0)` and `(2, 0.876 @ index 0)`. The
upward direction beyond `4`, and a burst large enough to move the volume's *list*, stay unmeasured —
they are the cheap next probe, not a conclusion from this one. `word 8`/`word 27` remain the oracles
that would name the pair in a stored file; nothing here reads a `.BDD`.

**The option lists, dumped for the first time** (§18.7's open item 2, first half):

| combo | items, in the order the control holds them | selected |
|---|---|---|
| burst `(0,1)` | `2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32` | index 1 (`4`) |
| sampling volume `(1,4)` | `0.876, 3.650, 1.752, 1.168, 0.876, 0.730, 0.584` | index 0 (`0.876`) |

Three rules fall out of those two rows, and each cost nothing here only because the probe was written
against them:

- the burst list is exactly the operator's reading (§18.6) and is **not contiguous** above `20` — a
  step-counting writer writes a different burst, and a value-based one is the only safe one;
- the volume list is **unordered, holds `0.876` twice, and keeps the currently-held value at index
  0**: "select by value, never by index" is necessary but not sufficient, because a value-based
  restore of `0.876` matches two entries. Measured rule: match the entry's own text and take the
  **lowest** matching index — that is the one the application itself leaves selected, at baseline and
  after both writes;
- the burst cell holds **two** controls stating the same value (the combo and its inner `Edit`). "The
  first thing inside the cell" gets one of them by luck; the cell's value is the combo (§18.6).

**The verify rungs of §19.1, as this run could check them.**

| rung | result | what backs it |
|---|---|---|
| 1 — the field states what was written | measured on the field; **not obtainable as a model-only read** | the cell's combo read `2` (own text and `CB_GETCURSEL` 0) before `Accept`. Nothing else in the open dialog states the burst, so the *control's belief* is not separable from the model's here — the archive's sensitivity trap (`CB_GETCURSEL` reports the control) is the reason that distinction matters. |
| 2 — after `Accept`, the re-opened dialog agrees | **passed** | the re-opened dialog read `2` with all 14 other cells identical; and in the other direction the re-opened dialog read `4` with the final dump identical to the baseline (controls in the same order, the dialog PNG byte-identical) |
| 3 — the stored `.BDD`'s word | **not attempted** | it needs a real recording on the channel, which a dialog round trip is not. `word 8`/`word 27` stay unread for this change. |

**Two consequences for §19, from the same measurement.** The dialog's **derived readouts are not an
oracle for this knob**: `Depth = 99 mm` and `Velocity scale = 292.1 mm/s` were printed identically
across burst `4 → 2` (read off the full-resolution crop, §18.8's rule), because neither depends on
burst. So rung 2's named evidence for a burst write is the re-opened table, not the painted pair.
And **rungs 1 and 2 are not independent for this dialog**: the only statement a combo's value has
inside an open `Operating parameters` dialog is the control itself, so rung 1 collapses into rung 2 —
the writer should treat the re-opened read as the field's own verification rather than claiming two
rungs, and only a stored file gives a truly second, independent witness.

**No modal appeared anywhere in the run** — not on the burst change and not on the `Accept`, so
`Warning — The burst length should be reduced` did not reproduce for `4 → 2` (its trigger is a
*requested volume* below the burst's floor, and nothing here requested a volume). The probe's own
guard still stands: it dismisses a warning with its leftmost button when the band holds two or more,
and refuses to press a single-button warning at all, because that one button is `Continue`.

**Artifacts**, all under the gitignored `outputs/live/`: `dialog-write-baseline.json` (also
`-baseline.png` + `-baseline-full.png`), `dialog-write-burst2.*`, `dialog-write-restored.*`,
`dialog-write-final.*`, the five `dialog-write-compare-*.json` diffs, and each run's log as
`run-*.log` (the dispatcher's own log, `task-dialog_write.py.log`, is overwritten per run, so it is
copied out under a name that says which run it was). `dump` costs 3.6 s, `write` 8.5 s — both
dispatchable with `PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py <mode> …`. One
process note: the first
write run recorded its per-cell summary through a helper that compared an integer to a dictionary
and so reported the two cells as missing; no write or read of the instrument was affected (the
dumped tables were correct), and the run was repeated so that every dump in this record comes from
the committed build.

### 18.10 Sampling volume: what a below-floor write actually does

The round trip §18.9 left open: the volume written **up** the list, a volume written **below the burst's
floor** and its modal answered, the burst moved to `8` and back to `4`, the volume written back **down**,
then both restored and diffed against the baseline. `tools/live/probes/dialog_write.py` grew a fourth mode
for it — `below-floor` (request a volume the floor does not allow, record the modal, answer it, re-read the
field, `Cancel`, refuse) — and its `write` mode now ends in a `read_back` verdict: the re-opened dialog's own
statement of both cells against the request, `refused` when they differ. `--burst` became optional so a
**volume-only** write is expressible, and `compare`'s `load` now resolves relative paths from the repository
root like `--out` does (the first compare run died with `FileNotFoundError` because it did not).

Every step is one dispatch, each one `open → dump + capture → write → Accept → re-open → dump + capture`, and
the dialog was never left open between them:

```bash
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py dump  --out outputs/live/sv-01-baseline.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py write --volume 3.650 --out outputs/live/sv-02-volume-3650.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py below-floor --volume 0.584 --answer safe     --out outputs/live/sv-03-belowfloor-safe.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py below-floor --volume 0.584 --answer continue --out outputs/live/sv-04-belowfloor-continue.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py write --burst 8 --out outputs/live/sv-05-burst8.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py write --burst 4 --out outputs/live/sv-06-burst4.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py write --burst 4 --volume 1.168 --out outputs/live/sv-07-volume-1168.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py write --burst 4 --volume 0.876 --out outputs/live/sv-08-restored.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py dump  --out outputs/live/sv-09-final.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py compare --baseline outputs/live/sv-01-baseline.json --after outputs/live/sv-08-restored.json --out outputs/live/sv-compare-baseline-restored.json
PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py compare --baseline outputs/live/sv-01-baseline.json --after outputs/live/sv-09-final.json    --out outputs/live/sv-compare-baseline-final.json
```

**The below-floor write, measured twice.** Requesting `0.584` at burst `4` raised the warning **on the
select's own notification** — not on the `Accept`, which was never reached — and the field, re-read in the
same dialog after the modal was answered, stated `3.650`: the value that was there **before** the request,
not the burst-implied one (`0.584 < 0.730 =` the floor at burst `4`). The operator's model is confirmed, and
`Continue` applies nothing.

| step | dialog's own statement after the previous step | what was requested | the modal | the field, re-read after the answer |
|---|---|---|---|---|
| `01` baseline | burst `4`, volume `0.876`, 42 controls at `(655, 364, 1282, 748)` | — | none | — |
| `02` | burst `4`, volume `0.876`, list `[0.876, 3.650, …]` | volume `3.650` | none | **accepted**: `3.650` (index 1), list `[3.650, 3.650, …]` |
| `03`+`04` | burst `4`, volume `3.650` | volume `0.584` | `warning` at `(772, 490, 1164, 622)`, one button at `(1070, 587, 1154, 612)` | **`3.650`** — the previous value; the request was dropped, nothing committed (the dialog was left with its `Cancel` both runs) |
| `05` | burst `4`, volume `3.650` | burst `8` | none | **accepted**: burst `8`, volume **still `3.650`** (index 0), list unchanged |
| `06` | burst `8`, volume `3.650` | burst `4` | none | **accepted**: burst `4`, volume **still `3.650`** |
| `07` | burst `4`, volume `3.650` | volume `1.168` (and burst `4`) | none | **accepted**: `1.168` (index 3) |
| `08` | burst `4`, volume `1.168` | volume `0.876` (and burst `4`) | none | **accepted**: `0.876` (index 0 — the lowest of its two), list identical to `01` |

The one modal's wording, read off the pixels because `WM_GETTEXT` returns **nothing** for its children
(`words: []`, `panel_text: ""` — the warning is caption-less the way the whole application is), is exactly:

> **Warning**
> The burst length should be reduced
> `[Continue]`

and the band holds **one** button, so `--answer safe` (leftmost) and `--answer continue` (rightmost) pressed
the same handle and both dismissed it — the two captures are byte-identical (`sha256 0ffbe5f8…`), which is
what makes "which button is `Continue`" a measurement rather than a reading. The warning's subtree holds two
`TSp_Button` widgets, and the band's one is the painted `Continue`: `_bottom_row`'s rule (the last 70 px of
the panel) is what picked it.

**`max(remembered, floor)` held at every step.** The requested value is the remembered one; the effective one
is the larger of it and the floor the burst implies.

| burst | volume in force | wrote | re-opened states | `max(remembered, floor)` | held? |
|---|---|---|---|---|---|
| `4` | `0.876` | volume `3.650` | `3.650` | `max(3.650, 0.730) = 3.650` | yes |
| `4` | `3.650` | volume `0.584` | `3.650` (after `Continue`) | the request is below `0.730` → **rejected** | yes |
| `8` | `3.650` | burst `8` | volume `3.650` | `max(3.650, 1.460) = 3.650` | yes |
| `4` | `3.650` | burst `4` | volume `3.650` | `max(3.650, 0.730) = 3.650` | yes |
| `4` | `3.650` | volume `1.168` | `1.168` | above the floor → accepted, and it is the new remembered value | yes |
| `4` | `1.168` | volume `0.876` | `0.876` | above the floor → accepted | yes |
| `4 → 8` | `0.876` | burst `8` | `1.460` **in the same dialog** | `max(0.876, 1.460) = 1.460` | yes |
| `8 → 4` | `1.460` | burst `4` | `0.876` **in the same dialog** | `max(0.876, 0.730) = 0.876` — the raise was not remembered | yes |

The floor itself was bracketed at burst `4` on a seventh run (`below-floor --volume 0.730`, `sv-15`): `0.730`
is **accepted** (no modal — the mode recorded *"the rejection did not reproduce"* and refused the point
anyway) where `0.584` is rejected, so `floor(4) ∈ (0.584, 0.730]`, the operator's `0.730` sitting on the
upper end. `floor(8) = 1.460` is measured outright below; the `6` floor (`1.095`) stays hand-measured.

**The couple, measured in the same dialog and in both directions.** §18.9 could not see the burst → volume
couple at `4 → 2`, because `0.876` was already at or above `floor(2) = 0.365`: there, `max(remembered, floor)`
and "no coupling at all" are the same reading. One burst write **to `8`** with `0.876` in force separates them,
and it was run twice:

| run | written | the field **inside the dialog, before `Accept`** | re-opened | what it settles |
|---|---|---|---|---|
| `21` | burst `4 → 8` | volume **`0.876 → 1.460`** | burst `8`, volume `1.460`, slot 0 `1.460` | the upward couple is real: `max(0.876, 1.460) = 1.460`, so `floor(8) = 1.460` is **measured**, not hand-measured |
| `22` | burst `8 → 4` | volume **`1.460 → 0.876`** | burst `4`, volume `0.876`, list identical to the baseline | a floor-raise is **not** a remembered write: the remembered `0.876` is what comes back, so `max(remembered, floor)` is the whole rule in both directions |
| `19` | burst `4 → 8`, then volume `0.876` | burst `8` (uncommitted), volume `1.460` | nothing committed | `0.876` **is** below `floor(8)`: asking for it explicitly raises the same warning — and the `write` mode, whose rule is that a single-button warning's `Continue` is not pressed, **refused** the run instead of answering it. That report says `dialog_closed: false`: the warning was left standing and the dialog's own `Cancel` takes a moment to clear both. The next run found no modal, the dialog openable, and the burst/volume unchanged — nothing was left committed. |

The raise in `21` is the third way slot 0 is filled: the list was
`[1.460, 3.650, 1.752, 1.168, 0.876, 0.730, 0.584]` — **`1.460` is not in the tail**, so slot 0 states a
volume the combo does not offer. That is the writer's problem in one row, and the reason the rule below asks
for the effective value rather than the requested one.

**The option lists, as read.** The measured shape is `[the value in force] + a fixed six-entry tail`, and the
tail did **not** move from burst `4` to burst `8` — the *list* is not burst-derived on this machine, contrary
to the archive-derived note in §18.7 that it is (the tail is c/f_e-dependent, and slot 0 is state):

| where | items, in the order the control holds them | selected |
|---|---|---|
| burst `4`, volume `0.876` (baseline) | `0.876, 3.650, 1.752, 1.168, 0.876, 0.730, 0.584` | index 0 |
| burst `4`, volume `3.650` | `3.650, 3.650, 1.752, 1.168, 0.876, 0.730, 0.584` | index 0 |
| **burst `8`**, volume `3.650` | `3.650, 3.650, 1.752, 1.168, 0.876, 0.730, 0.584` | index 0 |
| burst `4`, volume `1.168` | `1.168, 3.650, 1.752, 1.168, 0.876, 0.730, 0.584` | index 0 |
| burst `4`, volume `0.876` (restored) | `0.876, 3.650, 1.752, 1.168, 0.876, 0.730, 0.584` | index 0 |

So the held value appears **twice** (slot 0 and its own place in the tail), which is why "select by value"
must take the **lowest** matching index (§18.9's rule, confirmed three times: `0.876` → index 0 when in
force, index 4 when not); the burst list is unchanged (`2 … 20, 24, 28, 32`); and the floor value `1.460` is
**not offered** — the application can state a sampling volume its own combo does not list.

**The coupling nobody asked for: a volume write re-derives the first gate.** Every sampling-volume write in
this round trip moved the dialog's `First gate depth [mm]` cell `(1, 1)` and the `Depth` the dialog derives
from it, and **no burst write did**:

| run | volume written | `(1, 1)` first gate | `Depth` |
|---|---|---|---|
| `01`/`01b` baseline | — | `2` | `99 mm` |
| `02` post | `3.650` | **`1`** | `98 mm` |
| `05`, `06` (burst writes only) | `3.650` | `1` (unmoved) | — |
| `07` post | `1.168` | **`7`** | `103 mm` |
| `08` post / `09` | `0.876` | `7` (unmoved) | — |
| `11` post | `1.752` | **`5`** | — |
| `12` (30 s later, **nothing dispatched**) | — | `5` (unmoved) | — |
| `13` post | `0.876` | **`7`** | — |
| `15` post | `0.730` | **`8`** | — |
| `16` post | `0.876` | `7` | `104 mm` |

It is the application, it is a function of the volume written (`0.730 → 8`, `0.876 → 7`, `1.168 → 7`,
`1.752 → 5`, `3.650 → 1` at `c = 1460`, `f_e = 4000`, `797` gates, resolution `0.122`), and it is
reproducible: `0.876` gave `7` from two different starting first-gate values, `1.752` gave `5`, and an idle
window with nothing dispatched changed nothing. The law behind those five pairs is **not** derived here. The
committed `compare` shows the whole cost of it: `sv-01-baseline.json` against `sv-09-final.json` is identical
**control for control except one** — 42 controls, 15 cells, the same rect, the same burst/volume pair, and
one row differing:

```json
"controls_only_in_baseline": [[1, "TSp_Edit", [987, 491, 1057, 507], "2", true]],
"controls_only_in_after":    [[1, "TSp_Edit", [987, 491, 1057, 507], "7", true]],
"table_changed": [{"cell": [1, 1], "cls": "TSp_Edit", "baseline": "2", "after": "7"}]
```

Two consequences, and the second is the reason the writer rule below is worded the way it is:

- **`Cancel` never repair this** — the value is committed by `Accept`, and since it is a function of the
  volume written, writing the volume back to `0.876` re-derives `7` rather than restoring `2`. The baseline
  pair `(0.876, 2)` is not reachable with this experiment's vocabulary: the round trip's **own** writes end
  exactly where they started (`4`/`0.876`, list identical, the restored and final dialog PNGs byte-identical,
  `sha256 79c5091f…`) while the *configuration* does not, because one cell outside those two knobs was
  re-derived by the application and putting it back needs a first-gate write, which is not one of the two
  knobs this probe writes. **The closing state, stated rather than implied:** burst `4`, volume `0.876`, all
  42 controls and 15 cells at their baseline values and the option list identical — except `First gate depth
  [mm] = 7` and the `Depth = 104 mm` the dialog derives from it, where the baseline read `2` and `99 mm`.
  Restoring that one field is an operator's edit in the dialog (or a writer for `DialogField.FIRST_GATE_MM`,
  which does not exist yet); the campaign path will not fix it silently, it will *refuse*: `first_gate_mm` is
  a `FIXED_FACT_FIELDS` entry that `plan_campaign`'s check compares against this very cell, so a campaign
  declaring `2.0` stops at the compile until the cell states it.
- **`(1, 1)` is not a stray cell: it is a declared fixed fact.** `DialogField.FIRST_GATE_MM` is bound there,
  `first_gate_mm` is in `FIXED_FACT_FIELDS`/`SUPPORTED_READ_FACTS`, and `plan_campaign` refuses a campaign
  whose points disagree about it — so a point recorded after a volume write carries the instrument's derived
  first gate, and what refuses it is the compile's fact check, not the write's own read-back. A *silent*
  difference in a replaced knob is exactly the failure rung 2 exists for, and the two written cells' read-back
  said `matches: true` throughout.

**The writer rule, measured.** A dialog write is an `Accept`-committed transaction whose read-back must not be
limited to the fields it asked for:

1. **No write is believed.** Every dialog write is followed by a read-back of the *effective* value, and any
   point whose read-back differs from what was requested — or where a modal appeared anywhere on the path —
   is **refused** rather than recorded. `write` now returns `read_back: {asked, effective, matches, mismatch}`
   and non-zero on a mismatch; `below-floor` exists to demonstrate that path.
2. **The read-back is the re-opened dialog and the cell's own text.** `CB_GETCURSEL` is the control's belief
   and can disagree with the cell: at the start of this run the burst cell stated `4` while its cursel was
   `3` (whose item is `8`) — with the same handle and byte-identical pixels as the committed baseline, where
   the same cell read cursel `1` — and after the first write the two agreed again. A reader that believed the
   index would have recorded burst `8` for a dialog that stated `4`.
3. **The read-back covers the whole value table, not just the written cells.** `Accept` commits a coupled
   transaction: §19.2's burst → volume couple is one, and the sampling volume → `First gate depth` couple
   measured here is another, invisible to any read-back that only asks whether the two requested cells took.
   The writer compares the full table (and the control walk) before and after, and refuses the point when a
   cell it did not ask for moved — `compare`'s diff of two dumps is the instrument.
4. **A modal is a refusal, and it arrives before the commit.** The floor rejection is raised on the select's
   notification, so a batch can refuse without spending the `Accept`; `Continue` is not a repair (it puts the
   field back to the previous value and drops the request), and the value the instrument actually holds is
   then the *remembered* one, which no amount of pressing `Continue` changes.

**Artifacts**, all under the gitignored `outputs/live/`: the per-step dumps and captures
`sv-01-baseline.*`, `sv-02-volume-3650.*`, `sv-03-belowfloor-safe.*`, `sv-04-belowfloor-continue.*`,
`sv-05-burst8.*`, `sv-06-burst4.*`, `sv-07-volume-1168.*`, `sv-08-restored.*`, `sv-09-final.*`,
`sv-10a-state.*`, `sv-11-volume-1752.*`, `sv-12-idle-dump.*`, `sv-13-volume-back.*`, `sv-14-final-dump.*`,
`sv-15-belowfloor-0730.*`, `sv-16-restore-volume.*`, `sv-17-final.*`, `sv-18-closing.*` (identical to
`sv-17`, the tree stable while this was written up), `sv-19-burst8-volume.*`, `sv-20-burst4-back.*`,
`sv-21-burst8-raises.*`, `sv-22-burst4-returns.*`; the warning's own pixels as
`sv-03-belowfloor-safe-modal.png` and `sv-04-belowfloor-continue-modal.png` (byte-identical); the diffs
`sv-compare-baseline-restored.json`, `sv-compare-baseline-final.json`, `sv-compare-baseline-17final.json`,
`sv-compare-baseline-closing.json` (the baseline against the closing state — the one difference below),
`sv-compare-18-closing-vs-22.json` (identical: the extra runs `19`–`22` left the tree where run `18` found
it);
and each run's dispatcher log as `sv-run-*.log` with the probe's own log beside it as `sv-task-*.log`. Each
step costs 3.6 s (`dump`, `compare`) to 12 s (`write`, `below-floor`, whose modal capture and second read are
the difference).

## 19. A dialog write is an `Accept`-committed, coupled transaction — four decisions for the writer

The archive establishes four things about writing that §18.1–§18.8 do not state, and each changes the shape of
the writer rather than merely adding a field. They are decided here so the slice is built against them; the
citations are §18.7. Nothing above is rewritten by this section.

**19.1 The commit gesture for a dialog knob is `Accept`, and a write is a transaction — not a field poke.**
Write the field with its own recipe (edit: `WM_SETTEXT` + `WM_COMMAND(EN_CHANGE)` + `WM_KEYDOWN`/`WM_KEYUP
VK_RETURN`; combo: `CB_SETCURSEL` + `CBN_SELCHANGE`, no Enter), then press the bottom band's **rightmost** button
(`Accept` = `row[-1]`; `Cancel` = `row[-2]` — the band has four buttons and the leftmost pair are indicators).
`Cancel` discards, which is the archive's own read-only gesture and this repo's W1 read path: **a write must
never be verified with a `Cancel`.** So the verify step has three rungs, in this order — (1) the field states
what was written, read from the application's own model, not the control (§18.5); (2) *after* `Accept`, the
dialog's derived readouts (`Depth`, `Velocity scale`) and a re-opened dialog agree; (3) the stored `.BDD`'s word
states it for the channel that measured (§16.1). Rung 3 is the one that counts, and a point that fails any rung
is refused rather than recorded.

**19.2 Burst is a coupled write and its companion is derived, so the four combos are not one writer.**
Writing `Burst length` re-selects the `Sampling volume`; the volume's list is physics-driven (`c`, `f_e`, burst)
and a request below the burst's floor is **rejected** with a modal warning. Therefore: burst is a *source* knob,
sampling volume a *derived* one, and the point's declaration must carry the pair actually accepted (read back
from the combo — oracles: words `8` and `27`). A rejection is an outcome to record, not a retry: if the warning
appears, the requested volume was not applied, so read the volume back and record what the instrument chose — or
refuse the point when the volume was itself the swept value and must be exact. Order follows the existing
structure rule: write the determining knob first (burst, before the volume is read; resolution and first gate,
before the gate count).

**19.3 A knob can be two controls, and the enable is part of the knob.**
`Number of skipped profiles` + `Apply skip profile` is the first instance (§18.3): with the flag unticked the
value is inert, so the point's declaration for that knob is the pair, the reader carries both, and the writer
sets both. The order (count, then enable) is **unmeasured** — the archive's capture shows the enable greyed at
count `0`, which would make that order mandatory rather than merely sensible — so the probe in §18.7's list
settles it before the writer hard-codes a sequence. Until then the writer sets the count, attempts the enable,
and reads both back.

**19.4 The channel combo is read, never written in place.**
Writing the dialog's channel combo makes the application **replace the dialog** (measured `(655, 364) → (713,
364)`, every prior handle dead), so a channel change is a re-open, not a same-dialog write: read the combo for
§16.1's attribution, and never press `Accept` on a handle taken before a rebuild.

**Not decided here, deliberately.** Which surface is authoritative for the two knobs that exist twice
(`Emitting power`, `Sensitivity` — column combo and dialog cell): §18.7's open item 6. Until it is measured, the
writer writes the dialog cell and reads the column back as a cross-check, and the disagreement is recorded on
the point rather than averaged away.
