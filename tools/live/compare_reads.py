"""Compare two or more dispatched reads of the same application — the deltas §23 is made of.

**Why an offline tool next to the probes.** A probe answers "what is there *now*"; the questions §21–§23
ask are all "what changed, and what did *not*": whether the strip's rect survived a second read, whether
a tree that grew 155 → 165 moved anything visible, whether the dialog's cells are the same cells in both
modes. Those are differences between reads, and this tool is the arithmetic — straight from the JSON the
probes wrote, in session 0, with no application present.

**What it reads.** Either a probe's own JSON (`outputs/live/main-geometry.json`, `-run1.json`, …) or a
dispatch **log**, from which it recovers the single JSON object the probe printed
(`outputs/live/nonsim-run.log`, a `dialog_fields` log). The log form is deliberate: `dispatch.sh` prints
the probe's stdout, so an overwritten path is recoverable from the log that printed it — which is how the
§22.2 instrument read was recovered after a later run overwrote `main-geometry.json`.

**Two shapes, told apart by their top level.** A *geometry* read (`main_geometry.py`) has `main_window`,
`fingerprint`, `tree`; a *dialog* read (`dialog_fields.py`) has `opened`, `dialog`, `controls`. The
report each shape gets:

    geometry:  caption, window rect, visible controls, panels, tree size, the strip's rect and row,
               then the tree delta against the first read (added / removed / moved, by hwnd)
    dialog:    the dialog's rect and control count, then a per-cell table — rect, class, text — with
               the earlier read's value beside each cell of the later one

**What it cannot tell you.** A tree delta is *not* an error: the application builds controls on first
show, so a session that has been used has more of them than one that has not (§21.3 item 1, §23.2). And
two reads of *different processes* share no handles, so every row reads as added and removed — compare
reads of one process only, which is what the caption and the `hwnd` are for.

Usage:

    python tools/live/compare_reads.py outputs/live/main-geometry-run1.json outputs/live/main-geometry-run2.json
    python tools/live/compare_reads.py outputs/live/nonsim-run.log outputs/live/main-geometry-run1.json
    python tools/live/compare_reads.py outputs/live/dialog-fields.json outputs/live/dialog-fields-nonsim.log
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter


def load(path: str) -> dict:
    """The JSON one dispatched read left — in its own file, or printed into a dispatch log."""
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        first, last = text.index("{"), text.rindex("}")
        return json.loads(text[first : last + 1])


def shape(doc: dict) -> str:
    if "main_window" in doc:
        return "geometry"
    if "controls" in doc or "dialog" in doc:
        return "dialog"
    raise SystemExit(f"unrecognised read: top-level keys {sorted(doc)[:6]}")


def tree_rows(doc: dict) -> dict:
    """A tree keyed by handle: the only key two reads of one process share."""
    return {row["hwnd"]: row for row in doc.get("tree", []) if "hwnd" in row}


def report_geometry(path: str, doc: dict, base: dict | None) -> None:
    window = doc["main_window"]
    strip = doc.get("strip") or {}
    rows = tree_rows(doc)
    print(f"{path}")
    print(
        f"  window   {window['cls']} caption={window['caption']!r} rect={window['rect']} "
        f"zoomed={window['maximized']} foreground={window['foreground']}"
    )
    print(
        f"  screen   visible_controls={doc.get('visible_controls')} "
        f"panels={doc['fingerprint']['panels']} tree={len(rows)} dpi={doc['dpi']['system_dpi']}"
    )
    print(f"  strip    rect={strip.get('panel_rect')} id={strip.get('panel_id')} "
          f"view={strip.get('view')} buttons={strip.get('button_count')} slider={strip.get('has_slider')}")
    print(f"  strip row {[c['rect'] for c in strip.get('row', [])]}")
    print(f"           meanings {strip.get('row_meanings')}")
    print(f"  layout_note {doc.get('layout_note')!r}")
    if base is None:
        return
    other = tree_rows(base)
    added, gone = sorted(set(rows) - set(other)), sorted(set(other) - set(rows))
    moved = sorted(
        h for h in set(rows) & set(other) if rows[h]["rect"] != other[h]["rect"]
    )
    print(
        f"  tree delta vs the first read: +{len(added)} / -{len(gone)} / moved {len(moved)}"
        f" of {len(other)} common"
    )
    for tag, handles, table in (("+", added, rows), ("-", gone, other), ("~", moved, rows)):
        for handle in handles[:12]:
            row = table[handle]
            print(
                f"    {tag} {row['cls']:<18} rect={row['rect']} vis={row['visible']} "
                f"parent={row['parent']} text={row.get('text')!r}"
            )
    hist = Counter(row["cls"] for row in rows.values())
    print(f"  classes  {dict(sorted(hist.items()))}")


def report_dialog(path: str, doc: dict, base: dict | None) -> None:
    dialog = doc.get("dialog") or {}
    print(f"{path}")
    print(
        f"  opened={doc.get('opened')} controls={doc.get('control_count')} "
        f"closed={doc.get('dialog_closed')} rect={dialog.get('rect')} hwnd={dialog.get('hwnd')}"
    )
    if doc.get("error"):
        print(f"  error {doc['error']}")
    if doc.get("stranded"):
        print(f"  STRANDED {doc['stranded']}")
    cells = {tuple(c["rect"]): c for c in doc.get("controls", []) if c.get("rect")}
    was = {}
    if base is not None:
        was = {tuple(c["rect"]): c for c in base.get("controls", []) if c.get("rect")}
    print("  cells (rect, class, text) — with the earlier read's text beside the later one:")
    for rect in sorted(cells, key=lambda r: (r[1], r[0])):
        cell = cells[rect]
        before = was.get(rect)
        changed = "  <-- changed" if before is not None and before.get("text") != cell.get("text") else ""
        print(
            f"    {list(rect)!s:<28} {cell['cls']:<18} vis={cell['visible']!s:<5} "
            f"text={cell.get('text')!r}"
            f"{'' if before is None else '   was ' + repr(before.get('text'))}"
            f"{changed}"
        )
    only_here = sorted(set(cells) - set(was)) if was else []
    only_there = sorted(set(was) - set(cells)) if was else []
    if was and only_here:
        print(f"  cells only in the later read: {[list(r) for r in only_here]}")
    if was and only_there:
        print(f"  cells only in the earlier read: {[list(r) for r in only_there]}")


def main(argv: list[str]) -> int:
    if not argv:
        raise SystemExit(__doc__.split("Usage:")[1].strip())
    docs = [(path, load(path)) for path in argv]
    kinds = {shape(doc) for _, doc in docs}
    if len(kinds) != 1:
        raise SystemExit(f"mixed read shapes: {sorted(kinds)} — compare like with like")
    base = docs[0][1]
    for path, doc in docs:
        if shape(doc) == "geometry":
            report_geometry(path, doc, None if doc is base else base)
        else:
            report_dialog(path, doc, None if doc is base else base)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
