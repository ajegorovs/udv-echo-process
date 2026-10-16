# Reporting consolidation — one home per fact

**Task plan.** Written 2026-10-16. Register: [`PLANS.md`](../../PLANS.md). This is the work a fresh session performs.

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
   their durable content and their dated record; none of them says "resume here", and each names, in one dated line,
   where its live state went.
3. **One current system map.** `docs/architecture.md` (plus `docs/pipeline-conventions.md` for the landed contract) is
   it; `docs/pipeline-architecture.md` and `docs/interpolation-design.md` are dated pointers to it, with any unique
   measurement preserved where it is already cited (`docs/agenda-history.md` § *Superseded concepts*, the rework plan).
4. **Every `docs/dop3000/*plan*.md` carries a status line**, and the closed ones say what they closed with a link to
   the report or record that holds the result. "PLAN, not started" remains a legitimate status — the failure is the
   absence of one.
5. **A result has exactly one home**: `reports/*` for computed results, `data/<experiment>/README.md` for what a
   sitting's files are, the plan for the evidence line. No document summarises another's evidence set.
6. **The machine-local kit carries no state.** `.hermes/scratch/marimo-live/HANDOFF.md` keeps its commands, paths and
   traps (this is what the convention wants local) and loses anything a tracked record should own.
7. `PLANS.md` reads as the newer pattern asks: **current work** plus **unselected findings**, with *no selected effort*
   distinguishable from *no unresolved work*.

**Non-goals.** No estimator, model, transform or test changes. No deletion of evidence, reports, tests or measured
fixtures. No rewriting of historical entries to agree with today's summary — a correction is a new dated line naming
what it corrects. No change to the shared knowledge base or the skills collection from this plan.

**Authorization boundaries.** Owner-stated intent, 2026-10-16: use this plan in a fresh session to perform the
consolidation. That authorises edits to this repository's documentation. It does **not** authorise deleting a document
whose unique content has not been carried forward, committing to `master`, or touching anything outside this
repository.

