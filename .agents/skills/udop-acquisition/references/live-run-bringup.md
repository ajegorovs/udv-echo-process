# Running the automation on a machine that is not the one it was measured on

The automation is only as useful as the ability to start it somewhere else. This is the shape
of that: what the deliverable repository must carry, the staged way to find out what a new
machine does differently, and how to get most of that answer before the machine exists.

## What the deliverable repository must carry

Reconnaissance and the runnable path want different homes. The probes that produced the
*findings* are evidence and belong in a scratch archive, cited by name in docstrings and never
imported. The handlers that make the automation *runnable* belong in the repository beside the
code, or a second machine can clone it and still run nothing.

A workable layout (`tools/live/` — outside the packaged `src/`, since it never runs in CI):

| file | job |
|---|---|
| `task_run.py` | the interactive session's entry point: runs one target with `CREATE_NO_WINDOW` under a GUI-subsystem host, tees the output to `outputs/live/task-<slug>.log`, closes with `=== exit=<code> ===` |
| `dispatch.sh` | writes the target and its arguments to two small files, triggers the task, then **polls** that log (2 s steps, hard cap, log printed either way) — never a fixed sleep |
| `probes/` | the throwaway measurements that are *not* commands — a geometry probe, a one-off diagnostic. The capabilities themselves belong in the package (next section) |

Rules that make the set portable:

- **Every path derives from `__file__`** — the repository root, the probe directory, the output
directory. No clone path, machine name or user appears anywhere. The interpreter is the
project's own venv when it exists, falling back to the running one.
- **The scheduled task is created once per machine** and is the only machine-specific value
(an absolute interpreter path). Document the creation command next to the dispatcher.
- **Arguments travel in files, never in the trigger command line** — quoting through the
scheduler's own `/tr` is where that always breaks. Validate the argument file before
dispatching: a probe handed its own script name as its first argument read it as a duration,
ran for zero seconds and looked like a run that did nothing.
- **The wrapper must create no window.** A `.cmd` action puts a console on the interactive
desktop, in front of the target; an inactive window ignores hover, and the first hover-driven
step then silently does nothing (the mechanism and the measurement are in `SKILL.md`, §the
non-interactive-session bullet).

## The package interface the dispatcher drives

Capabilities are commands, not scripts, so a clone carries them and a test can drive them:

| command | job | writes to the app? |
|---|---|---|
| `status` | the read-only inventory as one record: class, handle, rect, maximized, screen, panel and control counts, strip view, overlay, layout note, cursor, foreground | no |
| `channel <n>` | verify the selector, writing it only when it differs, and report the mode the surface it built implies | only if it differs |
| `preflight [--seconds n]` | one whole cycle with nothing stored: record, hold, stop, read the store dialog, **cancel** it | presses the surface |
| `compile <definition>` | the pre-run check: read the instrument's own fixed facts off the dialog and the screen, compare them with the definition, and report each fact's value **and its source** | reads the app only; stores nothing |
| `point <name> --seconds n` | one stored item | stores a file |
| `sweep --seconds n --rungs k,k` | the runner's own path, one JSONL record per item | stores files |
| `decode <file> --channel n` | a stored file's own operation words — the certificate, and it needs no application | no |

- The dispatcher takes **either** an installed command (`-m <module> …`, run from the repository
root) **or** a probe file (run from its own directory). Accepting `-m` and its module as two
arguments, not one quoted string, is what makes the documented invocation typeable.
- **Exit codes are part of the interface** — 0 ok, 1 a refused item or a failed verification, 2
usage or configuration — because a caller polling the log only has the code and the text. Keep
usage errors (a missing store directory, a missing axis) exit 2, and refuse rather than default:
the cycle *asserts* the store directory and writes it when it differs, so a guessed path points
the instrument's output somewhere nobody asked for.
- **The pre-run check refuses in one message, and the application is left untouched.** A driver refusal
  is caught at the CLI boundary and printed as one `<prog>: <message>` line — never a traceback, and
  never by re-parenting the exception class to make an existing `except` match, because the hierarchy is
  what distinguishes a refused point from a broken instrument. A fact whose reader exists but whose read
  failed refuses the run rather than falling back to the declared value, a disagreement names both sides,
  and every fact that disagreed is named in one message, because the comparison is cheap and the
  instrument is in front of the operator (`docs/dop3000/acquisition-campaign-compilation-plan.md` §9.2,
  §13, §15).
- **State the foreground precondition in the operator sequence.** A dispatched command cannot take the
  foreground away from the user, and every hover-driven step needs the application in front: the guard
  refuses *before* the hover, so the operator brings the window forward and the same command is re-run,
  with nothing opened and nothing stranded.
- `--json` prints the report model and nothing else on stdout: notes go to stderr, or they corrupt
the machine-readable output.
- Verify the interface live from the clone, not only in tests: `status` should reproduce the
inventory the machine showed before (counts, layout note, foreground), and `preflight` should end
on a clean view having stored nothing.

