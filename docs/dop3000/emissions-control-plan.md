# Emissions/profile as the next automated control — design review

> **Status: proposal only. Nothing here is implemented, and no instrument has been touched.** This is the
> pre-implementation review requested before any code: the exact current path, the proposed transaction and its
> ordering, the stored-artifact oracle, the resume/provenance model, the answer to the provenance question
> (§5), the minimum offline tests and live commissioning, and the documents that will need amending.
> Written against `master` `14bcc1b`.

## 0. Why this knob, and the governance test it has to pass

`acquisition-closeout-plan.md:513–515` binds: **"No writers before the matrix names the axes. The five unturned
knobs stay candidates, not a work list."** §11.1 item 5 states the rule for funding one — *only the writers the
matrix requires*.

The emissions-per-profile axis is already named, and already executed:

- the portable nine-job plan sweeps it — `burst-4 → CR1 → burst-18 → CR2 → emissions-8 → CR3 → emissions-64 →
  CR4 → emissions-128` (`acquire/run_plan.py:7–11`), with `RUN_LEVEL` jobs defined as "one run-level observation
  of the pass's reference window **at its own emissions level**" (`run_plan.py:196–201`);
- a full nine-job pass has already run on the instrument (`docs/agenda-history.md:34`: 26 points, emissions
  `8/20/64/128`);
- the 2026-09-25 job-boundary pass **stopped after job 4 precisely because of this boundary** — the remaining
  jobs "request a *manual* emissions change" (`docs/dop3000/handoff-dop3010-acquisition.md:71`, `docs/agenda.md:269`,
  `:311`).

So the writer is funded by an axis the experiment already sweeps, and not by a knob's existence — which is what
the closeout rule demands. Emitting power, TGC, sensitivity and the skip-profile control fail the same test today
(§8), which is why they stay out even though power is the more obvious knob.

**What this slice buys:** the manual boundary that ended the nine-job run after job 4 disappears, exercised
through write infrastructure this repository has already measured (the parameter column), not through a new
dialog surface.

## 1. The current read / write / store path for emissions/profile

| stage | what happens today | anchor |
|---|---|---|
| vocabulary | `ParamRole.EMISSIONS_PER_PROFILE = "emissions_per_profile"`; its position in the column's fixed top-to-bottom order **is** its identity | `actuator.py:128`, `PARAM_COLUMN_ORDER` `:134–142` |
| read | the measurement screen's parameter column: `read_parameter(role)` → the row edit's own text | protocol `actuator.py:861`; impl `driver.py:1713–1732` (`_get_text(row["edit"]["hwnd"])`) |
| read (as a fact of the reading) | the instrument snapshot already carries it — it is a first-class fact, sourced from the column, not a dialog field | `driver.py:1442` (`_column_fact(roles, ParamRole.EMISSIONS_PER_PROFILE)`) |
| read (cross-surface agreement) | the `Operating parameters` dialog states its own copy at column 2, row 0, and every dialog-only fact is believed **only after all seven anchors agree with the column** | `DIALOG_ANCHORS` `actuator.py:201–209`, rule at `:193–200` |
| write (exists, unused for this role) | the column's edit is written and committed, and the app's read-back is returned: `_set_text_commit(edit_hwnd, value, parent)` then `_get_text(edit_hwnd)` | protocol `actuator.py:870`; impl `driver.py:1754–1771`; gesture vocabulary `actuator.py:100–104` (`WM_SETTEXT`, `EN_CHANGE`, `VK_RETURN`) |
| write (who may call it) | the ordering is data: `PARAMETER_WRITE_ORDER = (RESOLUTION, GATES)`, expanded by `ordered_writes()`. Emissions is **absent on purpose** — "`PARAM_COLUMN_ORDER`'s other fields are covariates read once per sweep" | `actuator.py:144–149`, `:509–524`; caller `driver.apply_point` `:1773–1784` |
| campaign declaration | required field, read once for the channel, forced onto every point; a point naming a different value is refused | `campaign.py:275`, docstring `:248–251`, `_effective_parameters` `:2031–2064` |
| campaign physics | the profile period law and the stored-size guard both need it | `plan.py:237–258`, `campaign.py:253–258` |
| stored artifact | **word 14**, `WordFacts.emissions_per_profile`, decoded into `ChannelConfig.emissions_per_profile` | `verify.py:120`, `:141`, `:205`, `:306`/`:325`; `io/dop/bdd.py:171`, `:341` |
| enforcement today | read, reported, returned — **advisory**: not compared into `ok` | `ADVISORY_COVARIATES` `verify.py:179`; contrast `ENFORCED_COVARIATES` `:149–153`, `ALWAYS_ENFORCED_COVARIATES` `:163`, `STRICTABLE_COVARIATES` `:189` |
| compile-side acceptance | a definition/instrument disagreement on this fact **warns** and proceeds — exactly one fact has that outcome | `Acceptance.WARN` `campaign.py:764–769`; the table is derived from the verifier's own tables `:781–783` |

