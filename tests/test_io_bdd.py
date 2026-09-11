"""IO-layer tests for the content-sniffing discovery/dispatch layer.

Numeric decode coverage for the DOP3000 `.BDD` reader moved to
`tests/test_io_bdd_artifacts.py` in Phase 6 (the reader now returns an
`ArtifactBundle`). This file keeps the layer-boundary coverage that is *not*
about decoded numbers:

- the magic-byte sniffer (including the unsupported DOP2000 marker);
- content-based discovery, so a `.BDD` misnamed `.jpg` is still found;
- `load()` dispatch to a reader and its rejection of unrecognised bytes.

Committed fixtures in `data/`:
- `data/echo/*.BDD` — single-channel echo (DOP3000, `BINUDOPV4.03.4`).
- `data/4-sensor-velocity/*.BDD` — 4-channel velocity, multiplexed.
- `data/echo-4-sensors-2x2/20260723_143754.jpg` — a genuine `.BDD` misnamed
  `.jpg` (magic still matches), exercising content-based discovery.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.io import discover_data_files, load
from udv_echo_process.io.dop.bdd import read, sniff_bdd
from udv_echo_process.provenance import ArtifactBundle

DATA = Path("data")
ECHO = DATA / "echo"
VEL = DATA / "4-sensor-velocity"


# ── sniff ──────────────────────────────────────────────────────────────


class TestSniff:
    def test_recognizes_binudopv(self):
        assert sniff_bdd(b"BINUDOPV4.03.4\r\n...") is True

    def test_rejects_foreign_bytes(self):
        assert sniff_bdd(b"\x89PNG\r\n\x1a\n") is False

    def test_rejects_dop2000(self):
        with pytest.raises(ValueError):
            sniff_bdd(b"BINWDOPV...")


# ── content-based discovery ────────────────────────────────────────────


class TestDiscover:
    def test_finds_bdd_despite_jpg_extension(self):
        """A .BDD misnamed .jpg must still be discovered (content, not ext)."""
        files = discover_data_files(DATA)
        assert any(p.suffix.lower() == ".jpg" for p in files)

    def test_finds_many_bdd(self):
        files = discover_data_files(DATA)
        assert any(p.suffix.lower() == ".bdd" for p in files)


# ── load() dispatch ────────────────────────────────────────────────────


class TestLoad:
    def test_read_returns_an_artifact_bundle(self):
        bundle = read(ECHO / "200.BDD")
        assert isinstance(bundle, ArtifactBundle)

    def test_load_dispatches_to_the_bdd_reader(self):
        bundle = load(VEL / "200RPM.BDD")
        assert isinstance(bundle, ArtifactBundle)
        assert len(bundle.recording.streams) == 4

    def test_load_rejects_unknown(self, tmp_path):
        bad = tmp_path / "x.bin"
        bad.write_bytes(b"not a udv file at all")
        with pytest.raises(ValueError):
            load(bad)
