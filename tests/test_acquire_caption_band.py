"""The painted caption line: exact-template recognition, and every way it refuses.

The fixtures in ``tests/data/caption-band/`` are deidentified crops of one operator-opened
``Channels`` popup (the popup's own rectangle only — no desktop, no title, no path, no machine
identity). ``tests/data/caption-band/README.md`` records each capture, the operator's statement
that labelled it, and its content digest.

What is held here:

1. the committed rasters equal the ones ``build_templates`` re-learns from the fixtures, so the
   oracle in the package is not hand-edited data;
2. each labelled training capture recognises the operator's stated channel, and the **holdout**
   (a return visit to channel 1) recognises it without ever being a template source;
3. the caption is read from its own band: the popup's numbers and its top-row circles change
   nothing, and replacing the band changes the reading;
4. every failure mode is ``UNKNOWN`` with a named reason — blank, cropped, one-pixel glyph
   repaint, repainted prefix, 1 px shift, rescaled crop, a digit with no template, and a digit
   the set was never given (a synthetic shape, never a fabricated "real" capture);
5. a report is a **visual attribution**: ``native_fact`` and ``action_authority`` are ``False``,
   it carries template and band digests, and it carries no path or machine identity;
6. through the public capture path the recogniser runs only on an ``ok``, stable capture whose
   two frames agree, it never becomes the report's ``caption``, and it never touches the
   native ``per_channel.channel`` or any amount.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from udv_echo_process.acquire import caption_band as cb
from udv_echo_process.acquire import channels_read
from udv_echo_process.acquire.caption_band import CaptionAttribution

FIXTURES = Path(__file__).parent / "data" / "caption-band"

TRAINING = {
    "train-channel-1": (FIXTURES / "train-channel-1.png", "1"),
    "train-channel-2": (FIXTURES / "train-channel-2.png", "2"),
    "train-channel-10": (FIXTURES / "train-channel-10.png", "10"),
}
HOLDOUT = "holdout-channel-1-return"
HOLDOUT_PATH = FIXTURES / f"{HOLDOUT}.png"


@pytest.fixture(scope="module")
def learned() -> cb.TemplateSet:
    return cb.build_templates(TRAINING)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _open(path: Path) -> Image.Image:
    image = Image.open(path)
    image.load()
    return image.convert("RGB")


def _copy(image: Image.Image) -> Image.Image:
    return image.copy()


def _paste_rows(
    base: Image.Image, other: Image.Image, top: int, bottom: int
) -> Image.Image:
    """One crop's rows ``[top, bottom)`` on another's — everything else untouched."""
    out = _copy(base)
    out.paste(other.crop((0, top, base.width, bottom)), (0, top))
    return out


def _assert_unknown(read: CaptionAttribution, needle: str) -> None:
    assert read.status == "UNKNOWN"
    assert read.caption is None
    assert read.channel is None
    assert read.digits is None
    assert read.glyphs == ()
    assert read.native_fact is False
    assert read.action_authority is False
    assert read.unknown_reasons, "an UNKNOWN must name its reason"
    assert needle in " ".join(read.unknown_reasons)


def _pixel_digest(path: Path) -> str:
    """One frame's pixel digest, taken by the capture path's own owner function."""
    from udv_echo_process.acquire.channels_capture import digest as frame_digest

    return frame_digest(_open(path))


def _painted(digits: str) -> Image.Image:
    """A **synthetic** band painted from the learned rasters onto a measured capture.

    Nothing here is a photograph: the popup comes from a measured fixture and the band is
    generated from :func:`caption_band._expected_band`, so the glyphs are the real learned
    rasters at the measured geometry. That isolates the supported-channel rule: if the band
    is refused, it is refused because of the channel it names, not because a pixel differs.
    """
    out = _copy(_open(FIXTURES / "train-channel-1.png"))
    background = (64, 72, 112)
    out.paste(
        Image.new(
            "RGB",
            (386 - cb.TEXT_LEFT, cb.BAND_ROWS[1] - cb.BAND_ROWS[0] + 1),
            background,
        ),
        (cb.TEXT_LEFT, cb.BAND_ROWS[0]),
    )
    expected, _glyphs = cb._expected_band(cb.TEMPLATES, digits)
    for y in range(expected.shape[0]):
        for x in range(expected.shape[1]):
            if expected[y, x]:
                out.putpixel((cb.TEXT_LEFT + x, cb.BAND_ROWS[0] + y), (255, 255, 255))
    return out


# ---------------------------------------------------------------------------------------------
# the oracle is derived, not hand-written
# ---------------------------------------------------------------------------------------------


def test_committed_templates_equal_the_ones_relearned_from_the_fixtures(
    learned: cb.TemplateSet,
) -> None:
    assert set(learned.training) == set(TRAINING)
    assert learned.prefix.rows == cb.TEMPLATES.prefix.rows
    assert learned.suffix.rows == cb.TEMPLATES.suffix.rows
    assert learned.alphabet == cb.TEMPLATES.alphabet == ("0", "1", "2")
    for glyph, template in learned.digits.items():
        assert template.rows == cb.TEMPLATES.digits[glyph].rows
        assert (template.width, template.height) in {(3, 13), (5, 13)}, glyph
    assert cb.TEMPLATES.digests() == learned.digests()
    # every raster's provenance names a training capture and its committed content digest
    rasters = (
        cb.TEMPLATES.prefix,
        cb.TEMPLATES.suffix,
        *cb.TEMPLATES.digits.values(),
    )
    for template in rasters:
        assert template.source in TRAINING
        assert template.source_digest == _digest(TRAINING[template.source][0])


def test_fixtures_are_the_measured_popup_and_nothing_else() -> None:
    for path in sorted(FIXTURES.glob("*.png")):
        image = Image.open(path)
        assert image.size == cb.POPUP_SIZE, path.name
        # the band is white on one flat background: exactly two colours in that band
        band = image.convert("RGB").crop(
            (cb.TEXT_LEFT, cb.BAND_ROWS[0], 393, cb.BAND_ROWS[1] + 1)
        )
        assert len(band.getcolors(maxcolors=8) or ()) <= 2, path.name


# ---------------------------------------------------------------------------------------------
# what it does read
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "path", "label"), [(n, p, x) for n, (p, x) in TRAINING.items()]
)
def test_training_capture_reads_its_stated_channel(name, path, label) -> None:
    read = cb.recognize_png(path)
    assert read.status == "RECOGNIZED", read.unknown_reasons
    assert read.digits == label
    assert read.channel == int(label)
    assert read.caption == f"For the current channel (channel {label})"
    assert read.recognition == "EXACT_TEMPLATE_MATCH"
    assert read.source == "visual_pixels"
    assert [glyph.glyph for glyph in read.glyphs] == list(label)
    assert all(glyph.exact for glyph in read.glyphs)
    assert {glyph.template_source for glyph in read.glyphs} <= set(
        cb.TEMPLATES.training
    )


def test_holdout_return_to_channel_1_is_read_without_being_trained() -> None:
    """The operator's return to channel 1 is a separate capture — never a template source."""
    assert HOLDOUT not in cb.TEMPLATES.training
    assert _digest(HOLDOUT_PATH) != _digest(FIXTURES / "train-channel-1.png")
    read = cb.recognize_png(HOLDOUT_PATH)
    assert read.status == "RECOGNIZED", read.unknown_reasons
    assert read.channel == 1
    trained = cb.recognize_png(FIXTURES / "train-channel-1.png")
    # the same rendered line has the same band digest, and nothing about it was learned here
    assert read.band_digest == trained.band_digest


