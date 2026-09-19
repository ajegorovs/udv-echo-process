"""Magnify a region of a screenshot, and dump a glyph's pixels — the two steps that
turn a crop into a *readable* caption.

**Why this exists.** Every caption and value in this application's UI is paint, not
control text, so a number reaches a reader as pixels and nothing else. Reading those
pixels at the crop's own size is where the errors come from, and they are not
hypothetical: the same frame read ``500`` for ``600`` twice, ``3.49`` for ``0.49`` and
``725`` for ``726``, and a summarising vision pass on a downscaled full frame is worse
still (a 1920x1080 frame is downscaled before it is seen, and the digit that breaks is
the first thing to go). The method that settled all of them has two steps, and this
tool is those two steps:

1. **composite** — cut one or more regions from a frame and stack them at a
   nearest-neighbour magnification (x5-x6 was enough in practice), so the glyphs are
   large and un-resampled. Nearest-neighbour matters: a smoothed magnified digit is a
   *different* digit to compare against.
2. **glyphs** — print the ink bitmap of a region as ASCII, one run per glyph, so a
   digit read out of a crop can be compared pixel-for-pixel with a digit that is
   known in the *same* frame (``5`` against the ``5`` of the same frame's ``50``, a
   digit the frame's own arithmetic corroborates). This is what removes the
   "which of these two glyphs is it" argument: the bitmaps either match or they do
   not, and neither reading is taken on trust.

Both subcommands are read-only with respect to their input: nothing is written except
the composite's own output file, given explicitly. Pillow is the only dependency and it
is cross-platform, so a reader on Linux can magnify the *committed* crops (the ones
under ``docs/dop3000/ui-crops/``) with no instrument and no Windows — which is the point
of keeping the crops in the repository at all.

Usage::

    # one panel, x6, from a committed crop
    .venv/Scripts/python.exe tools/ui/magnify.py composite /tmp/out.png \\
        --from docs/dop3000/ui-crops/sidebar-parameters.png \\
        --region 11,57,50,71 --label "US Frequency [kHz]"

    # several panels stacked in one image, one per --region
    .venv/Scripts/python.exe tools/ui/magnify.py composite /tmp/out.png \\
        --from docs/dop3000/ui-crops/overlay-operational-parameters-blocking.png \\
        --region 130,127,207,147 --label "Burst length" \\
        --region 334,168,403,183 --label "Nb of gates"

    # the bitmaps behind a contested digit
    .venv/Scripts/python.exe tools/ui/magnify.py glyphs \\
        docs/dop3000/ui-crops/sidebar-parameters.png --region 11,82,50,97

The composite prints each panel's source rect and the result's own image statistics
(distinct greys, dominant grey's share, grey range), so a flat or unreadable panel is
named where it is produced rather than discovered later — the same "a black PNG looks
like success" guard the live capture probe uses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LABEL_HEIGHT = 26
PAD = 6
MARGIN = 10


def _load_pillow():
    """Import Pillow, naming the fix when it is absent (it is not a base dependency)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover - only on a bare install
        print(
            "magnify: Pillow is required for the PNG work; install it with\n"
            "  uv sync --extra acquire        # or: uv pip install pillow",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    return Image, ImageDraw


def parse_region(spec: str) -> tuple[int, int, int, int]:
    """Parse ``x0,y0,x1,y1`` (a half-open pixel box) and validate its shape."""
    parts = spec.replace(" ", "").split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"region must be x0,y0,x1,y1 - got {spec!r}")
    try:
        x0, y0, x1, y1 = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"region values must be integers - got {spec!r}"
        ) from None
    if x1 <= x0 or y1 <= y0:
        raise argparse.ArgumentTypeError(
            f"region is empty: x1>x0 and y1>y0 required - {spec!r}"
        )
    return x0, y0, x1, y1


def image_stats(im) -> dict[str, float]:
    """Distinct greys, the dominant grey's share and the range — the flat-image guard."""
    counts = im.convert("L").histogram()  # 256 buckets, no per-pixel list
    total = sum(counts) or 1
    present = {value: n for value, n in enumerate(counts) if n}
    dominant, share = max(present.items(), key=lambda kv: kv[1])
    return {
        "greys": len(present),
        "dominant": dominant,
        "dominant_share": round(share / total, 4),
        "min": min(present),
        "max": max(present),
    }