**The hinge, stated plainly.** Word 14 is advisory *because a definition's value need not be a request*: it may
be a derivation that reproduces a stored profile count (`verify.py:165–173` — the committed point stores `150`
while the declaration said `52`). Automating the write is what turns that value into a request, and the verifier's
own docstring already names the condition under which it becomes enforceable (`verify.py:175–178`: a run whose
*axis* is this value raises it). **No new word, no new decoder and no new enforcement mechanism is needed** — the
strict path exists; what does not exist is a job that legitimately requests the value.

## 2. The proposed transition, and where it sits relative to burst

Same philosophy as burst (`_transit_burst_length`, `campaign.py:1300–1426`), on the column mechanism:

1. **read** the current value (`read_parameter(EMISSIONS_PER_PROFILE)`, or the fact from the reading already
   taken in the same pass);
2. **already equal → spend no write**, return no mutation (burst's third answer, `campaign.py:1365–1366`;
   a re-selection is not a no-op and an equal value is not a transition);
3. otherwise **write** through `write_parameter(EMISSIONS_PER_PROFILE, str(requested))` — the measured column
   path (`driver.py:1754`), never the dialog;
4. **read back independently**: a second `read_parameter` call, taken by the calling layer, not the write's own
   return value. The driver returns a read-back, and that return is *evidence the write layer produced*; the
   transaction's evidence must be a read the boundary performed, exactly as the burst transaction reopens the
   dialog rather than trusting its own Accept;
5. **compile/reconcile against the new state**: the caller re-takes the reading (dialog + snapshot) after the
   write and hands the compile the post-write state — the existing burst sequence at `campaign.py:1782–1790`;
6. **record**: append the mutation event after the write verifies and **before** anything that can refuse
   (the compile and the resume-identity comparison), fail-closed — the mechanism PR #44 implements;
7. **verify stored word 14 against the request for every stored point** (§3).

**Refusal rules** mirror burst's five demands, translated to a column write: the read-back must state the
requested value (an app that trims or renumbers is a refusal, naming both sides); a blank/unreadable row is a
refusal; a write raising `AcquisitionError` propagates untouched; nothing is compiled and no point is recorded
after any of them.

### Ordering relative to burst — explicit data, not code order

```python
BOUNDARY_WRITE_ORDER: tuple[ParamRole, ...] = (
    ParamRole.EMISSIONS_PER_PROFILE,   # column, no dependent row
    ParamRole.BURST_LENGTH,            # dialog, re-selects the dependent sampling volume
)
```

Four reasons, in order of weight:

- **the dialog transaction is the one that re-verifies cross-surface agreement.** `DIALOG_ANCHORS` requires the
  dialog's emissions copy (col 2, row 0) to read the same text as the column *before any dialog-only fact is
  believed* (`actuator.py:193–209`). Writing the column **first** means the next dialog-based transaction
  re-checks that agreement as part of its own work; writing it **last** leaves the final write on a surface
  nothing but its own read-back has looked at.
- **the boundary's last write should carry the strongest verification.** The burst transaction ends with a
  re-opened dialog and a named dependent read-back; the compile must reconcile against a reading taken after the
  *last* write, and that reading is cheapest and most informative when the last write is the dialog one.
- **one new axis per failure.** Emissions has no dependent row and no dialog; putting it first keeps a failure
  attributable to the new mechanism alone, which is what the assignment asks for.
- **no dependence either way**: neither write's outcome depends on the other's, so the order is a policy the
  repository can state and test, not a discovered constraint.

The order must be **tested as a sequence** (a job that changes both emits exactly `[emissions, burst]`), never
inherited from dict/field order. **Residual risk, for the live sitting:** if the burst Accept silently rewrote
the column's emissions value, the post-burst re-read would see a disagreeing fact and (for a writing job) refuse
(§3) — the design catches it by construction, but the *observation* belongs to the A→B→A sitting (§6).

## 3. The stored-artifact oracle and the refusal rule

