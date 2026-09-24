# Secondary sensitivity: omitting the first pair

This is a **post-hoc sensitivity reading**, not a revision of the prespecified
four-pair screen or its `unresolved overlap / not detected` verdict. The primary
result remains [`pairs.md`](pairs.md); the eight-run inputs and full-precision
window means are in [`pairs.json`](pairs.json).

The campaign's first run, `e20-a` (22.6053 mm/s), sets the primary E20
within-level maximum of 9.4044 mm/s against `e20-b`. Omitting `e20-a` makes
pair A (`e64-a − e20-a`) undefined; **do not retain its +7.2256 mm/s contrast
while recomputing the floor without its E20 member**. Omit the whole pair A
for a balanced comparison. The remaining pairs B, C and D have oriented
E64 − E20 contrasts −1.5733, +0.3448 and +1.3418 mm/s. Over their three
runs per level, the same maximum-absolute-difference *endpoint* gives E20
2.1756 mm/s and E64 0.7395 mm/s; the larger, 2.1756 mm/s, exceeds every
remaining absolute contrast. Their directions also disagree. Thus the
secondary scalar reading is still **unresolved overlap / not detected**.

This is a different, three-run-per-level floor (three same-level pairs instead
of the primary analysis's six); it is **not** a rerun of the frozen Stage-2
gate and cannot validate exclusion of the first run. In particular, comparing
pair A to the smaller 2.1756 floor would use the excluded `e20-a` as evidence
while denying it membership in the population that sets the screen. It is not
a coherent sensitivity analysis. No result here establishes that `e20-a` was
invalid or that E64 and E20 are equivalent. There is no new acquisition
recommendation.

Reproduce the scalar calculation from the committed run means:

```bash
uv run python -c "import json,itertools; d=json.load(open('reports/stage2-e20-e64/pairs.json')); r={x['job']:x['depth_averaged_mean_mm_s'] for x in d['runs']}; f=lambda level:max(abs(r[f'{level}-{a}']-r[f'{level}-{b}']) for a,b in itertools.combinations('bcd',2)); print('floors:',f('e20'),f('e64')); print('contrasts:',[(p,r[f'e64-{p}']-r[f'e20-{p}']) for p in 'bcd'])"
```
