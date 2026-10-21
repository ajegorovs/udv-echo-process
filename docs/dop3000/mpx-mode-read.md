# MPX mode read — read-only visual attribution

Status: **implemented, read-only**. `acquire mpx-mode-read --capture-dir DIR` and the additive
`visual_mode_mark` field on `channels-read --capture-dir` report the multiplexer mode entry and
its rollover mark from pixels. Nothing here presses, hovers, opens or closes anything.

## What is read

| surface (structural) | crop | mode-entry line | rollover row |
|---|---|---|---|
| `SETTINGS_FULL` | 393x426, 3 px frame | `Enable multiplexer` | measured red cross (OFF, 70 px) or green check (ON, 22 px) |
| `MULTIPLEXER_ON_ENTRY` | 158x43, 3 px frame, one band | `Desable multiplexer` | absent by structure |

Derived values, none of which is a native fact:

- `mode`: `VISUAL_ENABLED` / `VISUAL_DISABLED` / `UNKNOWN` — derived from the entry line only.
- `rolling`: `ON_PROVEN` / `OFF_PROVEN` / `ABSENT` / `UNKNOWN` — the mark, read independently.
- `mark`: the exact template matched at `(215,77,228,92)`, or `UNRECOGNIZED` / `ABSENT`.

`native_fact` and `action_authority` are `False` on every record. `recognition` is
`EXACT_TEMPLATE_MATCH` only when every region that shape offers was compared and matched — on
`SETTINGS_FULL` the entry line **and** the rollover mark, on the clipped entry the entry line
alone (it has no mark region). It is `NOT_MATCHED` when a region was compared and did not match
(a garbled clipped caption is `NOT_MATCHED` even though its `rolling` is `ABSENT`, because the
absence is a fact about the shape, not about the caption), and `NOT_PERFORMED` only when no
comparison happened at all (unreadable frame, unsupported size).

The comparison is an **exact shape mask**: the thresholded ink bitmap over the measured box or
rect must equal the committed raster cell for cell — no threshold distance, no nearest
look-alike, no OCR. It is *not* a claim about RGB bytes: a repaint that stays inside the ink
predicate still matches, and position is part of the template, so the same ink one pixel over
does not.

## Provenance of the read itself

The same pixels mean different things on the two paths, so every record carries which path
produced it:

| field | retained read (`mpx-mode-read --capture-dir`) | live read (`channels-read --capture-dir`) |
|---|---|---|
| `acquisition_context` | `retained` | `live-bracketed` |
| `freshness` | `not_established` | `live_bracketed` |
| `integrity` | `decoded-pair-only` | `capture-digest-verified` |
| `enable_precondition` | always `false` | `true` only for `VISUAL_DISABLED` + `ON_PROVEN` |

- **`retained` is historical evidence, never a precondition.** `mpx-mode-read` re-reads a
  directory the capture contract already wrote; there is no capture record beside it, no
  capture-time digest and no trusted time. Its digests are re-derived from the decoded pixels,
  which catches a swapped frame as *new content* — the directory is then attributed as what it
  now holds, with `decoded-pair-only` integrity, no retained capture identity claim and no
  freshness claim. A file's mtime is never read as age, and no invented timestamp or capture id
  is added. So even the retained `disabled-rolling-on` pair, which does paint
  `VISUAL_DISABLED` with `ON_PROVEN`, states `enable_precondition: false`.
- **`live-bracketed` is the only path that can state a moment.** `channels-read --capture-dir`
  binds one window, grabs the two frames that bracket its numeric read, and holds them to the
  capture's own recorded digests; that is what `capture-digest-verified` records. It still
  grants no action authority, and a refused or synthetic frame stays `not_established`.

## Before any future enable

A future enable needs a **fresh** `SETTINGS_FULL` read that proves **both** `VISUAL_DISABLED`
*and* `ON_PROVEN` in the same live-bracketed moment as the decision — the conjunction, not the
mark alone, and not a retained pre-state. A pre-state recorded earlier is history: it may show
the conjunction, but nothing in it establishes that the popup is still painting it. The clipped
entry popup — the only shape available after an enable press — states no rolling state at all,
so it can never supply the second half. No press recipe exists for the mode-toggle row; that
measurement is still missing and this reader does not supply it.

## Where it lives

| concern | owner |
|---|---|
| mark rects, committed rasters, exact match, typing | `acquire/mode_marks.py` (+ generated `mode_marks_templates.py`) |
| rasters → committed module | `tools/live/probes/gen_mode_mark_templates.py` over `tests/data/mpx-mode/` |
| settings capture, guards, bracketing, stability | `acquire/channels_capture.py`, `acquire/channels_read.py` (unchanged semantics) |
| retained-evidence read of either shape | `acquire mpx-mode-read --capture-dir` |

`channels-read --capture-dir` fills `capture.visual_mode_mark` **only** when the capture is
`ok`, both frames are stable, and the crop is the measured settings rectangle. A field of
`None` means no read was attempted, never that the popup states no mode. The report's `caption`
stays `UNKNOWN` whatever this reader returns.

`mpx-mode-read` adds no capture framework: it re-reads the two frames the existing capture
contract already retained (`channels-roi-frame-1.png`, `-2.png`) exactly once, re-derives their
pixel digests from the decoded RGB with `channels_capture.digest`, and refuses a pair whose
digests differ, whose path and digest counts disagree, or whose supplied digests do not match.
The existing guards, exclusive run-directory claim, virtual-screen-origin handling and partial
retention are untouched, and no clipped-entry capture path was added.

The clipped entry is a **separate structural contract**, not a relaxation of the settings one:
its shape is established from size, 3 px frame and exactly one ink band, it carries no numeric
settings bracketing (the record has no `numeric` field at all), and the settings capture's
`status == ok` still means what it meant — five bracketed amounts on the settings popup.

## Refusals

Changed label pixel, shifted mark inside the rect, mark at another rect, both marks present,
erased mark, translated or altered caption, unstable pair, incomplete pair, forged digest,
swapped frame, and any size other than the two measured ones (refused from the header, before
decode). A refusal is `mode=UNKNOWN` with a named reason; the independent fact survives, so a
failed label read does not erase a proven rolling state and vice versa. An unknown mode is exit
code 2 and licenses nothing.

## Before any future enable

A future enable needs a **fresh** `SETTINGS_FULL` read proving `VISUAL_DISABLED` **and**
`ON_PROVEN`, taken in the same live-bracketed moment as the decision. A pre-state recorded
earlier is history, not a precondition: rolling state is a live mark, and the clipped entry
popup — the only shape available after an enable press — states no rolling state at all. No
press recipe exists for the mode-toggle row; that measurement is still missing and this reader
does not supply it.