**Oracle: `stored word 14 == requested emissions_per_profile`, for every stored point of a job that writes it.**

- **Stored side** — the run is verified with `strict_covariates=("emissions_per_profile",)`; the plumbing already
  exists (`SweepRunner(strict_covariates=...)`, `campaign.py:1552`; the compile passes it at `:1709`). A file
  whose word 14 disagrees is then not that run's point, exactly as word 8 is for burst
  (`ALWAYS_ENFORCED_COVARIATES`, `verify.py:163`).
- **Compile side** — a definition/instrument disagreement on emissions must **REFUSE** for a job that *writes*
  it, not warn. That is a change to the acceptance table (`campaign.py:764–769`, derived at `:781–783`) and it is
  the honest consequence of the value becoming a request.
- **The distinction that must survive** (the same one the word-8 review settled): jobs that only *inherit* the
  channel's value keep today's advisory behaviour — `WARN` at compile, no strict covariate in the verifier — so a
  low-level caller can still verify window geometry against a file without asserting an emissions request.
- **Interaction with W6.** `acquisition-campaign-compilation-plan.md:431` (W6) exists to feed the period law the
  instrument's own emissions *without erasing the declaration*, because today declared (52) and observed (150)
  differ. For a job that **writes** emissions, declared == observed == effective == confirmed by construction, so
  the WARN rationale ("the declaration is as likely to be at fault as the instrument's", `campaign.py:766–768`)
  is void *for that job* and W6 remains for the read-only path. The design must say which of the two a job is,
  and it must be a property of the job, not of a caller's flag. **A job that writes emissions may not declare a
  derived value** — the declaration is the request.

## 4. Resume and failed-invocation provenance with two mutable parameters

- **One ordered history per job**, each entry role-tagged: `(role, before, verified_after, occurrence id,
  moment, routed channel, definition fingerprint)`. Not `emissions_transitions` beside `burst_transitions`.
- The boundary's transition function returns a **tuple** of mutations (possibly empty), in
  `BOUNDARY_WRITE_ORDER`. It is called once per invocation, after the pure refusals and before the compile.
- **Resume identity extends to every role the job writes**: a plan that changes either value for a job whose
  manifest already carries a different one fails the resume-identity comparison (as a burst change does today),
  rather than silently re-running.