def test_second_frame_of_one_capture_reads_identically() -> None:
    first = cb.recognize_png(FIXTURES / "train-channel-2.png")
    second = cb.recognize_png(FIXTURES / "train-channel-2-frame-2.png")
    assert first.digits == second.digits == "2"
    assert first.band_digest == second.band_digest


@pytest.mark.parametrize("digits", ["1", "2", "10"])
def test_photographed_channels_read_from_a_generated_band(digits) -> None:
    """Control for the negatives below: the same generator reads every photographed channel."""
    read = cb.recognize(_painted(digits))
    assert read.status == "RECOGNIZED", read.unknown_reasons
    assert read.digits == digits


@pytest.mark.parametrize("digits", ["0", "11", "12", "20", "21", "22"])
def test_a_channel_never_photographed_is_unknown_even_with_supported_glyphs(
    digits,
) -> None:
    """A synthetic band composed of learned glyphs: only channels 1, 2 and 10 are read.

    Every glyph here is a real learned raster at the measured pitch, so the raster match
    succeeds — the refusal must come from the channel the band *names*, which was never
    photographed, rather than from a pixel difference or a nearest match.
    """
    read = cb.recognize(_painted(digits))
    _assert_unknown(read, "never photographed")
    assert f"channel {digits}" in " ".join(read.unknown_reasons)
    assert read.recognition == "NOT_PERFORMED"
    assert read.unknown_reasons and "1, 2 and 10" in " ".join(read.unknown_reasons)


