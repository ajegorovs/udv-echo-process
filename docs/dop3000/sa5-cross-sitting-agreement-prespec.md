# SA5 — cross-sitting descriptive agreement (prespecification)

> **Status: design only; docs-only; no cross-sitting number, verdict or label is computed here.**
> This prespecification is frozen **before** any cross-sitting arithmetic is run over the two
> published within-sitting quartets. It reuses the validated SA5 vocabulary and conventions
> unchanged and adds only the *between-sitting* comparison: orientation, support, matching,
> definedness, reductions, non-value handling and typed labels. It commits **no schema, no
> generator and no code**, and it reuses no observed value. Its artifact contract is a separate,
> later, separately reviewed slice (§9). It complements, and does not amend,
> [`sa5-sitting-effects-prespec.md`](sa5-sitting-effects-prespec.md) (the within-sitting prespec)
> and [`sa5-effect-artifact-schema-proposal.md`](sa5-effect-artifact-schema-proposal.md) (the
> accepted v1 artifact contract, cited below as *the v1 contract*).
>
> **Amendment A1 — repeat context (§6, §11).** A repeat group attaches to an operand **only when
> the operand's whole achieved condition is provable from published metadata**; otherwise the
> context is a typed-empty state and **no numerical range is published**. This narrows the §6
> repeat-context mapping (the earlier draft attached the `e8`/`e64`/`e128` block-local anchor groups
> and published their ranges); it changes no comparison quantity and no `comparison_state` /
> `label_state`. Docs-only; no artifact, schema, generator or value is committed here.

## 1. Frozen input quartet and digest binding

The inputs are **two published quartets**, one per sitting, under the plan's publish root
`reports/sparse-signal/` (v1 contract §1):

| sitting | quartet |
| --- | --- |
| live-1 | `sa5-live-1-effects.{npz,json,csv,README.md}` |
| live-2 | `sa5-live-2-effects.{npz,json,csv,README.md}` |

Each quartet is bound as **one frozen unit**: the JSON reads are bound by the v1 digest chain
(README → JSON canonical-LF SHA-256 → `artifacts.npz.sha256` / `artifacts.csv.sha256`; v1 contract
§5.7 and §7). The agreement run records for each sitting, verbatim and as published, the JSON
canonical-LF digest and the two `artifacts` entries; it verifies the digests against published bytes and re-derives no
within-sitting value (v1 contract §11). A quartet whose three digests do not each match the
sitting's own README/JSON chain is **refused**, not repaired. Stage-2 (`stage2-e20-e64/`) is
context, is not a third sitting, and is never bound as an input quartet (within-sitting prespec
§"Frozen inputs and comparability"; v1 contract §1).

**The comparison is `live2 − live1` only**, by name, never by acquisition date or path. Both sides
share the identical vocabulary (v1 contract §2), so no translation is needed — which is why the pass
name is bound **per side** and is never inferred.

## 2. Comparison unit and strict match

The comparison unit is one **effect**, keyed exactly as the v1 contract keys it: the ordered
triple `(view, metric, contrast-or-interaction)`, cardinality **72 per sitting** (v1 contract §2).
The `effect_id` is the joined string `"<view>__<metric>__<contrast>"`; a reader **resolves each
`effect_id` through its own sitting's JSON `effects` list and never parses the ID string** (v1
contract §2). Cross-sitting pairs are matched by **exact equality of all three vocabulary values
*and* of the resolved `effect_id`** — a triple match that the string disagrees with, or a
resolution failure on either side, is `not comparable`. The pair's `metric`, `view`, `contrast`,
`grid`, `units`, `knot_count` and `participant_count` must agree exactly (structural identity, v1
contract §5.3); any disagreement is a refusal, not a renamed pairing.

`grid` is a **function of the contrast**, asserted rather than chosen: corner contrasts and the
interaction are `corner_knots`; the three `E*_minus_E20` contrasts are `emissions_knots` (v1
contract §2, §5.3). No pair mixes the two views or the two grids.

