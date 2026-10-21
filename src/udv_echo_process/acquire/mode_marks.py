"""Read-only **visual attribution** of the MPX mode entry and its rollover mark.

This module answers two separate questions from pixels only, at two measured popup shapes:

===================================  =========  ============================  =====================
surface                              crop       mode-entry line                rollover row
===================================  =========  ============================  =====================
``SETTINGS_FULL``                    393 x 426  ``Enable multiplexer`` at      measured red cross
                                                rows 48-60, left 29, right 137 (OFF) or green
                                                                               check (ON)
``MULTIPLEXER_ON_ENTRY``             158 x 43   ``Desable multiplexer`` at     absent by structure
                                                rows 14-26, left 30, right 147
===================================  =========  ============================  =====================

The two shapes paint their line at **different** rows: the full popup's rows 14-26 carry the
separate ``Use only channel`` control's caption, which is *never* a mode-entry source. Each
surface therefore owns its own measured band (:data:`LABEL_BANDS`); there is no "first band"
fallback, because the first band of the full popup is a different control's line.

The shapes are named after what the tree says they are, not after the state this reader
derives: ``MULTIPLEXER_ON_ENTRY`` is the *clipped one-entry popup* that only exists while the
multiplexer is on, and the label the operator sees there is the literal ``Desable
multiplexer`` (sic). Neither name is a native fact.

Why this is not part of the caption reader
------------------------------------------
:mod:`udv_echo_process.acquire.caption_band` reads the group box's caption ``For the current
channel (channel N)``. This module reads the **mode-entry line** of the same dialog with a
closed two-string vocabulary. Different lines, different questions: neither imports the other
and neither widens the other's alphabet.

What each field means, and what it never means
----------------------------------------------
* every value here is a **visual attribution** — an exact **shape mask** matched against committed
  rasters, never a claim that the frame's RGB bytes equal the template's;
* ``native_fact`` is ``False`` and ``action_authority`` is ``False`` on every record, by
  construction: the application states no text for these lines and this reader presses nothing;
* ``mode`` is ``VISUAL_ENABLED`` / ``VISUAL_DISABLED`` / ``UNKNOWN``, never ``ENABLED``. The
  clipped entry's caption alone is a visual reading, not a checked state;
* ``rolling`` is a **separate** fact. On ``MULTIPLEXER_ON_ENTRY`` it is ``ABSENT``: that popup
  has no rollover row, so a read taken there states no rolling state at all. An unreadable mark
  never erases a readable label, and a readable label never licenses a press;
* ``acquisition_context`` and ``freshness`` are part of the record, because the same pixels mean
  different things on the two paths. A frame pair re-read from a retained capture directory is
  ``retained`` / ``not_established``: nothing in it proves *when* it was taken, and no timestamp
  or file mtime is consulted. Only the live capture path, whose two grabs bracket the numeric
  read on the same bound window, reports ``live-bracketed`` / ``live_bracketed``;
* ``integrity`` names what verified the pair: ``capture-digest-verified`` when genuine capture
  evidence digests were supplied and re-derived from the decoded pixels, ``decoded-pair-only``
  when only the pair itself was read (a retained directory: no capture record, no retained
  identity claim), ``not_established`` on a refusal;
* ``enable_precondition`` is a derived boolean and is **never** true for a retained read: the
  historical pair may well paint ``VISUAL_DISABLED`` and ``ON_PROVEN`` together, but history is
  evidence of what was painted, not a precondition for a press now.

A future enable needs a **fresh** ``SETTINGS_FULL`` read proving ``VISUAL_DISABLED`` *and*
``ON_PROVEN`` together — the conjunction, not the mark alone — taken in the same moment as the
decision. Nothing in this module performs, authorises or plans that press.

Purity: no Win32 binding, no Pillow import at module scope, no image is decoded at import time.
Pillow is imported inside :func:`load_frame`, which refuses any size that is not one of the two
measured shapes **from the header**, before ``load()``/``convert()``/allocation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from udv_echo_process.acquire import mode_marks_templates as stored
from udv_echo_process.models.base import ValueModel

__all__ = [
    "BACKGROUND",
    "ENABLE_LABEL_BAND",
    "ENTRY_FRAME",
    "ENTRY_LABEL_BAND",
    "ENTRY_SIZE",
    "GREEN_INK",
    "INK_MIN",
    "LABEL_BANDS",
    "MEASURED_SIZES",
    "MODE_ENTRY_LABELS",
    "MULTIPLEXER_ON_ENTRY",
    "PAIR_FILES",
    "ROLLOVER_BAND",
    "ROLLOVER_INK",
    "ROLLOVER_RECT",
    "SETTINGS_FULL",
    "SETTINGS_SIZE",
    "SIGNATURE",
    "USE_ONLY_CHANNEL_BAND",
    "FrameUnreadable",
    "ModeMarkAttribution",
    "attribute_capture",
    "attribute_frames",
    "build_templates",
    "is_entry_rect",
    "is_settings_rect",
    "load_frame",
    "recognize",
    "recognize_png",
    "surface_of",
]

#: Structural surface names, taken from the tree's own vocabulary.
SETTINGS_FULL = "SETTINGS_FULL"
MULTIPLEXER_ON_ENTRY = "MULTIPLEXER_ON_ENTRY"

#: The blocked-disable popup's own rectangle (the full settings sheet).
SETTINGS_SIZE = (393, 426)
#: The clipped one-entry popup's own rectangle.
ENTRY_SIZE = (158, 43)
#: Every shape this reader will decode. Nothing else is loaded, not even its header rows.
MEASURED_SIZES = (SETTINGS_SIZE, ENTRY_SIZE)

#: The clipped popup is the entry row plus a 3 px white frame on all sides.
ENTRY_FRAME = 3

#: The rollover mark's own rectangle and its two measured ink counts.
ROLLOVER_RECT = (215, 77, 228, 92)
ROLLOVER_INK = 70  # red cross, rolling OFF
GREEN_INK = 22  # green check, rolling ON

#: The **Enable multiplexer** row's label band of the full settings popup, popup-relative letter
#: bounds: the ink box of the line that toggle paints. Measured on both committed settings pairs
#: (``tests/data/mpx-mode/disabled-rolling-on`` and ``-off``, identical at this band): rows 48-60,
#: left 29, right 137 (so right-exclusive 138). This is the line the mode read and every target
#: rect are held to.
ENABLE_LABEL_BAND = (29, 48, 138, 61)
#: The **Use only channel** row of the same popup, rows 14-26, left 30, right 130 (exclusive 131).
#: It is a *different* control's caption and never a mode-entry source; it is named here so the
#: band a false template was once learned from is explicit, and so no read may fall back to it.
USE_ONLY_CHANNEL_BAND = (30, 14, 131, 27)
#: The clipped one-entry popup's own line — the literal ``Desable multiplexer`` — at rows 14-26,
#: left 30, right 147 (exclusive 148). Popup-relative, and *not* the full popup's rows 14-26.
ENTRY_LABEL_BAND = (30, 14, 148, 27)

#: ``surface -> its own measured label band``. The two shapes paint their line at different rows,
#: so neither may inherit the other's position, and there is no ordinal/first-band default.
LABEL_BANDS = {
    SETTINGS_FULL: ENABLE_LABEL_BAND,
    MULTIPLEXER_ON_ENTRY: ENTRY_LABEL_BAND,
}

#: The rollover row's mark band, as the band no Enable target rect may contain.
ROLLOVER_BAND = ROLLOVER_RECT

INK_MIN = 250
BACKGROUND = (64, 72, 112)


def _bands_overlap(
    one: tuple[int, int, int, int], other: tuple[int, int, int, int]
) -> bool:
    return not (
        one[2] <= other[0]
        or other[2] <= one[0]
        or one[3] <= other[1]
        or other[3] <= one[1]
    )


def _check_measured_bands() -> None:
    """Refuse an import whose label geometry would let one row stand for another.

    The full popup paints ``Use only channel`` at rows 14-26 and ``Enable multiplexer`` at rows
    48-60. A template learned from the first band and labelled with the second string is a
    semantic false proof — the popup would read ``VISUAL_DISABLED`` while the Enable line was
    absent. This is the structural guard, not a per-frame heuristic: the two bands must be
    disjoint, the Enable band must stay clear of the rollover mark, and every band must sit
    inside the popup it belongs to.
    """
    for surface, band in LABEL_BANDS.items():
        width, height = SETTINGS_SIZE if surface == SETTINGS_FULL else ENTRY_SIZE
        left, top, right, bottom = band
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError(
                f"the measured {surface} label band {band!r} is not inside its "
                f"{width}x{height} popup: the label geometry is not a measured one"
            )
    if _bands_overlap(ENABLE_LABEL_BAND, USE_ONLY_CHANNEL_BAND):
        raise ValueError(
            f"the Enable label band {ENABLE_LABEL_BAND!r} overlaps the Use only channel row "
            f"{USE_ONLY_CHANNEL_BAND!r}: one line would stand for the other"
        )
    if _bands_overlap(ENABLE_LABEL_BAND, ROLLOVER_BAND):
        raise ValueError(
            f"the Enable label band {ENABLE_LABEL_BAND!r} overlaps the rollover mark "
            f"{ROLLOVER_BAND!r}: the rollover row would be read as the Enable line"
        )


_check_measured_bands()

#: Carried on every record: which reader produced it and what it is allowed to mean. The ink
#: counts are read from the committed rasters themselves, so the string cannot drift from the
#: templates it describes.
SIGNATURE = (
    "mode-mark-v1 rect="
    f"{ROLLOVER_RECT[0]},{ROLLOVER_RECT[1]}-{ROLLOVER_RECT[2]},{ROLLOVER_RECT[3]} "
    + " ".join(f"{entry.mark.lower()}={entry.ink}px" for entry in stored.MARKS)
)

#: The closed vocabulary of the entry line, as the two exact strings the popup paints.
MODE_ENTRY_LABELS = {
    "ENABLE_MULTIPLEXER": "Enable multiplexer",
    "DESABLE_MULTIPLEXER": "Desable multiplexer",
}

#: ``surface -> mode-entry label -> derived mode``. The derivation is this module's own
#: reading of the measured strings; it is not a native state.
_LABEL_MODE = {
    (SETTINGS_FULL, "ENABLE_MULTIPLEXER"): "VISUAL_DISABLED",
    (MULTIPLEXER_ON_ENTRY, "DESABLE_MULTIPLEXER"): "VISUAL_ENABLED",
}


class FrameUnreadable(Exception):
    """A saved frame that cannot be read as one of the measured shapes."""


# ---------------------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------------------


class ModeLabelTemplate(ValueModel):
    """One committed mode-entry raster: its exact ink rows, box and provenance."""

    label: Literal["ENABLE_MULTIPLEXER", "DESABLE_MULTIPLEXER"]
    #: The one shape this raster was measured on. A raster is never reused across surfaces:
    #: the full popup's rows 14-26 belong to ``Use only channel``, not to this vocabulary.
    surface: Literal["SETTINGS_FULL", "MULTIPLEXER_ON_ENTRY"]
    rows: tuple[str, ...]
    box: tuple[int, int, int, int]
    ink: int
    source: str
    source_digest: str


class MarkTemplate(ValueModel):
    """One committed rollover-mark raster over :data:`ROLLOVER_RECT`."""

    mark: Literal["GREEN_CHECK", "RED_CROSS"]
    rows: tuple[str, ...]
    allow: str
    ink: int
    source: str
    source_digest: str


class TemplateSet(ValueModel):
    """The committed rasters and where each came from — never synthesised."""

    labels: tuple[ModeLabelTemplate, ...]
    marks: tuple[MarkTemplate, ...]
    sources: tuple[tuple[str, str], ...] = ()

    def label(self, name: str) -> ModeLabelTemplate:
        for template in self.labels:
            if template.label == name:
                return template
        raise KeyError(name)

    def mark(self, name: str) -> MarkTemplate:
        for template in self.marks:
            if template.mark == name:
                return template
        raise KeyError(name)


class ModeMarkAttribution(ValueModel):
    """What one still capture states about the mode entry and the rollover mark.

    ``mode`` and ``rolling`` are deliberately independent: a capture whose label was not
    recognised can still prove the rolling state, and a capture whose mark was not recognised
    can still read the label. Folding either into the other would invent a state the pixels do
    not state.
    """

    surface: Literal["SETTINGS_FULL", "MULTIPLEXER_ON_ENTRY", "UNSUPPORTED"] = (
        "UNSUPPORTED"
    )
    label: Literal["ENABLE_MULTIPLEXER", "DESABLE_MULTIPLEXER", "UNRECOGNIZED"] = (
        "UNRECOGNIZED"
    )
    mode: Literal["VISUAL_ENABLED", "VISUAL_DISABLED", "UNKNOWN"] = "UNKNOWN"
    mark: Literal["GREEN_CHECK", "RED_CROSS", "ABSENT", "UNRECOGNIZED", "NOT_READ"] = (
        "NOT_READ"
    )
    rolling: Literal["ON_PROVEN", "OFF_PROVEN", "ABSENT", "UNKNOWN"] = "UNKNOWN"
    #: Which path produced this record, and what that path can say about *when* it was taken.
    acquisition_context: Literal["retained", "live-bracketed", "unstated"] = "unstated"
    freshness: Literal["not_established", "live_bracketed"] = "not_established"
    #: What verified the pair. ``decoded-pair-only`` is the retained read: no capture record,
    #: no capture-time digest, and no retained capture identity is claimed.
    integrity: Literal[
        "not_established", "decoded-pair-only", "capture-digest-verified"
    ] = "not_established"
    #: Derived, and never true for a retained read: history is not a precondition for a press.
    #: Only a live-bracketed read that proves the ``VISUAL_DISABLED`` + ``ON_PROVEN``
    #: conjunction in one moment sets it, and even then this record grants no authority.
    enable_precondition: bool = False
    rect: tuple[int, int, int, int] | None = None
    label_box: tuple[int, int, int, int] | None = None
    label_digest: str | None = None
    mask_digest: str | None = None
    #: Verified pixel digests of the two frames, re-derived from decoded RGB — never asserted.
    frame_digests: tuple[str, str] | None = None
    frames_agreed: bool = False
    recognition: Literal["EXACT_TEMPLATE_MATCH", "NOT_MATCHED", "NOT_PERFORMED"] = (
        "NOT_PERFORMED"
    )
    signature: str = SIGNATURE
    source: Literal["visual_pixels"] = "visual_pixels"
    native_fact: Literal[False] = False
    action_authority: Literal[False] = False
    requires_operator_popup: Literal[True] = True
    unknown_reasons: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()


# ---------------------------------------------------------------------------------------------
# pixels — duck-typed, so the models build on a host without Pillow
# ---------------------------------------------------------------------------------------------


def _rows(image: object) -> list[list[tuple[int, int, int]]]:
    rgb = image.convert("RGB")  # type: ignore[attr-defined]
    width, height = int(rgb.width), int(rgb.height)  # type: ignore[attr-defined]
    raw = rgb.tobytes()  # type: ignore[attr-defined]
    return [
        [tuple(raw[i : i + 3]) for i in range(y * width * 3, (y + 1) * width * 3, 3)]
        for y in range(height)
    ]


def _is_ink(pixel: tuple[int, int, int]) -> bool:
    return pixel[0] >= INK_MIN and pixel[1] >= INK_MIN and pixel[2] >= INK_MIN


def _is_red(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return r >= 200 and g < 80 and b < 80


def _is_green(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel
    return g > 120 and r < 120 and b < 120


_MARK_PREDICATE = {"GREEN_CHECK": _is_green, "RED_CROSS": _is_red}


def _digest(mask: list[bool]) -> str:
    return hashlib.sha256(bytes(1 if value else 0 for value in mask)).hexdigest()


def _mask(rows, top: int, bottom: int, left: int, right: int, predicate) -> list[bool]:
    return [
        predicate(rows[y][x]) for y in range(top, bottom) for x in range(left, right)
    ]


def _frame_inset(rows) -> int:
    """The white frame's thickness, measured: equal on all four sides, else ``0``."""
    height, width = len(rows), len(rows[0])
    limit = min(height, width) // 4
    thickness = 0
    for inset in range(limit):
        edges = (
            all(_is_ink(rows[inset][x]) for x in range(width)),
            all(_is_ink(rows[height - 1 - inset][x]) for x in range(width)),
            all(_is_ink(rows[y][inset]) for y in range(height)),
            all(_is_ink(rows[y][width - 1 - inset]) for y in range(height)),
        )
        if not all(edges):
            break
        thickness = inset + 1
    return thickness


