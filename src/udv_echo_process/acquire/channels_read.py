"""Read the operator-opened Channels popup without opening, closing or changing it.

Bind exactly one visible application, take its public screen snapshot, and query
visible edit controls with the driver's bounded WM_GETTEXT reader. GetWindowText
cannot supply cross-process control values. WM_GETTEXT is a read query, not a
setting write or posted input. No press, combo selection, commit, hover or cursor
movement occurs. Root identity is checked around the queries; existing child
handle lifetime limitations remain.

``capture_dir`` is the optional **capture evidence** half
(:mod:`udv_echo_process.acquire.channels_capture`): the popup's own rectangle is
cropped out of two whole-screen frames, saved as lossless PNG, and held to
before/after target, foreground, non-minimised and popup-rect guards plus a
numeric bracketing of every amount. It is opt-in, it claims a fresh
``capture-NNN`` run directory under the path the caller names (an earlier run's
frames are never overwritten). The image backend must report the virtual-screen origin and size
the grab was taken from, because a popup rect is in screen coordinates; a grab
whose bitmap size disagrees with that screen is refused rather than rescaled.
The image backend and the window-state read are injectable, so the whole path
is exercisable without a desktop.

Only after that capture is ``ok`` **and** its two frames are stable are the frames handed to
:func:`udv_echo_process.acquire.caption_band.attribute_frames`, which returns a **visual
attribution** of the painted caption line in ``capture.visual_caption`` when — and only when —
both frames read the same exact result. That attribution is not native text (the report's
``caption`` stays ``UNKNOWN``), carries no action authority, never touches
``per_channel.channel`` or an amount, and is not derived from anything the caller declared.
"""

from __future__ import annotations

from pathlib import Path

from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.caption_band import attribute_frames
from udv_echo_process.acquire.channels_capture import (
    CaptureEvidence,
    FrameEvidence,
    NumericBracketing,
    ScreenFrame,
    WindowGuard,
    assemble,
    bracket_numeric,
    compare_guards,
    crop_rect,
    digest,
    frame_geometry,
    frame_stats,
    roi_from_read,
    screen_frame,
)
from udv_echo_process.acquire.driver import (
    AcquisitionError,
    Win32Actuator,
    observation_of,
)
from udv_echo_process.acquire.ui.channels import ChannelsRead, resolve_channels
from udv_echo_process.acquire.ui.layout import MAIN_CLASS
from udv_echo_process.acquire.win32.tree import visible_main_windows

__all__ = ["ChannelsReadUnavailable", "read_channels"]


class ChannelsReadUnavailable(AcquisitionError):
    """No attributable popup reading could be obtained; never mistaken for absence."""


def _grab_screen() -> ScreenFrame:
    """The default image backend: one whole-desktop frame plus the screen it came from.

    ``Pillow`` belongs to the ``acquire`` extra, not the core dependencies, so it is imported
    here rather than at module scope — the models and every test import this module on any host.
    The virtual-screen origin and size are read from the same session as the grab
    (``GetSystemMetrics`` 76–79, the rule ``tools/live/probes/dialog_shot.py`` reads through
    ``user32``): a popup rect is in screen coordinates and the frame is not, so the origin has
    to travel with the bitmap. The metrics live on ``win32api``, not ``win32gui`` — the latter
    has no ``GetSystemMetrics`` at all, so importing the wrong module would fail only on a live
    desktop. Metrics that cannot be read raise here and become a named unknown in the report;
    they are never replaced by ``(0, 0)``.
    """
    import win32api
    from PIL import ImageGrab

    origin = (win32api.GetSystemMetrics(76), win32api.GetSystemMetrics(77))
    size = (win32api.GetSystemMetrics(78), win32api.GetSystemMetrics(79))
    return ScreenFrame(image=ImageGrab.grab(all_screens=True), origin=origin, size=size)


def _window_state(hwnd: int) -> dict[str, bool | None]:
    """Foreground/minimised for one handle, read-only; ``None`` when either read fails."""
    state: dict[str, bool | None] = {"foreground": None, "minimized": None}
    try:
        import win32gui

        state["foreground"] = win32gui.GetForegroundWindow() == hwnd
    except Exception:  # noqa: BLE001 — an unreadable precondition stays unknown
        state["foreground"] = None
    try:
        import win32gui

        state["minimized"] = bool(win32gui.IsIconic(hwnd))
    except Exception:  # noqa: BLE001 — same
        state["minimized"] = None
    return state