## 3. Comparison support and knots

**Support** is the intersection of the two sides' own `support_mm` (v1 contract §5.3/§6), which is
itself the intersection of the participating operands' depth extents (within-sitting prespec
§"Oriented within-sitting contrasts"). A comparison knot must lie inside both sides' supports.

**Knots are matched on native depths, with no interpolation.** The grid is frozen and structural:
both `cc3`/`cc4` corner knots at pitch `2.96` mm (`COARSE_PITCH_MM`) and the emissions knots at the
reference pitch `1.85` mm (`REFERENCE_PITCH_MM`), read as `knot_count`/`grid` metadata from the
published JSON, not as effect values. Rule:

1. **Identical native knots are compared directly.** Two knots are the *same* comparison knot iff
   their physical depths agree within `GATE_TOLERANCE_MM = 1e-6` mm
   (`analysis.sparse_sa5_effects.GATE_TOLERANCE_MM`). No nearest-gate substitution, resampling,
   interpolation or extrapolation occurs anywhere (within-sitting prespec §"Frozen inputs and
   comparability").
2. **Frozen-case expectation.** Both sittings publish the same grid construction, so the comparison
   set is expected to be each side's full `knot_count` — an *assertion checked at run time*: the two
   knot arrays must be equal within the tolerance of (1).
3. **Mismatched grids — fail closed, mapping deferred.** If the two knot sets are not equal under
   (1), the pair is **`not comparable`** with reason `grid-mismatch-pending-review`. This prespec
   deliberately applies **no** coarser-lattice mapping: `2.96` and `1.85` mm are not nested lattices,
   so an exact shared-knot map is not guaranteed. A nearest-native or coarser-grid
   mapping could be defined, but its offsets and admissibility rule need separate review;
   until then the pair refuses without silently resampling either side.
   A knot-set mismatch is in practice a **publication defect** (one generator writes both sittings),
   so it is signalled loudly, never silently narrowed.

## 4. Masks and nonvalues

Each side carries per-knot `defined` (`1` exactly where `EffectState.DEFINED`, else `0`) and
`state` (`0` defined, `1` `undefined-operand`, `2` `undefined-alignment`; v1 contract §3, §8 table
A). The comparison preserves these:

- A comparison knot `z_k` is **defined** iff **both** sides have `defined == 1`/`state == 0` there:
  `D = { k : defined2[k] = 1 and defined1[k] = 1 }`.
- Where either side is undefined, the comparison at `z_k` is **undefined**, and the pair's own two
  states `(state2[k], state1[k])` are published alongside it so a reader sees *which* side refused
  and *why* (`undefined-operand` vs `undefined-alignment` stay distinct on each side; v1 contract
  §8). An `undefined-alignment` side is the engine's sentinel for "no native gate lay within half
  the knot pitch" and is never a `0.0` measurement.
- The v1 contract §3.2 placeholder/mask/state discipline is inherited: `value == 0.0` with
  `defined == 0` is a placeholder, a measured zero (`defined == 1`) is a value, and **a missing side
  is never bridged and never read as `0.0`.**

## 5. Comparison quantities — equations and definedness

For a matched pair, with `E1(z)` and `E2(z)` the two oriented within-sitting effects (units from
the v1 CSV's `units` column; within-sitting prespec §"Oriented within-sitting contrasts"):

**Difference profile.** `D(z_k) = E2(z_k) − E1(z_k)`, computed at each `k ∈ D`. Units are the
effect's own: mm/s for `mean`/`std`/`mad_scaled`, seconds for the recurrence lags, a **dimensionless
difference** for `band_fraction` (never a relative percentage; within-sitting prespec §46). `D` is
undefined wherever either side is.

**Signed physical-depth average and RMS (no bridging).** Over the adjacent pairs of comparison knots
*both of whose endpoints lie in `D`* — reusing the within-sitting trapezoidal `WEIGHTING_RULE`
(`analysis.sparse_sa5_effects.WEIGHTING_RULE`; v1 contract §6) — let
`L = Σ gaps` be the covered depth of that valid interval set. Then

```
D̄        = Σ_k [ (D(z_k) + D(z_{k+1}))/2 · gap_k ] / L      (signed depth-average difference)
RMS(D)   = sqrt( Σ_k [ (D(z_k)² + D(z_{k+1})²)/2 · gap_k ] / L )
```

each **defined iff `L > 0`**; if `L = 0`, both are **empty**, never `0`. An interior undefined knot
never bridges its two neighbouring intervals; `L`, the covered depth, and its fraction of the
comparison span are published beside them. Weights describe physical depth, not gate count. A
signed average can cancel a spatially changing difference, so it is never the sole magnitude
summary (within-sitting prespec §50).

**Sign agreement.** Over the comparison-defined knots, let
`S = { k ∈ D : E2(z_k) ≠ 0 and E1(z_k) ≠ 0 }` — the knots where **both** effects carry a defined
non-zero sign. Then

```
A_sign = #{ k ∈ S : sign(E2(z_k)) = sign(E1(z_k)) } / |S|
```

**defined iff `|S| > 0`**, and empty (not `0`, not `1`) when `|S| = 0`. A knot where either side is
exactly zero has no sign to agree on and is **excluded from both numerator and denominator**; the
zero counts on each side are published separately so the exclusion cannot be read as agreement.
`A_sign` is a property of the two effects' directions, distinct from the sign composition of `D`
(reported separately as positive/negative/zero counts). No `p`-value or population claim is attached
to `A_sign` — it describes two realizations.

**Shape correlation.** Pearson correlation between `E1` and `E2` over `D`, reusing the within-sitting
`ProfileShape` rule (`analysis.sparse_sa5_effects.ProfileShape`; v1 contract §6): reported **iff
`|D| ≥ MIN_SHAPE_KNOTS` (= 3) and neither series is constant** (`CONSTANT_TOLERANCE_REL = 1e-12`),
else `undefined` with the failing reason. Correlation of `D` against depth is a **different**
endpoint and is not used here.

**Per-side numerical maximum, then peak localization — two separate things.** For each side
`s ∈ {1, 2}`, on the common-defined comparison knots `D` and using the frozen effect arrays and the
within-sitting shallower-depth tie rule (within-sitting prespec §50):

```
M*_s = max_{k ∈ D} |E_s(z_k)|          z*_s = the shallower depth attaining it
```

The **numerical maximum** (`M*_s`, `z*_s`) is **always defined whenever `|D| ≥ 1`** — a single
common-defined knot still yields a numerical extremum; it is typed-empty with reason
**`insufficient-depth-support`** only when `D` is empty. Retain each side's published
`max_abs_value`/`max_abs_depth_mm` separately as its original full-support context (never recomputed
on `D`).

A numerical extremum is a **localized peak** only when the profile actually varies. Define the
per-side boolean **`peak_localized_s`** as **true iff both** (a) the side has **≥ 2 distinct
common-defined depths** (`|D| ≥ 2`) **and** (b) its absolute effect profile over `D` is
**nonconstant** under the existing `CONSTANT_TOLERANCE_REL = 1e-12`
(`analysis.sparse_sa5_effects.CONSTANT_TOLERANCE_REL`, the same rule the `MIN_SHAPE_KNOTS`/`ProfileShape`
correlation uses). Otherwise `peak_localized_s` is **false**, with reason
**`insufficient-depth-support`** when `|D| < 2` (or `D` empty) and
**`constant-absolute-effect-profile`** when the absolute profile is constant to within tolerance. A
constant-absolute-effect profile keeps its numerical maximum but has **no** localized peak.

**Peak displacement and coincidence — only when both sides are localized.** The displacement
`Δz* = z*_2 − z*_1` (**positive = deeper in live-2**, reported with the two common-domain depths) and
the boolean "peaks coincide on the comparison grid" (the two `z*_s` equal within `GATE_TOLERANCE_MM`)
are published **only when `peak_localized_1` and `peak_localized_2` are both true**; otherwise both
are typed-empty with the failing side's reason (`constant-absolute-effect-profile` or
`insufficient-depth-support`). Neither is ever read off a non-localized side's numerical extremum. A
maximum is never called a robust effect (within-sitting prespec §50).

## 6. Per-sitting context, magnitude, coverage, repeats

Every cross-sitting quantity is published **beside** each sitting's own frozen context, quoted
verbatim from that sitting's CSV/JSON and **never recomputed with the comparison's own
denominator** (within-sitting prespec §54; an agreement number alone cannot say whether both
effects are large, both negligible or both unresolved). Per side: **magnitude**
(`rms_magnitude`, `signed_depth_average`, `equal_knot_average`, `max_abs_value`/`max_abs_depth_mm`);
**coverage/definedness** (`covered_depth_mm`, `coverage_fraction`, `defined_count`,
`undefined_alignment_count`, `undefined_operand_count`, `knot_count`); and **repeat context** — attached per contrast's **distinct operand** (never to the contrast as a whole),
**only when the operand's whole achieved condition is provable from published metadata** (amendment A1).

**What counts as proof.** A `repeats` group (v1 contract §5.6) publishes a prose `condition`, its
`metric`/`view`, `knot_count`, `defined_members`, `min_value`/`max_value`/`spread` and its `members`
— each member carrying `label`, `order`, `job`, `value`, `defined_count`, `state`, `reason` — and
**no achieved-condition field** (no burst length, emissions per profile, PRF, stored pitch or gate
count). The prose `condition` string is generator-authored text, **not** metadata, and is never
sufficient on its own. A group therefore attaches to an operand **iff** the operand's whole achieved
condition — as published in the sitting's `provenance` (v1 contract §5.1) — is matched field-for-field
through the members: the group's members must resolve to the operand's own `participants` (v1 `effects`
rows) by the same published `job` identities, each member's whole achieved condition must be present in
`provenance`, those conditions must agree with one another, and they must equal the operand's. A `job`,
`label` or `order` **name alone is never a substitute** for condition identity, and no group is ever
attached on the guess that two same-named jobs share a condition. The published v1 groups are the
**common-reference condition** (`cr1..cr4`) and each job's **block-local anchor controls**. The explicit
mapping for the seven oriented contrasts (published names and operand order as in §2 and the v1 `effects`
rows) is:

| contrast | distinct operands | repeat context (attached only if identity provable) |
| --- | --- | --- |
| `pitch_at_burst_4` | `cc1`, `cc3` | `repeat-context-unavailable` for both |
| `pitch_at_burst_18` | `cc2`, `cc4` | `repeat-context-unavailable` for both |
| `burst_at_fine_pitch` | `cc1`, `cc2` | `repeat-context-unavailable` for both |
| `burst_at_coarse_pitch` | `cc3`, `cc4` | `repeat-context-unavailable` for both |
| `E8_minus_E20` | `e8`, `E20` | `e8` → `repeat-context-identity-unverifiable`; `E20` → the common-reference group, iff identity provable |
| `E64_minus_E20` | `e64`, `E20` | `e64` → `repeat-context-identity-unverifiable`; `E20` → the common-reference group, iff identity provable |
| `E128_minus_E20` | `e128`, `E20` | `e128` → `repeat-context-identity-unverifiable`; `E20` → the common-reference group, iff identity provable |
| `pitch_x_burst_interaction` | `cc1`, `cc2`, `cc3`, `cc4` | `repeat-context-unavailable` for all four |

Two typed-empty context states replace the group selection, each with its own reason:

- **`repeat-context-unavailable`** (reason `no-published-repeat-group-matches-the-operand-whole-condition`):
  the four corner operands carry a fine (`0.616666666667` mm / 145 gates) or coarse (`2.96` mm / 31 gates)
  stored window, and no published group's whole achieved condition is provably that of a corner — the
  groups that name the corner jobs (`burst-4`, `burst-18`) are not identity-verifiable (their control
  members are unpublished, below) and are never attached by name — and the interaction's operands are
  the same four corners. **No contrast-level or synthetic repeat group is ever constructed** from a
  contrast's two sides, and no anchor or reference member is averaged into an operand (within-sitting
  prespec §42).
