"""What did the sweep leave on the screen? Read-only, three lines of state.

A run that ends on a store view leaves the operator with a blocked-looking application
until something normalises it, so the state after a sweep is part of the sweep's result,
not a detail of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from udv_echo_process.acquire.driver import Win32Actuator


def main() -> int:
    drv = Win32Actuator(channel=int(sys.argv[1]) if len(sys.argv) > 1 else 1)
    roles = drv._resolve()
    state = drv.strip_state()
    overlay = drv._find_overlay(roles)
    print(f"strip view   : {state.view.value} ({state.button_count} button(s))")
    print(f"panels       : {len(roles['panels'])}")
    print(f"visible ctrls: {len(roles['raw'])} (clean measurement screen: 43 in 4)")
    print(f"overlay      : {overlay[0].value if overlay else 'none'}")
    print(f"layout_note  : {drv.layout_note()!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
