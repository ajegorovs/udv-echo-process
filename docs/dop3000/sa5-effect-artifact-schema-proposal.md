# SA5 within-sitting evidence storage — review gate

> **Status: proposed, not accepted.** The typed backend is separate from the committed artifact boundary. No effect profile has been committed to `reports/` under this proposal. Review this schema **before** publishing array-bearing within-sitting evidence. Issue #49 (generic ndarray JSON serialization) remains open and is not solved here.

## Intended products and ownership

Publish two independent products, one per sitting, under `reports/sparse-signal/sa5-live-{1,2}-effects.*`. The generator accepts exactly one `PassRef` with `is_reproducibility_sitting=true`; it must never accept a second sitting in the same invocation or calculate a difference between sittings. Use source digests and plan fingerprints from the decoded and validated operands. Each product carries its own row counts and checks. Stage-2 is absent.

The suggested artifact boundary is:

- **JSON manifest** (strict finite JSON, `allow_nan=False`): sitting identity, source digests, analysis revision, prespec revision, exact binding table, endpoint/view/unit/settings, participant depth extents, support/alignment rule, data-file digests, observed refusal counts, descriptive repeat groups and definitions. Null is an undefined scalar, always paired with a typed state and reason. No per-knot numeric effect series or ndarray is placed in this manifest.
- **NPZ profile arrays**: explicitly named arrays for each `(sitting, contrast, metric, view)` row: common physical knots, effect values and defined mask; one array per participant for native gate index/depth and signed offset. Undefined effect positions use a finite placeholder **only alongside a false mask**; the reader never treats that placeholder as a measured zero. Use a documented dtype and deterministic member order. A canonical byte-reproduction rule must account for the NPZ container's ZIP timestamps, compression and metadata, not merely compare decompressed arrays.
- **CSV scalar summaries** (one row per contrast × metric × view, eight contrasts including the derived interaction): signed physical-depth average, weighted RMS, sign fractions, valid/undefined knot count, largest absolute signed effect/depth, profile correlation state/reason, and `descriptive / not resolvable with this design` where no metric-specific criterion exists. Its keys map to the NPZ arrays and the JSON's source/estimator definitions; it is not a second per-gate serialization.
- **README**: units, definitions, physical-depth weighting, acquisitions/anchors in order, separate view rows, refusal examples and regeneration command. Bind its table/manifest claims to the published files by digests. Do not interpret a descriptive repeat range as a floor or rank conditions.

No `model_dump(mode="json")` on an ndarray-bearing model, no `tolist()` workaround, and no disguised per-depth scalar CSV to evade the array decision. Do not modify the SA2.4 CSV/JSON or frozen WP reports. Stage files under a scratch destination first; verify all checks before publication and refuse overwriting an unrelated file. Tests must regenerate to an isolated destination and byte-compare the committed artifacts without rewriting them.

## Decisions required before the evidence commit

1. Accept NPZ as the explicit profile-array format and its deterministic byte rule (or choose a different explicit array format).
2. Fix the exact closed JSON/CSV fields, NPZ keys/dtypes/mask placeholder and cross-file digest convention; publish one authoritative representation of each value.
3. Decide whether every descriptive repeat group's **per-depth** spread belongs in the NPZ or only in a separate later product; do not drop the member identities/orders/reasons.
4. Require an independent verifier to decode the committed sources and recompute the profile effects, summaries and E20 equal-weight operand, not only check the writer's own files against each other.

Only after this gate should a generator publish `sa5-live-1` and `sa5-live-2` products. The following reviewed slice may compare them; this one must not compute `E_live2 − E_live1` or any recurrence verdict.