- **Reconstruction from three sources**, unchanged in shape from #44: the previous manifest's history, the job's
  own log's mutation events, and this invocation's own mutations — folded in sequence, one occurrence consumed
  per entry, never by a content key (two identical `20 → 64` transitions in one job's life stay two events).
- **Partial-failure shapes that must be reasoned about, not discovered**:
  - emissions verifies, burst then refuses → the emissions event is already durable (it was appended before the
    compile), and it must be, because the instrument really moved;
  - emissions refuses (unreadable/disagreeing read-back) → burst is never attempted, nothing is appended, no
    point recorded;
  - either write verifies and a *later* refusal (compile or resume identity) fires → the log carries the event
    and the manifest does not; the next invocation recovers it.
- **Fail-closed** stays as #44 has it: an event that cannot be appended aborts the invocation before the compile
  and before any recording.

## 5. The provenance question: what to do with PR #44

**Recommendation: generalize PR #44's durable event to a parameter-agnostic parameter-mutation record *before*
#44 merges, and have this slice use it unchanged in mechanism.**

The trigger the design document wrote has fired: automating emissions is a **second independently owned
instrument mutation** entering the automated path (`docs/dop3000/failed-invocation-provenance.md`, and the
trigger re-stated in `docs/agenda.md`).

Why before merge rather than after:

- **the mechanism is already parameter-agnostic in shape** — boundary append, fail-closed, explicit occurrence
  identity, occurrence-safe in-sequence folding, unknown-entry-type refusal. Only the payload generalizes:
  `transition: BurstWriteResult` becomes a role-tagged payload (`role`, `before`, `requested`, `verified`,
  plus the dependent covariate it moved when there is one, e.g. burst → sampling volume). That is a bounded edit
  to the record, the reconciler and the manifest accessor;
- **the migration is at its cheapest and strictly increasing**: #44 is unmerged, days old, and has no consumer
  beyond the manifest field and the pass-row note. After merge, the same change costs a second review *plus*
  either a bespoke parallel field (the architecture to avoid) or a migration of whatever landed meanwhile;
- **one review instead of two**: the reviewer reads one event model, and the same PR that introduces the second
  mutation is the one that proves the model carries two.

**Honest counter-argument, and the fallback.** Amending a branch under review invalidates the review of that
branch, and #44's shape was reviewed against a document that specifies the burst-shaped record. If the reviewer
prefers a stable reviewed artifact, then: **merge #44 as it stands, and land the generalization as the *first*
commit of the emissions slice** — before any campaign integration — so no `emissions_transitions` field ever
exists in a released state. What is *not* acceptable is merging #44 and then adding a parallel per-parameter
history, which is the outcome the assignment rules out.

Concrete generalization, for a reviewer to judge:

```
record:    SweepParameterMutation(record_type="parameter_mutation", mutation_id, occurred_at, job,
                                  fingerprint, routed_channel, role, before, requested, verified,
                                  dependent=None | {name, before, after})
manifest:  parameter_mutations: tuple[ParameterMutation, ...]   # ordered; legacy burst_transitions
                                                                # reads as burst-length entries through
                                                                # one accessor, so the three readers
                                                                # (accumulation, transition text, pass
                                                                # note) move once, not three times
```

## 6. Minimum offline tests, and the minimum live commissioning

**Offline (all through the existing fakes; the acquisition suite already counts writes and compiles):**

1. equal value → **zero** writes spent, no event appended;
2. write → the *independent* read-back is what the record carries (a fake whose second read disagrees with the
   value its write accepted ⇒ refusal, nothing compiled, no point recorded);
3. read-back blank/unreadable ⇒ refusal naming the row and the request;
4. `write_parameter` raising ⇒ propagates untouched, nothing recorded;
5. **ordering**: a job that changes both emits exactly `[emissions, burst]`, asserted as a sequence;
6. **partial shapes**: emissions verified then burst refused ⇒ exactly one durable event, no manifest; emissions
   refused ⇒ burst never attempted and no event;
7. resume at an already-correct value ⇒ no write, history retained, **no duplicate** event;
8. recurrence safety: two identical `20 → 64` transitions remain two events;
9. the oracle: word 14 == requested ⇒ `ok`; a swapped-emissions file ⇒ `INVALID` under the run's strict
   covariates; the advisory behaviour preserved for a job that does not write emissions;
10. the acceptance table: a writing job **refuses** a definition/instrument disagreement; the read-only path
    still warns (pins the W6 boundary);
11. a plan whose emissions changed for a job that already ran fails the **resume-identity** comparison;
12. **mutation-proof**: deliberately break the order (and separately the no-write rule and the append) and show
    exactly the new tests fail — the same evidence shape B5 and B6 carry.

**Live commissioning — deliberately one small sitting, not a science campaign.** A purpose-built four-job
run-plan at otherwise fixed settings (the pass's own frame: 4 MHz, Doppler angle `0`, velocity scale `1`, TGC
uniform ≈20 dB, emitting power medium, sensitivity medium, skipped profiles `0`, sound speed and first gate held):

| job | transition expected | what it proves |
|---|---|---|
| `emissions-20` | instrument's own value → `20`, one verified event | the write, the read-back, the record |
| `emissions-64` | `20 → 64` | a second transition of the same role, distinct occurrence |
| `emissions-return` | `64 → 20` | the A→B→A shape, and that a return is a new event, not a dedupe |
| `emissions-equal` | already `20` → **no write, no event**, history retained | the no-write boundary |

Every stored point verified with emissions strict; the evidence committed as a package in the shape of
`data/burst-commissioning-b5/` (portable plan copy without machine paths, path-sanitized derived summary with
per-file SHA-256 and word 14, and an instrument-free verifier that re-derives the plan's fingerprint, each
job's definition fingerprint and point list, the emitted event order, and each file's word 14). Stop conditions,
as for B5: an unverified read-back, an unexpected dialog/modal, or a screen that is not the expected one ⇒ abort,
leave the application as found, report. Nothing about scientific quality is claimed by this sitting, and the
emissions *effect* on the signal is not measured here — that is the sparse plan's job.

**Do not touch the instrument until items 1–12 and the evidence package exist offline and the requested value,
read-back, provenance and stored-word oracle are unambiguous.**

## 7. Documents and code comments that will need amending

| where | what it says today | why it changes |
|---|---|---|
| `docs/dop3000/handoff-dop3010-acquisition.md:71` | the remaining jobs "request a *manual* emissions change" | the boundary this slice removes |
| `docs/agenda.md:269`, `:311` | same wording, in the acquisition entries | same |
| `src/udv_echo_process/acquire/campaign.py:248–251` | "the emissions per profile and the burst length are read once from the application for the channel" | true only for a job that does not write it |
| `campaign.py:253–258`, `:2036–2040`, `:2052` | dialog-only framing for emissions | the column write path exists and is measured |
| `campaign.py:764–769` + `:781–783` | `WARN` for emissions, table derived from the verifier | becomes `REFUSE` for a writing job |
| `verify.py:165–179` | emissions advisory, "becomes enforceable when compiled against a live snapshot" | that condition is met by a writing job; the strict path is used, not changed |
| `actuator.py:516–518` | "covariates read once per sweep" | still true per *point*; a job boundary may now transition one |
| `actuator.py:106–117` | `DIALOG_ONLY_PARAMETERS` — emissions is **not** in it (correct already) | worth an explicit note that it is a *column* role, unlike burst |
| `docs/dop3000/acquisition-campaign-compilation-plan.md:476` (D4) | "record-and-continue only for word 14, whose declaration is known wrong until W6" | false for a writing job |
| same, `:431` (W6) | feed the period law the instrument's own emissions without erasing the declaration | stays for the read-only path; the writing path needs it to stay distinguishable |
| `docs/dop3000/acquisition-closeout-plan.md:513–515` | "no writers before the matrix names the axes" | amend with the dated finding that the emissions axis **is** named and already swept |
| `docs/dop3000/burst-length-control-plan.md:301` | the portable plan's remaining jobs vary emissions/profile | they stop being manual |

## 8. Explicitly out of scope for this slice (with the reason each is out)

- **Emitting power** — scientifically useful, but not low-risk: the existing evidence records that changing it can
  raise a TGC-mode modal. It needs its own commissioning/measurement slice first.
- **TGC** — dialog-only and depth-shaped, its stored representation is not settled, and its modes matter.
- **Sensitivity** — word 18 is ambiguous because it moved together with TGC in the available fixture diff; a
  recording where sensitivity alone changes must exist first.
- **Skipped profiles** — word 84's field identity exists but its semantics are unconfirmed; a dedicated live
  semantics check comes first.
- **First gate / sound speed** — they define and scale the physical measurement frame rather than solving the
  manual-job problem; they stay fixed for this campaign.
- **Sampling volume** — observed as dependent state, **never** written here. Word 27 stays provenance-only and is
  never converted to millimetres.
- **Per-point emissions** — the transition is a *job boundary* property (the plan's emissions jobs are run-level);
  varying it per point is a different mechanism with different provenance questions.
- **A generic editor for the dialog's fields** — the target is one verified sidebar parameter transaction, first
  applied to emissions/profile, later reusable for PRF. Not "write every visible field".

## 9. PRF — the named next sibling, and what is reusable

PRF is structurally identified (`ParamRole.PRF`, `actuator.py:124`; `DIALOG_ANCHORS` at `(1, 0)` `:203`), its
stored oracle is **word 5** (`verify.py`'s `_WORD_OF`, and `ENFORCED_COVARIATES` already contains `prf_us`), and it
is a campaign-declared value read from the column like emissions (`driver.py:1441`, `run_plan.py:168`). It affects
depth feasibility, the velocity range and profile timing, so it is a *heavier* axis than emissions.

Reusable from this slice, unchanged: the transition sequence, the ordering table (PRF would extend it), the
occurrence-tagged parameter mutation record, the fail-closed append, the strict-covariate oracle pattern, and the
four-job commissioning shape. What PRF adds and emissions does not: a **depth-feasibility consequence** — the
maximum depth law `P_max = c·T_prf/2` means a PRF change can invalidate a planned window, so it needs a
plan-level refusal this slice does not. That is exactly why it is a *second* slice: a failure there must be
attributable to that one new axis.

## 10. What I want adjudicated before implementing

1. **The #44 question (§5)** — generalize the event before merging #44 (my recommendation), or merge and
   generalize as the first commit of this slice. Either way: no parallel per-parameter history.
2. **The manifest shape** — one `parameter_mutations` history with role-tagged entries and a legacy read of
   `burst_transitions` (my recommendation), or keep `burst_transitions` and add a second field (rejected here).
3. **The acceptance change** — `WARN → REFUSE` for a writing job: same slice, or its own commit so the verifier
   and the compile-side tables can be reviewed against each other.
4. **The write's evidence** — a second, independent column read (my recommendation) rather than trusting the
   `write_parameter` return, at the cost of one more read per transition.
