# B5 supervised job-boundary commissioning (2026-09-25)

**Scope:** first four jobs of a separate nine-job `run-plan --next` pass. The rig was safe and the sensor connected; this was a control-path acceptance, not a claim about mixer signal quality. The operator confirmed the app's Store directory and fixed settings before the run, correcting emissions/profile from 128 to 20 and uniform TGC from 23 to about 20 dB. No burst value was changed by hand during the pass. The running code was PR #38 head `53d9066`.

| Step | Job | Verified dialog burst transition | Observed effective Sampling volume (mm) | BDDs, all `ok` | Stored word 8 |
|---|---|---|---:|---:|---:|
| 1 | `burst-4` | 10 → 4 | 1.776 | 5 | 4 |
| 2 | `common-reference-1` | 4 → 10 | 1.850 | 1 | 10 |
| 3 | `burst-18` | 10 → 18 | 3.330 | 5 | 18 |
| 4 | `common-reference-2` | 18 → 10 | 1.850 | 1 | 10 |

Each job's accumulated `burst_transitions` contained **one verified entry**, copied to its pass row; the compiled identity read the requested burst after that write and before recording. Every point log marked the stored-point verdict `ok`, with sound speed, PRF, burst and emissions/profile enforced. The 12 committed BDDs have the requested word-8 values, 600 µs PRF, 20 emissions/profile and 1480 m/s sound speed. Decoded fixed configuration is unchanged apart from burst. Scientific points deliberately use two different gate geometries; the control/reference points retain 50 gates at 1.85 mm resolution. Raw word 27 is `1` in every file: receiver-bandwidth-definition provenance, **not** an effective-mm index.

The `plan/` directory is the **actual portable plan and job definitions used**, copied from the live scratch location without machine-local paths. Its fingerprint is `032676289d6a62b33be7ba8d6d84909224ea30fc4f8c8b354869d3f9f45c805f`. `manifest.json` is a **derived, path-sanitized evidence summary**, not the unmodified runtime manifest: it carries the four structured transition objects, per-job compile identity, original runtime-manifest/log SHA-256 values, and each BDD's SHA-256, requested values, decoded config, and point label. The unmodified runtime manifests and logs remain in the local `outputs/live/store/` and contain absolute machine paths, so they are not committed. The original hashes cannot be independently checked from this repository alone; the BDD hashes and the extracted fields can.

Reproduce without instrument access:

```bash
uv run --no-sync python data/burst-commissioning-b5/verify.py
uv run --no-sync udv-acquire run-plan --plan data/burst-commissioning-b5/plan/run-plan.json --check
```

**What that first command does and does not prove.** It **re-derives**, from the committed
files alone: the plan fingerprint, the four executed jobs' definition fingerprints, each job's
point labels and full requested parameter set, and every recording's SHA-256, stored operation
words and decoded configuration — so the BDDs, the summary and the committed plan are tied
together cryptographically. It **cannot** re-derive the dialog transition objects or the
compilation identities: their inputs are the runtime manifests and logs, which stay local
because they carry absolute machine paths. For those it checks the derived summary against the
expectations written into `verify.py` itself. The tie is load-bearing — perturbing a
definition fingerprint, a recording hash, or a burst condition in the plan each makes it fail
(verified by mutation on a scratch copy).

**Stop point:** 4/9 jobs and 12/26 recordings completed by design. Step 5 (`emissions-8`) was **not run**: it requests a manual change to emissions/profile and is not part of this burst-only acceptance. The app was left on its ready measurement screen at burst 10 after step 4. The four live boundaries all changed burst; an equal-burst/no-write job was **not exercised live**, although it is covered by offline fake tests. The supervisor did not report another unexpected dialog-field change; the committed BDDs independently rule out changes to their decoded fixed settings, not changes to every unreadable UI field. The B4 second-hidden-dependent-effect stop rule remains in force.

**The review that followed accepted this evidence boundary.** The equal-burst/no-write path is offline-verified only and does not justify another instrument session — the unexercised branch performs *less* device interaction, not an unknown gesture, and the device-dependent work around it was exercised four times. The failed-post-write/pre-record provenance gap stays an open follow-up in its own right, deliberately **not** folded into B6. PR #38 leaves Draft on this evidence.
