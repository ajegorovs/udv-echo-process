"""recon/55 - put the measurement channel back, from a screen recon/47 will not touch.

`recon/47` refuses to start unless the screen is the clean measurement layout (43 visible
controls in 4 panels), and that guard is right for a read-only probe. It also makes the probe
useless for the one job left here: the application is on channel 2, channel 2 is in **assisted
mode**, and assisted mode *removes the sidebar parameter column* — measured live 2026-09-17,
the same screen is 21 visible controls in 3 panels. So the state that needs fixing is a state
the probe refuses to enter, by design.

`ensure_channel()` itself has no such precondition: it opens whichever parameters dialog the
popup's first entry names, writes the channel, accepts, re-opens and reads the channel back.
That is all this does.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))


from udv_echo_process.acquire.driver import (
    AcquisitionError,
    Win32Actuator,
)

OUT = Path(__file__).resolve().parents[3] / "outputs" / "live"
WANTED = int(sys.argv[1]) if len(sys.argv) > 1 else 1

actuator = Win32Actuator(
    channel=WANTED, allow_real_input=True, note_sink=lambda m: print(f"  note: {m}")
)
print(f"restoring channel {WANTED}; screen now: {actuator.layout_note()!r}")
print(f"cursor before: {actuator._cursor_position()}")
try:
    print(f"verified channel: {actuator.ensure_channel()}")
except AcquisitionError as exc:
    print(f"FAILED: {exc}")
    actuator._close_any_dialog()
time.sleep(0.8)
print(f"panels: {len(actuator._panel_map())}  visible controls: {len(actuator._resolve()['raw'])}")
print(f"layout_note: {actuator.layout_note()!r}")
print(f"dialog candidates: {[p['rect'] for p in actuator._dialog_panels()]}")
print(f"overlay open: {actuator._peek_overlay()!r}")
print(f"cursor after: {actuator._cursor_position()}")
print(f"warnings: {actuator.warnings}")

from PIL import ImageGrab

shot = OUT / f"restored-{time.strftime('%Y%m%d-%H%M%S')}.png"
ImageGrab.grab(all_screens=True).save(shot)
print(f"screenshot: {shot}")
