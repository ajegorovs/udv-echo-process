"""Read the operator-opened Channels popup without opening, closing or changing it.

Bind exactly one visible application, take its public screen snapshot, and query
visible edit controls with the driver's bounded WM_GETTEXT reader. GetWindowText
cannot supply cross-process control values. WM_GETTEXT is a read query, not a
setting write or posted input. No press, combo selection, commit, hover or cursor
movement occurs. Root identity is checked around the queries; existing child
handle lifetime limitations remain.
"""

from __future__ import annotations

from udv_echo_process.acquire.actuator import WindowTarget
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


def read_channels(
    actuator: Win32Actuator | None = None,
    *,
    target: WindowTarget | None = None,
) -> ChannelsRead:
    """Inspect the already-open popup on one bound window; never perform a gesture.

    ``target`` is for a caller that already bound the window in an earlier step: the binding is
    then **verified**, never replaced, so a read taken right before a write cannot silently
    migrate to a different window. Without it the one visible window is bound here, which is the
    read-only command's behaviour and stays the default.
    """
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
    return resolve_channels(observation_of({**roles, "raw": rows}))
