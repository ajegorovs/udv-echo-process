# Reporting consolidation — one home per fact

**Task plan.** Written 2026-10-16. **State:** blocked. Register: [agenda](../agenda.md#selected-work). This is the work a fresh session performs.

## Destination

**Purpose.** Remove the duplicated reporting and hand-off surfaces this repository has accumulated, so that every fact
has one home and a restarted session can find the selected work, the current state and the unresolved findings without
conversation history. The redundancy is measured, not assumed: `docs/` is 22,810 lines, of which `docs/dop3000/` is
21,070; three tracked documents carry "resume here" state blocks for workstreams the record now rows out; the
repository has three homes for one system map, one of which still names types that were removed; and twelve
`docs/dop3000/*plan*.md` documents range in status from *implemented, reviewed and frozen* to *PLAN, not started* with
no single place a reader learns which.

**Observable outcome, and this is the acceptance criteria.** All of:

1. `docs/agenda.md` § Current progress is the only **forward view**. No section of the agenda restates a position that
   a row already carries, and `docs/hardening-plan.md` holds only items with no other home (or points at the row that
   owns the item).
2. **No tracked document carries a session-state block.** `docs/dop3000/handoff-dop3010-acquisition.md`,
   `docs/dop3000/acquisition-closeout-plan.md` and `docs/dop3000/acquisition-campaign-compilation-plan.md` each keep
   their durable content and their dated record; none owns live execution state, and each names, in one dated line,
   where its live state went.
3. **One current system map.** `docs/architecture.md` (plus `docs/pipeline-conventions.md` for the landed contract) is
   it; `docs/pipeline-architecture.md` and `docs/interpolation-design.md` are dated pointers to it, with any unique
   measurement preserved in an explicitly verified destination before replacement; current destinations are not yet sufficient.
4. **Every `docs/dop3000/*plan*.md` carries a status line**, and the closed ones say what they closed with a link to
   the report or record that holds the result. "PLAN, not started" remains a legitimate status — the failure is the
   absence of one.
5. **A result has exactly one home**: `reports/*` for computed results, `data/<experiment>/README.md` for what a
   sitting's files are, the plan for evidence links. Required generated notebook evidence remains at its verified path;
   a requirement and its execution evidence are not duplicate results.
6. **The machine-local kit carries no state.** `.hermes/scratch/marimo-live/HANDOFF.md` keeps its commands, paths and
   traps (this is what the convention wants local) and loses anything a tracked record should own.
7. The agenda is the single work-discovery entry point: **selected work** plus **unselected findings**.
   `PLANS.md` is only a compatibility pointer. A cold-start reader finds plan-owned next actions and permission
   boundaries without conversation history. A successful local read does not claim publication or cross-machine validation.

**Non-goals.** No estimator, model, transform or test changes. No deletion of evidence, reports, tests or measured
fixtures. No rewriting of historical entries to agree with today's summary — a correction is a new dated line naming
what it corrects. Shared method design lives in the guide, not in this plan; no skill installation or universal rollout.

**Authorization boundaries.** Owner-stated intent, 2026-10-16: use this plan in a fresh session to perform the
consolidation. That authorises edits to this repository's documentation. It does **not** authorise deleting a document
whose unique content has not been carried forward, committing to `master`, or touching anything outside this
repository. Owner extension, 2026-10-16: update the shared guide with proposals, implement P1's agenda/index
mapping here, and persist the other mentioned tasks as unselected proposals. Shared writes obey the KB's own rules;
this did not authorize commits, pushes, merges, notebook changes or implementing P2–P6.
Owner extension, 2026-10-16: publish the saved documentation changes and park unfinished cleanup;
four-sensor notebook work takes priority next. This authorizes scoped commits, push and updating draft PR #71,
not merging, deleting worktrees, changing the explorer WIP or executing the longer notebook plan in this cleanup pass.

**Baseline.** Original drafting revision `cfd80a2`; execution baseline reconciled on 2026-10-16:
branch `docs/intent-progress-pivot` at `a9d807d`, plus the documented uncommitted edits (draft PR
[#71](https://github.com/ajegorovs/udv-echo-process/pull/71)). The earlier draft's commit count is not a current baseline. Re-verify before starting: `git rev-parse --short HEAD`, `git status --short`
(a notebook change may be sitting uncommitted in the primary checkout — see *Context*), and the counts above re-derived
with `find docs -name '*.md' | xargs wc -l`.

## Patterns this work follows

The method authority is the estate knowledge base's `docs/knowledge-base/dev-and-deploy/WORK-ORGANIZATION.md`.
The owner designated it authoritative while evolving. Its **P1 — one work-discovery entry point** is selected for
trial here; P2–P6 remain proposals with their questions, solutions and validation conditions in that source.
Authority, implementation and validation are separate claims; existing safety and permission boundaries govern:

- **Goals first.** Purpose, observable outcome, non-goals and priorities, because owner intent is not recoverable from
  source code.
- **Effort record fields**: destination → current checkpoint → remaining work → decisions and evidence → next session,
  with the checkpoint maintained **in place** and history left to linked evidence and version control.
- **One authoritative home per fact**, and **no per-session diaries**: a temporary transfer note cannot own unresolved
  work — it links the maintained records and carries only transfer-specific context. This is the rule that supersedes
  the hand-off documents this plan deals with.
- **Separate implemented, verified, accepted and deployed** claims, and keep **unresolved findings discoverable** when
  no effort is selected: "no selected effort" is not "no unresolved work".
- **A checkpoint must be checkable** — established behaviour, its limits and a concrete continuation point, not "made
  progress".
- **Capture deferred work before the session ends** — normally as a GitHub issue, marked *proposed / not started*,
  never an empty branch or placeholder PR; capturing an idea is not approval.

**Local P1 mapping:** the existing agenda is the work index; tracked `docs/plans/` records own effort checkpoints;
`PLANS.md` is a compatibility pointer. Tracking plans supports remote review and is compatible with the guide,
not a divergence from an assumed ignored-plan requirement. No second plan ledger or trial report is introduced.

## Current checkpoint

**Publication baseline (2026-10-16).** `docs/intent-progress-pivot` at `a9d807d`, with the reviewed
13-file documentation diff. Owner authorized publication to draft PR #71. The primary checkout's
`.gitignore` and `notebooks/signal_explorer.py` edits remain outside scope. No merge or deployment selected.
Publication verification belongs to PR #71 and its exact head revision; a local commit alone is not publication.

**Established.** The repository rules no longer treat the KB research draft as overriding instructions by age.
Both task plans have explicit lifecycle states. The agenda now owns selected-plan discovery and the unique
findings formerly in `PLANS.md`; that file is a pointer. Entry instructions and the template follow the same path.
E1 partially implemented: the duplicated signal-model acceptance/contract prose is now a pointer to the rework
plan §15/§7.4; its stale “two blockers open” row is corrected. The four-sensor row now points to its authorized
notebook plan, without selecting alignment. E2's hardening document is explicitly historical with current-home
pointers. E6 repaired five missing/stale statuses; this is not a full freshness audit of every older header.
E7 retains the required generated evidence and links it from its plan; no generated artifact or generator changed.

**Review corrections.** The original `docs/` total of 22,810 was wrong: counting `git ls-tree` Markdown files
and `git show a9d807d:<path>` lines gives 27,434. The original E7 premise was false: a requirement and its generated
execution evidence are different artifacts. The original E2 premise was false: no open P0/P1 checkbox remains.

**Verification / limits.** `git diff --check` passed. Screening-term tests: 35 passed, 2 failed, both caused by
one unchanged line in `sa5-cross-sitting-agreement-prespec.md:31`; compared that source with HEAD to confirm it
was not changed here. Local Markdown file targets and cited heading anchors were checked, not external URLs. No notebook
or scientific computation was changed or re-executed; historical device claims were not re-tested live.

**Broader consolidation blockers (not a block on the selected P1 trial).** E1's explorer evidence is on another branch, not this checkout; sidebar
constraints also need a durable home. E3 must preserve cited §11.1 writer-funding rules, guardrails and anchors.
E5's originals contain unique fixture lag/jitter, aliasing and interpolation measurements, CLI policy and use-case
rationale: the proposed destinations do not already contain them. The plan's stop-before-loss condition applies.
No original evidence or design document was deleted. E4's machine-local kit has not been audited.

**P1 trial checkpoint.** Owner selected the agenda mapping and preservation of P2–P6 on 2026-10-16.
Implementation was checked locally before publication. A fresh read-only agent starting from `AGENTS.md` passed all five
local scenarios: discovery entry, selected states, next action/unselected residue, authority/permissions and
verification limits. It found stale baseline wording, a duplicated agenda bullet and two contradictory reference
statements; these were corrected without notebook changes. The shared guide owns method design and adoption;
this plan owns implementation evidence. Shared-source access was outside the clone-only test, not proven unavailable.
**Same-machine restart checked (2026-10-16).** The restarted session followed this worktree's `AGENTS.md`
→ agenda → selected plan, then read both selected plans and the full documentation diff. Actual branch and HEAD
match `docs/intent-progress-pivot` / `a9d807d`; `git status --short --untracked-files=all` reports the same
13 modified documentation files and no untracked files. Both plans are tracked, and their lifecycle headers agree
with the agenda. Selected next work, authorization limits, unselected findings and E1–E8 preservation constraints
were recoverable from those records. `PLANS.md` remains a pointer; `git diff --check` passed.
This is a restart with the owner's short transfer message, not a blinded onboarding experiment; no prior session
transcript was consulted. The earlier independent onboarding check and this restart establish the bounded local
P1 discovery/resumption behavior only. Shared-guide hash, remote PR state, published-revision access and
cross-machine continuation were not re-verified in this restart; no general adoption claim follows.

**Recovery / continuation.** Session-end checkpoint, 2026-10-16: resume in the existing
`.worktrees/intent-progress-pivot` worktree on `docs/intent-progress-pivot`, not the primary checkout.
The primary checkout does not contain these updated entry instructions. Start at that worktree's `AGENTS.md`,
then its agenda and this selected plan; do not use the outgoing conversation to fill gaps. Reconcile HEAD and the
documentation baseline before proceeding. Publication is authorized to PR #71; verify its remote head against
this cleanup's publication commit before claiming receipt. Preserve the primary checkout's unrelated changes and do not
reset, switch or remove either worktree. The shared guide and its P1–P6 proposal register were published with
exact byte readback in the prior session; that hash was not re-verified in this cleanup pass. No delegated check remains
pending from this session. Resolve broader content destinations before removal; do not treat the successful
first onboarding check as completing E1–E8.

## Remaining work

**P1 bounded local stopping condition reached (2026-10-16).** Independent onboarding and same-machine
restart checks passed within the limits recorded above. No further local restart is selected. Publication,
another-machine availability and general adoption remain unverified, not silently waived.
**Owner disposition (2026-10-16):** publish the saved documentation and park broader consolidation behind
the four-sensor notebook priority. Lifecycle state is blocked (owner-priority hold, not complete). P2–P6,
cross-machine testing and broader method adoption remain unselected. Resume consolidation only when the owner
reselects it; first resolve the named content destinations without deleting unique material.

The broader consolidation below is preserved but not selected for execution; no unique content may be lost.

- **E1 — the agenda's own narration.** `docs/agenda.md`'s *Active work — …* sections (SA5, the acquisition track, the
  explorer, the sidebar notebook, the marimo follow-ups) restate what § Current progress rows out. Fold each durable
  statement into the authority document the section already names, leave the row, and keep only what is genuinely
  unstated. *Check:* every row's "Evidence / limits" cell resolves to a document that carries the detail; the agenda
  loses narration and keeps decisions.
- **E2 — the hardening list.** All P0/P1 checkboxes are closed; the open residue is the P3 DOPpy
  experiment and the marimo harness limitation. Preserve the historical acceptance record, route the residue to
  its authority documents, and make current navigation point there.
  *Check:* current hardening actions have one authoritative home; historical gates remain identifiable.
- **E3 — the three resume blocks.** Remove the session-state blocks from `handoff-dop3010-acquisition.md` § *Current
  state and next actions*, `acquisition-closeout-plan.md` § *Resume here*, and
  `acquisition-campaign-compilation-plan.md` § *11.1 Current state — resume here*; each keeps its durable design,
  guardrails and dated record, and gains one dated line naming where its live state now lives. *Check:* none of these
    three records owns live execution state; preserve cited anchors and historical quotations.
- **E4 — the local kit's state half.** Strip state from `.hermes/scratch/marimo-live/HANDOFF.md`, leaving commands,
  paths and traps. *Check:* nothing in it needs updating when a task's position changes.
- **E5 — architecture and design homes.** Turn `docs/pipeline-architecture.md` and `docs/interpolation-design.md` into
  dated pointers, after confirming each unique measurement or rejected option they carry is already held elsewhere
  (`docs/agenda-history.md` § *Superseded concepts*, `docs/signal-model-rework-plan.md`,
  `docs/pipeline-conventions.md`). *Check:* a reader following either pointer reaches the current map or contract, and
  nothing unique is lost — verify by listing what each document contains that the target does not.
- **E6 — plan statuses.** Give every `docs/dop3000/*plan*.md` a status line and, where the workstream is closed, one
  dated sentence naming what closed it and where the result lives. *Check:* a reader can classify all twelve without
  opening their bodies.
- **E7 — retain required evidence, link it.** Correction 2026-10-16: the preview evidence document is
  generated by `tools/notebook_evidence/sa23_export_evidence.py` and checked for drift. The plan describes a requirement;
  the report satisfies it. Keep both, link the report explicitly from the plan, and do not alter generated values.
  *Check:* the evidence artifact and generator are unchanged; the plan resolves to that artifact.
- **E8 — the closeout.** Update the agenda selection (clear only when the whole effort closes), its area pointers,
  and local bindings as needed. Keep outcomes in this plan, not in the compatibility pointer. *Check:* the acceptance criteria in *Destination* are
  each marked met with its evidence, and any unmet one is stated as unmet with the reason.

**Unselected, deliberately, and not to be started inside this plan:** the four-sensor alignment decision, its notebook
review plan (a sibling plan in this directory), and anything that changes behaviour rather than documentation.

## Publication and parking slice — 2026-10-16

**Owner-selected scope.** (1) Reconcile and verify the saved documentation diff; (2) commit explicit documentation
paths, push the existing branch and update draft PR #71; (3) read back the remote head and PR text, leaving the
broader consolidation parked and the four-sensor notebook review as the next priority. No merge, worktree removal,
notebook implementation, explorer-WIP mutation or shared-method rollout is included.

**Checks.** Ruff check of `src tests` passed. The focused screening suite returned 35 passed / 2 failed,
both naming the unchanged prespec line 31 already recorded above; no scientific wording repair was selected.
The first test invocation lacked pytest in this worktree; `uv sync --extra dev` installed the locked development
environment and the suite then executed. No full-suite, live notebook or hardware check is claimed.
The changed-file privacy scan found only AGENTS.md's existing scan command, not a credential or machine binding.

**Parking / stopping condition.** Broader E1–E8 acceptance remains unmet except the bounded P1 result and the
partial work explicitly established above. Preserve all remaining items and their blockers; do not call the whole
consolidation complete. Stop after the exact pushed head and updated draft PR are verified. Publication evidence
is the PR head and its verification comment, not a new handoff report. Another-machine execution remains untested.

## Decisions and evidence

- The redundancy inventory, with the measured figures, its seven classes and the dispositions E1–E7 derive from:
  summarised in this plan's *Destination* and *Current checkpoint*. Re-measure rather than trust the numbers here; they
  are a snapshot, and the acceptance criteria are stated so they can be checked without them.
- Why the hand-off documents are superseded rather than merely edited — the estate guide's rule that a temporary
  transfer note cannot own unresolved work, and that durable execution state belongs in the selected effort record.
- `docs/plans/TEMPLATE.md` — the field set every plan in this directory uses.
- Draft PR [#71](https://github.com/ajegorovs/udv-echo-process/pull/71) — the convention this plan executes against.

## Next session

**Objective (owner-selected priority).** Continue through the four-sensor notebook-review plan after this
publication/parking pass; do not execute it as part of the cleanup. This consolidation plan is parked, not complete.

**First action.** Read `AGENTS.md` → agenda → the four-sensor plan and reconcile its implementation baseline.
For consolidation, wait for explicit reselection; do not repeat the completed local P1 check.
Before E1/E3/E5 removal, resolve missing explorer evidence and preserve unique measurements, cited
anchors, sidebar constraints and acquisition guardrails in named homes. Stop rather than discard unique material.

**Stopping condition.** Stop when every acceptance criterion in *Destination* is either met with evidence or recorded
as unmet with its reason, and the agenda links the plan-owned result. Stop early, and hand back, if a document turns out to hold
unique content with no destination: report it rather than deleting it or inventing a home.
