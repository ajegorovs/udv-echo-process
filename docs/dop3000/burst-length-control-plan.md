# Plan — burst length as a commanded acquisition parameter

**Status: slices B1–B3 are in PR #35; B4 burst-control commissioning passed on
2026-09-24 (evidence in [`data/burst-commissioning-b4/`](../../data/burst-commissioning-b4/)).
The manual and the stored files separate word 27's receiver-bandwidth definition from the
effective Sampling-volume thickness read in the dialog. B5 job-level integration may proceed;
word-27 promotion is a separate B6 question.** Nothing here re-opens the acquisition
architecture: the plan adds one parameter to the acquisition model that the model already reads,
and every rule it uses is a rule this repository already has.

Burst length is the first acquisition parameter this repository **writes through the
`Operating parameters` dialog** (`Parameters → Operating parameters`, the third popup entry). The
parameters already automated live in the fast-access sidebar; burst does not, and it is coupled to
one other dialog fact, so it is not expressible as "write another GUI field".

---

## 1. The model this plan encodes

```text
Campaign / run-plan
        │
        ▼
Requested acquisition condition        burst = N, emissions = M, PRF = …
        │
        ▼
Compile against the instrument's own state   (already exists: snapshot.py, campaign.py)
        │
        ├── sidebar parameters: resolution, gates, …        (already automated)
        └── dialog parameters: burst                        (this plan)
                ↓
        the application re-derives the sampling volume      (measured, §3 below)
                ↓
        read burst + sampling volume back                   (this plan)
        │
        ▼
Record point → stored `.BDD` → point verdict / provenance
        ├── word 8  → burst            (verified already; make it strict — slice 6)
        └── word 27 → receiver-bandwidth definition/index (separate from effective mm — B6)
```

**The principle:**

> Burst length is **commanded**; sampling volume is an **instrument-selected dependent
> covariate**.

Three consequences, and they are the whole reason this is one parameter and not two:

1. **No explicit sampling-volume writes.** The volume is read on both sides of a burst change and
   recorded; writing it would turn a bounded feature into a two-parameter control problem.
2. **No generic dialog editor.** The change is specific to the burst row and to the dialog
   interaction that has been measured (`acquisition-campaign-compilation-plan.md` §18–§20,
   `tools/live/probes/dialog_write.py`). Nothing here generalises to "the Operating parameters
   dialog, editable".
3. **A requested setting is not applied until the instrument says so**, and a recorded point's
   burst is not valid until the stored file agrees. The transaction is therefore a
   `write → verify → compile → record` chain, never `write → assume → record`.

---

## 2. What is already in place (evidence, not intention)

| what | where | measured by |
|---|---|---|
| the burst row is the dialog's `(column 0, row 1)` value field, a `TComboBox` | `actuator.DIALOG_FIELD_ORDER`, pinned to `tests/data/udop-parameters-dialog-tree.json` | §18.6/§18.8, §18.9 |
| the row's own list: `2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32` | the fake's `BURSTS`; read live, never assumed | §18.9 |
| a selection commits with `CB_SETCURSEL` + `WM_COMMAND(CBN_SELCHANGE)` to the combo's parent, **no Enter** | `driver._combo_select` | §18.9 |
| the dialog is committed with its bottom band's **rightmost** button (`Accept`), refused with the one before it (`Cancel`) | `driver._dialog_button(…, DialogControl.CONFIRM/SAFE)` | §19.1 |
| the dialog states what **precedes** the commit; a re-opened dialog states what the application kept | the transaction's read-back, rung 2 | §19.1, §18.10 run 19 |
| the dialog can state a value the combo does not offer | `ComboReading`, and the fake's volume tail | §18.10 |
| writing the dialog's channel combo **replaces** the dialog (`(655, 364) → (713, 364)`, all handles dead) | `ensure_channel` re-opens; the burst transaction re-resolves its bindings if the panel is replaced | §19.4 |
| the write-order rule: the determining parameter first | `PARAMETER_WRITE_ORDER`, and here burst alone | §19.2 |
| word 8 = burst, word 27 = receiver-bandwidth definition/index (not effective mm) | `parameter-sweep-matrix.md` rows 2 and 9 | §16.1, §9; manual §10.7 |