def _bands(rows) -> list[tuple[int, int, int, int]]:
    """Ink bands of the frame interior, as ``(top, bottom, left, right)``."""
    height, width = len(rows), len(rows[0])
    inset = _frame_inset(rows) or 1
    bands: list[tuple[int, int, int, int]] = []
    open_band: list[int] | None = None
    for y in range(inset, height - inset):
        xs = [x for x in range(inset, width - inset) if _is_ink(rows[y][x])]
        if xs:
            if open_band is None:
                open_band = [y, y, min(xs), max(xs)]
            else:
                open_band[1] = y
                open_band[2] = min(open_band[2], min(xs))
                open_band[3] = max(open_band[3], max(xs))
        elif open_band is not None:
            bands.append(tuple(open_band))  # type: ignore[arg-type]
            open_band = None
    if open_band is not None:
        bands.append(tuple(open_band))  # type: ignore[arg-type]
    return bands


def surface_of(image: object) -> tuple[str, tuple[str, ...]]:
    """The shape this frame is, structurally — and the facts the verdict rests on.

    Only size, frame thickness and band count are consulted. Nothing about the *content* of
    the entry line or the mark is a surface fact, so an erased mark is a mark reading
    (``UNRECOGNIZED``/``NOT_READ``) rather than an unsupported surface.
    """
    rows = _rows(image)
    height, width = len(rows), len(rows[0])
    size = (width, height)
    facts = [
        f"size={width}x{height}",
        f"bg={BACKGROUND[0]},{BACKGROUND[1]},{BACKGROUND[2]}",
    ]
    frame = _frame_inset(rows)
    if frame:
        facts.append(f"frame={frame}")
    bands = _bands(rows)
    if bands:
        facts.append(f"bands={len(bands)}")
        facts.append(f"label_rows={bands[0][0]}-{bands[0][1]}")
        facts.append(f"label_left={bands[0][2]}")
    if size == SETTINGS_SIZE and frame == ENTRY_FRAME and len(bands) > 1:
        return SETTINGS_FULL, tuple(facts)
    if size == ENTRY_SIZE and frame == ENTRY_FRAME and len(bands) == 1:
        return MULTIPLEXER_ON_ENTRY, tuple(facts)
    return "UNSUPPORTED", tuple(facts)