def _bound(
    actuator: Win32Actuator | None, target: WindowTarget | None
) -> tuple[Win32Actuator, WindowTarget]:
    """The one visible window and the binding for it — verified, never replaced."""
    windows = visible_main_windows(MAIN_CLASS)
    if len(windows) != 1:
        raise ChannelsReadUnavailable(
            f"{len(windows)} visible {MAIN_CLASS} windows: channels-read requires exactly one"
        )
    if actuator is None:
        actuator = Win32Actuator(allow_real_input=False)
    if target is None:
        target = actuator.bind_target(windows[0])
    elif int(windows[0]) != target.hwnd:
        raise ChannelsReadUnavailable(
            f"the only visible window is {windows[0]} where the caller's binding is "
            f"{target.hwnd}: nothing is rebound"
        )
    return actuator, target


def _read_once(
    actuator: Win32Actuator, target: WindowTarget
) -> tuple[ChannelsRead, object]:
    """One inspection of the already-open popup, plus the screen fingerprint behind it."""
    fingerprint = actuator.screen_fingerprint()
    roles = getattr(actuator, "last_roles", None)
    if not isinstance(roles, dict):
        raise ChannelsReadUnavailable("the screen read published no role map")
    if roles.get("window") != fingerprint.hwnd or fingerprint.hwnd != target.hwnd:
        raise ChannelsReadUnavailable(
            "the role map, fingerprint and original window binding disagree"
        )
    actuator.verify_bound_target(target)
    rows = []
    for source in roles.get("raw", ()):
        row = dict(source)
        if row.get("cls") in {"Edit", "TSp_Edit"} and row.get("visible", True):
            row["text"] = actuator._get_text(row["hwnd"])
        rows.append(row)
    actuator.verify_bound_target(target)
    return resolve_channels(observation_of({**roles, "raw": rows})), fingerprint


def _guard(
    label: str,
    read: ChannelsRead,
    fingerprint: object,
    state: dict[str, bool | None],
    target: WindowTarget,
) -> WindowGuard:
    """One moment's attributable facts, from the report, its fingerprint and the state read."""
    rect = getattr(fingerprint, "rect", None)
    return WindowGuard(
        label=label,
        hwnd=getattr(fingerprint, "hwnd", None),
        rect=None if rect is None else tuple(rect),
        foreground=state.get("foreground"),
        minimized=state.get("minimized"),
        surface=read.surface.value,
        popup_rect=roi_from_read(read),
        popup_hwnd=None if read.popup is None else read.popup.hwnd,
    )


#: How many run directories a capture may try to claim under one caller path.
_MAX_RUN_DIRECTORIES = 1000


def _claim_directory(base: Path) -> Path:
    """Exclusively claim a fresh run directory under ``base``, preserving earlier runs.

    ``mkdir(exist_ok=False)`` is the claim: two captures into the same caller directory (the
    same operator re-run, or two processes) get different directories, so a later capture can
    never overwrite an earlier one's frames. Nothing is deleted and no existing file is reused.
    """
    base.mkdir(parents=True, exist_ok=True)
    for index in range(1, _MAX_RUN_DIRECTORIES + 1):
        candidate = base / f"capture-{index:03d}"
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(
        f"{_MAX_RUN_DIRECTORIES} capture directories already exist under {base}; refusing to "
        "reuse or overwrite any of them"
    )


