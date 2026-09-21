# Sweep automation: measured lessons from the DOP3010/UDOP rig

Hard-won rules from driving a 32-bit Delphi/VCL instrument app (UDOP 6.07.4) through
parameter sweeps. Most generalise to any posted-message UI automation; the specifics
are marked.

> **Authority (frozen 2026-09-18).** The repository's current model of these surfaces is
> `docs/dop3000/acquisition-ui-model.md`; its mechanism rules are `docs/dop3000/udop-automation.md`.
> This file is the skill's prose copy of the measured lessons — where the two disagree, the
> repository documents decide, and the fix belongs there.

## Driving the UI

- **The menu bar opens on a real cursor hover; the entry takes a posted held press.** The parameters
  menu ignores posted messages entirely (a posted move and a posted held press both opened nothing), so
  hover the button with `SetCursorPos` onto its centre plus one short relative `mouse_event` move, then
  poll for the popup. The entry underneath is taken with the ordinary widget recipe — posted
  `WM_LBUTTONDOWN` (hold ~180 ms) `WM_LBUTTONUP` on the entry's **own handle** — which needs no cursor.
  Do not "improve" that into a real click on the entry: the re-derived click opened no dialog.
- **Order popup entries by screen `top`, never by enumeration order** (enumeration order once pressed a
  destructive entry), and **never match one by title** — these widgets carry no captions. The overlay
  holds five entries (screen tops 61, 95, 130, 165, 205 inside the panel at `(169, 55, 401, 250)`); the
  first is `Operating parameters`, the second resets parameters.
- **A pre-created overlay is not an open overlay.** That panel exists in the child tree from startup
  with `IsWindowVisible` false. Enforce `IsWindowVisible` on the overlay *and* the entry before
  pressing, and name the hidden panel in the refusal — a tree hit alone is a hypothesis
  (`custom-menus-clipcursor-and-real-input.md`).
- **Bind by role + geometry (class name + rect), never by control id or caption.** These
  widgets (`TSp_*`) carry no captions, so captions cannot be used to identify them.
- **A combo can step *past* a value — select by value, never by counting steps.** Measured: one step up
  from burst length `4` landed on `6`, so a writer that presses the arrow n times writes a value nobody
  asked for. Read the options back, select the index whose text states the value, and read the field back
  to confirm what it now states (plan §18.2).
- **Find a combo by its item list, not by its nesting.** Burst length and sampling volume are nested
  inside `TSp_Value_Button` children, but the measurement channel is the dialog's **header** field — a
  direct child of the panel (`Operating parameters for channel [n ▼]`, measured at `(1083, 373)`, items
  `1`…`10`). Recurse the dialog's whole subtree and identify each combo by what it lists; requiring a
  value-button wrapper around one particular combo rejects the correctly opened dialog. A lookalike
  combo listing the same items exists in the sidebar, so scope the search to the dialog panel.
- **Identify a dialog structurally, then tell two dialogs apart by content.** A dialog is a panel that
  is not the sidebar column, is wider than 400 px and is full of controls of its own (≥15 direct
  children, a `TSp_Browse`, or input controls); the operating dialog measures `627x384` at
  `(655, 364)` with seven `TSp_Value_Button` fields. Answer an unidentified dialog with its **leftmost**
  bottom button (`Cancel`/`No`); the rightmost is `Accept`/`Do store`.
- **Write order matters where the app has auto-flags.** With automatic resolution/gate-count
  selection active, writing the gate count first gets silently clamped (805 -> 474); resolution *then*
  gates took the full 805. Write the resolution first, then the gate count, then verify — the order is
  part of the recipe, not an implementation detail, so pin it as data (`PARAMETER_WRITE_ORDER` in
  `acquire/actuator.py`; `udop-automation.md` §3).
- **Verify against the artifact, never against the control's text.** A control can read back
  what you wrote while the application keeps something else; re-open a dialog to re-read it,
  and treat the stored file as the authority for what a point actually was.
- **Never dismiss a popup with `WM_CLOSE`** - it wedges the modal menu loop until restart.
  Posted clicks ignore modality, which is what makes them usable at all; a modal dialog that
  sets `ClipCursor` still blocks real injected input.
- **The main-window record strip takes the posted *held* press** (Record / Stop / Clear). A/B on all
  three of its buttons: the held posted press started the recording and the Stop reached the store
  view, while `SetCursorPos` + `mouse_event` down/up did nothing on any of them. The strip, the popup
  entries and the dialog buttons are message surfaces; only the menubar hover needs the real cursor.
