# tools/ui — the inspection crops, and the two steps that make them readable

This directory holds the tooling for the one class of evidence the control tree cannot
give: **paint**. Every caption and every value on this application's surfaces is drawn,
not stored — the buttons and menu entries carry no window text at all (`WM_GETTEXT`
returns `""` for nearly all of them), and the sidebar's row labels are not controls in
any sense. So when a caption has to be quoted — which button says `Cancel`, what a
dropdown's entries read, which row of the parameter column is which — it is quoted from
pixels or it is not quoted.

```
docs/dop3000/ui-crops/          45 PNGs: the crops themselves (committed, ~hand-cut by the operator)
docs/dop3000/ui-element-index.md the index: one row per crop — id, file, size, surface, state,
                                 what it shows, and whether the surface blocks the cursor
tools/ui/crop_index.py           the checker: does the index describe the files it claims to?
tools/ui/magnify.py              composite (nearest-neighbour magnification) + glyphs (bitmaps)
```

## The rule that makes the set trustworthy

**The index is data, and it is checked.** `crop_index.py` reads the index's own table and
verifies it against the files: every crop on disk has a row, every row's file exists, the
`WxH` recorded in each cell equals the PNG's real size (read with Pillow), ids are unique,
the numbering inside each family has no gaps, and the row count matches the total the
document states in its own prose. Run it in the same change as any crop added, renamed or
withdrawn:

```bash
uv run --extra acquire python tools/ui/crop_index.py
# index rows: 45   crops on disk: 45   families: {'UI-BAR': 1, 'UI-MENU': 17, ...}
# ok: every indexed crop exists, is the size the index states, and is numbered without a gap
```

It exits non-zero on any failure, and it is deliberately a checker rather than a
generator. The ad-hoc builder that once wrote the index lived in a git-ignored directory
and its ledger fell behind the crops (30 rows against 45 files), so the committed
document could not be regenerated from anything in the repository — an index nobody can
verify is worse than no index, because a quoted caption then carries a provenance that
cannot be checked. `--emit-ledger PATH` writes the parsed rows as JSON when a generator
is wanted again; it is not the source of truth.

The **`blocking` column is the one cell no crop can settle** whether a surface traps the
mouse cursor is a property of the running application, not of a picture of it, and the
index says so per row (the operator's answer, or the plan's word, named as such). The
checker does not and cannot verify that column.

## Reading a crop without misreading it

Reading a crop at its own size is where the errors come from, and they are not
hypothetical: the same frame read `500` for `600` twice, `3.49` for `0.49`, `725` for
`726`. A vision pass over a *downscaled* full frame is worse — a 1920x1080 capture is
halved before it is seen and the digit that breaks is the first thing lost. So magnify
and compare glyphs before believing a number:

```bash
# stack the panels you care about at x6, nearest-neighbour, labelled
uv run --extra acquire python tools/ui/magnify.py composite /tmp/panels.png \
  --from docs/dop3000/ui-crops/sidebar-parameters.png \
  --region 11,82,50,97 --label "PRF [us]" \
  --region 11,132,50,147 --label "Resolution [mm]"

# the bitmaps behind a contested digit, to compare against a digit known in the same frame
uv run --extra acquire python tools/ui/magnify.py glyphs \
  --from docs/dop3000/ui-crops/sidebar-parameters.png --region 11,82,50,97
```

The `glyphs` dump prints each glyph run as ASCII, which is what settles `6` against `5`:
the bitmaps either match the frame's other, unambiguous digits or they do not. The
composite prints its own image statistics (distinct greys, dominant grey's share, range)
so a flat or blank panel is named where it is produced — the same guard the live capture
probe applies, because a black PNG looks like a success.

Prefer a **band-wide or column-wide crop to a full frame**, and cite the crop's id
(`UI-MENU-05`, `UI-OVERLAY-22`) when a caption is quoted in a document: the id is what
makes the quote checkable against the set later.

## Taking new crops (Windows + the interactive session only)

The capture half cannot run here, or anywhere without the instrument's desktop:

- `tools/live/probes/dialog_shot.py` — one whole-screen frame plus the dialog's own rect
  cropped out of *that same* frame (so the two images cannot disagree about which moment
  they show), full-size lossless PNG, with `image_stats`/`non_blank` and a two-frame
  stability check. It runs through `tools/live/dispatch.sh` in the interactive session —
  see `tools/live/README.md`.
- The operator then hand-cuts the regions that matter and the index gains a row per crop
  (the checker above enforces the bookkeeping).

A machine without Windows can read, magnify, check and quote the committed set; it can
never add to it. That split is the reason the crops are committed at all, and it is
recorded for the refactor in `docs/dev-handoff.md`.
