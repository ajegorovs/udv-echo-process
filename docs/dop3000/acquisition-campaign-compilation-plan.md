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
reading carries that field and something refuses on it.
