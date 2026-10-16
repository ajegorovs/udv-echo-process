# PLANS.md — what is selected, and where its plan is

One screen for a fresh session: read `AGENTS.md`, then this file, then the selected plan. It states what work is
selected, in what state, and what happens next. It is **not** a changelog and **not** a second agenda: the detail
belongs to the plan, the durable semantics to their own document, and the short area-by-area position to
`docs/agenda.md` § Current progress.

This is the ledger the estate's records-first convention asks for (skill `repository-planning`). It exists because a
restarted session could not reliably answer *what work was open, and how much of it was really done* from the
repository alone.

## Where a task plan lives, and why tracked here

Task plans are **tracked**, one per bounded task, at `docs/plans/<slug>.md`, written from `docs/plans/TEMPLATE.md`.

The convention's suggested layout puts task plans in an ignored `.hermes/plans/` beside an ignored index. This
repository deliberately does not, for three reasons: its reviewers work from the remote and cannot read a file that
exists on one machine only; this repository has always tracked its plan documents (so an ignored tree would be the
*parallel* ledger the convention warns against, not an addition to it); and a plan whose progress nobody can check has
the same problem as a plan nobody can find.

What is genuinely unpublishable — machine bindings, launch commands, absolute paths, credentials — does not belong in
a plan at all: it belongs in the machine-local hand-off (see `docs/dev-handoff.md` and the machine's own notes), and
the tracked plan refers to it without copying it. **Never** put a credential in a plan.

**Not task plans** — these are durable design and semantics documents, they stay where they are, and a task plan cites
them rather than restating them: `docs/signal-model-rework-plan.md`, `docs/pipeline-conventions.md`,
`docs/architecture.md`, `docs/dop3000/*-plan.md`, `docs/udv-analysis-absorption-plan.md`.

## Selected

| Plan | State | Next concrete action |
|---|---|---|
| *(none)* | — | — |

No execution plan is selected. The direction below is selected; it has no plan yet, which is itself the state a
fresh session needs to see rather than an empty file it has to interpret.

## Direction selected, no execution plan yet — owner-selected 2026-10-16

**Four-sensor velocity processing.** Process the committed four-channel rolling recordings,
`data/4-sensor-velocity/` — `200RPM.BDD` loads as four staggered velocity streams, 4 × (400 profiles, 55 gates at
1.095 mm, 44.2 s), adjacent-interval coefficient of variation 1.34.

**State: ready for review.** What is missing is a decision, not an implementation slice:

- how four channels whose visits are staggered get onto one comparable time base. `process/sync.py::synchronize`
  requires an explicit `(round_id, visit_id)` acquisition identity, and `io/dop/bdd.py` emits none by design (the
  block chain is decoded, but the format proves no round or visit identity — see its § *Acquisition topology*), so
  the transform cannot be driven from a real fixture yet.
- consequently: decode an identity, choose a documented alignment rule that does not invent one, or state the
  question as out of scope for now. Nothing else in this effort can be settled first.

A task plan gets written when that decision is taken, not before. Do not invent an estimator on a resampled grid to
have something to show.

## Candidates — not selected, do not start unprompted

- **Cross-sitting agreement (SA5 synthesis)** — the published per-sitting effects have a specified but uncomputed
  cross-sitting contrast; the next step is a bounded synthesis, not another estimator.
- **Comparison notebook (SA6)** and **spatial/modal description (SA3/POD)** — both conditional on the accepted
  backends, per `docs/dop3000/sparse-signal-analysis-plan.md`.
- **Acquisition re-opening** — a miniature automated burst campaign (B7) or the next sparse run (B8). Re-opens only on
  evidence, per `docs/agenda.md` § *Constraints on re-opening acquisition*.
- **`udv-analysis` register items** — three open decisions are listed in `docs/agenda.md`; the pack stays until they
  are taken.
- **Signal-explorer cursor/sidebar rework** — uncommitted, preserved only on a local branch; decide its fate before it
  drifts further.
- **PR [#70](https://github.com/ajegorovs/udv-echo-process/pull/70) review** — a draft awaiting its reader.

## Owner-selected versus agent-suggested

A next-goal proposal belongs here, marked for what it is — a proposal is not a grant, and no plan is created from one.
**Proposal (agent-suggested, 2026-10-16):** decide the four-sensor alignment question above, since it is the one
decision the owner has already asked to move to. **Owner-selected:** the direction itself is the owner's; the choice
of alignment rule is not.

## Proposed, not performed

Folding the long sections of `docs/agenda.md` into their authority documents, leaving only short rows in the
current-progress record. The record's shape is right; the narration under it is what will bloat. It is proposed here
rather than done because those sections are reviewed material with their own evidence, and moving them is a change
someone should see first.
