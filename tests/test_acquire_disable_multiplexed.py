"""The guarded Disable-multiplexer press: offline, real workflow, authentic entry frames.

The popup shape is the projected clipped one-entry surface the reader's own tests use. The mode
evidence is the operator's **real** reconfigured popup pair from
``tests/data/mpx-mode/entry-clipped-enabled``: its two frames are decoded, their digests
re-derived, and those same digests are what the fake capture reports, so a capture whose
attribution does not belong to its frames is refused. The double replaces only the Win32 layer
and counts every press, so "exactly one press on the entry" and "zero presses" are measurements.
"""

from __future__ import annotations

import json

import pytest
from test_acquire_channels_read import (
    ENTRY_ROWS,
    SETTINGS_ROWS,
    WINDOW,
    _roles,
)

from udv_echo_process.acquire import disable_multiplexed, mode_marks
from udv_echo_process.acquire.actuator import StripState, WindowTarget
from udv_echo_process.acquire.channels_capture import (
    CAPTURE_ENTRY_NO_NUMERIC,
    CAPTURE_SETTINGS_NUMERIC,
    CaptureEvidence,
    FrameEvidence,
    FrameStats,
    GuardComparison,
    NumericBracketing,
    WindowGuard,
)
from udv_echo_process.acquire.channels_capture import (
    digest as frame_digest,
)
from udv_echo_process.acquire.disable_multiplexed import (
    DisableStage,
    acquire_disable_multiplexed,
)
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.acquire.ui.channels import (
    ChannelsRead,
    ChannelsSurface,
    resolve_channels,
)
from udv_echo_process.acquire.ui.layout import observation_of

DATA = __import__("pathlib").Path(__file__).parent / "data" / "mpx-mode"
ENTRY = DATA / "entry-clipped-enabled"
ON = DATA / "disabled-rolling-on"

#: The clipped entry row and the (hidden) settings Enable toggle in the projected shape.
ENTRY_HWND = 1003
ENABLE_HWND = 1028

pytest.importorskip("PIL", reason="the acquire extra decodes the recorded fixtures")


def _pair(directory) -> tuple[str, ...]:
    return tuple(str(directory / name) for name in mode_marks.PAIR_FILES)


def _digests(directory) -> tuple[str, str]:
    paths = _pair(directory)
    return tuple(frame_digest(mode_marks.load_frame(path)) for path in paths)  # type: ignore[return-value]


def _live_mark(directory) -> mode_marks.ModeMarkAttribution:
    paths = _pair(directory)
    return mode_marks.attribute_frames(paths, _digests(directory), context="live-bracketed")


def _retained_mark(directory) -> mode_marks.ModeMarkAttribution:
    return mode_marks.attribute_capture(directory)


def _frames(directory, size) -> tuple[FrameEvidence, ...]:
    digests = _digests(directory)
    out = []
    for index, (path, digest_value) in enumerate(zip(_pair(directory), digests, strict=True), 1):
        out.append(
            FrameEvidence(
                index=index,
                path=path,
                rect=(0, 0, size[0], size[1]),
                stats=FrameStats(
                    width=size[0],
                    height=size[1],
                    mode="RGB",
                    distinct_grey_levels=8,
                    dominant_fraction=0.7,
                    non_blank=True,
                ),
                digest=digest_value,
            )
        )
    return tuple(out)


def _report(
    rows=ENTRY_ROWS,
    *,
    directory=ENTRY,
    capture_dir: str | None = None,
    run: str = "capture-001",
    retained: bool = False,
    kind: str | None = None,
) -> ChannelsRead:
    read = resolve_channels(observation_of(_roles(rows)))
    if capture_dir is None:
        return read
    entry_shape = read.surface is ChannelsSurface.MULTIPLEXER_ON_ENTRY
    evidence = CaptureEvidence(
        status="ok",
        captured=True,
        stable=True,
        capture_kind=(
            kind
            if kind is not None
            else (
                CAPTURE_ENTRY_NO_NUMERIC if entry_shape else CAPTURE_SETTINGS_NUMERIC
            )
        ),
        directory=str(__import__("pathlib").Path(capture_dir) / run),
        roi=(0, 0, *(mode_marks.ENTRY_SIZE if entry_shape else mode_marks.SETTINGS_SIZE)),
        frames=_frames(
            directory,
            mode_marks.ENTRY_SIZE if entry_shape else mode_marks.SETTINGS_SIZE,
        ),
        guards=GuardComparison(
            before=WindowGuard(label="before", hwnd=WINDOW),
            after=WindowGuard(label="after", hwnd=WINDOW),
            consistent=True,
        ),
        numeric=NumericBracketing(
            consistent=True, applicable=not entry_shape, note="entry shape states no amount"
        ),
        visual_mode_mark=(
            _retained_mark(directory) if retained else _live_mark(directory)
        ),
    )
    return read.model_copy(update={"capture": evidence})


