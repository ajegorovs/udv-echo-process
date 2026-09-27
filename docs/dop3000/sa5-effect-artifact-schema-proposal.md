# SA5 within-sitting effect artifacts — accepted v1 schema

> **Status: accepted v1 artifact contract; no effect artifacts published in PR #60.**
> The NPZ + JSON + scalar CSV split was approved at review of PR #60 (`97c2aae`, branch
> `feat/analysis-sa5-within-sitting`), subject to the two documentation corrections
> recorded in that review and applied in this contract. The typed backend
> (`analysis/sparse_sa5_effects.py`, `analysis/sparse_sa5_bindings.py`,
> `analysis/sparse_sa5_metrics.py`) is unchanged by this document; this document fixes the
> **committed artifact boundary** it publishes into, so a generator can be written against a
> reviewed contract in a separate publication PR without silently changing its format.
>
> Scope of this document: the schema, the byte rule, the digest convention, the non-value
> vocabulary and the verifier design. It commits **no array, no generator and no code**,
> and it does not publish any effect value. The four decisions in the earlier
> proposal are resolved in §10. Issue **#49** (generic ndarray JSON serialization) remains open
> and **unsolved**: no ndarray is ever placed in the JSON here; arrays live only in the
> canonical NPY-in-ZIP container of §3–§4. SA5 v1 publishes **no cross-sitting arithmetic**
> and **no Stage-2** product here.

## 1. Products, ownership and naming

Two independent products, **one per sitting**, under the plan's publish root
`reports/sparse-signal/`:

| file | content |
| --- | --- |
| `sa5-live-1-effects.npz` | the sitting's per-knot effect profiles and per-participant reads (§3, §4) |
| `sa5-live-1-effects.json` | identity, closed schema, provenance, alignment and operand definitions, non-value rows, descriptive repeats, digests (§5) |
| `sa5-live-1-effects.csv` | the sitting's one per-effect scalar row set: reductions, coverage, correlation (§6) |
| `sa5-live-1-effects.README.md` | units, definitions, digest binding, regeneration command, no-go list (§7) |

`sitting` is the pass's own name (`sparse-mixer-live-1`, `sparse-mixer-live-2`); the file
stem is `sa5-live-1-effects` / `sa5-live-2-effects`. A generator accepts **exactly one
`PassRef`** with `is_reproducibility_sitting=true` and never a second sitting in one
invocation. Stage-2 (`stage2-e20-e64/`) is contextual, is not a third sitting, and is not
reached by this generator or this schema. The frozen WP and SA2.4 reports under `reports/`
are byte-untouched by any run of this generator.

## 2. The observation unit and the effect identity

The schema's cardinality is the observation unit the prespec and the engine already fix:
one **effect** per `(sitting, view, metric, contrast-or-interaction)`. The engine's `ENDPOINTS`
(`analysis.sparse_sa5_effects.ENDPOINTS`) is nine `(metric, view)` endpoints; each endpoint carries
the seven bound contrasts (`analysis.sparse_sa5_bindings.CONTRASTS`) plus the derived
`pitch_x_burst_interaction`. That is **72 effects per sitting** and it is the whole row set
of the NPZ, the JSON and the CSV.

`SparseView` values are `primary-comparison` and `full-record` (`analysis._sparse_view.SparseView`);
`MetricName` values are `mean`, `std`, `mad_scaled`, `recurrence-1e-lag`,
`recurrence-peak-lag`, `band_fraction` (`analysis.sparse_sa5_metrics.MetricName`); the contrast names
are the bound `ContrastSpec.name`s — `pitch_at_burst_4`, `pitch_at_burst_18`,
`burst_at_fine_pitch`, `burst_at_coarse_pitch`, `E8_minus_E20`, `E64_minus_E20`,
`E128_minus_E20` — plus `pitch_x_burst_interaction`
(`analysis.sparse_sa5_effects.INTERACTION_NAME`).

