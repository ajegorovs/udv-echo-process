"""Boundary tests for :mod:`udv_echo_process.acquire.mode_marks` and its two consumers.

The fixtures in ``tests/data/mpx-mode/`` are the operator's **real** recorded popup crops,
copied and renamed (``disabled-rolling-on``, ``disabled-rolling-off``,
``entry-clipped-enabled``) so the report vocabulary carries no machine identity. Two of the
three pairs are training sources and the third is read only as a holdout surface, so the
reader is exercised on frames that never contributed a raster.

Pillow is optional here as well as in the module: the core model tests import and build
without it, and only the pixel cases ask for the ``acquire`` extra.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from udv_echo_process.acquire import mode_marks
from udv_echo_process.acquire.channels_capture import digest as frame_digest

DATA = Path(__file__).parent / "data" / "mpx-mode"
ON = DATA / "disabled-rolling-on"
OFF = DATA / "disabled-rolling-off"
ENTRY = DATA / "entry-clipped-enabled"

pytest.importorskip("PIL", reason="the acquire extra decodes the recorded fixtures")


def _pair(directory: Path) -> tuple[str, ...]:
    return tuple(str(directory / name) for name in mode_marks.PAIR_FILES)


def _digests(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(frame_digest(mode_marks.load_frame(path)) for path in paths)


def _read(directory: Path) -> mode_marks.ModeMarkAttribution:
    paths = _pair(directory)
    return mode_marks.attribute_frames(paths, _digests(paths))


# ---------------------------------------------------------------------------------------------
# the core stays importable without Pillow or Win32
# ---------------------------------------------------------------------------------------------


def test_core_imports_without_pillow_or_win32(monkeypatch):
    """No module-scope Pillow decode and no Win32 import: the model is host-independent."""
    import sys

    for name in ("PIL", "PIL.Image", "win32gui", "win32api"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    attribution = mode_marks.ModeMarkAttribution(mode="UNKNOWN")
    assert attribution.native_fact is False
    assert attribution.action_authority is False
    assert attribution.requires_operator_popup is True
    assert (
        json.loads(attribution.model_dump_json())["signature"] == mode_marks.SIGNATURE
    )


# ---------------------------------------------------------------------------------------------
# the two measured positives
# ---------------------------------------------------------------------------------------------


def test_disabled_popup_with_rolling_on_reads_visual_disabled_and_on_proven():
    record = _read(ON)
    assert record.surface == "SETTINGS_FULL"
    assert record.label == "ENABLE_MULTIPLEXER"
    assert record.mode == "VISUAL_DISABLED"
    assert record.mark == "GREEN_CHECK"
    assert record.rolling == "ON_PROVEN"
    assert record.frames_agreed is True
    assert record.recognition == "EXACT_TEMPLATE_MATCH"
    assert record.native_fact is False and record.action_authority is False
    # The mode is derived from the label; the string "ENABLED" is never a value here.
    assert record.mode not in {"ENABLED", "DISABLED"}


def test_holdout_off_pair_reads_off_proven_and_is_not_a_training_source():
    """The rolling-OFF pair is a separate real capture; each record states its own provenance."""
    assert all(len(digest) == 64 for _name, digest in mode_marks.TEMPLATES.sources)
    assert {name for name, _digest in mode_marks.TEMPLATES.sources} == {
        "ENABLE_MULTIPLEXER",
        "DESABLE_MULTIPLEXER",
        "GREEN_CHECK",
        "RED_CROSS",
    }
    record = _read(OFF)
    assert record.mode == "VISUAL_DISABLED"
    assert record.rolling == "OFF_PROVEN"
    assert record.mark == "RED_CROSS"


def test_clipped_entry_states_the_mode_and_no_rolling_state():
    """The clipped popup is structural: mode from the caption, rolling ``ABSENT`` by shape."""
    record = _read(ENTRY)
    assert record.surface == mode_marks.MULTIPLEXER_ON_ENTRY
    assert record.label == "DESABLE_MULTIPLEXER"
    assert record.mode == "VISUAL_ENABLED"
    assert record.mark == "ABSENT"
    assert record.rolling == "ABSENT"
    assert record.rect is None  # no rollover row exists to name a rect for
    assert record.frames_agreed is True


def test_clipped_entry_is_structural_not_a_relaxed_settings_capture():
    """A clipped-shaped frame that is not exactly the measured structure is unsupported."""
    image = mode_marks.load_frame(ENTRY / "channels-roi-frame-1.png")
    surface, _facts = mode_marks.surface_of(image)
    assert surface == mode_marks.MULTIPLEXER_ON_ENTRY
    # The settings reader's own three sizes/guards are untouched: this module adds no shape.
    assert mode_marks.SETTINGS_SIZE not in {(image.width, image.height)}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------------------------
# refusals: a pixel, a shape, a rect, a pair
# ---------------------------------------------------------------------------------------------


def _changed(image, x: int, y: int, pixel: tuple[int, int, int]):
    """A copy of a decoded fixture with one pixel replaced — no fixture is written."""

    copy = image.copy()
    copy.putpixel((x, y), pixel)
    return copy


def test_one_changed_label_pixel_is_unrecognised_but_the_mark_still_reads():
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    rows = mode_marks._rows(image)
    box = mode_marks._label_box(rows, mode_marks.SETTINGS_FULL)
    # The first background pixel of the line: painting it ink changes exactly one mask cell.
    spot = next(
        (x, y)
        for y in range(box[1], box[3])
        for x in range(box[0], box[2])
        if not mode_marks._is_ink(rows[y][x])
    )
    altered = _changed(image, spot[0], spot[1], (255, 255, 255))
    record = mode_marks.recognize(altered)
    assert record.label == "UNRECOGNIZED"
    assert record.mode == "UNKNOWN"
    # The two facts stay independent: the label failing does not erase the rolling read.
    assert record.rolling == "ON_PROVEN"


def test_one_changed_mark_pixel_is_an_unmeasured_mark_not_a_rolling_state():
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    left, top, _right, _bottom = mode_marks.ROLLOVER_RECT
    altered = _changed(image, left + 6, top + 7, (255, 0, 0))
    record = mode_marks.recognize(altered)
    assert record.mark == "UNRECOGNIZED"
    assert record.rolling == "UNKNOWN"
    assert record.mode == "VISUAL_DISABLED"  # the readable label survives
    assert record.unknown_reasons


def test_mark_shifted_inside_the_rect_does_not_match():
    """Position is part of the template: the same ink one pixel over is not the mark."""
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    left, top, right, bottom = mode_marks.ROLLOVER_RECT
    shifted = image.crop((0, 0, image.width, image.height))  # type: ignore[attr-defined]
    from PIL import Image

    block = image.crop((left, top, right, bottom))  # type: ignore[attr-defined]
    shifted.paste(
        Image.new("RGB", (right - left, bottom - top), (64, 72, 112)), (left, top)
    )
    shifted.paste(block, (left + 1, top))
    record = mode_marks.recognize(shifted)
    assert record.mark == "UNRECOGNIZED"
    assert record.rolling == "UNKNOWN"


def test_mark_at_another_rect_is_not_read_as_this_mark():
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    left, top, right, bottom = mode_marks.ROLLOVER_RECT
    from PIL import Image

    moved = image.crop((0, 0, image.width, image.height))  # type: ignore[attr-defined]
    block = image.crop((left, top, right, bottom))  # type: ignore[attr-defined]
    moved.paste(
        Image.new("RGB", (right - left, bottom - top), (64, 72, 112)), (left, top)
    )
    moved.paste(block, (left + 40, top))
    record = mode_marks.recognize(moved)
    assert record.mark == "UNRECOGNIZED"
    assert record.rolling == "UNKNOWN"


def test_both_marks_painted_is_a_conflict_not_a_tie_break():
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    left, top, right, bottom = mode_marks.ROLLOVER_RECT

    conflicting = image
    base = conflicting.load()  # type: ignore[attr-defined]
    other = mode_marks.load_frame(OFF / "channels-roi-frame-1.png").load()
    painted = 0
    for y in range(top, bottom):
        for x in range(left, right):
            if mode_marks._is_red(other[x, y]):
                base[x, y] = other[x, y]
                painted += 1
    assert painted == mode_marks.ROLLOVER_INK
    record = mode_marks.recognize(conflicting)
    assert record.mark == "UNRECOGNIZED"
    assert record.rolling == "UNKNOWN"


def test_unstable_pair_is_refused_rather_than_resolved_to_the_later_frame():
    paths = (
        str(ON / "channels-roi-frame-1.png"),
        str(ENTRY / "channels-roi-frame-1.png"),
    )
    record = mode_marks.attribute_frames(paths, _digests(paths))
    assert record.frames_agreed is False
    assert record.mode == "UNKNOWN" and record.rolling == "UNKNOWN"
    assert any(
        "differ" in reason or "readable" in reason for reason in record.unknown_reasons
    )


def test_incomplete_pair_is_refused(tmp_path: Path):
    (tmp_path / "channels-roi-frame-1.png").write_bytes(
        (ON / "channels-roi-frame-1.png").read_bytes()
    )
    record = mode_marks.attribute_capture(tmp_path)
    assert record.mode == "UNKNOWN"
    assert any("incomplete" in reason for reason in record.unknown_reasons)


def test_forged_digest_is_not_evidence():
    paths = _pair(ON)
    asserted = (hashlib.sha256(b"not the pixels").hexdigest(),) * 2
    record = mode_marks.attribute_frames(paths, asserted)
    assert record.mode == "UNKNOWN"
    assert any(
        "does not match the decoded pixels" in reason
        for reason in record.unknown_reasons
    )


def test_identity_drift_between_the_two_frames_is_caught_by_re_derived_digests():
    """A frame swapped for a different real popup: digests differ, nothing is attributed."""
    paths = (
        str(ON / "channels-roi-frame-1.png"),
        str(OFF / "channels-roi-frame-1.png"),
    )
    supplied = _digests(
        _pair(ON)
    )  # the capture's own digests, both from frame 1's pixels
    record = mode_marks.attribute_frames(paths, supplied)
    assert record.mode == "UNKNOWN" and record.rolling == "UNKNOWN"
    assert record.unknown_reasons


def test_header_bounds_refuse_a_non_measured_size_before_decode(tmp_path: Path):
    from PIL import Image

    oversized = tmp_path / "channels-roi-frame-1.png"
    Image.new("RGB", (2000, 2000), (64, 72, 112)).save(oversized)
    with pytest.raises(mode_marks.FrameUnreadable) as raised:
        mode_marks.load_frame(oversized)
    assert "header" in str(raised.value)
    assert "not one of the measured shapes" in str(raised.value)
    record = mode_marks.recognize_png(oversized)
    assert record.surface == "UNSUPPORTED" and record.mode == "UNKNOWN"


def test_missing_or_unreadable_frame_is_a_named_refusal(tmp_path: Path):
    record = mode_marks.recognize_png(tmp_path / "absent.png")
    assert record.mode == "UNKNOWN"
    assert record.unknown_reasons


# ---------------------------------------------------------------------------------------------
# provenance: the committed rasters are exactly what the fixtures produce
# ---------------------------------------------------------------------------------------------


def test_committed_templates_re_derive_from_the_measured_fixtures():
    """Relearn every raster from the fixtures and compare it with the committed module."""
    labels = {
        "ENABLE_MULTIPLEXER": (
            ON / "channels-roi-frame-1.png",
            mode_marks.SETTINGS_FULL,
        ),
        "DESABLE_MULTIPLEXER": (
            ENTRY / "channels-roi-frame-1.png",
            mode_marks.MULTIPLEXER_ON_ENTRY,
        ),
    }
    marks = {
        "GREEN_CHECK": (
            ON / "channels-roi-frame-1.png",
            "green-check",
            mode_marks.GREEN_INK,
        ),
        "RED_CROSS": (
            OFF / "channels-roi-frame-1.png",
            "red-cross",
            mode_marks.ROLLOVER_INK,
        ),
    }
    relearned = mode_marks.build_templates(labels, marks)
    assert relearned.model_dump() == mode_marks.TEMPLATES.model_dump()
    assert mode_marks.TEMPLATES.sources == relearned.sources


def test_recognition_is_not_matched_when_the_only_rollover_fact_is_structural_absence():
    """M1: an ``ABSENT`` rolling row is a shape fact and must not certify a garbled label.

    The clipped entry has no rollover row at all, so ``rolling == "ABSENT"`` is true whatever
    the caption paints. A label that matches neither measured string therefore leaves nothing
    recognised on that shape: ``NOT_MATCHED``, not an exact template match.
    """
    image = mode_marks.load_frame(ENTRY / "channels-roi-frame-1.png")
    rows = mode_marks._rows(image)
    box = mode_marks._label_box(rows, mode_marks.MULTIPLEXER_ON_ENTRY)
    spot = next(
        (x, y)
        for y in range(box[1], box[3])
        for x in range(box[0], box[2])
        if not mode_marks._is_ink(rows[y][x])
    )
    record = mode_marks.recognize(_changed(image, spot[0], spot[1], (255, 255, 255)))
    assert record.surface == mode_marks.MULTIPLEXER_ON_ENTRY
    assert record.label == "UNRECOGNIZED"
    assert record.mode == "UNKNOWN"
    assert record.mark == "ABSENT" and record.rolling == "ABSENT"
    assert record.recognition == "NOT_MATCHED"
    # The clean fixture on the same shape still matches exactly.
    assert mode_marks.recognize(image).recognition == "EXACT_TEMPLATE_MATCH"


def test_the_mask_is_a_shape_and_colour_variance_inside_the_ink_band_still_matches():
    """M2: the committed template is an exact *shape mask*, not exact RGB.

    Recognition compares the thresholded ink mask over the measured box, so a repaint that
    stays inside the ink predicate matches; that is what makes the template a shape fact
    rather than a false claim about the frame's bytes.
    """
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    rows = mode_marks._rows(image)
    box = mode_marks._label_box(rows, mode_marks.SETTINGS_FULL)
    spot = next(
        (x, y)
        for y in range(box[1], box[3])
        for x in range(box[0], box[2])
        if mode_marks._is_ink(rows[y][x])
    )
    original = rows[spot[1]][spot[0]]
    repainted = (250, 251, 252)  # a different colour, still ink by ``INK_MIN``
    assert repainted != original and mode_marks._is_ink(repainted)
    record = mode_marks.recognize(_changed(image, spot[0], spot[1], repainted))
    assert record.label == "ENABLE_MULTIPLEXER"
    assert record.mode == "VISUAL_DISABLED"
    assert record.recognition == "EXACT_TEMPLATE_MATCH"


def test_the_signature_states_the_measured_counts_the_templates_actually_hold():
    """M3: no hand-typed ink count may outlive the rasters it describes."""
    for entry in mode_marks.TEMPLATES.marks:
        assert f"{entry.mark.lower()}={entry.ink}px" in mode_marks.SIGNATURE
    left, top, right, bottom = mode_marks.ROLLOVER_RECT
    assert f"rect={left},{top}-{right},{bottom}" in mode_marks.SIGNATURE
    assert mode_marks.ModeMarkAttribution().signature == mode_marks.SIGNATURE


def test_a_path_and_digest_count_mismatch_is_a_typed_unknown_not_a_zip_error():
    paths = _pair(ON)
    for digests in ((_digests(paths)[0],), (*_digests(paths), "x")):
        record = mode_marks.attribute_frames(paths, digests)
        assert record.mode == "UNKNOWN" and record.frames_agreed is False
        assert any("exactly two" in reason for reason in record.unknown_reasons)


def test_a_missing_pillow_still_fails_closed(monkeypatch, tmp_path: Path):
    import sys

    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.delitem(sys.modules, "PIL.Image", raising=False)
    with pytest.raises(mode_marks.FrameUnreadable) as raised:
        mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    assert "Pillow is not installed" in str(raised.value)
    record = mode_marks.attribute_capture(ON)
    assert record.mode == "UNKNOWN" and record.unknown_reasons


# ---------------------------------------------------------------------------------------------
# provenance of the read itself: retained history vs a live-bracketed moment
# ---------------------------------------------------------------------------------------------


def test_a_retained_pair_is_history_and_is_never_an_enable_precondition():
    """B1: the retained pair proves the conjunction and still cannot license a press."""
    record = mode_marks.attribute_capture(ON)
    assert record.mode == "VISUAL_DISABLED"
    assert record.rolling == "ON_PROVEN"  # the conjunction *is* painted
    assert record.acquisition_context == "retained"
    assert record.freshness == "not_established"
    assert record.integrity == "decoded-pair-only"
    assert record.enable_precondition is False
    assert record.action_authority is False
    # No capture record was consulted, so no identity beyond the decoded pair is claimed.
    assert any("no retained capture identity" in note for note in record.uncertainties)


def test_a_live_bracketed_read_states_its_context_and_verified_integrity():
    paths = _pair(ON)
    record = mode_marks.attribute_frames(
        paths, _digests(paths), context="live-bracketed"
    )
    assert record.acquisition_context == "live-bracketed"
    assert record.freshness == "live_bracketed"
    assert record.integrity == "capture-digest-verified"
    # The conjunction, in the same moment, on this pair's own verified digests.
    assert record.enable_precondition is True
    assert record.action_authority is False  # still no authority to press anything


def test_a_mark_alone_is_not_the_precondition():
    """The conjunction matters: OFF_PROVEN beside a disabled label is not the precondition."""
    paths = _pair(OFF)
    record = mode_marks.attribute_frames(
        paths, _digests(paths), context="live-bracketed"
    )
    assert record.mode == "VISUAL_DISABLED"
    assert record.rolling == "OFF_PROVEN"
    assert record.enable_precondition is False


def test_a_retained_pair_replaced_with_new_content_reads_it_but_keeps_no_old_claim(
    tmp_path: Path,
):
    """B2: a retained directory re-read later attributes *its own* current content only.

    The directory now holds a different real popup (OFF instead of ON). The read recognises
    the new content, yet it still cannot claim the original pair's integrity or freshness:
    nothing ties these pixels to the capture that was taken, and no timestamp is believed.
    """
    for name in mode_marks.PAIR_FILES:
        (tmp_path / name).write_bytes((OFF / name).read_bytes())
    record = mode_marks.attribute_capture(tmp_path)
    assert record.surface == "SETTINGS_FULL"
    assert record.label == "ENABLE_MULTIPLEXER"  # the *new* content, recognised
    assert record.mode == "VISUAL_DISABLED"
    assert record.rolling == "OFF_PROVEN"
    assert record.acquisition_context == "retained"
    assert record.freshness == "not_established"
    assert record.integrity == "decoded-pair-only"
    assert record.enable_precondition is False


def test_a_second_frame_that_is_not_a_raster_source_still_has_to_agree():
    """Pair frames are byte-identical here (the capture was still), so both must read alike.

    That is the contract's own stability fact, not a template source: the templates name
    frame 1 of each measured capture, and the second frame is only ever compared against it.
    """
    for directory in (ON, OFF, ENTRY):
        first, second = (
            hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in mode_marks.PAIR_FILES
        )
        assert first == second
        record = _read(directory)
        assert record.frames_agreed is True


# ---------------------------------------------------------------------------------------------
# the Enable line's own row: the Use only channel caption is never a mode-entry source
# ---------------------------------------------------------------------------------------------


def _blank(image, band: tuple[int, int, int, int]):
    """A copy with one measured band filled with the popup background — no fixture written."""
    from PIL import Image

    copy = image.copy()
    copy.paste(
        Image.new("RGB", (band[2] - band[0], band[3] - band[1]), mode_marks.BACKGROUND),
        (band[0], band[1]),
    )
    return copy


def _paint(source, band: tuple[int, int, int, int], target, at: tuple[int, int]):
    """Paste the raster inside ``band`` of ``source`` onto ``target`` at ``at``."""
    copy = target.copy()
    copy.paste(source.crop(band), at)
    return copy


def test_the_enable_template_is_the_enable_row_not_the_use_only_channel_row():
    """The committed raster comes from the Enable line's band, never the popup's first band."""
    template = mode_marks.TEMPLATES.label("ENABLE_MULTIPLEXER")
    assert template.surface == mode_marks.SETTINGS_FULL
    assert template.box == mode_marks.ENABLE_LABEL_BAND == (29, 48, 138, 61)
    assert template.box != mode_marks.USE_ONLY_CHANNEL_BAND
    assert (
        mode_marks.LABEL_BANDS[mode_marks.SETTINGS_FULL] == mode_marks.ENABLE_LABEL_BAND
    )
    # The two rows are disjoint and the Enable band never reaches the rollover mark.
    assert not mode_marks._bands_overlap(
        mode_marks.ENABLE_LABEL_BAND, mode_marks.USE_ONLY_CHANNEL_BAND
    )
    assert not mode_marks._bands_overlap(
        mode_marks.ENABLE_LABEL_BAND, mode_marks.ROLLOVER_BAND
    )
    # And the rasters really differ: "Enable multiplexer" is not "Use only channel".
    use_only = mode_marks._rows(mode_marks.load_frame(ON / "channels-roi-frame-1.png"))
    left, top, right, bottom = mode_marks.USE_ONLY_CHANNEL_BAND
    raster = mode_marks._ascii(
        mode_marks._mask(use_only, top, bottom, left, right, mode_marks._is_ink),
        right - left,
    )
    assert raster != template.rows


def test_removing_the_enable_line_is_unknown_while_the_rollover_still_reads():
    """RED: this frame used to read ``VISUAL_DISABLED`` from the untouched Use only channel row."""
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    erased = _blank(image, mode_marks.ENABLE_LABEL_BAND)
    record = mode_marks.recognize(erased)
    assert record.surface == mode_marks.SETTINGS_FULL
    assert record.label == "UNRECOGNIZED"
    assert record.mode == "UNKNOWN"
    assert record.recognition == "NOT_MATCHED"
    # The rolling witness is independent and survives the missing label.
    assert record.mark == "GREEN_CHECK"
    assert record.rolling == "ON_PROVEN"
    assert record.enable_precondition is False


def test_repainting_the_enable_line_with_the_use_only_channel_caption_is_unknown():
    """A correct-looking ``Use only channel`` prefix must never stand in for the Enable line."""
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    repainted = _blank(image, mode_marks.ENABLE_LABEL_BAND)
    repainted = _paint(
        image,
        mode_marks.USE_ONLY_CHANNEL_BAND,
        repainted,
        (mode_marks.ENABLE_LABEL_BAND[0], mode_marks.ENABLE_LABEL_BAND[1]),
    )
    record = mode_marks.recognize(repainted)
    assert record.label == "UNRECOGNIZED"
    assert record.mode == "UNKNOWN"
    assert record.rolling == "ON_PROVEN"


def test_swapping_the_enable_line_for_desable_multiplexer_is_unknown_not_enabled():
    entry = mode_marks.load_frame(ENTRY / "channels-roi-frame-1.png")
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    swapped = _blank(image, mode_marks.ENABLE_LABEL_BAND)
    swapped = _paint(
        entry,
        mode_marks.ENTRY_LABEL_BAND,
        swapped,
        (mode_marks.ENABLE_LABEL_BAND[0], mode_marks.ENABLE_LABEL_BAND[1]),
    )
    record = mode_marks.recognize(swapped)
    assert record.surface == mode_marks.SETTINGS_FULL
    assert (
        record.mode == "UNKNOWN"
    )  # never the enabled reading the string names elsewhere
    assert record.rolling == "ON_PROVEN"


def test_changing_the_use_only_channel_row_does_not_change_the_mode():
    """The other control's line is not a mode fact on either shape."""
    image = mode_marks.load_frame(ON / "channels-roi-frame-1.png")
    before = mode_marks.recognize(image)
    altered = _blank(image, mode_marks.USE_ONLY_CHANNEL_BAND)
    after = mode_marks.recognize(altered)
    assert before.mode == after.mode == "VISUAL_DISABLED"
    assert before.label == after.label == "ENABLE_MULTIPLEXER"
    assert before.rolling == after.rolling == "ON_PROVEN"


def test_a_mutated_enable_line_blocks_the_enable_precondition_at_pair_level(
    tmp_path: Path,
):
    """The conjunction fails at the label half: UNKNOWN mode, rolling kept, no licence."""
    from PIL import Image

    erased = _blank(
        mode_marks.load_frame(ON / "channels-roi-frame-1.png"),
        mode_marks.ENABLE_LABEL_BAND,
    )
    paths = []
    for name in mode_marks.PAIR_FILES:
        path = tmp_path / name
        erased.save(path)
        paths.append(str(path))
    record = mode_marks.attribute_frames(
        tuple(paths), _digests(tuple(paths)), context="live-bracketed"
    )
    assert record.mode == "UNKNOWN"
    assert record.rolling == "ON_PROVEN"
    assert record.frames_agreed is True
    assert record.enable_precondition is False
    # The fixture itself is untouched: the mutation was made in memory and written to tmp only.
    assert Image.open(ON / "channels-roi-frame-1.png").size == (393, 426)
