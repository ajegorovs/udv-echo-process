# DOP3010 acquisition — architecture and invariants

**What this document is.** The current architecture of the acquisition subsystem
(`src/udv_echo_process/acquire/`), the invariants that the code may not reinterpret, the
target layering and its status, and the boundary of what a cloud-only refactor is allowed
to claim. It is the frozen authority for **architecture, layer boundaries and process** —
not for the mechanism (that is [`udop-automation.md`](udop-automation.md)) and not for
surfaces and bindings (that is
[`acquisition-ui-model.md`](acquisition-ui-model.md)).

**Status of this document.** Written as **Patch 0** of the acquisition refactor: a
documentation freeze with **no code change**. Everything below is either quoted from a
committed artefact, marked *live-reported*, or marked *device-pending*. Where the text
describes code, it describes the tree as measured at the freeze commit named in §4 and
says so; where it describes a target, it says **target** and names the patch that lands
it. Nothing here may be read as a claim that target code exists.

---

## 1. Evidence levels — the three labels used throughout this set

Every load-bearing statement in this document, in
[`acquisition-ui-model.md`](acquisition-ui-model.md) and in
[`device-verification.md`](device-verification.md) carries one of three levels:

| level | means | where it can be checked |
|---|---|---|
| **cloud-verified** | inspectable in this repository alone: committed code, committed fixtures, committed docs, or a tool that runs here | the path or the command is named beside the claim |
| **live-reported / screenshot-supported** | a device or UI observation recorded by the operator or by a probe and committed as text or as a crop — this session cannot reproduce it | cited by crop id (`UI-STRIP-02`) or by the document that records it |
| **device-pending** | must be re-established on the running application before the refactor may be called operational | listed in [`device-verification.md`](device-verification.md) |

Three rules follow, and they are the reason the labels exist:

- a **device-pending** fact is never presented as verified, in any document or comment;
- a painted caption is quoted **only with its crop id**, so the quote stays checkable
  against [`ui-element-index.md`](ui-element-index.md);
- a code claim is quoted as **`path:line`** — and treated as true only for the commit it
  was read at, because this branch is moving (§4).

## 2. The objective this architecture serves

Narrow, and unchanged by the refactor:

> Define a DOP3010 parameter-sensitivity campaign, run it unattended through UDOP, store
> one attributable `.BDD` per point, verify the stored artifact against the requested
> point, and preserve enough evidence to reproduce and analyse the campaign later.

The GUI is an actuator for that objective, not the objective. Anything in this document
that does not serve a point of that sentence is either a safety invariant or out of scope.

## 3. Design principle: OBSERVE → INTERPRET → ACT

```text
OBSERVE   a normalized projection of what the application currently shows
INTERPRET pure classification: which surface is this, is this state safe to act from
ACT       a live gesture, taken only against an interpretation just made
```

Two consequences are structural, not stylistic:

1. **A live gesture never decides what surface it is acting on.** The layer that sends
   `WM_LBUTTONDOWN` must not also be the layer that chose the target. Today those are the
   same module, which is what the target layering of §5 separates.
2. **Every action starts from a fresh observation, and any unexpected state ends the
   workflow.** No speculative recovery, no "press the thing that usually works".

## 4. Landed layout — cloud-verified at the freeze commit

Measured on this checkout at `bfbbb10` (`merge(acquire): PR #8 head (stated process mode +
layout gate) as the refactor base`), branch `refactor/acquire-foundation`:

