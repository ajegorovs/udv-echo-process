"""One window binding for a composition, and never a second one.

A composed workflow binds the instrument **once**, verifies that record, and hands it to every
child. Before this module each child called ``bind_target`` for itself, so a composition could
end up driving a window that was re-resolved after the parent had already compared, recorded or
pressed against the original. The two rules that prevent that are here and nowhere else:

* a child given ``bound_target`` calls :meth:`…Actuator.verify_bound_target` and **never**
  ``bind_target``;
* the enumerated window must be the same ``hwnd`` the caller bound, or the child refuses with
  nothing pressed. A ``verify_bound_target`` call against a different handle would verify the
  wrong window, which is why the comparison comes first.

``bound_target=None`` keeps every existing caller's behaviour exactly: one ``bind_target`` on the
single enumerated window.
"""

from __future__ import annotations

from collections.abc import Sequence

from udv_echo_process.acquire.actuator import WindowTarget
from udv_echo_process.acquire.driver import AcquisitionError

__all__ = ["resolve_bound_target"]


def resolve_bound_target(
    actuator,
    windows: Sequence[int],
    *,
    bound_target: WindowTarget | None,
    class_name: str,
) -> WindowTarget:
    """The run's one target: the caller's verified record, or a fresh bind when none was given.

    ``windows`` is the caller's own enumeration, already required to hold exactly one window.
    With a ``bound_target`` this refuses when the enumerated handle differs, then verifies the
    expected record — in that order, and without ever binding again.
    """
    expected_hwnd = int(windows[0])
    if bound_target is None:
        return actuator.bind_target(expected_hwnd)
    if not isinstance(bound_target, WindowTarget):
        raise AcquisitionError(
            "bound_target must be a WindowTarget record: this command will not bind a second "
            "time to guess which window the caller meant"
        )
    if int(bound_target.hwnd) != expected_hwnd:
        raise AcquisitionError(
            f"the enumerated {class_name} window is {expected_hwnd} where the caller bound "
            f"{bound_target.hwnd}: the target changed, so nothing was pressed and nothing was "
            "re-bound"
        )
    verify = getattr(actuator, "verify_bound_target", None)
    if verify is None:
        raise AcquisitionError(
            "the actuator cannot verify the caller's bound target, and this command never binds "
            "a second time: nothing was pressed"
        )
    return verify(bound_target)