**The deterministic effect ID** is the ordered concatenation of those three frozen
vocabulary values, joined by a double underscore:

```
effect_id = "<view>__<metric>__<contrast>"
```

e.g. `primary-comparison__mad_scaled__burst_at_coarse_pitch`,
`full-record__band_fraction__pitch_x_burst_interaction`. None of the three vocabularies
contains `__`, so the ID round-trips; uniqueness over the 72 IDs is asserted, never assumed.

**Effect order is fixed and is the endpoint order then the contrast order**:
endpoints in `ENDPOINTS` order, and within an endpoint the seven bound contrasts in
`CONTRASTS` order followed by the interaction. JSON `effects` and CSV rows use that
effect order; the NPZ members and JSON `npz_members` use lexicographically sorted
**member-name** order as required by §4. A reader resolves an `effect_id` through the JSON
`effects` list and **must never parse the ID string**; the ID is a stable key, not a grammar.

## 3. NPZ — closed per-effect keys, dtypes, placeholders, masks, state codes

`sa5-live-N-effects.npz` is a ZIP of NumPy `.npy` members. For every one of the 72 effects
the member-name set is **closed** and is exactly the ten suffixes below, prefix-qualified by
the effect ID:

| member name | dtype | shape | meaning |
| --- | --- | --- | --- |
| `<effect_id>__knots_mm.npy` | `<f8` | `(K,)` | the effect's knot depths, strictly increasing, `K = knot_count` |
| `<effect_id>__effect.npy` | `<f8` | `(K,)` | the oriented effect `value` where defined, the finite placeholder `0.0` where not |
| `<effect_id>__defined.npy` | `<u1` | `(K,)` | the mask: `1` exactly where the effect is `EffectState.DEFINED`, else `0` |
| `<effect_id>__state.npy` | `<u1` | `(K,)` | the effect's `EffectState` code (§8, table A) |
| `<effect_id>__participant_gate_index.npy` | `<i4` | `(P,K)` | each participant's native `GateMetric.gate_index`, `-1` where that read is unaligned |
| `<effect_id>__participant_depth_mm.npy` | `<f8` | `(P,K)` | each participant's native depth, `0.0` where that read is unaligned |
| `<effect_id>__participant_offset_mm.npy` | `<f8` | `(P,K)` | each participant's signed `depth − knot` offset, `0.0` where that read is unaligned |
| `<effect_id>__participant_value.npy` | `<f8` | `(P,K)` | each participant's measured value, `0.0` where not defined |
| `<effect_id>__participant_defined.npy` | `<u1` | `(P,K)` | mask: `1` exactly where the participant read is `MetricState.DEFINED`, else `0` |
| `<effect_id>__participant_state.npy` | `<u1` | `(P,K)` | the participant read's `MetricState` code (§8, table B) |

`K = knot_count` and `P = participant_count` are published per effect in the JSON (§5), so
the shapes are stated in two places and must agree. There is **no other member**: no
metadata member, no `__meta__`, no scalar member (every scalar is in the JSON or the CSV), no
per-depth repeat array, no per-operand or per-curve array.

### 3.1 Participant rows — fixed order

`P` participants are the distinct recordings the effect's operands read, in the engine's own
contract order: the high operand's members in `Operand.members` order, then the low
operand's members not already present. For a one-recording operand that is one row; for
`E20_OPERAND` (`kind = "mean-of-four"`, members `cr1..cr4`) it is four rows. So a corner
two-sided contrast has `P = 2`, the interaction has `P = 4` (`cc1, cc2, cc3, cc4`, matching
the coefficients `(1, -1, -1, 1)`), and each emissions contrast has `P = 5`
(`e8`/`e64`/`e128`, then `cr1..cr4`). Row `p` of every `(P,K)` array is that participant, and
the JSON `participants` list publishes the same order with each row's `label`, `job`,
`order` and `kind`. **The row order is a fixed part of the schema**: it is declared in the
JSON and the `(P,K)` member shapes are checked against it, never inferred from the members'
names.