| module | lines | bytes | what it is |
|---|---|---|---|
| `acquire/driver.py` | 3,899 | 205,996 | `Win32Actuator` — Win32 transport, cursor/foreground/`ClipCursor`, window and tree enumeration, semantic resolution, gestures and the record/store cycle |
| `acquire/campaign.py` | 1,836 | 94,417 | definitions, planning, compilation/reconciliation, resume identity, manifest IO, execution orchestration |
| `acquire/runner.py` | 1,151 | 60,144 | `SweepRunner` — per-point orchestration, logging, verification call sites |
| `acquire/actuator.py` | 694 | 30,715 | the pure `Actuator` protocol, the ported binding tables (`STRIP_BUTTON_ORDER`, `PARAM_COLUMN_ORDER`, `DIALOG_FIELD_ORDER`, …), `StripView`, `ParamRole` (`actuator.py:115`), `ScreenFingerprint` (`actuator.py:435`), `PreflightReport` (`actuator.py:490`) |
| `acquire/verify.py` | 552 | 23,198 | stored-artifact verification against the requested point; `verify_stored_point` at `verify.py:391`, `check_covariates: bool = False` at `verify.py:397`, `CHANNEL_1_OFFSET_BYTES = 548` at `verify.py:90` |
| `acquire/snapshot.py` | 498 | 27,187 | `InstrumentSnapshot` / `CompilationIdentity` / provenance (`FactSource`) |
| `acquire/log.py` | 462 | 21,016 | the JSONL job log and the size signature (`bytes_per_gate_profile: float = Field(default=1.7, gt=0)` at `log.py:182`) |
| `acquire/plan.py` | 387 | 15,779 | pure sweep arithmetic (ladder, gates, window depth, cap assertion) |
| `acquire/config.py` | 308 | 14,007 | configuration value objects and `ChannelSetting` |
| `acquire/live.py` | 179 | 7,480 | live-route defaults and helpers |
| `acquire/__init__.py` | 199 | 5,045 | re-exports (its docstring still says "four concerns, one module each" — stale, see §7) |

Related evidence that stays where it is: `tools/live/` (probes and the interactive-session
dispatcher), `tools/ui/` (the crop checker and magnifier), `docs/dop3000/ui-crops/` (45
committed PNGs), `tests/data/udop-measurement-screen-tree*.json` and
`tests/data/udop-parameters-dialog-tree.json` (committed control-tree fixtures), and the
13 `tests/test_acquire_*.py` modules.

The line and byte counts above are the **freeze-commit measurement**, not a live one: Patch 2
moved the pure half of `driver.py` (the normalized observation, the surface classification, the
shape gate, the mode reading and the geometry the binding rules use) into `acquire/ui/`, and then
its widget slice moved the three remaining pure interpreters after it — the recording strip, the
`Operating parameters` dialog and the one menubar binding (`ui/strip.py`, `ui/dialog.py`,
`ui/menu.py`). `driver.py` re-exports every moved name, so the module is smaller while every
caller still resolves (`driver.screen_mode`, `driver.layout_shape_reasons`,
`driver.dialog_value_fields`, `driver._strip_row`, `driver.PARAMETERS_MENU`, …).

Two of those moves carried a **corrected decision** rather than a moved line, and both refuse
earlier than the code they replace: a menubar whose painted set is not one this anchor was
measured against publishes **no** `Parameters` binding at all, so the one real-cursor hover
cannot be taken against it (ledger B03, `ui/menu.py`), and a four-button strip row without a
slider classifies as `StripView.AMBIGUOUS`, binds nothing, and refuses before the held press is
posted (ledger B10, `ui/strip.py`). Neither is a device claim: the four-button role map and the
anchor's behaviour on the instrument stay *device-pending* (§8), and the refusal is what a
cloud-only change is allowed to add.

**The diagnosis behind the refactor.** `driver.py` is not merely large: it mixes five
concerns that have different evidence and different test surfaces — (1) low-level Win32
transport, (2) cursor / foreground / `ClipCursor` management, (3) live-window enumeration
and structural UI resolution, (4) semantic interpretation of a resolved tree, (5)
state-changing orchestration. Only (5) contains the live-proven gesture recipes; the safe
refactor separates (1)–(4) while leaving (5) behaviourally untouched.
`campaign.py` accumulates definition models, planning, compilation/reconciliation, resume
identity, manifest IO and orchestration, and is split **last**, because acquisition
semantics currently move faster than campaign abstractions.

## 5. Target layout — **status: target** (one line per layer, with the patch that lands it)

None of the modules below existed in the tree at the freeze commit. `ls
src/udv_echo_process/acquire/` at `bfbbb10` shows only the flat module list of §4, and
`acquire/ui/` holds that list's first five entries as of Patch 2 (the layout slice, then the
widget slice: the strip, the dialog and the menubar anchor). Read every path in this section as
a **plan**, and check the tree before relying on one.

