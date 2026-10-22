"""Fail-closed recognition of the Channels popup's **painted caption line**.

The popup's group box captions the amounts it holds with one painted line —
``For the current channel (channel N)`` — and its widgets state no text at all (ledger B15:
``WM_GETTEXT`` returns the empty string), so the line exists as *paint* or not at all. This
module reads that one line out of a saved popup crop and returns a **visual attribution**:

* it is **not a native fact** — the application stated nothing, and no pixel read may be
  promoted into what the application says;
* it carries **no action authority** — nothing here presses, selects, opens or writes, and no
  gesture may be derived from it;
* it is **not** the caller's declaration, and never derived from one: the operator's stated
  channel, the plan, and the bracketed amounts are all absent from this module's inputs. Only
  the crop's pixels are read.

What is matched, and why only the caption band
----------------------------------------------
The popup's numbers (``Repeat``, ``Profiles``, ``seconds``, the two combos) and its top-row
circles change **independently** of the selected channel, so matching a whole popup answers
"is this the same dialog state", not "which channel is this dialog for". Only the caption
line names the channel, so only the caption line is matched, at exact measured geometry.

Fail closed, by construction
----------------------------
Every step is a verification against a measured constant, never a search for a best fit:

1. the crop must be the measured popup size (``393x426``) — another scale is ``UNKNOWN``, and
   for a saved frame that is checked from the PNG header **before** anything is decoded, so an
   oversized file is never loaded, converted or allocated (the measured popup *is* the cap);
2. the group box's top rule must sit at the measured rows and reach the measured right edge;
3. the caption's ink must be exactly the measured 13-row block with the measured left edge;
4. the constant prefix must be a **pixel-identical** raster match — the font/scale/layout
   signature, where a single differing pixel refuses;
5. each digit must be pixel-identical to a raster learned from a measured capture, at the
   measured 7 px pitch, followed by the ``)`` raster at its measured offset;
6. the digits must spell one of the **photographed** channels ``{1, 2, 10}``. The glyphs
   ``{0, 1, 2}`` can compose other strings, but a channel that was never photographed is
   ``UNKNOWN`` rather than read.

There is no nearest neighbour, no distance threshold and no probability: a glyph either equals
a learned raster exactly or the line is ``UNKNOWN``. That is what stops an untrained digit
(``3``-``9`` are **not** supported here) from being read as its closest visual neighbour.

When it may run
---------------
:func:`attribute_frames` is the only entry point for evidence: it needs **two** frames whose
digests agree and whose readings are identical, and it refuses everything else. The capture
path (:mod:`udv_echo_process.acquire.channels_read`) calls it only after its own
``status == "ok"`` / ``stable`` verdict, so a recognition never stands on an unstable or
unattributed grab.

Dependencies: numpy only, at module scope. Pillow is imported inside the two functions that
open a PNG (:func:`recognize_png`, :func:`build_templates`), so the models, the templates and
every test of the algorithm build on a host without the ``acquire`` extra.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import numpy as np

from udv_echo_process.acquire import caption_band_templates as stored
from udv_echo_process.models.base import ValueModel

__all__ = [
    "BAND_ROWS",
    "DIGIT_PITCH",
    "DIGIT_START",
    "MAX_DIGITS",
    "POPUP_SIZE",
    "PROVENANCE",
    "SIGNATURE",
    "SUPPORT",
    "SUPPORTED_CHANNELS",
    "TEMPLATES",
    "CaptionAttribution",
    "GlyphRead",
    "GlyphTemplate",
    "TemplateSet",
    "attribute_frames",
    "build_templates",
    "recognize",
    "recognize_png",
]

# ---------------------------------------------------------------------------------------------
# the measured geometry — read off four retained captures of one 393x426 popup, which agree
# exactly in every band used here (channel 1, channel 2, channel 10 and a return to channel 1)
# ---------------------------------------------------------------------------------------------

#: The popup crop's size: the capture path crops the popup panel's own rectangle.
POPUP_SIZE = (393, 426)

#: Text is pure white on the popup's flat background — measured: exactly two colours in the band.
_INK_MIN = 250

#: The caption's ink block, inclusive rows, and its left edge (the parentheses descend to 275).
BAND_ROWS = (263, 275)
TEXT_LEFT = 88

#: The group box's top rule (two rows) and the right edge it must reach: the structural anchor
#: that says "this line is the group box's caption", not some other text.
RULE_ROWS = (281, 282)
RULE_RIGHT = 382
_RULE_MIN_RUN = 300

#: The band is read inside the popup's own white frame, so a frame pixel is never caption ink.
_LEFT_WINDOW = 20
_RIGHT_WINDOW = 386

#: Digit cells: the first cell's ink starts at 279 and cells advance by 7 px. At most two
#: digits are supported because two is the widest ever observed; three is outside support.
DIGIT_START = 279
DIGIT_PITCH = 7
MAX_DIGITS = 2

#: The channels whose caption line was actually photographed. The digit rasters can compose
#: other strings (``0``, ``11``, ``20`` …), but only a channel seen in a measured capture is
#: ever *read*: a composed channel is UNKNOWN, never inferred by neighbourhood.
SUPPORTED_CHANNELS = ("1", "2", "10")

#: The ``)`` after the digits starts one pixel left of the cell that follows the last digit.
_SUFFIX_OFFSET = -1

#: Everything this line's shape is, in one string, so a report can be compared by eye.
SIGNATURE = (
    f"caption-band-v1 popup={POPUP_SIZE[0]}x{POPUP_SIZE[1]} rows={BAND_ROWS[0]}-{BAND_ROWS[1]} "
    f"left={TEXT_LEFT} rule={RULE_ROWS[0]}-{RULE_ROWS[1]} right={RULE_RIGHT} "
    f"digit_start={DIGIT_START} pitch={DIGIT_PITCH} max_digits={MAX_DIGITS} exact-raster"
)

#: What the learned templates can and cannot support — stated on every report.
SUPPORT = (
    "channels {1,2,10} only: glyphs {0,1,2} learned from the channel 1, channel 2 and channel 10 "
    "captures. A band whose learned glyphs compose another string (0, 11, 12, 20, 21, 22) is "
    "UNKNOWN, because that channel was never photographed; digits 3-9, three-digit captions, "
    "other fonts, other scales and other popup sizes are NOT supported, and no channel outside "
    "{1,2,10} is inferred"
)

PROVENANCE = (
    "visual attribution: the caption line's pixels in these frames were matched exactly against "
    "glyph rasters learned from the named measured captures. The application states no text for "
    "this widget, so this is not a native fact, and it carries no action authority - it may not "
    "be used to press, select, open or write. The operator's stated channel, a plan's declaration "
    "and the bracketed amounts were not inputs to this reading, so this neither confirms nor "
    "replaces any of them"
)


# ---------------------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------------------


class GlyphTemplate(ValueModel):
    """One learned glyph: its exact ink raster and the measured capture it came from."""

    glyph: str
    rows: tuple[str, ...]
    box: tuple[int, int, int, int]
    source: str
    source_digest: str

    @property
    def width(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    @property
    def height(self) -> int:
        return len(self.rows)

    def raster(self) -> np.ndarray:
        """The template as a boolean ink raster, built once per call from its committed rows."""
        return np.array([[ch == "X" for ch in row] for row in self.rows], dtype=bool)

    def digest(self) -> str:
        """The raster's digest — the identity a report quotes for "this exact glyph"."""
        return hashlib.sha256(self.raster().tobytes()).hexdigest()