- **`repeat-context-identity-unverifiable`** (reason `repeat-group-member-achieved-condition-not-published`):
  a block-local anchor group names the same job as the `e8`/`e64`/`e128` operand, but the group carries no
  achieved-condition field and its control members (`ctrl-begin`/`ctrl-mid`/`ctrl-end`) are not published
  in the sitting's `provenance`, so the operand's whole achieved condition cannot be proved to equal
  theirs. Because identity is unprovable, **no numerical range is published**: that side's
  `min`/`max`/`spread` are **omitted** from the cross-sitting context — not shown, not typed null, not
  bridged, and never resolved by the shared `job` name.

`min`/`max`/`spread` are published **only** for an identity-verified group, and are **descriptive only**
(no range is a floor, no member a replicate). The only identity-verified group in v1 is the
common-reference group attached to the `E20` operand: the v1 `E20` operand is published as kind
`mean-of-four` of members `cr1..cr4`, whose jobs appear in `provenance` with their whole achieved
condition, and the common-reference group's members are exactly those jobs — so the proof rule above is
satisfied. Comparison `L`, `|D|`, `|S|` and the span are published as the comparison's own coverage. For
each effect, show both original per-sitting magnitude summaries (always available from the sitting's own
frozen context), and — separately for each sitting, and only for an identity-verified group — the
applicable same-condition repeat members and their range/spread. The current repeat-member scalar is an
unweighted mean of one condition's defined knots, **not an effect contrast**; its range cannot be used as
a like-for-like interval for any effect magnitude, including the effect's equal-knot average, profile RMS
or absolute maximum. Mark numerical overlap `not-like-for-like` and display the context without a
threshold or universal floor. A future contrast-level variation diagnostic requires its own prespecified
member pairing and reduction.

