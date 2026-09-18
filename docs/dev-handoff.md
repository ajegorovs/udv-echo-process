# Working on this repository from a machine that cannot reach the instrument

**Audience:** an agent (or a person) with a clone of this repository on a machine that has no
Windows, no UDOP application and no DOP3010 — expected to be a Linux box doing a refactor.
Nothing here needs access to the machine the measurements were taken on, and nothing here
should be taken as a substitute for reading the four documents in §1.

**The one-sentence version:** two thirds of this repository is ordinary cross-platform Python
that you can run, test and refactor freely; one third drives a caption-less 32-bit Windows
application over Win32 messages, and every claim it makes was *measured* on that application.
That third is testable here (against fakes, which is how it is developed) but **not
verifiable** here: a gesture, a geometry, a painted caption or the application's acceptance of a
write can only be re-established on the instrument. §4 is the protocol for getting those
re-established without touching this repository's dependencies.

---

## 1. Read these, in this order

| # | document | what it gives you |
|---|---|---|
| 1 | [`AGENTS.md`](../AGENTS.md) | the conventions, the module map, the instrument invariants ("do not re-derive"), the vision/crops route, the scope boundaries |
| 2 | [`docs/architecture.md`](architecture.md) | the current system map, the dependency boundaries, the public entry points, **where a change belongs**, and the quality gates |
| 3 | [`docs/dop3000/acquisition-review-and-verdict.md`](dop3000/acquisition-review-and-verdict.md) | the **work list**: an external review, every finding verified with `file:line` evidence, what was over-stated, the per-phase decision, and the landed first slice |
| 4 | [`docs/dop3000/live-bringup.md`](dop3000/live-bringup.md) | what to do on a machine that *does* have the instrument — incl. the staged bring-up and the measured numbers to compare against |