def _children(rows=ENTRY_ROWS) -> tuple[dict, ...]:
    out = []
    for row in rows:
        hwnd, parent, cls, rect, _text, *rest = row
        out.append(
            {
                "hwnd": hwnd,
                "parent": parent,
                "cls": cls,
                "rect": rect,
                "visible": rest[0] if rest else True,
            }
        )
    return tuple(out)


class FakeDisableActuator:
    """The Win32 surface only: one binding, a ready strip, counters."""

    def __init__(self, *, strip: StripState | None = None, on_press=None) -> None:
        self.strip = strip or StripState(button_count=3)
        self.on_press = on_press
        self.bindings = 0
        self.warnings: list[str] = []
        self._target: WindowTarget | None = None

    def bind_target(self, hwnd: int) -> WindowTarget:
        self.bindings += 1
        self._target = WindowTarget(
            hwnd=int(hwnd), thread_id=11, process_id=22, class_name="TMain_Scr"
        )
        return self._target

    def verify_bound_target(self, target: WindowTarget) -> WindowTarget:
        assert self._target == target
        return target

    def window_caption(self) -> str:
        return "UDOP DOP3010.43"

    def peek_overlay(self):
        return None

    def strip_state(self) -> StripState:
        return self.strip

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the disable command reached {name!r}")


def _install_press(monkeypatch, presses: list[int], *, error: Exception | None = None):
    def fake_class(hwnd: int) -> str:
        assert hwnd in {1000, ENTRY_HWND}, f"unexpected class query for {hwnd}"
        return "TSp_Panel" if hwnd == 1000 else "TSp_Button"

    def fake_parent(hwnd: int) -> int:
        return WINDOW if hwnd == 1000 else 1000

    def fake_hold(hwnd: int) -> None:
        presses.append(int(hwnd))
        if error is not None:
            raise error

    monkeypatch.setattr(disable_multiplexed, "_class_of", fake_class)
    monkeypatch.setattr(disable_multiplexed, "_parent_of", fake_parent)
    monkeypatch.setattr(disable_multiplexed, "_visible_children", lambda hwnd: _children())
    monkeypatch.setattr(disable_multiplexed, "_click_hold", fake_hold)


def _run(
    tmp_path,
    *,
    live=None,
    reads=None,
    post=None,
    settings=None,
    children=None,
    **kwargs,
):
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir(exist_ok=True)
    queue = list(
        reads
        or [
            _report(capture_dir=str(capture_dir), run="capture-001"),
            _report(capture_dir=str(capture_dir), run="capture-002"),
        ]
    )
    params = {
        "capture_dir": capture_dir,
        "trial_record": tmp_path / "trial.json",
        "capture_entry": lambda *a, **k: queue.pop(0),
        "capture_settings": settings,
        "actuator": live or FakeDisableActuator(),
        "enumerate_windows": lambda: (WINDOW,),
        "popup_children": children if children is not None else (lambda h: _children()),
        "read_popup": lambda *a, **k: (
            post
            if post is not None
            else ChannelsRead(surface=ChannelsSurface.ABSENT, readable=False)
        ),
    }
    params.update(kwargs)
    return acquire_disable_multiplexed(**params)


