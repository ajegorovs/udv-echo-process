"""Read-only **capture evidence** for the operator-opened ``Channels`` popup.

What this module is, and what it deliberately is not. The popup's custom-button captions are
*painted*, not stated in text (ledger B15), so the amounts ``channels-read`` reads are only half
the surface: a reader that wants the painted captions needs a picture. This module carries the
picture **as evidence** and refuses to turn it into a fact:

* it saves the popup's own rectangle — the rect derived from the structural report, never a
  hardcoded box — out of two whole-screen frames, so a still screen is measurable;
* it checks the two frames' ROI digests and reports ``stable``;
* it brackets every numeric amount with a read taken **before** and **after** the capture and
  refuses to pair a number with an image when the two reads disagree;
* it reports the native caption as ``UNKNOWN`` with ``recognition: NOT_PERFORMED``. No OCR runs
  here, no threshold is guessed, no glyph is classified. An operator's stated caption stays the
  operator's statement and is never promoted to a native fact by this module.
* when the capture is ``ok`` and its two frames are stable, it also carries
  :class:`~udv_echo_process.acquire.caption_band.CaptionAttribution` in ``visual_caption``: a
  **visual attribution** read from the crop by exact template match
  (:mod:`udv_echo_process.acquire.caption_band`), never a native fact and never an action
  authority. The ``caption`` field above stays ``UNKNOWN`` regardless — a picture is not what
  the application states, and the two are deliberately different fields.

So a successful report says: *this image is the popup at this target, the screen was still, and
the numbers beside it were unchanged across the capture*. What the caption line reads is a
separate, weaker statement — ``visual_caption``, pixels matched against committed rasters — and
never a substitute for what the application states, which is nothing.

Evidence levels, in this repository's vocabulary (``docs/dop3000/device-verification.md``):

* **replay-verified** — ``tests/test_acquire_channels_capture.py`` drives the whole workflow,
  including the CLI, against an injected image backend and fake window-state reads;
* **measured** — the non-blank and stability checks are the ones ``tools/live/probes/dialog_shot.py``
  measured on this screen (:func:`frame_stats` is its ``image_stats`` rule, kept in one place);
* **unknown** — anything the frames do not settle. A capture that cannot be attributed is
  ``status="UNKNOWN"`` with a reason, never a silent success and never a fabricated reading.

The module is **pure**: no Win32 binding, no Pillow import at module scope, no window
enumeration. The images are duck-typed (``width``/``height``/``mode``/``convert("L")``/
``histogram()``/``crop(box)``/``tobytes()``/``save(path, format=...)``), so the models build,
compare and serialise on any host and a test backend is a five-line class.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal, NamedTuple

from udv_echo_process.acquire.caption_band import CaptionAttribution
from udv_echo_process.acquire.mode_marks import ModeMarkAttribution
from udv_echo_process.models.base import ValueModel

if TYPE_CHECKING:  # the report type is read, never constructed here
    from udv_echo_process.acquire.ui.channels import ChannelsRead

__all__ = [
    "CAPTION_EVIDENCE",
    "CAPTURE_ENTRY_NO_NUMERIC",
    "CAPTURE_SETTINGS_NUMERIC",
    "ENTRY_NUMERIC_NOTE",
    "ROI_SOURCE",
    "Bracket",
    "CaptureEvidence",
    "FrameEvidence",
    "FrameStats",
    "GuardComparison",
    "NumericBracketing",
    "ScreenFrame",
    "WindowGuard",
    "assemble",
    "bracket_numeric",
    "compare_guards",
    "crop_rect",
    "frame_geometry",
    "frame_stats",
    "numeric_slots",
    "roi_from_read",
    "screen_frame",
]

#: The only caption state this module can report: nothing here recognises glyphs.
UNKNOWN = "UNKNOWN"

#: The settings popup: five numeric amounts bracketed, the measured settings shape.
CAPTURE_SETTINGS_NUMERIC = "settings_numeric"

#: The clipped one-entry popup: no numeric settings fields exist to bracket.
CAPTURE_ENTRY_NO_NUMERIC = "entry_no_numeric"

#: Why an entry capture states no numeric pairing — a shape fact, not a relaxed settings read.
ENTRY_NUMERIC_NOTE = (
    "the clipped one-entry popup declares no numeric settings fields, so there is no amount "
    "to read before and after the crop: this capture is ``entry_no_numeric`` and its evidence "
    "rests on the measured shape, the paired frame digests and the window guards. The "
    "settings capture's all-five-amounts contract is unchanged and is not applied here"
)

#: Carried on every report so a reader never has to open this file to know what was not done.
CAPTION_EVIDENCE = (
    "no recognition was performed for this native caption field: the caption is a painted image "
    "and the application states no text for it. An operator's stated caption is the operator's "
    "statement, not a native fact, and is not promoted here. A validated pixel reader exists as a "
    "separate field (``visual_caption``), which is a visual attribution with no native-fact and no "
    "action-authority claim; this field stays UNKNOWN whatever that reader returns"
)

#: Where the crop's rectangle comes from — a structural fact of the same read, not a constant.
ROI_SOURCE = (
    "the popup rectangle of the structural channels-read report taken immediately before the "
    "capture (the same panel handle and rect the amounts were read from); a report whose popup "
    "did not resolve has no ROI and no image is taken"
)

#: A frame that is one colour (or 98 % one colour) is a failed capture that looks successful.
_MAX_DOMINANT_FRACTION = 0.98

#: The slots bracketed across the capture, in report order.
_SLOT_ORDER: tuple[str, ...] = (
    "repeat",
    "start_channel",
    "apply_from",
    "profiles",
    "seconds",
)


class FrameStats(ValueModel):
    """What one cropped frame holds — the blank check, not a verdict about the caption."""

    width: int
    height: int
    mode: str = ""
    distinct_grey_levels: int = 0
    dominant_fraction: float = 1.0
    non_blank: bool = False


class ScreenFrame(NamedTuple):
    """One whole-desktop grab **with the virtual screen it was taken from**.

    ``origin`` is the virtual-screen origin (``GetSystemMetrics(76/77)``) and ``size`` its
    size (``78/79``): a multi-monitor desktop can start at a negative coordinate, so a popup
    rect has to be translated by the frame's origin rather than assumed to be relative to
    ``(0, 0)``. ``image`` is the duck-typed bitmap. A backend that cannot state the virtual
    screen has no business returning a frame: the crop would be a guess.
    """

    image: object
    origin: tuple[int, int]
    size: tuple[int, int]


class FrameEvidence(ValueModel):
    """One saved ROI frame: where it went, what it holds, and its pixel digest."""

    index: int
    path: str
    rect: tuple[int, int, int, int]
    stats: FrameStats
    digest: str


class WindowGuard(ValueModel):
    """The window facts a capture has to be attributable to, read at one moment."""

    label: str
    hwnd: int | None = None
    rect: tuple[int, int, int, int] | None = None
    foreground: bool | None = None
    minimized: bool | None = None
    surface: str | None = None
    popup_rect: tuple[int, int, int, int] | None = None
    #: The popup panel's own handle: the popup has to be the *same* panel on both sides.
    popup_hwnd: int | None = None


class GuardComparison(ValueModel):
    """Before/after guards: the target, its frame, the foreground and the popup must not move."""

    before: WindowGuard
    after: WindowGuard | None = None
    consistent: bool = False
    failures: tuple[str, ...] = ()


class Bracket(ValueModel):
    """One numeric amount as it stood before and after the capture."""

    slot: str
    text_before: str = ""
    text_after: str = ""
    value_before: int | float | None = None
    value_after: int | float | None = None
    hwnd_before: int | None = None
    hwnd_after: int | None = None
    owner_before: int | None = None
    owner_after: int | None = None
    consistent: bool = False


class NumericBracketing(ValueModel):
    """Every amount bracketed; ``consistent`` only when all of them, and the set, agree."""

    slots: tuple[Bracket, ...] = ()
    consistent: bool = False
    note: str = ""
    #: ``False`` only for an ``entry_no_numeric`` capture, whose popup has no amounts at all.
    #: A settings capture is always applicable, and its five-amount contract is unchanged.
    applicable: bool = True


class CaptureEvidence(ValueModel):
    """The capture as evidence: attributed, still, bracketed — and caption-free.

    ``status`` is ``"ok"`` only when every guard, both frames and the numeric bracketing agree.
    Everything else is ``"UNKNOWN"`` with its reasons; ``captured`` says whether any image was
    written, which is deliberately independent of ``status`` (a torn frame is a picture).
    """

    requested: Literal[True] = True
    status: Literal["ok", "UNKNOWN"] = UNKNOWN
    captured: bool = False
    roi: tuple[int, int, int, int] | None = None
    #: Which contract this capture was held to. Explicit, never inferred by a consumer: a
    #: settings capture is ``settings_numeric`` (all five amounts bracketed) and a clipped
    #: one-entry popup is ``entry_no_numeric`` (structurally no amounts exist).
    capture_kind: Literal["settings_numeric", "entry_no_numeric"] = (
        CAPTURE_SETTINGS_NUMERIC
    )
    #: The run directory this capture exclusively claimed under the caller's path, if any.
    directory: str | None = None
    roi_source: str = ROI_SOURCE
    frames: tuple[FrameEvidence, ...] = ()
    stable: bool | None = None
    guards: GuardComparison
    numeric: NumericBracketing
    caption: Literal["UNKNOWN"] = UNKNOWN
    caption_evidence: str = CAPTION_EVIDENCE
    recognition: Literal["NOT_PERFORMED"] = "NOT_PERFORMED"
    #: The painted caption line as a **visual attribution**, present only when this capture was
    #: ``ok``, its two frames were stable, and both frames recognised the same exact result.
    #: ``None`` means no recognition was invoked — never that the line was read as absent.
    visual_caption: CaptionAttribution | None = None
    #: The MPX mode entry and rollover mark as a **visual attribution**, present only when this
    #: capture was ``ok``, both frames were stable, and the crop is the measured settings popup
    #: shape. ``None`` means no mode read was attempted — never that the popup states no mode.
    visual_mode_mark: ModeMarkAttribution | None = None
    unknown_reasons: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    setup_verified: Literal[False] = False


# ---------------------------------------------------------------------------------------------
# geometry and pixels — duck-typed, so no Pillow import is needed to reason about a frame
# ---------------------------------------------------------------------------------------------


def roi_from_read(read: ChannelsRead) -> tuple[int, int, int, int] | None:
    """The popup's own rectangle from a structural read, or ``None`` when it did not resolve."""
    popup = read.popup
    if popup is None or popup.rect is None:
        return None
    return popup.rect.as_tuple()


