"""Drive one whole point through the *port* and report every stage.

The port's own cycle, live: `Record` -> `Stop` -> `Do store` -> the Store dialog -> the
name and the working directory -> `Do store` -> the file on disk. Everything before a file
exists is the application's state; **the stored file is the only deliverable** (docs/16 §12).

Two modes, because the first one is cheap and read-only where it can be:

    preflight   record ~2 s, stop, press `Do store`, *read* the Store dialog's name field
                and working directory, then cancel it — nothing is stored. This proves the
                strip takes the real click, that `Do store` opens the dialog, and tells the
                caller which directory to watch.
    store       the whole point through the port: ``record_and_store``, then the file is
                read back through the repo's own verifier.

Usage (through the scheduler — the agent's shell is session 0 and cannot touch this
desktop; UDOP runs in session 1 "Console"):

    # out/task_target.txt = 56_point_cycle.py ; out/task_args.txt = preflight
    # out/task_args.txt = store port-probe-01 3
    .venv/Scripts/pythonw.exe recon/task_run.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# The repository this tool was cloned into: found from the file, never hard-coded, so the
# same file works at any clone path on any machine.
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from udv_echo_process.acquire.actuator import (
    DialogControl,
    StripControl,
    StripView,
)
from udv_echo_process.acquire.driver import Win32Actuator

OUT = Path(__file__).resolve().parents[3] / "outputs" / "live"
VIEW_TIMEOUT_S = 8.0


def report(drv: Win32Actuator, tag: str) -> None:
    """The strip's structure and the layout fingerprint, both re-resolved."""
    state = drv.strip_state()
    print(
        f"  [{tag}] view={state.view.value!r} buttons={state.button_count} "
        f"slider={state.has_slider} slider_max={state.slider_max}"
    )
    print(f"        layout_note={drv.layout_note()!r}")


def normalise(drv: Win32Actuator) -> None:
    """Get back to the ready view, the way the operator's first step says.

    A stopped recording leaves the store view up (three top-row buttons **and** the store
    slider); the ready view is the only one a point may start from, and the button row means
    something different in each. "Clear and restart" is the strip's own way out, and
    ``record_and_store`` presses it too — this is the operator's sequence made explicit.
    """
    state = drv.strip_state()
    if state.view is StripView.STORE:
        print("  a leftover store view is up: pressing Clear and restart, waiting for ready")
        drv.press(StripControl.NEW_ACQUISITION)
        state = drv._wait_for_view_guarded((StripView.READY,), VIEW_TIMEOUT_S)
        print(f"  view after the clear: {state.view.value!r}")


def preflight(drv: Win32Actuator) -> int:
    """Record two seconds, stop, open the Store dialog, read it, cancel it."""
    report(drv, "initial")
    normalise(drv)
    report(drv, "normalised")
    print("\nstage 1: press Record (a real click on the strip)")
    drv.press(StripControl.RECORD)
    state = drv._wait_for_view_guarded((StripView.RECORDING,), VIEW_TIMEOUT_S)
    print(f"  view after Record: {state.view.value!r} (wanted 'recording')")
    if state.view is not StripView.RECORDING:
        print("  the real click did not start a recording — stopping here")
        return 3

    print("stage 2: hold ~2 s, then press Stop")
    drv._hold_recording(2.0)
    drv.press(StripControl.STOP)
    state = drv._wait_for_view_guarded((StripView.STORE,), VIEW_TIMEOUT_S)
    report(drv, "stopped")
    if state.view is not StripView.STORE:
        print(f"  Stop did not reach the store view ({state.view.value!r})")
        return 4

    print("stage 3: press Do store and read the dialog it opens")
    drv.press(StripControl.DO_STORE)
    panel, kids = drv._require_store_dialog()
    name_field = drv._store_name_field(panel, kids)
    name_edit, path_edit = drv._store_edits(panel, kids)
    print(
        f"  Store dialog: {panel['w']}x{panel['h']} at {panel['rect'][:2]}, "
        f"{len(kids)} children"
    )
    print(f"  name field        : {drv._get_text(name_field['hwnd'])!r}")
    print(f"  first edit        : {drv._get_text(name_edit['hwnd'])!r}")
    if path_edit is None:
        print("  no path-looking field in this dialog")
    else:
        print(f"  working directory : {drv._get_text(path_edit['hwnd'])!r}")
    for kid in kids:
        if kid["cls"] in ("TSp_Button", "TButton", "TBitBtn"):
            print(f"    button {kid['cls']} at {kid['rect'][:2]} {kid['w']}x{kid['h']}")

    print("\nstage 4: cancel the dialog (nothing is stored by a preflight)")
    drv._dialog_button(panel, kids, DialogControl.SAFE)
    time.sleep(0.8)
    report(drv, "after-cancel")
    return 0


