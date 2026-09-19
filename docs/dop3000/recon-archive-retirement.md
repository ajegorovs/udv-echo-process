# The reconnaissance archive (`dop-control`) is retired — 2026-09-18

**What it was.** `~/Repos/dop-control` — a **scouting repository, never a git repo** — holding the
measurement campaign that produced this project's acquisition knowledge: 58 numbered probes
(`recon/01`…`63`), 16 finding documents (`docs/01`…`16`), a verified control map, a copy of the
DOP3000/DOP3010 manuals, and `recon/out/` with 45 stored `.BDD` captures, 241 screenshots and 35
JSON/JSONL logs.

**Why it is gone.** It was one folder doing three jobs, and all three have been discharged here:

| its job | where it lives now |
|---|---|
| probes that *drive* the instrument | `src/udv_echo_process/acquire/` (capabilities, driven by fakes in tests) — the rule is that a capability belongs in the package, where a double can drive it |
| probes that *measure* the instrument | `tools/live/` (the interactive-session route, `probes/` for what no command covers) |
| the findings | `docs/dop3000/udop-automation.md`, `handoff-dop3010-acquisition.md`, `live-bringup.md`, `parameter-sweep-matrix.md`, the manual corpus, and the skill `.agents/skills/udop-acquisition/` |
| the evidence (captures, logs) | the load-bearing recordings were lifted in as committed fixtures (e.g. `data/dop3010-velocity/sw100-k1-161738.BDD`, byte-identical by md5 to the archive's copy); the rest remains in the archive |
| the UI crops | `docs/dop3000/ui-crops/` + `ui-element-index.md`, with `tools/ui/` as their checker and magnification tool |

**Where it is now.** `~/Repos/_archive/dop-control-20260918.zip` — 18.9 MB, **498 files**, integrity
verified (`unzip -t`: no errors), containing all 45 `.BDD` captures, 241 PNGs, 35 logs, the 58
probes, the 16 documents and the manuals copy. Its bundled `.venv` (83 MB of the 119 MB) was
excluded as recreatable. The archive is a frozen artefact: nothing in this repository depends on it,
and nothing in it should be edited.

**How to read a citation of the form `recon/NN`.** The number names a probe **in that archive**. It
is cited because a rule's evidence is there — `recon/41` for the menubar gesture, `recon/19` for the
strip, `recon/53` for the popup that opens on hover and closes on nothing — not because any code
depends on it. With the folder gone: read the rule where it now lives (the documents and the skill
above); if you need the probe or its output, open the archive. The five capabilities that were
**never** ported are listed below, so a citation of one of those is not a gap to re-derive from a
doc — it is a measurement to re-take on a live machine.

**Never ported** (deliberately, or because a second machine is the right moment):

| in the archive | why it is not here |
|---|---|
| `recon/20_watch_sequence.py` — an operator-driven watcher, sampling the control inventory once a second and capturing on change | the *technique* is in the skill; the runnable watcher was a one-session instrument |
| `recon/12`–`16` menu/dropdown inventories and the menubar probes `recon/46`, `47`, `53` | the *gesture* is ported verbatim into the driver; re-measuring the inventories is a bring-up task (`docs/dop3000/live-bringup.md`) |
| `recon/34`, `35` — the cursor-capture probes | the `ClipCursor` hazard and the behavioural test are documented in the skill; nothing here re-measures it |
| `recon/21`, `42` — the `Record options` / block-cap surface | the cap is carried as a declared value marked `unreadable` (`driver.py`); that surface has never been opened by this automation |
| the crop-generation chain (`build_ui_index.py`, `zoommake.py`, `glyphs.py` and their ledger) | superseded in-repo by `tools/ui/crop_index.py` (a checker that cannot drift from the files) and `tools/ui/magnify.py` |

**The store directory moved with it.** The application's Store dialog had
`Working directory = ~/Repos/dop-control/recon/out/capture` (in Windows form), so the archive was
also the instrument's **drop folder** — which is why it kept growing after the port, its newest
file being from 2026-09-18 11:37. It is now `outputs/live/store/` in this repository (git-ignored,
beside the dispatch logs and captures; the directory has to exist — nothing in this repository
creates it, and nothing else does either). The setting is never assumed: the driver **asserts** the
dialog against the path the caller passes, writes it when it differs and reads it back —
`acquire point|sweep|campaign --store-dir <path>` (which also store a point) or
`acquire preflight --store-dir <path>` (which stores nothing). A mismatch refuses the run instead
of scattering files into whatever directory the application remembered.

**What this retirement did *not* archive.** Nothing: the zip holds every tracked file of the
scouting folder except the excluded virtual environment. If a future task needs the campaign's raw
screenshots, its `.BDD` captures or one of the numbered probes, it is one `unzip` away — and if a
task finds itself unzipping it routinely, that is the signal to lift that piece into the repository
properly (a fixture, a probe, or a doc), not to restore the folder.
