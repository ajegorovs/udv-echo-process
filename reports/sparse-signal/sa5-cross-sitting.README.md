# SA5 cross-sitting agreement artifacts — one comparison, `live2 - live1`

The between-sitting agreement artifact: one comparison, `live2 - live1` (`live-2` minus `live-1`), published under the cross-sitting schema (`docs/dop3000/sa5-cross-sitting-artifact-schema-proposal.md`), the analogue of the accepted v1 within-sitting contract. It holds **one** oriented comparison over 72 endpoints; it is never a per-sitting file and never a third sitting.

## Files and the digest chain

- `sa5-cross-sitting.npz` — the canonical `ZIP_STORED` container of NPY v1.0 members: for every **comparable** comparison, the five per-knot arrays of §3. It is the per-knot comparison array's one home.
- `sa5-cross-sitting.csv` — one row per comparison (72 rows), the **sole** comparison scalar record: every §5 reduction, the coverage and the peak columns (§6).
- `sa5-cross-sitting.json` — identity, the closed schema, the two sides' provenance digests, the typed states and reasons, the frozen context quotations, the non-value rows and the digests (§5). It carries no ndarray and no comparison reduction.
- `sa5-cross-sitting.README.md` — this file.

The chain is one-way: this README binds the document, the document binds the container and the table, and a file never carries its own digest.