def store(
    drv: Win32Actuator, name: str, seconds: float, directory: Path, lift: bool = False
) -> int:
    """The whole point, through the port, ending in a file that is read back.

    ``lift`` removes the driver's *layout* gate for this run and nothing else. The gate is
    "never start a point on a screen whose fingerprint is not the clean measurement one", and
    an **assisted-mode channel** fails it by design (21 visible controls in 3 panels, no
    sidebar). A *store* is still a meaningful thing to do there — it is the only way to get a
    file whose word 1 (`assisted Mode`) says what the application's mode is, which is what
    certifies that flag — while a parameter *sweep* is not meaningful there at all (there is no
    column to write). So the probe lifts the gate by hand, says so in its output, and leaves
    every other guard in place: the channel is still written and verified, the strip is still
    the port's own presses, and the file is still waited for and read back.
    """
    if lift:
        drv.layout_note = lambda: None  # type: ignore[method-assign]
        print("  (the layout gate is lifted by this probe: an assisted channel is a state a")
        print("   store is valid in, a parameter sweep is not)")
    report(drv, "initial")
    print(f"\nstoring one point: name={name!r} seconds={seconds} dir={directory}")
    path = drv.record_and_store(name, seconds, directory)
    print(f"\n  stored: {path}")
    print(f"  size  : {path.stat().st_size} bytes")

    try:
        from udv_echo_process.acquire.verify import read_words

        facts = read_words(Path(path), channel=int(os.environ.get("UDV_CHANNEL", "1")))
        print(f"  words : gates={facts.gates} resolution={facts.resolution_mm} mm "
              f"depth={facts.depth_mm} mm sound_speed={facts.sound_speed_ms} m/s "
              f"prf={facts.prf_us} us emissions={facts.emissions_per_profile} "
              f"burst={facts.burst_length}")
        if facts.missing_fields():
            print(f"  words missing: {facts.missing_fields()}")
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        print(f"  the words could not be read: {exc!r}")

    head = Path(path).read_bytes()[:64]
    print(f"  first 64 bytes: {list(head)}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    mode = args[0] if args else "preflight"
    # The channel is the fifth token of a store run, so one probe can cover a channel the
    # environment would not name (the scheduled task carries no per-run environment).
    channel = int(os.environ.get("UDV_CHANNEL", "1"))
    if mode == "store" and len(args) > 4 and args[4].isdigit():
        channel = int(args[4])
    notes: list[str] = []
    drv = Win32Actuator(channel=channel, note_sink=notes.append)
    print(f"port point cycle: mode={mode!r} channel={channel}")

    try:
        if mode == "preflight":
            code = preflight(drv)
        elif mode == "store":
            name = args[1] if len(args) > 1 else "port-probe-01"
            seconds = float(args[2]) if len(args) > 2 else 3.0
            if len(args) > 3:
                directory = Path(args[3])
            elif os.environ.get("UDV_STORE_DIR"):
                directory = Path(os.environ["UDV_STORE_DIR"])
            else:
                # Never a default: the driver *writes* the Store dialog's Working
                # directory when it does not match, so a guessed path here would point
                # the instrument's store at a directory nobody asked for. The preflight
                # mode is what reads the real one.
                print("store mode needs a directory: 56_point_cycle.py store <name> <s> <dir>")
                return 2
            code = store(drv, name, seconds, directory, lift="lift" in args)
        else:
            print(f"unknown mode {mode!r}: use 'preflight' or 'store'")
            code = 2
    except Exception as exc:  # noqa: BLE001 - the probe reports, it does not hide
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        code = 1
    finally:
        for note in notes:
            print(f"  note: {note}")
        report(drv, "final")
        state = drv.strip_state()
        if state.view is StripView.RECORDING:
            print("  still recording: pressing Stop so the buffer cannot fill")
            drv.press(StripControl.STOP)
    return code


if __name__ == "__main__":
    sys.exit(main())
