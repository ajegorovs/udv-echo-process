"""Write **one** ``Operating parameters`` dialog knob, commit it, and read the round trip back.

**Why this exists next to** :mod:`tools.live.probes.dialog_fields` and :mod:`…dialog_shot`. Those
two are the read half of §18's identification pass: one walks every control of the dialog and
prints it, the other photographs it so its painted labels can be read. This is the first probe in
this repository that *changes* the instrument through the dialog, and it exists to measure the
transaction §19.1 describes rather than to trust it:

1. **baseline** — open ``Parameters → Operating parameters`` through the driver's *existing*
   gesture, walk every control (visible and hidden), read the dialog's value table by ``(column,
   row)`` geometry, photograph the dialog's own rect and the whole screen, close with the dialog's
   **left** button (``Cancel``). Nothing is written;
2. **write** — open it again, bind the requested knob's cell **by geometry**, select the entry whose
   own text equals the requested value (``CB_SETCURSEL`` + ``CBN_SELCHANGE``, no Enter — the
   archive's combo recipe), re-read the cell and the whole table, then commit with the bottom band's
   **rightmost** button (``Accept``). Re-open, dump and photograph again;
3. **compare** — diff two dumps control by control and cell by cell, so "the dialog came back to its
   baseline" is a measurement rather than an impression.

**What it refuses, and why that is the point.** §19.1's write is a transaction: a value the combo
does not offer refuses the write instead of proceeding, and a **modal warning is not pressed
through**. This probe never presses a modal's rightmost button (*Continue*), never walks the
``Parameters`` popup down to the second entry (``Default parameters`` selects the assisted mode and
rebuilds the screen), and never touches the dialog's header combo — the **channel** selector, whose
write makes the application *replace* the dialog and kill every handle taken before it (measured,
§19.4). A single-button warning is left standing and the experiment stops: its only button is
*Continue*, which is an answer this probe does not have. Everything else is closed with the safe end
of its own button pair, so a refusal leaves the application as it was found.

**The verify rungs it can reach, and the one it cannot.** §19.1 orders the read-backs: (1) the field
states what was written; (2) after ``Accept``, a re-opened dialog agrees; (3) the stored ``.BDD``'s
word. This probe reaches **1 and 2**. Rung 3 is deliberately out of scope: it needs a real recording
on the channel, and this is a dialog round trip. The report says so rather than implying more.

**Where the machinery comes from.** The dialog gesture, the reader and the writers are the driver's
own private steps (:meth:`…driver.Win32Actuator._open_parameters_dialog`, ``_poll_dialog_fields``,
``_combo_select``, ``_dialog_button``) — never a reimplementation, so this probe cannot drift from
the code it is measured for. The control walk is :func:`tools.live.probes.dialog_fields.walk` and
the capture is :mod:`tools.live.probes.dialog_shot`'s, imported rather than copied: two pictures of
the same dialog taken by two different routines are two opinions.

**How it is run — and the one trap on that path.** Bare probe name, never a repo-relative path
(``task_run.py`` joins the argument onto the probes directory and a path finds nothing, silently —
§18.8's harness trap)::

    PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py dump --out outputs/live/x.json
    PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_write.py write --burst 2 --out outputs/live/y.json
    ./tools/live/dispatch.sh dialog_write.py compare --baseline outputs/live/x.json --after outputs/live/y.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

# The two sibling probes, imported and not copied: the walk is `dialog_fields`'s and the capture is
# `dialog_shot`'s, so this probe photographs and inventories the dialog exactly as the read pass
# does. Both live in this directory, which is on ``sys.path`` because it is the script's own.
import dialog_fields as probe_fields
import dialog_shot as probe_shot
import win32gui

from udv_echo_process.acquire import driver

#: Where the pictures go: ``outputs/`` is gitignored, and large binaries belong there.
OUT = REPO / "outputs" / "live"

#: The cells this experiment writes, as ``(column, row)`` of the dialog's value table (§18.6). The
#: binding is **geometry and never value**, and never "the first combo in the dialog": the first
#: ``TComboBox`` of this dialog is its header **channel** selector, and writing that one makes the
#: application replace the dialog (§19.4). The cell's own class is asserted before anything is
#: selected, so a dialog whose shape moved refuses rather than writes a different knob.
BURST_CELL = (0, 1)
SAMPLING_VOLUME_CELL = (1, 4)

#: The class each of those cells holds, per §18.6.
BURST_CLASS = "TComboBox"
SAMPLING_VOLUME_CLASS = "TComboBox"

#: A settle after a write before the read-back that follows it. `_combo_select`'s own
#: `_COMBO_SETTLE_S` (0.8 s) is the reference's, and the coupling between burst and the sampling
#: volume is the application computing something, so the read-back is taken after it.
SETTLE_S = 0.8


class Refused(RuntimeError):
    """A write this probe will not make, with the reason stated in full."""


def cell(fields, column: int, row: int, expect: str) -> dict:
    """The value table's ``(column, row)`` cell, asserted to hold the class it should.

    A missing cell means the table is not the measured one; a cell holding another class means the
    dialog's shape moved. Both are refusals, because the alternative is selecting an entry in a
    control that is not the knob whose cell this is — which is the trap the header channel combo
    sets (§19.4).
    """
    match = next(
        (row_ for row_ in fields if int(row_["column"]) == column and int(row_["row"]) == row),
        None,
    )
    if match is None:
        raise Refused(
            f"the dialog states no value cell at (column {column}, row {row}): the table it built "
            f"is {[(int(f['column']), int(f['row']), f['cls']) for f in fields]}"
        )
    if match["cls"] != expect:
        raise Refused(
            f"the value cell at (column {column}, row {row}) holds a {match['cls']!r}, not the "
            f"{expect!r} this knob's value lives in: nothing is written — the cell is bound by "
            "geometry, and a table whose classes moved is not the table these bindings were "
            "measured against"
        )
    return match


def read_table(actuator: driver.Win32Actuator, panel: dict) -> list[dict]:
    """The dialog's value table, with every combo cell's own selection and option list."""
    rows: list[dict] = []
    for field in actuator._poll_dialog_fields(panel):
        row: dict[str, object] = {
            "column": field["column"],
            "row": field["row"],
            "cls": field["cls"],
            "hwnd": field["hwnd"],
            "value": field["value"],
        }
        if field["cls"] == "TComboBox":
            row["combo_index"] = actuator._combo_index(field["hwnd"])
            row["combo_items"] = list(actuator._combo_items(field["hwnd"]))
        rows.append(row)
    return rows


def value_at(fields, column: int, row: int) -> dict:
    """One cell's current read: its own text, and its selection if it is a combo."""
    fields = fields or []
    match = next(
        (
            entry
            for entry in fields
            if int(entry["column"]) == column and int(entry["row"]) == row
        ),
        None,
    )
    if match is None:
        return {"cell": [column, row], "missing": True}
    return {
        "cell": [column, row],
        "cls": match["cls"],
        "value": match["value"],
        "combo_index": match.get("combo_index"),
        "combo_items": match.get("combo_items"),
    }