**Context only — it never touches the comparison.** A repeat context (a selected group, or either
typed-empty state) is attached **beside** the frozen per-sitting summaries and is **excluded** from every
comparison decision: it never enters `comparison_state`, `label_state`, or any §5 core diagnostic (`D̄`,
`RMS(D)`, `A_sign`, the profile correlation, `M*_s`, `peak_localized_s`, `Δz*`). A pair whose repeat
context is `repeat-context-unavailable` or `repeat-context-identity-unverifiable` is therefore **still
`comparable`** whenever §§2–5 make it so, and remains eligible for a future label rule; an unverifiable
context can never produce `not comparable`, `not resolvable with this design` or a label.

## 7. Typed noncomparability and nonresolvability

Every matched pair carries **two orthogonal, separately named states** — never one blended score, and
never labelled with the other's vocabulary:

**`comparison_state`** — whether the pair has a common comparison basis (this section). It is one
of three **typed**, mutually exclusive outcomes, each with its explicit reason:

| typed `comparison_state` | meaning | example reasons |
| --- | --- | --- |
| `comparable` | the pair has a common comparison basis; each §5 diagnostic is either defined or explicitly typed-empty | a §5 diagnostic typed-empty, e.g. `insufficient-depth-support` or `constant-absolute-effect-profile` |
| `not comparable` | the pair has no shared structural basis or no common defined knot | `effect-id-mismatch`, `triple-mismatch`, `grid-mismatch-pending-review`, `side-wholly-undefined`, `units-mismatch` |
| `not resolvable with this design` | a future pre-registered, endpoint-specific rule establishes that this design cannot resolve the comparison against its own like-for-like variation | no such rule is registered here; do not emit this outcome merely because a rule is absent |

