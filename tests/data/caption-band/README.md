# Caption-band fixtures — one measured Channels popup caption line

Portable, deidentified crops of the operator-opened **Channels** popup, used as the oracle for
`udv_echo_process.acquire.caption_band`. Each file is the popup's **own rectangle** only: no
desktop, no window frame or title, no path, no handle, no machine or operator identity. They are
the measured input to every recognition test, and nothing here was rendered or guessed.

| file | size | role | operator's statement (the label) | numbers beside it | sha256 (12) |
|---|---|---|---|---|---|
| `train-channel-1.png` | 393x426 | train | channel 1 | 50 Profiles / 2.01 s, repeat 1 | `62651d2fcdef` |
| `train-channel-2.png` | 393x426 | train | channel 2 | 50 / 2.01 | `809d569c5ea1` |
| `train-channel-10.png` | 393x426 | train | channel 10 | 1 / 0.07 | `78f3ecab0e8f` |
| `train-channel-2-frame-2.png` | 393x426 | train (second frame) | channel 2 | 50 / 2.01 | `809d569c5ea1` |
| `holdout-channel-1-return.png` | 393x426 | **holdout** | channel 1 (return visit) | 50 / 2.01 | `bcdffda9899b` |

**How they were taken.** One live sitting, by the operator switching the popup's top-row circles
in place — no recording, no amount written, no mode change — with the capture path that this
repository already had (`channels-read --capture-dir`). Each file is one saved ROI frame.

**What the holdout is.** `holdout-channel-1-return.png` is a *separate visit* to channel 1 after
the operator had moved away and back. It is never a template source; `tests/test_acquire_caption_band.py`
asserts that and then reads it, which is the only evidence in this set that the recogniser
generalises to a new photograph rather than to a remembered file.

**What the labels are.** The operator's statement of which channel was selected — recorded so a
measured glyph becomes a *named* digit template. The label selects templates; it is never the
recogniser's answer, and no test feeds a label into a reading.

**Known traps.** The two frame-2 files are byte-identical to their frame 1, so the set proves
stability only, not atomic stillness. Two colour values exist in the band (pure white ink on the
popup's flat `(64,72,112)`), and the glyph shapes are the application's own font at the measured
scale only: no other DPI, theme, font or popup size is covered by these files.