def capture(actuator: driver.Win32Actuator, panel: dict, stem: Path) -> dict:
    """One settled frame of the whole screen, the dialog cropped out of it, and both as PNGs.

    The same three checks ``dialog_shot`` makes, for the same reasons: two full-screen grabs are
    compared so a torn frame is *reported*, the crop's rect is read live, and every image carries
    its own blank check — a flat PNG is worse than a failed capture because it looks like a
    successful one down every later step.
    """
    rect = list(win32gui.GetWindowRect(panel["hwnd"]))
    time.sleep(probe_shot.SETTLE_S)
    first, route = probe_shot.grab_screen()
    time.sleep(0.15)
    second, _ = probe_shot.grab_screen()
    stable = first.tobytes() == second.tobytes()
    dpi = probe_shot.dpi_facts()
    origin_x, origin_y = dpi["virtual_screen_origin"]
    box = (rect[0] - origin_x, rect[1] - origin_y, rect[2] - origin_x, rect[3] - origin_y)
    safe_box = (
        max(0, box[0]),
        max(0, box[1]),
        min(second.width, box[2]),
        min(second.height, box[3]),
    )
    dialog_png = stem.with_name(stem.name + ".png")
    full_png = stem.with_name(stem.name + "-full.png")
    return {
        "route": route,
        "settle_s": probe_shot.SETTLE_S,
        "frame_stable": stable,
        "rect": rect,
        "crop_box": list(box),
        "crop_box_clamped": box != safe_box,
        "covering": probe_shot.covering_check(panel["hwnd"], rect),
        "dpi": dpi,
        "images": {
            "dialog": probe_shot.save(second.crop(safe_box), dialog_png),
            "full": probe_shot.save(second, full_png),
        },
    }