---

## 3. The coupling, as measured — not as the archive described it

The earlier note ("changing burst auto-selects the sampling volume") is directionally right and
**not** the mechanism. What §18.9/§18.10 measured on channel 1 at `c = 1460 m/s`, `f_e = 4000 kHz`:

* the volume's floor is the emitted burst's own length, `floor(N) = 1000·c·N/(2·f_e)` — the manual's
  own sentence (§20.1: ch. 8.4 p. 47 for the thickness, ch. 21 p. 119 for the gate). It reproduces
  the three measured values: `0.730` at burst 4 (bracketed, `0.584` rejected), `1.095` at 6,
  `1.460` at 8;
* the value in force is `max(remembered, floor)` — where *remembered* is what the operator last
  **wrote**, not what a burst last raised;
* so the coupling is **asymmetric**: `4 → 8` with `0.876` remembered states `1.460`, and `8 → 4`
  states `0.876` again — *the raise was not remembered*;
* the option list is `[the value in force] + a fixed six-entry tail`, and the tail does **not**
  move with the burst: the application can state a volume its own combo does not offer
  (`1.460`, and `3.285` at burst 18, are not in the tail);
* a request below the floor is refused by a **modal warning** (`The burst length should be
  reduced`, a single `Continue`), raised on the select's own notification, and `Continue` applies
  nothing — the field keeps the value from before the request.

This is why the writer never recomputes the volume and never writes it back: the application's
answer is the evidence, and a driver that derived it from the burst would be wrong in both
directions.

---

## 4. Slices

Each slice is independently testable and lands on its own branch/PR.

### 4.1 Slice 1–3 — landed here (`acquire/burst-length-transition`)

**B1 — the typed contract** (`acquire/actuator.py`)

* `DialogField.SAMPLING_VOLUME` — the dependent row, deliberately **not** a member of
  `DIALOG_FIELD_ORDER`, so `DialogParameters.readable()` keeps requiring exactly the three fixed
  facts a reading carries;
* `DIALOG_DEPENDENT_FIELDS` + `dialog_row(field)` — one lookup over both tables, refusing by name a
  field bound in neither;
* `ComboReading(text, items, item_index)` with `entry_of(value)` — the entry that states a value,
  **lowest match wins** (the held value sits at slot 0 *and* at its own place, measured three times);
* `BurstState` (`verified` / `unchanged` / `unverified`) and `BurstWriteResult` — the evidence a
  caller gets instead of "write succeeded": the request, the state, the panel's own mode, the
  dialog's channel, both rows **before** and **after**, the overlay that refused the selection, and
  whether the pending write was discarded.

**B2 — the Win32 transaction** (`acquire/udop/parameters.py::write_dialog_burst_length`,
`acquire/ui/dialog.py::field_at`)

```text
preconditions  channel compared against the one routed; the dialog identified by its channel combo;
               the measured table shape (3 columns of 4/6/5 fields); the three screen anchors agreeing
open           Parameters → Operating parameters
read before    burst row + dependent row (text, entries, the control's own belief)
refuse         unsupported burst · no combo on the row · table of another shape · another channel ·
               assisted panel · request < 1             → nothing is sent; Cancel; UNCHANGED
write          select the entry whose text IS the request (never a step from the value in force)
settle         wait for the row to restate it; re-resolve the bindings if the panel was replaced
overlay        warning → answer its left button and refuse (UNVERIFIED); anything else → name it, leave
               it standing, refuse (UNVERIFIED)
accept         the band's rightmost button
re-open        open the dialog again — the surface that states what the application kept
read after     burst row + dependent row; a row this driver cannot read as the request **raises**
return         BurstWriteResult(state=VERIFIED, before/after rows, channel, mode)
```

The invariants the code enforces:

* **no optimistic path** — there is no `combo.select(18); return`, and no branch that reports a burst
  the instrument has not stated;
