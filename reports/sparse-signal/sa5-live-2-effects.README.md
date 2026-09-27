# SA5 within-sitting effect artifacts — `sparse-mixer-live-2`

One committed sitting's within-sitting effect profiles and their scalar reductions, published under the accepted v1 schema (`docs/dop3000/sa5-effect-artifact-schema-proposal.md`). This set is **one sitting**: it is not a comparison, holds no between-sitting number and reaches no Stage-2 product.

## Files and the digest chain

- `sa5-live-2-effects.npz` — the canonical `ZIP_STORED` container of NPY v1.0 members: the per-effect profile arrays and the per-participant reads (§3–§4). It is the profile array's one home.
- `sa5-live-2-effects.csv` — one row per effect (72 rows), the **sole** per-effect scalar record: the reductions, the coverage and the correlation (§6).
- `sa5-live-2-effects.json` — the identity, the closed schema, the provenance, the alignment and operand definitions, the non-value rows, the descriptive repeats and the digests (§5). It carries no ndarray and no per-effect scalar.
- `sa5-live-2-effects.README.md` — this file.

The chain is one-way: this README binds the document, the document binds the container and the table, and a file never carries its own digest.

- `sa5-live-2-effects.npz` sha256: `sha256:8403fd5a8df712658fc8583a37485671b12224d29ce1ad09e507e604884fb38e` (over its exact file bytes).
- `sa5-live-2-effects.csv` sha256: `sha256:a2e6de4e221859072dc54e614ad1a695998c9ed558f2c2f8031abba41c11db07` (over its canonical LF bytes, so a Windows checkout with CRLF materialised on disk hashes to the value git stores).
- `sa5-live-2-effects.json` sha256: `sha256:de686f668c8bd469c8a4c841d630ee6b83c83d2d6b17d221055fc792ed1d5905` (canonical LF bytes; this is the reader's entry point to the chain).
- every digest is lowercase hex with the `sha256:` prefix, computed from the bytes this run staged, at the analysis revision below — never from a tree regenerated beside the destination.

## The observation unit and the effect identity

One **effect** per `(sitting, view, metric, contrast-or-interaction)`: nine `(metric, view)` endpoints, each carrying the seven bound contrasts plus the derived pitch×burst interaction — 72 effects, the whole row set of the NPZ, the JSON and the CSV. The effect id is the ordered concatenation of the three frozen vocabulary values, joined by `__`:

```
effect_id = "<view>__<metric>__<contrast>"
```

A reader resolves an id through the JSON `effects` list and **must never parse the id** string; the id is a stable key, not a grammar.

## The NPZ members (closed per effect)

For every effect the member-name set is exactly the ten suffixes below, prefix-qualified by the effect id, and there is no other member. `K = knot_count` and `P = participant_count` are published per effect in the document, so the shapes are stated in two places and must agree.

| member | dtype | shape | meaning |
| --- | --- | --- | --- |
| `<effect_id>__defined.npy` | `|u1` | `(K,)` | the mask: `1` exactly where the effect state is `defined`, else `0` |
| `<effect_id>__effect.npy` | `<f8` | `(K,)` | the oriented effect value where defined, the finite placeholder `0.0` where not |
| `<effect_id>__knots_mm.npy` | `<f8` | `(K,)` | the effect's knot depths, strictly increasing |
| `<effect_id>__participant_defined.npy` | `|u1` | `(P,K)` | mask: `1` exactly where the read state is `defined`, else `0` |
| `<effect_id>__participant_depth_mm.npy` | `<f8` | `(P,K)` | each participant's native depth, `0.0` where that read is unaligned |
| `<effect_id>__participant_gate_index.npy` | `<i4` | `(P,K)` | each participant's native gate index, `-1` where that read is unaligned |
| `<effect_id>__participant_offset_mm.npy` | `<f8` | `(P,K)` | each participant's signed `depth - knot` offset, `0.0` where unaligned |
| `<effect_id>__participant_state.npy` | `|u1` | `(P,K)` | the participant read state code (table B) |
| `<effect_id>__participant_value.npy` | `<f8` | `(P,K)` | each participant's measured value, `0.0` where not defined |
| `<effect_id>__state.npy` | `|u1` | `(K,)` | the effect state code (table A) |

- **participant rows (`P`)** are the distinct recordings the effect's operands read, in the engine's contract order: the high operand's members in `Operand.members` order, then the low operand's members not already present. A corner two-sided contrast has `P = 2`, the interaction has `P = 4`, an emissions contrast has `P = 5`. The document's `participants` list publishes the same order, and the `(P,K)` shapes are checked against it.
- **the finite placeholder**: an undefined effect knot carries `0.0`, mask `0` and a non-zero state code; a `0.0` in a value array is a measurement only where its mask is `1`. An **unaligned** read is `gate_index = -1`, depth/offset/value `0.0`, mask `0` and state code `6`; an **aligned** read whose metric is undefined keeps its real gate index, depth and offset and carries only a `0.0` value with mask `0` and a code `1`–`5`.
- **strictly increasing knots**, exact little-endian dtypes and C-contiguous payloads; no member contains `NaN`, `Inf` or an object, so `allow_pickle=False` reading is exact.

## The physical-depth weighting rule

trapezoidal physical weighting over the *adjacent pairs of valid common knots whose both endpoints define the effect*: each such interval contributes its own depth gap and no interval is bridged across an undefined knot. With L the summed width of those valid intervals (the covered depth), the signed depth average is sum((E_i + E_i+1)/2 * gap)/L and the RMS magnitude is sqrt(sum((E_i^2 + E_i+1^2)/2 * gap)/L). On a uniform, fully defined grid this is the ordinary trapezoid rule with half-weight end knots, and the separately reported equal-knot mean is not this integral. When no adjacent pair is valid L is zero, so the signed average and the RMS are not reported while the equal-knot average and the knot-wise sign fractions and extrema stay descriptive. The weights describe physical depth, not gate count.

The unit of every value and reduction is the effect's own `units` cell (`dimensionless`, `mm/s`, `s`); displacements are `mm/s`, lags `s` and `band_fraction` `dimensionless` (a Φ difference is a dimensionless difference, never a relative percentage gain).

## The alignment rule

WP3 nearest-native alignment: the knots are the coarsest participating grid's own native supported gate depths inside the common support, and every other operand is read at its nearest NATIVE gate to each knot - no interpolation, no resampling, no fit. The native depth used and its signed offset are published per knot, and a knot whose nearest gate lies farther than half the knot pitch away carries no read rather than an interpolated one.

## The CSV columns (closed, one row per effect)

The table is keyed `effect_id` and has one row per effect in the fixed order, with the columns below in order. An undefined scalar is the **empty field**, never `0`; every finite float is rendered with `format(value, ".17g")`, the round-trip decimal for binary64.

- **`sitting`** — the pass name this row set belongs to.
- **`effect_id`** — `<view>__<metric>__<contrast>`, the stable key into the JSON `effects` list.
- **`view`** — `primary-comparison` or `full-record`.
- **`metric`** — the observable (`mean`, `std`, `mad_scaled`, `recurrence-1e-lag`, `recurrence-peak-lag`, `band_fraction`).
- **`contrast`** — the bound contrast name, or `pitch_x_burst_interaction`.
- **`units`** — the effect's unit (`mm/s`, `s` or `dimensionless`).
- **`grid`** — `corner_knots` or `emissions_knots` — the knot grid the effect was aligned on.
- **`knot_count`** — `K`, the number of knots.
- **`defined_count`** — the knot count whose effect is defined.
- **`undefined_count`** — `K` less the defined count.
- **`undefined_alignment_count`** — the knots with effect state code `2` (undefined-alignment).
- **`undefined_operand_count`** — the knots with effect state code `1` (undefined-operand).
- **`covered_depth_mm`** (unit `mm`) — `L`, the summed depth of adjacent knot pairs whose both endpoints define the effect.
- **`coverage_fraction`** — `L / (last knot - first knot)`; empty for a one-knot profile.
- **`support_low_mm`** (unit `mm`) — the low edge of the effect's participating common support (not the coverage denominator).
- **`support_high_mm`** (unit `mm`) — the high edge of that common support.
- **`half_pitch_mm`** (unit `mm`) — half the mean knot pitch, the alignment tolerance.
- **`max_abs_offset_mm`** (unit `mm`) — the alignment scalar: the largest absolute native offset used (the engine's `DepthEffects` row, not the summary).
- **`signed_depth_average`** — the trapezoidal signed depth average over the valid intervals; empty where `L = 0`.
- **`equal_knot_average`** — the equal-weight mean over defined knots (not the integral).
- **`rms_magnitude`** — the trapezoidal RMS magnitude over the valid intervals; empty where `L = 0`.
- **`positive_fraction`** — the fraction of defined non-zero knots with a positive effect.
- **`negative_fraction`** — the fraction of defined non-zero knots with a negative effect.
- **`zero_fraction`** — the fraction of defined non-zero knots with a zero effect.
- **`min_value`** — the smallest defined effect.
- **`min_depth_mm`** (unit `mm`) — the depth the minimum was reached at.
- **`max_value`** — the largest defined effect.
- **`max_depth_mm`** (unit `mm`) — the depth the maximum was reached at.
- **`max_abs_value`** — the largest absolute effect (ties resolved to the shallower depth).
- **`max_abs_depth_mm`** (unit `mm`) — the depth the largest absolute effect was reached at.
- **`correlation`** — the Pearson correlation of the compared pair of profiles; empty on a shape refusal.
- **`correlation_defined_count`** — the number of common defined knots the correlation used.

## Acquisitions and anchors, in order

The eleven bound operands, in acquisition order. No block-local anchor is an operand.

| order | label | job | relative path | source sha256 |
| --- | --- | --- | --- | --- |
| 2 | `cc1` | `burst-4` | `sparse3-burst-4-cc1-20260924T171726.BDD` | `a7a749df1b92f2a8e8be8572fcc93b587c8c17070d943df6ab0bb71399f2c812` |
| 4 | `cc3` | `burst-4` | `sparse3-burst-4-cc3-20260924T171726.BDD` | `1ff3cea0de38ef7988f3296ff8e551dcf3e4b3ef856c012fe70ec75f66c66930` |
| 6 | `cr1` | `common-reference-1` | `sparse3-common-reference-1-cr1-20260924T172037.BDD` | `96f578e9272de41154cae14b3e60be281211e1b588c9bf56f5c7ac2f3e173a58` |
| 8 | `cc2` | `burst-18` | `sparse3-burst-18-cc2-20260924T172136.BDD` | `2dd3321821c0c3510d620c685b5b383375450e8582623088d632ebe21b737d21` |
| 10 | `cc4` | `burst-18` | `sparse3-burst-18-cc4-20260924T172136.BDD` | `4a8b84ee651dcd5952602321032b7e9dd3d052d786fd8c50cbdb060ac15b5d90` |
| 12 | `cr2` | `common-reference-2` | `sparse3-common-reference-2-cr2-20260924T172424.BDD` | `974605480a54543605205402e4a66f06a85bc0d026d91844e552e3a6b849864f` |
| 14 | `e8` | `emissions-8` | `sparse3-emissions-8-e8-20260924T172909.BDD` | `884394065835034e34932fde00b7e20282ad5d02ffbf5d017dd06aae4d5e9ef3` |
| 17 | `cr3` | `common-reference-3` | `sparse3-common-reference-3-cr3-20260924T173145.BDD` | `8f9afb1c4a0fea3b1d19bba2bebbc72c7c35516e0daf1a1d5e039c2ed1319ca5` |
| 19 | `e64` | `emissions-64` | `sparse3-emissions-64-e64-20260924T173312.BDD` | `051d6c1bcaa08475605781e2ad065044ad74d6f53d1deecfb1a87332a8d8a75d` |
| 22 | `cr4` | `common-reference-4` | `sparse3-common-reference-4-cr4-20260924T173503.BDD` | `cc6b1e6c1fd4d7d3eb43c73de7f4d428f72945c31c8523d05db0ce037eb53367` |
| 24 | `e128` | `emissions-128` | `sparse3-emissions-128-e128-20260924T173603.BDD` | `8e3e17a7699fd2ac21a2a43071be375bfbd02b1550c26ac139c6365a71e950b6` |

Block-local anchor controls present, **context only** and bound to no operand: `ctrl-begin`, `ctrl-end`, `ctrl-mid`.

## The two views

This set carries the two named views `full-record` and `primary-comparison`, never mixed in one profile. The **primary comparison** is the sitting's declared window (12 s, 100 revolutions), cut from each recording's own stored stamps; the **full record** keeps every stored profile of the recording, so it is the longer view. Both are read on the recording's own native gate grid: the longer view has the finer frequency resolution `1/T` at the same effective sample rate and Nyquist `1/(2·dt)`, and a fluctuation scale (`mean`, `std`, `mad_scaled`) is declared on the primary comparison only. The exact duration, gate pitch and sample rate of each view are the recordings' own decoded axes, published per gate by the recordings' own reports; this set publishes no axis number it did not measure.

## Non-value rows

`nonvalue_rows` records every effect-knot, operand-knot, participant read or profile-correlation position whose scalar value is missing, one row per such position, with `kind` in `effect-knot`, `operand-knot`, `read`, `shape`. It is the missing-value set, not the refusal set: a position appears because no value is carried, and its `state` is the distinct reason. A refusal or an unsupported measurement is never a `0.0`, and a **defined measured zero** is a value, never a non-value row. `nonvalue_counts` states the totals by `(state, kind)`.

- `shape` at `primary-comparison__mean__pitch_x_burst_interaction`: `undefined-shape` — the derived pitch x burst interaction has no pair of compared profiles: it is a difference of differences of four corner profiles, so no two-profile correlation is defined for it
- `shape` at `primary-comparison__std__pitch_x_burst_interaction`: `undefined-shape` — the derived pitch x burst interaction has no pair of compared profiles: it is a difference of differences of four corner profiles, so no two-profile correlation is defined for it
- `shape` at `primary-comparison__mad_scaled__pitch_x_burst_interaction`: `undefined-shape` — the derived pitch x burst interaction has no pair of compared profiles: it is a difference of differences of four corner profiles, so no two-profile correlation is defined for it

## Code vocabulary

The two `uint8` code spaces are closed. A code outside its table is a refused artifact.

Table A — effect state (`<effect_id>__state.npy`):

| code | text |
| --- | --- |
| 0 | `defined` |
| 1 | `undefined-operand` |
| 2 | `undefined-alignment` |

Table B — participant read state (`<effect_id>__participant_state.npy`), the metric states plus the read-level unaligned sentinel:

| code | text |
| --- | --- |
| 0 | `defined` |
| 1 | `defined-zero-power` |
| 2 | `refused-axis` |
| 3 | `undefined-constant-trace` |
| 4 | `undefined-not-supported` |
| 5 | `undefined-no-estimate` |
| 6 | `undefined-alignment` |

## Repeat groups — descriptive only

`repeats` describes same-whole-condition repeat groups as scalars: member labels, orders, jobs, values, defined counts, states and reasons, and the group's spread. No spread is a floor, no member is a replicate, and there is no per-depth repeat array.

## Provenance and digests

- sitting: `sparse-mixer-live-2`.
- plan: `sparse-mixer-live-2`.
- plan fingerprint: `f9de5b803921b62e788572ef5209a779d05638f1f7da4933384a743c02b6b7ef`.
- analysis revision: `6a983c4`.
- generator revision: `6a983c4`.
- window: 12 s, 100 revolutions.
- common support: 10.138 .. 98.938000000000017 mm.
Publication is staged: every file is written beside its destination under a unique, fsynced temporary name and moved onto its final name with one `os.replace` at a time. The four-file set is **not** a transaction, so a failure after some renames can leave a mixed set — one a reader detects by recomputing the digests above. An existing SA5 stem is never overwritten to guess ownership: a full byte-identical set is left untouched, and any missing or differing file makes the run refuse rather than replace a file it did not produce.

## Reproduce

```bash
python -m udv_echo_process.analysis.sparse_sa5_report --sitting sparse-mixer-live-2
```

## What this artifact does not claim

- No cross-sitting number exists here: this run reads exactly one sitting, and `E_live2 - E_live1` and every other between-sitting comparison is a separate, later, reviewed artifact.
- No Stage-2 product: the Stage-2 E20/E64 campaign is contextual, is not a third sitting, and is not reached by this writer.
- No p-value, no floor, no optimum and no causality verdict: nothing here screens, ranks or decides.
- A descriptive recurrence-peak lag is not a period claim, and a descriptive repeat range is not a floor and not a replicate.
- `correlation` describes the shape of a compared pair of profiles only; it is not a test.
- No effect profile is reduced to a scalar row while its array is omitted: the NPZ is the profile array's one home, the CSV the per-effect scalar's, the JSON the identity's.
- No ndarray is placed in the JSON (issue #49 remains open and unsolved), and there are no per-depth repeat arrays.

## The gate

- `operands_bound_to_decoded_sources` — ok
- `inventory_digest_matches_every_operand` — ok
- `achieved_settings_match_every_operand` — ok
- `corners_share_their_own_grids` — ok
- `emissions_operands_share_the_reference_pitch_and_grid` — ok
- `every_endpoint_has_one_effect_per_knot` — ok
- `e20_is_the_equal_weight_mean_of_the_four_runs` — ok
- `no_block_local_anchor_enters_an_operand` — ok
- `repeats_name_their_members_and_orders` — ok
- `window_is_the_declared_primary` — ok
- `no_cross_sitting_arithmetic` — ok
- `npz_members_are_the_closed_set` — ok
- `every_undefined_position_carries_placeholder_mask_and_state` — ok
- `participant_rows_are_the_declared_order` — ok
- `digests_match_the_staged_bytes` — ok