def crop_rect(
    rect: tuple[int, int, int, int], origin: tuple[int, int] = (0, 0)
) -> tuple[int, int, int, int]:
    """A screen rect as a crop box in the frame's own coordinates.

    ``origin`` is the virtual-screen origin the grab was taken from (a negative origin on a
    multi-monitor desktop). The box is returned as computed — clamping is the caller's decision,
    and a box outside the frame is a refusal rather than a silently smaller picture.
    """
    left, top, right, bottom = rect
    return (left - origin[0], top - origin[1], right - origin[0], bottom - origin[1])


def screen_frame(grab: object) -> ScreenFrame:
    """A backend's return value as a :class:`ScreenFrame`.

    A backend may return the frame itself (origin and size stated by the backend) or a bare
    duck-typed bitmap. A bare bitmap has no virtual-screen facts, so it is treated as a frame
    whose origin is ``(0, 0)`` and whose size is its own pixel size — the single-monitor
    convention. That assumption is visible in the returned frame, not guessed later.
    """
    if isinstance(grab, ScreenFrame):
        return grab
    return ScreenFrame(
        image=grab,
        origin=(0, 0),
        size=(int(grab.width), int(grab.height)),  # type: ignore[attr-defined]
    )


def frame_geometry(frame: ScreenFrame) -> tuple[str, ...]:
    """Why a grab cannot be cropped by screen coordinates — empty when it can.

    The bitmap must be exactly the virtual screen the backend reported. A smaller/larger
    bitmap means the grab was of one monitor, a virtualised (DPI-scaled) desktop, or a
    partial frame; translating a screen rect into it would be a guess, so it is refused and
    named rather than rescaled.
    """
    image = frame.image
    width, height = int(image.width), int(image.height)  # type: ignore[attr-defined]
    origin_x, origin_y = frame.origin
    size_x, size_y = frame.size
    if size_x <= 0 or size_y <= 0:
        return (
            (
                f"the backend reported a virtual desktop of {size_x}x{size_y}: that is not a "
                "screen a crop box can be translated into"
            ),
        )
    if (width, height) != (size_x, size_y):
        return (
            (
                f"the grab is {width}x{height} while the virtual desktop is reported as "
                f"{size_x}x{size_y} at origin {origin_x},{origin_y}: a partial, single-monitor "
                "or DPI-scaled frame; the crop is refused rather than rescaled or guessed"
            ),
        )
    return ()


