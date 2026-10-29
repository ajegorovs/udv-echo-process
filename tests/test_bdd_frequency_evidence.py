"""Saved configuration coexistence is distinct from acquired stream frequencies."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from udv_echo_process.io.dop.bdd import read

ROOT = Path(__file__).resolve().parents[1]


def test_committed_dual_quantity_fixture_has_unused_ten_mhz_configuration():
    path = ROOT / "data/dual-profile-mux/4MHz.BDD"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "7270664aa1793a51b8959da35f617368b21e705407e4c85c76f3636c5864d825"
    )
    # Documented binary layout: per-channel 256-word blocks at 548, frequency word 0.
    configured = {
        channel: struct.unpack_from("<i", raw, 548 + (channel - 1) * 1024)[0]
        for channel in (1, 2, 3, 4, 10)
    }
    assert configured == {1: 4000, 2: 4000, 3: 4000, 4: 4000, 10: 10000}
    bundle = read(path)
    assert len(bundle.recording.streams) == 8
    acquired = {
        (stream.acquisition.channel.device_channel, stream.config.source_freq_khz)
        for stream in bundle.recording.streams
    }
    assert acquired == {(1, 4000), (2, 4000), (3, 4000), (4, 4000)}
    assert 10 not in {channel for channel, frequency in acquired}