# ---------------------------------------------------------------------------------------------
# templates and the bounded loader
# ---------------------------------------------------------------------------------------------


def _read_bounded(path: Path) -> object:
    """Decode one saved crop, refusing a non-measured size from its header.

    Pillow is imported here: a host without the ``acquire`` extra gets a typed refusal, not an
    ``ImportError`` at import time. The size check runs on the header ``Image.open`` has
    already parsed, **before** ``load()``/``convert()`` or any allocation, so a 4000x4000 PNG
    costs one header read rather than a decode.
    """
    try:
        from PIL import Image  # the ``acquire`` extra
    except ImportError as exc:
        raise FrameUnreadable(
            f"Pillow is not installed, so no saved frame can be decoded: install the "
            f"'acquire' extra ({exc})"
        ) from exc
    try:
        with Image.open(path) as opened:
            size = (int(opened.size[0]), int(opened.size[1]))
            if size not in MEASURED_SIZES:
                raise FrameUnreadable(
                    f"the crop is {size[0]}x{size[1]}, not one of the measured shapes "
                    f"{list(MEASURED_SIZES)!r}: refused from its header before decode, because "
                    "this reader measures those two sizes and no other bound applies"
                )
            opened.load()
            image = opened.convert("RGB")
    except FrameUnreadable:
        raise
    except (OSError, ValueError) as exc:
        raise FrameUnreadable(f"the saved frame could not be read: {exc}") from exc
    return image