class TemplateSet(ValueModel):
    """The learned set: one constant prefix, the closing parenthesis, and the digits."""

    prefix: GlyphTemplate
    suffix: GlyphTemplate
    digits: dict[str, GlyphTemplate]
    training: tuple[str, ...]

    @property
    def alphabet(self) -> tuple[str, ...]:
        return tuple(sorted(self.digits))

    def without(self, *glyphs: str) -> TemplateSet:
        """The same set minus some digits — how a test removes support without inventing it."""
        return TemplateSet(
            prefix=self.prefix,
            suffix=self.suffix,
            digits={
                glyph: template
                for glyph, template in self.digits.items()
                if glyph not in glyphs
            },
            training=self.training,
        )

    def digests(self) -> tuple[tuple[str, str], ...]:
        """``(id, digest)`` for every raster in the set, in a stable order."""
        items = [("prefix", self.prefix.digest()), ("suffix", self.suffix.digest())]
        items += [
            (f"digit:{glyph}", self.digits[glyph].digest()) for glyph in self.alphabet
        ]
        return tuple(items)


class GlyphRead(ValueModel):
    """One glyph of a recognised line: where it was, and which learned raster it equals."""

    glyph: str
    box: tuple[int, int, int, int]
    template_source: str
    template_digest: str
    exact: Literal[True] = True