def frame_stats(image: object) -> FrameStats:
    """Distinct greys, the dominant grey's share and the blank verdict for one frame.

    The rule is ``tools/live/probes/dialog_shot.py``'s, kept identical on purpose: a frame is
    blank when it holds one grey, and *effectively* blank when one grey covers almost all of it.
    """
    grey = image.convert("L")  # type: ignore[attr-defined]
    hist = grey.histogram()
    total = sum(hist) or 1
    present = [value for value, count in enumerate(hist) if count]
    dominant = max(hist) / total if hist else 1.0
    return FrameStats(
        width=int(image.width),  # type: ignore[attr-defined]
        height=int(image.height),  # type: ignore[attr-defined]
        mode=str(getattr(image, "mode", "")),
        distinct_grey_levels=len(present),
        dominant_fraction=round(dominant, 4),
        non_blank=len(present) > 1 and dominant < _MAX_DOMINANT_FRACTION,
    )


def digest(image: object) -> str:
    """The frame's pixel digest — the comparison two grabs are held to."""
    return hashlib.sha256(image.tobytes()).hexdigest()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------------------
# guards and bracketing
# ---------------------------------------------------------------------------------------------


def compare_guards(
    before: WindowGuard,
    after: WindowGuard | None,
    target_hwnd: int | None,
    *,
    expected_surface: str = "settings_popup",
) -> GuardComparison:
    """Hold the capture to one target: same window, same frame, foreground, not minimised.

    A missing reading is a failure, never a pass: ``foreground=None`` means the foreground could
    not be read, and an unreadable precondition cannot support an attributed picture.

    ``expected_surface`` is the one surface this capture's contract covers — the full settings
    popup for ``settings_numeric``, the clipped one-entry popup for ``entry_no_numeric``. Any
    other surface fails here, so a caller that mistook one shape for the other is refused rather
    than read under the wrong contract.
    """
    failures: list[str] = []
    for guard in (before, after):
        if guard is None:
            continue
        if target_hwnd is not None and guard.hwnd != target_hwnd:
            failures.append(
                f"{guard.label}: the read resolved hwnd {guard.hwnd}, the bound target is "
                f"{target_hwnd}"
            )
        if guard.foreground is not True:
            failures.append(
                f"{guard.label}: the instrument was not the foreground window "
                f"({guard.foreground!r}); a capture cannot be attributed to it"
            )
        if guard.minimized is not False:
            failures.append(
                f"{guard.label}: the instrument window is minimised or its state is unreadable "
                f"({guard.minimized!r})"
            )
        if guard.surface != expected_surface:
            failures.append(
                f"{guard.label}: the surface read {guard.surface!r} where {expected_surface!r} "
                "is required, so this capture contract has no ROI to crop"
            )
        if guard.popup_rect is None:
            failures.append(f"{guard.label}: the report states no popup rectangle")
        if guard.popup_hwnd is None:
            failures.append(f"{guard.label}: the popup panel states no handle")
    if after is None:
        failures.append(
            "the after-capture read is missing: a capture without a closing read is unbracketed"
        )
    else:
        if before.rect != after.rect:
            failures.append(
                f"the window rect moved across the capture ({before.rect!r} -> {after.rect!r}); "
                "the crop and the amounts may describe different moments"
            )
        if before.popup_rect != after.popup_rect:
            failures.append(
                f"the popup rect moved across the capture ({before.popup_rect!r} -> "
                f"{after.popup_rect!r})"
            )
        if before.popup_hwnd != after.popup_hwnd:
            failures.append(
                f"the popup identity changed across the capture: the panel read before is "
                f"hwnd {before.popup_hwnd}, after is hwnd {after.popup_hwnd} — the same rect on "
                "a different panel is a different popup, not the same one repainted"
            )
    return GuardComparison(
        before=before, after=after, consistent=not failures, failures=tuple(failures)
    )


