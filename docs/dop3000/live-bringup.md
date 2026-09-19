# Live bring-up on a second machine

What it takes to prove the acquisition controls work on a machine that has **only this
repository** — no reconnaissance archive, no `dop-control`, no captures, no measurements taken
here. Written for the second-machine test; each stage has a pass criterion, and a stage that
fails names what to look at.

The purpose is *not* to make the code machine-independent. Where this machine's measurements
were folded into the code they are listed under **§4** with what to do when they do not hold:
that is a deliberate edit on the new machine, not a generalization to maintain. What must not
happen is the test being unrunnable because a capability lives in a directory that is not
cloned.

> **Authority (added 2026-09-18, documentation freeze).** This document is the **bring-up
> path** for a machine that has only this repository: the stages, their pass criteria, and the
> measurements folded into the code with what to do when they do not hold. It is not the
> subsystem's architecture ([`acquisition-architecture.md`](acquisition-architecture.md)), not
> the surface/binding model
> ([`acquisition-ui-model.md`](acquisition-ui-model.md)), and its stages are not the refactor's
> device verification procedure ([`device-verification.md`](device-verification.md)) — the two
> are complementary: this proves the controls answer on a new machine, that one proves the
> refactor did not change what they do. Nothing in the body changed at the freeze.

## 1. Prerequisites

- **The application**: UDOP driving a DOP3010 (or its simulator), installed and licensed.
  This machine ran 6.07.4. A different version is the largest single unknown (§4).
- **Python and the project's environment**: `uv sync --extra acquire --extra dev` — the
  `acquire` extra is `pywin32`, which the GUI layer needs and the processing side does not.
- **An interactive desktop** (console session or RDP) that owns the screen the application is
  on, plus **a scheduled task** pointing at this clone — the one-liner is in
  [`tools/live/README.md`](../../tools/live/README.md). Without it nothing that touches the
  application can be started: the agent's shell is session 0 and the application is session 1.