def modal_state(actuator: driver.Win32Actuator) -> dict | None:
    """What overlay is up, if any — the one check that must run before the next press.

    This application raises its warnings as modal panels, and a modal owns the input: a press
    posted past it can land on the wrong surface (the reason §18.4 makes "nothing modal is ever left
    open while a probe runs" a rule). The report names the panel, its rect and the classes of its
    children, because a warning on this instrument is recognised by structure, not by caption.
    """
    found = actuator._find_overlay()
    if found is None:
        return None
    kind, panel, kids = found
    return {
        "kind": kind.value,
        "rect": panel["rect"],
        "children": [k["cls"] for k in kids],
        "buttons": [[b["rect"], b["hwnd"]] for b in driver._bottom_row(panel, kids)],
    }


def dismiss_modal(actuator: driver.Win32Actuator, report: dict) -> dict:
    """Answer a warning the way this driver answers every warning: its **leftmost** button.

    With two or more buttons that is ``Cancel`` (or ``No`` on an overwrite question) — the safe end,
    and the rightmost is never pressed. With **one** button the only answer on offer is *Continue*,
    which is a decision this experiment does not have: nothing is pressed, the experiment stops, and
    the report says the operator has to clear it.
    """
    state = modal_state(actuator)
    if state is None:
        return {"modal": "none"}
    buttons = state.get("buttons") or []
    if len(buttons) < 2:
        state["action"] = (
            "not pressed: this warning offers "
            f"{len(buttons)} button(s), and a single-button warning's only button is Continue — "
            "answering it is a decision this experiment does not have. Nothing behind it was "
            "touched either, because a modal owns the input"
        )
        report["modal"] = state
        return state
    found = actuator._find_overlay()
    _kind, panel, kids = found
    actuator._dialog_button(panel, kids, driver.DialogControl.SAFE)
    time.sleep(SETTLE_S)
    state["action"] = (
        "leftmost button pressed (Cancel/No — the safe end; the rightmost was never pressed)"
    )
    state["still_up"] = bool(win32gui.IsWindowVisible(panel["hwnd"]))
    report["modal"] = state
    return state


def open_dialog(actuator: driver.Win32Actuator, report: dict) -> dict | None:
    """The driver's own open gesture, with its refusal recorded rather than raised."""
    state = modal_state(actuator)
    if state is not None:
        report["opened"] = False
        report["error"] = (
            "a modal panel is up before the dialog was asked for, and this probe presses nothing "
            f"through one: {state}"
        )
        return None
    try:
        return actuator._open_parameters_dialog()
    except driver.AcquisitionError as exc:
        report["opened"] = False
        report["error"] = str(exc)
        return None


def close_dialog(actuator: driver.Win32Actuator, panel: dict, report: dict) -> None:
    """Close with the dialog's **left** button and say whether it went away.

    Never ``Accept``: on a parameters dialog that button *commits* whatever the dialog holds, so it
    is the one thing a read must not press. A dialog still visible afterwards is reported as
    ``stranded`` — the operator restarts the application, and that is the only documented exit.
    """
    actuator._close_parameters_dialog(panel)
    try:
        still_up = bool(win32gui.IsWindowVisible(panel["hwnd"]))
    except win32gui.error:
        still_up = False
    report["dialog_closed"] = not still_up
    if still_up:
        report["stranded"] = (
            "the dialog is still visible after its left button was pressed — the operator has to "
            "restart the application; this probe stops here and pokes nothing further"
        )


def dump_state(actuator: driver.Win32Actuator, panel: dict) -> dict:
    """Everything this probe believes about one open dialog: the walk, the table, the captures."""
    state: dict[str, object] = {"dialog": {k: v for k, v in panel.items() if k != "raw"}}
    controls = probe_fields.walk(panel["hwnd"], actuator._get_text)
    state["control_count"] = len(controls)
    state["controls"] = controls
    state["table"] = read_table(actuator, panel)
    return state