class CaptionAttribution(ValueModel):
    """The caption line as evidence: a visual attribution, and nothing stronger.

    ``status`` is ``RECOGNIZED`` only when every check passed exactly and, for
    :func:`attribute_frames`, when two frames said the same thing. Everything else is
    ``UNKNOWN`` with a named reason. The two boolean fields are ``Literal[False]`` so no
    consumer can construct a version of this report that claims more.
    """

    status: Literal["RECOGNIZED", "UNKNOWN"] = "UNKNOWN"
    #: The channel the **pixels** name. Not a native fact and not the caller's declaration.
    channel: int | None = None
    caption: str | None = None
    digits: str | None = None
    band_box: tuple[int, int, int, int] | None = None
    band_digest: str | None = None
    prefix_digest: str | None = None
    suffix_digest: str | None = None
    glyphs: tuple[GlyphRead, ...] = ()
    #: ``(id, digest)`` for every template the set could have matched — the oracle's identity.
    template_digests: tuple[tuple[str, str], ...] = ()
    #: The captures the templates were learned from — names and content digests, no machine ids.
    template_sources: tuple[tuple[str, str], ...] = ()
    #: The captured frames' crop digests; two entries only when two frames were compared.
    frame_digests: tuple[str, ...] = ()
    frames_agreed: bool | None = None
    source: Literal["visual_pixels", "NONE"] = "NONE"
    signature: str = SIGNATURE
    support: str = SUPPORT
    provenance: str = PROVENANCE
    native_fact: Literal[False] = False
    action_authority: Literal[False] = False
    recognition: Literal["EXACT_TEMPLATE_MATCH", "NOT_PERFORMED"] = "NOT_PERFORMED"
    diagnostics: tuple[str, ...] = ()
    unknown_reasons: tuple[str, ...] = ()


def _template(entry: stored._Template) -> GlyphTemplate:
    return GlyphTemplate(
        glyph=entry.glyph,
        rows=tuple(entry.rows),
        box=tuple(entry.box),  # type: ignore[arg-type]
        source=entry.source,
        source_digest=entry.source_digest,
    )


#: The committed rasters, rebuilt from the generated data module at import — never learned here.
TEMPLATES = TemplateSet(
    prefix=_template(stored.PREFIX),
    suffix=_template(stored.SUFFIX),
    digits={glyph: _template(entry) for glyph, entry in stored.DIGITS.items()},
    training=tuple(stored.TRAINING),
)


# ---------------------------------------------------------------------------------------------
# pixels — duck-typed, so a real grab and a test double are read by the same code
# ---------------------------------------------------------------------------------------------


def _size(image: object) -> tuple[int, int]:
    size = getattr(image, "size", None)
    if isinstance(size, tuple) and len(size) == 2:
        return int(size[0]), int(size[1])
    return int(image.width), int(image.height)  # type: ignore[attr-defined]