def load_frame(path: str | Path) -> object:
    """One saved crop as an RGB image, or :class:`FrameUnreadable`."""
    return _read_bounded(Path(path))


def is_settings_rect(rect: tuple[int, int, int, int] | None) -> bool:
    """Whether a crop rectangle is exactly the measured settings popup shape.

    Used by the capture path to decide whether a mode read belongs beside the numbers at all:
    a crop of another size has no rollover row to read, so no mark is reported from it.
    """
    if rect is None:
        return False
    return (rect[2] - rect[0], rect[3] - rect[1]) == SETTINGS_SIZE


def is_entry_rect(rect: tuple[int, int, int, int] | None) -> bool:
    """Whether a crop rectangle is exactly the measured clipped one-entry popup shape.

    The enabled entry popup is the only other shape this module has templates for. The size is
    measured here, in the module that owns the templates, so the capture path never restates
    158x43 and a caller cannot admit an arbitrary crop by claiming it is "the small one".
    """
    if rect is None:
        return False
    return (rect[2] - rect[0], rect[3] - rect[1]) == ENTRY_SIZE


def _ascii(mask: list[bool], width: int) -> tuple[str, ...]:
    return tuple(
        "".join("X" if value else "." for value in mask[start : start + width])
        for start in range(0, len(mask), width)
    )