### 3.2 The finite placeholder, the mask and the sentinel

Every undefined position carries a **finite placeholder, a `0` mask and a non-zero state
code** — never a non-finite number, never a silent zero:

- `effect[i] == 0.0` and `defined[i] == 0` and `state[i] != 0` exactly where the effect is
  not defined; `defined[i] == 1` and `state[i] == 0` exactly where it is. The placeholder is
  a placeholder because the mask says so: a reader must never treat `effect[i] == 0.0` as a
  measured zero without reading `defined[i]`.
- An *unaligned* read has `participant_gate_index[p,i] == -1`, depth, offset and
  value placeholders `0.0`, mask `0` and state code `6`. An aligned read whose
  metric is undefined **retains its actual nonnegative native gate index, depth
  and offset**; only its value is placeholder `0.0`, its mask is `0`, and its
  state is the backend's code `1`–`5`. An aligned defined read has mask `1`, code
  `0` and a finite measured value, including a measured zero where applicable.
- Every placeholder is **finite** (`0.0` or `-1`), so no member ever contains `NaN`, `Inf`
  or an object, and `allow_pickle=False` reading is exact.

**Resolved ambiguity — impossible alignment entries.** The engine's `EffectState.UNDEFINED_ALIGNMENT`
and the `ReadAligned` unaligned case (`analysis.sparse_sa5_effects._align`: no native gate lay
within half the knot pitch, so no interpolation is performed) are the cases where a reader
could otherwise mistake "no measurement" for `0.0`. Their resolution is the **sentinel**:
`participant_state` code `6` at the read level, and the effect `state` code `2`
(`undefined-alignment`) — together with the `-1` gate index and the `0` masks above. The
sentinel is part of the closed code vocabulary of §8; it is not an out-of-band flag, and a
`0.0` in any value array is only ever a measurement when its mask is `1`.

### 3.3 No per-depth repeat arrays

The descriptive same-whole-condition repeats (`RepeatGroup` / `RepeatMember`,
`analysis.sparse_sa5_effects.RepeatMember` / `.RepeatGroup`) are **not** in the NPZ and carry **no per-depth array**. A
repeat group's members keep their `label`, `order`, `job`, scalar `value`, `defined_count`,
`state` and `reason`, and its `spread`/`min`/`max` are descriptive scalars — these are
published in the JSON (§5.6), not as arrays. Per-member per-knot values are deliberately not
serialized: they would duplicate the effect profiles' own participant rows at a different
reduction, and the proposal's "do not drop the member identities/orders/reasons" is satisfied
by the JSON scalars. If a per-depth repeat product is ever wanted it is a separately reviewed
schema, not a silent addition here.

## 4. The canonical NPZ byte rule

A committed NPZ is a **canonical, byte-reproducible** artifact: two runs of the generator at
one analysis revision over one committed dataset must produce byte-identical files. The rule
is:

1. **Container.** One ZIP written with `zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=False)`.
   Every member is **stored, never compressed** (`ZIP_STORED`), so the bytes are the `.npy`
   payloads verbatim and not deflate output.