def _ink_mask(image: object) -> np.ndarray:
    """Pure-white ink, measured on the popup's flat background; no threshold is guessed.

    The image must be 8-bit RGB: a mode conversion here would be a resampling step this
    reader has not measured, so a caller converts and the wrong mode is a refusal upstream.
    """
    mode = str(getattr(image, "mode", "RGB") or "RGB")
    if mode != "RGB":
        raise ValueError(
            f"the frame states mode {mode!r}: this reader measures 8-bit RGB only"
        )
    width, height = _size(image)
    raw = image.tobytes()  # type: ignore[attr-defined]
    if len(raw) != width * height * 3:
        raise ValueError(
            f"the frame's {len(raw)} bytes are not {width}x{height} RGB pixels: a partial or "
            "padded buffer is not the measured popup"
        )
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
    return np.all(rgb >= _INK_MIN, axis=2)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _longest_run(row: np.ndarray) -> tuple[int, int] | None:
    xs = np.nonzero(row)[0]
    if xs.size == 0:
        return None
    best_start = best_end = int(xs[0])
    start = prev = int(xs[0])
    for x in xs[1:]:
        x = int(x)
        if x == prev + 1:
            prev = x
            continue
        if prev - start > best_end - best_start:
            best_start, best_end = start, prev
        start = prev = x
    if prev - start > best_end - best_start:
        best_start, best_end = start, prev
    return best_start, best_end


def _component_runs(mask: np.ndarray, start: int, stop: int) -> list[tuple[int, int]]:
    """Column runs holding ink, in ``[start, stop)`` — glyph inks never touch in this font."""
    runs: list[tuple[int, int]] = []
    open_at: int | None = None
    for x in range(start, stop):
        here = bool(mask[:, x].any())
        if here and open_at is None:
            open_at = x
        elif not here and open_at is not None:
            runs.append((open_at, x - 1))
            open_at = None
    if open_at is not None:
        runs.append((open_at, stop - 1))
    return runs


# ---------------------------------------------------------------------------------------------
# learning — the path the committed templates were produced by, re-run by the tests
# ---------------------------------------------------------------------------------------------


def _open_capture(path: Path) -> tuple[object, np.ndarray]:
    from PIL import Image  # the ``acquire`` extra, imported only where a PNG is read

    image = Image.open(path)
    if image.size != POPUP_SIZE:
        raise ValueError(
            f"{path.name}: {image.size} is not the measured popup {POPUP_SIZE}"
        )
    image.load()
    rgb = image.convert("RGB")
    return rgb, _ink_mask(rgb)


def _from_mask(
    mask: np.ndarray,
    glyph: str,
    box: tuple[int, int, int, int],
    source: str,
    source_digest: str,
) -> GlyphTemplate:
    left, top, right, bottom = box
    return GlyphTemplate(
        glyph=glyph,
        rows=tuple(
            "".join("X" if v else "." for v in row)
            for row in mask[top:bottom, left:right]
        ),
        box=box,
        source=source,
        source_digest=source_digest,
    )