def numeric_slots(
    read: ChannelsRead,
) -> dict[str, tuple[str, int | float | None, int | None, int | None]]:
    """Every numeric amount one read states: ``slot -> (text, value, edit, owner)``."""
    found: dict[str, tuple[str, int | float | None, int | None, int | None]] = {}
    per_channel = read.per_channel
    slots = {
        "repeat": read.repeat,
        "start_channel": read.start_channel,
        "apply_from": read.apply_from,
        "profiles": None if per_channel is None else per_channel.profiles,
        "seconds": None if per_channel is None else per_channel.seconds,
    }
    for name, slot in slots.items():
        if slot is not None:
            found[name] = (slot.text, slot.value, slot.hwnd, slot.owner_hwnd)
    return found


def bracket_numeric(before: ChannelsRead, after: ChannelsRead) -> NumericBracketing:
    """Pair each amount with the same amount read again after the capture.

    A number is only beside an image when the *same edit* stated the *same value* from the
    *same owning widget* before and after it, and when all five amounts are stated on both
    sides. A changed value, a changed edit handle, a changed owner, or a slot missing on
    either side is reported as inconsistent — this repository's rule that a mismatched
    observation is not averaged or picked from.

    Comparing handles refuses a pairing; it cannot prove the handles were *reused*, because a
    reuse that preserves every handle, value and owner is not observable from this read at all.
    """
    left = numeric_slots(before)
    right = numeric_slots(after)
    brackets: list[Bracket] = []
    for name in _SLOT_ORDER:
        if name not in left and name not in right:
            continue
        before_text, before_value, before_hwnd, before_owner = left.get(
            name, ("", None, None, None)
        )
        after_text, after_value, after_hwnd, after_owner = right.get(
            name, ("", None, None, None)
        )
        consistent = (
            name in left
            and name in right
            and before_text == after_text
            and before_value == after_value
            and before_hwnd == after_hwnd
            and before_owner == after_owner
            and before_value is not None
        )
        brackets.append(
            Bracket(
                slot=name,
                text_before=before_text,
                text_after=after_text,
                value_before=before_value,
                value_after=after_value,
                hwnd_before=before_hwnd,
                hwnd_after=after_hwnd,
                owner_before=before_owner,
                owner_after=after_owner,
                consistent=consistent,
            )
        )
    missing = [name for name in _SLOT_ORDER if name not in left or name not in right]
    changed = [b.slot for b in brackets if not b.consistent and b.slot not in missing]
    notes: list[str] = []
    if missing:
        notes.append(
            f"these amounts were not stated on both sides of the capture: {missing!r}; all of "
            f"{list(_SLOT_ORDER)!r} are required before any number is paired with the image"
        )
    if changed:
        notes.append(
            f"these amounts did not hold text, value, edit handle and owner across the "
            f"capture: {changed!r}"
        )
    return NumericBracketing(
        slots=tuple(brackets),
        consistent=not notes and all(b.consistent for b in brackets),
        note=(
            "; ".join(notes) + "; no number is paired with the image"
            if notes
            else (
                "all five numeric amounts were read twice from the same edit and owning widget; "
                "a handle comparison can only refuse a pairing — it cannot show that Windows "
                "did not reuse a handle for another window"
            )
        ),
    )