2. **Fixed timestamps and attributes.** Every member is written through an explicit `zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))` — the ZIP epoch — with `compress_type=ZIP_STORED`, `external_attr=(0o600 << 16)`, `internal_attr=0`, `create_system=0`, `extra=b""` and `comment=b""`. Python's `ZipFile` replaces a zero `external_attr` with `0o600 << 16` during writing; specifying the nonzero value avoids that implicit default. No archive comment and no directory entries.
3. **Sorted members.** Members are written in **ascending lexicographic order of the member name** (the sorted `effect_id`-prefixed names of §3), so the ZIP's central directory order is fixed by the schema and not by dictionary iteration.
4. **Fixed member format.** Each payload is a `.npy` written by `numpy.lib.format.write_array(buf, array, version=(1, 0), allow_pickle=False)`. The array is **C-contiguous** (`order="C"`) and of the member's exact **fixed little-endian** dtype (`<f8`, `<u1`, `<i4`) — the byte order is written into the dtype, so a big-endian host still produces the same bytes. Only those three dtypes occur; no object, string, structured or complex array.
5. **No pickling, no extras.** `allow_pickle=False` is enforced on every read, and the payload is a plain numeric array. The container carries **no extra member, no comment and no metadata** beyond the ten closed suffixes per effect. A member whose name is not in the closed set, a duplicate member, a payload whose declared dtype/shape is not the §3 one, or any non-finite value is a **refused artifact**, not a warning.
6. **The digest is the actual SHA-256 of these bytes** (§5.7), computed from the file this run staged for publication, never from a copy regenerated beside it.

The `.npy` header is deterministic for a fixed dtype, shape and format version (NumPy pads
the header to its fixed alignment with spaces), so step 4 adds no variability. These six
points are exactly what a byte-reproduction test compares; comparing decompressed arrays
would not catch a compression, timestamp or ordering drift, which is why the rule is stated
at the byte level.

## 5. JSON — closed fields, provenance, non-value rows, digest convention