def _label_box(rows, surface: str) -> tuple[int, int, int, int]:
    """The measured label line's own ink box **on this surface**, bounded by its frame.

    The band is looked up per surface: the full settings popup's Enable line is rows 48-60 while
    the clipped entry's ``Desable`` line is rows 14-26. Nothing here scans for "the first band"
    — on the full popup that band is the ``Use only channel`` caption, a different control's
    line, and treating it as the mode entry is exactly the false proof this geometry excludes.
    """
    if surface not in LABEL_BANDS:
        raise FrameUnreadable(f"{surface!r} has no measured label band")
    left, top, right_measured, bottom = LABEL_BANDS[surface]
    inset = _frame_inset(rows) or 1
    right = left
    for x in range(left, len(rows[0]) - inset):
        if any(_is_ink(rows[y][x]) for y in range(top, bottom)):
            right = x + 1
    if right == left:
        raise FrameUnreadable(
            f"the measured {surface} label band {LABEL_BANDS[surface]!r} holds no ink: the "
            "line is absent or was repainted, so no mode-entry string is read there"
        )
    if any(_is_ink(rows[y][x]) for y in range(top, bottom) for x in range(inset, left)):
        raise FrameUnreadable(
            "ink sits left of the measured label margin: this is not the measured layout"
        )
    if right > right_measured:
        raise FrameUnreadable(
            f"the {surface} label ink runs to x={right} past the measured band "
            f"{LABEL_BANDS[surface]!r}: a longer or shifted string is not this line"
        )
    return (left, top, right, bottom)


def build_templates(
    labels: dict[str, tuple[str | Path, str]],
    marks: dict[str, tuple[str | Path, str, str]],
) -> TemplateSet:
    """Learn every raster from its own measured frame; a missing file is a hard error.

    ``labels`` maps a vocabulary name to ``(path, surface)``; ``marks`` maps a mark name to
    ``(path, predicate, ink)``. Nothing is thresholded, interpolated or normalised: the
    template *is* the measured mask at the measured box or rect, so position is part of it.
    """
    learned_labels: list[ModeLabelTemplate] = []
    for name, (path, surface) in labels.items():
        rows = _rows(_read_bounded(Path(path)))
        if surface_of(_as_image(rows))[0] != surface:
            raise FrameUnreadable(
                f"{Path(path).name} is not the measured {surface} shape"
            )
        if (surface, name) not in _LABEL_MODE:
            raise FrameUnreadable(f"{name} is not a measured label of {surface}")
        box = _label_box(rows, surface)
        mask = _mask(rows, box[1], box[3], box[0], box[2], _is_ink)
        expected = MODE_ENTRY_LABELS[name]
        learned_labels.append(
            ModeLabelTemplate(
                label=name,  # type: ignore[arg-type]
                surface=surface,  # type: ignore[arg-type]
                rows=_ascii(mask, box[2] - box[0]),
                box=box,
                ink=sum(mask),
                source=expected,
                source_digest=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            )
        )
    learned_marks: list[MarkTemplate] = []
    for name, (path, allow, ink) in marks.items():
        rows = _rows(_read_bounded(Path(path)))
        left, top, right, bottom = ROLLOVER_RECT
        mask = _mask(rows, top, bottom, left, right, _MARK_PREDICATE[name])
        if sum(mask) != ink:
            raise FrameUnreadable(
                f"the {name} mark holds {sum(mask)} ink pixels in {Path(path).name}, not the "
                f"measured {ink}: the training frame changed"
            )
        learned_marks.append(
            MarkTemplate(
                mark=name,  # type: ignore[arg-type]
                rows=_ascii(mask, right - left),
                allow=allow,
                ink=sum(mask),
                source=f"measured {allow} at {ROLLOVER_RECT!r}",
                source_digest=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            )
        )
    return TemplateSet(
        labels=tuple(learned_labels),
        marks=tuple(learned_marks),
        sources=tuple(
            (template.label, template.source_digest) for template in learned_labels
        )
        + tuple((template.mark, template.source_digest) for template in learned_marks),
    )