**Baseline.** Branch `docs/intent-progress-pivot` at `cfd80a2` (draft PR
[#71](https://github.com/ajegorovs/udv-echo-process/pull/71)), whose six commits introduce the record, the ledger and
the plans directory this plan sits in. Re-verify before starting: `git rev-parse --short HEAD`, `git status --short`
(a notebook change may be sitting uncommitted in the primary checkout — see *Context*), and the counts above re-derived
with `find docs -name '*.md' | xargs wc -l`.

## Patterns this work follows

The method is the estate knowledge base's `docs/knowledge-base/dev-and-deploy/WORK-ORGANIZATION.md` — an estate
document, not part of this repository — which is **more recent (created 2026-10-16) than the `repository-planning`
skill** this repository's convention was first drawn from. Where the two differ, the guide governs; it is what shapes
this plan:

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

Divergences of this repository from the guide, kept deliberately and to be re-examined at this plan's closeout: task
plans are **tracked** in `docs/plans/` rather than machine-local (the reviewer works from the remote), and the ledger
is `PLANS.md` at the root rather than a section of an existing status record.

## Current checkpoint

**Established (measured 2026-10-16, on this branch's base):**

- The redundancy inventory: seven classes, summarised below in *Remaining work* as E1–E7, each with its measured
  evidence. `docs/` 22,810 lines / `docs/dop3000/` 21,070; forward-view layer = `agenda.md` 565 + `hardening-plan.md`
  211 + `agenda-history.md` 63; twelve `docs/dop3000/*plan*.md` totalling 7,936 lines; `pipeline-architecture.md` 655
  vs `architecture.md` 349 vs `pipeline-conventions.md` 298; three resume blocks inside 4,892 lines of acquisition
  documents.
- The convention being followed is on this branch and unreviewed: `docs/agenda.md` § Current progress, `PLANS.md`,
  `docs/plans/TEMPLATE.md`, `AGENTS.md` § *Planning a task* and § *Reporting intent and progress*.
- The sibling plans live in the same directory and share this plan's field set.

**Not established.** Nothing has been consolidated yet — E1–E7 are all open. Whether the reviewers consider the
tracked-plans divergence correct is open (PR #71 is a draft).

**Relevant revision / artifacts.** Branch `docs/intent-progress-pivot`, worktree
`.worktrees/intent-progress-pivot`; the primary checkout holds an uncommitted notebook change that this plan must not
disturb.

**Working state / recovery needs.** Nothing half-done. Recovery is trivial: no step of this plan has been executed, so
a fresh session starts at E1.

## Remaining work

Ordered so that nothing is orphaned: each entry either moves content to a named home or converts a duplicate into a
pointer, and each ends with a check that the content still resolves.

- **E1 — the agenda's own narration.** `docs/agenda.md`'s *Active work — …* sections (SA5, the acquisition track, the
  explorer, the sidebar notebook, the marimo follow-ups) restate what § Current progress rows out. Fold each durable
  statement into the authority document the section already names, leave the row, and keep only what is genuinely
  unstated. *Check:* every row's "Evidence / limits" cell resolves to a document that carries the detail; the agenda
  loses narration and keeps decisions.
- **E2 — the hardening list.** `docs/hardening-plan.md` is a third forward view with its own legend. Reduce it to
  items with no home elsewhere, or make it a pointer with the genuinely open P0/P1 rows. *Check:* no item appears in
  both it and the record.
- **E3 — the three resume blocks.** Remove the session-state blocks from `handoff-dop3010-acquisition.md` § *Current
  state and next actions*, `acquisition-closeout-plan.md` § *Resume here*, and
  `acquisition-campaign-compilation-plan.md` § *11.1 Current state — resume here*; each keeps its durable design,
  guardrails and dated record, and gains one dated line naming where its live state now lives. *Check:* the phrase
  "resume here" no longer appears in a tracked document.
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
- **E7 — the evidence overlap.** `docs/dop3000/sa2-3-notebook-preview-evidence.md` summarises an export its own plan
  also describes; leave one home and make the other a pointer. *Check:* the one-home rule of the convention holds for
  results.
- **E8 — the closeout.** Update `PLANS.md` (clear the selection, record outcomes), the agenda rows whose position
  moved, and `AGENTS.md` if the divergence list above changed. *Check:* the acceptance criteria in *Destination* are
  each marked met with its evidence, and any unmet one is stated as unmet with the reason.

**Unselected, deliberately, and not to be started inside this plan:** the four-sensor alignment decision, its notebook
review plan (a sibling plan in this directory), and anything that changes behaviour rather than documentation.

## Decisions and evidence

- The redundancy inventory, with the measured figures, its seven classes and the dispositions E1–E7 derive from:
  summarised in this plan's *Destination* and *Current checkpoint*. Re-measure rather than trust the numbers here; they
  are a snapshot, and the acceptance criteria are stated so they can be checked without them.
- Why the hand-off documents are superseded rather than merely edited — the estate guide's rule that a temporary
  transfer note cannot own unresolved work, and that durable execution state belongs in the selected effort record.
- `docs/plans/TEMPLATE.md` — the field set every plan in this directory uses.
- Draft PR [#71](https://github.com/ajegorovs/udv-echo-process/pull/71) — the convention this plan executes against.

## Next session

**Objective (agreed).** Perform E1–E8 on a branch of its own, one commit per entry, ending with the acceptance criteria
checked item by item.

**First action.** Re-verify the baseline (`HEAD`, `git status --short`, the line counts), then read `docs/agenda.md`
§ Current progress and pick up E1 — the agenda's own narration — because E2–E7 all reference it.

**Stopping condition.** Stop when every acceptance criterion in *Destination* is either met with evidence or recorded
as unmet with its reason, and `PLANS.md` names the result. Stop early, and hand back, if a document turns out to hold
unique content with no destination: report it rather than deleting it or inventing a home.