def test_success_diagnostics_state_the_actual_tight_band_not_the_fixed_slice() -> None:
    read = cb.recognize_png(HOLDOUT_PATH)
    assert read.band_box is not None
    left, top, right, bottom = read.band_box
    stated = " ".join(read.diagnostics)
    assert f"band {right - left}x{bottom - top} px" in stated
    assert "298" not in stated  # the frozen right-window slice, not what was matched


# ---------------------------------------------------------------------------------------------
# the band is what is matched — not the popup, and not any declaration
# ---------------------------------------------------------------------------------------------


def test_changed_numbers_do_not_change_the_caption() -> None:
    base = _open(FIXTURES / "train-channel-1.png")
    other = _open(FIXTURES / "train-channel-10.png")
    read = cb.recognize(_paste_rows(base, other, 283, 426))
    assert read.status == "RECOGNIZED", read.unknown_reasons
    assert read.digits == "1"


def test_changed_top_row_circles_do_not_change_the_caption() -> None:
    base = _open(FIXTURES / "train-channel-1.png")
    other = _open(FIXTURES / "train-channel-10.png")
    read = cb.recognize(_paste_rows(base, other, 0, 250))
    assert read.status == "RECOGNIZED", read.unknown_reasons
    assert read.digits == "1"


def test_caption_replaced_with_another_capture_reads_that_caption() -> None:
    base = _open(FIXTURES / "train-channel-1.png")
    other = _open(FIXTURES / "train-channel-10.png")
    read = cb.recognize(_paste_rows(base, other, 262, 277))
    assert read.status == "RECOGNIZED", read.unknown_reasons
    assert read.digits == "10"
    assert read.channel == 10


# ---------------------------------------------------------------------------------------------
# failures are UNKNOWN, and say why
# ---------------------------------------------------------------------------------------------


def test_blank_crop_is_unknown() -> None:
    blank = Image.new("RGB", cb.POPUP_SIZE, (64, 72, 112))
    _assert_unknown(cb.recognize(blank), "no ink at all")


def test_cropped_popup_is_unknown() -> None:
    base = _open(FIXTURES / "train-channel-1.png")
    rolled = Image.new("RGB", cb.POPUP_SIZE, (64, 72, 112))
    rolled.paste(base.crop((0, 0, 393, 240)), (0, 0))
    _assert_unknown(cb.recognize(rolled), "top rule")


def test_band_shifted_by_one_pixel_is_unknown() -> None:
    base = _open(FIXTURES / "train-channel-1.png")
    moved = _copy(base)
    moved.paste(base.crop((87, 263, 386, 276)), (88, 263))
    _assert_unknown(cb.recognize(moved), "not the measured x=88")


def test_repainted_glyph_pixel_is_unknown() -> None:
    """One extra ink pixel in the digit cell: the exact match refuses, it does not round off."""
    altered = _open(FIXTURES / "train-channel-1.png")
    altered.putpixel((279, 266), (255, 255, 255))
    read = cb.recognize(altered)
    _assert_unknown(read, "no trained caption matches")
    assert "pixel-identical" in " ".join(read.unknown_reasons)


