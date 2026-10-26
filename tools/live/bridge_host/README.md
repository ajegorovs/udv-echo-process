# tools/live/bridge_host — the host half of the guarded cycle

`--route bridge --bridge-guarded-cycle` asks the module named by `--bridge-runner` /
`UDV_BRIDGE_RUNNER` for one export, `guarded_cycle(*, table, table_path, target_digest, channel)`,
and refuses by name if it does not get a bound `RoutineCycle`. This directory is that export,
implemented against the demonstrated producer's own design.

**It is address-free and machine-independent.** Nothing here knows a pointer, a signature, a build
digest, a pid or a path. The addresses and the build digest stay in the machine-local table; where
the producer lives and where a point lands stay in the host config beside that table.

## Point the run at it

```bash
UDV_BRIDGE_RUNNER=tools/live/bridge_host/bootstrap.py   # or --bridge-runner
UDV_BRIDGE_TABLE=/path/to/table.json                    # or --bridge-table, which is required
```

`bootstrap.py` is a module *file* because `live.bridge_module` loads a file by path. It re-exports
`guarded_cycle` and `activation_report`; importing it reads no configuration and starts nothing.

`--bridge-table` must be passed explicitly: the host config is the table's sibling
(`table.json` → `table.host.json`), so a run that lets the table default from the environment gives
the host no path to find its config. That refusal is named
`host_config_missing:table-path-not-given`.

## Compose the menu dispatch too — a cycle alone is not background-usable

`live.bridge_actuator` reads `module.dispatch` **before** it asks for `guarded_cycle` and gives it to
`BridgeMenu`; without it, channel verification falls back to **hovering the menubar**, a foreground
gesture. So the module the run is pointed at must export both, and the smallest way to get the menu
half is to reuse the proven dispatch unchanged:

```python
# the machine-local module --bridge-runner points at
from bridge_host.api import activation_report, guarded_cycle
from bridge_host.menu import legacy_dispatch

dispatch = legacy_dispatch("<explicit path to the proven menu dispatch module>")
```

`legacy_dispatch` loads that file by path and returns its `dispatch` callable as-is — no
reimplementation, no address in this repository. A host without one is **refused as background
readiness** by the preflight (check `menu_dispatch`), never silently blessed.

## The host config

Copy [`host.example.json`](host.example.json) beside the table, as `<table-stem>.host.json`, and fill
it in. All fields are listed there; the ones that matter:

| field | meaning |
|---|---|
| `store_directory` | the directory the one-time setup establishes. Required, and checked to exist. Each point still names its own `--store-dir`: the commit compares the dialog's answer against **that** one (see below). |
| `producer.argv` | the producer command, as an argument vector. The session directory is appended as its last argument. |
| `producer.cwd` | the producer's working directory, or omitted. |
| `start_/dispatch_/probe_/close_timeout_s` | bounds on one producer round-trip. |
| `total_budget_s` | the session's whole life. A session never outlives it. |
| `*_settle_s`, `store_timeout_s`, `state_timeout_s`, `poll_s` | the cycle's own waits, passed through unchanged. |

## The producer protocol

The producer owns the attachment and the native calls; this package owns the conversation. A producer
implements five conventions:

1. Started as `argv + [<session directory>]`.
2. Writes `<session>/session-ready.json`: `identity` (`pid`, `created_ns`, `image_sha256`), `owner`,
   `owner_source`, `record_handler`, `store_handler`, `message_name`.
3. Reads `<session>/request.json` (`sequence`, `operation`, and — for a dispatch — `address`,
   `form`), removes it, and answers in `<session>/receipt-<sequence>.json`.
4. A dispatch receipt states `ok`, `operation`, `consumed_target` and `errors`; a probe receipt
   states `identity`, `owner_ok`, `owner`.
5. Exits when `<session>/close.json` appears (and may carry its own deadline).

`consumed_target` is the load-bearing field: it says the application's **own message loop** reached
the command. A producer that ran a stub without the loop consuming it reports `false`, and the
session refuses that as `host_dispatch_not_consumed:<operation>`.

## What happens on a run

`guarded_cycle` loads the config, starts **one** bounded session, takes the binding from what the
producer observed, compares it with the table (`host_build_mismatch`, `host_routine_conflict:*`,
`host_owner_not_observed`), and returns a `RoutineCycle` whose caller, identity reader, owner check,
strip reader and store-dialog adapter are the ones in this package. The cycle then dispatches
`record` → `stop` → `store` in that order — the first two through one handler address, which the
caller distinguishes by call count — and commits the store dialog through
`StoreDialogCommit` (`acquire/udop/store.py`).

That adapter is **bound to each invocation's directory** by `BoundRoutineCycle` immediately before
every `try_record_and_store`, because the cycle is built once per command and a sweep runs several
points. It reads the dialog's `Working directory` and refuses a disagreement
(`store_directory_mismatch:<shown>!=<expected>`) **before** writing a name or pressing anything; it
never writes that field, so this route owes no restoration and changes no persisted setting. Its
`True` means the accept was dispatched — the artifact check remains the acceptance.

## Activation first

`activation_report(table=…, table_path=…, target_digest=…, strip_reader=…)` is the passive preflight:
it reads the config, checks the store directory, the table and the producer, then starts one session
to read the identity, the owner and the routines, and closes it. It **dispatches nothing** — a
report whose `ready` is true means the host is configured and bound, not that anything was recorded.
Run it before a recording grant is spent.

## Measured live (2026-10-26)

Two consecutive 2 s points were recorded and stored through `point --route bridge --bridge-guarded-cycle` with a
machine-local producer adapter, against the instrument-mode application: `host-01.BDD` (58 profiles, 2.299 s stored
span) and `host-02.BDD` (57 profiles, 2.259 s), both one 80-gate axial-velocity stream matching the column before the
run at the measured 40.3 ms period. `activate.py` passed every check first. Transducers were disconnected, so those
files are configuration/timing/storage evidence and nothing about a signal.

Two obligations the producer contract did not state and a live run enforced:

1. **Prove the dispatch boundary before the session reports ready.** The demonstrated chain proves one posted
   operation, records that `DispatchMessage` return as its boundary, and refuses every later command whose boundary
   differs. A producer that serves a `record` request without that first operation gets
   `record_not_dispatched:record-refused: Dispatch boundary changed` — a real refusal, and the reason a producer must
   do the proof inside `start()`, not on the first dispatch.
2. **Everything must fit in one attachment window.** The instrumentation host caps an attach at 60 s, so record → stop
   → store → dialog → commit happens inside that budget; a slower store never reaches the commit, because the cycle
   asks for a live identity and owner read immediately before it.

A per-point producer command (a point's name and window are its own) means a per-point table directory: the host
config is the table's sibling, so the pair travelling together is what keeps one run from naming another run's file.

## Limits, stated rather than implied

- The store dialog's `Accept` and the sweep's fresh-block reset are still presses, so a guarded run
  is not input-free.
- A standalone `point` is safe from a `READY` strip; a **second** consecutive per-point run refuses
  (`cycle_strip_not_ready`) because the block is held. Multi-point work belongs on `sweep`, whose
  `SweepRunner` clears the block first (`runner.py:722,959`).
- `RoutineCycle` has no teardown hook, so the session closes at interpreter exit, on its own budget,
  or when the producer reaches its own deadline — not at the instant the point completes. One session
  per command is the whole of what is claimed.
- Offline tests prove the protocol, the state machine, the refusals and the loading seam. They prove
  nothing about a live application: the producer behind them is a stand-in.