`sa5-live-N-effects.json` is **strict JSON**: UTF-8, `ensure_ascii=True`, `sort_keys=True`,
`separators=(",", ":")` and **`allow_nan=False`** (a non-finite value fails the run before
any byte is written), LF endings and exactly one trailing newline. Its field set is
**closed**: a new field is a schema change, not a new value. It carries no ndarray
(issue #49) and **no per-effect summary number** — those are the CSV's sole copy (§6).
Every **scientific reduction and numerical payload has exactly one authoritative home**: the
NPZ holds the profile arrays, the CSV the per-effect scalar reductions, the JSON the
identity, provenance, definitions, non-value rows, repeats and digests. Only **structural
identity, shape and join metadata** (`effect_id`, `view`, `metric`, `contrast`, `grid`,
`knot_count`, `participant_count`, `npz_members` and the participant order) may mirror
between the JSON, the NPZ and the CSV, and only where the mirrored values agree **exactly**.
Mirrored shape counts and support coordinates are structural checks, not a second
authoritative scientific reduction.

### 5.1 Identity and gate

`schema` (`"sa5-within-sitting-effects/v1"`), `ok` (bool), `checks` (object, the engine's own
check names with their verdicts — `operands_bound_to_decoded_sources`,
`inventory_digest_matches_every_operand`, `achieved_settings_match_every_operand`,
`corners_share_their_own_grids`, `emissions_operands_share_the_reference_pitch_and_grid`,
`every_endpoint_has_one_effect_per_knot`, `e20_is_the_equal_weight_mean_of_the_four_runs`,
`no_block_local_anchor_enters_an_operand`, `repeats_name_their_members_and_orders`,
`window_is_the_declared_primary`, `no_cross_sitting_arithmetic`), and `artifact_checks` — the
schema-level names `npz_members_are_the_closed_set`,
`every_undefined_position_carries_placeholder_mask_and_state`,
`participant_rows_are_the_declared_order`, `digests_match_the_staged_bytes`.

### 5.2 Provenance

`analysis_commit`, `generator_revision`, `generator_command` (following SA2.4's writer
shape), `sitting` (the pass name, `PassRef.name`), `plan`, `plan_fingerprint` (bare 64-hex
lowercase `RunPlan.plan_fingerprint`), `window_s` (`12.0`), `window_revolutions` (`100`),
`support_mm` (`[low, high]`), `method` and `contrast_source` (the engine's own rule texts).
`provenance` is the eleven bound operand rows (`sparse_sa5_bindings.OperandRow`): `label`,
`job`, `order`, `identity`, `relative_path`, `source_sha256` (bare 64-hex lowercase), `plan`,
`plan_fingerprint`, `burst_length`, `emissions_per_profile`, `prf_us`, `resolution_mm`,
`gates`, `first_gate_mm`, `last_gate_mm`, `supported_gates`, `window_s`. `control_labels`
carries the block-local anchors as **context only**; no anchor is an operand.

### 5.3 The effect list — structure, not numbers

`effects` is the 72 records in the fixed §2 order, each with: `effect_id`, `view`, `metric`,
`contrast` (the name), `expression`, `reduction`, `units`, `grid` (`corner_knots` or
`emissions_knots`), `knot_count` (`K`), `participant_count` (`P`), `operand_names`,
`operands` (each `{name, kind, members: [...]}`), `coefficients`, `participants` (§3.1 order,
each `{label, job, order, kind}`), `support_mm`, `half_pitch_mm`,
`alignment_rule` and `state_meanings` (§8, so a code is never ambiguous). The `grid`,
`knot_count` and `participant_count` here are the shape contract the NPZ is checked against.

### 5.4 Member list — the closed key set, published

`npz_members` is the **sorted list of every member name** in `sa5-live-N-effects.npz`. It is
the reader's check on §3: the member set must equal this list exactly (no extra, no missing,
no duplicate), and every name is `<effect_id>__<suffix>.npy` for a suffix in the closed ten.

### 5.5 Non-value rows — missing effect/operand/read/shape values, with distinct states

`nonvalue_rows` records each effect-knot, operand-knot, participant read or
profile-correlation position **whose scalar value is missing**, one row per such
position, each `{effect_id, kind, knot_index, depth_mm, side, member, state, reason}`.
It is the *missing-value* set for those four position types, not the refusal set and not
the acquisition-failure set: a position appears here because no value is carried, and its
`state` is the distinct reason the value is missing. Null physical-depth integrals when
covered depth is zero are instead determined by the CSV's coverage fields (§6), not by a
fabricated per-knot refusal. For a profile-level `shape` position, `knot_index` and
`depth_mm` are null.
`kind` is one of `effect-knot`, `operand-knot`, `read`, `shape`; `side` and `member` are null
where the position is the effect's own; `state` for a per-knot entry names its
backend effect or metric state (§8), e.g. `undefined-alignment`,
`undefined-operand`, `undefined-constant-trace`, `undefined-not-supported`,
`refused-axis`, `defined-zero-power`. A `shape` row alone uses the JSON-only
`undefined-shape` label for `ProfileShape.correlation is None`; it has no NPZ
state code. `reason` is the engine's own reason text, copied,
never rewritten. `nonvalue_counts` states the totals by `(state, kind)`.

**`defined-zero-power` is a valid admitted `0/0`, not a refusal and not a failed
acquisition.** The spectral axis was admitted and its total power is exactly zero (a constant
gate), so the fraction is undefined and *no value is carried*: the measurement was taken and
the state records that its number does not exist. It appears in `nonvalue_rows` only because
its scalar is missing; it is never a declined axis and never a failed capture. The states stay
distinct — `defined-zero-power` (a measurement whose value does not exist) and the
`refused-axis` / `undefined-*` refusals share this row set only in carrying no scalar. A
refused or unsupported measurement is never a `0.0`, and a defined measured zero is a value,
never a non-value row.

### 5.6 Descriptive repeats — scalars only

`repeats` is the repeat group set (§3.3), one row per `(sitting × observable × view ×
condition)`: `condition`, `metric`, `view`, `units`, `knot_count`, `defined_members`,
`min_value`, `max_value`, `spread`, `rule` and `statement`, with `members` carrying each
member's `label`, `order`, `job`, `value`, `defined_count`, `state` and `reason`. It is
**descriptive only**: no range is a floor, no member is a replicate, and there is no
per-depth array here.

### 5.7 Digests — the precise convention

One convention, applied identically to every published file:

- `artifacts.npz.sha256` is `"sha256:" + SHA-256(canonical)` where the **NPZ is hashed over
  its exact file bytes** (the container is already canonical by §4, so no normalization is
  applied or permitted).
- `artifacts.csv.sha256` is `"sha256:" + SHA-256(canonical)` where the **CSV is hashed over
  its canonical LF bytes** (`analysis._floor_documents.table_digest`:
  `read_bytes().replace(b"\r\n", b"\n")`), so a Windows checkout that materialised CRLF
  hashes to the value git stores.
- Both are recorded in the JSON, each with the sibling `file` name, so the JSON binds both
  files. The **JSON**'s own digest is recorded in the README (§7); a file never carries its
  own digest.
- Every digest is lowercase hex with the `sha256:` prefix. A **source** digest is the bare
  64-hex lowercase `source_sha256` of an operand row and is never re-prefixed; a
  `plan_fingerprint` is likewise bare. `nonvalue_counts` and the repeat numbers are not
  digests.
- Digests are computed from the bytes **this run staged**, at the analysis commit the JSON
  records, never from a tree regenerated beside the destination.

## 6. CSV — the one per-effect scalar row set

`sa5-live-N-effects.csv` has **one row per effect** (72 rows), in the fixed §2 order, keyed
`effect_id`. It is the **sole** per-effect scalar record: the JSON does not repeat it, and
it is not a per-gate serialization (no row follows a knot). Columns, closed and in order:

`sitting, effect_id, view, metric, contrast, units, grid, knot_count, defined_count,
undefined_count, undefined_alignment_count, undefined_operand_count, covered_depth_mm,
coverage_fraction, support_low_mm, support_high_mm, half_pitch_mm, max_abs_offset_mm, signed_depth_average,
equal_knot_average, rms_magnitude, positive_fraction, negative_fraction, zero_fraction,
min_value, min_depth_mm, max_value, max_depth_mm, max_abs_value, max_abs_depth_mm,
correlation, correlation_defined_count`

These are the engine's `DepthSummary` and `ProfileShape` scalars
(`analysis.sparse_sa5_effects.DepthSummary` / `.ProfileShape`) with their **coverage**: `knot_count`, `defined_count`,
`undefined_count`, the split `undefined_alignment_count` / `undefined_operand_count`,
`covered_depth_mm = L`, the sum of adjacent knot intervals with *both* effect
values defined, and `coverage_fraction = L / (last knot − first knot)` where the
profile spans a positive depth; a one-knot profile has an empty fraction, not zero.
An interior undefined knot never bridges the two neighbouring intervals. Where
`L = 0`, `signed_depth_average` and `rms_magnitude` are empty even if an isolated
knot is defined; the equal-knot average and extrema remain descriptive. The
`support_low_mm` / `support_high_mm` columns name common support, not the
denominator of the coverage fraction. `undefined_alignment_count` and
`undefined_operand_count` come from the NPZ `state` codes (§8 table A).
The `weighting_rule` and the per-effect
`statement` are definitions and are in the JSON; the CSV carries the number, the JSON carries
the rule.

Conventions: an undefined scalar is the **empty field**, never `0`; every finite
float is rendered with Python's `format(value, ".17g")` (round-trip decimal for
binary64), with no display rounding or significant-digit choice left to the
generator. CSV uses UTF-8, RFC 4180 quoting as needed and `\n` row terminators.
An empty `correlation` is a typed shape refusal; its exact reason is the JSON's
`nonvalue_rows` row with `kind = "shape"` (constant profiles can refuse even with
`correlation_defined_count >= MIN_SHAPE_KNOTS`, which is `3`). `max_abs_offset_mm` is the
alignment scalar of the engine's `DepthEffects` row (not of `DepthSummary`/`ProfileShape`) and
is a per-effect number, so it lives **only** here in the CSV and is deliberately absent from
the JSON's effect record (§5.3).