def _as_image(rows) -> object:
    """A duck-typed image view over already-decoded rows (avoids a second decode)."""

    class _Decoded:
        width = len(rows[0])
        height = len(rows)

        def convert(self, _mode: str) -> _Decoded:
            return self

        def tobytes(self) -> bytes:
            return bytes(channel for row in rows for pixel in row for channel in pixel)

    return _Decoded()


TEMPLATES = TemplateSet(
    labels=tuple(
        ModeLabelTemplate(
            label=entry.label,
            surface=entry.surface,
            rows=entry.rows,
            box=entry.box,
            ink=entry.ink,
            source=entry.source,
            source_digest=entry.source_digest,
        )
        for entry in stored.LABELS
    ),
    marks=tuple(
        MarkTemplate(
            mark=entry.mark,
            rows=entry.rows,
            allow=entry.allow,
            ink=entry.ink,
            source=entry.source,
            source_digest=entry.source_digest,
        )
        for entry in stored.MARKS
    ),
    sources=stored.SOURCES,
)


# ---------------------------------------------------------------------------------------------
# recognition
# ---------------------------------------------------------------------------------------------


def _unknown(reason: str, *more: str, **update) -> ModeMarkAttribution:
    return ModeMarkAttribution(
        unknown_reasons=(reason, *more),
        **update,
    )


def _read_label(
    rows, surface: str
) -> tuple[str, tuple[int, int, int, int], str, list[str]]:
    band = LABEL_BANDS.get(surface)
    if band is None:
        return (
            "UNRECOGNIZED",
            (0, 0, 0, 0),
            "",
            [f"{surface!r} has no measured label band"],
        )
    try:
        box = _label_box(rows, surface)
    except FrameUnreadable as exc:
        return (
            "UNRECOGNIZED",
            band,
            "",
            [str(exc)],
        )
    mask = _mask(rows, box[1], box[3], box[0], box[2], _is_ink)
    raster = _ascii(mask, box[2] - box[0])
    for name in MODE_ENTRY_LABELS:
        if (surface, name) not in _LABEL_MODE:
            continue
        template = TEMPLATES.label(name)
        if (
            template.surface == surface
            and template.box == box
            and template.rows == raster
        ):
            return name, box, _digest(mask), []
    return (
        "UNRECOGNIZED",
        box,
        _digest(mask),
        [
            (
                f"the raster at the measured {surface} label band {box} equals neither string "
                f"measured on that surface ({sorted(n for s, n in _LABEL_MODE if s == surface)!r}): "
                "an absent, altered, translated or swapped caption — including the "
                "`Use only channel` line at another row — is not read as the mode entry"
            )
        ],
    )


def _read_mark(rows, surface: str) -> tuple[str, str, str | None, list[str]]:
    """``(mark, rolling, mask_digest, reasons)`` for one decoded frame."""
    if surface != SETTINGS_FULL:
        return (
            "ABSENT",
            "ABSENT",
            None,
            [
                (
                    "the clipped entry popup has no rollover row by structure: a read taken "
                    "here states no rolling state at all, and this is not the enabled surface's "
                    "missing mark"
                )
            ],
        )
    left, top, right, bottom = ROLLOVER_RECT
    red = _mask(rows, top, bottom, left, right, _is_red)
    green = _mask(rows, top, bottom, left, right, _is_green)
    if any(red) and any(green):
        return (
            "UNRECOGNIZED",
            "UNKNOWN",
            _digest(red + green),
            [
                (
                    "both the red cross and the green check are painted inside "
                    f"{ROLLOVER_RECT}: two contradictory marks state no single rolling state"
                )
            ],
        )
    for name, mask in (("GREEN_CHECK", green), ("RED_CROSS", red)):
        if not any(mask):
            continue
        template = TEMPLATES.mark(name)
        if template.rows == _ascii(mask, right - left):
            return (
                name,
                "ON_PROVEN" if name == "GREEN_CHECK" else "OFF_PROVEN",
                _digest(mask),
                [],
            )
        return (
            "UNRECOGNIZED",
            "UNKNOWN",
            _digest(mask),
            [
                (
                    f"ink at {ROLLOVER_RECT} is {sum(mask)} pixels and is not the measured "
                    f"{name} ({template.ink} pixels at this rect): a shifted, repainted or "
                    "elsewhere-green shape states no rolling state"
                )
            ],
        )
    return (
        "UNRECOGNIZED",
        "UNKNOWN",
        None,
        [
            (
                f"{ROLLOVER_RECT} holds no measured mark: an erased or repainted mark states "
                "no rolling state"
            )
        ],
    )