## The staged bring-up, with pass criteria

Each stage separates a different cause of failure. Do not skip to the end because the first
stage passed.

| stage | how | pass criterion |
|---|---|---|
| 0. the logic arrived intact | the project's test suite, headless | the automation suites pass with no application present — this is the only stage that can tell "the code is wrong here" from "this machine is different" |
| 1. inventory | `acquire status` | the window is found by **class**, the strip reports a view, and the layout note is **clean**. Any other note names the problem (a dialog left open, an item in a mode that removes a panel, a different build's layout) |
| 2. selector read | `acquire channel <n>` | the selector verifies, the panel counts are reported, the run's notes name the mode it found, and the cursor is where it started |
| 3. the cycle, storing nothing | `acquire preflight` | open the store dialog, read its fields, cancel it, end on a clean view. Nothing written |
| 4. one item | `acquire point <name> --seconds <n>` | the artefact appears in the directory the application is configured to write, and reading it back yields the application's own values, which should agree with its display |
| 5. a multi-item run | `acquire sweep --seconds <n> --rungs <k,k>` | every item `ok`, and the log carrying one record per item — request, read-back, artefact, decoded values, failure field |
| 5b. the pre-run check | `acquire compile --definition <file>` | exit 0 with the reading's facts agreeing with the declaration and the facts no surface states marked `unreadable` rather than silently declared, and **nothing written**; then prove the refusal in both directions — a definition with one changed fact exits 2 naming it against the instrument's own value, and a fact changed *in the application* makes the unmodified definition refuse. Restore it and the same check is accepted |

Stage 3 is the operator's own sequence without the risk; stage 4 is the first write to the
instrument; stage 5 is the loop end to end. A stage-1 failure is configuration; a stage-4
failure is almost always the target directory or the selector; a stage-5 failure carries its
reason per item. Stage 5b is the gate the writing stages sit behind: it costs no slot and
no stored file, and it is where a wrong declaration is caught before a recording is spent.
Stated once more in the shorter form it takes where nothing gates the writing stages:
reason per item.

## The measurements folded in from the first machine

List them as a table rather than abstracting them away. The user position that makes this the
right shape: they are not asking for a driver that fits machines nobody can test, they are ask-
ing to know *what to look at* when the new one behaves differently, and they will fix it there.
The edit per machine is deliberate and explicit; a fallback that silently accepts a state the
run was not designed for is worse than a refusal.

| folded-in measurement | where it lives | if it does not hold |
|---|---|---|
| the clean layout's control and panel counts | the driver's constants | read the counts off stage 1 and set them, or bring the item's mode/state to match — a mode that removes a panel changes the count by design |
| the main window's **class name** | the driver's `MAIN_CLASS` | if a new build renames it, nothing resolves: set it for that install |
| a dialog's geometry and its button band | driver predicates | dialogs are found structurally, so a changed dialog refuses loudly instead of pressing the wrong thing — verify, do not widen blindly |
| the application's **own working directory** | asserted before every commit | set it in the application, or pass the same path; a mismatch must refuse the item, not scatter files |
| first-run configuration values (sound speed, depths, rates) | the sweep definition | these are *that* instrument's settings, not the library's: read them off the application or the first stored artefact and use those |
| an absolute screen coordinate inside a predicate | the overlay finder | expect the fallback path (appearance diff) to carry it — see the proxy test below |

## Deliberately open, and say so

- **How much of a long item is actually kept.** A fixed delay between start and stop is not the
same as the stored window; measure it at the production length with a two-duration linearity run
(`references/artefact-decoding.md` §5) and carry the achieved duration on the item's record.
- **Simulation versus real hardware**, and **a different application version** — untested until
tested; say which was assumed.
- **The axes the driver cannot write** because they are dialog-only fields. Name them in the
bring-up so a failed attempt reads as "not implemented" rather than "this machine is broken".

## The proxy test: get most of the answer before the machine exists

A window's **maximized** state is what makes absolute screen coordinates look stable — the frame
is the screen, so every earlier hover point happens to hold. Un-maximize the target and move it,
and every such coordinate shifts at once (part of it may even go off-screen).

Run stage 1 and stage 3 against the moved window:

- **structural rules should survive** — class + containing panel + order, containers found by
what they own, dialogs identified by content, the store band index from the right;
- **any predicate stated in screen coordinates is now on its fallback**, which is the point: you
learn whether the fallback carries it without waiting for a new install, a second monitor or a
different DPI.

Restore the window afterwards (same size, maximized, position) and re-read the inventory to
confirm you left the operator's screen as you found it.

## Verify the toolchain from the clone, not only from the machine it was built on

After moving the live path into the repository, re-point the scheduled task at the repository's
own wrapper and run stages 1-3 **through the clone**. Passing lint and compiling the moved files
is not a run: `py_compile` accepts a `NameError` that fires only at execution (a path rewrite
using `Path` before the module's own import), so run each probe once from its new location and
fix the import order, not the symptom. Expect the same numbers the original copy produced.