| target module | layer | status |
|---|---|---|
| `acquire/ui/model.py` — `Rect`, `UiNode`/`UiTree`, `SurfaceKind`, `ParameterPanelState`, `StripObservation`, `MenuObservation`, `DialogObservation` | normalized observations | **landed by Patch 2 (layout slice)** |
| `acquire/ui/layout.py` — measurement / overlay / dialog / popup / replacement / unknown classification | pure interpreter | **landed by Patch 2 (layout slice)** |
| `acquire/ui/strip.py` — pure strip observation and classification (`strip_row`, `has_slider`, `strip_state_of`, `press_refusal`, `strip_clauses`) | pure interpreter | **landed by Patch 2 (widget slice)** |
| `acquire/ui/dialog.py` — operating-parameters table binding, widget-aware value extraction (`dialog_value_fields`, `dialog_refusal`, `channel_mismatch`, `_is_dialog_panel`, `bottom_row`) | pure interpreter | **landed by Patch 2 (widget slice)** |
| `acquire/ui/menu.py` — the `Parameters` anchor and its expected popup, and nothing generic (`anchor_clause`, `anchor_button`, `entry_buttons`, `observation_text`) | pure interpreter | **landed by Patch 2 (widget slice)** |
| `acquire/win32/messages.py` — `SendMessageTimeoutW`, posted held click, text commit, combo read/select | Win32 mechanics | **target — Patch 3** |
| `acquire/win32/cursor.py` — foreground checks, real cursor move/restore, `ClipCursor` | Win32 mechanics | **target — Patch 3** |
| `acquire/win32/tree.py` — enumerate the main window, visibility, normalize into `ui/model` nodes | Win32 mechanics | **target — Patch 3** |
| `acquire/udop/parameters.py`, `recording.py`, `store.py`, `session.py` | UDOP workflows (the only layer that combines observations with actions) | **target — Patch 4** |
| `acquire/campaign/{models,planning,compile,resume,run}.py` | campaign decomposition | **target — after device verification** |

Rules the target layout pins:

- **No HWND is a semantic identity.** A live handle is valid only as an action reference
  for the resolve that produced it; an `hwnd` changes on every application restart.
- **No DOP experiment policy in `win32/`**, and no `WM_LBUTTONDOWN` knowledge in `ui/`.
- **A `StripBinding` that carries executable button roles exists only for known-safe
  strip states** — ambiguity has no binding, not a default one.
- **Compatibility first:** `from udv_echo_process.acquire.driver import Win32Actuator`
  keeps working; the `Actuator`/`SweepActuator` method names, the CLI behaviour and the
  campaign JSON do not change; implementations move behind compatibility imports rather
  than every call site changing at once. `udop/session.py` may re-export the existing
  `Win32Actuator` interface while the rest of the repository stays still.

## 6. Phase plan, and which patch lands what

The phases are ordered by risk, and the order matters: the pure model comes before the
Win32 extraction, and both come before any gesture algorithm is touched.

| phase | content | patch |
|---|---|---|
| **R0** | freeze behaviour and evidence: this documentation set, the blind-spot ledger, the counterexample tests | **Patch 0 (this)**, Patch 1 |
| **R1** | extract the pure UI semantic model (`acquire/ui/`), inputs are normalized rows or committed fixtures, no Win32 calls | Patch 2 |
| **R2** | isolate Win32 mechanics (`acquire/win32/`), thin and boring, no experiment policy | Patch 3 |
| **R3** | retain the compatibility façade: `Win32Actuator`'s high-risk gesture algorithms move by **verbatim extraction with regression tests** — menubar real-hover, popup held press, numeric commit, dialog close/cancel, record/stop/store held presses, Store dialog directory/name handling. No algorithmic "cleanup" while moving them | Patch 3/4 |
| **R4** | split live workflows by surface (`acquire/udop/`) — Parameters, recording, Store, session | Patch 4 |
| **R5** | campaign module decomposition, re-export compatibility retained until callers and tests migrate | after device verification |

**Patch 5 is device verification** (a discrepancy is its own commit); **Patch 6** promotes
the verified invariants out of *device-pending*; **Patch 7** adds writers and axes only
when the sensitivity matrix requires them. The ordering rule from the acquisition verdict
stands: do not start by splitting `driver.py` — if the models and interfaces come first,
the decomposition has obvious destinations.

## 7. Invariants

These are the architectural rules that survive the refactor. The *mechanism* invariants —
what commits a value, in which order, and which failure modes silently invalidate a point —
have one authoritative copy in [`udop-automation.md`](udop-automation.md) and are **linked,
never restated** here. The surface and binding invariants have one authoritative copy in
[`acquisition-ui-model.md`](acquisition-ui-model.md).