- **The application's own state**, before the first run: a **working directory** configured for
  stored files, at least one channel in **manual** mode (an assisted-mode channel has no
  parameter column to sweep), and the block cap set deliberately ("Do not keep in a block more
  profiles than" — see §4).

## 2. Stage 0 — the logic arrived intact (no instrument needed)

```bash
uv run --extra dev pytest tests/ -q
```

**Pass**: the acquisition suites pass (`test_acquire_*.py`; 144 cases on 2026-09-17) with only
the pre-existing `storage/npy.py` permission failures. This runs the whole acquisition layer
against fakes — the strip, the dialogs, the store window, the runner — with no application
present, so it separates *the code is wrong here* from *the machine is different*.

## 3. Stages 1-5 — against the instrument, in increasing order of commitment

Run each through the dispatcher (`./tools/live/dispatch.sh -m udv_echo_process.cli <command>`),
which starts it in the session that owns the screen and returns when it is done. The commands
come from the package, so a clone carries them; `--json` prints any report for a machine, and
the exit codes are 0 ok / 1 a refused point / 2 usage or configuration. They are preceded by
the one command that needs no application at all — `acquire plan --definition <file>` prints
every point of a job with the window and gate count it would ask for, and states per point what
a block cap means for the stored file, so a definition can be checked before UDOP is installed.

| stage | command | pass criterion |
|---|---|---|
| 1. inventory (`acquire status`) | `dispatch.sh -m udv_echo_process.cli acquire status` | the window is found by class (`TMain_Scr`), the strip shows a view, **`layout_note: None`**, `layout_shape_reasons: []` (the shape verdict) and **`process_mode`** naming the process in front (`simulation` or `instrument`) — the counts beside them are evidence, not a gate. Any other note names what is wrong (a dialog left open, a channel in assisted mode, a different app version's layout) |
| 2. channel read | `dispatch.sh -m udv_echo_process.cli acquire channel 1` | `verified channel: 1`, the panel counts reported, and the run's notes naming the channel's mode (`manual` / `assisted`). The dialog is read, and written only if the channel differs |
| 3. cycle, nothing stored | `dispatch.sh -m udv_echo_process.cli acquire preflight` | record → `recording` → store view → `Do store` opens the **Store dialog**; the working directory it shows is the one configured; cancel returns a clean ready view. Nothing is written |
| 4. one point | `UDV_STORE_DIR=<the app's dir> dispatch.sh -m udv_echo_process.cli acquire point bringup-01 --seconds 3 --expect-mode <simulation|instrument>` | a `.BDD` file appears in that directory, and reading it back yields the application's own words — gates, depth, sound speed, PRF, emissions/profile, burst — which should agree with the application's own display |
| 5. two-point sweep | `UDV_STORE_DIR=<the app's dir> dispatch.sh -m udv_echo_process.cli acquire sweep --seconds 12 --rungs 1,2 --expect-mode <simulation|instrument>` | two outcomes, both `ok`, and `outputs/live/sweep.jsonl` carrying one entry per point: `requested`, `readback_gates`/`readback_resolution`, `file_path`, `file_size_bytes`, `decoded`, `failure: null` |
| 5b. the pre-run check | `dispatch.sh -m udv_echo_process.cli acquire compile --definition examples/campaign-single-channel.json --expect-mode <simulation|instrument>` | exit 0 with the reading's five facts agreeing with the declaration and the block cap `unreadable` (declared, not verified) — and **nothing written**: no store call, no log, no manifest. Then prove the refusal, in both directions: a copy of the definition with one fixed fact changed (`"burst_length": 5`) exits 2 naming that fact with both values; change one readable parameter *in the application* instead and the unmodified definition refuses naming the instrument's own value. Restore it and the same compile is accepted |
| 6. the goal: a campaign | `UDV_STORE_DIR=<the app's dir> dispatch.sh -m udv_echo_process.cli acquire campaign --definition examples/campaign-single-channel.json --log outputs/live/ladder.jsonl --expect-mode <simulation|instrument>` | one stored point per permutation, `N/N point(s) ok` — 6/6 took 104 s on the first machine — a `ladder.manifest.json` beside the log, and `acquire report --log outputs/live/ladder.jsonl` reading the job back with the ladder's own gate counts (797/399/199/100). Re-run it with `--resume`: it finishes in seconds having skipped every point, which is the job tracking. The example carries no store directory of its own — a path from the machine it was written on would assert against the wrong dialog on any other — so this stage supplies it the same way stage 4 does |

Stage 3 is the operator's own sequence without the risk; stage 4 is the first thing that writes
to the instrument; stage 5 is the runner's path end to end; stage 6 is the project's near-term
goal itself — one channel, one ~12 s window, a slot of parameter permutations, and a job that
can be resumed rather than repeated. A stage-1 failure is almost always
configuration (a dialog, the channel's mode); a stage-4 failure is almost always the store
directory or the channel; a stage-5 failure carries its own reason per point in the log.

## 4. What was measured on the first machine, and what to do if it does not hold

| folded-in measurement | where | if it differs on the new machine |
|---|---|---|
| the clean layout is **43 visible controls in 4 panels** on *this* machine, and **44 in 4** on the instrument (`driver.EXPECTED_CONTROL_COUNT` / `EXPECTED_PANEL_COUNT`) | `driver.py`, evidence only | **nothing to set** — do not make a total a gate on the new machine. What a run needs is stage 1's **shape verdict** (`layout_shape_reasons: []`: the `TMain_Scr` window, a menubar band at the client's top, a status band at its bottom, a strip panel whose row length maps into `STRIP_BUTTON_ORDER`, no popup and no dialog panel, and the sidebar column with its seven roles) plus the **stated process mode** (`--expect-mode`, checked against the window's caption). A screen with **no column at all** is refused by name as of Patch 2 rather than read as a mode: the fast-access panel may be hidden by the application's own `Preferences` option while the channel stays manual, so the refusal names both that and an assisted channel (ledger B01), and an **assisted-mode channel** — 21 in 3 — is refused by the same clause. The 43/44 totals are read beside all of it, so a drift is visible without stopping a run |
| the parameters popup is the visible panel at `left == 169` (screen coords) | `driver._poll_parameters_overlay` | the appearance-diff fallback should carry it: measured on 2026-09-17 with the window un-maximised and moved to `(300, 120)` — every absolute screen coordinate shifted — the menu, the dialog, the strip and the Store dialog all still worked |
| the window is found by class name `TMain_Scr` | `driver.MAIN_CLASS` | if a new UDOP version renames it, nothing resolves: set `MAIN_CLASS` for that install |
| the store dialog's geometry (`584x330`, its buttons from the right) | `driver` predicates | dialogs are found structurally; a changed dialog will refuse loudly rather than press the wrong thing |
| the app's **working directory** is asserted before committing a store | `driver.assert_working_directory` | set it in the application, or pass the same path as `UDV_STORE_DIR`. A mismatch refuses the point — by design |
| the application must be **foreground** before any hover | `driver._require_foreground` | click the UDOP window (or Alt+Tab to it) and re-run. Windows' foreground lock refuses a request from anything but the user, so a dispatched probe cannot take it (measured 2026-09-18: `SetForegroundWindow` returns 0 three times), and a console window opened by the launcher is the usual thief. The guard fires **before** the hover, so nothing is opened and nothing is stranded |
| first-run configuration values (sound speed 1460 m/s, first gate 2 mm, gates ~804, PRF 212 µs, 150 emissions/profile, burst 4) | sweep definitions | these are *this* channel's settings, not the library's: read the new instrument's own values off the application (or the first stored file) and pass them to the sweep |
| 12 s of recording at these settings kept ~**8.4 s** of signal | measured, unexplained | check the application's block cap before trusting any delay longer than a few seconds (§5) |

## 5. Deliberately open — do not treat these as solved

- **How much of a long recording is kept.** The delay between the Record and Stop presses is
  exact (measured: 3.0 s and 6.0 s holds, from the confirmed recording view to the Stop press),
  but the stored block is not proportional to it: 3 / 4 / 6 / 12 s delays stored ~106 / ~123 /
  ~156 / ~257 profiles. The counts come from file sizes through the size signature, so the
  exact numbers lean on a calibration taken at another configuration — the sub-linearity does
  not. The point's own record carries no achieved duration (`timing: {target_s: null,
  achieved_s: null}`), which is the field to fill, from the application's *own* count, before a
  campaign compares windows.
- **Real hardware versus simulation.** Everything measured so far is the simulator.
- **A different application version.** Nothing here has been checked against one.
- **The parameter axes the port cannot write yet.** `f_e`, PRF, emissions-per-profile and the
  sampling volume are the sweep matrix's genuine axes, but they are dialog-only fields: the
  port writes the sidebar (resolution and gate count). That gap is in the acquisition handoff,
  not something the second machine will fix.