def build_templates(training: dict[str, tuple[Path, str]]) -> TemplateSet:
    """Learn the prefix, the suffix and one raster per digit from labelled captures.

    ``training`` maps a capture id to ``(path, operator_stated_channel)``. The label is the
    **operator's statement** and it does nothing but select which measured glyph becomes which
    digit template — it is never read as the recognition's answer. Geometry is not searched; a
    capture that does not sit on the measured constants is rejected outright.
    """
    prefix: GlyphTemplate | None = None
    suffix: GlyphTemplate | None = None
    digits: dict[str, GlyphTemplate] = {}
    sources: list[str] = []
    for name, (path, label) in training.items():
        _, mask, digest = (*_open_capture(path), _file_digest(path))
        top = BAND_ROWS[0]
        prefix_box = (TEXT_LEFT, top, DIGIT_START - 1, BAND_ROWS[1] + 1)
        candidate = _from_mask(mask, "", prefix_box, name, digest)
        if prefix is None:
            prefix = candidate
        elif candidate.rows != prefix.rows:
            raise ValueError(
                f"{name}: the caption prefix is not pixel-identical to {prefix.source}; the "
                "training captures disagree about the layout, so no template is built"
            )
        if not label.isdigit():
            raise ValueError(
                f"{name}: the stated channel {label!r} is not a digit string"
            )
        width = DIGIT_START + DIGIT_PITCH * len(label) + _SUFFIX_OFFSET
        runs = _component_runs(mask[top : BAND_ROWS[1] + 1], DIGIT_START, width + 8)
        digit_runs = [run for run in runs if run[1] < width]
        suffix_runs = [run for run in runs if run[0] >= width]
        if len(digit_runs) != len(label) or len(suffix_runs) != 1:
            raise ValueError(
                f"{name}: expected {len(label)} digit run(s) and one suffix run at the measured "
                f"geometry, measured {digit_runs!r} and {suffix_runs!r}"
            )
        for glyph, (run_left, run_right) in zip(label, digit_runs, strict=True):
            box = (run_left, top, run_right + 1, BAND_ROWS[1] + 1)
            template = _from_mask(mask, glyph, box, name, digest)
            known = digits.get(glyph)
            if known is None:
                digits[glyph] = template
            elif known.rows != template.rows:
                raise ValueError(
                    f"{name}: digit {glyph!r} is not pixel-identical to the one learned from "
                    f"{known.source}; two captures disagree, so the glyph is not trusted"
                )
        close_left, close_right = suffix_runs[0]
        close = _from_mask(
            mask,
            ")",
            (close_left, top, close_right + 1, BAND_ROWS[1] + 1),
            name,
            digest,
        )
        if suffix is None:
            suffix = close
        elif suffix.rows != close.rows:
            raise ValueError(
                f"{name}: the closing parenthesis differs from {suffix.source}"
            )
        sources.append(name)
    if prefix is None or suffix is None or not digits:
        raise ValueError("no training captures: nothing can be learned")
    return TemplateSet(
        prefix=prefix, suffix=suffix, digits=digits, training=tuple(sources)
    )


# ---------------------------------------------------------------------------------------------
# recognition
# ---------------------------------------------------------------------------------------------


def _expected_band(
    templates: TemplateSet, digits: str
) -> tuple[np.ndarray, tuple[GlyphRead, ...]]:
    """The exact raster a caption with ``digits`` would paint, plus its glyph provenance."""
    prefix = templates.prefix.raster()
    height = prefix.shape[0]
    suffix_col = (DIGIT_START - TEXT_LEFT) + DIGIT_PITCH * len(digits) + _SUFFIX_OFFSET
    width = suffix_col + templates.suffix.width
    expected = np.zeros((height, width), dtype=bool)
    expected[:, : prefix.shape[1]] = prefix
    glyphs: list[GlyphRead] = []
    for index, glyph in enumerate(digits):
        template = templates.digits[glyph]
        col = (DIGIT_START - TEXT_LEFT) + DIGIT_PITCH * index
        raster = template.raster()
        expected[:, col : col + raster.shape[1]] = raster
        glyphs.append(
            GlyphRead(
                glyph=glyph,
                box=(
                    TEXT_LEFT + col,
                    BAND_ROWS[0],
                    TEXT_LEFT + col + raster.shape[1],
                    BAND_ROWS[0] + height,
                ),
                template_source=template.source,
                template_digest=template.digest(),
            )
        )
    suffix = templates.suffix.raster()
    expected[:, suffix_col : suffix_col + suffix.shape[1]] = suffix
    return expected, tuple(glyphs)


def _sources(templates: TemplateSet) -> tuple[tuple[str, str], ...]:
    ids = {templates.prefix.source, templates.suffix.source}
    ids.update(template.source for template in templates.digits.values())
    digests = {
        templates.prefix.source: templates.prefix.source_digest,
        templates.suffix.source: templates.suffix.source_digest,
    }
    for template in templates.digits.values():
        digests[template.source] = template.source_digest
    return tuple((name, digests[name]) for name in sorted(ids))


def _base(templates: TemplateSet) -> CaptionAttribution:
    return CaptionAttribution(
        template_digests=templates.digests(),
        template_sources=_sources(templates),
        prefix_digest=templates.prefix.digest(),
        suffix_digest=templates.suffix.digest(),
    )