def _attribute(image: object) -> ModeMarkAttribution:
    surface, facts = surface_of(image)
    if surface == "UNSUPPORTED":
        return _unknown(
            (
                f"the crop is none of the measured shapes {list(MEASURED_SIZES)!r} with a "
                f"3 px frame: measured {facts!r}"
            ),
        )
    rows = _rows(image)
    label, box, label_digest, label_reasons = _read_label(rows, surface)
    mark, rolling, mask_digest, mark_reasons = _read_mark(rows, surface)
    mode = _LABEL_MODE.get((surface, label), "UNKNOWN")
    reasons = list(label_reasons) + list(mark_reasons)
    uncertainties: list[str] = []
    if surface == MULTIPLEXER_ON_ENTRY:
        uncertainties.append(
            "the enabled mode rests on the clipped entry's caption alone: that popup carries "
            "no checked state, no rollover row and no machine-readable text"
        )
    if rolling == "ABSENT":
        uncertainties.append(
            "no rolling state in this popup: the only measured enabled shape is the clipped "
            "one-entry popup, which structurally contains no rollover row"
        )
    if mode == "UNKNOWN" and label_reasons:
        uncertainties.append(
            "the mode is unknown, so no mode-dependent action is supported by this record"
        )
    matched_label = mode != "UNKNOWN"
    matched_mark = rolling in {"ON_PROVEN", "OFF_PROVEN"}
    # The clipped entry has no rollover row, so its mark region is never attempted and its
    # recognition rests on the entry line alone. On the settings shape both regions are read,
    # so a garbled label beside a structurally absent mark is ``NOT_MATCHED`` rather than an
    # exact match — the ABSENT rolling state is a fact about the shape, not about the label.
    complete = (
        matched_label
        if surface == MULTIPLEXER_ON_ENTRY
        else matched_label and matched_mark
    )
    return ModeMarkAttribution(
        surface=surface,  # type: ignore[arg-type]
        label=label,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        mark=mark,  # type: ignore[arg-type]
        rolling=rolling,  # type: ignore[arg-type]
        rect=ROLLOVER_RECT if surface == SETTINGS_FULL else None,
        label_box=box,
        label_digest=label_digest,
        mask_digest=mask_digest,
        recognition="EXACT_TEMPLATE_MATCH" if complete else "NOT_MATCHED",
        unknown_reasons=tuple(reasons),
        uncertainties=tuple(uncertainties),
    )


def recognize(image: object) -> ModeMarkAttribution:
    """Attribute one decoded frame. Pure: no file, no path, no identity in the result."""
    return _attribute(image)


def recognize_png(path: str | Path) -> ModeMarkAttribution:
    """Attribute one saved crop, refusing a non-measured size from its header."""
    try:
        return _attribute(_read_bounded(Path(path)))
    except FrameUnreadable as exc:
        return _unknown(str(exc))


def _load_pair(paths: tuple[str, ...]) -> tuple[list[object], list[str], list[str]]:
    """Decode the first two frames **once**: ``(images, re-derived digests, problems)``."""
    from udv_echo_process.acquire.channels_capture import digest as frame_digest

    images: list[object] = []
    actual: list[str] = []
    problems: list[str] = []
    for index, path in enumerate((paths[0], paths[1]), start=1):
        try:
            image = _read_bounded(Path(path))
        except FrameUnreadable as exc:
            problems.append(f"frame {index}: {exc}")
            continue
        images.append(image)
        actual.append(frame_digest(image))
    return images, actual, problems


def _attribute_pair(
    images: list[object],
    actual: list[str],
    *,
    acquisition_context: Literal["retained", "live-bracketed", "unstated"],
    integrity: Literal["decoded-pair-only", "capture-digest-verified"],
) -> ModeMarkAttribution:
    """The one pair-state machine, shared by the retained and live reads.

    The caller has already decoded both frames exactly once and has already held the pair to
    whatever digest evidence its context supplied; this function adds no second decode and no
    second identity claim of its own.
    """
    if actual[0] != actual[1]:
        return _unknown(
            (
                f"the two frames' decoded pixel digests differ ({actual[0][:12]} vs "
                f"{actual[1][:12]}): the popup was repainting, so neither frame is a still "
                "moment and no mode or rolling state is attributed"
            ),
            frame_digests=(actual[0], actual[1]),  # type: ignore[arg-type]
            acquisition_context=acquisition_context,
            integrity="not_established",  # type: ignore[arg-type]
        )
    first = _attribute(images[0])
    second = _attribute(images[1])
    if _comparable(first) != _comparable(second):
        return _unknown(
            (
                f"the pair is unstable: frame 1 reads surface={first.surface!r} "
                f"label={first.label!r} mark={first.mark!r} and frame 2 reads "
                f"surface={second.surface!r} label={second.label!r} mark={second.mark!r}, so "
                "this capture states no single popup state"
            ),
            frame_digests=(actual[0], actual[1]),  # type: ignore[arg-type]
            frames_agreed=False,
            acquisition_context=acquisition_context,
            integrity="not_established",  # type: ignore[arg-type]
        )
    # The conjunction is the whole precondition: a disabled mode *and* a proven rolling mark,
    # read in the same moment, on a pair those very frames verified. A proven mark alone, a
    # disabled label alone, or either one re-read from a retained directory is not one.
    precondition = (
        acquisition_context == "live-bracketed"
        and integrity == "capture-digest-verified"
        and first.mode == "VISUAL_DISABLED"
        and first.rolling == "ON_PROVEN"
    )
    context_note = (
        "two frames were decoded, each supplied digest was re-derived from its RGB pixels and "
        "matched, and both read the same surface, label and mark"
        if integrity == "capture-digest-verified"
        else (
            "the pair was decoded and agreed, but no capture record or capture-time digest was "
            "consulted: this is decoded-pair-only evidence with no retained capture identity "
            "claim and no freshness claim"
        )
    )
    return first.model_copy(
        update={
            "frame_digests": (actual[0], actual[1]),
            "frames_agreed": True,
            "acquisition_context": acquisition_context,
            "freshness": (
                "live_bracketed"
                if acquisition_context == "live-bracketed"
                else "not_established"
            ),
            "integrity": integrity,
            "enable_precondition": precondition,
            "uncertainties": (*first.uncertainties, context_note),
        }
    )


