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
./tools/live/dispatch.sh -m udv_echo_process.cli acquire status
```

`dispatch.sh` writes the target and its arguments to `outputs/live/task_target.txt` and
`task_args.txt`, starts the task, and **polls the target's log** for its closing
`=== exit=<code> ===` instead of sleeping a fixed time — a fixed sleep makes a 24 s run look
like a two-minute stall, and it hides *whose* time is being spent. Set
`LIVE_TASK_NAME` to use a different task name, `PROBE_TIMEOUT_S` to change the poll cap.

### Two forms of target

```bash
./tools/live/dispatch.sh -m udv_echo_process.cli acquire status   # a package command, from the repo root
./tools/live/dispatch.sh move_window.py move                       # a probe file, from tools/live/probes
```

The `-m` form is how the supported commands are reached, and it is the one the bring-up
checklist uses; the file form stays for measurements that are not commands (a geometry probe, a
one-off diagnostic). Both write their log to `outputs/live/task-<target>.log`.

## The commands

The supported way to drive the instrument is the package's own CLI, started with the `-m` form
above. Because it lives in the package it can be tested headless against the fakes, which is
what the ported probe scripts could not be — they reached into the driver's private members.

| command | what it does | writes to the app? |
|---|---|---|
| `acquire status` | read-only inventory: window class/rect/maximised, screen, panels, visible control count, strip view, overlay, `layout_note`, cursor, foreground | no |
| `acquire channel <n>` | opens `Parameters → Operating parameters`, reads the channel, writes it only if it differs, and reports the channel's mode (manual/assisted) with the panel counts | only if the channel differs |
| `acquire preflight [--seconds N]` | the operator's sequence with nothing stored: clear-and-restart if needed → record → hold → stop → `Do store` → read the Store dialog (name, working directory, children) → cancel with its **left** button | no store; presses the strip |
| `acquire point <name> --seconds N` | one whole point: reset, channel, record `N` seconds, stop, name the file, store, read it back and decode it | stores one file |
| `acquire sweep --seconds N --rungs 1,2` | the runner's own path for a multi-point sweep: `plan_sweep` → write → read back → record → store → decode → verify → one JSONL entry per point | stores files |
| `acquire plan --definition FILE` | loads and validates a campaign definition and prints its points, with a note wherever the window outruns what the block will keep | no |
| `acquire campaign --definition FILE [--resume]` | runs a definition point by point through the runner — one JSONL entry per point, a job manifest beside the log, and `--resume` skipping what the log already holds | stores files |
| `acquire report --log FILE` | reads a finished job (log + manifest) and prints each point's status and the summary | no |
| `acquire decode <file> --channel N` | a stored file's own operation words, off the instrument: the file is the authority | no |

The campaign is the near-term goal written down: one channel, one 10-15 s window, a slot of
parameter permutations. `examples/campaign-single-channel.json` is a working one — 12 s points
over the resolution ladder k=1/2/4/8 at the 99 mm window, with the k=1 baseline repeated at the
start, middle and end of the axis. Measured on the first machine: six points in 104 s, one
parameters dialog for the whole run, and a re-run with `--resume` finishing in seconds with
nothing to do.

`point`, `sweep` and `campaign` take the application's own working directory from `--store-dir` or
`UDV_STORE_DIR` (the cycle **asserts** the Store dialog against it, so a wrong value refuses the
point rather than scattering files). `--json` prints a machine-readable report — notes then go
to stderr, so stdout stays parseable — and the exit codes are 0 ok, 1 a refused point, 2 usage.

### What is still a probe

`probes/` holds what measures something no command covers. Today that is six files:

| probe | what it measures | writes to the app? |
|---|---|---|
| `move_window.py move\|restore` | relocates the application window (un-maximising first) so the geometry assumptions can be tested, then puts it back | moves the window |
| `main_geometry.py` | the main window's own geometry, whole control tree, and where the strip sits — presses **nothing** | no |
| `w1_fixed_facts.py` | where the dialog-only fixed facts (sound speed, first gate, burst length) and the block cap are stated on the live application | opens/closes the dialog |
| `dialog_fields.py` | every control of the `Operating parameters` dialog — the fast read-only half of the identification pass | opens/closes the dialog |
| `dialog_shot.py` | **the capture half**: one whole-screen frame plus the dialog's own rect cropped from that same frame, lossless PNG, with `image_stats`/`non_blank` and a two-frame stability check | opens/closes the dialog |
| `dialog_write.py` | writes **one** `Operating parameters` knob, commits it at `Accept`, and reads the round trip back (incl. the below-floor volume refusal modes) | writes one knob |

`dialog_shot.py` is the one to reach for whenever a caption or a value has to be *read* —
these widgets carry no window text and their labels are paint, so `tools/ui/README.md` (the
magnify/glyph step) is its companion. Its output lands in `outputs/live/dialog.png` (the
dialog) and `dialog-full.png` (the frame it was cut from).

Anything that becomes a *capability* belongs in the package, where a fake can drive it. That is
the rule the ported scripts broke: they worked on the instrument and could not be tested, so
nothing caught them drifting. Logs, screenshots and job records land in `outputs/live/`, and the
application's own Store directory is `outputs/live/store/` (git-ignored, beside them) — it used to
be inside the retired reconnaissance archive, which is why that folder kept growing after the port.
The driver asserts that directory rather than assuming it, so a run whose `--store-dir` disagrees
with the application refuses instead of scattering files.

## Where the rest lives

`docs/dop3000/` carries the durable findings — the parameter-sweep matrix, the automation
reference, the acquisition handoff, and the manual corpus. The **reconnaissance archive** (the
numbered probes `01..63`, their raw outputs and captures, the first end-to-end evidence) was a
separate repository that was deliberately not a dependency of this one; the code here cites it by
number where a rule was measured (`recon/41` for the menubar gesture, `recon/19` for the strip) so
the origin stays traceable. **It was retired on 2026-09-18** and is now a frozen zip
(`~/Repos/_archive/dop-control-20260918.zip`); what it held, what was lifted into this repository,
what was never ported, and how the Store directory moved off it are in
[`../../docs/dop3000/recon-archive-retirement.md`](../../docs/dop3000/recon-archive-retirement.md).

Bring-up order for a machine that is not the one these measurements were taken on:
[`docs/dop3000/live-bringup.md`](../../docs/dop3000/live-bringup.md).