def _unknown(
    read: CaptionAttribution, *reasons: str, diagnostics: tuple[str, ...] = ()
) -> CaptionAttribution:
    return read.model_copy(
        update={
            "status": "UNKNOWN",
            "channel": None,
            "caption": None,
            "digits": None,
            "glyphs": (),
            "source": "NONE",
            "recognition": "NOT_PERFORMED",
            "unknown_reasons": tuple(reasons),
            "diagnostics": diagnostics,
        }
    )


def recognize(image: object, templates: TemplateSet = TEMPLATES) -> CaptionAttribution:
    """Match the caption line in one popup crop, or refuse — there is no third outcome."""
    base = _base(templates)
    try:
        width, height = _size(image)
        if (width, height) != POPUP_SIZE:
            return _unknown(
                base,
                f"the crop is {width}x{height}, the measured popup is "
                f"{POPUP_SIZE[0]}x{POPUP_SIZE[1]}: this is a different scale or a partial crop, "
                "and no measured layout applies",
            )
        mask = _ink_mask(image)
    except (ValueError, TypeError) as exc:
        return _unknown(
            base, f"the frame could not be read as the measured popup: {exc}"
        )
    if not mask.any():
        return _unknown(
            base,
            "the crop holds no ink at all: it is one flat colour, so it is a failed capture "
            "rather than a caption, and nothing is read from it",
        )
    top, bottom = BAND_ROWS
    for row in RULE_ROWS:
        rule = _longest_run(mask[row])
        if rule is None or rule[0] > 25 or rule[1] < RULE_RIGHT:
            return _unknown(
                base,
                f"the group box's top rule is not at measured row {row} (measured {rule!r}); the "
                "popup's structure changed, so the caption band is not where it was measured",
            )
    rules = [
        y
        for y in range(200, RULE_ROWS[0])
        if (run := _longest_run(mask[y])) is not None
        and run[1] - run[0] + 1 >= _RULE_MIN_RUN
    ]
    lower = max(rules) if rules else 200  # the separator directly above the group box
    ink_rows = [
        y
        for y in range(lower + 1, RULE_ROWS[0])
        if mask[y, _LEFT_WINDOW:_RIGHT_WINDOW].any()
    ]
    block = (min(ink_rows), max(ink_rows)) if ink_rows else None
    if block != (top, bottom) or len(ink_rows) != bottom - top + 1:
        return _unknown(
            base,
            f"the caption ink block is {block!r} over {len(ink_rows)} row(s), not the measured "
            f"{BAND_ROWS}; the line was moved, cut or re-rendered",
        )
    band_mask = mask[top : bottom + 1, _LEFT_WINDOW:_RIGHT_WINDOW]
    columns = band_mask.nonzero()[1]
    left = _LEFT_WINDOW + int(columns.min()) if columns.size else -1
    if left != TEXT_LEFT:
        return _unknown(
            base,
            f"the caption starts at x={left}, not the measured x={TEXT_LEFT}; the text or the "
            "font was shifted and no template applies",
        )
    band = band_mask[:, TEXT_LEFT - _LEFT_WINDOW :]
    tight_right = int(np.nonzero(band.any(axis=0))[0].max()) + 1
    band_digest = hashlib.sha256(band[:, :tight_right].tobytes()).hexdigest()
    read = base.model_copy(
        update={
            "band_box": (TEXT_LEFT, top, TEXT_LEFT + tight_right, bottom + 1),
            "band_digest": band_digest,
        }
    )
    prefix = templates.prefix.raster()
    if band[:, : prefix.shape[1]].tobytes() != prefix.tobytes():
        return _unknown(
            read,
            "the constant prefix is not pixel-identical to the learned one: the font, scale or "
            "wording changed, and no digit is read from a band whose fixed text moved",
        )
    exact: list[tuple[str, tuple[GlyphRead, ...]]] = []
    for length in range(1, MAX_DIGITS + 1):
        for combo in _products(templates.alphabet, length):
            digits = "".join(combo)
            expected, glyphs = _expected_band(templates, digits)
            if expected.shape[1] > band.shape[1]:
                continue
            mismatch = int((expected != band[:, : expected.shape[1]]).sum())
            extra = bool(band[:, expected.shape[1] :].any())
            if mismatch == 0 and not extra:
                exact.append((digits, glyphs))
    candidates = [pair for pair in exact if pair[0] in SUPPORTED_CHANNELS]
    if not candidates:
        if exact:
            composed = ", ".join(digits for digits, _ in exact)
            return _unknown(
                read,
                "the band's glyphs are pixel-identical to learned rasters and compose "
                f"channel {composed}, but that channel was never photographed: only channels "
                "1, 2 and 10 are supported, so a composed caption is UNKNOWN rather than read "
                "as some neighbouring channel",
            )
        widths = sorted(
            {
                (DIGIT_START - TEXT_LEFT)
                + DIGIT_PITCH * n
                + _SUFFIX_OFFSET
                + templates.suffix.width
                for n in range(1, MAX_DIGITS + 2)
            }
        )
        near = f"the band is {tight_right} px wide where the trained shapes are {widths} px"
        return _unknown(
            read,
            "no trained caption matches this band exactly: every glyph must be pixel-identical "
            f"to a learned one, and none is ({near}). A digit outside {templates.alphabet}, a "
            "different font or any repaint is UNKNOWN rather than the closest match",
        )
    if len(candidates) > 1:
        return _unknown(
            read,
            "two trained captions match the band exactly "
            f"({[digits for digits, _ in candidates]!r}): an ambiguous band is UNKNOWN, never "
            "picked",
        )
    digits, glyphs = candidates[0]
    return read.model_copy(
        update={
            "status": "RECOGNIZED",
            "channel": int(digits),
            "caption": f"For the current channel (channel {digits})",
            "digits": digits,
            "glyphs": glyphs,
            "source": "visual_pixels",
            "recognition": "EXACT_TEMPLATE_MATCH",
            "diagnostics": (
                (
                    f"band {tight_right}x{bottom - top + 1} px at ({TEXT_LEFT},{top}); "
                    f"prefix, {len(digits)} digit(s) and suffix all pixel-identical to the "
                    "learned rasters"
                ),
            ),
        }
    )


