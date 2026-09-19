# Evidence discipline — what counts as a claim, and how it is checked

## Evidence discipline

Label every load-bearing claim **verified** (measured on this machine), **from documentation**,
or **unverified** — and grep the source text for the exact phrase a proposal attributes to it
before designing around it. Documentation and marketing pages describe features that the
shipped build, or the licence, does not have; option/licence state is visible inside the app
itself and is worth checking early, because it can invalidate a whole design. When a claim from
the manual cannot be found in the manual, say so plainly rather than repeating it.

**Treat a handover document as a hypothesis set, not as measurements.** Long-running automation work
spans sessions, and the handoff carries the previous session's *beliefs* alongside its facts: before
porting anything from it, re-open the capture, log or probe script each load-bearing claim cites and
check the claim against it — including the capture code's own filters and truncation limits, which
silently bound what the artifact can show. The reference script that performed the interaction is the
strongest evidence in the pack; a summary of it is not. **Its highest-value content is usually the write knowledge, not the readings:**
which recipe commits a field on which surface, which gesture the app ignores, what order fields must be
written in, and which control a value's companion sits in. Mine that first — re-deriving a gesture the
archive already proved is the expensive path. Its *values* are configuration-specific and must not be
carried over (bind by geometry, never by value; select a combo by its painted text, never by index, because
the list is physics-driven and the accepted index moves with the other settings), while its *recipes*
transfer to any instance of the same build.

**A *review* of the subsystem is the same kind of document, written from further away.** Before
adopting any of it, check each claim against the code it cites and against the repository's own
memory — a finding already recorded in a commit message, a handoff section or the live agenda is
still actionable but is not a discovery, and a review presenting it as one is a signal to check the
rest harder (grepping its own numbers is the cheapest such test: a quantitative example that appears
nowhere in the repository is a transcription error). Reconcile the proposals with this repository's
standing gates as well — *port the proven gesture verbatim, never re-derive it*, *add decoded
artefact metadata only with byte-level evidence, a destination field, propagation rules and storage
implications*. An outside review has not read those rules, and a proposal that collides with one is
acceptable only in the gated form. The full adjudication procedure is the `review-adjudication` skill.

**An empty result from a filtered query is not evidence until the filter is proven.** Before
believing "nothing matched", run the same command against something known to qualify: a
time-filtered file search that silently ignored its own age flag reported "no file was written" for
a file that was sitting on disk, and that wrong conclusion stood until the flag was tested against a
known-recent file. Validate the predicate first, then trust the absence.

**A capture is a query too — read the capture code before trusting a count.** A dump that slices its
list (`kids[:12]`) or filters by class turns a partial inventory into a definitive-looking one:
measured, a dialog's direct-child count read as an exact 12 from a capture that truncated at 12, while
the rule consuming it required `>= 15`, which pointed at the wrong conclusion about which predicate the
working reference used. Re-enumerate fresh and unfiltered before asserting a count or the absence of a
control class, and treat a suspiciously round number as the truncation limit.

The same trap in UI form, and it cost three live probes: asking a **stock-Windows question of a
custom-widget app** answers "nothing there" no matter what is on screen. Looking for the native menu
class to decide whether a menu had opened returned nothing at every position and for every gesture,
because these toolkits draw their own menus — the entries are ordinary child widgets inside a panel the
app positions itself. Probe with the **same detector the driver uses** (the app's own control tree,
filtered the way the map filters it), and read agreement between several independent probes as a reason
to doubt the detector, not to believe the result. A negative from an API the app never used is not
evidence of absence; it is an untested measure.