def _record(tmp_path) -> dict:
    return json.loads((tmp_path / "trial.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# authentic evidence
# ---------------------------------------------------------------------------------------------


def test_the_authentic_clipped_pair_states_enabled_and_no_rolling_state() -> None:
    mark = _live_mark(ENTRY)
    assert mark.surface == mode_marks.MULTIPLEXER_ON_ENTRY
    assert mark.label == "DESABLE_MULTIPLEXER"
    assert mark.mode == "VISUAL_ENABLED"
    assert mark.rolling == "ABSENT"
    assert mark.integrity == "capture-digest-verified"
    assert mark.frames_agreed is True


# ---------------------------------------------------------------------------------------------
# the one press
# ---------------------------------------------------------------------------------------------


def test_exactly_one_press_on_the_clipped_entry_and_nothing_else(tmp_path, monkeypatch) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    live = FakeDisableActuator()
    result = _run(tmp_path, live=live)
    assert presses == [ENTRY_HWND]
    assert ENTRY_HWND != ENABLE_HWND
    assert result.presses == 1 and result.posted == "unknown"
    assert result.stage is DisableStage.PRESSED
    assert result.target_hwnd == ENTRY_HWND
    assert result.target_attribution == "Disable multiplexer"
    assert result.old_mode == "VISUAL_ENABLED"
    assert result.old_context == "live-bracketed"
    assert result.old_integrity == "capture-digest-verified"
    assert all(len(digest) == 64 for digest in result.old_frame_digests or ())
    assert result.post_mode == "UNKNOWN"  # no settings helper was supplied


def test_the_obligation_is_durable_before_the_press_and_forever_unknown(
    tmp_path, monkeypatch
) -> None:
    seen: dict = {}
    presses: list[int] = []

    def hold(hwnd: int) -> None:
        seen.update(_record(tmp_path))
        presses.append(int(hwnd))

    monkeypatch.setattr(
        disable_multiplexed,
        "_class_of",
        lambda hwnd: "TSp_Panel" if hwnd == 1000 else "TSp_Button",
    )
    monkeypatch.setattr(
        disable_multiplexed, "_parent_of", lambda hwnd: WINDOW if hwnd == 1000 else 1000
    )
    monkeypatch.setattr(disable_multiplexed, "_visible_children", lambda hwnd: _children())
    monkeypatch.setattr(disable_multiplexed, "_click_hold", hold)
    _run(tmp_path)
    assert seen["phase"] == "obligation"
    assert seen["entry_hwnd"] == ENTRY_HWND
    assert seen["scope"] == "one held press on the clipped Disable entry; nothing else"
    assert seen["presses"] == 0 and seen["posted"] == "not_attempted"
    # The pre-press record is explicit that "not_attempted" is *as of its own write* and that
    # the obligation is already open, so a failed post-write cannot be read as "no press".
    assert seen["action"] == "pending"
    assert seen["obligation_open"] is True
    assert seen["press"] == "not_attempted"
    assert "as of this record's own write" in seen["press_state_as_of"]
    assert "may still exist" in seen["ready_only"]
    assert "Record, Stop or Clear" in seen["ready_only"]
    assert seen["target_attribution"] == "Disable multiplexer"
    record = _record(tmp_path)
    assert record["phase"] == "after" and record["obligation_open"] is True
    assert "retried" in record["obligation_warning"]
    assert record["old_frame_digests"] == list(seen["old_frame_digests"])


# ---------------------------------------------------------------------------------------------
# ready-only refusals: zero presses, no record
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "strip",
    [
        StripState(button_count=1),  # recording in progress
        StripState(button_count=4),  # ambiguous row
        StripState(button_count=3, has_slider=True, slider_max=4),  # store/completed view
    ],
)
def test_active_recording_or_store_data_refuses_with_zero_actions(
    tmp_path, monkeypatch, strip
) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    with pytest.raises(AcquisitionError, match="ready|strip|slider|recording"):
        _run(tmp_path, live=FakeDisableActuator(strip=strip))
    assert presses == []
    assert not (tmp_path / "trial.json").exists()


def test_retained_evidence_in_the_decision_capture_is_not_a_licence(
    tmp_path, monkeypatch
) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    with pytest.raises(AcquisitionError, match="fresh|retained|live-bracketed|not a"):
        _run(
            tmp_path,
            reads=[
                _report(capture_dir=str(tmp_path / "captures"), run="capture-001", retained=True),
                _report(capture_dir=str(tmp_path / "captures"), run="capture-002"),
            ],
        )
    assert presses == []
    assert not (tmp_path / "trial.json").exists()


# ---------------------------------------------------------------------------------------------
# structural binding refusals: malformed shape, wrong owner row
# ---------------------------------------------------------------------------------------------


def test_a_popup_of_another_size_refuses_with_zero_presses(tmp_path, monkeypatch) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    wide = (ENTRY_ROWS[0][0], WINDOW, "TSp_Panel", (0, 0, 200, 43), "")
    with pytest.raises(AcquisitionError, match="measures|clipped|different popup shape"):
        _run(
            tmp_path,
            reads=[
                _report((wide, *ENTRY_ROWS[1:]), capture_dir=str(tmp_path / "captures"), run="capture-001"),
                _report(capture_dir=str(tmp_path / "captures"), run="capture-002"),
            ],
        )
    assert presses == []
    assert not (tmp_path / "trial.json").exists()


def test_two_direct_buttons_owning_the_band_refuse_with_zero_presses(
    tmp_path, monkeypatch
) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    rivals = _children() + (
        {"hwnd": 1030, "parent": 1000, "cls": "TSp_Button", "rect": (12, 5, 150, 35), "visible": True},
    )
    with pytest.raises(AcquisitionError, match="direct|own the measured entry band|exactly one"):
        _run(tmp_path, children=lambda h: rivals)
    assert presses == []
    assert not (tmp_path / "trial.json").exists()


def test_a_tree_without_parent_links_refuses_instead_of_guessing(tmp_path, monkeypatch) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    orphaned = [{key: value for key, value in row.items() if key != "parent"} for row in _children()]
    with pytest.raises(AcquisitionError, match="parent|direct descent"):
        _run(tmp_path, children=lambda h: tuple(orphaned))
    assert presses == []


def test_a_wrong_class_or_parent_at_the_press_boundary_posts_nothing(monkeypatch) -> None:
    posted: list[int] = []
    monkeypatch.setattr(disable_multiplexed, "_click_hold", posted.append)
    target = WindowTarget(hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr")
    monkeypatch.setattr(
        disable_multiplexed,
        "_class_of",
        lambda hwnd: "TSp_Edit" if hwnd == ENTRY_HWND else "TSp_Panel",
    )
    monkeypatch.setattr(disable_multiplexed, "_parent_of", lambda hwnd: WINDOW)
    monkeypatch.setattr(disable_multiplexed, "_visible_children", lambda hwnd: _children())
    with pytest.raises(AcquisitionError, match="not a TSp_Button"):
        disable_multiplexed.press_disable_entry(
            target=target,
            popup_hwnd=1000,
            entry_hwnd=ENTRY_HWND,
            entry_rect=(10, 3, 148, 33),
        )
    assert posted == []


# ---------------------------------------------------------------------------------------------
# the final capture is a new fact
# ---------------------------------------------------------------------------------------------


def test_a_final_capture_that_changes_refuses_and_rewrites_the_obligation(
    tmp_path, monkeypatch
) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    with pytest.raises(AcquisitionError, match="action boundary|fresh|retained"):
        _run(
            tmp_path,
            reads=[
                _report(capture_dir=str(tmp_path / "captures"), run="capture-001"),
                _report(capture_dir=str(tmp_path / "captures"), run="capture-002", retained=True),
            ],
        )
    assert presses == []
    record = _record(tmp_path)
    assert record["phase"] == "preflight_refused"
    assert record["presses"] == 0 and record["press"] == "not_attempted"
    assert record["restoration_owed"] == []


def test_a_moved_entry_at_the_boundary_refuses_instead_of_reusing_the_handle(
    tmp_path, monkeypatch
) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    calls = {"n": 0}

    def children(hwnd: int):
        calls["n"] += 1
        if calls["n"] == 1:
            return _children()
        moved = [
            {**row, "rect": (10, 3, 140, 20)} if row["hwnd"] == ENTRY_HWND else row
            for row in _children()
        ]
        return tuple(
            moved
            + [
                {
                    "hwnd": 1031,
                    "parent": 1000,
                    "cls": "TSp_Button",
                    "rect": (12, 5, 150, 35),
                    "visible": True,
                }
            ]
        )

    with pytest.raises(AcquisitionError, match="action boundary|own the measured|disagree|one"):
        _run(
            tmp_path,
            reads=[
                _report(capture_dir=str(tmp_path / "captures"), run="capture-001"),
                _report(capture_dir=str(tmp_path / "captures"), run="capture-002"),
            ],
            children=children,
        )
    assert presses == []
    assert _record(tmp_path)["phase"] == "preflight_refused"


# ---------------------------------------------------------------------------------------------
# a raised press is a recorded attempt, never a retry
# ---------------------------------------------------------------------------------------------


def test_a_raised_press_is_recorded_as_an_attempt_of_unknown_delivery(
    tmp_path, monkeypatch
) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses, error=OSError("the control vanished"))
    result = _run(tmp_path)
    assert presses == [ENTRY_HWND]
    assert result.stage is DisableStage.PRESS_RAISED
    assert result.presses == 1 and result.posted == "unknown"
    assert "attempted" in result.press.lower() or "unknown" in result.press_error
    assert "whether any message reached" in result.press_error
    record = _record(tmp_path)
    assert record["phase"] == "after" and record["press"] == "attempted"
    assert record["posted"] == "unknown"
    assert "OSError" in record["press_error"]


# ---------------------------------------------------------------------------------------------
# post mode: proved only from a fresh visible settings popup
# ---------------------------------------------------------------------------------------------


def test_post_mode_is_disabled_only_with_a_fresh_settings_capture(
    tmp_path, monkeypatch
) -> None:
    _install_press(monkeypatch, [])
    result = _run(
        tmp_path,
        post=_report(SETTINGS_ROWS),
        settings=lambda *a, **k: _report(
            SETTINGS_ROWS, directory=ON, capture_dir=str(tmp_path / "captures"), run="capture-003"
        ),
    )
    assert result.post_mode == "VISUAL_DISABLED"
    assert result.post_capture_dir
    assert result.post_error == ""


def test_post_mode_stays_unknown_when_the_popup_is_absent(tmp_path, monkeypatch) -> None:
    _install_press(monkeypatch, [])
    result = _run(
        tmp_path,
        settings=lambda *a, **k: pytest.fail("no capture may be taken without a popup"),
    )
    assert result.post_mode == "UNKNOWN"
    assert "unknown" in result.post_error.lower()


# ---------------------------------------------------------------------------------------------
# capture identity: same run, foreign root, popup drift, kind swap
# ---------------------------------------------------------------------------------------------


def test_reusing_the_decision_capture_run_is_not_a_licence(tmp_path, monkeypatch) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    with pytest.raises(AcquisitionError, match="reuses the decision capture|own capture"):
        _run(
            tmp_path,
            reads=[
                _report(capture_dir=str(tmp_path / "captures"), run="capture-001"),
                _report(capture_dir=str(tmp_path / "captures"), run="capture-001"),
            ],
        )
    assert presses == []
    record = _record(tmp_path)
    assert record["phase"] == "preflight_refused"
    assert record["presses"] == 0 and record["press"] == "not_attempted"
    assert record["action"] == "completed"
    assert record["obligation_open"] is False


def test_a_capture_outside_the_invocation_root_is_not_a_licence(tmp_path, monkeypatch) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    with pytest.raises(AcquisitionError, match="outside this invocation|capture root"):
        _run(
            tmp_path,
            reads=[
                _report(capture_dir=str(tmp_path / "captures"), run="capture-001"),
                _report(
                    capture_dir=str(tmp_path / "elsewhere"), directory=ENTRY, run="capture-002"
                ),
            ],
        )
    assert presses == []
    assert _record(tmp_path)["phase"] == "preflight_refused"


def test_a_settings_kind_pair_cannot_licence_the_entry_press(tmp_path, monkeypatch) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    with pytest.raises(AcquisitionError, match="entry_no_numeric|contract"):
        _run(
            tmp_path,
            reads=[
                _report(capture_dir=str(tmp_path / "captures"), run="capture-001"),
                _report(
                    capture_dir=str(tmp_path / "captures"),
                    run="capture-002",
                    kind=CAPTURE_SETTINGS_NUMERIC,
                ),
            ],
        )
    assert presses == []
    assert _record(tmp_path)["phase"] == "preflight_refused"


def test_a_different_popup_at_the_boundary_refuses(tmp_path, monkeypatch) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    first = _report(capture_dir=str(tmp_path / "captures"), run="capture-001")
    second = _report(capture_dir=str(tmp_path / "captures"), run="capture-002")
    drifted = second.model_copy(
        update={"popup": second.popup.model_copy(update={"hwnd": 1005})}
    )
    with pytest.raises(AcquisitionError, match="different panel|popup"):
        _run(tmp_path, reads=[first, drifted])
    assert presses == []
    assert _record(tmp_path)["phase"] == "preflight_refused"


# ---------------------------------------------------------------------------------------------
# the press reads the geometry it is about to use
# ---------------------------------------------------------------------------------------------


def test_stale_entry_geometry_at_the_press_posts_nothing(monkeypatch) -> None:
    posted: list[int] = []
    monkeypatch.setattr(disable_multiplexed, "_click_hold", posted.append)
    monkeypatch.setattr(
        disable_multiplexed, "_class_of", lambda hwnd: "TSp_Panel" if hwnd == 1000 else "TSp_Button"
    )
    monkeypatch.setattr(
        disable_multiplexed, "_parent_of", lambda hwnd: WINDOW if hwnd == 1000 else 1000
    )
    moved = [
        {**row, "rect": (row["rect"][0], row["rect"][1] + 7, *row["rect"][2:])}
        if row["hwnd"] == ENTRY_HWND
        else row
        for row in _children()
    ]
    monkeypatch.setattr(disable_multiplexed, "_visible_children", lambda hwnd: tuple(moved))
    target = WindowTarget(hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr")
    with pytest.raises(AcquisitionError, match="licensed one|current rectangle|moved"):
        disable_multiplexed.press_disable_entry(
            target=target, popup_hwnd=1000, entry_hwnd=ENTRY_HWND, entry_rect=(10, 3, 148, 33)
        )
    assert posted == []


def test_a_vanished_popup_rect_at_the_press_posts_nothing(monkeypatch) -> None:
    posted: list[int] = []
    monkeypatch.setattr(disable_multiplexed, "_click_hold", posted.append)
    monkeypatch.setattr(disable_multiplexed, "_visible_children", lambda hwnd: ())
    target = WindowTarget(hwnd=WINDOW, thread_id=11, process_id=22, class_name="TMain_Scr")
    with pytest.raises(AcquisitionError, match="no current rectangle|gone"):
        disable_multiplexed.press_disable_entry(
            target=target, popup_hwnd=1000, entry_hwnd=ENTRY_HWND, entry_rect=(10, 3, 148, 33)
        )
    assert posted == []


# ---------------------------------------------------------------------------------------------
# the production role-map path: parent_of is the resolver's own statement
# ---------------------------------------------------------------------------------------------


def test_the_production_last_roles_path_normalises_the_resolver_parent_links(
    tmp_path, monkeypatch
) -> None:
    presses: list[int] = []
    _install_press(monkeypatch, presses)
    live = FakeDisableActuator()
    roles = _roles(ENTRY_ROWS)
    # A map read back from a capture may carry only the link: no row states its own parent.
    live.last_roles = {
        "raw": [dict(row) for row in roles["raw"]],
        "parent_of": {row[0]: row[1] for row in ENTRY_ROWS},
    }
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir(exist_ok=True)
    queue = [
        _report(capture_dir=str(capture_dir), run="capture-001"),
        _report(capture_dir=str(capture_dir), run="capture-002"),
    ]
    result = acquire_disable_multiplexed(
        capture_dir=capture_dir,
        trial_record=tmp_path / "trial.json",
        capture_entry=lambda *a, **k: queue.pop(0),
        actuator=live,
        enumerate_windows=lambda: (WINDOW,),
        read_popup=lambda *a, **k: ChannelsRead(
            surface=ChannelsSurface.ABSENT, readable=False
        ),
    )
    assert presses == [ENTRY_HWND]
    assert result.target_hwnd == ENTRY_HWND
    assert result.presses == 1