def _products(alphabet: tuple[str, ...], length: int):
    """``itertools.product`` without importing it just for a two-deep loop."""
    from itertools import product

    return product(alphabet, repeat=length)


class _FrameUnreadable(Exception):
    """A saved frame that cannot be read — carries the named reason, never a bare crash."""


def _read_saved_frame(path: Path) -> object:
    """Decode one saved popup crop as RGB, refusing a non-measured size from its header.

    Pillow is imported here — the ``acquire`` extra is only needed where a PNG is read, and a
    host without it gets a typed refusal rather than an ``ImportError``. The size check runs on
    the header that ``Image.open`` has already read, **before** ``load()``/``convert()`` or any
    array allocation, so an oversized or wrong-shaped file costs no decode.
    """
    try:
        from PIL import Image  # the ``acquire`` extra
    except ImportError as exc:
        raise _FrameUnreadable(
            "Pillow is not installed, so no saved frame can be decoded: install the 'acquire' "
            f"extra ({exc})"
        ) from exc
    try:
        with Image.open(path) as opened:
            size = (int(opened.size[0]), int(opened.size[1]))
            if size != POPUP_SIZE:
                raise _FrameUnreadable(
                    f"{path.name} is {size[0]}x{size[1]}, not the measured popup "
                    f"{POPUP_SIZE[0]}x{POPUP_SIZE[1]}: the frame was refused from its header, "
                    "before it was decoded, because this reader measures one size only and no "
                    "bound other than the measured popup applies"
                )
            opened.load()
            image = opened.convert("RGB")
    except (OSError, ValueError) as exc:
        raise _FrameUnreadable(
            f"the saved frame {path.name} could not be read: {exc}"
        ) from exc
    return image


