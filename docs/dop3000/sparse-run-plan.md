# The first sparse pass, encoded — nine jobs, one order, one record

> **Status:** implemented. This document describes what
> [`examples/sparse-mixer-first-pass/`](../../examples/sparse-mixer-first-pass) contains, what
> `src/udv_echo_process/acquire/run_plan.py` checks before anything is recorded, and what the pass
> still leaves to the operator. It changes no acquisition architecture: no writer, no reader and no
> gesture were added (the batch review's stop condition,
> [`acquisition-campaign-compilation-plan.md`](acquisition-campaign-compilation-plan.md) §9.1), and
> the job a pass hands to the runner is the campaign layer's own, unchanged.
>
> **What it encodes.** [`sparse-parameter-set.md`](sparse-parameter-set.md) §3.1's rows and §3.2's
> two control kinds, as executable `CampaignDefinition` files plus the run-level order the rows
> deliberately do not carry (`existing-sweep-analysis-plan.md` §9.2, §10.2). It is the slice that
> document's §9 asks for: the set encoded, the writers it needs added — and it needs **none** — and
> the controls and reference jobs recorded as points rather than as a convention.

## 1. The pass as encoded

| | |
|---|---|
| run plan | `examples/sparse-mixer-first-pass/run-plan.json` |
| job definitions | `examples/sparse-mixer-first-pass/jobs/<job>.json` (nine files) |
| channel | 1 |
| window | 12 s per recording — §4's assumption of at least 11.52 s, so every record truncates to the common comparison window |
| frame | sound speed 1480 m/s, first gate 10.1626666667 mm (both dialog-only: set by hand, and a disagreement refuses) |
| run-wide | PRF 600 µs for the whole pass (§1); burst and emissions per job |
| names | `<root>-<job>-<label>-<stamp>` under one root (`sparse1`) |
| store | `outputs/live/store` |
| block cap | 2500 profiles — the pass's own requirement, declared (see §3) |

The job order is the one the design intends, with each reference check **between** two scientific
jobs:

| step | job | kind | burst | emissions | recordings | between |
|---:|---|---|---:|---:|---:|---|
| 1 | `burst-4` | scientific | 4 | 20 | 5 | — |
| 2 | `common-reference-1` | common-reference | 10 | 20 | 1 | `burst-4` / `burst-18` |
| 3 | `burst-18` | scientific | 18 | 20 | 5 | — |
| 4 | `common-reference-2` | common-reference | 10 | 20 | 1 | `burst-18` / `emissions-8` |
| 5 | `emissions-8` | scientific | 10 | 8 | 4 | — |
| 6 | `common-reference-3` | common-reference | 10 | 20 | 1 | `emissions-8` / `emissions-64` |
| 7 | `emissions-64` | scientific | 10 | 64 | 4 | — |
| 8 | `common-reference-4` | common-reference | 10 | 20 | 1 | `emissions-64` / `emissions-128` |
| 9 | `emissions-128` | scientific | 10 | 128 | 4 | — |

A scientific job's point order is the design's own: a block-local control **at the beginning of the
run**, the block's scientific rows, a control **around the middle** and one **at the end**
(`sparse-parameter-set.md` §3.1). For a job with two scientific rows the middle control falls between
them; for the one-row emissions jobs it falls after that row, which is where "the middle" is in a
one-condition run.

The three windows of the pass are the design's own — 0.617 mm × 145 gates, 1.850 mm × 50 gates and
2.960 mm × 31 gates — requested in mm, exactly as the committed reference recordings carry them
(`res/0-6.BDD`, `res/1-8.BDD`, `res/3-0.BDD`); a job's own window is what its rows move, and nothing
else in a row moves.

## 2. What is checked statically, before any recording

`udv-acquire run-plan --plan examples/sparse-mixer-first-pass/run-plan.json --check` plans all nine
jobs, touches no instrument, and refuses — naming the step, the job and the point — when:

- a job's file disagrees with the pass on any run-wide fact: channel, window length, name prefix,
  store directory, block cap, or the window frame of any point;
- a job's run-wide burst, emissions or PRF is not the value the plan states for it, or the PRF moves
  at all (§1 holds 600 µs; 250 µs is deferred, not acquired);
- a point's window is not one of the pass's three, a scientific job acquires one window twice, or the
  plan declares a window nothing acquires;
- a scientific job records at the reference condition — the design has no such row, because the
  reference is already committed and is repeated only by the reference-only jobs;
- a block-local control is not the pass's reference window, or the controls are not at
  beginning / middle / end;
