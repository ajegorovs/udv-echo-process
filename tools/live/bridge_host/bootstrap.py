"""The module file ``--bridge-runner`` / ``UDV_BRIDGE_RUNNER`` points at.

`live.bridge_module` loads a **file by path** and looks for the ``guarded_cycle`` attribute on it, so
this file exists to be that path: the package's loading seam gets the factory without the package
needing to know this directory, and the factory's own module stays a normal importable package.

It also puts its parent on ``sys.path`` — the one thing a path-loaded module cannot inherit — so
``bridge_host`` imports the same way it does from a shell. Nothing else happens at import: no
configuration is read, no process is started, no application is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent  # tools/live
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bridge_host.api import activation_report, guarded_cycle

__all__ = ["activation_report", "guarded_cycle"]