def test_glyph_without_a_template_is_unknown_not_nearest() -> None:
    """A digit the set was never given (here ``2``) is refused by the template's absence."""
    without_two = cb.TEMPLATES.without("2")
    read = cb.recognize(_open(FIXTURES / "train-channel-2.png"), without_two)
    _assert_unknown(read, "no trained caption matches")
    assert read.recognition == "NOT_PERFORMED"
    assert "'0', '1'" in " ".join(read.unknown_reasons)


def test_unsupported_digit_three_is_unknown_and_never_invented() -> None:
    """A synthetic three-shaped blob in the digit cell refuses — no real capture is fabricated.

    ``3``-``9`` were never measured, so this test draws an ink shape of the measured cell size
    rather than pretending a photographed ``3`` exists.
    """
    base = _open(FIXTURES / "train-channel-1.png")
    altered = _copy(base)
    background = (64, 72, 112)
    altered.paste(Image.new("RGB", (5, 13), background), (279, 263))
    for y in range(263, 276):
        altered.putpixel((280, y), (255, 255, 255))
    for x in range(281, 283):
        altered.putpixel((x, 263), (255, 255, 255))
        altered.putpixel((x, 269), (255, 255, 255))
    read = cb.recognize(altered)
    _assert_unknown(read, "no trained caption matches")
    assert "UNKNOWN rather than the closest match" in " ".join(read.unknown_reasons)


def test_rescaled_crop_is_unknown() -> None:
    doubled = _open(FIXTURES / "train-channel-1.png").resize(
        (786, 852), Image.Resampling.NEAREST
    )
    _assert_unknown(cb.recognize(doubled), "different scale")


def test_a_saved_frame_is_size_checked_before_it_is_decoded(monkeypatch) -> None:
    """An oversized saved image is refused from its header: no load, no convert, no allocation."""
    from PIL import Image as PILImage

    class _Oversize:
        size = (786, 852)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def load(self):
            raise AssertionError("an oversized frame must not be decoded")

        def convert(self, mode):
            raise AssertionError("an oversized frame must not be converted or copied")

    monkeypatch.setattr(PILImage, "open", lambda _path: _Oversize())
    read = cb.recognize_png("oversize.png")
    _assert_unknown(read, "786x852")
    stated = " ".join(read.unknown_reasons)
    assert "not the measured popup" in stated
    assert "before it was decoded" in stated


def test_missing_pillow_is_a_typed_unknown_not_a_crash(monkeypatch) -> None:
    """On a host without the ``acquire`` extra the reader refuses, it does not raise."""
    monkeypatch.setitem(sys.modules, "PIL", None)
    read = cb.recognize_png(FIXTURES / "train-channel-1.png")
    _assert_unknown(read, "Pillow")
    assert read.source == "NONE"


def test_repainted_prefix_is_unknown() -> None:
    """A repaint of the constant text: the layout signature moved, so nothing is read."""
    base = _open(FIXTURES / "train-channel-1.png")
    altered = _copy(base)
    altered.paste(base.crop((260, 262, 300, 277)), (258, 262))
    _assert_unknown(cb.recognize(altered), "not pixel-identical")


def test_three_digit_caption_is_outside_support() -> None:
    base = _open(FIXTURES / "train-channel-1.png")
    fabricated = _copy(base)
    fabricated.paste(base.crop((279, 263, 282, 276)), (286, 263))
    _assert_unknown(cb.recognize(fabricated), "no trained caption matches")


# ---------------------------------------------------------------------------------------------
# two frames, one exact result
# ---------------------------------------------------------------------------------------------


def test_two_agreeing_frames_attribute_the_caption() -> None:
    paths = (
        str(FIXTURES / "train-channel-2.png"),
        str(FIXTURES / "train-channel-2-frame-2.png"),
    )
    digests = (_pixel_digest(FIXTURES / "train-channel-2.png"),) * 2
    read = cb.attribute_frames(paths, digests)
    assert read.status == "RECOGNIZED", read.unknown_reasons
    assert read.channel == 2
    assert read.frames_agreed is True
    assert read.frame_digests == digests


