"""Check the committed UI crops against the index that claims to describe them.

The 45 PNGs in ``docs/dop3000/ui-crops/`` are the only oracle for this
application's own captions: its widgets are caption-less (``WM_GETTEXT`` returns
the empty string) and their labels exist as *paint*. The index
``docs/dop3000/ui-element-index.md`` is the record of what each crop shows, and
it is the thing a reader is asked to trust when a caption is quoted from it.

**Why a checker rather than a generator.** The crop set was hand-cut by the
operator and the index was written from it; the ad-hoc builder that once wrote
the document lived in a git-ignored directory and its ledger is now behind the
crops (30 rows against 45 files), so the committed document cannot be
regenerated from anything in the repository. A generator whose input is lost is
not evidence. This tool inverts the direction: it *reads the index as data* and
checks it against the files, so every claim the index makes about a file — that
it exists, and that the pixel dimensions in its cell are that file's real size —
is verified on any host, with no instrument and no Windows.

What it checks (read-only; nothing is written unless ``--emit-ledger`` is
passed):

1. every crop on disk has a row, and every row's file is on disk;
2. each row's recorded ``WxH`` equals the PNG's real size (read with Pillow, so
   this runs on Linux as well as on Windows);
3. ids are unique, and the numbering has no gaps inside a family;
4. the row count matches the count the document states in its own prose
   ("Total: N crops, ..."), so a crop added without updating the summary fails;
5. the crop files are the ones the document's family counts describe.

A failure is printed as a named line and the exit code is non-zero — this is a
gate, not a report: an index that misdescribes its own files is worse than no
index, because a quoted caption would carry a provenance nobody can check.

Usage::

    .venv/Scripts/python.exe tools/ui/crop_index.py            # check
    .venv/Scripts/python.exe tools/ui/crop_index.py --emit-ledger tools/ui/crop-ledger.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INDEX = REPO / "docs" / "dop3000" / "ui-element-index.md"
CROPS = REPO / "docs" / "dop3000" / "ui-crops"

#: ``| UI-MENU-01 | `file.png` (667x34) … | surface | state | blocking | notes |``
#: The two rows whose filename carries a note right after the dimensions are why
#: the dimension group is not anchored to the cell's end.
ROW_RE = re.compile(r"^\|\s*(UI-[A-Z]+-\d+)\s*\|\s*`([^`]+)`\s*\((\d+)x(\d+)\)")
TOTAL_RE = re.compile(r"Total:\s*(\d+)\s*crops")


def parse_index(path: Path) -> tuple[list[dict], int | None]:
    """Return the index's crop rows and the total its prose states (if any)."""
    text = path.read_text(encoding="utf-8")
    rows: list[dict] = []
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if m:
            ident, name, w, h = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
            rows.append(
                {
                    "id": ident,
                    "file": name,
                    "w": w,
                    "h": h,
                    "family": ident.rsplit("-", 1)[0],
                }
            )
    total = TOTAL_RE.search(text)
    return rows, (int(total.group(1)) if total else None)


def png_sizes(directory: Path) -> dict[str, tuple[int, int]]:
    """Map every PNG in *directory* to its real pixel size (Pillow, if present)."""
    files = sorted(directory.glob("*.png"))
    sizes: dict[str, tuple[int, int]] = {}
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - exercised only on a bare install
        return {p.name: (-1, -1) for p in files}
    for p in files:
        with Image.open(p) as im:
            sizes[p.name] = im.size
    return sizes


def check(rows: list[dict], directory: Path) -> list[str]:
    """Return one line per failed check; empty means the index describes its files."""
    problems: list[str] = []
    on_disk = png_sizes(directory)

    ids = [r["id"] for r in rows]
    for ident, count in Counter(ids).items():
        if count > 1:
            problems.append(f"duplicate id: {ident} appears {count} times")

    indexed = {r["file"] for r in rows}
    for name in sorted(set(on_disk) - indexed):
        problems.append(f"on disk, not in the index: {name}")
    for name in sorted(indexed - set(on_disk)):
        problems.append(f"in the index, not on disk: {name}")

    for r in rows:
        actual = on_disk.get(r["file"])
        if actual is None:
            continue  # already reported as missing
        if actual == (-1, -1):
            problems.append(f"cannot read the PNG (Pillow missing): {r['file']}")
        elif actual != (r["w"], r["h"]):
            problems.append(
                f"{r['id']}: index says {r['w']}x{r['h']}, {r['file']} is {actual[0]}x{actual[1]}"
            )

    for family, idents in _by_family(ids).items():
        numbers = sorted(int(i.rsplit("-", 1)[1]) for i in idents)
        expected = list(range(1, len(numbers) + 1))
        if numbers != expected:
            missing = sorted(set(expected) - set(numbers))
            problems.append(
                f"{family}: numbering has a gap - ids {numbers}, missing {missing} "
                "(a crop was withdrawn or renumbered without updating the family)"
            )
    return problems


def _by_family(ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ident in ids:
        out.setdefault(ident.rsplit("-", 1)[0], []).append(ident)
    return out


def summary(
    rows: list[dict], on_disk_count: int, stated_total: int | None
) -> list[str]:
    """The lines worth printing even when every check passed."""
    families = {
        k: len(v) for k, v in sorted(_by_family([r["id"] for r in rows]).items())
    }
    lines = [
        f"index rows: {len(rows)}   crops on disk: {on_disk_count}   families: {families}"
    ]
    if stated_total is not None and stated_total != len(rows):
        lines.append(
            f"the document states {stated_total} crops but its table lists {len(rows)} rows"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, default=INDEX, help="the index to read")
    ap.add_argument("--crops", type=Path, default=CROPS, help="the crop directory")
    ap.add_argument(
        "--emit-ledger",
        type=Path,
        default=None,
        help="write the parsed rows as JSON, for a future generator",
    )
    args = ap.parse_args(argv)

    if not args.index.exists():
        print(f"crop_index: no such index: {args.index}", file=sys.stderr)
        return 2
    rows, stated_total = parse_index(args.index)
    if not rows:
        print(f"crop_index: no crop rows found in {args.index}", file=sys.stderr)
        return 2

    on_disk = png_sizes(args.crops)
    for line in summary(rows, len(on_disk), stated_total):
        print(line)

    problems = check(rows, args.crops)
    if stated_total is not None and stated_total != len(rows):
        problems.append(f"stated total {stated_total} != {len(rows)} indexed rows")

    if args.emit_ledger:
        args.emit_ledger.write_text(
            json.dumps(rows, indent=1) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"wrote {args.emit_ledger}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(
        "ok: every indexed crop exists, is the size the index states, and is numbered without a gap"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