- **A channel has its own mode, and the mode changes the whole screen.** Selecting a channel inside
  the operating dialog re-renders the panel for *that* channel's mode: an assisted channel shows
  `Assisted mode parameters for channel [n]` with no sidebar parameter column (21 visible controls in
  3 panels against 43 in 4 with the column), so a parameter write there has no target and a *sweep*
  must be refused while a single store is still valid. Read the mode from the panel the application
  built (the assisted one carries a slider the others do not), record it on the run, refuse by naming
  the mode rather than the missing field, and never leave the mode yourself — its toggle is the
  application's Preference menu, which the automation deliberately does not drive.

## Reading the instrument's own fixed facts (the pre-run check)

The `Operating parameters` dialog's value table is caption-less, so a field's identity is its
**(column, row)** — never a control id (ids change on every launch) and never a caption (there are none).
Measured: three columns of `TSp_Value_Button` widgets, 15 value fields in a `4 / 6 / 5` rows-per-column
shape, the columns being the x bands of the value edits' left edges (786 / 987 / 1187 px in a `627x384`
dialog at `655,364`). A row's value is the **combo** when the row offers one and the `TSp_Edit` beside it
otherwise: at `burst = 4` that row states a combo `'4'` *and* an edit `'89'`, and the 89 is the
sampling-volume read-out, not the parameter.

- **Gate the shape, then the anchors.** A reading that does not build the measured `4 / 6 / 5` shape is
  refused unread, and seven of the dialog's fields are facts the measurement screen also states — all
  seven must read the same text on both surfaces before a dialog-only fact is believed. Refuse
  *uncheckable* (nothing states the anchor on both surfaces) separately from *disagreement*. The binding
  is pinned to a committed capture of the measured tree (`tests/data/udop-parameters-dialog-tree.json`)
  and as data in `DIALOG_FIELD_ORDER` / `DIALOG_ANCHORS` / `DIALOG_COLUMN_ROWS` (`acquire/actuator.py`),
  so a re-layout refuses rather than putting a different value at the same position (plan §14).
- **Five of the six fixed facts are read live; the sixth has no path.** `prf_us '212'`,
  `emissions_per_profile '150'`, `burst_length '4'`, `sound_speed_ms '1460'`, `first_gate_mm '2'` read
  from the dialog; `max_profiles_per_block` stays `unreadable` with its reason, because the cap is an
  application Preference and the surface holding it has no established path. Nothing invents a read for
  it — the compile carries it as unproven (plan §14, §18).
- **The cap, and the surface it lives on, are not the store path.** The **Store** dialog commits a
  recording and its geometry is known and exercised; `Do not keep in a block more profiles than` lives in
  **`Record settings`**, which this automation has never read or written — no path to it has been
  exercised. The cap is **not a planning limit** (the UI accepted 1,000,000) but the value *in force*
  does truncate a long point's start, so a plan resting on the cap rests on a value nothing here has
  established. Name which surface a note means (`udop-automation.md` §7, §12.4; plan §18).
- **A supported read that failed is a refusal, not a fall back to the declaration** (plan §9.2). And the
  reader polls for the **filled** table: a freshly started application builds it empty on the first open
  (measured 2 stating controls, then 22) and reports which of the two states it saw, because an empty
  field is not a value.

---

## Reading a stored point (DOP3010 `.BDD`)

- uint32 little-endian words, 256 per channel, stride 1024 bytes; channel 1 starts at byte
  offset 548. Word *i* of channel *c* is at `548 + (c-1)*1024 + i*4`.
- w2 = depth in mm, w5 = PRF in microseconds, w8 = burst length, w10 = 0-based resolution
  index (`resolution_mm = (w10+1) * sound_speed_ms / 12000`), w13 = gate count,
  w14 = emissions per profile, w19 = sound speed in m/s. w17 is the constant 16. **w1 = `assisted
  Mode`** (1 while that channel is in assisted mode), per the manual's parameter table.