def emit(report: dict, out: Path | None, started: float) -> None:
    """Stamp the elapsed time, write the JSON where asked, and print it — the probe's output."""
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    body = json.dumps(report, indent=2, default=str)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body + "\n", encoding="utf-8")
        report["written"] = str(out)
    print(body)


def shot_stem(args: argparse.Namespace) -> Path:
    """Where the two PNGs go: ``--shot`` if given, otherwise named after the JSON dump.

    Absolute on purpose: the probe runs with its working directory set to the probes directory, so
    a relative path here would land beside the source instead of in ``outputs/live/``.
    """
    stem = Path(getattr(args, "shot", None) or Path(args.out).with_suffix(""))
    return stem if stem.is_absolute() else REPO / stem


def output_path(args: argparse.Namespace) -> Path:
    """``--out`` as an absolute path, for the same working-directory reason as :func:`shot_stem`."""
    path = Path(args.out)
    return path if path.is_absolute() else REPO / path


def run_dump(actuator: driver.Win32Actuator, args: argparse.Namespace, started: float) -> int:
    """The baseline/verify mode: read the dialog, photograph it, close it. Writes nothing."""
    report: dict[str, object] = {"probe": "dialog_write", "mode": "dump", "writes": False}
    panel = open_dialog(actuator, report)
    if panel is None:
        emit(report, output_path(args), started)
        return 2
    report["opened"] = True
    try:
        report.update(dump_state(actuator, panel))
        report["capture"] = capture(actuator, panel, shot_stem(args))
    finally:
        close_dialog(actuator, panel, report)
    report["driver_notes"] = list(actuator.warnings)
    images = (report.get("capture") or {}).get("images") or {}
    report["non_blank"] = all(row["non_blank"] for row in images.values()) if images else False
    emit(report, output_path(args), started)
    if report.get("stranded"):
        return 3
    return 0 if report["non_blank"] else 4


def select_by_value(actuator: driver.Win32Actuator, combo: dict, wanted: str) -> int:
    """Select the entry whose **own text** equals ``wanted``; refuse a value the combo does not offer.

    Selection is by the option's value and never by counting steps: on this machine one step up from
    burst ``4`` landed on ``6`` because the entries are not contiguous (§18.6), and a count-based
    writer would silently write a different burst. A value the list does not hold is exactly the
    "a wrong write refuses the point" case §19.1's acceptance calls for.
    """
    items = actuator._combo_items(combo["hwnd"])
    match = next((i for i, item in enumerate(items) if item.strip() == wanted.strip()), None)
    if match is None:
        raise Refused(
            f"the combo at the cell holds {list(items)} and none of them is {wanted!r}: nothing is "
            "selected — a value the control does not offer is a wrong write, not a near miss"
        )
    actuator._combo_select(combo["hwnd"], match, win32gui.GetParent(combo["hwnd"]))
    time.sleep(SETTLE_S)
    return match