- `sa5-cross-sitting.npz` sha256: `sha256:75eb2d147b939d36f9f70275571c2245baaaa94fd3e1901a50da8f0eb37da99d` (over its exact file bytes).
- `sa5-cross-sitting.csv` sha256: `sha256:256a63706970c3bbe76435cee6ca0dae68c1085f4a7ff8728e9f67356e9c2cd1` (over its canonical LF bytes, so a Windows checkout with CRLF materialised on disk hashes to the value git stores).
- `sa5-cross-sitting.json` sha256: `sha256:f74d5d645c6f1880bbd6f403fafb83fa828f1bf553b91a85e50b4991eb847f01` (canonical LF bytes; this is the reader's entry point to the chain).
- every digest is lowercase hex with the `sha256:` prefix, computed from the bytes this run staged, at the analysis revision below — never from a tree regenerated beside the destination.

## The two source quartets and their digest chains

The two sides are the two fixed reproducibility sittings, read **by name** through the input layer from the committed source quartets under `reports/sparse-signal/`, independent of any scratch output directory. Each side's chain is `README -> JSON (canonical LF) -> NPZ (exact bytes) + CSV (canonical LF)`, recomputed by this run from the published bytes and never re-derived.

- `live-1` (`sparse-mixer-live-1`, stem `sa5-live-1-effects`, plan `sparse-mixer-live-1`, plan fingerprint `655298032dab02efe516e2e9d0294fc28330243f4aeb5f1e733fc5a50fd5ce86`):
  - JSON sha256: `sha256:a866ad75854ecbbba3e19b34dc9f706cf2c7920f7e8a1fc732c161862c0af1c5`
  - NPZ sha256: `sha256:af6ca0bea9693954640ce9b724bca93095495e6c111c3fddd9e2eff9ffeeac35`
  - CSV sha256: `sha256:9dfeaca668a0e5bb235815cde864af601e674a9258d1b53278986ba572614853`
  - own checks hold: `true`, own artifact checks hold: `true`
- `live-2` (`sparse-mixer-live-2`, stem `sa5-live-2-effects`, plan `sparse-mixer-live-2`, plan fingerprint `f9de5b803921b62e788572ef5209a779d05638f1f7da4933384a743c02b6b7ef`):
  - JSON sha256: `sha256:4f4aa18bd4669fc3447bec6284bc41a161694f5956603010e36472788e21d993`
  - NPZ sha256: `sha256:8403fd5a8df712658fc8583a37485671b12224d29ce1ad09e507e604884fb38e`
  - CSV sha256: `sha256:a2e6de4e221859072dc54e614ad1a695998c9ed558f2c2f8031abba41c11db07`
  - own checks hold: `true`, own artifact checks hold: `true`

## The comparison unit and the effect identity

One comparison per `(view, metric, contrast-or-interaction)`: nine `(metric, view)` endpoints, each carrying the seven bound contrasts plus the derived pitch×burst interaction — 72 comparisons, the whole row set of the NPZ, the JSON and the CSV. `grid` is a function of the contrast, asserted and never chosen. The comparison key is the ordered triple; the effect id is their `__` join:

```
effect_id = "<view>__<metric>__<contrast>"
```

A reader resolves an id through the JSON `comparisons` list and **must never parse the id** string; the id is a stable key, not a grammar.

## The NPZ members (closed per comparable comparison)

For every **comparable** comparison the member-name set is exactly the five suffixes below, prefix-qualified by the effect id, and there is no other member. A **not comparable** comparison contributes **no** member. `Kc` is published as `comparison_knot_count` in the document, so the shape is stated in two places and must agree.

| member | dtype | shape | meaning |
| --- | --- | --- | --- |
| `<effect_id>__defined.npy` | `<u1` | `(Kc,)` | the common-defined mask: `1` exactly where both sides' state code is `0`, else `0` |
| `<effect_id>__difference.npy` | `<f8` | `(Kc,)` | the oriented difference `D = E2 - E1` where defined, the finite placeholder `0.0` where not |
| `<effect_id>__knots_mm.npy` | `<f8` | `(Kc,)` | the comparison knot depths, strictly increasing |
| `<effect_id>__state1.npy` | `<u1` | `(Kc,)` | the live-1 effect state code (table A) |
| `<effect_id>__state2.npy` | `<u1` | `(Kc,)` | the live-2 effect state code (table A) |

- **the finite placeholder**: an undefined comparison position carries `0.0`, mask `0` and a non-zero state code; the mask is `1` exactly where both sides' state code is `0`. The stored `difference` is the IEEE-754 binary64 result of `E2 - E1` exactly as the backend computes it: a `-0.0` is written as `-0.0` (never normalized), occupies a **defined** position, and counts in `zero_count` — it is never negative.
- **strictly increasing knots**, exact little-endian dtypes and C-contiguous payloads; no member contains `NaN`, `Inf` or an object, so `allow_pickle=False` reading is exact.

## The physical-depth weighting rule

trapezoidal physical weighting over the *adjacent pairs of valid common knots whose both endpoints define the effect*: each such interval contributes its own depth gap and no interval is bridged across an undefined knot. With L the summed width of those valid intervals (the covered depth), the signed depth average is sum((E_i + E_i+1)/2 * gap)/L and the RMS magnitude is sqrt(sum((E_i^2 + E_i+1^2)/2 * gap)/L). On a uniform, fully defined grid this is the ordinary trapezoid rule with half-weight end knots, and the separately reported equal-knot mean is not this integral. When no adjacent pair is valid L is zero, so the signed average and the RMS are not reported while the equal-knot average and the knot-wise sign fractions and extrema stay descriptive. The weights describe physical depth, not gate count.

The unit of every difference and reduction is the effect's own `units` cell (`mm/s`, `s` or `dimensionless`); a `band_fraction` difference is dimensionless, never a relative percentage. Weights describe physical depth, not gate count; a signed average can cancel a spatially changing difference, so it is never the sole magnitude summary.

## The method

per sitting: bind the committed per-pass inventory to the decoded recordings (source digest, job, acquisition order, achieved settings all re-checked), read one scalar per (recording, view, metric, supported native gate) from the frozen SA1/SA2.4 slices, align each operand to the coarsest participating grid's native supported gate depths by nearest native gate (no interpolation), reduce E20 to the exactly equal-weight mean of its four common-reference runs (refusing the operand at a knot where any member is undefined), and form effect = M(high) - M(low) per knot. One sitting only: no cross-sitting arithmetic, no published table, no floor.

## The two views

The set carries the two named views `primary-comparison` and `full-record`, never mixed in one comparison. The **primary comparison** is each sitting's declared window, cut from each recording's own stored stamps; the **full record** keeps every stored profile of the recording, so it is the longer view. Both are read on the recording's own native gate grid: the longer view has the finer frequency resolution `1/T` at the same effective sample rate and Nyquist `1/(2·dt)`, and a fluctuation scale is declared on the primary comparison only. The exact duration, gate pitch and sample rate of each view are the frozen quartets' own decoded axes, published per gate by the recordings' own reports; this set publishes no axis number it did not measure.

## The CSV columns (closed, one row per comparison)

The table is keyed `effect_id` and has one row per comparison in the fixed order (endpoint, then contrast, then interaction), with the 30 columns below in order. An undefined scalar is the **empty field**, never `0`; every finite float is rendered with `format(value, ".17g")`, the round-trip decimal for binary64. A non-comparable row keeps its structural identity cells where they are known (including its state and reason, read from the JSON) and leaves every reduction and boolean cell empty.

- **`effect_id`** — `<view>__<metric>__<contrast>`, the stable key into the JSON `comparisons` list.
- **`view`** — `primary-comparison` or `full-record`.
- **`metric`** — the observable (`mean`, `std`, `mad_scaled`, `recurrence-1e-lag`, `recurrence-peak-lag`, `band_fraction`).
- **`contrast`** — the bound contrast name, or `pitch_x_burst_interaction`.
- **`units`** — the effect's unit (`mm/s`, `s` or `dimensionless`).
- **`grid`** — `corner_knots` or `emissions_knots` — the knot grid both sides were aligned on.
- **`knot_count`** — the mirrored source `K` (structural identity, equal on both sides).
- **`comparison_knot_count`** — `Kc`, the number of native knots inside both supports' intersection — the `(Kc,)` NPZ member shape.
- **`defined_count`** — `|D|`, the knots where both sides are defined.
- **`sign_count`** — `|S|`, the common-defined knots where both effects carry a defined non-zero sign.
- **`span_mm`** — the comparison span (last knot − first knot, `0.0` when `Kc == 1`).
- **`covered_depth_mm`** — `L`, the depth of adjacent comparison-knot pairs whose both endpoints are defined.
- **`coverage_fraction`** — `L / span`; empty when `span == 0`.
- **`signed_depth_average`** — `D̄`, the trapezoidal signed depth average over the valid intervals; empty where `L = 0`.
- **`rms_difference`** — `RMS(D)`, the trapezoidal RMS difference over the valid intervals; empty where `L = 0`.
- **`positive_count`** — the defined differences with a positive sign (sums with the next two to `defined_count`).
- **`negative_count`** — the defined differences with a negative sign.
- **`zero_count`** — the defined differences that are numerically zero (a `−0.0` counts here, never as negative).
- **`sign_agreement`** — `A_sign`, the fraction of `|S|` with matching signs; empty where `|S| = 0`.
- **`zero1_count`** — the live-1 defined-zero knots over the comparison domain.
- **`zero2_count`** — the live-2 defined-zero knots over the comparison domain.
- **`shape_correlation`** — the Pearson correlation of the two profiles over `|D|`; empty on a shape refusal (its reason is the JSON `shape` non-value row).
- **`peak1_value`** — the live-1 numerical maximum `M*_1`, defined whenever `|D| ≥ 1`.
- **`peak1_depth`** — the shallower depth the live-1 maximum was reached at.
- **`peak2_value`** — the live-2 numerical maximum `M*_2`, defined whenever `|D| ≥ 1`.
- **`peak2_depth`** — the shallower depth the live-2 maximum was reached at.
- **`peak_localized1`** — whether live-1's numerical maximum is a localized peak.
- **`peak_localized2`** — whether live-2's numerical maximum is a localized peak.
- **`peak_displacement`** — `z*_2 − z*_1` (positive = deeper in live-2); empty unless both sides are localized.
- **`peaks_coincide`** — whether the two localized peaks coincide within tolerance; empty unless both sides are localized.

## The typed states

`comparison_state` is `comparable` or `not comparable`; `not resolvable with this design` requires a separately reviewed rule, none is registered, and such a row is refused. `label_state` is a **different axis**: `deferred-pending-review` for a comparable pair and absent otherwise, never a verdict and never a `comparison_state`. The per-knot `state1`/`state2` codes use table A:

| code | text |
| --- | --- |
| 0 | `defined` |
| 1 | `undefined-operand` |
| 2 | `undefined-alignment` |

A non-value row (`nonvalue_rows`) records a scalar whose value is missing because the comparison could not carry it — `undefined-shape`, an un-localized `peak`, or `peak-displacement`; a scalar whose emptiness is derivable from a CSV count is left to the CSV. A `not comparable` pair contributes no non-value row.

## The repeat context and its conditional range

Each side's frozen magnitude/coverage context is quoted from its own CSV row and published **beside** the comparison, never as this artifact's reduction. A repeat context attaches to an operand only when the operand's whole achieved condition is provable from the published metadata; a non-selected context (`repeat-context-unavailable` or `repeat-context-identity-unverifiable`) publishes **no** numerical range: its `min_value`/`max_value`/`spread` keys are omitted entirely — not `null`, not `0` — so a range can never be read against an operand whose condition is not proved equal to the group's. A repeat context is context only and is excluded from every comparison decision.

## The gate: structural `ok` vs the ancillary repeat-identity check

`ok` is the **structural** verdict: true exactly when every `artifact_checks` entry is true **and** every `checks` entry is true **except** `repeat_context_identity_fully_established`. That ancillary check is **false** whenever any operand's repeat context is `repeat-context-identity-unverifiable`; it is published as `false` and it does **not** make `ok` false. A pair whose repeat context is unavailable or unverifiable is still `comparable`, with identical `comparison_state`, `label_state` and diagnostics to the same pair with a selected context.

- `no_output_artifact_written` — ok
- `fixed_orientation_live2_minus_live1` — ok
- `seventy_two_comparisons` — ok
- `every_effect_id_resolves_in_both_sittings` — ok
- `comparison_and_label_states_kept_separate` — ok
- `no_label_but_deferred_pending_review_is_written` — ok
- `no_recurrence_verdict` — ok
- `repeat_context_identity_fully_established` — FAILED
- `repeat_context_state_isolated_from_comparison_and_label` — ok
- `npz_members_are_the_closed_set` — ok
- `every_comparison_position_carries_its_mask_and_state` — ok
- `comparison_rows_are_the_frozen_order` — ok
- `no_comparison_scalar_lives_outside_the_csv` — ok
- `source_quartets_are_byte_unchanged` — ok
- `digests_match_the_staged_bytes` — ok

## Provenance and digests

- comparison: `live2 - live1`.
- analysis revision: `c29d74d`.
- generator revision: `c29d74d`.
Publication is staged: every file is written beside its destination under a unique, fsynced temporary name and moved onto its final name with one `os.replace` at a time. The four-file set is **not** a transaction, so a failure after some renames can leave a mixed set — one a reader detects by recomputing the digests above. An existing file is never overwritten to guess ownership: a full byte-identical set is left untouched, and any missing or differing file makes the run refuse rather than replace a file it did not produce.

## Reproduce

Run from a checkout of the recorded generator revision. Set `SA5_SCRATCH` to an absolute directory **outside the checkout**; do not regenerate into this committed report root. `--report-dir` redirects the **outputs** only: the two sides are always read from the committed source quartets, so a scratch directory never redirects the reads. A later checkout has a different default revision and must not overwrite an existing artifact set.

```bash
python -m udv_echo_process.analysis.sparse_sa5_cross_report --report-dir reports/sparse-signal --report-dir "$SA5_SCRATCH" --analysis-commit c29d74d --generator-revision c29d74d
```

## What this artifact does not claim

- No agreement value, verdict, ranking or label is computed: this artifact publishes the comparison's numbers and states without a recurrence verdict, so `label_state` is `deferred-pending-review` for every comparable pair and absent otherwise.
- No `p`-value, floor, optimum or causality/population claim: this is two realizations compared descriptively, never inference.
- No Stage-2 pooling and no third sitting: Stage-2 is contextual, is not a sitting, and is never bound.
- A repeat-context range is descriptive only, is not a floor and not a replicate, and is `not-like-for-like` with any effect magnitude.
- No per-knot value in the JSON or the CSV, and no comparison scalar in the JSON: the NPZ is the per-knot array's one home and the CSV the comparison scalar's, while the JSON holds identity, provenance, states, context quotations and digests.
- No ndarray in the JSON (issue #49 remains open and unsolved), and no coarser-lattice or nearest-native knot mapping.
- The two oriented effect profiles `E1`/`E2` are not re-published here: their single home is each side's own `sa5-live-N-effects.npz` under its own digest chain.