* **the dependent row is never written back** — no code path selects the volume;
* **a refusal is explicit and leaves a classified state** — `UNCHANGED` (nothing was sent) or
  `UNVERIFIED` (something was sent and the dialog was cancelled), never a silent success. The dialog
  is closed on every path, including the failure paths (`finally`);
* **the modal rules are the repository's own** — the overlay classifier, the left-button answer, the
  "press nothing into a surface this driver does not own" rule; no new recovery behaviour;
* **a drifted binding is refused, not trusted** — a dialog stating another channel, or a table that
  is no longer the measured shape, is refused before anything is written.

**B3 — the coupled fake and the failure matrix** (`tests/test_acquire_burst.py`, 26 tests)

The fake models the **measured** state machine, not an invented dependency: rows and geometry from
the committed dialog tree, the measured option lists, `max(remembered, floor(burst))` derived from
the manual's law, the pending-vs-kept split (`Accept` commits, `Cancel` reverts), and the measured
asymmetry. It is scriptable for every failure the transaction has an answer for: a burst the row does
not offer, a warning raised instead of the selection, an overlay with no answer, a selection that is
never restated, a row whose control is not a combo, a table of another shape, another channel, the
assisted panel, a dialog the application replaced mid-write, a re-open that states another burst, a
re-open that fails, and a request below one.

**What the fake is there to catch** (measured by mutation, on this branch — each mutation was
applied to `parameters.py`, the suite run, and the file restored):

| mutation | result |
|---|---|
| the result carries the row read in the dialog that was written, not the re-opened one | **3 tests fail** (`after_sampling_volume` = `1.825` instead of `3.285`) |
| the writer selects by counting one step from the value in force instead of by value text | **12 tests fail** |

**B4 — live A/B commissioning** *(control/recording pass 2026-09-24; burst-control gate passed)*

```bash
# the operating instrument stays the operator's: this driver never presses a modal's right button
uv run udv-acquire burst-length 4  --channel 1 --json     # from 10 → 4, read both rows back
uv run udv-acquire burst-length 10 --channel 1 --json
uv run udv-acquire burst-length 18 --channel 1 --json
uv run udv-acquire burst-length 10 --channel 1 --json     # the restoration is part of the test
```

Accept: each call reports `verified` with the burst the re-opened dialog stated, the volume the
application left, and its entry projection; the return to burst 10 states the volume the run began
with. Then one tiny acquisition per burst (`4 / 10 / 18 / 10`, one short reference point each),
requiring `word 8 == requested burst`, a recorded effective Sampling-volume readback,
and every other decoded fixed setting unchanged. The former proposed criterion
`word 27 == the index the recorded readback implies` is withdrawn: word 27 defines
receiver bandwidth, not necessarily the effective thickness displayed in millimetres.

**Observed 2026-09-24:** all four reopened reads verified (`4 / 10 / 18 / 10`), returned to
the initial `10 / 1.850 mm`, and four two-second BDDs decoded word 8 as `4 / 10 / 18 / 10`.
The readback volumes were `1.776 / 1.850 / 3.330 / 1.850 mm`, while word 27 was `1` in all
four files; every other *decoded* configuration field stayed fixed. The inactive rig produced
all-zero payloads, which do not bear on stored settings. See the committed recordings, SHA-256
manifest and paired command logs in [`data/burst-commissioning-b4/`](../../data/burst-commissioning-b4/).
**B4 verdict — pass for burst control.** Manual §§8.4 and 10.7 describe word 27 as the
receiver-bandwidth definition and the dialog's millimetres as effective longitudinal thickness;
when burst length exceeds bandwidth-associated thickness, burst determines the latter. At
`c = 1480 m/s`, `f = 4 MHz`, `cN/(2f)` gives `0.740 / 1.850 / 3.330 mm` for bursts
`4 / 10 / 18`. Using the burst-4 observed `1.776 mm` as the bandwidth-associated
thickness, `max(1.776 mm, cN/(2f))` predicts exactly the four dialog readbacks. This
supports the two-quantity model, not a calibrated mapping from word 27 to mm. In
particular, combo slot 0 displays current effective state, not stored word 27. The
verified transitions, dependent readback, stored word-8 agreement, unchanged other
*decoded* configuration fields and restoration suffice to start B5. Do not derive
millimetres from word 27, explicitly write Sampling volume to restore it, or demand a
word-27-to-effective-mm equality. No further B4 live run is required; B5 still needs
its own end-to-end live acceptance. See the evidence README for the limits and the
older measurement that explicit volume writes can move First gate depth.

