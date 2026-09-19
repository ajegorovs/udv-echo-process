# Live acceptance rehearsal for a GUI-only instrument

Three things that each cost a round trip or a wrong claim when a pre-run check has to be proved against a
real application (measured on a 32-bit Delphi/VCL instrument driven over Win32).

## A background or scheduled process cannot take the foreground

A probe dispatched through a scheduler or service runs outside the interactive session, so
`SetForegroundWindow` is refused by Windows' foreground lock — measured: it returned `0` three times even
from the interactive session, and the driver's own guard reported `is_foreground: False` with another
window (a `Windows.UI.CoreWindow`, empty title) holding focus. Design for it:

- make the driver **refuse before the gesture** when the target window is not foreground — a hover into an
  inactive window is worse than no hover, because the app ignores the first mouse event and a popup can be
  left open;
- state the precondition in the operator sequence, and ask the operator to click the window: focussing it
  is not available to a process the user is not interacting with;
- report a precondition refusal as exactly that. "Stopped at a precondition, nothing opened, nothing
  stranded" and "stopped mid-gesture" have very different consequences for the operator's machine.

## Prove the refusal in both directions

A check that refuses a mismatch before doing real work needs two negative cases, not one:

- **declaration side** — a copy of the input (definition/config) with one field changed must refuse and
  name that field with both sides;
- **instrument side** — the operator changes one readable setting by hand (agree the restore step at the
  same time) and the unmodified input must refuse, naming the instrument's own value;
- then the good case must be **accepted** on the restored state, and the run must leave the instrument's
  output directory untouched.

Do it on the application rather than only in fakes: a fake agrees with whatever the driver was told, so it
cannot show that the *reading* detects a real difference. Watch for a "one step up" control that skips a
value (a burst combo took `4` to `6`), and record the value actually read, not the one requested.

## The evidence has to reach the reviewer

Tracebacks, probe logs and stored files live on the operator's machine, and a reviewer cannot open them.
Commit the record (the plan's own section, the operator sequence) or post the transcribed sequence as a
comment on the change — and quote the exact refusal text, because that is the part a reviewer can check.

## Read the run's output directory out of the application, never infer it from disk

The run asserts that the store directory it is handed is the application's own working directory, so a
wrong value refuses the point — fail-safe, but not a way to *find* the right value. Do not conclude it
from the artefacts already on the machine: the newest files are regularly weeks old, in a directory the
operator has since migrated away from, and a folder of correctly named files is the most convincing wrong
answer available. Ask the operator to read the path from the application's own settings dialog, or read it
through the driver, and pass exactly that.

## A refusal must arrive as a message, not a stack trace

An acceptance run is *supposed* to refuse; the next thing to check is **how**. An environmental
precondition that surfaces as a traceback with exit 1 tells the operator nothing and is unusable in an
unattended pass — measured, and its usual cause is that the tool boundary catches a narrower error type
than the layer below raises, so the driver's own refusals (foreground, a dialog that will not open, a
control that is not there) bypass every handler. Check the form of each refusal in the rehearsal: one
line naming the precondition, plus the documented exit code, is part of the deliverable rather than
polish. Treat "it refused, but as a crash" as its own defect to close before a batch is trusted, and note
that a refusal naming *both sides* of a disagreement is what makes the same evidence reviewable off the
machine.

## The log running for tens of seconds must be dispatched, not waited on

A multi-point pass outruns a foreground command timeout, so it belongs in a tracked background process
whose own log is polled to completion — never a fixed sleep after the start, which makes the operator's
timer show your wait instead of the run.

## The last case is the resume, and it must prove before it skips

Ending a rehearsal at "the run completed" leaves the restart path unproven on a real record. Re-run the
same job against the completed log and assert the **shape** of the outcome: the points report as already
recorded, none is re-run, and the identity is validated *before* any point leaves the todo set. A resume
that skips first and checks afterwards passes this case too, which is why the assertion is on the
ordering — and the inverse, the same job against a changed configuration, must refuse rather than skip.
