# BDD dual-quantity streams (velocity + echo in one block)

**Task plan.** Written 2026-10-21. **State:** ready for review.

## Destination

**Purpose.** The DOP3010 stores one profile of *each* quantity in the same
measurement block when its monitor shows two plots. Until now the reader kept a
block's velocity profile and silently dropped its echo profile, so a two-plot
capture read as velocity-only data. This effort makes both quantities readable
without widening the pinned artifact model.

**Observable outcome / acceptance criteria.**

1. Reading `data/dual-profile-mux/4MHz.BDD` yields **eight** streams — four
   channels × two quantities — each with its own content-addressed artifact id.
   Evidence: `tests/test_io_bdd_artifacts.py::test_dual_profile_file_yields_one_stream_per_channel_and_quantity`.
2. For one channel the velocity and echo streams carry **identical** `time_s`
   and `gate_depths_mm` arrays, so the two plots are row-aligned.
   Evidence: `…::test_dual_profile_streams_share_the_timestamp_and_gate_axis`.
3. The echo series is decoded on the module scale (0…2048, `module`) and is
   statistically independent of the velocity series. Evidence:
   `…::test_dual_profile_echo_is_decoded_on_the_module_scale`,
   `…::test_dual_profile_quantities_are_not_a_rescaling_of_each_other`.
4. `select_channel` refuses to guess which quantity of a dual-quantity channel
   was meant, and `replace_channel` replaces only the matching stream. Evidence:
   `tests/test_recording.py::test_select_channel_requires_the_quantity_when_a_channel_carries_two`,
   `…::test_replace_channel_targets_the_matching_quantity_stream`.
5. A dual-quantity bundle round-trips through `.npy` storage with two artifact
   directories per channel. Evidence:
   `tests/test_storage_npy.py::test_round_trip_dual_quantity_bdd_fixture`.
6. Every pre-existing fixture reads exactly as before (single-quantity files
   keep one stream per channel). Evidence: the full suite, plus
   `…::test_every_discovered_fixture_round_trips_to_a_closed_bundle`.

**Non-goals.** No change to §6.6's five `ChannelArtifact` fields; no combined
"velocity+echo" artifact; no visualisation change (`viz.py` already groups by
`(channel, measurement type)`); no `round_id`/`visit_id` fabrication from the
multiplexer block word; no new analysis module. The single-stream-only analysis
helpers (`analysis/_native_grid.py`, `reference_repeat.py`,
`sparse_inventory.py`) keep refusing a dual-quantity file with their existing
"expected exactly one channel stream" error — adapting them is separate work.

**Authorization boundaries.** Owner asked for double-plot reading on 2026-10-21
and proposed a fresh worktree + PR. That grant covers the reader, model
invariant, provenance bridges, tests, fixture and documentation. The owner then
explicitly approved the `AGENTS.md` short-form edit (protected
agent-instruction file) on 2026-10-21. Merging and publication beyond the draft
PR are still **not** covered.

**Baseline.** Branch `feat/bdd-dual-profile`, worktree seeded from
`origin/master` = `d276d6e` (2026-10-21). Full suite on that revision, agent
session 0: **25 failed, 3572 passed, 22 skipped** — 6 failures in
`test_acquire_{dialog,driver,live}.py` (no interactive desktop in this session),
16 in `test_notebook_spectral_preview.py`, 2 in `test_screening_terms.py`, 1 in
`test_sparse_signal_report_verifier.py`. Those 25 are the comparison baseline;
any new failure is attributable to this change.

## Patterns this work follows

`docs/signal-model-rework-plan.md` governs the model (§6.6 artifacts, §6.7
recording). The §6.7 amendment recorded there is the authority for
`(channel, quantity)` stream identity; `AGENTS.md` and
`docs/pipeline-architecture.md` carry the short form.

Measured facts a fresh reader would otherwise re-derive:

- The capture holds 2004 measurement blocks: per channel one depth-only block
  (two depth pseudo-profiles) plus 500 signal blocks, each signal block carrying
  profile type 0 (velocity, `int8`) **and** type 1 (echo, `uint8`), 42 gates.