**Layering**

1. **Observation before interpretation, interpretation before action** (§3). A module that
   presses must not be a module that classifies.
2. **A refusal is a first-class outcome.** An unrecognised surface, an unproven anchor, an
   ambiguous strip state and a dial-reading disagreement all end the workflow with a named
   reason. Never guess a recovery, never promote an absence to an observation.
3. **Surface before target.** Classify the top-level surface and any active overlay before
   resolving a press target. An overlay can otherwise be selected as a candidate strip
   panel and the diagnosis that follows blames the wrong thing (ledger B06).
4. **Counts are evidence, not gates.** Visible-control totals move with the channel's TGC
   mode and differ between the simulation and the instrument; they belong in diagnostics
   and in the record, and never in resume identity or a cleanliness verdict.
5. **The raw tree is a session artefact.** Bind against a normalized *visible* projection;
   keep raw rows as diagnostics; never bind a surface to a pre-show rectangle or to a
   handle taken before a state change.
6. **A generic menubar index map does not exist.** Only the `Parameters` anchor is
   exposed, with a structural signature and a post-open content verification — landed by Patch 2's
   widget slice as `acquire/ui/menu.py`, which publishes the anchor by its **relative location**
   in a bar of a measured painted length, and refuses before any cursor movement when it cannot
   (`anchor_clause`, `anchor_button`; no name is assigned to a button by position).
7. **The artifact is the authority.** GUI success is not verification: a stored `.BDD`
   decoded **for the requested channel** is what makes a point count
   (`acquire/verify.py:391`, `verify_stored_point`, called with the run's channel at
   `acquire/runner.py`). The size signature (`acquire/log.py:182`,
   `bytes_per_gate_profile = 1.7`, acceptance band a factor of two) stays a gross
   corruption detector, never a statement of how much valid observation time exists.
8. **One authoritative copy per fact.** Where a fact lives elsewhere, the text here links.
   Duplicated prose is how the chronology became the truth in the first place.

**Process**

9. **Proven gestures move verbatim.** A gesture that was paid for with a live slot is
   moved, never re-derived and never "improved" during a move.
10. **No new writer without a scientific axis.** Implement a writer only when the
    sensitivity matrix says that axis is required.
11. **A point that failed is invalid, not "approximately fine".** Stored + decoded for the
    right channel + verified, or invalid; a point that saw a memory/cap warning is
    invalid however valid its file looks (`udop-automation.md` §7, §12.4).

## 8. The cloud-only validation contract

A refactor performed without the instrument **may** claim:

- pure-model tests pass against committed fixtures;
- package imports and static checks pass (`uv run --extra dev ruff check src tests`,
  `uv run --extra dev pytest -q`);
- no public behaviour was intentionally changed, and existing fixture cases remain stable;
- newly discovered counterexamples **fail safely** (refuse) rather than press.

It **may not** claim:

- menubar anchors still hover correctly;
- any moved Win32 code still commits a live field;
- strip-state transitions are correct — least of all the four-button state;
- Store-dialog behaviour is unchanged on the device;
- the real/simulation UI-state classifications are complete.

Those stay **device-pending** until [`device-verification.md`](device-verification.md) has
been run and its results written back.

## 9. Exit condition for the refactor

The refactor is ready for device takeover when:

- all cloud tests pass and the static checks are clean;
- no live-proven gesture algorithm has changed semantically;
- every state-changing method sits behind an explicit precondition or fresh observation;
- a dedicated device verification checklist can exercise the behaviour in one short
  ordered session; and
- unresolved states — especially the four-button strip — **refuse rather than guess**.

## 10. Reading module status on this branch

`src/udv_echo_process/acquire/` is being split into `acquire/ui/`, `acquire/win32/` and
`acquire/udop/` on this same branch while this documentation freeze is written. Two rules
keep the docs honest against that:

- **Re-check before you rely.** `ls src/udv_echo_process/acquire/` is the cheapest check;
  a path in §5 that does not appear there is a target, whatever any document says.
- **A document that names a module must name its status.** "status: target / landed by
  patch N" is the required form, and prose that describes target code in the present tense
  is a documentation defect to fix, not a harmless shorthand.