def composite(args: argparse.Namespace) -> int:
    Image, ImageDraw = _load_pillow()
    source = Path(args.source)
    if not source.exists():
        print(f"magnify: no such image: {source}", file=sys.stderr)
        return 2

    with Image.open(source) as im:
        frame = im.convert("RGB")
        panels = []
        for spec, label in zip(args.region, args.label, strict=False):
            box = parse_region(spec)
            panel = frame.crop(box)
            if args.scale != 1:
                panel = panel.resize(
                    (panel.width * args.scale, panel.height * args.scale), Image.NEAREST
                )
            panels.append((label or f"{spec}", box, panel))
            print(
                f"panel {label or spec!r}: {source.name} {box} -> {panel.width}x{panel.height}"
            )

    width = max(p.width for _, _, p in panels) + 2 * MARGIN
    height = sum(LABEL_HEIGHT + p.height + PAD for _, _, p in panels) + MARGIN
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    y = MARGIN
    for label, _, panel in panels:
        draw.text((MARGIN, y), label, fill=(200, 0, 0))
        y += LABEL_HEIGHT
        canvas.paste(panel, (MARGIN, y))
        y += panel.height + PAD
    canvas.save(args.out)
    print(
        f"wrote {args.out} ({canvas.width}x{canvas.height}) stats={image_stats(canvas)}"
    )
    return 0


def glyphs(args: argparse.Namespace) -> int:
    Image, _ = _load_pillow()
    source = Path(args.source)
    if not source.exists():
        print(f"magnify: no such image: {source}", file=sys.stderr)
        return 2
    box = parse_region(args.region)
    with Image.open(source) as im:
        grey = im.convert("L").crop(box)
    w, h = grey.size
    ink = [[grey.getpixel((x, y)) < args.threshold for x in range(w)] for y in range(h)]
    print(f"{source.name} {box} -> {w}x{h} threshold={args.threshold}")

    columns = [any(row[x] for row in ink) for x in range(w)]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    blanks = 0
    for i, filled in enumerate(columns):
        if filled:
            if start is None:
                start = i
            blanks = 0
        elif start is not None:
            blanks += 1
            if blanks >= args.gap:
                runs.append((start, i - blanks))
                start = None
    if start is not None:
        runs.append((start, w - 1))

    if not runs:
        print("  no ink found: the region is blank or the threshold is too low")
        return 1
    print(f"  {len(runs)} glyph run(s), split on {args.gap}+ blank column(s):")
    for k, (s, e) in enumerate(runs):
        block = [row[s : e + 1] for row in ink]
        print(f"  glyph[{k}] width={e - s + 1}")
        for row in block:
            print("    " + "".join("#" if v else "." for v in row))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("composite", help="stack magnified regions into one image")
    c.add_argument("out", help="the PNG to write")
    c.add_argument("--from", dest="source", required=True, help="the frame to cut from")
    c.add_argument(
        "--region",
        action="append",
        required=True,
        metavar="X0,Y0,X1,Y1",
        help="a box to cut (repeatable)",
    )
    c.add_argument(
        "--label",
        action="append",
        default=[],
        help="a caption for the matching --region",
    )
    c.add_argument(
        "--scale",
        type=int,
        default=6,
        help="nearest-neighbour magnification (default 6)",
    )
    c.set_defaults(func=composite)

    g = sub.add_parser("glyphs", help="print a region's ink bitmap, one run per glyph")
    g.add_argument("--from", dest="source", required=True, help="the frame to read")
    g.add_argument(
        "--region", required=True, metavar="X0,Y0,X1,Y1", help="the box to read"
    )
    g.add_argument(
        "--threshold", type=int, default=150, help="ink below this grey (default 150)"
    )
    g.add_argument(
        "--gap",
        type=int,
        default=2,
        help="blank columns that separate two glyphs (default 2)",
    )
    g.set_defaults(func=glyphs)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