**`label_state`** — the recurrence verdict (§8), a *different* axis: it is
**`deferred-pending-review`** in v1 for a `comparable` pair, and it is what a registered
metric-specific evidence rule would eventually set. A missing classification rule defers the
`label_state`; it never becomes a `comparison_state`, and no `comparison_state` is ever written
into the label field.

A broken digest chain or failed input gate **refuses the whole run**, not merely a
row; a defined pair with an empty sign/correlation/integral remains comparable
with a typed-empty diagnostic. A missing classification rule defers the
`label_state`, not the `comparison_state`. `comparison_state` and `label_state` are **states, not values**: **absence of a
resolved difference is never equivalence**, and gates/profiles are never independent replicates
(within-sitting prespec §52). A within-sitting refusal on one side (a non-value `0.0`, a constant
trace, a declined axis, a `defined-zero-power` `0/0`) propagates to a comparison non-value at that
knot — it is not resolved by the other side's value.

## 8. Labels — explicit evidence rules only, or deferred

The only permitted `label_state` vocabulary is the within-sitting prespec's (§54): **`recurs
descriptively`** and **`does not recur descriptively`**. The within-sitting prespec writes this set as
`recurs descriptively / does not recur descriptively / not comparable / not resolvable`; the latter
two terms belong to §7 **`comparison_state`** (the pair carries no recurrence label at all), **not** a
`label_state` value — the two axes stay separate. A label (a `label_state`) may be emitted **only**
under an explicit, pre-registered, metric-specific evidence rule that names the endpoint (which of
`D̄`, `RMS(D)`, `A_sign`, correlation, `Δz*`), the like-for-like reduction it reads, and the threshold
— none of which is invented from observed values here.

**No such rule is registered in this prespec.** In v1 the `label_state` field is
**`deferred-pending-review`** for structurally comparable rows; `not comparable`
is still emitted where §§2–4 force it. `not resolvable with this design` requires
a separately reviewed endpoint-specific rule and is not emitted by this version.
The artifact publishes the §5 quantities and §6 context **without a recurrence
verdict**. Registering a rule is an **explicit amendment**, reviewed before its
application; a rule chosen to fit observed differences is forbidden (within-sitting prespec §52). **No `p`-value, floor
or population/causal claim is permitted** here; this is two realizations, not inference (plan §"SA5").

## 9. Artifact contract plan (separate, not this prespec)

This file fixes the **comparison design**, not the serialization schema. The next
backend slice may implement typed, in-memory comparisons without publication;
the following publication/verifier PR must specify and review the distinct
cross-sitting artifact contract before committing any generated evidence. A
possible name is `sa5-cross-sitting.{npz,json,csv,README.md}` under
`reports/sparse-signal/`; its exact closed schema remains to be reviewed. It must
specify, at minimum: the NPZ member set and byte rule (v1 contract §4); the
JSON's closed fields including a `comparison_state` vocabulary, a separate `label_state` field and a
per-knot `(state2, state1)` pair;
the CSV's 72-row one-row-per-effect scalar set (`D̄`, `RMS(D)`, `A_sign`, `|S|`, `L`, correlation,
`Δz*`, the per-side `peak_localized`); the digest convention (v1 contract §5.7); the `D`/`A_sign`
non-value rows and the §6 `repeat-context-unavailable` / `repeat-context-identity-unverifiable`
rows (the latter carrying no numerical range); and the
independent verifier (v1 contract §11) recomputing from the two committed quartets rather than
re-reading a writer's staged values. Until that contract is accepted, **no cross-sitting artifact is
generated or committed**; the two v1 quartets and every frozen WP/SA2.4 report stay byte-untouched.

## 10. Refusal gate and provenance

The generator (later slice) must bind each side's quartet by the §1 digest chain and **refuse** on
any mismatch; refuse a third sitting and Stage-2 as inputs; refuse the reversed orientation
(`live1 − live2`) once `live2 − live1` is fixed here; refuse any **operand reselection or revision
of the within-sitting definitions** (agenda "SA5 cross-sitting agreement"); refuse to cross the two
views or two grids (§2), to interpolate (§3), or to bridge an undefined knot (§5); and never
overwrite or re-derive a v1 within-sitting value or a frozen WP/SA2.4 report (v1 contract §9).
Provenance carries, per side: pass name, `plan`, `plan_fingerprint`, `analysis_commit`, the three
quartet digests, and the sitting's own `checks`/`artifact_checks` verdicts quoted from its JSON
(v1 contract §5.1) — an input is not usable until its own checks re-assert true.

## 11. Testing gate

The implementation must test, deterministically and to scratch outputs:

1. the two-side digest binding, including a tampered quartet (refusal);
2. exact triple/`effect_id` match (swapped `view`; swapped `contrast`) and orientation
   (including a reversed-input attempt);
3. knot matching on identical native knots, and a doctored mismatched knot set refusing as
   `grid-mismatch-pending-review` (no interpolation performed);
4. a knot undefined on exactly one side (both `undefined-operand` and `undefined-alignment`),
   checking the published `(state2, state1)` pair and that `D` is not bridged;
5. `L = 0` giving empty `D̄`/`RMS`, and a one-knot-common case;
6. `A_sign` with zero-effect knots excluded from numerator **and** denominator, and `|S| = 0`
   giving an empty (not `0`) agreement;
7. `MIN_SHAPE_KNOTS` / `CONSTANT_TOLERANCE_REL` correlation refusal; the §5 split — a numerical
   maximum defined at exactly one common-defined knot (`|D| = 1`), `peak_localized_s` false with
   `insufficient-depth-support` (`|D| < 2`) and with `constant-absolute-effect-profile`, and
   `Δz*`/coincidence typed-empty unless **both** sides are localized, with the shallower-depth tie
   rule and a wholly-undefined side;
8. the §6 repeat-context attachment by **provable** whole achieved identity — `E20` selecting the
   common-reference group **only** through the published `cr1..cr4` operand provenance (and, when a
   member's condition or identity is withheld, refusing as `repeat-context-identity-unverifiable`);
   `repeat-context-identity-unverifiable` for the `e8`/`e64`/`e128` sides with that group's
   `min`/`max`/`spread` **absent** (no numerical range, no typed null) so an unverifiable range can
   never be read; `repeat-context-unavailable` for the four corner operands and the interaction; no
   contrast-level synthetic group, no `job`/`label`/`order` substitution, and no group attached on its
   prose `condition` string alone;
9. `comparison_state` / `label_state` typed states kept separate, that no `label_state` but
   `deferred-pending-review` is ever written in v1, and that the v1 quartets and frozen WP/SA2.4
   reports are byte-unchanged after a run.
10. that a pair whose repeat context is `repeat-context-unavailable` or
    `repeat-context-identity-unverifiable` stays `comparable` and carries **identical** `comparison_state`,
    `label_state` and §5 diagnostics (`D̄`, `RMS(D)`, `A_sign`, correlation, `M*_s`, `peak_localized_s`,
    `Δz*`) to the same pair with a selected context — the repeat context changes nothing but itself.

## 12. Out of scope

No schema, generator, committed array or value here; no Stage-2 pooling, no third sitting, no
`p`-value, floor, optimum, causality or population claim, no agreement artifact. SA3/POD, SA6 UI and
CFD alignment remain separate evidence-driven slices (plan §"Delivery split and non-goals"). Any new
endpoint or observable is an explicit amendment before its effect values are examined.