# ---------------------------------------------------------------------------------------------
# the assembler
# ---------------------------------------------------------------------------------------------


def assemble(
    *,
    roi: tuple[int, int, int, int] | None,
    frames: tuple[FrameEvidence, ...],
    guards: GuardComparison,
    numeric: NumericBracketing,
    capture_kind: Literal[
        "settings_numeric", "entry_no_numeric"
    ] = CAPTURE_SETTINGS_NUMERIC,
    readable: bool = True,
    after_readable: bool | None = None,
    refusals: tuple[str, ...] = (),
    directory: str | None = None,
    visual_caption: CaptionAttribution | None = None,
    visual_mode_mark: ModeMarkAttribution | None = None,
) -> CaptureEvidence:
    """One evidence record, with every failed check named and no caption invented.

    ``stable`` is only stated when two frames exist; with one frame it stays ``None`` (unknown)
    rather than ``True`` by default, because a single grab cannot witness that nothing moved.
    A structural report that refused part of the popup (``readable=False``) cannot produce an
    ``ok`` capture: the amounts it refused are exactly the ones a pairing would need.

    ``capture_kind`` selects the contract explicitly. ``settings_numeric`` keeps the existing
    requirement that all five amounts bracket consistently; ``entry_no_numeric`` requires that no
    amount was paired at all (``numeric.applicable`` false and no slots), because the clipped
    popup states none. Neither kind is inferred from the other, and the entry kind never relaxes
    the settings check.
    """
    reasons: list[str] = []
    if not readable:
        reasons.append(
            "the structural channels-read report is not readable, so a picture cannot be "
            "paired with a complete reading"
            + (f": {'; '.join(refusals)}" if refusals else "")
        )
    if after_readable is False:
        reasons.append(
            "the closing structural read is not readable, so the amounts after the capture are "
            "not a complete reading and nothing is paired"
        )
    if roi is None:
        reasons.append(
            "the structural report resolved no settings popup rectangle, so there is no ROI and "
            "no image was cropped: nothing is guessed at a bounding box"
        )
    if not frames:
        reasons.append("no frame was saved")
    if any(not frame.stats.non_blank for frame in frames):
        reasons.append(
            "a cropped frame is blank or one colour: it is a failed capture that would read as a "
            "successful one, so it is not evidence"
        )
    stable: bool | None = None
    if len(frames) >= 2:
        stable = frames[0].digest == frames[1].digest
        if not stable:
            reasons.append(
                "the two ROI frames differ: the popup was repainting while it was photographed, "
                "so the picture may hold a torn frame and the reading may belong to another moment"
            )
    else:
        reasons.append("fewer than two frames: two-frame stability was not established")
    if not guards.consistent:
        reasons.extend(guards.failures)
    expected_surface = (
        "multiplexer_on_entry"
        if capture_kind == CAPTURE_ENTRY_NO_NUMERIC
        else "settings_popup"
    )
    if guards.before.surface is not None and guards.before.surface != expected_surface:
        reasons.append(
            f"the capture is held to {capture_kind!r} but its before-guard read surface "
            f"{guards.before.surface!r} rather than {expected_surface!r}"
        )
    if capture_kind == CAPTURE_ENTRY_NO_NUMERIC:
        if numeric.applicable or numeric.slots:
            reasons.append(
                "an entry_no_numeric capture states no numeric settings amounts, and this one "
                "carries a numeric bracketing: the two contracts are not mixed"
            )
    elif not numeric.applicable:
        reasons.append(
            "a settings_numeric capture requires all five amounts bracketed, and this one "
            "declares the numeric contract inapplicable"
        )
    elif not numeric.consistent:
        reasons.append(numeric.note)
    return CaptureEvidence(
        status="ok" if not reasons else UNKNOWN,
        captured=bool(frames),
        roi=roi,
        capture_kind=capture_kind,
        directory=directory,
        frames=frames,
        stable=stable,
        guards=guards,
        numeric=numeric,
        visual_caption=visual_caption,
        visual_mode_mark=visual_mode_mark,
        unknown_reasons=tuple(reasons),
        uncertainties=(
            (
                "a capture is evidence about the moment it was taken, at the rectangle this read "
                "resolved; it establishes no mode, no tick and no installed configuration"
            ),
            (
                "a visual caption, when present, is pixels matched against committed glyph "
                "rasters: it is not what the application states, carries no action authority, "
                "and is limited to the digits those rasters were learned from"
            ),
            (
                "the ROI is the popup's whole rectangle: it is not glyph-aligned, so a later "
                "reader must locate text inside it rather than assume a field position"
            ),
            (
                "stability compares two frames of the same ROI; a screen that changed and "
                "changed back between the grabs is indistinguishable from a still one"
            ),
            (
                "the crop is a pixel copy of the virtual desktop as this interpreter sees it: "
                "at 100 % scaling that is 1:1, but at any other scaling a DPI-unaware process "
                "sees GetWindowRect and the bitmap virtualised together, so the crop lands "
                "approximately right and comes back resampled rather than wrong-sized; a grab "
                "whose bitmap size disagrees with the reported virtual screen is refused"
            ),
            (
                "the crop box is the popup rect minus the frame's reported virtual-screen "
                "origin; a backend that reports no origin is treated as the primary monitor at "
                "(0, 0), so a popup on a monitor left of or above the primary needs a backend "
                "that states the negative origin"
            ),
        ),
    )
