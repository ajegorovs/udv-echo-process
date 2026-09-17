# tools/live — driving the instrument from a shell that cannot see it

The acquisition code in `src/udv_echo_process/acquire/` is a library: it posts messages, hovers
a menubar and presses strip buttons, but nothing here *starts* a run. This directory is the
missing half — the way a probe gets started in the session that owns the screen — and it lives
in the repository so a machine that has only a clone can still run the test.

Everything is relative to this file's own location: no machine name, no user, no repository
path. Clone anywhere.

## Why starting a probe is not just `python probe.py`

The agent shell runs in **session 0** (a service window station); UDOP runs in the interactive
**session 1**. Measured from the service session: `GetCursorPos` fails with error 1459,
`GetForegroundWindow()` returns 0, `FindWindow('TMain_Scr')` returns 0. Nothing that touches
the application's screen can run there — it has to be *started in* session 1, and from session
0 the only route is the Task Scheduler.

`task_run.py` is the entry point that route runs. It launches the probe with
`CREATE_NO_WINDOW` under `pythonw.exe` and tees the output to `outputs/live/task-<probe>.log`.
Read its docstring before changing it: the `pythonw` rule is load-bearing. A `.cmd` action
gives the task a **console window on the interactive desktop, in front of the application**,
and an inactive window ignores hover, so the menubar step then opens nothing (measured,
`recon/53`).

## Create the task (once per machine)

The interpreter path must be absolute and is the one thing that is machine-specific. From a
shell in the repository, with the path adjusted to this clone:

```bat
schtasks /create /tn hermes_gui_probe /tr "\"C:\path\to\clone\.venv\Scripts\pythonw.exe\" \"C:\path\to\clone\tools\live\task_run.py\"" /sc once /st 00:00 /f
```

Then dispatch (the same task is triggered on demand with `/run`):

```bash
./tools/live/dispatch.sh status_screen.py 1
```

`dispatch.sh` writes the probe name and its arguments to `outputs/live/task_target.txt` and
`task_args.txt`, starts the task, and **polls the probe's log** for its closing
`=== exit=<code> ===` instead of sleeping a fixed time — a fixed sleep makes a 24 s run look
like a two-minute stall, and it hides *whose* time is being spent. Set
`LIVE_TASK_NAME` to use a different task name, `PROBE_TIMEOUT_S` to change the poll cap.

## The probes

| probe | what it does | writes to the app? |
|---|---|---|
| `status_screen.py <channel>` | read-only inventory: window class/rect/maximised, screen, panels, visible control count, strip view, overlay, `layout_note`, cursor | no |
| `channel_select.py <channel>` | opens `Parameters → Operating parameters`, reads the channel, writes it only if it differs, reports the channel's mode (manual/assisted) and the panel counts | only if the channel differs |
| `point_cycle.py preflight` | the operator's sequence with nothing stored: clear-and-restart if needed → record → hold → stop → `Do store` → read the Store dialog (name, working directory, children) → cancel | no store; presses the strip |
| `point_cycle.py store <name> <seconds> [channel] [lift]` | one whole point: reset, channel, record `seconds`, stop, name the file, store, read it back | stores a file |
| `sweep_run.py <seconds> <channel> <rungs>` | the runner's own path for a multi-point sweep: `plan_sweep` → write → read back → record → store → decode → verify → one JSONL entry per point | stores files |
| `move_window.py move\|restore` | relocates the application window (un-maximising first) so geometry assumptions can be tested; `restore` puts it back maximised | moves a window |

`point_cycle.py` and `sweep_run.py` take the application's own working directory from
`UDV_STORE_DIR` (the cycle **asserts** the Store dialog against it, so a wrong value refuses
the point rather than scattering files). Logs, screenshots and sweep records land in
`outputs/live/`; stored `.BDD` files land wherever the application is configured to write.

## Where the rest lives

`docs/dop3000/` carries the durable findings — the parameter-sweep matrix, the automation
reference, the acquisition handoff, and the manual corpus. The **reconnaissance archive** (the
numbered probes `01..63`, their raw outputs and captures, the first end-to-end evidence) is a
separate repository that is deliberately not a dependency of this one: the code here cites it
by number where a rule was measured (`recon/41` for the menubar gesture, `recon/19` for the
strip) so the origin stays traceable, and `docs/dop3000/udop-automation.md` plus
`docs/dop3000/handoff-dop3010-acquisition.md` carry the substance of those measurements.

Bring-up order for a machine that is not the one these measurements were taken on:
[`docs/dop3000/live-bringup.md`](../../docs/dop3000/live-bringup.md).
