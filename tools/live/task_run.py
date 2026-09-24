"""The scheduled task's entry point: run one in-repo probe in the interactive session.

**Why this file is in the repository.** Some agent shells run in a service window station while
UDOP runs in an interactive user session. When the current shell cannot access that session, anything
that touches the application's screen has to be *started there*, and the repository's route is Task
Scheduler. So a second machine needs this file, the dispatcher beside it, and the task itself —
which is why all of it lives in the repository, with every path taken from this file's own
location. Nothing here knows a machine name, a user, or a repository path.

**Why ``pythonw.exe`` and never a ``.cmd``.** A ``.cmd`` action gives the task a *console
window*, and that console is created on the interactive desktop — in front of the application
being driven. Measured in the reconnaissance repository (``recon/53``): with the ``.cmd`` route
the foreground window was ``ConsoleWindowClass``/``cmd.exe``, UDOP reported
``is_foreground=False, has_focus=False``, and the menubar hover then opened nothing, because an
inactive window ignores hover. ``pythonw.exe`` creates no console at all, and the child is
started with ``CREATE_NO_WINDOW``, so this route cannot take the foreground from anything.

The probe and its arguments arrive in two small files — argument quoting through ``schtasks
/tr`` is where that breaks — and the child's combined output is teed to
``outputs/live/task-<probe>.log``, closing with ``=== exit=<code> ===`` so a dispatcher can poll
for the end of the run instead of sleeping for it.

Nothing here touches the GUI: the child does that, in this same interactive session.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

#: ``tools/live`` -> the repository it was cloned into. Works at any clone path.
LIVE = Path(__file__).resolve().parent
REPO = LIVE.parents[1]
PROBES = LIVE / "probes"
OUT = REPO / "outputs" / "live"

#: The project's own interpreter, which has this probe's dependencies (``uv sync --extra
#: acquire`` installs pywin32). Falls back to whatever interpreter is running this file, so a
#: machine that keeps its environment elsewhere still works.
VENV_PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
PYTHON = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)

#: The child gets no console of its own: it must not appear in front of the application.
CREATE_NO_WINDOW = 0x08000000

#: A sweep of a dozen 15 s points is minutes, not seconds; the bound is a backstop, not a wait.
TIMEOUT_S = 1800


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    probe = (OUT / "task_target.txt").read_text(encoding="utf-8").strip()
    if not probe:
        print("nothing to run: outputs/live/task_target.txt is empty")
        return 2
    args = shlex.split((OUT / "task_args.txt").read_text(encoding="utf-8"))

    # Two forms, because the interface is not always a file any more:
    #   "-m <module> [args...]"  an installed module, run from the repository root — this is how
    #                            the supported commands are reached (`udv-acquire`).
    #   "<probe.py> [args...]"   a file under tools/live/probes, run from its own directory for
    #                            the throwaway measurements that are not commands.
    module = probe.removeprefix("-m ") if probe.startswith("-m ") else None
    if module is None and not (PROBES / probe).is_file():
        print(f"no such probe: {PROBES / probe}")
        return 2
    command = [str(PYTHON), "-m", module, *args] if module else [
        str(PYTHON),
        str(PROBES / probe),
        *args,
    ]
    cwd = REPO if module else PROBES
    slug = re.sub(r"[^A-Za-z0-9_.-]", "-", probe.removeprefix("-m "))

    log = OUT / f"task-{slug}.log"
    started = time.strftime("%d/%m/%Y %H:%M:%S")
    header = f"=== {started} running {probe} {' '.join(args)} (no console: pythonw) ===\n"
    try:
        done = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            creationflags=CREATE_NO_WINDOW,
            check=False,  # the return code *is* the result here, logged below
        )
        body = (done.stdout or "") + (done.stderr or "")
        code = done.returncode
    except subprocess.TimeoutExpired as exc:
        body = f"TIMEOUT after {TIMEOUT_S} s\n{exc.stdout or ''}{exc.stderr or ''}"
        code = 3
    log.write_text(f"{header}{body}\n=== exit={code} ===\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