- **Read a word at the channel's own offset, and never conclude uniformity from one block.** The
  parameter area holds one block per channel, so word *i* read at channel 1 for a point measured on
  channel 2 is channel 1's field and not the point's — read that way the mode flag looked like "0 in
  every file" while the blocks actually read channel 1 = 0 and channels 2-4 = 1. Print the value for
  every channel before calling it uniform, and corroborate a pattern against a channel you have not
  touched (the mode read off the files predicted an untouched channel's panel correctly).
- **Each stored profile record carries its channel.** Two files written from one configuration on
  different channels differ at byte 881 and then at every 1024-byte stride (values 1 and 2) and
  nowhere else — the cheap proof that a channel write reached the data and not just the label.
- **Sweep rungs are 1-based multipliers**, not indices: k = 1, 2, 4 give 0.1217 / 0.2433 /
  0.4867 mm at c = 1460. Word 10 stores `k - 1`.
- The stored depth word is the application's own derivation and deviates a few tenths of a
  mm from `first_gate + gates * resolution` - there is no consistent floor-or-round rule, so
  compare depth with a tolerance (~1.5 mm) rather than exactly.
- **Profile period is computable, not measured:** `T_profile ~= T_tran + T_prf * (16 + N_PRF)`
  where `N_PRF` is emissions per profile and 16 is the fixed constant stored as word 17.
  Deviations are expected (mechanics, electrical, a non-real-time OS), so log the achieved
  value as a per-point certificate instead of calibrating models from it. Measured at the production
  length (12 s, 797 gates at 0.122 mm) the law predicts 366 profiles (33 ms) while the block holds
  228 — an achieved period of **53 ms**, and **46 ms** at 399 gates: the transfer term is ~1.6x larger
  than the law and it scales with the gate count, as that term implies. So compute the achieved period
  from the artefact itself (size / (gates x 1.7 B) -> profile count; period = T / profiles; flag a wrap
  when the count reaches the block cap) and carry it on the point's record — a point log whose timing
  field is empty cannot support a duration-based comparison, and the size guard's factor-of-2 tolerance
  is loose enough to pass a 0.62 ratio.

## Run safety

- **Clear the block before every independent point.** A stale buffer (a few thousand leftover
  profiles from an earlier failed cycle) produced a stored file ~60x the expected size that
  still decoded as a perfectly valid point - silent corruption. Clearing first produced the
  correct size. On screen the symptom is large **negative** `Time between profile` values.
- **Keep the size guard gross, not precise.** Contamination shows up as 10x/60x. Profile
  timing carries OS and mechanical jitter, so a tight expectation is illusory: ~1.7 bytes per
  gate-profile with a factor of 2-4 is the right shape. Note the ratio drifts with gate count
  (a per-profile overhead plus ~1.2 bytes per gate), so do not enforce it across rungs.
- **Circuit breaker: stop the run when the application's state is unverified** - unknown
  overlay, unstartable strip, a cycle that raised - instead of cascading the failure across
  every remaining point. Refuse and stop on an unrecognised panel; never press a button on a
  popup you cannot identify.
- **A file that exists but disagrees with the requested parameters must not be logged as
  valid.** Existence is not success.
- **Failures before a file exists are run-level (abort); failures after it exists are
  point-level (continue).** That boundary is the clean place to hang the circuit breaker.
- **Make channels/retargeting a single knob** (config field + environment variable, one
  source of truth). A rig that needs code edits in several places to change channel will be
  retargeted wrongly at some point.

## Process

- A live run that must be observed: run it in the **foreground** (timeout <= 600 s) so the
  result returns inline. Above that cap it is promoted to a background process and the result
  arrives later as a notification.
- Probe the live app read-only first (current state, panels, view) and build every object
  before touching the GUI, so a construction error costs nothing. An introspection failure
  must print and exit, not half-run.
- **A whole point and a short sweep run through the runner's own API, not through hand-rolled presses:**
  plan -> write -> read-back -> record -> store -> decode -> verify -> one JSONL entry per point, whose
  fields (`sweep_id`, `key`, `name`, `status`, `requested`, `readback_*`, `file_path`, sizes, `decoded`,
  `failure`) are the minimum a tracking layer needs — build the campaign on that record rather than
  inventing a second one. A definition is JSON (`job`, `channel`, `duration_s`, `name_prefix`, `prf_us`,
  `emissions_per_profile`, `burst_length`, `store_dir`, `max_profiles_per_block`, and `points` of
  `{label, parameters}`), driven by `acquire plan|campaign|report`. Resume keys on
  `<name_prefix>-<label>` read out of the record's own name, so the record gains no field; the stored
  file is `<prefix>-<label>-<stamp>`, which means a label that repeats the prefix doubles it. Only the
  sidebar parameters (resolution, gate count) vary per point — sound speed, first gate and burst length
  are dialog-only, so a point may repeat them but never change them, and the plan refuses such a change
  by name. The block cap is an input to state, not a law to assert on: the 12 s production point keeps
  ~8.4 s, so the plan reports that per point and runs. Measured: 6/6 points in 104 s at 12 s each on
  channel 1, one parameters dialog for the whole job, `--resume` skipping every recorded point in 4 s
  (gates 797/399/199/100 read back as planned). An assisted-mode channel has no sidebar at all, so a
  campaign must target a manual one. One axis per sweep, and keep the window, channel and duration fixed across
  the points, so the two files differ only in the parameter under study.
- Print the field names and types of an unfamiliar model when construction fails; it turns a
  guess into one exact fix (`rungs` being 1-based multipliers was found this way).

## A pass: several jobs, one order (the run plan) — measured 2026-09-20

- **A definition is one job; a *pass* is several.** `acquire/run_plan.py` + a run plan JSON
  (`examples/sparse-mixer-first-pass/`) carry the three things no single definition can: the job
  order, each job's **within-job** control placement, and a cross-job record. A job's own log must be
  its own file (`<store_dir>/<plan>-<job>.jsonl`): `run_campaign` proves a resume against the manifest
  beside the log it was given, so nine jobs sharing one log is a resume that refuses.
- **Run-wide values are per job, and set by hand between jobs.** `burst_length`,
  `emissions_per_profile` and `prf_us` live on `CampaignDefinition` and a point cannot write them, so a
  pass of nine jobs is nine manual setups and the automation must move nothing. The sheet
  (`run-plan --sheet`) states what to set; the *compile* is what refuses a wrong setup.
- **Stored names carry the job:** a pass declares one root and each job stores under `<root>-<job>`, so
  labels may repeat from job to job (`ctrl-begin`, `cc1`) without colliding on identity.
- **Two acceptance gaps to know before trusting a run-wide value.** `burst_length`, `prf_us`,
  `sound_speed_ms` and `first_gate_mm` are read and a disagreement refuses; **`emissions_per_profile`
  is advisory by default** (`verify.py::ADVISORY_COVARIATES`) — it is read from the column, but a
  disagreement is recorded and the run proceeds. That default exists because a definition's value for
  word 14 used to be *derived* rather than asked for; when the value **is** the axis under study, a run
  must **raise** it instead of living with the default: `campaign.run_campaign(strict_facts=...)` (and
  `compile_campaign`, `SweepRunner(strict_covariates=...)`, `verify_stored_point(strict_covariates=...)`
  for the halves) refuses a disagreement before the first recording *and* compares the stored file's
  own word into the verdict, so the dataset is self-validating. A run plan declares it as
  `strict_facts`, and only facts a stored file carries a word for can be raised — the block cap cannot.
- **The block cap is an input, declared.** No reader here reaches the application preference, so a plan
  declares its own requirement: the achieved profile period is never shorter than `emissions × PRF`, so
  `ceil(T / (emissions × PRF))` over the pass cannot wrap any point whatever the transfer term is. The
  plan's own per-point note fires instead when a *point* overrides `duration_s` past the cap.
- **Declared ≠ retained.** A large accepted value for *"Do not keep in a block more profiles than"* did
  not stop an observed block from ending far short of it, so **effective retention is only ever measured
  from the stored file** — profile count, first→last stamp span, achieved period — never read off the
  preference and never inferred from a clean decode. At a 12 s window this is the first thing to check on
  a new configuration, and a short file stops the run rather than being noted.
- **Declare the frame from the files, and expect the dialog to speak last.** The reference frame is
  derived from the committed recordings' own decoded values (c = 1480 m/s, and a first gate of
  10.1626666667 ± 0.5 mm implied by their depth words), and the pre-run check compares numerically
  against the *dialog's* text with zero tolerance: a last-decimal difference refuses before any
  recording, and the dialog's rendering is then the number that belongs in the plan. Measured
  2026-09-20: this dialog states the first gate as an **integer** — `10.163` commits as `10`, and commas
  are rejected outright — so the declared frame is `10.0 mm`, and the derived window is what `word 2`
  confirms after the recording. Before treating the difference as a scientific loss, check whether the
  rungs in play can see it at all: at 1.85, 0.617 and 2.96 mm the two candidates round to the same
  stored depth word.
