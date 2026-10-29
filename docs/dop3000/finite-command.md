# Finite acquisition command and private-provider contract

`udv-acquire finite` promotes the **orchestration**, not the native bindings. It
loads an explicitly selected trusted Python provider and private configuration;
there is no implicit provider, UI fallback, bundled native address table or
cross-channel frequency-equality rule.

## Verification state

The predecessor private command completed a real 1+2 trial on October 29, 2026
([evidence](evidence/finite-one-command-20261029.json)); its proof was not inherited.
A separately supervised **packaged command** trial then completed configuration,
one Run, one Store, clean closure and restoration with maximized Explorer covering
UDOP. [Independent retained-evidence review](evidence/finite-packaged-covered-20261029.json)
accepted that bounded result: original BDD, 11 native phases/19 returned calls,
real hook removal/helper exit without kill, and a separate full baseline/final
comparison. No restoration is owed. Of 2,387 passive foreground samples, three
caught console windows and none caught UDOP: **not uninterrupted Explorer focus
or proof of unsampled instants**. This establishes only the measured 1+2 request
with its private provider; not arbitrary configurations, software abort, campaigns,
mixed-frequency operation or flow validity. The public parser/loader/coordinator
also retain offline tests using an explicitly fake backend and original BDD.

## Invocation

Supply the configuration for the intended machine and a new recording stem:

```bash
udv-acquire finite --provider private/provider.py --config private/config.json \
  --definition examples/finite-1-2.json --name a-new-recording \
  --store-dir outputs/live/store --expect-mode instrument --check
```

`--check` validates declaration, name/directory, provider exports, the provider's
static admission and unchanged input digests. It never calls the backend factory.
Python provider imports and `finite_preflight` are **trusted to be static**; this
is not a sandbox for arbitrary Python code.

`--execute` is the mutually exclusive effectful verb. It requires the applicable
operator/exit authorization, fresh target admission and a new name. Neither a
successful check nor an earlier recording grants another acquisition. JSON is
always printed; `--report FILE` additionally creates a new JSON record without
overwriting one. A post-effect report-write failure exits nonzero while retaining
the successful action facts on stdout. Exit 0 means ready (check) or successful
execution; exit 2 means refused, failed or evidence persistence failed.

The definition contains `channels` and optional `sequences` (currently exactly
one). Each channel/quantity request declares frequency in kHz, profiles, gates,
PRF period in microseconds and emissions. Distinct channel frequencies are legal
input; the selected provider still must establish that its device/build can
execute that particular request. The example is a measured initial case, not a
hardware restriction.

## Provider exports

- `finite_preflight(*, request: FiniteInvocation, config_path: Path) -> dict`:
  return `ready: true` only when all static dependencies and requested capability
  are present; resolve transitive native-script assets through their real owner.
- `finite_backend(*, request: FiniteInvocation, config_path: Path) -> FiniteBackend`:
  bind the **same** validated request/configuration. Construction must not attach
  or mutate the instrument. Native bindings, instance identity, retained code and
  transport stay in this private implementation.

The backend phase methods are specified by `acquire.finite_workflow.FiniteBackend`:
`prepare`, `configure`, `enable`, `observe`, `store`, `close`, `restore`, `verify`,
`residual`, `source_evidence`. Their measured, per-operation guards remain the
backend's responsibility; the public coordinator does not reimplement native
policy from guessed words.

`prepare` reads actual process mode/baseline and resolves every setup/restore
operation. Every effect rechecks target identity, pending state and applicable
control fields. `enable` issues one Run and returns the existing public
`FiniteRunRequest`/`FiniteRunReceipt`. `observe` uses `classify_finite_run` on fresh
observations with the invocation's bounded wait. It must never treat timeout as
an abort or issue Record/Stop/Clear/retry. `store` saves only that owned held block.

The coordinator independently decodes the requested file and checks its complete
channel/quantity set, profiles/gates, per-channel frequencies, PRF, emissions and
observed support. Its reported file digest comes from the decoder's retained input;
a differing post-decode read-back or provided Store digest refuses before restore.
This is consistency across observations, not a filesystem lock. It requires receipted Store-helper closure **before** restoring.
A supplied backend is closed and its source facts collected even if static file
admission refuses before `prepare`. `close` must be idempotent and retain
per-session actual cleanup/exit facts; an
empty session list cannot certify successful storage cleanup. `verify` must
provide every named restoration check in `VERIFICATION_KEYS`; missing checks
cannot pass by empty aggregation. The final close must be clean too.

Every post-configuration failure is terminal and carries fresh residual state or
an explicit failed residual read. Settings may remain owed, or stored data may
already exist. No speculative rollback, acquisition replay, automatic retry or
new attachment is supplied. Backend observations are trusted executable-provider
claims, not independent measurements supplied by the coordinator.