def run_write(actuator: driver.Win32Actuator, args: argparse.Namespace, started: float) -> int:
    """The write mode: one or two combo cells, ``Accept``, then the re-opened dialog read back."""
    report: dict[str, object] = {
        "probe": "dialog_write",
        "mode": "write",
        "requested": {"burst": args.burst, "sampling_volume": args.volume},
    }
    panel = open_dialog(actuator, report)
    if panel is None:
        emit(report, output_path(args), started)
        return 2
    report["opened"] = True
    accepted = False
    try:
        # --- 1. the pre-write state, and the two cells bound by geometry ----------------
        pre_table = read_table(actuator, panel)
        report["pre"] = {
            "table": pre_table,
            "burst": value_at(pre_table, *BURST_CELL),
            "sampling_volume": value_at(pre_table, *SAMPLING_VOLUME_CELL),
        }
        burst = cell(pre_table, *BURST_CELL, BURST_CLASS)
        volume = cell(pre_table, *SAMPLING_VOLUME_CELL, SAMPLING_VOLUME_CLASS)

        # --- 2. the burst write, then the whole table again ---------------------------
        report["burst_index"] = select_by_value(actuator, burst, args.burst)
        after_burst_table = read_table(actuator, panel)
        report["after_burst_write"] = {
            "burst": value_at(after_burst_table, *BURST_CELL),
            "sampling_volume": value_at(after_burst_table, *SAMPLING_VOLUME_CELL),
            "table": after_burst_table,
            "note": (
                "read in the SAME dialog, before Accept: the coupled sampling volume moving here is "
                "the application's own reaction to the burst notification (§19.2), which is the "
                "only same-dialog evidence that the message reached the model rather than only the "
                "control"
            ),
        }
        if modal_state(actuator) is not None:
            dismiss_modal(actuator, report)
            report["stopped"] = "a modal appeared after the burst write; nothing was accepted"
            close_dialog(actuator, panel, report)
            report["driver_notes"] = list(actuator.warnings)
            emit(report, output_path(args), started)
            return 1

        # --- 3. the coupled knob, only when the restore needs it ----------------------
        if args.volume is not None:
            report["volume_index"] = select_by_value(actuator, volume, args.volume)
            after_volume_table = read_table(actuator, panel)
            report["after_volume_write"] = {
                "burst": value_at(after_volume_table, *BURST_CELL),
                "sampling_volume": value_at(after_volume_table, *SAMPLING_VOLUME_CELL),
                "table": after_volume_table,
            }
            if modal_state(actuator) is not None:
                dismiss_modal(actuator, report)
                report["stopped"] = "a modal appeared after the sampling-volume write; nothing accepted"
                close_dialog(actuator, panel, report)
                report["driver_notes"] = list(actuator.warnings)
                emit(report, output_path(args), started)
                return 1

        # --- 4. commit: the bottom band's RIGHTMOST button ----------------------------
        kids = actuator._children_of(panel["hwnd"], actuator._resolve())
        target = actuator._dialog_button(panel, kids, driver.DialogControl.CONFIRM)
        report["accept"] = {"rect": target["rect"], "hwnd": target["hwnd"]}
        time.sleep(SETTLE_S)
        try:
            accepted = not bool(win32gui.IsWindowVisible(panel["hwnd"]))
        except win32gui.error:
            accepted = True
        report["accepted"] = accepted
        if modal_state(actuator) is not None:
            dismiss_modal(actuator, report)
        if not accepted:
            # The dialog is still up after Accept. Cancelling it discards the pending write, which
            # is the outcome that leaves the instrument as it was found — and a write that was not
            # taken is a measurement, not something to force.
            report["note"] = "the dialog survived its Accept press; it is cancelled, so nothing stays pending"
            close_dialog(actuator, panel, report)
            report["driver_notes"] = list(actuator.warnings)
            emit(report, output_path(args), started)
            return 1
    finally:
        if not accepted:
            try:
                if win32gui.IsWindowVisible(panel["hwnd"]):
                    close_dialog(actuator, panel, report)
            except win32gui.error:
                pass

    # --- 5. the re-opened dialog: rung 2 of §19.1's verify ladder ---------------------
    panel2 = open_dialog(actuator, report)
    if panel2 is None:
        report["error_after_accept"] = report.get("error")
        report["driver_notes"] = list(actuator.warnings)
        emit(report, output_path(args), started)
        return 1
    try:
        report["post"] = dump_state(actuator, panel2)
        report["capture"] = capture(actuator, panel2, shot_stem(args))
    finally:
        close_dialog(actuator, panel2, report)
    report["post"]["burst"] = value_at(report["post"]["table"], *BURST_CELL)
    report["post"]["sampling_volume"] = value_at(report["post"]["table"], *SAMPLING_VOLUME_CELL)
    report["driver_notes"] = list(actuator.warnings)
    images = (report.get("capture") or {}).get("images") or {}
    report["non_blank"] = all(row["non_blank"] for row in images.values()) if images else False
    emit(report, output_path(args), started)
    if report.get("stranded"):
        return 3
    return 0


def state_of(record: dict) -> dict:
    """The dialog state a dump holds, whichever way it was produced.

    A ``dump`` writes its inventory at the top level; a ``write`` report carries the *re-opened*
    dialog's inventory under ``post`` (the pre-write and post-write-but-in-dialog tables are the
    report's other evidence, not a state to compare from). Reading the state the record's own
    producer wrote is what keeps the comparison honest about which moment it is diffing.
    """
    if "controls" in record or "table" in record:
        return record
    post = record.get("post")
    return post if isinstance(post, dict) else record


