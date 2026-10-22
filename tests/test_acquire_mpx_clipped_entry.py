"""Offline: the shared clipped-entry lifecycle and the acceptance probe's refusals.

The lifecycle is the one implementation both ``acquire mpx-run`` and
``tools/live/probes/mpx_enabled_menu_lifecycle.py`` call. These tests script the owners it
composes (a bound read, the actuator's dismissal, a fresh capture report) and assert the
**sequence and the licences**: one fresh read, one dismissal only from the clipped surface, a
fresh live-bracketed enabled pair when required, and a fresh ABSENT re-read.

What these tests do **not** establish: any real-provider or desktop behaviour. They are offline.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

from udv_echo_process.acquire import mpx_run
from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.channels_capture import (
    CaptureEvidence,
    GuardComparison,
    NumericBracketing,
    WindowGuard,
)
from udv_echo_process.acquire.mode_marks import ModeMarkAttribution
from udv_echo_process.acquire.mpx_run import ClippedEntryStage, settle_clipped_entry
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    DismissalOutcome,
)
from udv_echo_process.acquire.ui.channels import ChannelsRead, ChannelsSurface

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools" / "live" / "probes"))


def target(hwnd: int = 4242) -> WindowTarget:
    return WindowTarget(hwnd=hwnd, thread_id=11, process_id=22, class_name="TMain_Scr")


def _read(surface: ChannelsSurface, *, capture: CaptureEvidence | None = None) -> ChannelsRead:
    return ChannelsRead(
        surface=surface,
        readable=surface is not ChannelsSurface.ABSENT,
        capture=capture,
    )


def entry_capture(
    *,
    mode: str = "VISUAL_ENABLED",
    mark_surface: str = "MULTIPLEXER_ON_ENTRY",
    directory: str | None = None,
    hwnd: int = 4242,
    popup_hwnd: int | None = 9001,
    context: str = "live-bracketed",
    freshness: str = "live_bracketed",
    integrity: str = "capture-digest-verified",
    agreed: bool = True,
) -> CaptureEvidence:
    guard = WindowGuard(label="UDOP", hwnd=hwnd, popup_hwnd=popup_hwnd)
    return CaptureEvidence(
        status="ok",
        captured=True,
        directory=directory,
        guards=GuardComparison(before=guard, after=guard.model_copy(), consistent=True),
        numeric=NumericBracketing(applicable=False),
        visual_mode_mark=ModeMarkAttribution(
            surface=mark_surface,
            label="DESABLE_MULTIPLEXER",
            mode=mode,
            mark="GREEN_CHECK" if mode == "VISUAL_ENABLED" else "RED_CROSS",
            rolling="UNKNOWN",
            acquisition_context=context,
            freshness=freshness,
            integrity=integrity,
            frames_agreed=agreed,
            recognition="EXACT_TEMPLATE_MATCH",
            frame_digests=("a" * 64, "b" * 64),
        ),
    )


def dismissal(
    outcome: DismissalOutcome = DismissalOutcome.ABSENT,
    *,
    before: str = "multiplexer_on_entry",
    after: str = "absent",
):
    return ChannelsDismissal(
        outcome=outcome, point=(500, 500), surface_before=before, surface_after=after
    )


class Script:
    """The three seams the lifecycle calls, in one ordered log."""

    def __init__(
        self,
        surfaces: list[ChannelsSurface] | None = None,
        *,
        close_outcome: DismissalOutcome = DismissalOutcome.ABSENT,
        close_after: str = "absent",
        read_error: BaseException | None = None,
        close_error: BaseException | None = None,
        reread_error: BaseException | None = None,
    ) -> None:
        self.surfaces = list(
            surfaces
            or [ChannelsSurface.MULTIPLEXER_ON_ENTRY, ChannelsSurface.ABSENT]
        )
        self.close_outcome = close_outcome
        self.close_after = close_after
        self.read_error = read_error
        self.close_error = close_error
        self.reread_error = reread_error
        self.calls: list[str] = []
        self.capture_calls = 0

    def read(self) -> ChannelsRead:
        index = len([c for c in self.calls if c == "read"])
        self.calls.append("read")
        if index >= 1 and self.reread_error is not None:
            raise self.reread_error
        if index == 0 and self.read_error is not None:
            raise self.read_error
        return _read(self.surfaces.pop(0) if self.surfaces else ChannelsSurface.ABSENT)

    def capture(self) -> ChannelsRead:
        self.capture_calls += 1
        self.calls.append("capture")
        return _read(
            ChannelsSurface.MULTIPLEXER_ON_ENTRY,
            capture=entry_capture(directory=None),
        )

    def close(self):
        self.calls.append("close")
        if self.close_error is not None:
            raise self.close_error
        return dismissal(self.close_outcome, after=self.close_after)


# ---------------------------------------------------------------------------------------------
# the sequence, and each refusal, on the shared implementation
# ---------------------------------------------------------------------------------------------


def test_the_lifecycle_reads_once_dismisses_once_and_requires_absent() -> None:
    script = Script()
    result = settle_clipped_entry(target=target(), read=script.read, close=script.close)

    assert result.stage is ClippedEntryStage.ABSENT
    assert result.absent
    assert script.calls == ["read", "close", "read"]
    assert result.surface_before == "multiplexer_on_entry"
    assert result.surface_after == "absent"
    assert result.owed == ()


def test_a_required_enabled_capture_is_taken_before_the_dismissal() -> None:
    script = Script()
    result = settle_clipped_entry(
        target=target(),
        read=script.read,
        close=script.close,
        capture=script.capture,
        capture_dir=Path.cwd(),
        require_enabled=True,
    )

    assert result.stage is ClippedEntryStage.ABSENT
    assert result.enabled_mode == "VISUAL_ENABLED"
    assert script.calls == ["read", "capture", "close", "read"]


def test_a_read_that_is_not_clipped_walks_no_dismissal_or_capture() -> None:
    script = Script([ChannelsSurface.SETTINGS_POPUP])
    result = settle_clipped_entry(
        target=target(),
        read=script.read,
        close=script.close,
        capture=script.capture,
        capture_dir=Path.cwd(),
        require_enabled=True,
    )

    assert result.stage is ClippedEntryStage.NOT_CLIPPED
    assert script.calls == ["read"]
    assert script.capture_calls == 0
    assert "no dismissal was walked" in result.reason


def test_a_disabled_capture_never_licenses_the_dismissal() -> None:
    script = Script()
    disabled = _read(
        ChannelsSurface.MULTIPLEXER_ON_ENTRY,
        capture=entry_capture(mode="VISUAL_DISABLED"),
    )
    result = settle_clipped_entry(
        target=target(),
        read=script.read,
        close=script.close,
        capture=lambda: disabled,
        capture_dir=Path.cwd(),
        require_enabled=True,
    )

    assert result.stage is ClippedEntryStage.NOT_ENABLED
    assert script.calls == ["read"]
    assert "VISUAL_DISABLED" in result.reason


@pytest.mark.parametrize(
    "overrides",
    [
        {"context": "retained"},
        {"freshness": "not_established"},
        {"integrity": "decoded-pair-only"},
        {"agreed": False},
        {"hwnd": 7777},
        {"mark_surface": "SETTINGS_FULL"},
    ],
)
def test_a_capture_that_is_not_this_runs_licensed_pair_refuses(overrides: dict) -> None:
    script = Script()
    report = _read(
        ChannelsSurface.MULTIPLEXER_ON_ENTRY, capture=entry_capture(**overrides)
    )
    result = settle_clipped_entry(
        target=target(),
        read=script.read,
        close=script.close,
        capture=lambda: report,
        capture_dir=Path.cwd(),
        require_enabled=True,
    )

    assert result.stage is ClippedEntryStage.NOT_ENABLED
    assert script.calls == ["read"]


def test_a_required_capture_seam_that_is_missing_refuses() -> None:
    script = Script()
    result = settle_clipped_entry(
        target=target(), read=script.read, close=script.close, require_enabled=True
    )

    assert result.stage is ClippedEntryStage.NOT_ENABLED
    assert script.calls == ["read"]


def test_a_fresh_read_that_raises_is_its_own_stage() -> None:
    script = Script(read_error=RuntimeError("capture backend down"))
    result = settle_clipped_entry(target=target(), read=script.read, close=script.close)

    assert result.stage is ClippedEntryStage.READ_RAISED
    assert "capture backend down" in result.error
    assert script.calls == ["read"]


def test_a_dismissal_that_raises_leaves_the_popup_owed() -> None:
    script = Script(close_error=RuntimeError("the dismissal geometry cannot fit"))
    result = settle_clipped_entry(target=target(), read=script.read, close=script.close)

    assert result.stage is ClippedEntryStage.DISMISS_RAISED
    assert "cannot fit" in result.error
    assert any("may still be open" in clause for clause in result.owed)
    assert script.calls == ["read", "close"]


def test_a_dismissal_that_is_not_absent_is_not_retried() -> None:
    script = Script(close_outcome=DismissalOutcome.UNKNOWN, close_after="multiplexer_on_entry")
    result = settle_clipped_entry(target=target(), read=script.read, close=script.close)

    assert result.stage is ClippedEntryStage.NOT_ABSENT
    assert result.close is not None
    assert script.calls == ["read", "close"]
    assert any("absence was not observed" in clause for clause in result.owed)


def test_a_closing_read_that_raises_is_not_an_absence() -> None:
    script = Script(reread_error=RuntimeError("read failed"))
    result = settle_clipped_entry(target=target(), read=script.read, close=script.close)

    assert result.stage is ClippedEntryStage.REREAD_RAISED
    assert script.calls == ["read", "close", "read"]


def test_a_popup_still_present_after_the_dismissal_refuses() -> None:
    script = Script([ChannelsSurface.MULTIPLEXER_ON_ENTRY, ChannelsSurface.SETTINGS_POPUP])
    result = settle_clipped_entry(target=target(), read=script.read, close=script.close)

    assert result.stage is ClippedEntryStage.STILL_PRESENT
    assert "not 'absent'" in result.reason


def test_the_production_composition_calls_this_helper_and_never_reimplements_it() -> None:
    source = inspect.getsource(mpx_run.run_mpx_once)
    assert "settle_clipped_entry(" in source
    # The inline lifecycle is gone: no second fresh-read/dismiss/ABSENT block remains.
    assert "the clipped entry's owned dismissal refused or raised" not in source
    assert source.count("read_fn(live, target=bound)") == 2  # the helper read + its close


# ---------------------------------------------------------------------------------------------
# the acceptance probe: fail-closed before the hover, no other owner's action
# ---------------------------------------------------------------------------------------------


def _probe():
    spec = importlib.util.spec_from_file_location(
        "mpx_enabled_menu_lifecycle",
        REPO / "tools" / "live" / "probes" / "mpx_enabled_menu_lifecycle.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["mpx_enabled_menu_lifecycle"] = module
    spec.loader.exec_module(module)
    return module


def test_the_probe_refuses_a_screen_it_did_not_open() -> None:
    probe = _probe()

    assert probe._initial_refusal(_read(ChannelsSurface.ABSENT)) == ""
    for surface in (
        ChannelsSurface.SETTINGS_POPUP,
        ChannelsSurface.MULTIPLEXER_ON_ENTRY,
    ):
        refusal = probe._initial_refusal(_read(surface))
        assert refusal and "never adopts" in refusal


def test_the_probe_composes_the_production_helper_and_no_other_action() -> None:
    probe = _probe()
    source = inspect.getsource(probe.main)

    assert "settle_clipped_entry(" in source
    assert "require_enabled=True" in source
    assert "open_channels_popup(" in source
    assert "dismiss_channels_popup(" in source
    for forbidden in (
        "run_mpx_once",
        "record_multiplexed",
        "store_preflight",
        "set_rollover(",
        "acquire_enable_multiplexed(",
        "press_mode_toggle(",
        "disable_multiplexed",
    ):
        assert forbidden not in source, forbidden
    assert probe.BASELINE == "off"
    assert any("Disable" in clause for clause in probe.RESTORATION_OWED)
    assert "Record: none" in probe.SCOPE["presses"]
