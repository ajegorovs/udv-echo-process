# The guarded cycle — the contract a host provider has to satisfy

**Status (2026-10-26): contract only.** The package side is implemented, offline-verified and independently reviewed at the
local source checkpoint `29cbd0a` (not published), but this slice supplies **no production host provider**: no real configured host export and no
current-instance binding was implemented or validated, and no live run exercised the new guarded route — the cycles that
did run were driven by fake providers in tests.
This is the durable half of that slice: what a host must supply, what the package refuses regardless, and what stays unproved; the register, checkpoint and history are in
[`../plans/message-route-port.md`](../plans/message-route-port.md).

## What is selected

`--route bridge --bridge-guarded-cycle`, on `point` and `sweep` only. The selection is **closed**: refused on the `ui`
route, refused alongside an injected cycle, refused when the host cannot produce one — and a refusal never falls back to the press dispatch. Anything not asking for the flag keeps today's
behaviour: `--route ui` is the default, the legacy bridge press path unchanged.

## The factory

The host module is the one the run is already configured with (`--bridge-runner` / `UDV_BRIDGE_RUNNER`); the guarded cycle is one optional export on it, named `guarded_cycle` and called
**at most once per construction**, keyword arguments only:

```
guarded_cycle(*, table, table_path, target_digest, channel) -> RoutineCycle
```

`table` is the validated table the run itself refuses on; `table_path` is where it came from, metadata for the host's own audit; `target_digest` is the caller's declared build digest or
`None`; `channel` is the channel asked for. **A request already known to contradict the table is refused before the factory runs** — that comparison needs nothing a host would produce.
Everything else is checked on the returned cycle, by which time the factory may already have observed the running application, because that is how a binding is taken.

Two things it may not do: start, stop or store a recording — the factory constructs, the cycle executes — or return anything that is not a `RoutineCycle`, which is what stops a generic
store cycle passing as the hardened one. The refusals are the code's, not this document's: `GuardedCycleFactory` and `guarded_cycle_from` in
[`bridge.py`](../../src/udv_echo_process/acquire/bridge.py), pinned by [`test_acquire_cycle_factory.py`](../../tests/test_acquire_cycle_factory.py), which also asserts that a static
conflict calls the factory **zero** times.

## The binding, its identity and its guards

A `CycleBinding` names the owning object and the two routine addresses the cycle dials, each as an observed address with the **source of the observation** beside it — audit metadata,
not a check — and the identity `pid` + `created_ns` + `image_sha256`. A pid alone is not an identity: the operating system reuses it, so the same pid with another creation stamp is a
different process and every pointer observed on the old one is stale. The build digest is read, never computed here. A null or unmapped pointer is a fact worth naming, so it is
constructible and refused rather than a construction error.

Three host-supplied guards are required: `identity` reads the live instance, `owner_valid` answers yes-or-no about one pointer (a truthy non-boolean is malformed evidence, not a pass),
and `read_strip` returns the strip's current view. There is deliberately **no unguarded mode** — a flag there would be the stale-pointer hazard with an opt-out.

## Static readiness, then runtime revalidation

Two questions, two checks. **Is this cycle fit to dispatch at all?** `configuration_problem()` is pure: it reads only what the cycle already holds, touches no process, and so can be asked
by a factory without invoking any live reader — the factory itself may already have observed the application to bind a cycle. It names a missing binding, a missing or non-callable guard, a null pointer, or a binding that contradicts the routines it would run.
**Is the instance still the one the binding was taken on?** Asked again before **every** dispatch and once more before the commit — because the interesting change happens *during* a
recording, and a restart between start and stop must not be answered by calling the new instance's object with the old instance's pointer.

The cycle also confirms its own transitions instead of trusting a dispatch report: the strip must show `RECORDING` after the start and `STORE` after the stop, within a bounded poll — an
unconfirmed start cannot record a successful start, and an unconfirmed stop requests no store and commits nothing.

## Reports

`CycleReport` is typed, immutable and attached to the cycle on **every** exit — including refusals before the first call — and reset at the start of each invocation, so a caller can never
read a stale victory. `stage` says where the cycle stopped, `last_view` is the last view it actually confirmed, and the flags say what was reached, not what was attempted.

The actuator exposes `last_cycle_report` with `cycle_report_problem` beside it, read once immediately after the single cycle call. The pair is the interface because `None` has two
meanings that must not merge: **absence** (no such capability — a legacy or generic cycle, or a point refused before its cycle) and **malformed** (a report was offered and could not be
used: unreadable, not a report, or another cycle's). A claimed store whose report is foreign or says `stored=False` is refused rather than credited; a sweep point whose report cannot be
attributed refuses the point and stops the run, because a cycle whose account of itself does not hold cannot establish where the application is.

`SweepPointRecord.cycle_report` is optional and sits beside `status`/`failure`, because "the stop was never dispatched" and "this file is not this point's data" send a reader to different
places; a log written before the field existed reads back `None`. See [`log.py`](../../src/udv_echo_process/acquire/log.py) and
[`test_acquire_cycle_reporting.py`](../../tests/test_acquire_cycle_reporting.py).

## The stored file is the acceptance

A cycle succeeds on the artifact, not on its own optimism: the requested file must exist and be **non-empty** (zero bytes is refused before any decoder is asked about it), must decode to at
least one stream, and must yield a finite, non-negative span. The span is reported with an optional caller-set ceiling — it is the application buffer's age, **not** the recording window, so
it is not a duration check. The file must also be *this point's*: its directory, and its name exactly or with one application-added suffix, because "a file exists" is satisfied by the
previous point's block ([`test_acquire_cycle_safety.py`](../../tests/test_acquire_cycle_safety.py)).

## What it does not remove

The Store dialog's `Accept` and the sweep's pre-point block reset are still presses (register rows 7 and 18), so a guarded run is **not** input-free. Record, stop and store still need an
owning object observed on the **current** instance: given correct identity and owner validation the guarded cycle makes a stale one refuse loudly instead of faulting — but it does not
find a fresh one, and a guard callback supplied by an external host cannot itself be shown correct from here. Owner rediscovery after a restart, live adapter compatibility and
deployment are outside this slice and unproved by it.

## The saved-report fixture

[`tests/data/bridge_dispatch_s3_run_20261022_06.json`](../../tests/data/bridge_dispatch_s3_run_20261022_06.json) and its companion `.provenance.json` are a faithful, path-normalised
projection of one real recorded cycle. They ground **schema compatibility only**: that the strict parser reads a real cycle's own words as typed evidence and refuses it when altered — not
that a current request produces those keys, nor that the live operation still works. The original capture report and stored `.BDD` are private and untracked; the coordinator checked the raw
report's digest and size on the machine that recorded it and preserved both flags locally, so a clone alone cannot recheck the original.
See [`test_bridge_report_fixture.py`](../../tests/test_bridge_report_fixture.py).

## Application readiness entry gate

The local `429597f` checkpoint adds the shared [readiness guard](../../src/udv_echo_process/acquire/ui/readiness.py)
to UI/bridge point entry, preflight and the sweep runner. An offered unusable reader is not absence; a callable returning
`None` is clear, but a declared non-callable `None` is refused. UI hold-time refusal skips recovery even if a later sample
would be clear. [Composed tests](../../tests/test_acquire_readiness.py) exercise these paths without a live application.
The reader blocks target-process `#32770` dialogs conservatively; it does not diagnose crashes or certify a dismissed
fault as repaired. Standalone channel/column commands and production-host integration are not established by this slice.
