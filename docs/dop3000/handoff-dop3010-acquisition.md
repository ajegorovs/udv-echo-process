# DOP3010 acquisition — handoff (2026-09-17)

State of the automation work: what is proven, what is broken, and exactly what to do
next. Written for a fresh session starting in this repository.

## 1. Where the work lives

- `C:\Repos\udv-echo-process`, branch **`feat/dop3010-acquisition`**, pushed to origin;
  `master` untouched at `ef8b0e5`. Working tree clean.
- Commits, newest first: `1395887` (ClipCursor + real-click entry), `33e1e0c` (geometry
  entry matching), `c9b2e55` (real-hover channel selection), `6659412` (posted held
  press for the menubar), `f1068c9` (sweep runner), `4f4221e` (lint), `92eb024`
  (acquire core, docs, BDD pin).
- Package `src/udv_echo_process/acquire/`: `plan.py`, `config.py`, `log.py`,
  `actuator.py` (the pure Protocol), `driver.py` (`Win32Actuator`), `runner.py`
  (`SweepRunner`), `verify.py` (artifact verification).
- Tests ~1,420 pass; the acquire set ~300; ruff clean. Pre-existing failures unrelated
  to this work: `tests/test_storage_npy.py` (~35) and
  `test_io_bdd_artifacts.py::test_canonical_depth_ids_round_trip_through_storage` —
  `PermissionError` from `storage/npy.py::_fsync_dir` (`os.open` on a directory).
- Campaign repo (not git): `C:\Repos\dop-control` — `recon/` holds the probes that are
  the source of truth for the application's behaviour, `docs/16-record-strip-automation.md`
  the verified UI rule set, `recon/out/` the captures and JSONL logs.

## 2. The immediate task — port the menu interaction VERBATIM

Source of truth: `C:\Repos\dop-control\recon\41_burst_sampling_volume.py`,
`open_operating_parameters()` (lines 109–135), plus `udop_roles.py` (`click_hold`,
`resolve`, `children`, `combo_state`, `text_of`). This code opened the menu, selected
`Operating parameters`, read the dialog, changed a combo, and accepted — repeatedly.

**The entry press is `click_hold(entry_hwnd)`** — a *posted* held press
(`WM_LBUTTONDOWN` with `MK_LBUTTON`, ~180 ms, `WM_LBUTTONUP`) on the entry's **own
handle**. It is *not* a cursor move followed by a click. A recent fix replaced it with a
real click; the menu then opened and the entry was never pressed, which is the whole
failure. Restore the posted held press as the primary gesture.

**Dialog identification is structural**: a panel with `>= 15 children` or containing a
`TSp_Browse`, and width `> 400`. The driver currently requires the presence of the
channel combo, which is stricter than the evidence and can reject a correctly opened
dialog.

**Bottom buttons** sorted by `left`: leftmost is `Cancel`, rightmost is `Accept`. Never
press Accept on a dialog that has not been identified.

**The hover**: `SetCursorPos(204, 40)` → 0.3 s → `mouse_event(MOUSEEVENTF_MOVE, 2, 0, 0, 0)`
→ 1.0 s. The driver derives the point from a resolved rect instead — pin it to the
measured point, or require the overlay to *become visible* as proof the hover worked.

**Precondition before pressing any entry**: the overlay panel must report
`IsWindowVisible == True`. The panel `(169, 55, 401, 250)` is **pre-created in the control
tree with `visible = False`**. Presence is not visibility; a rule that accepts presence
will click real coordinates into empty screen, which is what happened.

**No window activation anywhere.** The overlay opens on an unfocused application and it is
sticky — it survives activation and needs an explicit close.

## 3. Verified facts (measured on the instrument, not inferred)