def test_a_forged_frame_digest_is_unknown_and_never_trusted() -> None:
    """The supplied digests are checked against the decoded RGB pixels, not believed."""
    paths = (
        str(FIXTURES / "train-channel-2.png"),
        str(FIXTURES / "train-channel-2-frame-2.png"),
    )
    actual = _pixel_digest(FIXTURES / "train-channel-2.png")
    _assert_unknown(
        cb.attribute_frames(paths, ("a" * 64, "a" * 64)),
        "does not match the decoded pixels",
    )
    forged = cb.attribute_frames(paths, (actual, "b" * 64))
    _assert_unknown(forged, "does not match the decoded pixels")
    assert "frame 2" in " ".join(forged.unknown_reasons)


def test_one_frame_is_not_enough_to_attribute() -> None:
    read = cb.attribute_frames((str(FIXTURES / "train-channel-2.png"),), ("a" * 64,))
    _assert_unknown(read, "fewer than two frames")


def test_frames_with_different_crop_digests_are_unknown() -> None:
    """Two genuinely different frames, supplied honestly: the pixels disagree, so UNKNOWN."""
    first = FIXTURES / "train-channel-2.png"
    second = FIXTURES / "train-channel-10.png"
    read = cb.attribute_frames(
        (str(first), str(second)), (_pixel_digest(first), _pixel_digest(second))
    )
    _assert_unknown(read, "pixel digests differ")


def test_a_frame_that_cannot_be_read_is_unknown_not_taken_from_the_other(
    tmp_path,
) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a png")
    read = cb.attribute_frames(
        (str(FIXTURES / "train-channel-2.png"), str(broken)), ("a" * 64, "a" * 64)
    )
    _assert_unknown(read, "did not produce two identical readings")


# ---------------------------------------------------------------------------------------------
# provenance: a visual attribution, and nothing stronger
# ---------------------------------------------------------------------------------------------


def test_report_is_a_visual_attribution_with_no_native_or_action_claim() -> None:
    read = cb.recognize_png(HOLDOUT_PATH)
    assert read.native_fact is False
    assert read.action_authority is False
    assert "visual attribution" in read.provenance
    assert "not a native fact" in read.provenance
    assert "no action authority" in read.provenance
    assert (
        "not inputs" in read.provenance
    )  # declaration/amounts never become the reading
    assert f"popup={cb.POPUP_SIZE[0]}x{cb.POPUP_SIZE[1]}" in read.signature
    assert read.support.startswith("channels {1,2,10} only")
    assert "never photographed" in read.support
    assert "3-9" in read.support and "NOT supported" in read.support
    assert read.band_digest and read.prefix_digest and read.suffix_digest
    assert len(read.template_digests) == 5  # prefix, suffix, digits 0/1/2
    assert {glyph.template_digest for glyph in read.glyphs} <= {
        digest for _, digest in read.template_digests
    }


def test_report_carries_no_path_or_machine_identity() -> None:
    payload = cb.recognize_png(FIXTURES / "train-channel-10.png").model_dump_json()
    assert "tests/data" not in payload and "fixtures" not in payload
    assert "C:" not in payload and "\\\\" not in payload
    assert ".png" not in payload
    assert "hwnd" not in payload


def test_report_is_deterministic_and_json_serialisable() -> None:
    first = cb.recognize_png(FIXTURES / "train-channel-10.png")
    second = cb.recognize_png(FIXTURES / "train-channel-10.png")
    assert first.model_dump() == second.model_dump()
    payload = json.loads(first.model_dump_json())
    assert payload["status"] == "RECOGNIZED"
    assert payload["glyphs"][1]["glyph"] == "0"
    assert payload["native_fact"] is False
    assert payload["action_authority"] is False


def test_training_refuses_captures_that_disagree_about_the_layout(tmp_path) -> None:
    moved = _open(FIXTURES / "train-channel-1.png")
    shifted = _copy(moved)
    shifted.paste(moved.crop((88, 263, 290, 276)), (90, 263))
    path = tmp_path / "moved.png"
    shifted.save(path)
    with pytest.raises(ValueError, match="not pixel-identical"):
        cb.build_templates({**TRAINING, "moved": (path, "1")})