## 7. README — definitions and binding

`sa5-live-N-effects.README.md` states the units and definitions of every column and member,
the physical-depth trapezoidal weighting rule, the acquisitions and anchors in order, the
separate view rows, the two views' differing duration/resolution/Nyquist, the non-value row
examples, the regeneration command, and the no-go list. It binds its own claims to the
published files by digests — including `artifacts.json.sha256`, the JSON's canonical-LF
digest, which is the reader's entry point to the chain
(README → JSON → NPZ + CSV). It does **not** interpret a descriptive repeat range as a floor
or rank conditions, and it does not publish a cross-sitting number.

## 8. Code vocabulary — matching the backend states

The two `uint8` code spaces are closed: effect codes map to the backend enum
`sparse_sa5_effects.EffectState`; participant codes map to
`sparse_sa5_metrics.MetricState` **plus a read-level unaligned sentinel**. A code
outside the corresponding table is a refused artifact. The vocabulary is the backend's own: `MetricState`'s two
refusal labels are literally `BandFractionState`'s and `RecurrenceVerdict`'s values
(`analysis.sparse_sa5_metrics.MetricState` and its `STATE_MEANING`), so no row can invent a state the estimator never produced.

**Table A — effect state (`<effect_id>__state.npy`, `EffectState`):**