- **Word map** — uint32 little-endian, 256 words per channel, stride 1024, channel 1 at
  byte offset 548 (`548 + (c-1)*1024`): 2 = depth mm; 5 = PRF µs; 8 = burst; **10 =
  0-based resolution rung index, `resolution_mm = (idx+1) * c / 12000`**; 13 = gates;
  14 = emissions; 19 = sound speed m/s; 27 = sampling-volume index (identity unresolved
  against the manual's bandwidth); 11/12 = auto flags (both 1).
- **Depth law** — `depth = first_gate + gates * resolution`, stored word is the *floor* of
  it (100.06 → 100, 99.8 → 99). The first gate is dialog-only and not stored.
- **Write order matters** — resolution first, then gates; writing gates first clamps them
  (words 11/12 set auto resolution and auto gate count).
- **The chain works** — record → stop → store → confirmed file, unattended, strip back to
  `ready/3` (three buttons, no slider) every time. Three points recorded by the driver:
  805 / 403 / 201 gates at 100 mm, c = 1460.
- **Block hygiene** — a point recorded into a buffer still holding ~6,000 stale profiles
  was stored as **8,272,897 B** where ~90 KB was expected, looked like a valid `.BDD`, and
  the status bar showed large **negative** time-between-profile values. One
  `Clear and restart` before the point produced a clean 87,281 B (64 profiles). Reset
  before every independent point.
- **Size signature** — roughly 1.7 bytes per gate-profile at the calibration
  configuration; use it as a *gross* factor check (the contamination cases were 10× and
  60×), never as a precise expectation. For reference, `466 B/profile + 1.20 B/gate` fits
  three clean points within 0.2%, but the profile count depends on the achieved period.
- **Profile period** — the manual gives `T_profile ≈ T_tran + T_prf * (16 + N_PRF)`, and
  word 17 = 16 in every file, which corroborates it. Compute the period from the point's
  parameters; log the achieved value once per configuration as a certificate. Note: the
  ported doc's §8 says "measure the period; do not trust the formula" — that line is the
  assistant's over-caution and should be corrected.
- **One channel is the scope.** Everything measured on channel 1, c = 1460. The channel is
  a single knob: `UDV_CHANNEL` → `ChannelSetting` (default 1, range 1–10).
- **Store dialog** — its `Working directory` field decides where points land (currently
  `C:\REPOS\DOP-CONTROL\RECON\OUT\CAPTURE`); it persists. Names must be unique: a repeat
  raises a `No`/`Yes` overwrite panel, and the correct response is the **left** button
  (`No`). The dialog also sets `ClipCursor`.
- **ClipCursor** — this application clips the cursor while its popups are open, and a
  clipped `SetCursorPos` is clamped *silently*; that pinned the operator's cursor into the
  dropdown's corner and made the entry loop's re-hover impossible. Read the clip, release
  it with `ClipCursor(NULL)` when the target lies outside, never restore the cursor into a
  clip, and name the clip rectangle rather than blaming a locked desktop.
- **The menubar needs real input; nothing else does.** Posted messages never open the
  menubar (a posted move and a posted held press both failed), while the record strip,
  the sidebar numerics, the popup entries and the dialogs all accept posted messages.
- **Caption-less widgets** — the entire UI is caption-less `TSp_*` controls. Never match by
  title. The menu entries are `TSp_Button`s inside the overlay, ordered by screen `top`
  (first = `Operating parameters`, second = `Default parameters`, then a third and fourth).
- **The artifact is the authority** — verify every point from the stored bytes
  (`verify.py`: gates exact, resolution rung inverted from the request, depth within
  tolerance), never from the request, the driver's intent, or a control's text.

## 4. Open / unproven

- No live run has yet pressed a popup entry with the posted held press on a **visible**
  menu. That is the next live test, and it should be the first one after the port.
- The real-click entry fallback, the "settle before the click" theory and the
  "posted press needs a settle" theory are all moot once the verbatim port is in.
- `layout_note()` returns `None` for the clean screen (a documented sentinel) and a summary
  otherwise; `StripState.slider_max` is always `None` (the slider's range is never read).
- The at-cap warning's text was never captured (the state clears before it can be read).
  With independent points and a 10,000-profile cap it is off the critical path.
- A point's duration is nominal, not measured — the driver waits out the recording window
  blind, so the real length is uncertified (a few percent at 10–20 s points).

## 5. Running a live point

```
cd C:/Repos/udv-echo-process
uv run --with pywin32 python C:/Repos/dop-control/recon/45_live_sweep_runner.py
```

Preconditions: UDOP 6.07.4 simulator (`TMain_Scr`) in the `ready/3` view, **no popup
open** (a lingering one makes the layout guard refuse: `49 visible controls in 5 panels`
against the clean `43 in 4`), and a clean buffer. `pywin32` is declared as the optional
`acquire` extra.

Diagnostics that answered the hard questions:
`recon/46_menubar_probe.py` reports, before and after a hover, whether the app is focused,
the dropdown panel's rect and `IsWindowVisible`, and the desktop pixels inside it. It also
snapshots the driver's own prelude (its strip press and its sidebar write) — that is what
proved the prelude is not the cause and that focus is irrelevant.

## 6. Rules that were expensive to learn

- **Refuse, don't press.** On an unrecognised state or panel, stop the run. The circuit
  breaker did this five times live and never once sent a stray press.
- **One change at a time**, and verify from the artifact rather than from the code, the
  request or the control tree.
- **Never `WM_CLOSE` a popup** — it wedges the modal menu loop until the application is
  restarted.
- **Trust the operator's eyes over telemetry.** Twice the control tree reported the popup
  open while the screen showed nothing; both times the eye was right.
- **Port proven code verbatim before re-deriving it.** The working menu interaction existed
  in `recon/41` all along; three fix cycles went into reinventing it.

## 7. Delegation notes

Subagents deliver when given one file (or a tight, disjoint file set), no exploration, a
blueprint, the exact test command, and the report format. An open-ended ask burns the
output budget and writes nothing (one did: 545 s, twelve API calls, no file). State
explicitly whether they may run ruff — one task was told not to, and the lint landed red.
Two siblings editing one file produce flaky runs; keep the file sets disjoint.
