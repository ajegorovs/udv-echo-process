"""Screenshot the ``Operating parameters`` dialog, so its painted labels can be read.

**Why pictures, and why here.** This application's dialog labels are *painted into* their
controls rather than stored in them: ``WM_GETTEXT`` returns the empty string for every one of
them, which is what :mod:`tools.live.probes.dialog_fields` measures — 42 controls, almost all
with ``text: ""``. A caption-less dump identifies a field by class and position only. The
labels a human reads off the screen are not retrievable through any API this repository has,
so the other half of the identification pass is an **image**: the dialog photographed at a
known rect, losslessly, for a reader (a vision model, or a person) that can see the text.

That is the whole of this probe: open, photograph, close. It is the capture half of the
prototype tooling that was dropped when the port started; nothing here writes a value, presses
a strip button, or touches the ``Parameters`` popup beyond the topmost entry the driver itself
presses (:meth:`~udv_echo_process.acquire.driver.Win32Actuator._open_parameters_dialog`).

What it does, in order:

1. open ``Parameters → Operating parameters`` through the driver's *existing* gesture, with the
   same refusals (a popup already open, the wrong dialog, the assisted mode switched on) —
   never a reimplementation of that path, exactly as ``dialog_fields.py`` does;
2. read the dialog's rect **live** from ``GetWindowRect`` on the panel the driver resolved, and
   also record the rect the driver's own resolver reported: the window can be moved
   (``probes/move_window.py``) and the rect recorded in a committed JSON is a measurement of a
   different session;
3. capture the **whole screen** once, twice in a row, and keep the second frame: two grabs are
   compared so ``frame_stable`` says whether the screen was still while the picture was taken
   (an animation or a half-painted dialog shows up as *not* stable rather than as a mysterious
   artefact in the PNG);
4. crop the dialog's own rect out of that **same** frame — one capture, two images, so the two
   PNGs cannot disagree about which moment they show;
5. save both as PNG (lossless: the reader is reading small painted text, and JPEG ringing around
   glyph edges is exactly what breaks it) under ``outputs/live/``;
6. close the dialog with its **left** button, as ``dialog_fields.py`` does
   (``_close_parameters_dialog`` → ``DialogControl.SAFE``), never a window close and never its
   default button — on a parameters dialog that button *commits* what the dialog holds.

**The blank-image trap, and what is checked instead.** A capture taken from the wrong session —
or one that failed and was written anyway — is a **black or flat PNG**, and a black PNG is worse
than a failure because it looks like a successful capture down every later step. So every image
saved here carries its own statistics (:func:`image_stats`): the number of distinct greys, the
dominant grey's share of the frame, and the grey range. ``non_blank`` is false when the frame
holds a single value, and the report says so instead of the parent finding it out later.

**DPI — the one way this can come out soft, and how it would look.** Read live and reported
rather than assumed: this interpreter is **DPI-unaware** (``GetProcessDpiAwareness == 0``), which
is harmless at the 100 % scaling measured here (``GetDpiForSystem == 96``, ``1920x1080`` screen,
virtual-screen origin ``0,0``). On a machine at 125 % or 150 % scaling it is *not* harmless: a
DPI-unaware process sees a virtual screen and a virtualised ``GetWindowRect``, so the two stay
consistent with each other but the bitmap is resampled — the crop would come out **soft and
slightly misplaced rather than wrong-sized**, and small painted text would be the first thing to
go. ``dpi.unaware_risk`` names that, and ``rect_clamped``/``covering`` below catch the grosser
failures (a rect outside the grabbed frame, or a dialog with something in front of it).

**The dispatcher trap, unchanged from every other probe here.** The probe is named to the
dispatcher as a file **under ``tools/live/probes``**::

    PROBE_TIMEOUT_S=150 ./tools/live/dispatch.sh dialog_shot.py

A repo-relative path (``tools/live/probes/dialog_shot.py``) is joined onto the probes directory
again by ``task_run.py``, finds no file, prints ``no such probe`` to a ``pythonw`` process with
no console, and returns **without writing a log** — the dispatcher then polls for a line that
cannot appear and reports a wedged probe. Both PNGs are written by absolute path for the same
reason: the probe runs with its working directory set to the probes directory.

**No recovery, by policy.** If the dialog will not open, the driver's own refusal is printed as
JSON (``error``) and the exit code is non-zero; if it is still visible after the close press the
report says ``stranded`` and the probe stops — the operator restarts the application, and that is
the only documented exit. If the dialog *is* open and the capture fails, the close still runs:
a failed picture never leaves a dialog in front of the operator.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

import win32con
import win32gui
import win32ui
from PIL import Image, ImageGrab

from udv_echo_process.acquire import driver

#: Where the pictures go: ``outputs/`` is gitignored, and large binaries belong there.
OUT = REPO / "outputs" / "live"

#: A settle before the first grab: the dialog is validated by the driver's own read of its
#: channel combo, which says the controls exist, not that the application has finished painting
#: them. The two-frame stability check below is what actually measures that.
SETTLE_S = 0.8

#: In PNG, because the reader reads small text off these: JPEG ringing around glyph edges is
#: exactly what costs a caption its last character.
FORMAT = "PNG"


def image_stats(im: Image.Image) -> dict:
    """What the frame holds, so a flat or black capture is *reported* rather than saved.

    ``non_blank`` is the check the parent asked for: more than one distinct grey. The share of
    the dominant grey is the sharper signal — a fully black frame, a fully white one and a
    half-painted dialog all pass "more than one value" in some form, and only the share (close
    to ``1.0``) says the picture is essentially one colour. ``distinct_colors`` is counted only
    for small frames: on a full screen it is a set of hundreds of thousands of tuples, and the
    grey histogram answers the same question for a fraction of the work.
    """
    grey = im.convert("L")
    hist = grey.histogram()
    total = sum(hist) or 1
    present = [value for value, count in enumerate(hist) if count]
    stats: dict[str, object] = {
        "width": im.width,
        "height": im.height,
        "mode": im.mode,
        "distinct_grey_levels": len(present),
        "grey_min": present[0] if present else None,
        "grey_max": present[-1] if present else None,
        "dominant_fraction": round(max(hist) / total, 4),
        "non_blank": len(present) > 1,
    }
    if im.width * im.height <= 1_000_000:
        colors = im.convert("RGB").getcolors(maxcolors=1 << 20)
        stats["distinct_colors"] = None if colors is None else len(colors)
    return stats


def grab_screen() -> tuple[Image.Image, str]:
    """The whole virtual desktop as a bitmap, with the name of the route that worked.

    ``PIL.ImageGrab`` first, with ``all_screens=True`` so a multi-monitor desktop is caught whole
    rather than only the monitor the dialog happens to be on. The fallback is a direct BitBlt of
    the desktop DC through ``win32ui``: it covers the primary monitor only, which is why it is
    the fallback and why the route used is printed — a reader looking at a full-screen PNG needs
    to know whether it is the whole desktop or one monitor.
    """
    try:
        return ImageGrab.grab(all_screens=True), "PIL.ImageGrab(all_screens=True)"
    except Exception as exc:  # noqa: BLE001 — the fallback below is the point
        primary_error = repr(exc)
    left, top, right, bottom = win32gui.GetWindowRect(win32gui.GetDesktopWindow())
    src = win32gui.GetWindowDC(win32gui.GetDesktopWindow())
    try:
        source = win32ui.CreateDCFromHandle(src)
        memory = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(source, right - left, bottom - top)
            memory.SelectObject(bitmap)
            memory.BitBlt(
                (0, 0),
                (right - left, bottom - top),
                source,
                (left, top),
                win32con.SRCCOPY,
            )
            info = bitmap.GetInfo()
            raw = bitmap.GetBitmapBits(True)
            image = Image.frombuffer(
                "RGB",
                (info["bmWidth"], info["bmHeight"]),
                raw,
                "raw",
                "BGRX",
                0,
                1,
            )
            image.load()
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory.DeleteDC()
            source.DeleteDC()
    finally:
        win32gui.ReleaseDC(win32gui.GetDesktopWindow(), src)
    return image, f"win32ui BitBlt of the desktop DC (ImageGrab failed: {primary_error})"


def dpi_facts() -> dict:
    """Scaling as this interpreter sees it — the one thing that can quietly soften a capture.

    Everything here is a *read*. ``unaware_risk`` is the derived sentence: a DPI-unaware
    interpreter at anything other than 100 % sees a virtualised screen, so both the rect it
    crops by and the bitmap it crops from are scaled together — the crop lands in
    approximately the right place and comes back resampled, which reads as blurry text rather
    than as an obviously broken image.
    """
    import ctypes

    user32 = ctypes.windll.user32
    awareness = ctypes.c_int()
    try:
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness))
        aware_value: int | None = awareness.value
    except Exception:  # noqa: BLE001 — a missing shcore is a fact, not a failure
        aware_value = None
    return {
        "process_dpi_awareness": aware_value,
        "process_dpi_awareness_note": {
            0: "unaware",
            1: "system",
            2: "per-monitor",
            None: "unreadable (shcore unavailable)",
        }.get(aware_value, str(aware_value)),
        "screen": [user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)],
        "virtual_screen_origin": [user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)],
        "virtual_screen_size": [user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)],
        "system_dpi": user32.GetDpiForSystem() if hasattr(user32, "GetDpiForSystem") else None,
        "unaware_risk": (
            "at 96 dpi / 100 % scaling an unaware process captures 1:1; at any other scaling "
            "the rect and the bitmap are virtualised together, so the crop is soft and slightly "
            "offset instead of being obviously wrong"
        ),
    }


def is_self_or_child(hwnd: int, ancestor: int, depth: int = 6) -> bool:
    """Whether ``hwnd`` is ``ancestor`` or lies inside it — used to name what covers a rect."""
    for _ in range(depth):
        if not hwnd:
            return False
        if hwnd == ancestor:
            return True
        hwnd = win32gui.GetParent(hwnd)
    return False


def covering_check(panel: int, rect: list[int]) -> dict:
    """What the window manager says is on top at five points inside the dialog's rect.

    A dialog can be visible and still be *behind* something — the crop would then be a
    photograph of whatever is in front, which is not discoverable from the PNG itself. Five
    points (four inset corners and the middle) are enough to catch an overlapping window, and
    each answer is reported as the top window's class rather than as a boolean, so the failure
    names what was in the way.
    """
    left, top, right, bottom = rect
    inset_x = max(4, (right - left) // 10)
    inset_y = max(4, (bottom - top) // 10)
    points = [
        (left + inset_x, top + inset_y),
        (right - inset_x, top + inset_y),
        (left + inset_x, bottom - inset_y),
        (right - inset_x, bottom - inset_y),
        ((left + right) // 2, (top + bottom) // 2),
    ]
    hits: list[dict] = []
    for x, y in points:
        try:
            window = win32gui.WindowFromPoint((x, y))
        except win32gui.error as exc:
            hits.append({"point": [x, y], "error": repr(exc)})
            continue
        try:
            cls = win32gui.GetClassName(window)
        except win32gui.error:
            cls = "<vanished>"
        hits.append(
            {"point": [x, y], "hwnd": window, "cls": cls, "inside": is_self_or_child(window, panel)}
        )
    return {
        "points": hits,
        "all_inside": all(hit.get("inside") for hit in hits),
        "foreground": win32gui.GetForegroundWindow(),
        "foreground_cls": _safe_class(win32gui.GetForegroundWindow()),
    }


def _safe_class(hwnd: int) -> str:
    try:
        return win32gui.GetClassName(hwnd)
    except win32gui.error:
        return "<vanished>"


def save(image: Image.Image, path: Path) -> dict:
    """Write one PNG and describe it — size, dimensions and the blank check in one row."""
    image.save(path, format=FORMAT, optimize=False)
    row = image_stats(image)
    row["path"] = str(path)
    row["bytes"] = path.stat().st_size
    return row


def emit(report: dict, started: float) -> None:
    """Stamp the elapsed time and print the report once — the probe's whole output."""
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, indent=2, default=str))


