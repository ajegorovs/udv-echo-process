"""Committed glyph rasters for the painted Channels-popup caption line.

Generated from the measured fixtures in ``tests/data/caption-band/`` by
``caption_band.build_templates`` (the same learning path the tests re-run); do not edit by
hand. Every raster is one exact ink bitmap of a glyph measured in a named capture, so a
digit that was never photographed has no entry here. ``tests/test_acquire_caption_band.py``
re-derives this file's content from the committed PNGs and fails if the two disagree.
"""

from __future__ import annotations

from typing import NamedTuple


class _Template(NamedTuple):
    """One learned glyph: its ink rows, measured box, and the capture it came from."""

    glyph: str
    rows: tuple[str, ...]
    box: tuple[int, int, int, int]
    source: str
    source_digest: str


PREFIX = _Template(
    glyph="",
    rows=(
        "XXXXXXX...................X...................................................................X....................................X.......X........X....................................X....",
        "X......................X..X......................................................X............X....................................X......X.........X....................................X....",
        "X......................X..X......................................................X............X....................................X......X.........X....................................X....",
        "X........XXXX...X.X...XXX.X.XX....XXXX.......XXXX..X...X..X.X.X.X..XXXX...X.XX..XXX.....XXXX..X.XX....XXXX...X.XX...X.XX....XXXX...X.....X....XXXX..X.XX....XXXX...X.XX...X.XX....XXXX...X....",
        "XXXXXX..X....X..XX.....X..XX..X..X....X.....X....X.X...X..XX..XX..X....X..XX..X..X.....X....X.XX..X..X....X..XX..X..XX..X..X....X..X.....X...X....X.XX..X..X....X..XX..X..XX..X..X....X..X....",
        "X.......X....X..X......X..X...X..X....X.....X......X...X..X...X...X....X..X...X..X.....X......X...X...XXXXX..X...X..X...X..X....X..X.....X...X......X...X...XXXXX..X...X..X...X..X....X..X....",
        "X.......X....X..X......X..X...X..XXXXXX.....X......X...X..X...X...XXXXXX..X...X..X.....X......X...X..X....X..X...X..X...X..XXXXXX..X.....X...X......X...X..X....X..X...X..X...X..XXXXXX..X....",
        "X.......X....X..X......X..X...X..X..........X......X...X..X...X...X.......X...X..X.....X......X...X..X....X..X...X..X...X..X.......X.....X...X......X...X..X....X..X...X..X...X..X.......X....",
        "X.......X....X..X......X..X...X..X....X.....X....X.X..XX..X...X...X....X..X...X..X.....X....X.X...X..X....X..X...X..X...X..X....X..X.....X...X....X.X...X..X....X..X...X..X...X..X....X..X....",
        "X........XXXX...X.......X.X...X...XXXX.......XXXX...XX.X..X...X....XXXX...X...X...X.....XXXX..X...X...XXXX.X.X...X..X...X...XXXX...X.....X....XXXX..X...X...XXXX.X.X...X..X...X...XXXX...X....",
        "..........................................................................................................................................X...................................................",
        "..........................................................................................................................................X...................................................",
        "...........................................................................................................................................X..................................................",
    ),
    box=(88, 263, 278, 276),
    source="train-channel-1",
    source_digest="62651d2fcdefb39332ae32ffc28e6a9ce7bf3770878aa894a8ef110e77a70253",
)

SUFFIX = _Template(
    glyph=")",
    rows=(
        "X..",
        ".X.",
        ".X.",
        "..X",
        "..X",
        "..X",
        "..X",
        "..X",
        "..X",
        "..X",
        ".X.",
        ".X.",
        "X..",
    ),
    box=(285, 263, 288, 276),
    source="train-channel-1",
    source_digest="62651d2fcdefb39332ae32ffc28e6a9ce7bf3770878aa894a8ef110e77a70253",
)

DIGITS: dict[str, _Template] = {
    "0": _Template(
        glyph="0",
        rows=(
            ".XXX.",
            "X...X",
            "X...X",
            "X...X",
            "X...X",
            "X...X",
            "X...X",
            "X...X",
            "X...X",
            ".XXX.",
            ".....",
            ".....",
            ".....",
        ),
        box=(286, 263, 291, 276),
        source="train-channel-10",
        source_digest="78f3ecab0e8f4fd846d1f96cf5fe4cfc503e492a81cbbf31b9e782090a80c8dd",
    ),
    "1": _Template(
        glyph="1",
        rows=(
            "..X",
            "XXX",
            "..X",
            "..X",
            "..X",
            "..X",
            "..X",
            "..X",
            "..X",
            "..X",
            "...",
            "...",
            "...",
        ),
        box=(279, 263, 282, 276),
        source="train-channel-1",
        source_digest="62651d2fcdefb39332ae32ffc28e6a9ce7bf3770878aa894a8ef110e77a70253",
    ),
    "2": _Template(
        glyph="2",
        rows=(
            ".XXX.",
            "X...X",
            "X...X",
            "....X",
            "...X.",
            "..X..",
            ".X...",
            "X....",
            "X....",
            "XXXXX",
            ".....",
            ".....",
            ".....",
        ),
        box=(279, 263, 284, 276),
        source="train-channel-2",
        source_digest="809d569c5ea15a2a86e5d9b63e62c4c3647c8da57ca525ba7f7d12d334930e72",
    ),
}

TRAINING: tuple[str, ...] = (
    "train-channel-1",
    "train-channel-2",
    "train-channel-10",
)