Then, as the work touches them: `docs/dop3000/udop-automation.md` (how a point is set,
recorded, stored and validated, with the failure modes), `docs/dop3000/handoff-dop3010-acquisition.md`
(the measurement session's own record, with the rules that were expensive to learn),
`docs/agenda.md` (the live backlog), `docs/udv-analysis-reference.md` (the preservation
register for the retiring `udv-analysis` package — §2 explains its 22 skipped tests).

## 2. Step 0 — a clone, and the gates that run anywhere

```bash
uv sync --extra dev            # tests, ruff — cross-platform
uv sync --extra acquire --extra dev   # + pillow (pywin32 is marker-gated to Windows)
uv run --extra dev pytest      # 1701 passed, 22 skipped, ~70 s on the first machine
uv run --extra dev ruff check src tests tools
```

- Python **3.14** (`.python-version`), package manager **uv** only.
- **There is no CI.** The gates are the ones above, run locally. Nothing else will catch a
  regression, so run them before you claim a change is done.
- **`ruff format --check` is not clean on the committed tree** (18 files under `src/` and
  `tests/` would be reformatted — pre-existing, measured on `master`). Format a file you
  are already editing; do not reformat the tree inside a refactor.
- `ruff check` passing includes `.agents/` being excluded (skills are prose) and
  `tools/` **not** being excluded (tool code is code) — keep `tools/**` ruff-clean.
- **All 22 skips are the same reason**, and it is not the instrument:
  `UDV_ANALYSIS_ARCHIVE is unset (archived baseline unavailable)` — the archived baselines of
  the retiring external `udv-analysis` package. Set that env var to the extracted baseline
  pack to run them; otherwise they mean nothing about this machine's capabilities.

## 3. The platform and commitment split

| runs anywhere (and is how the code is developed) | needs Windows + UDOP running | needs the instrument's desktop (session 1) | needs the DOP3010 hardware |
|---|---|---|---|
| `models/ process/ provenance/ storage/ io/ parser.py viz.py analysis/ cli.py` | `acquire/driver.py` attaching to the process | taking a screenshot (`dialog_shot.py`, `main_geometry.py`'s PNG) | the sweep's scientific validity: what the instrument actually measured |
| `acquire/{actuator,plan,config,campaign,runner,verify,snapshot,log,live}.py` — logic, planning, the cycle, verification, the JSONL log | reading a control over Win32 messages | any gesture: the menubar hover, a strip press, a dialog open | the trigger/auto-record behaviour, the FTDI failure modes |
| the fakes and the whole `tests/` suite | writing a control and reading it back | cursor position, foreground window, `ClipCursor` | timing/duration linearity under real acquisition |

Structural facts that make this work, and that a refactor must preserve:

- **`acquire/driver.py` is the only module allowed to touch `pywin32`**, it imports lazily
  inside functions, and `acquire/__init__.py` stays import-safe everywhere — so importing the
  package, planning a campaign and running the CLI all work on Linux.
- **The doubles are the contract**: `tests/test_acquire_driver.py` (`FakeUdopApp`,
  `FakeUdopWindow`, `FakeActuator`, `FakeDriver`), `tests/test_acquire_actuator.py`,
  `tests/test_acquire_runner.py` (`ScriptedBlock`, `ScriptedReader`, `FakeVerification`,
  `ScriptedVerifier`), `tests/test_acquire_dialog.py` (`FakeDialogDriver`). A change to the
  driver that the doubles cannot express is a change to the interface — decide that
  deliberately, not by accident.
- **Committed evidence you can read and re-check without the instrument:** 66 recordings under
  `data/` (23 `.BDD`, 43 `.ADD`), three measured control-tree fixtures under
  `tests/data/` (each names the probe that produced it), and the 45 UI crops under
  `docs/dop3000/ui-crops/` with a checker (`tools/ui/crop_index.py`) that proves the index
  describes the files.

**What you cannot establish here, at all:** that a gesture works, that a rect is where the
code assumes, what a caption says (read it from a crop, or ask for a capture), that the
application *accepted* a write, how long anything takes, or whether a stored file is
scientifically valid. Do not infer any of these from code, from the docs alone, or from a
green test suite.

## 4. The handoff protocol — asking the machine that has the instrument

Work in two halves: **refactor here, verify there.** A request that will be executed on the
instrument side should arrive as one of these, and should state its own expectation so a
divergence is a named line rather than a coordinate lost in a wall of output:

| you want | ask for | it lands in |
|---|---|---|
| the current state of the screen, read-only | `./tools/live/dispatch.sh -m udv_echo_process.cli acquire status` | the dispatcher log |
| a read of the main window's tree/geometry (presses nothing) | `PROBE_TIMEOUT_S=240 ./tools/live/dispatch.sh main_geometry.py` | `outputs/live/task-main_geometry.py.log` |
| what the `Operating parameters` dialog holds | `… dispatch.sh dialog_fields.py` | the log (JSON) |
| **pixels** — a caption, a label, a value | `PROBE_TIMEOUT_S=150 … dispatch.sh dialog_shot.py` | `outputs/live/dialog.png` + `dialog-full.png`, plus `image_stats`/`non_blank` |
| proof that a write is accepted | `… dispatch.sh dialog_write.py write --burst 4` (then read back) | the log, with the round trip |
| one stored point / a sweep / a campaign | `UDV_STORE_DIR=<the app's dir> ./tools/live/dispatch.sh -m udv_echo_process.cli acquire point <name> --seconds 12` (or `sweep`/`campaign`) | `outputs/live/*.jsonl` + a stored `.BDD` |

Rules that are not negotiable on the instrument side (they are all measured, see `AGENTS.md`
§"Driving the instrument"): a probe is dispatched by its **bare file name**; nothing presses a
control that changes state without a documented way back; a dialog is closed with its **left**
button and read back from a **reopened** dialog; a gesture that opens a popup owns its cleanup
in a `finally`; edits land in `outputs/live/`, never in tracked files.

**A capture is data, not a claim.** When a PNG comes back, quote it: magnify the region
(`tools/ui/magnify.py composite`) and compare glyphs (`… glyphs`) before a digit is believed,
and cite the crop or the capture by name. A screenshot the author did not read is not evidence.

## 5. Do not "fix" these

- **Two reviewed `.BDD` limits** — the header version string and the 512-byte comment are
  decoded and then dropped (`ChannelArtifact`/`Recording` are pinned at five fields each by
  §6.6/§6.7 of the decode review), and the binary format proves no round/visit identity, so
  `synchronize()` is exercised on synthetic topology only. Both are deliberate; changing them
  needs new decoded evidence, not a refactor.
- **`acquire/driver.py` is ~3.5 k lines and is not the place to start.** The review's Phase 3
  (split it) is *deferred behind a trigger* — split when a second sweep parameter forces a real
  edit, and then as a mechanical move. Every gesture in that file was paid for on live hardware;
  a "cleaner" rewrite of a gesture cannot be verified without it.
- **Phase 4 (an explicit state machine) is deferred in code**, accepted as documentation and
  tests over the existing `StripView`/overlay logic.
- **The block cap** (`Do not keep in a block more profiles than`) lives in the application's
  `Record settings` surface, which this automation has never opened. It is carried as a declared
  value, marked `unreadable` — not as a law. Do not derive a planning limit from it.
- **The `Tgc [dB]` row, the monitor, the two caption-less buttons below the strip and the title
  bar have no crop**, and the index says so: an absent row is a limit of the *set*, not evidence
  about the application. `docs/dop3000/ui-element-index.md` lists every such gap.
- **The optical/camera modules and the `udv-project`/`udv-mixvel` CLIs were removed** as
  out-of-scope; the canonical copy is the sibling `python-image-processing-notebooks` repo. Do
  not port them back.

## 6. Known-stale or known-incomplete (fix deliberately, not by surprise)

| what | state |
|---|---|
| `tools/live/README.md` §"What is still a probe" | listed one probe while six were tracked — corrected; trust the directory listing over prose |
| the old crop generator + its ledger | lived in the git-ignored `outputs/` and had fallen behind (30 rows against 45 crops), so the committed index could not be regenerated from it. Replaced by the checker `tools/ui/crop_index.py`, which verifies the index against the PNGs instead |
| no committed sample job log | `acquire report --log FILE` has no committed fixture to read; a single-point `*.jsonl` (with its `*.manifest.json`) committed under `tests/data/` would make the job-tracking path exercisable off-instrument |
| `ruff format --check` | 18 files under `src/`/`tests/` are unformatted on `master` (see §2) |
| the profile-global `windows-gui-automation` skill | **at its size limit**: 100,831 characters against Hermes's 100,000 cap, so `skill_manage` refuses every patch to it. It cannot grow, and it still carries instrument-specific material that now belongs in the repo overlay (`.agents/skills/udop-acquisition/`). A new lesson learned here goes to the overlay; the global needs splitting into `references/` before it can be maintained again |
| `models/signal.py` | ~540 lines, the module to watch before adding another nesting level (per `AGENTS.md`) |

## 7. How a change is reviewed here

The reviewer is external and has **no access to this machine, its temp files or its
git-ignored outputs**. So:

- one commit per finding or request, with the evidence *in the commit* — a number, a fixture,
  a log line, a `file:line`;
- never cite a local path or an `outputs/` artefact as the evidence for a claim: commit the
  fixture or quote the measurement in the message;
- a claim about the instrument that the reviewer cannot re-derive belongs in
  `docs/dop3000/` with its provenance stated (`measured` / `operator-reported` /
  `mechanism-level` — the vocabulary the existing docs use), not only in a code comment;
- `docs/agenda.md` is the live backlog; superseded detail is folded into its authority
  document and `docs/agenda-history.md`, not left as a transcript.