**The stop rule, binding: if a later live run shows a *second* hidden dependent effect beyond
the sampling volume, stop the campaign and model that effect before proceeding.**

**B5 — campaign integration (job-level only)** *(after B4)*

Today the runner requires the operator to have set burst before the job; `run_plan.py`
(`RunPlan.validate`, ~line 572) **refuses** a job whose `burst_length` differs from its run-level
reference, and `campaign.py:~1764` carries the definition's burst into the compile. B5 makes the
runner perform the verified transition when the next job's burst differs from the current verified
one, and keeps the existing compilation check as an independent second opinion:
`write → verify → compile → record`. Job-level only: the sparse design groups burst conditions, so
the manual step disappears without changing the campaign model.

**B6 — stored-artifact verification** *(after B4 and B5)*

`word 8 == requested burst` becomes strict (largely supported today). Word 27 is
preserved as the stored receiver-bandwidth-definition index alongside the *separate*
pre-record effective Sampling-volume readback:

```text
requested:            burst 18
pre-record verified:  burst 18 · effective Sampling volume 3.330 mm (dialog)
stored:               word 8 = 18 · word 27 = 1 (bandwidth definition)
```

`burst mismatch → the point is invalid`. Word 27 is **not** a strict oracle for
the displayed effective millimetres: burst length can determine thickness while
the bandwidth selection stays fixed. B6 may investigate or qualify the stored
bandwidth index independently; it must not populate `sampling_volume_mm` from
word 27 or compare a made-up inverse index to the dialog's effective mm.

**B7 — a miniature automated burst campaign** (`4 / 10 / 18 / 10`, all recordings and the
restoration verified) before **B8 — the next sparse experimental run uses it**.

---

## 5. Scope

**In:** automatic burst-length changes; post-write burst read-back; dependent sampling-volume
read-back; job-level campaign integration; stored-artifact verification of burst and the
sampling-volume index; explicit provenance of the transition.

**Out (this branch, and each needs its own decision):** explicit sampling-volume writes; deriving
sampling-volume millimetres from the stored index; automatic first-gate depth; generic editing of
the `Operating parameters` dialog's other fields; restructuring the 3.5k-line driver; a general
dialog-automation framework; per-point burst changes; revisiting the verified sidebar writers.

---

## 6. Definition of done

Burst automation is complete when a run can issue *"job requires burst 18"* from an instrument at
burst 4 with no operator touching the dialog, and the record proves it:

```text
requested burst                  18
GUI verified burst               18
GUI sampling-volume statement     3.285 mm  (and its entry projection)
stored BDD burst (word 8)         18
stored BDD sampling index (word 27)  …
all fixed covariates              unchanged
recording verdict                 ok
final UDOP screen                 clean
```

At that point the manual burst-change step leaves the sparse campaign procedure.

---

## 7. Picking this up cold

```bash
uv run --no-sync --extra dev pytest tests/test_acquire_burst.py -q     # 26 tests, the whole slice
uv run --no-sync --extra dev pytest -q                                  # 2581 passed, 22 skipped
```

Read, in this order: this plan → `acquisition-campaign-compilation-plan.md` §18.9/§18.10/§19/§20
(the measurements this rests on) → `src/udv_echo_process/acquire/udop/parameters.py`
(`write_dialog_burst_length`) → `tests/test_acquire_burst.py` (the fake and the matrix) →
`tools/live/probes/dialog_write.py` (the probe that measured the round trip).