def load(path: str) -> dict:
    """One dump, read back from the JSON the probe wrote — the comparison's two sides."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def control_keys(state: dict) -> list[list]:
    """One control per row, as ``[depth, cls, rect, text, visible]`` — hwnd is per-launch, never an id.

    The handles in these dumps are fresh on every launch (1 of 43 control ids survives a relaunch),
    so a comparison that keyed on them could only ever report "everything changed".
    """
    return [
        [c.get("depth"), c.get("cls"), c.get("rect"), c.get("text"), c.get("visible")]
        for c in state.get("controls", [])
    ]


def table_keys(state: dict) -> list[list]:
    """The dialog's value table as ``[column, row, cls, value]`` rows — the state that matters."""
    return [
        [f.get("column"), f.get("row"), f.get("cls"), f.get("value")]
        for f in state.get("table", [])
    ]


def sorted_rows(rows: list[list]) -> list[list]:
    """A shape-independent order, so a re-enumeration is not reported as a value change."""
    return sorted(rows, key=lambda row: json.dumps(row, default=str))


def run_compare(args: argparse.Namespace, started: float) -> int:
    """Diff two dumps: every control, then every cell, then the values the experiment cares about."""
    report: dict[str, object] = {
        "probe": "dialog_write",
        "mode": "compare",
        "baseline": args.baseline,
        "after": args.after,
    }
    baseline, after = state_of(load(args.baseline)), state_of(load(args.after))
    report["compared"] = {
        "baseline": f"{args.baseline} (state at {baseline.get('dialog', {}).get('rect')})",
        "after": f"{args.after} (state at {after.get('dialog', {}).get('rect')})",
    }
    left, right = control_keys(baseline), control_keys(after)
    report["control_counts"] = [len(left), len(right)]
    report["controls_identical_in_order"] = left == right
    report["controls_identical_as_a_set"] = sorted_rows(left) == sorted_rows(right)
    if not report["controls_identical_as_a_set"]:
        only_left = [row for row in left if row not in right]
        only_right = [row for row in right if row not in left]
        report["controls_only_in_baseline"] = only_left
        report["controls_only_in_after"] = only_right
    table_left, table_right = sorted_rows(table_keys(baseline)), sorted_rows(table_keys(after))
    report["table_identical"] = table_left == table_right
    report["table_baseline"] = table_left
    report["table_after"] = table_right
    if not report["table_identical"]:
        by_cell = {(row[0], row[1]): row for row in table_right}
        report["table_changed"] = [
            {
                "cell": [row[0], row[1]],
                "cls": row[2],
                "baseline": row[3],
                "after": (by_cell.get((row[0], row[1])) or [None, None, None, None])[3],
            }
            for row in table_left
            if by_cell.get((row[0], row[1])) != row
        ]
    report["identical"] = bool(
        report["controls_identical_as_a_set"] and report["table_identical"]
    )
    emit(report, output_path(args) if getattr(args, "out", None) else None, started)
    return 0 if report["identical"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write one Operating parameters knob and read it back")
    sub = parser.add_subparsers(dest="mode", required=True)

    dump = sub.add_parser("dump", help="read-only: inventory + photograph one dialog")
    dump.add_argument("--out", required=True, help="where the JSON dump is written")
    dump.add_argument("--shot", help="PNG stem (default: the --out stem)")

    write = sub.add_parser("write", help="select combo cell(s), Accept, re-open and read back")
    write.add_argument("--burst", required=True, help="the burst-length value to select")
    write.add_argument("--volume", help="optionally set the sampling volume to this value too")
    write.add_argument("--out", required=True, help="where the JSON report is written")
    write.add_argument("--shot", help="PNG stem (default: the --out stem)")

    compare = sub.add_parser("compare", help="diff two dumps, control by control and cell by cell")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--after", required=True)
    compare.add_argument("--out", help="where the JSON comparison is written")

    args = parser.parse_args(argv)
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)

    if args.mode == "compare":
        return run_compare(args, started)

    actuator = driver.Win32Actuator()
    try:
        if args.mode == "dump":
            return run_dump(actuator, args, started)
        return run_write(actuator, args, started)
    except Refused as exc:
        # A refused write is the designed outcome for a value the control does not offer: the JSON
        # is still the report, so a caller reads the refusal rather than an empty log.
        emit(
            {
                "probe": "dialog_write",
                "mode": args.mode,
                "opened": True,
                "refused": str(exc),
                "driver_notes": list(actuator.warnings),
            },
            output_path(args),
            started,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