def attribute_frames(
    paths: tuple[str, ...],
    digests: tuple[str, ...],
    *,
    context: Literal["live-bracketed", "unstated"] = "unstated",
) -> ModeMarkAttribution:
    """Attribute one read from **two** frames that must state the same exact thing.

    This is the entry point a *live* capture path uses, and it passes ``context="live-bracketed"``
    only because its own two grabs bracket the numeric read on one bound window. Each supplied
    digest is re-derived from the decoded RGB pixels with the capture path's own
    :func:`~udv_echo_process.acquire.channels_capture.digest` — an asserted digest is not
    evidence — and the pair is refused when the two digests differ, when either digest was
    forged, when the path and digest counts disagree, when a frame is not a measured shape, or
    when the two readings disagree. A pair that disagrees is reported ``UNKNOWN`` rather than
    resolved in favour of the later frame: a popup that repainted between the grabs states no
    single state.
    """
    if len(paths) != 2 or len(digests) != 2:
        return _unknown(
            (
                f"a two-frame check needs exactly two frame paths and two digests, and this "
                f"call supplied {len(paths)} and {len(digests)}: a pair that is not one path "
                "per digest states no mode or rolling state"
            ),
            acquisition_context=context,  # type: ignore[arg-type]
        )
    images, actual, problems = _load_pair(paths)
    if problems:
        return _unknown(
            "the two-frame check did not produce two readable measured frames",
            *problems,
            acquisition_context=context,  # type: ignore[arg-type]
        )
    if actual[0] != actual[1]:
        return _attribute_pair(
            images,
            actual,
            acquisition_context=context,
            integrity="capture-digest-verified",
        )
    for index, (expected, got) in enumerate(zip(digests, actual, strict=True), start=1):
        if expected != got:
            return _unknown(
                (
                    f"the supplied digest for frame {index} ({str(expected)[:12]}) does not "
                    f"match the decoded pixels ({got[:12]}): an asserted digest is not "
                    "evidence, so no two-frame agreement is claimed"
                ),
                frame_digests=(actual[0], actual[1]),  # type: ignore[arg-type]
                acquisition_context=context,  # type: ignore[arg-type]
            )
    return _attribute_pair(
        images,
        actual,
        acquisition_context=context,
        integrity="capture-digest-verified",
    )


def _comparable(attribution: ModeMarkAttribution) -> tuple[object, ...]:
    """Every field a two-frame agreement stands on."""
    return (
        attribution.surface,
        attribution.label,
        attribution.label_digest,
        attribution.mark,
        attribution.mask_digest,
        attribution.mode,
        attribution.rolling,
    )


#: The two file names the capture contract writes into a claimed run directory.
PAIR_FILES = ("channels-roi-frame-1.png", "channels-roi-frame-2.png")


def attribute_capture(directory: str | Path) -> ModeMarkAttribution:
    """Attribute a **retained** capture directory: two frames, either measured shape.

    This is the read-only boundary the ``mpx-mode-read`` command uses, and it says what it is:
    ``acquisition_context="retained"``, ``freshness="not_established"`` and
    ``integrity="decoded-pair-only"``. The directory is whatever the existing capture contract
    retained (its guards, exclusive run-directory claim, virtual-screen origin and
    partial-retention behaviour are unchanged and already applied at capture time), and this
    function only reads those two files **once**. There is no external capture record here — no
    capture-time digest to compare against, no trusted timestamp — so the pair's own decoded
    content is all the identity this read claims; a file's mtime is never consulted as age.
    ``enable_precondition`` is therefore always ``False``: even a pair painting
    ``VISUAL_DISABLED`` with ``ON_PROVEN`` is history, not a licence to press.

    A ``MULTIPLEXER_ON_ENTRY`` directory is read with **no** numeric settings bracketing: that
    popup has no numeric settings fields, and the shape is established structurally (measured
    size, 3 px frame, exactly one band) rather than by loosening the settings capture's own
    ``status == ok`` meaning.
    """
    root = Path(directory)
    paths = tuple(str(root / name) for name in PAIR_FILES)
    missing = [Path(path).name for path in paths if not Path(path).exists()]
    if missing:
        return _unknown(
            f"the capture pair is incomplete in {root.name!r}: {missing!r} are missing, so "
            "no mode or rolling state is attributed",
            acquisition_context="retained",
        )
    images, actual, problems = _load_pair(paths)
    if problems:
        return _unknown(
            "the retained capture did not produce two readable measured frames",
            *problems,
            acquisition_context="retained",
        )
    return _attribute_pair(
        images,
        actual,
        acquisition_context="retained",
        integrity="decoded-pair-only",
    )