def recognize_png(
    path: str | Path, templates: TemplateSet = TEMPLATES
) -> CaptionAttribution:
    """Recognise one saved popup crop from disk.

    The file's digest is **not** carried into the report: the evidence's provenance is the
    capture's own crop digest and the template digests, and a filesystem path is machine
    identity that a portable report must not carry.
    """
    try:
        image = _read_saved_frame(Path(path))
    except _FrameUnreadable as exc:
        return _unknown(_base(templates), str(exc))
    return recognize(image, templates)


def attribute_frames(
    paths: tuple[str, ...],
    digests: tuple[str, ...],
    templates: TemplateSet = TEMPLATES,
) -> CaptionAttribution:
    """Attribute one caption from **two** frames that must say the same exact thing.

    This is the only entry point the capture path uses. It re-derives each frame's pixel digest
    with the capture path's own :func:`~udv_echo_process.acquire.channels_capture.digest` and
    refuses when a supplied digest does not match the decoded RGB pixels — a digest the caller
    merely asserts is not evidence. It also refuses a single frame, a pair whose decoded pixels
    differ, and a pair where either reading is ``UNKNOWN``: a caption that cannot be reproduced
    from a second frame of proved-identical pixels is not evidence, whatever the first frame
    said. ``frame_digests`` carries the **verified** pixel digests; ``band_digest`` stays the
    honoured band's own identity.
    """
    base = _base(templates)
    if len(paths) < 2 or len(digests) < 2:
        return _unknown(
            base,
            "fewer than two frames: a caption read from one grab cannot be checked against "
            "itself, so no attribution is made",
        )
    from udv_echo_process.acquire.channels_capture import digest as frame_digest

    images: list[object] = []
    actual: list[str] = []
    problems: list[str] = []
    for index, path in enumerate((paths[0], paths[1]), start=1):
        try:
            image = _read_saved_frame(Path(path))
        except _FrameUnreadable as exc:
            problems.append(f"frame {index}: {exc}")
            continue
        images.append(image)
        actual.append(frame_digest(image))
    if problems:
        return _unknown(
            base,
            "the two-frame check did not produce two identical readings, so the caption is "
            "UNKNOWN rather than taken from the frame that happened to match",
            *problems,
        )
    if actual[0] != actual[1]:
        return _unknown(
            base,
            f"the two frames' decoded pixel digests differ ({actual[0][:12]} vs "
            f"{actual[1][:12]}): the popup was repainting, so neither frame is a still "
            "moment and no caption is attributed",
        )
    for index, (expected, got) in enumerate(zip(digests, actual, strict=True), start=1):
        if expected != got:
            return _unknown(
                base,
                f"the supplied digest for frame {index} ({str(expected)[:12]}) does not match "
                f"the decoded pixels ({got[:12]}): an asserted digest is not evidence, so no "
                "two-frame agreement is claimed",
            )
    first = recognize(images[0], templates)
    second = recognize(images[1], templates)
    if first.status != "RECOGNIZED" or second.status != "RECOGNIZED":
        sides = (
            f"frame 1: {first.unknown_reasons or 'recognised'}",
            f"frame 2: {second.unknown_reasons or 'recognised'}",
        )
        return _unknown(
            base.model_copy(
                update={"band_digest": first.band_digest or second.band_digest}
            ),
            "the two-frame check did not produce two identical readings, so the caption is "
            "UNKNOWN rather than taken from the frame that happened to match",
            *sides,
        )
    # Equal, independently re-derived pixel digests make the two readings identical by
    # construction, so a "the frames read different captions" branch could never fire: the
    # pixel comparison above is the check that used to be approximated by comparing readings.
    return first.model_copy(
        update={
            "frame_digests": (actual[0], actual[1]),
            "frames_agreed": True,
            "diagnostics": (
                *first.diagnostics,
                (
                    "two frames were decoded, each supplied digest was re-derived from its "
                    "RGB pixels and matched, and both read the same channel and the same "
                    "band digest"
                ),
            ),
        }
    )