**A positive from the control tree is not evidence of what is on screen either.** A custom
overlay's panel and all four of its entry rectangles were present in the child tree — geometry
identical to the real dropdown — while the operator saw no menu at all, on a freshly restarted app.
A driver that trusts the tree then clicks real coordinates on an invisible surface and reports "the
popup did not react", which is indistinguishable from a gesture the app ignores. Require a
*displayed* signal (a pixel change, or the operator's confirmation) before treating an overlay as
open, and hold "the tree says it is there" as a hypothesis. **The usual mechanism is a pre-created
panel:** these toolkits construct the overlay at startup with `WS_VISIBLE` off and show it on the
opening gesture, so "present in the tree" and "open on screen" are different states that a
presence-based rule conflates. Make visibility an **enforced precondition**, not a diagnostic — the
overlay poll returns only panels reporting `IsWindowVisible`, the press refuses an overlay or entry
that does not, and the refusal names the hidden panel and its rectangle so the log records which state
was actually seen.

**The other direction of that rule is a free read path: a panel the app keeps hidden still states its
values.** These toolkits build each mode's panel at startup and show one of them, so a value the
dialogs only reveal behind a menubar hover can already be read where it sits. Measured: the manual
panel held the sound speed, the first gate and the burst length, while its assisted counterpart one
panel over in the same tree held that mode's own numbers (1460 m/s against 1500). Dump the **whole**
child tree, hidden controls included, and read the values with `WM_GETTEXT` *before* designing any
gesture-based read path — it costs no cursor, no dialog and no state change. **Scope every such read
to the panel it belongs to:** the same class of widget in the sibling panel is the same *shape* with
another mode's values, so "the edit holding this text" is not an identity, and a value-only match will
happily read the wrong mode's configuration.

**A row that offers a choice states its value in the *combo*, and the control beside it is a derived
read-out.** At `burst = 4` the row holds a `TComboBox` `'4'`, its inner `'4'`, and a `TSp_Edit`
`'89'` — and the 89 is the sampling volume the manual says this window displays (0.876 mm at
1460 m/s), not the burst. Bind the combo when a row has one, and prove the rule survives
**enumeration order**: controls come back in creation order, so the test has to try both orders or a
"first control in the row" implementation passes for the wrong reason (it did, on the first pass).

**A field bound by position is evidence only if a second surface confirms the position.** Seven of
this dialog's fields are facts the measurement screen also states; requiring all seven to read the
same text on both surfaces is what makes the binding trustworthy rather than habitual — a
re-laid-out dialog (another software package installed, a field built or not built) would put a
*different* value in the same `(column, row)` while still reading exactly like a value, and a pre-run
check would then hand the run a plausible wrong fact. Refuse as **uncheckable** (nothing states the
anchor on both surfaces) separately from **disagreement** (the two surfaces state different text):
they are different faults, and a run record has to be able to tell which one happened. Gate the
**shape** before the anchors: a positionally-read surface is read only when it builds the measured shape
(here: three columns of value fields in a `4 / 6 / 5` row-per-column layout), and one that does not is
refused unread. A field's identity on such a surface *is* its `(column, row)` — never a control id (ids
change on every launch) and never a caption (these carry none) — so the shape is the only thing saying
the position you are about to believe is the position it was measured at. Pin all of it to a committed
capture of the measured tree (`tests/data/udop-parameters-dialog-tree.json`) so a re-layout refuses
rather than mis-reads: `DIALOG_FIELD_ORDER` / `DIALOG_ANCHORS` / `DIALOG_COLUMN_ROWS` in
`src/udv_echo_process/acquire/actuator.py` are the binding as data (plan §14).

**A freshly started application builds its value table empty the first time a dialog is opened, and
states it on the next open.** Measured: the first open after a restart read 2 stating controls where
the second read 22. Poll for the fill with a bounded timeout, and record *which* state was seen — an
empty field is not a value, and a read that took the first empty answer as the answer would report
three unreadable facts about an instrument that states them perfectly well. The same is true of the
pre-created panels: a long-running instance has them populated, a fresh one does not.

**Ask the operator what they saw; their report outranks your telemetry.** Run the live slot step by
step: one change per run, and never two unverified gestures in the same attempt, so the outcome can
be attributed to something. Measured twice in one session, the operator's eyes resolved what the
APIs could not — the cursor visibly locked inside a popup, and a menu that never appeared — and each
observation redirected the diagnosis immediately. State which single hypothesis the next run tests
before you start it.

