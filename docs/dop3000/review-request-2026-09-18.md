# Review request — the 2026-09-18 documentation-and-instrumentation delta

The work under review is the **28 commits ending at `ca8bac8`** — everything on `master` after the last
merge commit, committed straight to `master` and never carried by a pull request:

```bash
git clone https://github.com/ajegorovs/udv-echo-process.git
cd udv-echo-process
git log  --oneline 0f894c2..ca8bac8     # the work: 28 commits
git diff --stat   0f894c2..ca8bac8      # the work: 6 files, +3593 / -0
git log  --oneline 0f894c2..HEAD        # + the bookkeeping: this request, and round 2's amendments
```

`0f894c2` is the merge commit of PR #3, which carried PRs #4–#7 with it — everything reachable from that
commit has been reviewed already. **The two anchors are deliberate.** The work ends at `ca8bac8`; the commits
after it are this file and the documentation that answers the first review (plan §25), so a count taken on
`..HEAD` moves with each documentation commit and a count taken on `..ca8bac8` does not. Read the range, not
a number.

The work delta is additive: **no file under `src/` and no test changed** — the plan document, plus five new
files under `tools/live/` (four probes and `compare_reads.py`).

**Status:** reviewed once, as round 2 on 2026-09-18. Its findings and what changed are the table in plan §25;
the amendments are the commits after `ca8bac8`. **The first *code* slice built on that review is open separately
as PR #8** (`feat/acquire-stated-process-mode-layout-shape`), with two findings from its own live verification
posted as comments on the pull request — the plan's §26.12 and §26.3 record them in full.

## What to review, in two halves

| half | where | state |
|---|---|---|
| **completed** — how the application was measured, and what the measurements found | plan §18.9 → §23; `tools/live/probes/{dialog_fields,dialog_shot,dialog_write,main_geometry}.py`, `tools/live/compare_reads.py` | done, committed, green |
| **planned** — the slice that unblocks a recording in real-experiment mode | plan §24 (five decisions in 24.5), §11.1's ordered list | plan only, nothing implemented |

## Reading order

The plan is 2,800 lines and was written to be read out of order:

1. **§11.1** — the live checkpoint: where the work stands and what a fresh session does next, in order.
2. **§21** and **§22** — the two layouts (simulation and real-experiment), measured and compared; the rule
   §21.1 states (an absolute screen coordinate is not a binding).
3. **§23** — today's reads in real-experiment mode, and the finding that blocks item 2.
4. **§24** — the proposed slice for that finding, with the five decisions.
5. **§18.9–§18.12** and **§19**, only where §23 cites them (the dialog writer's semantics).
6. `tools/live/compare_reads.py` last: every table in §23 is its output, and it is the only new code.

## What you can check for yourself

```bash
uv sync --extra acquire --extra dev
uv run --no-sync --extra dev ruff check src tests    # clean
uv run --no-sync --extra dev pytest -q               # 1701 passed, 22 skipped (pre-existing storage/npy.py)
git diff --stat 0f894c2..ca8bac8                     # additive: 6 files, no src/, no tests
python tools/live/compare_reads.py <a.json> <b.json>  # offline; takes any two dispatched reads
```

## What you cannot check, and must not read as verified

- **`outputs/live/`** — every JSON, log and PNG behind §21–§23 is **gitignored by policy**, so the numbers
  in those sections are *transcribed, not independently checkable*. Treat them as reported evidence, in the
  same category as §15.1's simulation acceptance run. The probes that produced them are committed, so they
  are regenerable on a machine that has the application — but that machine is this one.
- **The application** — UDOP 6.07.4 driving a DOP3010, on this machine's session-1 desktop, maximised,
  1920x1080 at 96 dpi. Nothing here is a claim about a different installation or version.
- **The instrument itself** — §21's item 2 is the **operator's report** from the real box, and §23 now
  records that the non-simulation *layouts* were measured on **this** machine's application in
  real-experiment mode, with nothing being measured. Do not read §21/§22's "the instrument" as a second
  machine: §23 states the correction, and the two are worth keeping apart.

## The questions this review should answer

1. **Is splitting the layout gate right (§24.2–24.4)?** It currently does three jobs through one number;
   the proposal is a structural shape check plus a stated mode check. Is anything load-bearing lost, and is
   the shape predicate in 24.3 the one the code already proves per surface (§21.1's table)?
2. **D4 — a strict count only where one was measured.** Simulation keeps `43 in 4` asserted; the
   real mode is shape-checked with its count carried as evidence until §22.6's `Tgc [dB]` question is
   answered. Is that the honest line, or should the slice stop asserting a count anywhere?
3. **D2 — `process_mode` into `CompilationIdentity`.** Does it break resume semantics for existing
   manifests, and is the fail-closed argument (criterion 6 / W4) enough? Note that today the two modes
   differ in the identity only *incidentally*, through `visible_controls` — the very number D4 stops
   asserting.
4. **D3 — where the expectation is declared.** `--expect-mode` required on the record paths (refusing when
   absent, on the `routed_channel` precedent) versus a field in the campaign definition. The proposal argues
   the mode is a property of the machine the operator stands at, not of the science. Is that right?
5. **Are §23's claims sufficiently evidenced for a reader who cannot open the logs?** If a claim needs the
   bytes rather than a transcription, name which one: the policy is that the record, the PR or an artifact
   carries what a reviewer must judge, and the fix is to commit or publish the specific evidence — not to
   widen the transcription.
6. **Two smaller things** the record flags rather than hides: the `89` strays are **four** cells in the
   dumps against the earlier record's **three** (§23.3), and `emissions_per_profile` is an advisory
   covariate, so a disagreement is recorded and not fatal (§23.4). Is either a defect, or does the record
   already say enough?

## The rules this work is meant to be held to

- **Nothing presses that changes state.** No strip button (all three commit), no `Do store`, no popup entry
  below the topmost one, no recording, no write, on any read in §21–§23.
- **A refusal beats a plausible wrong press** — the parameter column, the strip and the Store dialog all
  commit on the press, so a binding that is not where it expects refuses.
- **An absolute screen coordinate is one session's measurement.** The strip is a hand-dragged overlay; the
  repo's coordinates are evidence for the structural rules, never the rules.
- **A fact that is `unreadable` is never silently skipped**, and a channel that is not `routed` is a
  refusal rather than a declaration to trust.
- **The caption is the only discriminator between simulation and real** — not the panel count, which differs
  *because* the layout differs.

---

*This file exists so the request travels with the repository: an agent on another machine needs only the
clone and this path. It is the prompt, not a substitute for the diff.*