| code | text | meaning |
| --- | --- | --- |
| 0 | `defined` | the effect is measured; `defined` mask is `1`, the value is finite |
| 1 | `undefined-operand` | an operand's metric was undefined or refused at the knot (constant trace, unsupported decay, declined axis, undefined E20 member) |
| 2 | `undefined-alignment` | a required gate fell farther than half the knot pitch from its knot, so no measurement exists there (the sentinel) |

**Table B — participant read state (`<effect_id>__participant_state.npy`, `MetricState` plus
the read-level sentinel):**

| code | text | meaning |
| --- | --- | --- |
| 0 | `defined` | measured; the read carries a finite value |
| 1 | `defined-zero-power` | the axis was admitted and its total power is exactly zero (a constant gate); a measurement whose fraction is `0/0` and carried as no value |
| 2 | `refused-axis` | the admission declined the axis; nothing was measured |
| 3 | `undefined-constant-trace` | the trace is constant; its normalized autocorrelation does not exist |
| 4 | `undefined-not-supported` | the estimator ran and the quantity is undefined on this trace's support (a 1/e decay the lag range never reached, or no admissible peak) |
| 5 | `undefined-no-estimate` | the backend carried no usable scalar for this gate |
| 6 | `undefined-alignment` | read-level sentinel: no native gate lay within half the knot pitch, so the `ReadAligned` carries no gate index, depth, offset or value (`state = None`) |

Codes `3`–`255` in table A and `7`–`255` in table B are invalid and refused. The NPZ carries codes; the JSON
`state_meanings` (§5.3) carries the text, so `nonvalue_rows` can quote a name and the NPZ a code
without either drifting from the backend.

## 9. Publication and refusal gate

- Stage every file beside its destination under a unique, fsynced temporary name and move it
  onto its final name with one `os.replace` at a time. The set is **not** a transaction; a
  digest mismatch is what a reader detects, not a rollback. Refuse to overwrite an existing
  file this writer did not produce, and refuse a stage file or lock an interrupted run left
  behind.
- Generate the two sittings as **two independent invocations**, one `PassRef` each. Refuse a
  second sitting in one invocation and refuse any computation of `E_live2 − E_live1`, a
  recurrence verdict or a cross-sitting summary — that comparison is a separate, later,
  reviewed artifact.
- No `model_dump(mode="json")` on an ndarray-bearing model, no `tolist()` or base64 workaround,
  and no disguised per-depth scalar CSV to evade the array decision. No effect profile is
  reduced to a scalar row while its array is omitted; the NPZ is the array's one home.
- The byte-reproduction test writes to a scratch destination and byte-compares; it never
  rewrites a committed artifact and never touches the frozen WP or SA2.4 reports.

