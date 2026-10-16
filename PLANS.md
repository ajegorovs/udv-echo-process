# PLANS.md — current work, and where each effort's plan is

One screen for a fresh session: read `AGENTS.md`, then this file, then the selected effort's plan. It states what is
selected, in what state, and what happens next. It is **not** a changelog and **not** a second agenda: the detail
belongs to the plan, the durable semantics to their own document, and the short area-by-area position to
`docs/agenda.md` § Current progress.

**No selected effort is not the same as no unresolved work.** Everything known to be open, selected or not, is listed
below — a session that ends with nothing selected still leaves its findings here.

## Where a task plan lives, and why tracked here

Task plans are **tracked**, one per bounded effort, at `docs/plans/<slug>.md`, written from `docs/plans/TEMPLATE.md`.
Task plans are the only document type called *plans* in this directory; the design and contract documents listed below
are not task plans and do not live here.

The estate convention suggests machine-local, ignored task plans. This repository deliberately tracks them instead:
its reviewers work from the remote and cannot read a file that exists on one machine only, it has always tracked its
plan documents, and an ignored tree would be the *parallel* ledger the convention itself warns against.

What is genuinely unpublishable — machine bindings, launch commands, absolute paths, credentials — does not belong in
a plan at all: it belongs in the machine-local hand-off (see `docs/dev-handoff.md` and the machine's own notes), and
the plan refers to it without copying it. **Never** a credential in either, and **never** a temporary hand-off as the
only home of unresolved work.

**Not task plans** — durable design and semantics, which stay where they are and which a plan cites rather than
restates: `docs/signal-model-rework-plan.md`, `docs/pipeline-conventions.md`, `docs/architecture.md`,
`docs/dop3000/*-plan.md`, `docs/udv-analysis-absorption-plan.md`.

## Current work

| Plan | State | Established today | Next action |
|---|---|---|---|
| [`docs/plans/reporting-consolidation.md`](docs/plans/reporting-consolidation.md) | authorized | the redundancy inventory: seven classes, measured; the convention it executes against is on this branch and unreviewed. Nothing consolidated yet. | re-verify the baseline, then **E1** — the agenda's own narration |
| [`docs/plans/four-sensor-velocity-notebook-review.md`](docs/plans/four-sensor-velocity-notebook-review.md) | authorized | the measured notebook inventory (five notebooks, their plotting APIs, controls and data paths); nothing changed yet | re-derive the inventory, then decide which `channel_preview` twin leads |

The two are independent — the first is documentation, the second notebook tooling — and both are sized for a fresh
session to execute.

## Unselected findings and open questions

Not selected, and not to be started unprompted. Each says what it needs before it could become a selected effort.

- **Four-sensor channel alignment.** `data/4-sensor-velocity/200RPM.BDD` loads as four staggered velocity streams and
  nothing puts them on one time base. `process/sync.py::synchronize` needs an explicit `(round_id, visit_id)` identity
  and `io/dop/bdd.py` emits none by design. Needs a decision: decode an identity, choose a documented alignment rule
  that invents nothing, or declare it out of scope for now. The notebook review above must not pre-empt it by
  resampling to make a view possible.
- **Cross-sitting agreement (SA5 synthesis).** The per-sitting effects are published and frozen; the cross-sitting
  contrast is specified but not computed. Needs the owner to select a bounded synthesis.
- **Comparison notebook (SA6)** and **spatial/modal description (SA3/POD)** — conditional on the accepted backends, per
  `docs/dop3000/sparse-signal-analysis-plan.md`.
- **Acquisition re-opening** — a miniature automated burst campaign (B7) or the next sparse run (B8). Re-opens only on
  evidence, per `docs/agenda.md` § *Constraints on re-opening acquisition*.
- **`udv-analysis` register items** — three open decisions listed in `docs/agenda.md`; the pack stays until they are
  taken.
- **Signal-explorer cursor/sidebar rework** — uncommitted, preserved only on a local branch. Needs a decision on its
  fate before it drifts further (see also the draft PR below).
- **PR [#70](https://github.com/ajegorovs/udv-echo-process/pull/70)** — a draft awaiting its reader; the same draft
  carries the convention this ledger belongs to ([#71](https://github.com/ajegorovs/udv-echo-process/pull/71)).

## Owner-selected versus agent-suggested

Both plans above are **owner-selected**: the consolidation came with the owner's stated intent to do it from a fresh
session, and the notebook review with the owner's request to continue on four-sensor velocity. Anything an agent
proposes appears here marked *agent-suggested* and is **not** a grant; **there are no agent-suggested items open
today**.

## Proposed, not performed

- Folding the long sections of `docs/agenda.md` into their authority documents. This is now **E1** of the selected
  consolidation plan rather than a free-standing proposal.
- Adopting the estate guide's full behavioral patch kit (entry patch + lifecycle skill + issue-capture flow). The
  repository's `AGENTS.md` § *Planning a task* carries the entry rules today; the guide's lifecycle skill and delegated
  cold-start test are not installed, and installing them is a decision for the owner, not a step of either plan.