- Both profiles of a block end at the same footer timestamp (`meas_end-12`), so
  one block is one simultaneous sample of both quantities.
- Multiplexer: op word 51 = 50 profiles per channel per visit, word 53 = 10
  blocks. The per-channel timeline is ten 50-sample runs at 71.4 ms separated by
  ~10.8 s holes (the other three channels' visits); the echo stream carries the
  same holes because it shares the block timestamps.
- Echo decodes as `counts × module_scale / 255` with `module_scale = 2048`;
  velocity as mm/s from words 0, 5, 15, 19, 20, 22.

## Current checkpoint

**Established.** Implemented and verified on `feat/bdd-dual-profile`:

- `Recording` keys streams by `(device_channel, descriptor.quantity)`;
  `acquisition_order` stays a permutation over channels.
- `select_channel(..., quantity=)` requires the quantity when a channel carries
  two streams; `replace_channel` disambiguates the same way and still replaces a
  lone stream whatever its quantity (a transform may change it).
- The reader accumulates per quantity, with per-quantity timestamps, and emits
  velocity before echo per channel.
- Fixture `data/dual-profile-mux/4MHz.BDD` (244,028 B, SHA-256
  `7270664aa1793a51b8959da35f617368b21e705407e4c85c76f3636c5864d825`) with a
  measured-structure README.
- `udv-inspect` lists both quantities and no longer prints `Max velocity` on an
  echo stream.
- `AGENTS.md`'s short-form "Data" bullet names the dual-quantity case and the
  `(channel, quantity)` stream identity (owner approved 2026-10-21).

**Not established.** Nothing is merged or released. Whether the sibling
`10MHz.BDD` capture and the second recording set behave identically is measured
only by the same raw scan, not by a committed fixture.

**Relevant revision / artifacts / live target.** Branch `feat/bdd-dual-profile`
in worktree `udv-double-plot`; no live instrument involved.

**Working state / recovery needs.** Clean tree after the documentation commit;
`.venv` is a fresh `uv sync --frozen --extra dev`.

## Remaining work

**Selected next.** Owner review of the draft PR — in particular the §6.7
amendment, since it is a model-schema decision rather than a bug fix.

**Blocked.** Nothing. (The `AGENTS.md` short-form update needed the owner's
explicit approval for a protected agent-instruction file; granted 2026-10-21 and
landed in this PR.)

**Unselected findings / open questions.**

- The single-stream-only analysis helpers refuse a dual-quantity file. Decide
  whether they should accept a quantity argument or keep refusing.
- `10MHz.BDD` and recording set `002` show the same structure in a raw scan but
  are not committed; add a fixture only if a divergence appears.
- The multiplexer block word still carries no round/visit identity (unchanged);
  the ten visits are visible only through the timestamps.

**Deferred or excluded.** A per-quantity `ChannelConfig` split: the echo stream
carries the channel's velocity configuration because the file stores one
op-parameter block per channel, not per quantity.

## Decisions and evidence

- **2026-10-21 — two streams, not one wider artifact.** §6.6 pins
  `ChannelArtifact` at five fields and `viz.py` already groups panels by
  `(channel, measurement type)`, so a dual-quantity channel is two streams. The
  alternative (adding a second payload field) would break the field-count
  contract for every consumer.
- **2026-10-21 — per-quantity timestamps in the reader.** One shared time vector
  would misalign a series that was absent from some blocks; the previous code
  had that latent bug on any mixed file.
- **2026-10-21 — refusal over default.** `select_channel` without a quantity on a
  dual-quantity channel raises and names both quantities: returning the first
  match would hand back the wrong physics under the right channel number.

## Next session

**Objective.** Agreed: close the review loop on the draft PR.

**First action.** Read the reviewer's findings and answer them commit by commit.

**Stopping condition.** PR merged, or the amendment rejected and the reader
change reverted with the fixture removed.