## 10. Resolved decisions (the proposal's open questions)

1. **NPZ is accepted** as the explicit profile-array format, with the deterministic byte rule
   of §4 (ZIP_STORED, sorted members, fixed ZIP epoch, fixed little-endian dtypes,
   `allow_pickle=False`, no extras, actual SHA-256 in the JSON).
2. **The field set is closed, and every scientific reduction and numerical payload has one
   authoritative home**: the NPZ carries the arrays, the CSV the sole per-effect scalar
   reductions — including `max_abs_offset_mm`, which is therefore dropped from the JSON's
   §5.3 effect records — and the JSON the identity, provenance, definitions, non-value rows,
   repeats and digests. Structural identity, shape and join metadata (`effect_id`, `view`,
   `metric`, `contrast`, `grid`, `knot_count`, `participant_count`, `npz_members`, the
   participant order) may be mirrored between the files, but only with exact agreement. The
   digest convention is fixed in §5.7.
3. **Per-depth repeat spreads are not published here.** Repeats stay scalar in the JSON
   (§5.6); the member identities, orders and reasons are kept; a per-depth repeat product, if
   ever wanted, is a separately reviewed schema.
4. **An independent verifier is required** (§11), decoding the committed sources and
   recomputing the effects and summaries, not only re-reading the writer's files.

**Out of scope, unchanged:** issue #49; the cross-sitting agreement artifact; Stage-2
E20/E64 as a third sitting; SA3/POD, SA6 UI and CFD alignment; any p-value, floor, optimum or
causality verdict; any generator code or committed array in this PR.

## 11. The independent verifier

The verifier is a separate program that **does not read the writer's staged values as its
input**. It decodes the committed sources and recomputes, then compares:

1. **Re-derive the binding** from the sitting's own committed `points.csv`
   (`reports/sparse-mixer-live-{1,2}/points.csv` via `bind_sitting`) and the decoded
   recordings (`decode_pass`); re-check every operand's `source_sha256`, job, acquisition
   order and achieved settings against the decoded file — an inventory row is not evidence
   until it is reconciled with the file it names.
2. **Recompute the metrics and the effects** through the frozen slices
   (`read_metric_profile` → `measure_binding`) rather than trusting the NPZ or the CSV, and
   recompute the **E20 equal-weight mean** from the four decoded `cr1..cr4` operands, not
   from the writer's own sum.
3. **Compare element-wise**: every NPZ array (knots, effect, mask, state and the six
   `(P,K)` participant arrays) against the recomputed profiles; every CSV scalar against the
   recomputed `DepthSummary`/`ProfileShape`; the JSON structure, provenance and non-value
   rows against the recomputed binding and states. An `effect-knot` non-value row
   requires a false effect mask and matching effect state; an `operand-knot` row
   requires a false effect mask and the recomputed *operand* state (which can differ
   from the effect state when another operand has an alignment refusal). A `read`
   row requires a false participant mask and matching participant state. A `shape`
   row has no NPZ mask: it requires an empty CSV `correlation` and the recomputed
   shape reason.
4. **Check the invariants the writer could get wrong silently**: `state[i] != 0` exactly
   where `defined[i] == 0`; every placeholder is finite and every mask is consistent; the
   `-1`/`0.0` sentinel appears exactly at unaligned reads; every participant row order equals
   the JSON `participants`; `knot_count`/`participant_count` match the array shapes;
   `npz_members` equals the closed set exactly; no anchor label is an operand; no
   cross-sitting number exists.
5. **Check the digests last**: recompute the NPZ's file-byte SHA-256 and the CSV's
   canonical-LF SHA-256 and compare with the JSON, then the JSON's canonical-LF SHA-256 with
   the README. A digest check is a *last* check, not the whole verification: a matching
   digest over wrong numbers is still wrong, so steps 1–4 must pass on their own.