def main() -> int:
    started = time.monotonic()
    report: dict[str, object] = {"probe": "dialog_shot"}
    OUT.mkdir(parents=True, exist_ok=True)

    actuator = driver.Win32Actuator()

    # --- 1. the dialog, opened through the driver's own gesture --------------------------
    try:
        panel = actuator._open_parameters_dialog()
    except driver.AcquisitionError as exc:
        # The driver's refusal, verbatim: it already names what was asked for and what the
        # application showed. Nothing here retries it and nothing recovers it.
        report["opened"] = False
        report["error"] = str(exc)
        emit(report, started)
        return 2

    report["opened"] = True
    report["dialog"] = {k: v for k, v in panel.items() if k != "raw"}

    try:
        # --- 2. the rect, live, and the one the resolver recorded ------------------------
        try:
            live_rect = list(win32gui.GetWindowRect(panel["hwnd"]))
        except win32gui.error as exc:
            report["error"] = f"the dialog vanished before it could be photographed: {exc!r}"
            return 4
        rect = live_rect
        report["rect"] = rect
        report["rect_source"] = (
            "GetWindowRect on the panel this driver resolved, taken now — the driver's own "
            "report is kept beside it because the window can be moved between sessions"
        )
        report["rect_from_driver"] = panel.get("rect")
        report["dpi"] = dpi_facts()

        # --- 3. one settled frame of the whole screen ------------------------------------
        time.sleep(SETTLE_S)
        first, route = grab_screen()
        time.sleep(0.15)
        second, _ = grab_screen()
        frame_stable = first.tobytes() == second.tobytes()
        report["capture"] = {
            "route": route,
            "settle_s": SETTLE_S,
            "frame_stable": frame_stable,
            "frame_stable_note": (
                "two full-screen grabs 0.15 s apart were compared; False means the screen was "
                "changing while it was photographed, so the PNGs may hold a torn frame"
            ),
            "full_image_size": [second.width, second.height],
            "virtual_screen_origin": report["dpi"]["virtual_screen_origin"],  # type: ignore[index]
        }

        # --- 4. the crop, out of that same frame -----------------------------------------
        left, top, right, bottom = rect
        origin_x, origin_y = report["dpi"]["virtual_screen_origin"]  # type: ignore[index]
        box = (left - origin_x, top - origin_y, right - origin_x, bottom - origin_y)
        clamped = (
            box[0] < 0 or box[1] < 0 or box[2] > second.width or box[3] > second.height
        )
        safe_box = (
            max(0, box[0]),
            max(0, box[1]),
            min(second.width, box[2]),
            min(second.height, box[3]),
        )
        crop = second.crop(safe_box)
        report["capture"]["crop_box"] = list(box)
        report["capture"]["crop_box_clamped"] = clamped
        report["capture"]["covering"] = covering_check(panel["hwnd"], rect)

        # --- 5. the pictures -------------------------------------------------------------
        report["images"] = {
            "dialog": save(crop, OUT / "dialog.png"),
            "full": save(second, OUT / "dialog-full.png"),
        }
        report["images_note"] = (
            "the dialog image is a crop of the full-screen frame, not a second capture: the two "
            "cannot disagree about which moment they show"
        )
    finally:
        # A dialog is not recoverable by the operator — Escape closes nothing in this
        # application — so a capture that raises still has to put the dialog back the way it
        # was found. `_close_parameters_dialog` presses the bottom row's left button and notes,
        # rather than raises, a panel whose button cannot be resolved.
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
    images = report.get("images") or {}
    report["non_blank"] = all(row["non_blank"] for row in images.values()) if images else False
    emit(report, started)

    if report.get("stranded"):
        return 3
    if not images or not report["non_blank"]:
        # A flat image is a failed capture that looks like a successful one; it exits non-zero
        # so a caller cannot mistake the PNG's existence for its content.
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