# ---------------------------------------------------------------------------------------------
# the public capture path: invoked only on an ok, stable, two-frame-identical capture
# ---------------------------------------------------------------------------------------------


def _grab(fixture: Path):
    """A whole-desktop grab with the measured popup at the popup's own rect ``(0, 0)``."""
    from udv_echo_process.acquire.channels_capture import ScreenFrame

    def grab() -> ScreenFrame:
        screen = Image.new("RGB", (1920, 1080), (0, 0, 0))
        screen.paste(_open(fixture), (0, 0))
        return ScreenFrame(image=screen, origin=(0, 0), size=(1920, 1080))

    return grab


@pytest.fixture()
def one_window(monkeypatch):
    from test_acquire_channels_capture import WINDOW

    monkeypatch.setattr(channels_read, "visible_main_windows", lambda *args: (WINDOW,))


def _capture(tmp_path, fixture, *, second=None):
    from test_acquire_channels_capture import CaptureActuator, states

    frames = iter([_open(fixture), _open(second or fixture)])
    from udv_echo_process.acquire.channels_capture import ScreenFrame

    def backend() -> ScreenFrame:
        screen = Image.new("RGB", (1920, 1080), (0, 0, 0))
        screen.paste(next(frames), (0, 0))
        return ScreenFrame(image=screen, origin=(0, 0), size=(1920, 1080))

    return channels_read.read_channels(
        CaptureActuator(),
        capture_dir=tmp_path,
        image_backend=backend,
        window_state=states(),
    )


def test_capture_attributes_the_painted_caption_and_leaves_every_native_field_alone(
    tmp_path, one_window
) -> None:
    report = _capture(tmp_path, FIXTURES / "train-channel-2.png")
    evidence = report.capture
    assert evidence is not None
    assert evidence.status == "ok", evidence.unknown_reasons
    attribution = evidence.visual_caption
    assert attribution is not None
    assert attribution.status == "RECOGNIZED", attribution.unknown_reasons
    assert attribution.channel == 2
    assert attribution.frames_agreed is True
    assert len(attribution.frame_digests) == 2
    assert attribution.frame_digests[0] == attribution.frame_digests[1]
    assert attribution.frame_digests[0] == evidence.frames[0].digest
    # the native caption is still UNKNOWN, and the operator's stated amounts are untouched
    assert evidence.caption == "UNKNOWN"
    assert evidence.recognition == "NOT_PERFORMED"
    assert report.per_channel is not None
    assert report.per_channel.channel == "UNKNOWN"
    assert report.per_channel.profiles.text == "7"
    assert report.per_channel.seconds.value == 0.28
    assert report.repeat is not None and report.repeat.text == "1"
    assert report.setup_verified is False
    # no action authority travelled with the report
    assert attribution.action_authority is False
    assert attribution.native_fact is False


def test_capture_does_not_invoke_recognition_when_its_frames_disagree(
    tmp_path, one_window
) -> None:
    report = _capture(
        tmp_path,
        FIXTURES / "train-channel-2.png",
        second=FIXTURES / "train-channel-10.png",
    )
    evidence = report.capture
    assert evidence is not None
    assert evidence.status == "UNKNOWN"
    assert evidence.visual_caption is None
    assert report.caption_source


def test_the_cli_prints_the_visual_attribution_without_upgrading_it(
    monkeypatch, capsys, tmp_path, one_window
) -> None:
    """The CLI's JSON carries the attribution beside an unchanged native caption."""
    from udv_echo_process.cli import acquire_main

    report = _capture(tmp_path, FIXTURES / "train-channel-10.png")
    monkeypatch.setattr(channels_read, "read_channels", lambda **kwargs: report)
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            ["channels-read", "--capture-dir", str(tmp_path / "again"), "--json"]
        )
    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["capture"]["caption"] == "UNKNOWN"
    assert payload["per_channel"]["channel"] == "UNKNOWN"
    visual = payload["capture"]["visual_caption"]
    assert visual["status"] == "RECOGNIZED"
    assert visual["channel"] == 10
    assert visual["native_fact"] is False
    assert visual["action_authority"] is False
    assert "visual attribution" in visual["provenance"]