- **The agent's own shell may be in a non-interactive session — prove that before believing the
driver is broken.** A Hermes terminal tool can run in **session 0** on a *service* window station
(`Service-0x0-…$`) while the target app runs in **session 1** on `WinSta0`. From there
`GetForegroundWindow()` returns 0, `GetCursorPos()` fails with **1459** (*"requires an interactive
window station"*), `EnumWindows` sees no application window and `FindWindow("TMain_Scr")` returns 0 — so
the driver refuses with *"no visible <MainClass> window"*, which reads exactly like a broken binding and
is not one. Check the caller first (`ProcessIdToSessionId(os.getpid())` plus the window station name via
`GetUserObjectInformationW(GetProcessWindowStation(), 2, …)`), print the comparison against the target
process's session, and only then look at the driver. To run the driver anyway, register a **scheduled
task with the caller's own principal**: `schtasks /create /tn X /tr "C:\...\run.cmd" /sc once /st 23:59
/ru INTERACTIVE /it /f` then `schtasks /run /tn X` executes in the logged-on interactive session, needs
no password, and its redirected stdout is a log the agent can read. Have the wrapper read the probe name
and its arguments from small **files** instead of passing them through `/tr` — quoting arguments through
`schtasks` is where that always breaks. **The action must create no window at all:** a `.cmd`
action gives the task a *console window on the interactive desktop, in front of the target app*,
and that alone can break the driver — measured: with the console up, the app reported
`is_foreground=False` and a menubar **hover opened nothing**, because an inactive window ignores
hover (its first mouse event only activates it). Use a GUI-subsystem host (`pythonw.exe`) that
runs the child with `CREATE_NO_WINDOW`, and verify afterwards that the foreground window is not
a console. **Screenshots are then the only route to painted labels:**
caption-less widgets answer `GetWindowText` with `""`, so `PIL.ImageGrab` executed *inside that session*
(plus 2x crops of the popup/dialog) is how the *text* on a button is read, and the difference between
`Cancel` and the indicator next to it is pixels, not window text. State the plan's expected geometry in
the probe and print an `EXPECTED vs OBSERVED` table, so a divergence is a named line rather than a
coordinate lost in a wall of output.
**Read a digit off a capture only after zooming to full resolution, and take values from the API read, not
from the image.** A whole-dialog capture is small enough that a glyph clipped by its field's frame misreads:
measured, `0.68` in a 627x384 dialog read as `3.168` to *two independent* vision passes — a subagent's and
the coordinator's — which then agreed on the wrong number. **Agreement between two readings of the same lossy
source is not corroboration**; an independent source, or a re-read at full resolution, is. So: labels from
the pixels (nothing else states them), numbers from the API read of the field's own control, and every
disagreement between the two settled by looking again — which is how both errors in that comparison were
caught.
- **Keep ad-hoc probe commands short, and run multi-step ones from a file.** The operator reads the
session's tool calls on screen, and a long single-line `python -c` blob renders as garbled wrapped
JSON in their view — put the probe in a small script the report can name, and keep inline commands
to a few readable lines. Have the probe print **one** JSON object and read it back through a small
summariser that prints only the keys you asked about (extract from the first `{` to the last `}`): a
full control-tree dump flung into the transcript costs the context the next step needs, while the log
file keeps all of it for the questions you did not think to ask.
- **A probe is code under test too: read the helper's real signature and field names before running
  it.** A probe that passed a control and a count in the wrong order reported three buttons that
  "did not respond" — indistinguishable from a widget the app ignores — and guessed model field names
  read as missing values in a decode that was fine. Grep the signature and the field list out of the
  source, run the probe read-only once, and only then believe a negative result. **When a probe has to
  bypass one of the driver's own guards, lift it inside the probe, print that it did, and leave every
  other guard in place** — measured: a store on a mode the driver refuses by design, with the channel
  still written, read back and the artefact still decoded. Never loosen the production path for a
  probe's sake, or the guard stops meaning anything. **Print the dump's own key set, with each key's type,
  before writing a summariser — and never let a missing key answer for the application.** Measured, one
  read's rows sat under `tree`/`tree_with_text` while the similarly-named `tree_controls` held a *count* (an
  int), and the caption sat at `main_window.caption` in a document with no `window` key at all: the first
  raised `TypeError: 'int' object is not iterable`, and the second returned `None` through a helper that
  fell back to a default — which reported "the application records no caption in any mode" when every read
  carried one. A wrong key path is indistinguishable from an absent field unless the reader asserts the
  type or lists the keys first, and the wrong conclusion lands in the report as a fact about the app.