def _capture(
    read: ChannelsRead,
    fingerprint: object,
    actuator: Win32Actuator,
    target: WindowTarget,
    capture_dir: str | Path,
    image_backend,
    window_state,
) -> ChannelsRead:
    """Take the optional capture evidence around one bracketing re-read.

    Order: guards from the first read, two frames, then a second read of the same popup on the
    same binding. Nothing is captured when the report resolved no popup rectangle, and a failed
    grab is reported as unknown rather than written as an empty picture.
    """
    directory = Path(capture_dir)
    before_guard = _guard(
        "before", read, fingerprint, window_state(target.hwnd), target
    )
    roi = roi_from_read(read)
    frames: list[FrameEvidence] = []
    backend_error: str | None = None
    claimed: Path | None = None
    if roi is not None:
        try:
            claimed = _claim_directory(directory)
        except (OSError, RuntimeError) as exc:
            backend_error = f"the capture directory could not be created: {exc!r}"
    if roi is not None and backend_error is None and claimed is not None:
        for index in (1, 2):
            try:
                frame = screen_frame(image_backend())
                geometry = frame_geometry(frame)
                if geometry:
                    backend_error = geometry[0]
                    break
                image = frame.image
                box = crop_rect(roi, frame.origin)
                # Only the bitmap's own size is needed here: the whole frame is never
                # converted to greyscale, because the blank/stability rules are about the crop.
                width = int(image.width)  # type: ignore[attr-defined]
                height = int(image.height)  # type: ignore[attr-defined]
                if box[0] < 0 or box[1] < 0 or box[2] > width or box[3] > height:
                    backend_error = (
                        f"the popup rect {roi!r} (crop box {box!r} at virtual origin "
                        f"{frame.origin!r}) lies outside the {width}x{height} frame; no crop is "
                        "invented"
                    )
                    break
                crop = image.crop(box)
                path = claimed / f"channels-roi-frame-{index}.png"
                crop.save(path, format="PNG")
                frames.append(
                    FrameEvidence(
                        index=index,
                        path=str(path),
                        rect=roi,
                        stats=frame_stats(crop),
                        digest=digest(crop),
                    )
                )
            except Exception as exc:  # noqa: BLE001 — a failed grab is evidence, not a crash
                backend_error = f"frame {index} could not be captured: {exc!r}"
                break
    after = None
    after_guard = None
    numeric = NumericBracketing(
        consistent=False,
        note=(
            "the closing read did not complete, so no amount is bracketed and no number is "
            "paired with the image; the frames are retained as evidence of an unbracketed moment"
        ),
    )
    try:
        after, after_fingerprint = _read_once(actuator, target)
    except Exception as exc:  # noqa: BLE001 — a failed closing read keeps its frames
        backend_error = (
            f"the closing read failed after the frames were saved: {exc!r}; the frames are "
            "retained and the capture is UNKNOWN rather than left as orphaned evidence"
        )
    else:
        after_guard = _guard(
            "after", after, after_fingerprint, window_state(target.hwnd), target
        )
        numeric = bracket_numeric(read, after)
    evidence = assemble(
        roi=roi,
        frames=tuple(frames),
        guards=compare_guards(before_guard, after_guard, target.hwnd),
        numeric=numeric,
        readable=read.readable,
        after_readable=None if after is None else after.readable,
        refusals=read.refusals,
        directory=None if claimed is None else str(claimed),
    )
    if backend_error is not None:
        evidence = CaptureEvidence(
            **{
                **evidence.model_dump(),
                "status": "UNKNOWN",
                "unknown_reasons": (*evidence.unknown_reasons, backend_error),
            }
        )
    # The painted caption is attributed **only** from an attributed, still capture whose two
    # frames read the same exact thing. The recogniser never sees the amounts, the caller's
    # declaration or the operator's statement, and its result stays a visual attribution: the
    # report's ``caption`` is untouched, and nothing downstream may treat it as native text or
    # as permission to press.
    if (
        evidence.status == "ok"
        and evidence.stable is True
        and len(evidence.frames) >= 2
    ):
        evidence = evidence.model_copy(
            update={
                "visual_caption": attribute_frames(
                    tuple(frame.path for frame in evidence.frames),
                    tuple(frame.digest for frame in evidence.frames),
                )
            }
        )
    return ChannelsRead(**{**read.model_dump(), "capture": evidence})


def read_channels(
    actuator: Win32Actuator | None = None,
    *,
    target: WindowTarget | None = None,
    capture_dir: str | Path | None = None,
    image_backend=None,
    window_state=None,
) -> ChannelsRead:
    """Inspect the already-open popup on one bound window; never perform a gesture.

    ``target`` is for a caller that already bound the window in an earlier step: the binding is
    then **verified**, never replaced, so a read taken right before a write cannot silently
    migrate to a different window. Without it the one visible window is bound here, which is the
    read-only command's behaviour and stays the default.

    ``capture_dir`` is opt-in and additive: without it this is the original single read and the
    report's ``capture`` stays ``None``. With it the report carries
    :class:`~udv_echo_process.acquire.channels_capture.CaptureEvidence`, the popup is read once
    more around the capture for the numeric bracketing, and — only when that capture is ``ok`` and
    both of its frames are stable — ``capture.visual_caption`` carries the painted caption line as
    a **visual attribution**. The report's own ``caption`` stays ``UNKNOWN`` either way: no native
    text is read, and no amount, channel or declaration is derived from the picture.
    ``image_backend``/``window_state`` are injection points for exercising the whole path without
    a desktop.
    """
    actuator, target = _bound(actuator, target)
    read, fingerprint = _read_once(actuator, target)
    if capture_dir is None:
        return read
    return _capture(
        read,
        fingerprint,
        actuator,
        target,
        capture_dir,
        _grab_screen if image_backend is None else image_backend,
        _window_state if window_state is None else window_state,
    )
