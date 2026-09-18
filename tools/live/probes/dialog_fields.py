"""Fast, read-only: dump every control of the ``Operating parameters`` dialog.

**Why this exists next to** :mod:`tools.live.probes.w1_fixed_facts`. That probe answers a
different question — where the dialog-only fixed facts and the cap are stated on the live
application — and to do so it hovers the ``Parameters`` menubar popup (a gesture that opens a
popup neither a cursor restore nor a posted ``WM_CANCELMODE`` closes), dumps the main window's
whole tree twice around a settle sleep, and prints its JSON only at the very end. Whatever it
costs, it is not a read an operator can be asked to hold a field still for, and the knob it is
being asked about is identified by re-reading the dialog. So this probe does **one thing**:

1. open ``Parameters → Operating parameters`` through the driver's *existing* gesture —
   :meth:`~udv_echo_process.acquire.driver.Win32Actuator._open_parameters_dialog`, the real-cursor
   hover of the menubar button plus the posted held press on the **topmost** entry, with the same
   refusals (a popup already open, wrong dialog, assisted mode switched on) — never a
   reimplementation of that path;
2. walk **every** descendant of the dialog's panel, visible *and* hidden, and read each control's
   own text with the driver's own reader (``WM_GETTEXT``, ``driver.Win32Actuator._get_text``).
   ``win32gui.GetWindowText`` is **not** used: it does not retrieve text from a control in another
   process, which is why a first run of ``w1_fixed_facts`` saw empty captions everywhere
   (measured 2026-09-18);
3. close it with the dialog's **left** button, exactly as the driver does
   (:meth:`…Win32Actuator._close_parameters_dialog` → ``DialogControl.SAFE``), never a window
   close and never its default button, which on a parameters dialog is what would commit whatever
   it holds.

Nothing is written, nothing is pressed but the topmost popup entry and that left button, and no
value is changed anywhere: the dump is the whole point, so it is one JSON object on stdout.

**No recovery, by policy.** If the dialog will not open, the driver's own refusal is printed as
JSON (``error``) and the exit code is non-zero — the probe does not retry in a loop and does not
walk down the popup (the second entry is ``Default parameters`` and selects the assisted mode).
If the dialog is still visible after the close press, that is reported as ``stranded`` and the
probe stops there: a stranded popup or dialog means the operator restarts the application, and
that is the only documented exit (``w1_fixed_facts``'s own notes, 2026-09-18).

The dump is bound to nothing. Which control is which is decided downstream, by class, by position
in the dialog and by the value a control reads back — this application's widgets are caption-less
and ``Operating parameters`` identifies its fields structurally, never by a caption.

**How it is run — and the one trap on that path.** The probe is named to the dispatcher the way
:mod:`tools.live.task_run` resolves it: as a file **under ``tools/live/probes``**, so

    ./tools/live/dispatch.sh dialog_fields.py > outputs/live/dialog-fields.json 2>&1

A *repo-relative* path (``tools/live/probes/dialog_fields.py``) is the trap: ``task_run.py`` joins
it onto the probes directory, finds no such file, prints ``no such probe`` to a ``pythonw`` process
that has no console, and returns **without writing a log at all** — so the dispatcher polls for a
line that can never appear and reports a wedged probe. That is what
``outputs/live/w1-baseline.json`` records (191 bytes, "no exit line after 600s", no log), and the
first attempt at this probe paid the same 150 s for it (measured 2026-09-18). The probe itself then
ran in **2.5 s**.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

import win32gui

from udv_echo_process.acquire import driver

#: How deep the walk goes: the dialog nests a value's edit *inside* its value button, and a
#: button's own children one level further down still belong to the field.
MAX_DEPTH = 6


def walk(hwnd: int, read_text, depth: int = 0) -> list[dict]:
    """Every descendant of ``hwnd`` — visible or not — with its class, rect and own text.

    Depth-first, pre-order, so a parent is always the entry immediately above its own children and
    the order on screen is the order in the list. A control that dies mid-walk is recorded as an
    ``error`` row rather than failing the dump: a partial inventory is what an identification pass
    can still use, and the reader never raises on a vanished handle.
    """
    rows: list[dict] = []
    if depth > MAX_DEPTH:
        return rows
    child = win32gui.GetWindow(hwnd, 5)  # GW_CHILD
    while child:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(child)
            rows.append(
                {
                    "depth": depth,
                    "hwnd": child,
                    "cls": win32gui.GetClassName(child),
                    "text": read_text(child),
                    "rect": [left, top, right, bottom],
                    "visible": bool(win32gui.IsWindowVisible(child)),
                }
            )
        except win32gui.error as exc:  # a vanished control is a row, not a failed run
            rows.append({"depth": depth, "hwnd": child, "error": repr(exc)})
        rows.extend(walk(child, read_text, depth + 1))
        child = win32gui.GetWindow(child, 2)  # GW_HWNDNEXT
    return rows


def emit(report: dict, started: float) -> None:
    """Stamp the elapsed time and print the report once — the probe's whole output."""
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, indent=2, default=str))


def main() -> int:
    started = time.monotonic()
    report: dict[str, object] = {"probe": "dialog_fields"}

    actuator = driver.Win32Actuator()
    text = actuator._get_text

    # --- 1. the dialog, opened through the driver's own gesture --------------------------
    try:
        panel = actuator._open_parameters_dialog()
    except driver.AcquisitionError as exc:
        # The driver's refusal, verbatim: it already names what was asked for and what the
        # application showed (a popup left open, no entry, a dialog without the channel combo,
        # the real-cursor step refused). Nothing here retries it and nothing recovers it.
        report["opened"] = False
        report["error"] = str(exc)
        emit(report, started)
        return 2

    report["opened"] = True
    # The driver's own row for the panel, minus the resolver's raw list: the dialog's identity as
    # this driver resolved it, not a second opinion assembled here.
    report["dialog"] = {k: v for k, v in panel.items() if k != "raw"}

    # --- 2. every control, then the left button — the close is not optional --------------
    try:
        try:
            controls = walk(panel["hwnd"], text)
        except (win32gui.error, OSError) as exc:
            # A failed walk is still an answer — the dialog is dumped as far as it was walked —
            # and the close below is what matters more than the dump.
            controls = []
            report["walk_error"] = repr(exc)
        report["control_count"] = len(controls)
        report["controls"] = controls
    finally:
        # A dialog is not recoverable by the operator — Escape closes nothing in this
        # application — so a dump that raises still has to put the dialog back the way it found
        # it. `_close_parameters_dialog` presses the bottom row's left button and notes, rather
        # than raises, a panel whose button cannot be resolved: cleanup never masks the dump.
        actuator._close_parameters_dialog(panel)
        try:
            still_up = bool(win32gui.IsWindowVisible(panel["hwnd"]))
        except win32gui.error:
            still_up = False
        report["dialog_closed"] = not still_up
        if still_up:
            report["stranded"] = (
                "the dialog is still visible after its left button was pressed — the operator "
                "has to restart the application; this probe stops here and pokes nothing further"
            )
    report["driver_notes"] = list(actuator.warnings)
    emit(report, started)
    # Non-zero when anything was left on screen: a dialog the operator has to restart for is not
    # a successful read, whatever the inventory says.
    return 3 if report.get("controls") and not report["dialog_closed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
