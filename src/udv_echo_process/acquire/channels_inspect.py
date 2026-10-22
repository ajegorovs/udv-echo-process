"""One managed ``Channels`` inspection: open, read (and capture), close — with no operator gesture.

This is the reusable **application workflow** behind ``acquire channels-inspect``. It composes
the owners that already exist and invents no gesture of its own:

* the popup lifecycle — :meth:`…udop.parameters.ParametersSurface.open_channels_popup` (one
  measured hover on the proven anchor, or an adopted popup) and
  :meth:`…dismiss_channels_popup` (one bounded stepped real-cursor path);
* the reading — :func:`udv_echo_process.acquire.channels_read.read_channels`, including its
  opt-in :class:`~udv_echo_process.acquire.channels_capture.CaptureEvidence`;
* the strip's own view — :meth:`…driver.Win32Actuator.strip_state`, which is the only mode and
  recording predicate on this path. No field is re-derived here.

The caller's **original bound target** is used throughout: it is verified, never rebound, and
``allow_real_input`` is a required argument, so nothing on this path can silently hover the
operator's desktop. The command presses no popup entry and no strip button, enables nothing,
toggles nothing, records nothing and writes no parameter.

**Ownership, and the close.** The popup is closed in a ``finally`` only when this workflow owns
it — it opened it — or when the caller adopted an already-open popup **and** passed
``close_adopted=True``. An operator-opened popup that was merely adopted is left open by default,
and the report says so. The close result is its own field: a read (and capture) that succeeded
beside a close that was not observed ``ABSENT`` is reported exactly that way, never rolled into a
single verdict.

**Before any gesture**, in this order: real input must be allowed; the bound target must still be
the run's; and the strip must not be recording. A strip view that cannot be read is
``mode: "unknown"`` and refuses — it is never reported as ``ready``, and nothing is retried.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol

from udv_echo_process.acquire.actuator import StripView, WindowTarget
from udv_echo_process.acquire.channels_capture import CaptureEvidence
from udv_echo_process.acquire.channels_read import read_channels
from udv_echo_process.acquire.driver import AcquisitionError
from udv_echo_process.acquire.udop.parameters import (
    ChannelsDismissal,
    ChannelsOpen,
    DismissalOutcome,
    PopupOutcome,
)
from udv_echo_process.acquire.ui.channels import (
    READABLE_SURFACES,
    ChannelsRead,
    ChannelsSurface,
    surface_left_open,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "READABLE_SURFACES",
    "ChannelInspection",
    "InspectionOutcome",
    "inspect_channels",
]


class InspectionOutcome(str, Enum):
    """How far one managed inspection got — each member is an observed stage, not a success."""

    #: Refused before any gesture (real input, binding, recording, or an unreadable strip view).
    REFUSED = "refused"
    #: A popup read (and capture) was obtained, and the popup was not closed by this workflow.
    READ = "read"
    #: Read, and a close was observed ``ABSENT``.
    CLOSED = "closed"
    #: Read, but the close was not observed ``ABSENT`` (the popup may still be up).
    UNCONFIRMED = "unconfirmed"


class _Lifecycle(Protocol):
    def verify_bound_target(self, expected: WindowTarget) -> WindowTarget: ...

    def strip_state(self) -> object: ...

    def open_channels_popup(self, **kwargs: object) -> ChannelsOpen: ...

    def dismiss_channels_popup(self, **kwargs: object) -> ChannelsDismissal: ...


class ChannelInspection(ValueModel):
    """One inspection's evidence: the read, the capture and the close, each stated separately.

    ``mode`` is the strip view this run read before any gesture (``"unknown"`` when it could not
    be read, which refuses), and ``mode_source`` says which of the two it is. ``opened`` and
    ``closed`` are the lifecycle primitives' own records; ``read``/``capture`` survive a close
    that failed, and ``refused``/``refused_stage`` name a refusal that happened before the read.
    """

    outcome: InspectionOutcome
    mode: str
    mode_source: str
    refused: str | None = None
    refused_stage: str | None = None
    opened: ChannelsOpen | None = None
    read: ChannelsRead | None = None
    capture: CaptureEvidence | None = None
    closed: ChannelsDismissal | None = None
    popup_left_open: bool | None = None
    capture_dir: str | None = None
    notes: tuple[str, ...] = ()


def _reader(actuator: object, target: WindowTarget) -> Callable[..., ChannelsRead]:
    """The reading bound to this run's one target — the command's own read, never a new finder."""

    def read(**kwargs: object) -> ChannelsRead:
        return read_channels(actuator=actuator, target=target, **kwargs)

    return read


def _refused(
    stage: str, clause: str, *, mode: str, mode_source: str, **extra: object
) -> ChannelInspection:
    return ChannelInspection(
        outcome=InspectionOutcome.REFUSED,
        mode=mode,
        mode_source=mode_source,
        refused=clause,
        refused_stage=stage,
        **extra,
    )


def _left_open(
    opened: ChannelsOpen | None, reading: ChannelsRead | None
) -> bool | None:
    """Whether a popup is up after a failure — the shared surface classification, never a guess."""
    if reading is not None:
        return surface_left_open(reading.surface)
    if opened is not None:
        return surface_left_open(opened.surface)
    return None


def inspect_channels(
    *,
    actuator: _Lifecycle,
    target: WindowTarget,
    capture_dir: str | Path,
    allow_real_input: bool,
    adopt_open: bool = False,
    close_adopted: bool = False,
    settle_s: float = 3.0,
    read: Callable[..., ChannelsRead] | None = None,
) -> ChannelInspection:
    """Open (or adopt), read with capture evidence, then close — in that order, once each.

    ``allow_real_input`` is required because the opener's one gesture is a real-cursor hover;
    passing ``False`` refuses here by name instead of reaching the driver. ``adopt_open`` accepts
    an already-readable popup without a hover, and ``close_adopted`` is what lets this workflow
    close it — an adopted popup is the operator's unless the caller says otherwise.

    Nothing is retried: one open, one read (the capture path's own second read is inside
    ``read_channels``), one close. A close is attempted in a ``finally`` and only when the popup
    is owned (or explicitly adopted-and-closeable), so a capture failure still leaves the screen
    as the policy says it should.
    """
    reading = read if read is not None else _reader(actuator, target)
    directory = str(capture_dir)

    if not allow_real_input:
        return _refused(
            "real-input",
            "this workflow opens the Channels popup with one real-cursor hover, and "
            "allow_real_input=False: nothing is read, moved or clamped on this desktop",
            mode="unobserved",
            mode_source="refused-before-read",
        )

    try:
        actuator.verify_bound_target(target)
    except AcquisitionError as exc:
        return _refused(
            "binding",
            str(exc),
            mode="unobserved",
            mode_source="refused-before-read",
        )

    # The strip's own view is the mode/recording predicate: one read, no invented field.
    try:
        state = actuator.strip_state()
        mode = str(getattr(getattr(state, "view", None), "value", "unknown"))
        mode_source = "strip_state"
    except Exception as exc:  # noqa: BLE001 — an unreadable mode is a refusal, not "ready"
        return _refused(
            "mode",
            "the recording strip's view could not be read, so whether a recording is running "
            f"is UNKNOWN (never assumed 'ready') and nothing is opened: {exc}",
            mode="unknown",
            mode_source="unread",
        )
    if mode == StripView.RECORDING.value:
        return _refused(
            "recording",
            "the strip reads 'recording': a managed inspection would hover the menubar and "
            "walk the cursor across a live run, so nothing is opened and the recording is "
            "left untouched",
            mode=mode,
            mode_source=mode_source,
        )

    try:
        first = reading()
    except AcquisitionError as exc:
        return _refused(
            "read",
            f"the pre-open read failed, so no popup state is known and nothing is hovered: {exc}",
            mode=mode,
            mode_source=mode_source,
        )

    owner = False
    adopted = False
    opened: ChannelsOpen | None = None
    if first.surface in READABLE_SURFACES and first.readable:
        if not adopt_open:
            return _refused(
                "adopt",
                "a readable Channels popup is already open and adopt_open=False: this workflow "
                "does not take over a popup it did not open, so nothing is read or moved",
                mode=mode,
                mode_source=mode_source,
            )
        adopted = True
    elif first.surface is not ChannelsSurface.ABSENT:
        return _refused(
            "surface",
            f"the pre-open reading is {first.surface.value!r}, neither 'absent' nor a readable "
            "Channels popup: nothing is hovered and nothing else is dismissed",
            mode=mode,
            mode_source=mode_source,
        )
    else:
        try:
            opened = actuator.open_channels_popup(
                target=target,
                read=reading,
                timeout_s=max(0.0, settle_s),
                adopt_open=True,
            )
        except AcquisitionError as exc:
            return _refused(
                "open",
                str(exc),
                mode=mode,
                mode_source=mode_source,
            )
        if opened.outcome is not PopupOutcome.OPEN:
            return ChannelInspection(
                outcome=InspectionOutcome.REFUSED,
                mode=mode,
                mode_source=mode_source,
                refused=(
                    "the measured Channels hover produced no readable popup: "
                    f"{opened.clause or opened.surface}"
                ),
                refused_stage="open",
                opened=opened,
                popup_left_open=_left_open(opened, None),
                capture_dir=directory,
            )
        owner = True

    notes: list[str] = []
    figure: ChannelsRead | None = None
    capture: CaptureEvidence | None = None
    read_failed: str | None = None
    try:
        try:
            figure = reading(capture_dir=directory)
            capture = figure.capture
        except Exception as exc:  # noqa: BLE001 — any failure here is a stated partial fact
            read_failed = f"{type(exc).__name__}: {exc}"
            notes.append(
                "the capture read failed, so no read or capture evidence exists for this run: "
                f"{read_failed}"
            )
    finally:
        closed: ChannelsDismissal | None = None
        close_failed: str | None = None
        closeable = owner or (adopted and close_adopted)
        surface_now = None if figure is None else figure.surface
        if surface_now is ChannelsSurface.ABSENT:
            notes.append("the popup read 'absent' before the close: no path was walked")
        elif closeable:
            try:
                closed = actuator.dismiss_channels_popup(
                    target=target, read=reading, timeout_s=max(0.0, settle_s)
                )
            except Exception as exc:  # noqa: BLE001 — a failed close keeps the read evidence
                close_failed = f"{type(exc).__name__}: {exc}"
        elif adopted:
            notes.append(
                "the popup was adopted, not opened, and close_adopted=False: it is left open "
                "for the operator"
            )

    closed_absent = closed is not None and closed.outcome is DismissalOutcome.ABSENT
    popup_left_open: bool | None
    if closed is not None:
        popup_left_open = not closed_absent
    elif surface_now is ChannelsSurface.ABSENT:
        popup_left_open = False
    elif adopted and not closeable:
        popup_left_open = True
    else:
        popup_left_open = _left_open(opened, figure)

    if closed_absent:
        outcome = InspectionOutcome.CLOSED
    elif closeable:
        outcome = InspectionOutcome.UNCONFIRMED
    else:
        outcome = InspectionOutcome.READ

    refused = read_failed
    stage = "capture" if read_failed is not None else None
    if close_failed is not None:
        notes.append(f"the close was refused, and is not retried: {close_failed}")
    if closed is not None and not closed_absent:
        notes.append(
            "the close was not observed ABSENT (outcome "
            f"{closed.outcome.value!r}, last surface {closed.surface_after!r}); no second path "
            "is walked"
        )

    return ChannelInspection(
        outcome=outcome,
        mode=mode,
        mode_source=mode_source,
        refused=refused,
        refused_stage=stage,
        opened=opened,
        read=figure,
        capture=capture,
        closed=closed,
        popup_left_open=popup_left_open,
        capture_dir=directory,
        notes=tuple(notes),
    )