- a reference-only job is not exactly one recording of the true reference condition, or one of its
  recordings is labelled as a control;
- two points of the pass share an identity (one store directory, one root: a shared identity is a
  point a resumed pass cannot place);
- the declared block cap is below the pass's requirement, or any point would wrap it;
- the job sequence does not open and close on a scientific job with every reference check between
  two scientific jobs, or steps are not 1..N, or two jobs share one definition file.

Two of those have no counterpart in the campaign layer and are the reason this module exists: the
**cross-job order** (no single definition can carry it) and the **control placement** (a definition
carries its point order, but nothing checks that the order is the design's).

**D1 cannot be compiled into this plan at all.** Its two ingredients are a sensitivity other than the
reference's and an echo/energy channel; the run plan's four models are `extra="forbid"` and carry no
`sensitivity` field, so a file that names one is refused by field. What the pass records is therefore
exactly the seven executable scientific conditions plus their controls and the reference checks — the
counts the decision table derives, minus the one blocked condition.

## 3. The pass's own policy: what it raises, what it declares, what it cannot check

**Raised: emissions per profile.** The compile's own table calls `word 14` a *warning*
(`acquire/verify.py::ADVISORY_COVARIATES`), because a definition's value for it used to be derived
from the period law to reproduce a stored profile count rather than asked for. For this pass it is
not a derivation — it is the factor that separates E8 from E64 and E128 — so the run plan **raises**
it (`strict_facts`), and the raise is enforced on **both** sides of the recording:

- before it, the compile refuses a job whose declaration and the screen's column disagree, instead of
  recording an advisory and running (`campaign.compile_campaign(strict_facts=...)`);
- after it, the stored file's own `word 14` is compared **into the verdict** rather than into the
  advisories, so a file that disagrees invalidates its point instead of being logged with a note
  (`verify.verify_stored_point(strict_covariates=...)`, reached through
  `SweepRunner(strict_covariates=...)` and `campaign.run_campaign(strict_facts=...)`).

The table's default is unchanged for every other campaign, and the raise is only offered for a fact a
stored file carries a word for — enforced before a recording but not after it would leave the dataset
weaker than the policy claims, so the block cap can never be raised and a plan that tries is refused.

**Declared, and *not* verified: the block cap.** It is an application *preference* with no reader in
this repository (`sparse-parameter-set.md` §9, W1 §14), so the pass declares its own **retention
requirement** rather than defaulting to a number nothing checked: the achieved profile period is never
shorter than the programmed `emissions × PRF` of one profile, so a cap at least
`ceil(T / (emissions × PRF))` cannot wrap any point of this pass whatever the transfer term turns out
to be. For this pass that is 2500 profiles.

**That number is a requirement, not a device capacity, and the difference is not academic.** This
installation once accepted a very large value for its own *"Do not keep in a block more profiles
than"* setting while an observed block nevertheless stopped far short of it, so the preference's
displayed value does not prove what the block retains. **Effective retention is a property of the
stored files and is measured from them** — count, timestamp span and the achieved period — never read
off the preference and never inferred from a successful decode. §5 makes that the first gate of the
trial.

**Declared: the first gate's own rendering.** The frame is declared as the value the forty committed
recordings carry in their words. If the `Operating parameters` dialog renders that setting with a
different last decimal, the compile refuses *before* the first recording — naming both sides — and the
number the dialog states is then the number that belongs in the run plan. That is the designed loop,
not a defect: a declaration is compared with the application's own text, and the file's own words are
the authority afterwards.

Also unchanged and still true: the stated process mode is declared per run (`--expect-mode`), the
block cap stays explicitly unproven, and no pass may move the PRF, emitting power, TGC, sensitivity or
the velocity scale — §1's fixed facts are listed on the sheet, and the ones no reader reaches are
confirmed by hand.

## 4. The pass's own record

The run-level record is `<store_dir>/<plan>.run.json` — one row per job, in plan order, written
before the first job and updated after each. Each job keeps its own log and manifest
(`<store_dir>/<plan>-<job>.jsonl` + `.manifest.json`), because `campaign.run_campaign` proves a
resume against the manifest beside the log it was given: one shared log would make the second job's
resume refuse the first job's fingerprint.

`record_job` refuses a job that is not next, with the step that stands in front of it. That is the
one thing a per-job resume cannot check and the reason the pass has a record of its own: a
common-reference check means something only if the job it follows actually ran. `--resume` inside a
job is unchanged — it still skips exactly the points that job's log holds as ok.

## 5. The bounded trial: the gate before the rest of the pass

Two jobs first — step 1 (`burst-4`), then step 2 (`common-reference-1`) — because that pair is the
highest-value missing measurement (the pitch × burst corner) and the cheapest exercise of everything
this slice adds: a run-wide burst set by hand, two resolution/gate writes inside one job, the
block-local control placement, the fixed window, the pass's own record, and the transition into a
reference-only job.

**"Five of five points stored" is not the gate.** The trial is diagnostic; the questions it has to
answer are about the *data*, not about the run's exit status:

1. **Retention, from the stored files.** For every point: the stored profile count, the first→last
   record stamp span, and the achieved period, against the ≈12 s window the pass asked for — i.e. does
   the file cover the requested comparison interval (≥ 11.52 s of usable physical time under the
   existing normalization rule), or is there any sign of ring-buffer truncation? A file that decodes
   cleanly and covers only its last few seconds is exactly the failure the block cap can produce, and
   the only place it is visible is the file's own timestamps.
2. **The window, from the stored files.** Requested resolution/gates read back as the rung and count
   asked for; `word 8` (burst) 4; `word 14` (emissions) 20; `word 5` (PRF) 600; `word 19` (sound speed)
   1480 — the same words the committed reference carries.
3. **The order.** The five recordings appear as `ctrl-begin`, `cc1`, `ctrl-mid`, `cc3`, `ctrl-end`, and
   the pass record places `common-reference-1` between `burst-4` and `burst-18`.
4. **The records.** Each job's log and manifest exist under the pass's store directory, the job's
   definition fingerprint is the plan's, the pass record advances one step per job, and a re-run of a
   finished job resumes to zero points to run.
5. **The reference check restores the reference condition.** `CR1` re-reads and re-records burst 10 /
   emissions 20 at the reference window, and its own words say so.
6. **No compile advisory remains for a fact this pass treats as mandatory** — the raised fact above
   has no advisory left to record — and no unexplained modal, popup or overlay is left up afterwards.

**The stop condition, stated in advance.** If the effective retention measured in (1) is materially
short of the requested window — the shape the ~257-profile observation would produce, ~5-6 s at this
period — then **the trial stops there**: that invalidates the 12 s protocol assumption in
`sparse-parameter-set.md` §4 and has to be resolved (a shorter window per recording, a cap that is
actually raised, or a different profile period) before the remaining seven jobs are spent. Only if all
six hold does the plan stay frozen and the remaining jobs run.

## 6. Using it

```text
# what the pass is, and that it compiles — no instrument needed
uv run udv-acquire run-plan --plan examples/sparse-mixer-first-pass/run-plan.json --check

# the operator's sheet: run-wide values, points, and what to set by hand
uv run udv-acquire run-plan --plan examples/sparse-mixer-first-pass/run-plan.json --sheet

# where the pass stands
uv run udv-acquire run-plan --plan examples/sparse-mixer-first-pass/run-plan.json --status

# run the next job (records; declares the process this pass was measured against)
uv run udv-acquire run-plan --plan examples/sparse-mixer-first-pass/run-plan.json --next \
    --store-dir outputs/live/store --expect-mode <process>
```

The pass's raised facts are part of what `--check` and `--sheet` state, and they travel with every job
`--next` runs: the compile refuses on them, and the stored file's own word is compared into the verdict
(§3). The trial's acceptance gates are §5.

## 7. What does not come from this slice

The analysis of the new data is its own work (ingest and QC of the stored files, per-job drift,
the reference checks across runs, the pitch × burst contrast), and it is deliberately not part of
this slice: it reads files that do not exist yet. Nothing here decides the second, denser stage.

Two deferrals came with the review of `5946185..2f929ea` and are recorded here so they are not
rediscovered later. Neither weakens the pass: enforcement is per point, and a stored `word 14` that
disagrees fails the point.

- **Why a fact was enforced, not just that it was.** The verifier folds a raised fact into
  `enforced_covariates`, so a point's log entry lists `emissions_per_profile` as enforced without
  saying whether the verifier's own table enforced it or this pass raised it. The pass's policy is
  in `run-plan.json` (`strict_facts`), so nothing is lost while the plan travels with the data;
  what is missing is the answer *from a point's own record*. That matters only to a later reader
  auditing a single point without the plan (a per-point certificate), which is when the strict
  tuple should be copied into the durable point record — not before.
- **Reading the first trial gate off the file.** Gate 1 of §5 — retained profile count, first→last
  stamp span and achieved period against the ≈12 s window — is measured by hand today. Measuring it
  from a stored file as soon as one exists belongs to the analysis ingest, which is its own step;
  the trial is deliberately not gated on tooling that does not exist yet.
